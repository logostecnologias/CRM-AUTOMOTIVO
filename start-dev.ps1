$ErrorActionPreference = "Stop"

$GatewayEnvFile = "/home/ubuntu/evolution/.env"
$GatewayComposeDir = "/home/ubuntu/evolution"
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
        $_.CommandLine -match "27017:127\.0\.0\.1:27017" -or $_.CommandLine -match "8090:127\.0\.0\.1:8090"
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

    Write-Host "Tunel Cloudflare pronto: $tunnelUrl" -ForegroundColor Green
    Write-Host "Reconfigurando o gateway remoto para apontar pra esse tunel..." -ForegroundColor Cyan

    $webhookUrl = "$tunnelUrl/api/webhooks/wuzapi"
    $webhookTemplateUrl = "$tunnelUrl/api/webhooks/wuzapi/{tenant_id}/{connection_id}"
    $remoteCmd = "sed -i 's#^DOWNSTREAM_WEBHOOK_URL=.*#DOWNSTREAM_WEBHOOK_URL=$webhookUrl#' $GatewayEnvFile && " +
        "sed -i 's#^DOWNSTREAM_WEBHOOK_URL_TEMPLATE=.*#DOWNSTREAM_WEBHOOK_URL_TEMPLATE=$webhookTemplateUrl#' $GatewayEnvFile && " +
        "cd $GatewayComposeDir && (docker compose up -d gateway || docker-compose up -d gateway)"

    try {
        ssh -o ConnectTimeout=10 -o BatchMode=yes WuzAPI $remoteCmd
        Write-Host "Gateway remoto reconfigurado - webhooks reais do WhatsApp devem chegar no seu backend local agora." -ForegroundColor Green
    }
    catch {
        Write-Host "Falha ao reconfigurar o gateway remoto: $_" -ForegroundColor Red
    }

    return $proc
}

Stop-StaleProcesses

Write-Host "Abrindo tunel SSH para o banco de dados (bancos-db)..." -ForegroundColor Cyan
$dbTunnel = Start-Process -FilePath "ssh" -ArgumentList "-N", "-L", "27017:127.0.0.1:27017", "bancos-db" -WindowStyle Hidden -PassThru

Write-Host "Abrindo tunel SSH para o gateway WuzAPI..." -ForegroundColor Cyan
$wuzapiTunnel = Start-Process -FilePath "ssh" -ArgumentList "-N", "-L", "8090:127.0.0.1:8090", "WuzAPI" -WindowStyle Hidden -PassThru

$dbOk = Wait-Port 27017 "banco de dados"
$wuzapiOk = Wait-Port 8090 "gateway WuzAPI"

if (-not $dbOk -or -not $wuzapiOk) {
    Stop-Process -Id $dbTunnel.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $wuzapiTunnel.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "Tuneis abertos. Subindo backend + frontend..." -ForegroundColor Green

$cloudflaredProc = Start-WebhookTunnel

try {
    npm run dev
}
finally {
    Write-Host "Encerrando tuneis e processos..." -ForegroundColor Cyan
    Stop-Process -Id $dbTunnel.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $wuzapiTunnel.Id -Force -ErrorAction SilentlyContinue
    if ($cloudflaredProc) {
        Stop-Process -Id $cloudflaredProc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($script:ProxyProc) {
        Stop-Process -Id $script:ProxyProc.Id -Force -ErrorAction SilentlyContinue
    }
}
