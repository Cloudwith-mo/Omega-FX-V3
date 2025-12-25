$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (-not (Test-Path ".venv")) {
  py -3.11 -m venv .venv
}
. .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"

$runId = ""
if (Test-Path "runtime\run_state.json") {
  $runId = (Get-Content "runtime\run_state.json" | ConvertFrom-Json).run_id
}
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ($runId) {
  $summaryDir = Join-Path "reports\bundle_summary" "$runId-$stamp"
  python scripts\analyze_bundles.py --bundle-root reports/daily_bundles --run-id $runId --last 1 --output-dir $summaryDir
} else {
  $summaryDir = Join-Path "reports\bundle_summary" $stamp
  python scripts\analyze_bundles.py --bundle-root reports/daily_bundles --last 1 --output-dir $summaryDir
}

$summaryPath = Join-Path $summaryDir "summary.json"
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
Write-Host "safe_mode_unexpected_events:" $summary.totals.safe_mode_unexpected_events
Write-Host "min_daily_headroom:" $summary.totals.min_daily_headroom
Write-Host "min_max_headroom:" $summary.totals.min_max_headroom
Write-Host "total_trades:" $summary.totals.total_trades
