param(
  [ValidateSet("runtime", "evidence")]
  [string]$Profile = "runtime",
  [switch]$Replace
)

$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\AI-Workspace\Projects\crypto-quant-nfi"
$WslProjectRoot = "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi"
$OutLog = Join-Path $ProjectRoot "user_data\logs\freqtrade-native.wslproc.out.log"
$ErrLog = Join-Path $ProjectRoot "user_data\logs\freqtrade-native.wslproc.err.log"
$RuntimeConfigPath = if ($Profile -eq "evidence") {
  "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi/user_data/config.sample_validation.json"
} else {
  "/mnt/d/AI-Workspace/Projects/crypto-quant-nfi/user_data/config.runtime.json"
}
if ($Replace) {
  $StopCommand = "cd $WslProjectRoot && bash scripts/stop-native.sh"
  & wsl.exe -e bash -lc $StopCommand
  if ($LASTEXITCODE -ne 0) {
    throw "Existing dry-run process could not be stopped safely."
  }
}
$WslCommand = "cd $WslProjectRoot && export RUNTIME_CONFIG_PATH='$RuntimeConfigPath' && exec ./scripts/run-native.sh"
$Arguments = '-e bash -lc "' + $WslCommand + '"'

$process = Start-Process `
  -FilePath "wsl.exe" `
  -ArgumentList $Arguments `
  -WindowStyle Hidden `
  -RedirectStandardOutput $OutLog `
  -RedirectStandardError $ErrLog `
  -PassThru

Write-Host "[PASS] Started hidden WSL dry-run process. Windows PID=$($process.Id) Profile=$Profile"
Write-Host "Web UI: http://127.0.0.1:8080"
Write-Host "Out log: $OutLog"
Write-Host "Err log: $ErrLog"
