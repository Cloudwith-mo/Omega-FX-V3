"""Drift detection for broker/journal mismatches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ftmo_bot.execution.models import ReconcileReport
from ftmo_bot.runtime.safe_mode import SafeModeController


@dataclass
class DriftEntry:
    first_seen: datetime
    last_seen: datetime
    alerted: bool


class DriftTracker:
    def __init__(
        self,
        path: str | Path,
        max_age_seconds: float = 60.0,
        audit_log: Optional[object] = None,
        safe_mode: Optional[SafeModeController] = None,
    ) -> None:
        self.path = Path(path)
        self.max_age_seconds = max(0.0, max_age_seconds)
        self._audit_log = audit_log
        self._safe_mode = safe_mode
        self._state = self._load_state()

    def _log(self, event: str, payload: dict) -> None:
        if self._audit_log is None:
            return
        self._audit_log.log(event, payload)

    def _load_state(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload.get("mismatches", {})

    def _save_state(self) -> None:
        payload = {
            "mismatches": self._state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def update(self, report: ReconcileReport, now: Optional[datetime] = None) -> None:
        if now is None:
            now = datetime.now(timezone.utc)

        current_keys: set[str] = set()
        for order_id in report.missing_in_broker:
            current_keys.add(f"missing_in_broker:{order_id}")
        for order_id in report.missing_in_journal:
            current_keys.add(f"missing_in_journal:{order_id}")

        # New or existing mismatches
        for key in current_keys:
            entry = self._state.get(key)
            if entry is None:
                self._state[key] = {
                    "first_seen": now.isoformat(),
                    "last_seen": now.isoformat(),
                    "alerted": False,
                }
                kind, order_id = key.split(":", 1)
                self._log("drift_detected", {"kind": kind, "order_id": order_id})
                continue

            entry["last_seen"] = now.isoformat()
            first_seen = datetime.fromisoformat(entry["first_seen"])
            duration = (now - first_seen).total_seconds()
            if duration >= self.max_age_seconds and not entry.get("alerted"):
                entry["alerted"] = True
                kind, order_id = key.split(":", 1)
                self._log(
                    "drift_unresolved",
                    {
                        "kind": kind,
                        "order_id": order_id,
                        "duration_seconds": duration,
                    },
                )
                if self._safe_mode is not None:
                    self._safe_mode.enable(f"Drift unresolved: {kind} {order_id}")

        # Resolved mismatches
        for key in list(self._state.keys()):
            if key in current_keys:
                continue
            entry = self._state.pop(key)
            first_seen = datetime.fromisoformat(entry["first_seen"])
            last_seen = datetime.fromisoformat(entry["last_seen"])
            duration = (last_seen - first_seen).total_seconds()
            kind, order_id = key.split(":", 1)
            self._log(
                "drift_resolved",
                {
                    "kind": kind,
                    "order_id": order_id,
                    "duration_seconds": duration,
                },
            )

        self._save_state()
