# XiaoBaWang Windows local launcher (development)
# No Docker required. Do not run elevated; all services bind to loopback.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Python launcher py not installed" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js not installed" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm not installed" }
if (-not (Test-Path ".venv")) { py -m venv .venv }
$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
& $python -m pip install -r backend/requirements.txt
Push-Location integrations/whatsapp
try { npm install --no-audit --no-fund } finally { Pop-Location }
$secretPath = Join-Path (Get-Location) ".secrets.local.ps1"
if (-not (Test-Path $secretPath)) {
    $admin = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    $tg = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    $bridge = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    @(
      '$env:XBW_API_KEY="' + $admin + '"',
      '$env:XBW_TG_KEY="' + $tg + '"',
      '$env:XBW_BRIDGE_KEY="' + $bridge + '"'
    ) | Set-Content -LiteralPath $secretPath -Encoding UTF8
}
. $secretPath
$env:DRY_RUN="true"
$env:XBW_SEND_ENABLED="false"
$env:BAILEYS_SEND_ENABLED="false"
Write-Host "Local dev server only. Never share .secrets.local.ps1."
Write-Host "Backend URL: http://127.0.0.1:3100"
$bridgeDir = Join-Path (Get-Location) "integrations/whatsapp"
$bridgeProcess = Start-Process -FilePath (Get-Command node).Source -ArgumentList "bridge.mjs" -WorkingDirectory $bridgeDir -PassThru -NoNewWindow
try {
    & $python -m uvicorn backend.app:app --host 127.0.0.1 --port 3100
} finally {
    if (-not $bridgeProcess.HasExited) { Stop-Process -Id $bridgeProcess.Id -Force }
}
