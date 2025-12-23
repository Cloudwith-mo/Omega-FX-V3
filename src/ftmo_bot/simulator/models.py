"""Simulation data structures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence


@dataclass(frozen=True)
class PriceBar:
    time: datetime
    bid: float
    ask: float


@dataclass(frozen=True)
class Signal:
    time: datetime
    action: str  # "open" or "close"
    side: str  # "buy" or "sell"
    size: float
    price: Optional[float] = None


@dataclass(frozen=True)
class SimulatedTrade:
    entry_time: datetime
    exit_time: datetime
    side: str
    size: float
    entry_price: float
    exit_price: float
    profit: float


@dataclass(frozen=True)
class EquityPoint:
    time: datetime
    equity: float


@dataclass(frozen=True)
class MonteCarloConfig:
    slippage_range: Sequence[float] = (0.0, 0.0)
    spread_range: Sequence[float] = (0.0, 0.0)


@dataclass(frozen=True)
class SimulationResult:
    equity_curve: list[EquityPoint]
    passed: bool
    failure_reason: Optional[str]
    trading_days: int
    target_progress: float
    violations: list[str]
    min_daily_headroom: float
    min_max_headroom: float
    buffer_breaches: int
