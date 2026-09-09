# Publica a versão local no servidor de produção.
#
# Faz o build do frontend, empacota backend e build, manda por SSH e reinicia o
# serviço. É o mesmo caminho do primeiro deploy, e é de propósito: um roteiro
# que só existe na cabeça de quem subiu a primeira vez não sobrevive à segunda.
#
# O que este script NÃO toca, por serem coisas que se configuram uma vez:
#   - o `.env` do servidor (segredos, inclusive as chaves da Meta);
#   - o Caddyfile e as units do systemd (estão em deploy/, e mudam com
#     `-Infra`);
#   - o banco, que roda noutra máquina.
param(
    # Reenvia Caddyfile e units. Só é preciso quando algum deles muda.
    [switch]$Infra
)

$ErrorActionPreference = "Stop"
$Alvo = "WuzAPI"          # alias no ~/.ssh/config (a máquina da aplicação)
$Raiz = Split-Path $PSScriptRoot -Parent

function Passo($texto) { Write-Host "==> $texto" -ForegroundColor Cyan }

Passo "Build do frontend"
Push-Location (Join-Path $Raiz "frontend")
try {
    # Quem zera o REACT_APP_BACKEND_URL é o `frontend/.env.production`, e não
    # uma variável de ambiente daqui: no PowerShell, `$env:X = ""` **apaga** a
    # variável em vez de defini-la como vazia, e o CRA cairia de volta no
    # `.env` de desenvolvimento, que aponta para http://localhost:8000. Foi
    # exatamente assim que o primeiro build subiu quebrado.
    if (-not (Test-Path ".env.production")) {
        throw "frontend/.env.production nao existe: o build sairia com localhost:8000 cravado"
    }
    npx craco build
    if ($LASTEXITCODE -ne 0) { throw "build do frontend falhou" }

    # Conferência do que realmente foi para o bundle. É barato e pega a classe
    # de erro que só aparece no navegador do cliente, depois do deploy.
    $cravado = Select-String -Path "build\static\js\*.js" -Pattern "localhost:8000" -List -ErrorAction SilentlyContinue
    if ($cravado) {
        throw "o bundle saiu com localhost:8000 dentro; confira frontend/.env.production"
    }
}
finally { Pop-Location }

Passo "Empacotando"
$tmp = $env:TEMP
Push-Location $Raiz
try {
    tar czf "$tmp\zz-backend.tgz" --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.env' --exclude='media' backend
    tar czf "$tmp\zz-frontend.tgz" -C frontend/build .
}
finally { Pop-Location }

Passo "Enviando"
scp -o BatchMode=yes "$tmp\zz-backend.tgz" "$tmp\zz-frontend.tgz" "${Alvo}:/tmp/"
if ($LASTEXITCODE -ne 0) { throw "scp falhou" }

