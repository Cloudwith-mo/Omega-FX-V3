"""Daily bundle generation for audit trails."""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def _filter_audit_log(
    source: Path,
    target: Path,
    bundle_day: date,
    timezone: str,
) -> int:
    tz = ZoneInfo(timezone)
    count = 0
    with source.open("r", encoding="utf-8") as handle, target.open("w", encoding="utf-8") as out:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = _parse_ts(record.get("ts", ""))
            if timestamp is None:
                continue
            local_day = timestamp.astimezone(tz).date()
            if local_day != bundle_day:
                continue
            out.write(json.dumps(record, default=str))
            out.write("\n")
            count += 1
    return count


def generate_daily_bundle(
    run_id: str,
    config_path: Path,
    output_dir: Path,
    timezone: str,
    audit_log_path: Path,
    status_path: Path,
    run_state_path: Path,
    safe_mode_path: Path,
    daily_metrics_path: Path | None = None,
    drift_state_path: Path | None = None,
    journal_path: Path | None = None,
    state_snapshot_path: Path | None = None,
    bundle_day: date | None = None,
) -> Path:
    tz = ZoneInfo(timezone)
    if bundle_day is None:
        bundle_day = datetime.now(tz).date()

    bundle_dir = output_dir / run_id / bundle_day.isoformat()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, str] = {}

    def copy_if_exists(source: Path | None, name: str) -> None:
        if source is None or not source.exists():
            return
        target = bundle_dir / name
        shutil.copy2(source, target)
        manifest[name] = str(source)

    copy_if_exists(config_path, "config.yaml")
    lock_path = config_path.with_suffix(config_path.suffix + ".lock.json")
    copy_if_exists(lock_path, "config.lock.json")
    copy_if_exists(run_state_path, "run_state.json")
    copy_if_exists(safe_mode_path, "safe_mode.json")
    copy_if_exists(status_path, "status.json")
    copy_if_exists(state_snapshot_path, "state_snapshot.json")
    copy_if_exists(Path("runtime") / "farm_status.json", "farm_status.json")
    if journal_path:
        copy_if_exists(journal_path, "journal.db")
    if drift_state_path:
        copy_if_exists(drift_state_path, "drift_state.json")
    if daily_metrics_path:
        copy_if_exists(daily_metrics_path, "daily_metrics.json")
        if daily_metrics_path.exists():
            try:
                metrics_payload = json.loads(daily_metrics_path.read_text(encoding="utf-8"))
                day_key = bundle_day.isoformat()
                day_entry = metrics_payload.get("days", {}).get(day_key)
                if day_entry:
                    day_path = bundle_dir / "daily_metrics_day.json"
                    day_path.write_text(json.dumps(day_entry, indent=2), encoding="utf-8")
                    manifest["daily_metrics_day.json"] = f"{daily_metrics_path}#{day_key}"
            except json.JSONDecodeError:
                pass

    if audit_log_path.exists():
        audit_target = bundle_dir / "audit.log"
        line_count = _filter_audit_log(audit_log_path, audit_target, bundle_day, timezone)
        manifest["audit.log"] = f"{audit_log_path} ({line_count} lines)"

    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return bundle_dir
