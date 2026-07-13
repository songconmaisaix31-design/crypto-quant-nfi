param(
    [string]$ProjectRoot = "D:\AI-Workspace\Projects\crypto-quant-nfi"
)

$ErrorActionPreference = "Stop"
$LogDir = Join-Path $ProjectRoot "reports\shadow_decision"
$LogFile = Join-Path $LogDir "shadow_daily_run_logs.txt"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-RunLog {
    param([string]$Message)
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -LiteralPath $LogFile -Value $line
    Write-Host $line
}

Write-RunLog "Starting shadow daily run"
Write-RunLog "ProjectRoot=$ProjectRoot"

$wslProject = "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"
$commands = @(
    "bash scripts/shadow-signal-check.sh",
    "bash scripts/shadow-decision-journal.sh",
    "bash scripts/shadow-decision-daily-report.sh"
)

foreach ($cmd in $commands) {
    Write-RunLog "Running: $cmd"
    & wsl.exe -e bash -lc "cd $wslProject && $cmd" 2>&1 | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        Write-RunLog "Command failed with exit code ${LASTEXITCODE}: $cmd"
        exit $LASTEXITCODE
    }
}

Write-RunLog "Shadow daily run complete"