if ($Infra) {
    Passo "Enviando Caddyfile e units"
    scp -o BatchMode=yes `
        (Join-Path $PSScriptRoot "Caddyfile") `
        (Join-Path $PSScriptRoot "zappzen.service") `
        (Join-Path $PSScriptRoot "zappzen-db-tunnel.service") `
        (Join-Path $PSScriptRoot "requirements-prod.txt") `
        "${Alvo}:/tmp/"
    ssh -o BatchMode=yes $Alvo "sudo -n install -m 644 /tmp/zappzen.service /tmp/zappzen-db-tunnel.service /etc/systemd/system/ && sudo -n install -m 644 -o root -g root /tmp/Caddyfile /etc/caddy/Caddyfile && sudo -n systemctl daemon-reload && sudo -n caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 && sudo -n systemctl restart caddy && /opt/zappzen/venv/bin/pip install -q -r /tmp/requirements-prod.txt"
    if ($LASTEXITCODE -ne 0) { throw "atualizacao de infra falhou" }
}

Passo "Instalando e reiniciando"
# O backend é extraído sobre o que está lá e o serviço reinicia: são poucos
# segundos de indisponibilidade. Blue/green não se paga num único processo, e
# a alternativa (dois processos no mesmo banco) reintroduz exatamente a
# duplicação de worker que a unit existe para evitar.
#
# A primeira linha é um comentário de propósito, e `set -e` só vem na segunda:
# se algum dia um BOM voltar a entrar na frente do texto, ele estraga a linha
# em que cai. Estragar um comentário não custa nada; estragar o `set -e` deixa
# o deploy inteiro sem parada de emergência, e foi o que aconteceu em
# 02/09/2026 (`bash: line 1: ﻿set: command not found`, com o BOM invisível na
# mensagem). O erro seguinte, na extração do backend, seguiu adiante como se
# nada fosse, o serviço reiniciou e o script só falhou no fim, apontando para
# o lugar errado.
$remoto = @'
# deploy remoto do zappzen
set -e
cd /opt/zappzen

# Apagar árvore publicada exige devolver o bit de escrita antes: as pastas
# chegam do pacote em `dr-xr-xr-x` (ver a explicação do tar abaixo) e o `rm -rf`
# não remove o conteúdo de uma pasta sem escrita. Isto valia desde sempre e
# passava batido porque o `set -e` estava inerte: o `rm` da árvore anterior
# falhava calado e ela ficava para trás ocupando disco.
apagar() {
    [ -e "$1" ] || return 0
    chmod -R u+w "$1"
    rm -rf "$1"
}

# O backend vai para uma pasta nova e é trocado por `mv`, igual ao frontend, e
# não extraído por cima do que está lá.
#
# O problema que isto conserta: o tar do Windows (bsdtar) deriva o modo das
# pastas do atributo do NTFS e grava `dr-xr-xr-x` no pacote — as pastas do
# backend estão marcadas como somente-leitura pelo OneDrive. O tar do servidor
# **aplica esse modo ao criar a pasta** e só depois escreve o conteúdo dela, de
# onde vem o "Permission denied" em `routes/` e `tests/` enquanto os `.py` da
# raiz entram sem reclamar (a raiz do pacote o tar já mantém aberta).
#
# `--delay-directory-restore` é a opção do GNU tar feita para isso: adia o modo
# das pastas para o fim da extração, então durante ela elas ficam graváveis.
# Trocar a ordem de outra forma não resolve — um `chmod -R u+w` antes da
# extração é desfeito pelo próprio tar no meio do caminho, e extrair numa pasta
# vazia falha igual, o que prova que não era conflito com o arquivo antigo.
#
# A pasta nova + `mv` (em vez de extrair por cima) vem de brinde: a troca fica
# atômica, como a do frontend, e a árvore antiga sobra como caminho de volta.
apagar /opt/zappzen/backend.novo && mkdir -p /opt/zappzen/backend.novo
tar xzf /tmp/zz-backend.tgz -C /opt/zappzen/backend.novo --strip-components=1 --delay-directory-restore
# Agora o tar já terminou e o chmod cola: é preciso para copiar o .env para
# dentro.
chmod -R u+w /opt/zappzen/backend.novo
# O .env é excluído do pacote de propósito (segredos não saem da máquina), então
# ele é o único arquivo que a troca tem de carregar do que já estava lá. Sem
# `cp`, o backend novo sobe sem MONGO_URL e sem as chaves da Meta. O `-p`
# preserva o modo 600. Se não existir, o `set -e` derruba aqui, que é o certo:
# melhor não trocar do que trocar por uma árvore que não sobe.
cp -p /opt/zappzen/backend/.env /opt/zappzen/backend.novo/.env
apagar /opt/zappzen/backend.antigo
mv /opt/zappzen/backend /opt/zappzen/backend.antigo
mv /opt/zappzen/backend.novo /opt/zappzen/backend
# A árvore antiga só é apagada depois do health check, mais abaixo: o processo
# que ainda está no ar tem o CWD nela, e se o novo não subir ela é a volta.

apagar /opt/zappzen/frontend.novo && mkdir -p /opt/zappzen/frontend.novo
tar xzf /tmp/zz-frontend.tgz -C /opt/zappzen/frontend.novo --delay-directory-restore
apagar /opt/zappzen/frontend.antigo
mv /opt/zappzen/frontend /opt/zappzen/frontend.antigo
mv /opt/zappzen/frontend.novo /opt/zappzen/frontend
apagar /opt/zappzen/frontend.antigo
rm -f /tmp/zz-backend.tgz /tmp/zz-frontend.tgz
sudo -n systemctl restart zappzen

# Espera até responder, em vez de um `sleep` fixo: o backend abre o túnel do
# banco e sobe os workers de fundo antes de atender, e cinco segundos nem
# sempre bastam. O `sleep 5` seco fazia o script terminar com erro num deploy
# que tinha dado certo — pior que não conferir, porque manda procurar defeito
# onde não há.
#
# A árvore antiga é apagada só aqui, depois de o backend novo responder: se ele
# não subir, ela é o caminho de volta (`mv backend.antigo backend` e restart).
for i in $(seq 1 20); do
    if curl -sf --max-time 5 http://127.0.0.1:8000/api/health; then
        echo
        apagar /opt/zappzen/backend.antigo
        exit 0
    fi
    sleep 2
done
echo "backend nao respondeu em ~40s; a arvore anterior esta em /opt/zappzen/backend.antigo" >&2
systemctl is-active zappzen
exit 1
'@

# O `sed` tira o BOM que o PowerShell 5.1 põe na frente do texto ao escrever no
# stdin de um programa nativo. Quem codifica ali não é `$OutputEncoding` (essa
# está sem preâmbulo) e sim `[Console]::OutputEncoding`, que neste ambiente é
# UTF-8 **com** BOM — e trocá-la de dentro do script não surte efeito, porque o
# 5.1 já a leu na abertura do processo. Então o conserto é no lado remoto, onde
# funciona independente do que o PowerShell faça.
$remoto | ssh -o BatchMode=yes $Alvo "sed '1s/^\xef\xbb\xbf//' | bash -s"
if ($LASTEXITCODE -ne 0) { throw "deploy remoto falhou (veja: ssh $Alvo journalctl -u zappzen -n 50)" }

Write-Host ""
Write-Host "Publicado: https://zappzen.atendimentoautomatizado.com.br" -ForegroundColor Green
