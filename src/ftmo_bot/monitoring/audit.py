"""Append-only audit log for decisions and order events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class AuditLog:
    path: Path
    run_id: str | None = None
    config_hash: str | None = None

    def __init__(self, path: str | Path, run_id: str | None = None, config_hash: str | None = None) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.config_hash = config_hash
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, payload: dict[str, Any]) -> None:
        record = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "run_id": self.run_id,
            "config_hash": self.config_hash,
            "event": event,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str))
            handle.write("\n")
