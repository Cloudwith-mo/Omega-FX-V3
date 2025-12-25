from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from ftmo_bot.execution import ExecutionEngine, ExecutionOrder, OrderJournal, PaperBroker
from ftmo_bot.monitoring import AuditLog
from ftmo_bot.runtime import AsyncServiceConfig, AsyncServiceLoop, SafeModeController


def _load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def test_reconcile_threaded_loop_no_safe_mode(tmp_path) -> None:
    journal = OrderJournal(tmp_path / "journal.db")
    broker = PaperBroker(fill_on_place=False)
    audit_path = tmp_path / "audit.log"
    audit = AuditLog(audit_path)
    safe_mode = SafeModeController(tmp_path / "safe_mode.json", audit_log=audit)
    engine = ExecutionEngine(broker, journal, audit_log=audit)

    engine.place_order(
        ExecutionOrder(
            client_order_id="thread-test-1",
            symbol="EURUSD",
            side="buy",
            volume=1.0,
            time=datetime.now(timezone.utc),
            price=1.1,
            intent_id="intent-thread-1",
        )
    )

    service = AsyncServiceLoop(
        engine,
        config=AsyncServiceConfig(
            fast_loop_interval_seconds=0.01,
            bar_loop_interval_seconds=0.5,
            reconcile_interval_seconds=0.01,
            health_check_interval_seconds=0.01,
        ),
        safe_mode=safe_mode,
        audit_log=audit,
    )

    async def runner() -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(service.run_forever(stop_event))
        await asyncio.sleep(0.2)
        stop_event.set()
        await task

    asyncio.run(runner())

    assert safe_mode.state.enabled is False
    events = _load_events(audit_path)
    assert not any(event.get("event") == "service_error" for event in events)
