$ErrorActionPreference = "Stop"

# O webpack recusa caminho com "!" (reservado para a sintaxe de loader), e a
# pasta do projeto fica dentro de "!LOGOS TECNOLOGIAS": o frontend morre com
# "Invalid configuration object ... contains exclamation mark". Em vez de
# renomear a pasta (OneDrive, atalhos e outros projetos dependem do caminho),
# mapeamos o projeto numa letra de unidade com subst e rodamos este mesmo
# script a partir dela. Dentro da unidade o caminho nao tem "!", entao a
# chamada interna nao entra aqui de novo. O mapeamento e desfeito no fim,
# inclusive com Ctrl+C (o finally roda nesse caso).
if ($PSScriptRoot -match '!') {
    $drive = $null
    # Reaproveita um mapeamento que tenha sobrado de uma execucao interrompida.
    foreach ($linha in (subst)) {
        if ($linha -match '^([A-Z]):\\: => (.+)$' -and $Matches[2].TrimEnd('\') -eq $PSScriptRoot.TrimEnd('\')) {
            $drive = $Matches[1]
            break
        }
    }
    if (-not $drive) {
        $usadas = (Get-PSDrive -PSProvider FileSystem).Name
        $drive = [char[]]'ZYXWVUTSRQP' | Where-Object { $usadas -notcontains "$_" } | Select-Object -First 1
        if (-not $drive) {
            Write-Host "Nenhuma letra de unidade livre (P-Z) para contornar o '!' no caminho." -ForegroundColor Red
            exit 1
        }
        subst "${drive}:" "$PSScriptRoot"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Falha ao mapear ${drive}: para o projeto." -ForegroundColor Red
            exit 1
        }
    }

    Write-Host "Caminho com '!' (o webpack nao aceita). Rodando a partir de ${drive}:\ ..." -ForegroundColor Cyan
    $origem = Get-Location
    $codigo = 0
    try {
        Set-Location "${drive}:\"
        & "${drive}:\start-dev.ps1"
        $codigo = $LASTEXITCODE
    }
    finally {
        Set-Location $origem
        subst "${drive}:" /D | Out-Null
    }
    exit $codigo
}

$CloudflaredLogOut = Join-Path $env:TEMP "zappzen-cloudflared.out.log"
$CloudflaredLogErr = Join-Path $env:TEMP "zappzen-cloudflared.err.log"

# Porta do proxy de webhook (backend/webhook_proxy.py). O tunel Cloudflare
# aponta pra ELE, nao pro backend: assim so /api/webhooks/* fica publico, e o
# resto da API (login, admin) nunca sai na internet. Ver ZZ-03.
$WebhookProxyPort = 8099
$script:ProxyProc = $null

function Stop-StaleProcesses {
    Write-Host "Encerrando tuneis e processos antigos (se houver)..." -ForegroundColor Cyan

    Get-CimInstance Win32_Process -Filter "Name = 'ssh.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "27017:127\.0\.0\.1:27017"
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

    # A npm run dev anterior as vezes nao encerra limpo (terminal fechado a
    # forca, etc.) e deixa o uvicorn/react-scripts presos nas portas do
    # backend/frontend. Isso trava o proximo "npm run dev" numa porta
    # diferente (ou o processo velho responde no lugar do novo), o que
    # quebra login por conflito de porta/CORS — mata por porta, nao por nome
    # de processo, pra nao afetar node/python de outros projetos abertos.
    foreach ($port in 3001, 8000) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
            $staleId = $_.OwningProcess
            if ($staleId -and $staleId -ne $PID) {
                $p = Get-Process -Id $staleId -ErrorAction SilentlyContinue
                if ($p) {
                    Write-Host "Matando processo preso na porta $port ($($p.ProcessName), PID $staleId)..." -ForegroundColor Yellow
                    Stop-Process -Id $staleId -Force -ErrorAction SilentlyContinue
                }
                # Com `uvicorn --reload` no Windows a porta aparece no nome do
                # processo PAI (o reloader), mas quem atende e o filho (o
                # worker do multiprocessing). Se o pai ja morreu, matar so ele
                # nao faz nada e o worker orfao continua respondendo na 8000,
                # sem tunel para o banco: o login falha sem erro claro.
                Get-CimInstance Win32_Process -Filter "ParentProcessId = $staleId" -ErrorAction SilentlyContinue | ForEach-Object {
                    Write-Host "Matando processo filho preso na porta $port ($($_.Name), PID $($_.ProcessId))..." -ForegroundColor Yellow
                    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                }
            }
        }
    }
}

