"""Persist and load RuleState snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from ftmo_bot.rule_engine.models import RuleState, Trade


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def _serialize_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def load_rule_state(path: str | Path) -> RuleState:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    trades = []
    for trade in data.get("trades", []):
        trades.append(
            Trade(
                symbol=trade["symbol"],
                entry_time=_parse_dt(trade["entry_time"]) or datetime.now(),
                exit_time=_parse_dt(trade.get("exit_time")),
                entry_price=float(trade["entry_price"]),
                exit_price=float(trade["exit_price"]) if trade.get("exit_price") is not None else None,
                profit=float(trade.get("profit", 0.0)),
            )
        )

    return RuleState(
        now=_parse_dt(data.get("now")) or datetime.now(),
        equity=float(data.get("equity", 0.0)),
        balance=float(data.get("balance", 0.0)),
        day_start_equity=float(data.get("day_start_equity", data.get("equity", 0.0))),
        day_start_time=_parse_dt(data.get("day_start_time")) or datetime.now(),
        initial_balance=float(data.get("initial_balance", 0.0)),
        floating_pnl=float(data.get("floating_pnl", 0.0)),
        commission=float(data.get("commission", 0.0)),
        swap=float(data.get("swap", 0.0)),
        other_fees=float(data.get("other_fees", 0.0)),
        trades=trades,
        is_news_blackout=bool(data.get("is_news_blackout", False)),
        open_positions=int(data.get("open_positions", 0)),
        last_trade_time=_parse_dt(data.get("last_trade_time")),
        stage_start_time=_parse_dt(data.get("stage_start_time")),
        drawdown_start_time=_parse_dt(data.get("drawdown_start_time")),
    )


def save_rule_state(path: str | Path, state: RuleState, extra: Optional[dict] = None) -> None:
    payload = asdict(state)
    payload["now"] = _serialize_dt(state.now)
    payload["day_start_time"] = _serialize_dt(state.day_start_time)
    payload["last_trade_time"] = _serialize_dt(state.last_trade_time)
    payload["stage_start_time"] = _serialize_dt(state.stage_start_time)
    payload["drawdown_start_time"] = _serialize_dt(state.drawdown_start_time)
    payload["trades"] = [
        {
            "symbol": trade.symbol,
            "entry_time": _serialize_dt(trade.entry_time),
            "exit_time": _serialize_dt(trade.exit_time),
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "profit": trade.profit,
        }
        for trade in state.trades
    ]
    if extra:
        payload.update(extra)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
