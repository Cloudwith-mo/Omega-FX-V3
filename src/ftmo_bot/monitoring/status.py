"""Runtime status reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ftmo_bot.rule_engine.models import AccountStage


@dataclass(frozen=True)
class RuleHeadroom:
    daily: float
    maximum: float
    daily_buffer: float
    max_buffer: float


@dataclass(frozen=True)
class RuntimeStatus:
    now: datetime
    stage: AccountStage
    equity: float
    balance: float
    day_start_equity: float
    day_start_time: datetime
    open_positions: int
    trading_days: int
    min_trading_days_remaining: int
    days_since_last_trade: int | None
    drawdown_pct: float
    drawdown_days: int | None
    headroom: RuleHeadroom
    target_progress: float
