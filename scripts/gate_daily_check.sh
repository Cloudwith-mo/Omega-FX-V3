#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

RUN_ID=$(python3 - <<'PY'
import json
from pathlib import Path
path = Path("runtime/run_state.json")
if not path.exists():
    print("")
else:
    print(json.loads(path.read_text()).get("run_id", ""))
PY
)

STAMP="$(date +%Y%m%d-%H%M%S)"
if [[ -n "$RUN_ID" ]]; then
  SUMMARY_DIR="reports/bundle_summary/${RUN_ID}-${STAMP}"
  python3 scripts/analyze_bundles.py --bundle-root reports/daily_bundles --run-id "$RUN_ID" --last 1 --output-dir "$SUMMARY_DIR"
else
  SUMMARY_DIR="reports/bundle_summary/${STAMP}"
  python3 scripts/analyze_bundles.py --bundle-root reports/daily_bundles --last 1 --output-dir "$SUMMARY_DIR"
fi

SUMMARY_DIR="$SUMMARY_DIR" python3 - <<'PY'
import json
import os
from pathlib import Path
summary = Path(os.environ["SUMMARY_DIR"]) / "summary.json"
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
print("safe_mode_unexpected_events:", totals.get("safe_mode_unexpected_events"))
print("min_daily_headroom:", totals.get("min_daily_headroom"))
print("min_max_headroom:", totals.get("min_max_headroom"))
print("total_trades:", totals.get("total_trades"))
PY
