#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python3 -m pip install -e .[dev]

PYTHONPATH=src python3 scripts/freeze_config.py configs/ftmo_v1.yaml

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q '^ftmo-bot.service'; then
  sudo systemctl start ftmo-bot
  sudo systemctl is-active --quiet ftmo-bot
  echo "systemd: ftmo-bot is active"
else
  echo "systemd unit not found; start manually:"
  echo "PYTHONPATH=src python3 scripts/run_service_loop.py --config configs/ftmo_v1.yaml --resume"
fi

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

echo "$RUN_ID" > runtime/gate_run_id.txt

echo "run_id: $RUN_ID"
echo "bundles: reports/daily_bundles/$RUN_ID/YYYY-MM-DD/"
echo "end-of-run summary command:"
STAMP="$(date +%Y%m%d-%H%M%S)"
echo "python3 scripts/analyze_bundles.py --bundle-root reports/daily_bundles --run-id $RUN_ID --last 5 --output-dir reports/bundle_summary/${RUN_ID}-${STAMP}"
