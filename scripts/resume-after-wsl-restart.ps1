$ErrorActionPreference = "Stop"
$Project = "D:\AI-Workspace\Projects\crypto-quant-nfi"
$LogDir = Join-Path $Project "user_data\logs\network-repair"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$ts = Get-Date -Format yyyyMMdd-HHmmss
$log = Join-Path $LogDir "resume-after-wsl-restart-$ts.log"
"== wsl shutdown ==" | Tee-Object -FilePath $log
wsl.exe --shutdown 2>&1 | Tee-Object -FilePath $log -Append
Start-Sleep -Seconds 8
"== resume network repair ==" | Tee-Object -FilePath $log -Append
wsl.exe -e bash /mnt/d/AI-Workspace/Projects/crypto-quant-nfi/scripts/resume-network-repair.sh 2>&1 | Tee-Object -FilePath $log -Append
"resume_after_log=$log"