#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MINUTES="${1:-30}"

cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python3 -m pip install -e .[dev]

PYTHONPATH=src python3 scripts/freeze_config.py configs/ftmo_v1.yaml

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q '^ftmo-bot.service'; then
  sudo systemctl restart ftmo-bot
  sudo systemctl is-active --quiet ftmo-bot
  echo "systemd: ftmo-bot is active"
else
  echo "systemd unit not found; starting service loop directly"
  PYTHONPATH=src python3 scripts/run_service_loop.py --config configs/ftmo_v1.yaml --resume &
  echo $! > runtime/gate_smoke.pid
fi

echo "Waiting ${MINUTES} minutes..."
sleep "$((MINUTES * 60))"

RUN_ID=$(python3 - <<'PY'
import json
from pathlib import Path
path = Path("runtime/run_state.json")
if not path.exists():
    raise SystemExit("runtime/run_state.json not found")
print(json.loads(path.read_text()).get("run_id", ""))
PY
)

if [[ -z "$RUN_ID" ]]; then
  echo "run_id not found in runtime/run_state.json"
  exit 1
fi

if [[ ! -d "reports/daily_bundles/${RUN_ID}" ]]; then
  PYTHONPATH=src python3 scripts/generate_daily_bundle.py --config configs/ftmo_v1.yaml --run-id "$RUN_ID" --output-dir reports/daily_bundles
else
  if ! find "reports/daily_bundles/${RUN_ID}" -mindepth 1 -maxdepth 1 -type d | grep -q .; then
    PYTHONPATH=src python3 scripts/generate_daily_bundle.py --config configs/ftmo_v1.yaml --run-id "$RUN_ID" --output-dir reports/daily_bundles
  fi
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
SUMMARY_DIR="reports/bundle_summary/${RUN_ID}-${STAMP}"
python3 scripts/analyze_bundles.py --bundle-root reports/daily_bundles --run-id "$RUN_ID" --last 1 --output-dir "$SUMMARY_DIR"

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

BUNDLE_DIR=$(python3 - <<'PY'
from pathlib import Path
import json
root = Path("reports/daily_bundles")
state = Path("runtime/run_state.json")
run_id = json.loads(state.read_text()).get("run_id")
run_dir = root / run_id
if not run_dir.exists():
    raise SystemExit("bundle dir not found")
latest = max([p for p in run_dir.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime)
print(latest)
PY
)

echo "latest bundle: $BUNDLE_DIR"
