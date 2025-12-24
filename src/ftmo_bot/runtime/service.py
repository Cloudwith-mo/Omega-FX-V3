"""Scheduled reconciliation and health checks."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event
from typing import Optional

from ftmo_bot.execution.engine import ExecutionEngine
from ftmo_bot.monitoring.monitor import Monitor


@dataclass
class ServiceConfig:
    reconcile_interval_seconds: int = 30
    health_check_interval_seconds: int = 10


class ServiceLoop:
    def __init__(
        self,
        engine: ExecutionEngine,
        monitor: Optional[Monitor] = None,
        config: Optional[ServiceConfig] = None,
    ) -> None:
        self.engine = engine
        self.monitor = monitor
        self.config = config or ServiceConfig()

    def run_forever(self, stop_event: Optional[Event] = None) -> None:
        if stop_event is None:
            stop_event = Event()

        last_reconcile = 0.0
        last_health = 0.0
        self.engine.reconcile()

        while not stop_event.is_set():
            now = time.monotonic()
            if now - last_health >= self.config.health_check_interval_seconds:
                self.engine.check_connection()
                last_health = now
            if now - last_reconcile >= self.config.reconcile_interval_seconds:
                self.engine.reconcile()
                last_reconcile = now
            time.sleep(0.2)
