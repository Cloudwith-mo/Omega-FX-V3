"""Notification backends."""

from __future__ import annotations

from dataclasses import dataclass


class Notifier:
    def notify(self, event: str, message: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class LogNotifier(Notifier):
    prefix: str = "[FTMO]"

    def notify(self, event: str, message: str) -> None:
        print(f"{self.prefix} {event}: {message}")
