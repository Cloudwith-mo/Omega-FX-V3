"""Broker adapter interface."""

from __future__ import annotations

from typing import Iterable

from ftmo_bot.execution.models import BrokerOrder, ExecutionOrder, Position


class BrokerAdapter:
    def place_order(self, order: ExecutionOrder) -> BrokerOrder:  # pragma: no cover - interface
        raise NotImplementedError

    def cancel_order(self, broker_order_id: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def modify_order(self, broker_order_id: str, price: float | None = None) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_open_orders(self) -> Iterable[BrokerOrder]:  # pragma: no cover - interface
        raise NotImplementedError

    def list_positions(self) -> Iterable[Position]:  # pragma: no cover - interface
        raise NotImplementedError

    def ping(self) -> bool:  # pragma: no cover - interface
        return True
