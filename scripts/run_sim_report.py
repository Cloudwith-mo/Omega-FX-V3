from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ftmo_bot.config import load_config
from ftmo_bot.rule_engine.models import Trade
from ftmo_bot.simulator import EvaluationSimulator


def _serialize_equity_curve(equity_curve):
    return [{"time": point.time.isoformat(), "equity": point.equity} for point in equity_curve]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    config_path = Path(args.config)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config(config_path)
    tz = ZoneInfo(config.rule_spec.timezone)

    trades = [
        Trade(
            symbol="EURUSD",
            entry_time=datetime(2024, 6, 1, 9, 0, tzinfo=tz),
            exit_time=datetime(2024, 6, 1, 10, 0, tzinfo=tz),
            entry_price=1.1,
            exit_price=1.12,
            profit=2000,
        ),
        Trade(
            symbol="EURUSD",
            entry_time=datetime(2024, 6, 2, 9, 0, tzinfo=tz),
            exit_time=datetime(2024, 6, 2, 10, 0, tzinfo=tz),
            entry_price=1.12,
            exit_price=1.10,
            profit=-1500,
        ),
        Trade(
            symbol="EURUSD",
            entry_time=datetime(2024, 6, 3, 9, 0, tzinfo=tz),
            exit_time=datetime(2024, 6, 3, 10, 0, tzinfo=tz),
            entry_price=1.10,
            exit_price=1.13,
            profit=3000,
        ),
        Trade(
            symbol="EURUSD",
            entry_time=datetime(2024, 6, 4, 9, 0, tzinfo=tz),
            exit_time=datetime(2024, 6, 4, 10, 0, tzinfo=tz),
            entry_price=1.13,
            exit_price=1.15,
            profit=3000,
        ),
    ]

    simulator = EvaluationSimulator(config.rule_spec)
    result = simulator.simulate_trades(trades, initial_balance=config.rule_spec.account_size)

    report = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "config_path": str(config_path),
        "summary": {
            "passed": result.passed,
            "failure_reason": result.failure_reason,
            "trading_days": result.trading_days,
            "target_progress": result.target_progress,
            "violations": result.violations,
            "min_daily_headroom": result.min_daily_headroom,
            "min_max_headroom": result.min_max_headroom,
            "buffer_breaches": result.buffer_breaches,
        },
        "equity_curve": _serialize_equity_curve(result.equity_curve),
        "trades": [asdict(trade) for trade in trades],
    }

    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
