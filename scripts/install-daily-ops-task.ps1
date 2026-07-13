$TaskName = "CryptoQuantNfiDailyOps"
$ProjectRoot = "D:\AI-Workspace\Projects\crypto-quant-nfi"
$Script = Join-Path $ProjectRoot "scripts\run-daily-ops.ps1"
Write-Host "Manual install command:"
Write-Host "schtasks /Create /TN $TaskName /SC DAILY /ST 08:30 /TR `"powershell -NoProfile -ExecutionPolicy Bypass -File `"$Script`"`""
Write-Host "Manual uninstall command:"
Write-Host "schtasks /Delete /TN $TaskName /F"

