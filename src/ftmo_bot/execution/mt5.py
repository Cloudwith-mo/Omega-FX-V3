"""MT5 broker adapter (skeleton)."""

from __future__ import annotations

from typing import Iterable

from ftmo_bot.execution.broker import BrokerAdapter
from ftmo_bot.execution.models import BrokerOrder, ExecutionOrder, Position

try:  # pragma: no cover - optional dependency
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - optional dependency
    mt5 = None


class MT5Broker(BrokerAdapter):
    def __init__(self, login: int, password: str, server: str) -> None:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 package is not installed")
        self.login = login
        self.password = password
        self.server = server
        if not mt5.initialize(login=login, password=password, server=server):
            raise RuntimeError("Failed to initialize MetaTrader5")

    def place_order(self, order: ExecutionOrder) -> BrokerOrder:
        raise NotImplementedError("MT5 order placement not implemented yet")

    def cancel_order(self, broker_order_id: str) -> None:
        raise NotImplementedError("MT5 order cancel not implemented yet")

    def modify_order(self, broker_order_id: str, price: float | None = None) -> None:
        raise NotImplementedError("MT5 order modify not implemented yet")

    def list_open_orders(self) -> Iterable[BrokerOrder]:
        return []

    def list_positions(self) -> Iterable[Position]:
        return []

    def ping(self) -> bool:
        if mt5 is None:
            return False
        return mt5.terminal_info() is not None
