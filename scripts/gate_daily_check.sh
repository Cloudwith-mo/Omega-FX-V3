#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

python3 scripts/analyze_bundles.py --bundle-root reports/daily_bundles --last 1 --output-dir reports/bundle_summary

python3 - <<'PY'
import json
from pathlib import Path
summary = Path("reports/bundle_summary/summary.json")
if not summary.exists():
    raise SystemExit("summary.json missing")
payload = json.loads(summary.read_text())
print("run_id:", payload.get("run_id"))
print("go_no_go:", payload.get("go_no_go"))
print("passes_policy_1:", payload.get("passes_policy_1"))
print("passes_policy_2:", payload.get("passes_policy_2"))
totals = payload.get("totals", {})
print("daily_buffer_stop_count:", totals.get("daily_buffer_stop_count"))
print("breach_events:", totals.get("breach_events"))
print("unresolved_drift_events:", totals.get("unresolved_drift_events"))
print("duplicate_order_events:", totals.get("duplicate_order_events"))
print("min_daily_headroom:", totals.get("min_daily_headroom"))
print("min_max_headroom:", totals.get("min_max_headroom"))
print("total_trades:", totals.get("total_trades"))
PY
