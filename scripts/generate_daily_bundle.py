from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ftmo_bot.config import load_config
from ftmo_bot.runtime.bundles import generate_daily_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", default="reports/daily_bundles")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (Prague time)")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)

    run_id = args.run_id or "manual"
    if args.date:
        bundle_day = datetime.fromisoformat(args.date).date()
    else:
        bundle_day = datetime.now(ZoneInfo(config.rule_spec.timezone)).date()

    output_dir = Path(args.output_dir)
    run_state_path = Path("runtime") / "run_state.json"
    journal_path = None
    if run_state_path.exists():
        try:
            payload = run_state_path.read_text(encoding="utf-8")
            if payload:
                run_id = run_id or "manual"
        except Exception:
            pass
    if args.run_id:
        run_id = args.run_id
    else:
        if run_state_path.exists():
            try:
                import json

                payload = json.loads(run_state_path.read_text(encoding="utf-8"))
                run_id = payload.get("run_id", run_id)
            except Exception:
                pass

    journal_path_candidate = Path("runtime") / f"journal-{run_id}.db"
    if journal_path_candidate.exists():
        journal_path = journal_path_candidate

    bundle_dir = generate_daily_bundle(
        run_id=run_id,
        config_path=config_path,
        output_dir=output_dir,
        timezone=config.rule_spec.timezone,
        audit_log_path=Path(config.monitoring.audit_log_path),
        status_path=Path(config.runtime.status_path),
        run_state_path=run_state_path,
        safe_mode_path=Path(config.runtime.safe_mode_path),
        journal_path=journal_path,
        state_snapshot_path=Path(config.runtime.state_snapshot_path),
        bundle_day=bundle_day,
    )

    print(f"Bundle written to {bundle_dir}")


if __name__ == "__main__":
    main()
