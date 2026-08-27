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
$remoto = @'
set -e
cd /opt/zappzen
tar xzf /tmp/zz-backend.tgz
rm -rf /opt/zappzen/frontend.novo && mkdir -p /opt/zappzen/frontend.novo
tar xzf /tmp/zz-frontend.tgz -C /opt/zappzen/frontend.novo
rm -rf /opt/zappzen/frontend.antigo
mv /opt/zappzen/frontend /opt/zappzen/frontend.antigo
mv /opt/zappzen/frontend.novo /opt/zappzen/frontend
rm -rf /opt/zappzen/frontend.antigo
rm -f /tmp/zz-backend.tgz /tmp/zz-frontend.tgz
sudo -n systemctl restart zappzen
sleep 5
systemctl is-active zappzen
curl -sf --max-time 10 http://127.0.0.1:8000/api/health
'@
$remoto | ssh -o BatchMode=yes $Alvo "bash -s"
if ($LASTEXITCODE -ne 0) { throw "deploy remoto falhou (veja: ssh $Alvo journalctl -u zappzen -n 50)" }

Write-Host ""
Write-Host "Publicado: https://zappzen.atendimentoautomatizado.com.br" -ForegroundColor Green
