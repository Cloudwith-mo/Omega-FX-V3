from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from ftmo_bot.config import load_config
from ftmo_bot.strategy import StrategyContext, StrategyFarm
from ftmo_bot.simulator import PriceBar


def _parse_bar(row: dict) -> PriceBar | None:
    time_raw = row.get("time") or row.get("timestamp")
    if not time_raw:
        return None
    time = datetime.fromisoformat(time_raw)
    symbol = row.get("symbol") or "SIM"
    bid = float(row.get("bid") or row.get("close") or row.get("price"))
    ask = float(row.get("ask") or bid)
    high = float(row.get("high") or bid)
    low = float(row.get("low") or bid)
    return PriceBar(time=time, bid=bid, ask=ask, high=high, low=low, symbol=symbol)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--bars", required=True, help="CSV with time,symbol,bid,ask,high,low")
    parser.add_argument("--output-dir", default="reports/tournament")
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bars: list[PriceBar] = []
    with Path(args.bars).open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            bar = _parse_bar(row)
            if bar:
                bars.append(bar)

    bars.sort(key=lambda b: b.time)
    context = StrategyContext(
        timezone=config.rule_spec.timezone,
        initial_balance=config.rule_spec.account_size,
        symbol_specs=None,
    )
    farm = StrategyFarm(config.farm, config.rule_spec, context, baseline_strategy=config.strategy)

    for bar in bars:
        farm.process_bar(bar)

    scores = farm.latest_scores
    ranked = sorted(scores.items(), key=lambda item: item[1].score, reverse=True)
    ranked_payload = [
        {
            "strategy_id": strategy_id,
            "score": score.score,
            "net_return": score.net_return,
            "max_drawdown": score.max_drawdown,
            "buffer_stops": score.buffer_stops,
            "burst_violations": score.burst_violations,
            "trade_count": score.trade_count,
        }
        for strategy_id, score in ranked
    ]
    (output_dir / "ranked_strategies.json").write_text(
        json.dumps(ranked_payload, indent=2),
        encoding="utf-8",
    )

    selected = []
    if ranked_payload:
        selected.append({"strategy_id": ranked_payload[0]["strategy_id"], "weight": 1.0})
    (output_dir / "selected_portfolio.yaml").write_text(
        "strategies:\n"
        + "\n".join([f"  - strategy_id: {item['strategy_id']}\n    weight: {item['weight']}" for item in selected]),
        encoding="utf-8",
    )

    print(f"Wrote {output_dir}")


if __name__ == "__main__":
    main()
