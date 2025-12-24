"""Run context creation and metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ftmo_bot.config.loader import compute_config_hash


@dataclass(frozen=True)
class RunContext:
    run_id: str
    config_path: Path
    config_hash: str
    started_at: datetime


def create_run_context(
    config_path: str | Path,
    run_id_prefix: str,
    run_id: Optional[str] = None,
) -> RunContext:
    path = Path(config_path)
    config_hash = compute_config_hash(path)
    started_at = datetime.now(timezone.utc)
    if run_id is None:
        stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{run_id_prefix}-{stamp}-{config_hash[:8]}"
    return RunContext(
        run_id=run_id,
        config_path=path,
        config_hash=config_hash,
        started_at=started_at,
    )
