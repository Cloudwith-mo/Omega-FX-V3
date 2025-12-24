"""Safe mode latch for operational failures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ftmo_bot.monitoring.monitor import Monitor


@dataclass(frozen=True)
class SafeModeState:
    enabled: bool
    reason: Optional[str]
    since: Optional[datetime]


class SafeModeController:
    def __init__(
        self,
        path: str | Path,
        latched: bool = True,
        monitor: Optional[Monitor] = None,
        audit_log: Optional[object] = None,
    ) -> None:
        self.path = Path(path)
        self.latched = latched
        self.monitor = monitor
        self._audit_log = audit_log
        self._state = self._load_state()

    def _log(self, event: str, payload: dict) -> None:
        if self._audit_log is None:
            return
        self._audit_log.log(event, payload)

    def _load_state(self) -> SafeModeState:
        if not self.path.exists():
            return SafeModeState(False, None, None)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        since = payload.get("since")
        return SafeModeState(
            enabled=bool(payload.get("enabled", False)),
            reason=payload.get("reason"),
            since=datetime.fromisoformat(since) if since else None,
        )

    def _save_state(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "enabled": self._state.enabled,
            "reason": self._state.reason,
            "since": self._state.since.isoformat() if self._state.since else None,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @property
    def state(self) -> SafeModeState:
        return self._state

    def enable(self, reason: str) -> None:
        if self._state.enabled and self.latched:
            return
        self._state = SafeModeState(True, reason, datetime.now(timezone.utc))
        self._save_state()
        if self.monitor is not None:
            self.monitor.safe_mode(reason)
        self._log("safe_mode", {"enabled": True, "reason": reason})

    def clear(self, reason: str = "manual") -> None:
        self._state = SafeModeState(False, reason, datetime.now(timezone.utc))
        self._save_state()
        self._log("safe_mode", {"enabled": False, "reason": reason})
