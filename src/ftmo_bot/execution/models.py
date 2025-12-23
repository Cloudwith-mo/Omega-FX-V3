"""Execution models for broker interaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class ExecutionOrder:
    client_order_id: str
    symbol: str
    side: str
    volume: float
    time: datetime
    price: Optional[float] = None


@dataclass(frozen=True)
class BrokerOrder:
    broker_order_id: str
    client_order_id: str
    status: str
    symbol: str
    side: str
    volume: float
    time: datetime
    price: Optional[float] = None


@dataclass(frozen=True)
class Position:
    symbol: str
    side: str
    volume: float
    entry_price: float
    unrealized_pnl: float = 0.0
