"""Monitoring and alert routing."""

from __future__ import annotations

from dataclasses import dataclass

from ftmo_bot.monitoring.notifier import Notifier


@dataclass
class Monitor:
    notifier: Notifier

    def rule_buffer_breach(self, which: str, remaining: float) -> None:
        self.notifier.notify("RULE_BUFFER", f"{which} buffer reached, remaining {remaining:.2f}")

    def flatten_trigger(self, reason: str) -> None:
        self.notifier.notify("FLATTEN", reason)

    def disconnect(self, reason: str) -> None:
        self.notifier.notify("DISCONNECT", reason)

    def inactivity_warning(self, message: str) -> None:
        self.notifier.notify("INACTIVITY", message)

    def safe_mode(self, reason: str) -> None:
        self.notifier.notify("SAFE_MODE", reason)
