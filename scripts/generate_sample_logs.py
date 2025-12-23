from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ftmo_bot.config import load_config
from ftmo_bot.monitoring import AuditLog, LogNotifier, Monitor
from ftmo_bot.risk import RiskGovernor
from ftmo_bot.rule_engine import RuleEngine
from ftmo_bot.rule_engine.models import OrderIntent, RuleState
from ftmo_bot.runtime import create_run_context


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    config_path = Path(args.config)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config(config_path)
    context = create_run_context(config_path, config.run_id_prefix)

    run_context_path = output_dir / "run_context.json"
    run_context_path.write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "config_path": str(config_path),
                "config_hash": context.config_hash,
                "started_at": context.started_at.isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    audit_path = output_dir / "audit.log"
    audit = AuditLog(audit_path, run_id=context.run_id, config_hash=context.config_hash)
    monitor = Monitor(LogNotifier(prefix="[FTMO-DEMO]"))

    engine = RuleEngine(config.rule_spec)
    governor = RiskGovernor(engine, audit_log=audit, monitor=monitor)

    tz = ZoneInfo(config.rule_spec.timezone)
    state = RuleState(
        now=datetime(2024, 6, 1, 23, 50, tzinfo=tz),
        equity=96500,
        balance=96500,
        day_start_equity=100000,
        day_start_time=datetime(2024, 6, 1, 0, 0, tzinfo=tz),
        initial_balance=100000,
        trades=[],
    )

    intent = OrderIntent(
        symbol="EURUSD",
        side="buy",
        volume=1.0,
        time=state.now,
        estimated_risk=600,
    )

    audit.log("run_start", {"run_id": context.run_id, "config_path": str(config_path)})
    governor.evaluate_state(state)
    governor.pre_trade(intent, state)

    alerts_path = output_dir / "alerts.log"
    alerts_path.write_text(
        "[FTMO-DEMO] RULE_BUFFER: daily buffer reached, remaining 3500.00\n"
        "[FTMO-DEMO] FLATTEN: Hard limit reached\n",
        encoding="utf-8",
    )

    snapshot_path = output_dir / "state_snapshot.json"
    snapshot_path.write_text(json.dumps(asdict(state), indent=2, default=str), encoding="utf-8")

    print(f"Wrote bundle to {output_dir}")


if __name__ == "__main__":
    main()
