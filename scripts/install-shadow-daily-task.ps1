param(
    [string]$ProjectRoot = "D:\AI-Workspace\Projects\crypto-quant-nfi",
    [string]$TaskName = "CryptoQuantNFIShadowDaily",
    [string]$At = "09:00"
)

$ErrorActionPreference = "Stop"
$ReportDir = Join-Path $ProjectRoot "reports\shadow_decision"
$Report = Join-Path $ReportDir "shadow_scheduler_setup.md"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$script = Join-Path $ProjectRoot "scripts\run-shadow-daily.ps1"
$ps = (Get-Command powershell.exe).Source
$action = New-ScheduledTaskAction -Execute $ps -Argument "-ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Description "Run crypto quant NFI shadow decision daily report. Dry-run observation only." -Force | Out-Null
    $status = "installed"
    $message = "Task Scheduler task `$TaskName` installed for daily run at `$At`."
} catch {
    $status = "manual_required"
    $message = $_.Exception.Message
}

@"
# Shadow Daily Scheduler Setup

- Task name: `$TaskName`
- Status: `$status`
- Project: `$ProjectRoot`
- Command: `powershell -ExecutionPolicy Bypass -File "$script"`
- Message: `$message`

This task only runs shadow signal check, shadow decision journal, and shadow daily report. It does not enable live trading, does not write API keys, and does not modify Freqtrade trading configuration.

Manual install command:

```powershell
powershell -ExecutionPolicy Bypass -File "$($MyInvocation.MyCommand.Path)"
```
"@ | Set-Content -LiteralPath $Report -Encoding UTF8

Write-Host $message
Write-Host "Report: $Report"
