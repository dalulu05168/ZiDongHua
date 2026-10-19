# Windows PowerShell 5.1 end-to-end local launcher test, no external accounts.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$outFile = Join-Path $env:TEMP "xiaobawang-windows-startout.log"
$errFile = Join-Path $env:TEMP "xiaobawang-windows-starterr.log"
$launcher = Join-Path $root "scripts\start-windows.ps1"
$process = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $launcher + '"')) `
    -WorkingDirectory $root -RedirectStandardOutput $outFile `
    -RedirectStandardError $errFile -PassThru

try {
    $ready = $false
    for ($i = 0; $i -lt 150; $i++) {
        Start-Sleep -Seconds 2
        $process.Refresh()
        if ($process.HasExited) { break }
        try {
            $status = Invoke-RestMethod -Uri "http://127.0.0.1:3100/health" -TimeoutSec 2
            if ($status.real_sending -eq $false) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) {
        Write-Host "Windows launcher did not become healthy."
        if (Test-Path $outFile) { Get-Content $outFile -Tail 20 }
        if (Test-Path $errFile) { Get-Content $errFile -Tail 30 }
        throw "Windows launcher startup failed"
    }
    $settings = Get-Content -LiteralPath ".secrets.local.json" -Raw | ConvertFrom-Json
    $res = Invoke-RestMethod -Uri "http://127.0.0.1:3100/api/whatsapp/sessions" `
        -Headers @{"X-API-Key"=[string]$settings.XBW_API_KEY} -TimeoutSec 5
    if (@($res).Count -ne 0) { throw "Expected zero unpaired WhatsApp sessions" }
    Write-Host "PASS: Windows PowerShell 5.1 startup, backend HTTP and Baileys bridge authorization"
    Write-Host "PASS: No real accounts connected, no messages sent"
} finally {
    if ($process) {
        $process.Refresh()
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    }
}
