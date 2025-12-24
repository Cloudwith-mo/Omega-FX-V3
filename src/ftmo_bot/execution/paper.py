"""Paper broker adapter for local testing."""

from __future__ import annotations

from dataclasses import replace

from ftmo_bot.execution.broker import BrokerAdapter
from ftmo_bot.execution.models import BrokerOrder, ExecutionOrder, Position, SymbolSpec


class PaperBroker(BrokerAdapter):
    def __init__(self, fill_on_place: bool = True, symbol_specs: dict[str, SymbolSpec] | None = None) -> None:
        self.fill_on_place = fill_on_place
        self._orders: dict[str, BrokerOrder] = {}
        self._positions: dict[str, Position] = {}
        self._counter = 0
        self._symbol_specs = symbol_specs or {}

    def place_order(self, order: ExecutionOrder) -> BrokerOrder:
        existing = self._orders.get(order.client_order_id)
        if existing:
            return existing

        self._counter += 1
        broker_id = f"paper-{self._counter}"
        status = "filled" if self.fill_on_place else "submitted"
        broker_order = BrokerOrder(
            broker_order_id=broker_id,
            client_order_id=order.client_order_id,
            status=status,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            time=order.time,
            price=order.price,
        )
        self._orders[order.client_order_id] = broker_order

        if status == "filled":
            self._apply_fill(order)

        return broker_order

    def _apply_fill(self, order: ExecutionOrder) -> None:
        existing = self._positions.get(order.symbol)
        if existing is None:
            self._positions[order.symbol] = Position(
                symbol=order.symbol,
                side=order.side,
                volume=order.volume,
                entry_price=order.price or 0.0,
                unrealized_pnl=0.0,
            )
            return

        volume = existing.volume + order.volume if existing.side == order.side else existing.volume - order.volume
        if volume <= 0:
            del self._positions[order.symbol]
        else:
            self._positions[order.symbol] = replace(existing, volume=volume)

    def cancel_order(self, broker_order_id: str) -> None:
        for key, order in list(self._orders.items()):
            if order.broker_order_id == broker_order_id:
                self._orders[key] = replace(order, status="canceled")

    def modify_order(self, broker_order_id: str, price: float | None = None) -> None:
        for key, order in list(self._orders.items()):
            if order.broker_order_id == broker_order_id:
                self._orders[key] = replace(order, price=price)

    def list_open_orders(self):
        return [order for order in self._orders.values() if order.status in {"submitted", "open"}]

    def list_positions(self):
        return list(self._positions.values())

    def get_symbol_spec(self, symbol: str) -> SymbolSpec | None:
        return self._symbol_specs.get(symbol)
