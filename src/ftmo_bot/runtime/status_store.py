"""Helpers to store runtime status snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ftmo_bot.monitoring.status import RuntimeStatus


def write_runtime_status(path: str | Path, status: RuntimeStatus) -> None:
    payload = asdict(status)
    payload["now"] = status.now.isoformat()
    payload["day_start_time"] = status.day_start_time.isoformat()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_runtime_status(path: str | Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
