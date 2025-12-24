$ErrorActionPreference = "Stop"

param(
  [ValidateSet("smoke", "gate")]
  [string]$Phase = "smoke",
  [int]$Minutes = 30,
  [string]$RepoPath = "",
  [string]$Config = "configs/ftmo_v1.yaml",
  [switch]$Resume,
  [switch]$TailLogs
)

if (-not $RepoPath) {
  $RepoPath = Join-Path $HOME "Omega-FX-V3"
}

if (-not (Test-Path $RepoPath)) {
  git clone https://github.com/Cloudwith-mo/Omega-FX-V3.git $RepoPath
}

Set-Location $RepoPath

if (-not (Test-Path ".venv")) {
  py -3.11 -m venv .venv
}
. .\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev] | Out-Null
pip install MetaTrader5 | Out-Null

$env:PYTHONPATH = "src"

if (-not $env:MT5_LOGIN) { $env:MT5_LOGIN = Read-Host "MT5_LOGIN" }
if (-not $env:MT5_SERVER) { $env:MT5_SERVER = Read-Host "MT5_SERVER" }
if (-not $env:MT5_PASSWORD) {
  $secure = Read-Host "MT5_PASSWORD" -AsSecureString
  $env:MT5_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  )
}
if (-not $env:FTMO_FORCE_DISCONNECT) {
  $env:FTMO_FORCE_DISCONNECT = Join-Path $env:TEMP "ftmo_force_disconnect"
}

if (-not (Select-String -Path $Config -Pattern "broker: mt5" -Quiet)) {
  (Get-Content $Config) -replace "broker: paper", "broker: mt5" | Set-Content $Config
}

python scripts\freeze_config.py $Config

if (-not $Resume) {
  Remove-Item "runtime\run_state.json" -ErrorAction SilentlyContinue
}

$serviceScript = Join-Path $RepoPath "scripts\start_service.ps1"
New-Item -ItemType Directory -Force -Path "runtime" | Out-Null
New-Item -ItemType File -Force -Path "runtime\service.log" | Out-Null

$tailProc = $null
if ($TailLogs) {
  $tailCmd = 'Get-Content -Path "runtime\service.log" -Wait'
  $tailProc = Start-Process -FilePath "powershell" -WorkingDirectory $RepoPath `
    -ArgumentList "-NoProfile -Command `"$tailCmd`"" `
    -PassThru
}

if ($Phase -eq "smoke") {
  $proc = Start-Process -FilePath "powershell" -WorkingDirectory $RepoPath `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$serviceScript`" -Config `"$Config`"" `
    -PassThru

  Write-Host "Smoke running for $Minutes minutes (service PID $($proc.Id))..."
  Start-Sleep -Seconds ($Minutes * 60)

  if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force
  }
  if ($tailProc -and -not $tailProc.HasExited) {
    Stop-Process -Id $tailProc.Id -Force
  }

  python scripts\analyze_bundles.py --bundle-root reports/daily_bundles --last 1 --output-dir reports/bundle_summary

  $summaryPath = "reports\bundle_summary\summary.json"
  if (-not (Test-Path $summaryPath)) {
    throw "summary.json missing: $summaryPath"
  }
  $summary = Get-Content $summaryPath | ConvertFrom-Json
  Write-Host "run_id:" $summary.run_id
  Write-Host "go_no_go:" $summary.go_no_go
  Write-Host "passes_policy_1:" $summary.passes_policy_1
  Write-Host "passes_policy_2:" $summary.passes_policy_2
  Write-Host "daily_buffer_stop_count:" $summary.totals.daily_buffer_stop_count
  Write-Host "breach_events:" $summary.totals.breach_events
  Write-Host "unresolved_drift_events:" $summary.totals.unresolved_drift_events
  Write-Host "duplicate_order_events:" $summary.totals.duplicate_order_events

  if (Test-Path "runtime\service_crash.txt") {
    Write-Warning "Crash marker:"
    Get-Content "runtime\service_crash.txt"
  }
  Write-Host "Logs: runtime\service.log"
  exit 0
}

Start-Process -FilePath "powershell" -WorkingDirectory $RepoPath `
  -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$serviceScript`" -Config `"$Config`"" | Out-Null

$runId = ""
if (Test-Path "runtime\run_state.json") {
  $runId = (Get-Content "runtime\run_state.json" | ConvertFrom-Json).run_id
}
if ($runId) {
  $runId | Set-Content "runtime\gate_run_id.txt"
}

Write-Host "Gate run started."
Write-Host "run_id:" $runId
Write-Host "bundles: reports\daily_bundles\$runId\YYYY-MM-DD\"
Write-Host "daily check: scripts\gate_daily_check.ps1"
Write-Host "end-of-run summary:"
Write-Host "python scripts\analyze_bundles.py --bundle-root reports/daily_bundles --run-id $runId --last 5 --output-dir reports/bundle_summary"
Write-Host "Logs: runtime\service.log (crash marker: runtime\service_crash.txt)"
