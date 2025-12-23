from __future__ import annotations

from datetime import datetime, timezone

from ftmo_bot.execution import ExecutionEngine, ExecutionOrder, OrderJournal, RequestThrottle
from ftmo_bot.execution.broker import BrokerAdapter
from ftmo_bot.execution.models import BrokerOrder
from ftmo_bot.execution.paper import PaperBroker


class RejectBroker(BrokerAdapter):
    def place_order(self, order: ExecutionOrder) -> BrokerOrder:
        return BrokerOrder(
            broker_order_id="reject-1",
            client_order_id=order.client_order_id,
            status="rejected",
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            time=order.time,
            price=order.price,
        )

    def cancel_order(self, broker_order_id: str) -> None:
        return None

    def modify_order(self, broker_order_id: str, price: float | None = None) -> None:
        return None

    def list_open_orders(self):
        return []

    def list_positions(self):
        return []


class PartialBroker(RejectBroker):
    def place_order(self, order: ExecutionOrder) -> BrokerOrder:
        return BrokerOrder(
            broker_order_id="partial-1",
            client_order_id=order.client_order_id,
            status="partial",
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            time=order.time,
            price=order.price,
        )


class DisconnectBroker(RejectBroker):
    def ping(self) -> bool:
        return False


class DummyMonitor:
    def __init__(self) -> None:
        self.disconnects: list[str] = []

    def disconnect(self, reason: str) -> None:
        self.disconnects.append(reason)



def test_execution_idempotent_place_order(tmp_path):
    journal = OrderJournal(tmp_path / "journal.db")
    broker = PaperBroker(fill_on_place=True)
    engine = ExecutionEngine(broker, journal)

    order = ExecutionOrder(
        client_order_id="id-1",
        symbol="EURUSD",
        side="buy",
        volume=1.0,
        time=datetime(2024, 6, 1, tzinfo=timezone.utc),
        price=1.1,
    )

    first = engine.place_order(order)
    engine = ExecutionEngine(broker, journal)
    second = engine.place_order(order)

    assert first.broker_order_id == second.broker_order_id
    assert len(broker._orders) == 1


def test_execution_reject_records_status(tmp_path):
    journal = OrderJournal(tmp_path / "journal.db")
    broker = RejectBroker()
    engine = ExecutionEngine(broker, journal)

    order = ExecutionOrder(
        client_order_id="id-2",
        symbol="EURUSD",
        side="buy",
        volume=1.0,
        time=datetime(2024, 6, 1, tzinfo=timezone.utc),
        price=1.1,
    )

    engine.place_order(order)
    entry = journal.get("id-2")
    assert entry is not None
    assert entry.status == "rejected"


def test_partial_fill_stays_open(tmp_path):
    journal = OrderJournal(tmp_path / "journal.db")
    broker = PartialBroker()
    engine = ExecutionEngine(broker, journal)

    order = ExecutionOrder(
        client_order_id="id-3",
        symbol="EURUSD",
        side="buy",
        volume=1.0,
        time=datetime(2024, 6, 1, tzinfo=timezone.utc),
        price=1.1,
    )

    engine.place_order(order)
    open_entries = journal.list_open()
    assert any(entry.client_order_id == "id-3" for entry in open_entries)


def test_request_throttle_blocks(tmp_path):
    journal = OrderJournal(tmp_path / "journal.db")
    broker = PaperBroker(fill_on_place=True)
    throttle = RequestThrottle(max_requests_per_day=1, timezone="Europe/Prague")
    engine = ExecutionEngine(broker, journal, throttle=throttle)

    order = ExecutionOrder(
        client_order_id="id-4",
        symbol="EURUSD",
        side="buy",
        volume=1.0,
        time=datetime(2024, 6, 1, tzinfo=timezone.utc),
        price=1.1,
    )

    engine.place_order(order)
    try:
        engine.place_order(
            ExecutionOrder(
                client_order_id="id-5",
                symbol="EURUSD",
                side="buy",
                volume=1.0,
                time=datetime(2024, 6, 1, 0, 1, tzinfo=timezone.utc),
                price=1.1,
            )
        )
        assert False, "Expected throttle to block"
    except RuntimeError as exc:
        assert "Daily request cap" in str(exc)


def test_disconnect_monitor_called(tmp_path):
    journal = OrderJournal(tmp_path / "journal.db")
    broker = DisconnectBroker()
    monitor = DummyMonitor()
    engine = ExecutionEngine(broker, journal, monitor=monitor)

    ok = engine.check_connection()
    assert ok is False
    assert monitor.disconnects == ["Broker connection lost"]
