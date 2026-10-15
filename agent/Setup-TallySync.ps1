# Setup-TallySync.ps1 - one-time setup on the Tally PC.
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$CfgPath = Join-Path $Here "TallySync.config.json"

Write-Host ""
Write-Host "=== Tally Mobile - sync setup ===" -ForegroundColor Cyan
Write-Host ""

$cfg = $null
if (Test-Path $CfgPath) { $cfg = Get-Content $CfgPath -Raw | ConvertFrom-Json }

$defUrl = if ($cfg) { $cfg.ServerUrl } else { "" }
$url = Read-Host "Server address, e.g. http://100.101.102.103:8780  [$defUrl]"
if (-not $url) { $url = $defUrl }
$url = $url.Trim().TrimEnd("/")
if ($url -notmatch '^https?://') { $url = "http://" + $url }

$tok = Read-Host "Sync token (same as SYNC_TOKEN in docker-compose.yml)$(if ($cfg) {' [keep current]'})"
if (-not $tok -and $cfg) { $tok = $cfg.SyncToken }

$from = Read-Host "Sync vouchers from date YYYY-MM-DD (blank = start of this financial year)"

$newCfg = [ordered]@{ ServerUrl = $url; SyncToken = $tok.Trim(); TallyUrl = "http://localhost:9000"; FromDate = $from.Trim() }
$newCfg | ConvertTo-Json | Set-Content $CfgPath -Encoding UTF8
Write-Host "Saved settings." -ForegroundColor Green

Write-Host "Checking the server ..."
try {
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("Authorization", "Bearer " + $newCfg.SyncToken)
    [void]$wc.DownloadString("$url/agent/ping")
    Write-Host "Server reachable and token accepted." -ForegroundColor Green
} catch {
    Write-Host ("Could not reach the server: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "Check the address, that Tailscale is connected on this PC, and the token. Then run Setup.bat again."
    exit 1
}

Write-Host ""
Write-Host "Running the first full sync (keep TallyPrime open) ..." -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Here "TallySync.ps1") -Force
if ($LASTEXITCODE -ne 0) {
    Write-Host "The first sync did not finish cleanly - see the messages above." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Scheduling automatic sync every 10 minutes ..."
$vbs = Join-Path $Here "run-hidden.vbs"
& schtasks.exe /Create /TN "Tally Mobile Sync" /TR "wscript.exe `"$vbs`"" /SC MINUTE /MO 10 /F | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Done. Tally data will sync every 10 minutes while this PC is on and Tally is open." -ForegroundColor Green
} else {
    Write-Host "Could not create the scheduled task. Try running Setup.bat as administrator." -ForegroundColor Red
}
