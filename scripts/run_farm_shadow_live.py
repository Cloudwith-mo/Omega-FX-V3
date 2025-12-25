from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from ftmo_bot.config import load_config
from ftmo_bot.execution import MT5Broker
from ftmo_bot.strategy import StrategyContext, StrategyFarm, fetch_symbol_specs
from ftmo_bot.strategy.market_data import MT5BarFeed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--status-path", default="runtime/farm_status.json")
    args = parser.parse_args()

    config = load_config(args.config)
    if not config.farm.enabled:
        raise SystemExit("farm.enabled is false in config; enable it before running shadow live")

    login = os.getenv("MT5_LOGIN") or config.execution.account
    server = os.getenv("MT5_SERVER")
    password = os.getenv("MT5_PASSWORD")
    path = os.getenv("MT5_PATH") or None
    if not login or not server or not password:
        raise SystemExit("MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER are required")

    broker = MT5Broker(login=int(login), password=password, server=server, path=path)
    symbol_specs = fetch_symbol_specs(broker, config.instruments)

    context = StrategyContext(
        timezone=config.rule_spec.timezone,
        initial_balance=config.rule_spec.account_size,
        symbol_specs=symbol_specs or None,
    )
    farm = StrategyFarm(config.farm, config.rule_spec, context, baseline_strategy=config.strategy)
    farm_params = (config.farm.strategies[0].parameters if config.farm.strategies else config.strategy.parameters)
    farm_timeframe = str(farm_params.get("timeframe", "M15"))
    feed = MT5BarFeed(config.instruments, farm_timeframe, config.rule_spec.timezone)

    status_path = Path(args.status_path)
    status_path.parent.mkdir(parents=True, exist_ok=True)

    while True:
        bars = feed.fetch_new_bars()
        for bar in bars:
            farm.process_bar(bar)
            snapshot = farm.snapshot(bar.time)
            status_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        time.sleep(max(1.0, config.runtime.bar_loop_interval_seconds))


if __name__ == "__main__":
    main()