function Wait-Port($port, $label) {
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        if (Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue -InformationLevel Quiet) {
            return $true
        }
    }
    Write-Host "Nao foi possivel abrir o tunel para $label (porta $port). Verifique sua conexao e tente de novo." -ForegroundColor Red
    return $false
}

function Start-WebhookTunnel {
    $cfCmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    $cfPath = if ($cfCmd) { $cfCmd.Source } else { "C:\Program Files (x86)\cloudflared\cloudflared.exe" }
    if (-not (Test-Path $cfPath)) {
        Write-Host "cloudflared nao encontrado - pulando auto-configuracao do webhook do WhatsApp." -ForegroundColor Yellow
        return $null
    }

    Remove-Item $CloudflaredLogOut, $CloudflaredLogErr -Force -ErrorAction SilentlyContinue

    # Sobe o proxy de webhook ANTES do tunel: ele e o alvo do tunel, e limita a
    # superficie publica a /api/webhooks/* (ver backend/webhook_proxy.py e ZZ-03).
    # O proxy e o tunel sao NAO-fatais de proposito: se qualquer um falhar, a
    # app ainda sobe local (o `npm run dev` la embaixo roda de qualquer jeito).
    # So os webhooks reais do WhatsApp deixam de chegar ate resolver — nunca a
    # aplicacao inteira. Sem este try/catch, com $ErrorActionPreference=Stop um
    # Start-Process que falhasse abortaria o start inteiro.
    Write-Host "Subindo proxy de webhook (so /api/webhooks/* fica publico)..." -ForegroundColor Cyan
    $env:PROXY_PORT = "$WebhookProxyPort"
    $env:BACKEND_PORT = "8000"
    try {
        $script:ProxyProc = Start-Process -FilePath "python" `
            -ArgumentList "backend/webhook_proxy.py" `
            -WindowStyle Hidden -PassThru -ErrorAction Stop
    }
    catch {
        Write-Host "Nao foi possivel iniciar o proxy de webhook ($_). Pulando o tunel: a app sobe local, webhooks reais nao chegam ate resolver." -ForegroundColor Yellow
        return $null
    }
    if (-not (Wait-Port $WebhookProxyPort "proxy de webhook")) {
        Write-Host "Proxy de webhook nao respondeu - pulando o tunel (app sobe local; webhooks reais nao chegam)." -ForegroundColor Yellow
        if ($script:ProxyProc) { Stop-Process -Id $script:ProxyProc.Id -Force -ErrorAction SilentlyContinue }
        $script:ProxyProc = $null
        return $null
    }

    Write-Host "Abrindo tunel Cloudflare para receber webhooks reais do WhatsApp..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath $cfPath `
        -ArgumentList "tunnel", "--url", "http://localhost:$WebhookProxyPort" `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $CloudflaredLogOut `
        -RedirectStandardError $CloudflaredLogErr

    $tunnelUrl = $null
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        foreach ($log in @($CloudflaredLogErr, $CloudflaredLogOut)) {
            if (-not $tunnelUrl -and (Test-Path $log)) {
                $match = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($match) { $tunnelUrl = $match.Matches[0].Value }
            }
        }
        if ($tunnelUrl) { break }
    }

    if (-not $tunnelUrl) {
        Write-Host "Nao foi possivel obter a URL do tunel Cloudflare a tempo - webhooks reais do WhatsApp nao vao chegar." -ForegroundColor Red
        return $proc
    }

    # A URL do tunel muda a cada execucao (tunel efemero), e o webhook da Cloud
    # API e cadastrado a mao no painel do app da Meta: nao existe API para
    # troca-lo. Por isso aqui so imprimimos o endereco, em vez de reconfigurar
    # nada sozinho. Para trabalhar sem colar a URL a cada dia, use um tunel
    # nomeado do Cloudflare (dominio fixo) e cadastre-o uma vez.
    # O canal nao oficial NAO tem esse problema, e por isso aqui ha uma acao
    # alem de imprimir: o webhook da WuzAPI e configurado por nos, por chamada,
    # quando a conexao e criada. Basta o backend saber o endereco publico da
    # vez, e e isso que PUBLIC_BASE_URL carrega. O `load_dotenv` do server.py
    # nao usa override, entao a variavel posta aqui ganha do valor do .env — que
    # em dev e o localhost, um endereco que a ponte (noutra maquina) nunca
    # alcancaria. Sem isto a conexao pareia por QR e nao recebe mensagem
    # nenhuma, que e o sintoma mais caro desse canal.
    $env:PUBLIC_BASE_URL = $tunnelUrl

    Write-Host ""
    Write-Host "Tunel Cloudflare pronto." -ForegroundColor Green
    Write-Host "Canal nao oficial (WuzAPI): nada a fazer, o webhook e apontado sozinho para" -ForegroundColor Cyan
    Write-Host "    $tunnelUrl/api/webhooks/wuzapi" -ForegroundColor Yellow
    Write-Host "Cadastre esta URL no painel do app da Meta, em WhatsApp > Configuracao > Webhook:" -ForegroundColor Cyan
    Write-Host "    $tunnelUrl/api/webhooks/whatsapp" -ForegroundColor Yellow
    Write-Host "O campo 'Verificar token' e o valor de META_WEBHOOK_VERIFY_TOKEN do backend/.env." -ForegroundColor Cyan
    Write-Host "Assine o campo 'messages' na mesma tela, senao nada entra." -ForegroundColor Cyan
    Write-Host ""

    return $proc
}

