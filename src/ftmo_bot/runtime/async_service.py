"""Asyncio-based service loop for live ops scheduling."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from ftmo_bot.execution.engine import ExecutionEngine
from ftmo_bot.runtime.safe_mode import SafeModeController


Callback = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True)
class AsyncServiceConfig:
    fast_loop_interval_seconds: float = 0.5
    bar_loop_interval_seconds: float = 60.0
    reconcile_interval_seconds: float = 30.0
    health_check_interval_seconds: float = 10.0


class AsyncServiceLoop:
    def __init__(
        self,
        engine: ExecutionEngine,
        config: Optional[AsyncServiceConfig] = None,
        safe_mode: Optional[SafeModeController] = None,
        audit_log: Optional[object] = None,
    ) -> None:
        self.engine = engine
        self.config = config or AsyncServiceConfig()
        self.safe_mode = safe_mode
        self._audit_log = audit_log

    async def _maybe_call(self, callback: Callback | None) -> None:
        if callback is None:
            return
        result = callback()
        if inspect.isawaitable(result):
            await result

    def _log(self, event: str, payload: dict) -> None:
        if self._audit_log is None:
            return
        self._audit_log.log(event, payload)

    async def _run_periodic(
        self,
        name: str,
        interval: float,
        callback: Callback | None,
        stop_event: asyncio.Event,
    ) -> None:
        loop = asyncio.get_running_loop()
        while not stop_event.is_set():
            start = loop.time()
            try:
                await self._maybe_call(callback)
            except Exception as exc:  # pragma: no cover - defensive
                if self.safe_mode is not None:
                    self.safe_mode.enable(f"{name} loop error: {exc}")
                self._log("service_error", {"loop": name, "error": str(exc)})
            elapsed = loop.time() - start
            delay = max(0.0, interval - elapsed)
            if delay:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass

    async def _reconcile_once(self) -> None:
        await asyncio.to_thread(self.engine.reconcile)

    async def _health_once(self) -> None:
        ok = await asyncio.to_thread(self.engine.check_connection)
        if not ok and self.safe_mode is not None:
            self.safe_mode.enable("Broker connection lost")

    async def run_forever(
        self,
        stop_event: Optional[asyncio.Event] = None,
        fast_callback: Callback | None = None,
        bar_callback: Callback | None = None,
    ) -> None:
        if stop_event is None:
            stop_event = asyncio.Event()

        async with asyncio.TaskGroup() as group:
            group.create_task(
                self._run_periodic(
                    "fast",
                    self.config.fast_loop_interval_seconds,
                    fast_callback,
                    stop_event,
                )
            )
            group.create_task(
                self._run_periodic(
                    "bar",
                    self.config.bar_loop_interval_seconds,
                    bar_callback,
                    stop_event,
                )
            )
            group.create_task(
                self._run_periodic(
                    "reconcile",
                    self.config.reconcile_interval_seconds,
                    self._reconcile_once,
                    stop_event,
                )
            )
            group.create_task(
                self._run_periodic(
                    "health",
                    self.config.health_check_interval_seconds,
                    self._health_once,
                    stop_event,
                )
            )
            await stop_event.wait()
