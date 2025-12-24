from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ftmo_bot.config import load_config
from ftmo_bot.simulator import EvaluationSimulator, PriceBar, Signal


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

    price_series = [
        PriceBar(
            time=datetime(2024, 6, 1, 9, 0, tzinfo=tz),
            bid=1.1000,
            ask=1.1002,
            high=1.1020,
            low=1.0990,
            symbol="EURUSD",
        ),
        PriceBar(
            time=datetime(2024, 6, 1, 10, 0, tzinfo=tz),
            bid=1.1010,
            ask=1.1012,
            high=1.1030,
            low=1.1000,
            symbol="EURUSD",
        ),
        PriceBar(
            time=datetime(2024, 6, 2, 10, 0, tzinfo=tz),
            bid=1.0990,
            ask=1.0992,
            high=1.1010,
            low=1.0980,
            symbol="EURUSD",
        ),
        PriceBar(
            time=datetime(2024, 6, 3, 10, 0, tzinfo=tz),
            bid=1.1020,
            ask=1.1022,
            high=1.1040,
            low=1.1010,
            symbol="EURUSD",
        ),
        PriceBar(
            time=datetime(2024, 6, 4, 10, 0, tzinfo=tz),
            bid=1.1050,
            ask=1.1052,
            high=1.1060,
            low=1.1040,
            symbol="EURUSD",
        ),
    ]
    signals = [
        Signal(time=price_series[0].time, action="open", side="buy", size=1.0, symbol="EURUSD"),
        Signal(time=price_series[1].time, action="close", side="buy", size=1.0, symbol="EURUSD"),
        Signal(time=price_series[2].time, action="open", side="buy", size=1.0, symbol="EURUSD"),
        Signal(time=price_series[3].time, action="close", side="buy", size=1.0, symbol="EURUSD"),
        Signal(time=price_series[4].time, action="open", side="buy", size=1.0, symbol="EURUSD"),
    ]

    simulator = EvaluationSimulator(config.rule_spec)
    result = simulator.simulate_signals(price_series, signals, initial_balance=config.rule_spec.account_size)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
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
            "min_equity_intraday": result.min_equity_intraday,
            "min_equity_overall": result.min_equity_overall,
        },
        "breach_events": [
            {
                "time": event.time.isoformat(),
                "reason": event.reason,
                "equity": event.equity,
                "daily_headroom": event.daily_headroom,
                "max_headroom": event.max_headroom,
            }
            for event in result.breach_events
        ],
        "equity_curve": _serialize_equity_curve(result.equity_curve),
        "signals": [asdict(signal) for signal in signals],
    }

    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