Stop-StaleProcesses

Write-Host "Abrindo tunel SSH para o banco de dados e a ponte WuzAPI (bancos-db)..." -ForegroundColor Cyan
$dbTunnel = Start-Process -FilePath "ssh" `
    -ArgumentList "-N", "-L", "27017:127.0.0.1:27017", "-L", "8080:127.0.0.1:8080", "bancos-db" `
    -WindowStyle Hidden -PassThru

# Duas portas, e so a primeira e obrigatoria.
#
# A Cloud API e um endereco publico da Meta (graph.facebook.com), entao o envio
# por ela sai direto da maquina; o que precisa de tunel ali e o caminho de
# VOLTA, o webhook, e disso cuida o cloudflared abaixo.
#
# A 8080 e a ponte WuzAPI do canal nao oficial, que roda na MESMA maquina do
# banco e escuta so em loopback la. Producao ja a carrega no
# `zappzen-db-tunnel`; aqui ela faltava, e sem ela criar uma conexao nao
# oficial falhava no ato: a instancia e criada por chamada a ponte, e a ponte
# nao existia deste lado. Nao e fatal de proposito — quem so trabalha com a
# Cloud API nao deve ficar sem ambiente porque a ponte esta fora do ar.
$dbOk = Wait-Port 27017 "banco de dados"

if (-not $dbOk) {
    Stop-Process -Id $dbTunnel.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port 8080 -WarningAction SilentlyContinue -InformationLevel Quiet)) {
    Write-Host "Ponte WuzAPI (porta 8080) nao respondeu - o canal nao oficial (QR) nao vai funcionar nesta sessao." -ForegroundColor Yellow
}

Write-Host "Tunel aberto. Subindo backend + frontend..." -ForegroundColor Green

$cloudflaredProc = Start-WebhookTunnel

try {
    npm run dev
}
finally {
    Write-Host "Encerrando tuneis e processos..." -ForegroundColor Cyan
    Stop-Process -Id $dbTunnel.Id -Force -ErrorAction SilentlyContinue
    if ($cloudflaredProc) {
        Stop-Process -Id $cloudflaredProc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($script:ProxyProc) {
        Stop-Process -Id $script:ProxyProc.Id -Force -ErrorAction SilentlyContinue
    }
}
