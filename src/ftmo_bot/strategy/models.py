"""Strategy and sizing models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from ftmo_bot.rule_engine.models import OrderIntent
from ftmo_bot.simulator.models import Signal


@dataclass(frozen=True)
class InstrumentConfig:
    pip_size: float
    pip_value_usd_per_lot: float
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 100.0


@dataclass(frozen=True)
class SizerConfig:
    risk_per_trade_pct: float = 0.0025


@dataclass(frozen=True)
class SizeResult:
    allow: bool
    lot_size: float
    estimated_risk: float
    reason: str


@dataclass(frozen=True)
class StrategyDecision:
    signal: Optional[Signal]
    order_intent: Optional[OrderIntent]
    reason: str


@dataclass
class PositionState:
    symbol: str
    side: str
    size: float
    entry_price: float
    stop_price: float
    target_price: float
    entry_time: datetime
    entry_index: int


@dataclass
class StrategyState:
    positions: list[PositionState] = field(default_factory=list)
    trades_by_day: dict[date, int] = field(default_factory=dict)
    realized_pnl_by_day: dict[date, float] = field(default_factory=dict)

    def trades_today(self, day: date) -> int:
        return self.trades_by_day.get(day, 0)

    def realized_pnl_today(self, day: date) -> float:
        return self.realized_pnl_by_day.get(day, 0.0)

    def record_trade(self, day: date) -> None:
        self.trades_by_day[day] = self.trades_by_day.get(day, 0) + 1

    def record_realized_pnl(self, day: date, pnl: float) -> None:
        self.realized_pnl_by_day[day] = self.realized_pnl_by_day.get(day, 0.0) + pnl
