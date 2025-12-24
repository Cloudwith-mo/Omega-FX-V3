"""Execution engine with journaled idempotency and reconciliation."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from ftmo_bot.execution.broker import BrokerAdapter
from ftmo_bot.execution.journal import OrderJournal
from ftmo_bot.execution.models import BrokerOrder, ExecutionOrder, ReconcileReport
from ftmo_bot.execution.throttle import RequestThrottle


class ExecutionEngine:
    def __init__(
        self,
        broker: BrokerAdapter,
        journal: OrderJournal,
        throttle: Optional[RequestThrottle] = None,
        audit_log: Optional[object] = None,
        monitor: Optional[object] = None,
        duplicate_window_seconds: float = 10.0,
        duplicate_block: bool = True,
    ) -> None:
        self.broker = broker
        self.journal = journal
        self.throttle = throttle
        self._audit_log = audit_log
        self._monitor = monitor
        self._duplicate_window_seconds = max(0.0, duplicate_window_seconds)
        self._duplicate_block = duplicate_block
        self._recent_orders: deque[tuple[float, tuple]] = deque(maxlen=1000)

    def _log(self, event: str, payload: dict) -> None:
        if self._audit_log is None:
            return
        self._audit_log.log(event, payload)

    def _duplicate_signature(self, order: ExecutionOrder) -> Optional[tuple]:
        if order.intent_id is None:
            return None
        price_key = round(order.price, 6) if order.price is not None else None
        return (
            order.intent_id or "",
            order.strategy_id or "",
            order.symbol,
            order.side,
            round(order.volume, 6),
            price_key,
        )

    def _check_duplicate(self, order: ExecutionOrder) -> None:
        if self._duplicate_window_seconds <= 0:
            return
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - self._duplicate_window_seconds
        while self._recent_orders and self._recent_orders[0][0] < cutoff:
            self._recent_orders.popleft()

        signature = self._duplicate_signature(order)
        if signature is None:
            return
        for _, existing in self._recent_orders:
            if existing == signature:
                self._log(
                    "duplicate_order_detected",
                    {
                        "client_order_id": order.client_order_id,
                        "intent_id": order.intent_id,
                        "strategy_id": order.strategy_id,
                        "symbol": order.symbol,
                        "side": order.side,
                        "volume": order.volume,
                        "price": order.price,
                        "window_seconds": self._duplicate_window_seconds,
                    },
                )
                if self._duplicate_block:
                    raise RuntimeError("Duplicate order detected")
                break

        self._recent_orders.append((now, signature))

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
        if not ok:
            self._log("disconnect", {"reason": "Broker connection lost"})
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

        self._check_duplicate(order)
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

    def reconcile(self) -> ReconcileReport:
        broker_open = {order.client_order_id: order for order in self.broker.list_open_orders()}
        missing_in_broker: list[str] = []
        reconciled_closed: list[str] = []
        for entry in self.journal.list_open():
            if entry.client_order_id not in broker_open and entry.status != "closed":
                self.journal.mark_status(entry.client_order_id, "closed")
                missing_in_broker.append(entry.client_order_id)
                reconciled_closed.append(entry.client_order_id)
                self._log("order_reconciled", {"client_order_id": entry.client_order_id, "status": "closed"})

        missing_in_journal: list[str] = []
        reconciled_added: list[str] = []
        for client_order_id in broker_open.keys():
            if self.journal.get(client_order_id) is None:
                self.journal.record_intent(client_order_id, {})
                self.journal.mark_status(client_order_id, "submitted")
                missing_in_journal.append(client_order_id)
                reconciled_added.append(client_order_id)
                self._log("order_reconciled", {"client_order_id": client_order_id, "status": "submitted"})

        return ReconcileReport(
            missing_in_broker=missing_in_broker,
            missing_in_journal=missing_in_journal,
            reconciled_closed=reconciled_closed,
            reconciled_added=reconciled_added,
        )
