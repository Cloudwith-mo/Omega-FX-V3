"""Daily metrics tracking for runtime observability."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ftmo_bot.monitoring.status import RuntimeStatus
from ftmo_bot.rule_engine.models import RuleState
from ftmo_bot.rule_engine.time import trading_day_for


def _load_payload(path: Path) -> dict:
    if not path.exists():
        return {"days": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"days": {}}


def _save_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _count_trades_for_day(state: RuleState, day: date, timezone: str) -> int:
    count = 0
    tz = ZoneInfo(timezone)
    for trade in state.trades:
        if trade.entry_time.astimezone(tz).date() == day:
            count += 1
    return count


def update_daily_metrics(
    path: str | Path,
    state: RuleState,
    status: RuntimeStatus,
    timezone: str,
) -> dict:
    path = Path(path)
    payload = _load_payload(path)
    days = payload.setdefault("days", {})

    day = trading_day_for(state.now, timezone).isoformat()
    entry = days.get(day, {})

    equity = status.equity
    daily_headroom = status.headroom.daily
    max_headroom = status.headroom.maximum
    drawdown_pct = status.drawdown_pct
    day_start_equity = status.day_start_equity

    min_equity = min(entry.get("min_equity", equity), equity)
    max_equity = max(entry.get("max_equity", equity), equity)
    min_daily_headroom = min(entry.get("min_daily_headroom", daily_headroom), daily_headroom)
    min_max_headroom = min(entry.get("min_max_headroom", max_headroom), max_headroom)
    max_drawdown_pct = max(entry.get("max_drawdown_pct", drawdown_pct), drawdown_pct)
    intraday_drawdown_pct = 0.0
    if day_start_equity > 0:
        intraday_drawdown_pct = max(0.0, (day_start_equity - min_equity) / day_start_equity)
    max_intraday_drawdown = max(entry.get("max_intraday_drawdown_pct", intraday_drawdown_pct), intraday_drawdown_pct)

    trades_total = len(state.trades)
    trades_today = _count_trades_for_day(state, date.fromisoformat(day), timezone)

    entry.update(
        {
            "min_equity": min_equity,
            "max_equity": max_equity,
            "min_daily_headroom": min_daily_headroom,
            "min_max_headroom": min_max_headroom,
            "max_drawdown_pct": max_drawdown_pct,
            "max_intraday_drawdown_pct": max_intraday_drawdown,
            "day_start_equity": day_start_equity,
            "trades_total": trades_total,
            "trades_today": trades_today,
            "trading_days": state.trading_days(timezone),
            "last_update": datetime.utcnow().isoformat() + "Z",
        }
    )
    days[day] = entry

    payload["last_updated"] = datetime.utcnow().isoformat() + "Z"
    _save_payload(path, payload)
    return entry
