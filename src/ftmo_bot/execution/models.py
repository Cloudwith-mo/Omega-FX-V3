"""Execution models for broker interaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    pip_size: float
    pip_value_usd_per_lot: float
    min_lot: float
    lot_step: float
    max_lot: float
    tick_size: Optional[float] = None
    tick_value: Optional[float] = None
    digits: Optional[int] = None
    contract_size: Optional[float] = None


@dataclass(frozen=True)
class ReconcileReport:
    missing_in_broker: list[str]
    missing_in_journal: list[str]
    reconciled_closed: list[str]
    reconciled_added: list[str]


@dataclass(frozen=True)
class ExecutionOrder:
    client_order_id: str
    symbol: str
    side: str
    volume: float
    time: datetime
    price: Optional[float] = None
    intent_id: Optional[str] = None
    strategy_id: Optional[str] = None


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
