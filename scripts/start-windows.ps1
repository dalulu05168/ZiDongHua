# XiaoBaWang Windows local launcher (development, no Docker).
# Run from your own checkout. All services bind to localhost.
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Python launcher 'py' is missing" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js is missing" }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw "npm.cmd is missing" }

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    & py -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Creating Python virtual environment failed" }
}
& $python -m pip install -r backend/requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Installing Python requirements failed" }

Push-Location (Join-Path $projectRoot "integrations\whatsapp")
try {
    & npm.cmd install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE" }
} finally { Pop-Location }

# Keep secrets in JSON data, NEVER dot-source an executable .ps1 secrets file.
# Uses Windows PowerShell 5.1 compatible cryptographic randomness.
function New-LocalSecret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([System.BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

$secretPath = Join-Path $projectRoot ".secrets.local.json"
if (-not (Test-Path -LiteralPath $secretPath)) {
    $secrets = [pscustomobject]@{
        XBW_API_KEY = New-LocalSecret
        XBW_TG_KEY = New-LocalSecret
        XBW_BRIDGE_KEY = New-LocalSecret
    }
    $secrets | ConvertTo-Json -Compress | Set-Content -LiteralPath $secretPath -Encoding UTF8
}
try {
    $secrets = Get-Content -LiteralPath $secretPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    throw "Invalid .secrets.local.json. Back it up or delete it locally, then relaunch."
}
$keys = @([string]$secrets.XBW_API_KEY, [string]$secrets.XBW_TG_KEY, [string]$secrets.XBW_BRIDGE_KEY)
foreach ($key in $keys) {
    if ($key -cnotmatch '^[0-9a-f]{64}$') { throw "Invalid local secret format. Regenerate .secrets.local.json." }
}
if (($keys | Sort-Object -Unique).Count -ne 3) { throw "Local service keys must be different" }

$env:XBW_API_KEY = $secrets.XBW_API_KEY
$env:XBW_TG_KEY = $secrets.XBW_TG_KEY
$env:XBW_BRIDGE_KEY = $secrets.XBW_BRIDGE_KEY
$env:DRY_RUN = "true"
$env:XBW_SEND_ENABLED = "false"
$env:BAILEYS_SEND_ENABLED = "false"
$env:XBW_BRIDGE_HOST = "127.0.0.1"

Write-Host "Local-only developer server, real messaging disabled."
Write-Host "Local admin key is stored in .secrets.local.json. Never paste it into chat."
Write-Host "Open http://127.0.0.1:3100"
$bridgeDir = Join-Path $projectRoot "integrations\whatsapp"
$bridgeProcess = Start-Process -FilePath (Get-Command node).Source -ArgumentList "bridge.mjs" -WorkingDirectory $bridgeDir -PassThru -NoNewWindow
try {
    & $python -m uvicorn backend.app:app --host 127.0.0.1 --port 3100
} finally {
    if ($bridgeProcess -and -not $bridgeProcess.HasExited) {
        Stop-Process -Id $bridgeProcess.Id -Force
    }
}
