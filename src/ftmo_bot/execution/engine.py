"""Execution engine with journaled idempotency and reconciliation."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Optional

from ftmo_bot.execution.broker import BrokerAdapter
from ftmo_bot.execution.journal import OrderJournal
from ftmo_bot.execution.models import BrokerOrder, ExecutionOrder
from ftmo_bot.execution.throttle import RequestThrottle


class ExecutionEngine:
    def __init__(
        self,
        broker: BrokerAdapter,
        journal: OrderJournal,
        throttle: Optional[RequestThrottle] = None,
        audit_log: Optional[object] = None,
        monitor: Optional[object] = None,
    ) -> None:
        self.broker = broker
        self.journal = journal
        self.throttle = throttle
        self._audit_log = audit_log
        self._monitor = monitor

    def _log(self, event: str, payload: dict) -> None:
        if self._audit_log is None:
            return
        self._audit_log.log(event, payload)

    def _throttle(self, kind: str, now: datetime) -> None:
        if self.throttle is None:
            return
        decision = self.throttle.allow(kind, now)
        if not decision.allow:
            self._log("throttle_block", {"kind": kind, "reason": decision.reason})
            raise RuntimeError(decision.reason)

    def check_connection(self) -> bool:
        ok = self.broker.ping()
        if not ok and self._monitor is not None:
            self._monitor.disconnect("Broker connection lost")
        return ok

    def place_order(self, order: ExecutionOrder) -> BrokerOrder:
        existing = self.journal.get(order.client_order_id)
        if existing and existing.broker_order_id:
            payload = existing.payload
            return BrokerOrder(
                broker_order_id=existing.broker_order_id,
                client_order_id=existing.client_order_id,
                status=existing.status,
                symbol=payload["symbol"],
                side=payload["side"],
                volume=payload["volume"],
                time=order.time,
                price=payload.get("price"),
            )

        if not existing:
            self.journal.record_intent(order.client_order_id, asdict(order))

        self._throttle("place", order.time)
        broker_order = self.broker.place_order(order)
        self.journal.mark_submitted(order.client_order_id, broker_order.broker_order_id)
        status = broker_order.status
        if status in {"rejected", "canceled", "filled", "open", "partial"}:
            self.journal.mark_status(order.client_order_id, status)
        self._log(
            "order_submitted",
            {
                "client_order_id": order.client_order_id,
                "broker_order_id": broker_order.broker_order_id,
                "symbol": order.symbol,
                "side": order.side,
                "volume": order.volume,
                "status": status,
            },
        )
        if status == "rejected":
            self._log(
                "order_rejected",
                {"client_order_id": order.client_order_id, "broker_order_id": broker_order.broker_order_id},
            )
        return broker_order

    def cancel_order(self, broker_order_id: str, now: Optional[datetime] = None) -> None:
        if now is None:
            now = datetime.utcnow().astimezone()
        self._throttle("cancel", now)
        self.broker.cancel_order(broker_order_id)
        self._log("order_canceled", {"broker_order_id": broker_order_id})

    def modify_order(self, broker_order_id: str, price: float | None = None, now: Optional[datetime] = None) -> None:
        if now is None:
            now = datetime.utcnow().astimezone()
        self._throttle("modify", now)
        self.broker.modify_order(broker_order_id, price=price)
        self._log("order_modified", {"broker_order_id": broker_order_id, "price": price})

    def reconcile(self) -> None:
        broker_open = {order.client_order_id: order for order in self.broker.list_open_orders()}
        for entry in self.journal.list_open():
            if entry.client_order_id not in broker_open and entry.status != "closed":
                self.journal.mark_status(entry.client_order_id, "closed")
                self._log("order_reconciled", {"client_order_id": entry.client_order_id, "status": "closed"})

        for client_order_id in broker_open.keys():
            if self.journal.get(client_order_id) is None:
                self.journal.record_intent(client_order_id, {})
                self.journal.mark_status(client_order_id, "submitted")
                self._log("order_reconciled", {"client_order_id": client_order_id, "status": "submitted"})
