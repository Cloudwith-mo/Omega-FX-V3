from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _parse_audit_log(path: Path) -> list[dict[str, Any]]:
    events = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _select_run_dir(root: Path, run_id: str | None) -> Path:
    if run_id:
        candidate = root / run_id
        if not candidate.exists():
            raise FileNotFoundError(f"Run id not found: {run_id}")
        return candidate
    candidates = [path for path in root.iterdir() if path.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No bundles found in {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _day_dirs(run_dir: Path) -> list[Path]:
    return sorted([path for path in run_dir.iterdir() if path.is_dir()])


def _count_trades_from_state(state: dict | None, day: str) -> int | None:
    if not state or "trades" not in state:
        return None
    count = 0
    for trade in state.get("trades", []):
        entry_time = trade.get("entry_time")
        if not entry_time:
            continue
        if entry_time.startswith(day):
            count += 1
    return count


def _count_trades_from_events(events: list[dict[str, Any]]) -> int:
    return sum(1 for event in events if event.get("event") == "order_submitted")


def _extract_reason(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    reason = payload.get("reason")
    if reason:
        return str(reason)
    return str(event.get("reason", ""))


@dataclass
class DaySummary:
    day: str
    trades: int
    trading_day: bool
    max_drawdown_pct: float | None
    min_daily_headroom: float | None
    min_max_headroom: float | None
    safe_mode_events: list[dict[str, str]]
    restart_events: int
    disconnect_events: int
    buffer_breaches: int
    hard_limit_breaches: int


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", default="reports/daily_bundles")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--last", type=int, default=5)
    parser.add_argument("--output-dir", default="reports/bundle_summary")
    args = parser.parse_args()

    root = Path(args.bundle_root)
    run_dir = _select_run_dir(root, args.run_id)
    day_dirs = _day_dirs(run_dir)
    if not day_dirs:
        raise FileNotFoundError(f"No day bundles found in {run_dir}")

    day_dirs = day_dirs[-args.last :]

    summaries: list[DaySummary] = []
    notes: list[str] = []

    for day_dir in day_dirs:
        day = day_dir.name
        metrics_day = _load_json(day_dir / "daily_metrics_day.json")
        status = _load_json(day_dir / "status.json")
        state = _load_json(day_dir / "state_snapshot.json")
        events = _parse_audit_log(day_dir / "audit.log")

        trades = _count_trades_from_state(state, day)
        if trades is None:
            trades = _count_trades_from_events(events)
            if events and state is None:
                notes.append(f"{day}: trades from audit log (state snapshot missing)")

        if metrics_day:
            max_drawdown_pct = metrics_day.get("max_drawdown_pct")
            min_daily_headroom = metrics_day.get("min_daily_headroom")
            min_max_headroom = metrics_day.get("min_max_headroom")
        elif status:
            max_drawdown_pct = status.get("drawdown_pct")
            headroom = status.get("headroom", {})
            min_daily_headroom = headroom.get("daily")
            min_max_headroom = headroom.get("maximum")
            notes.append(f"{day}: metrics missing, using status snapshot")
        else:
            max_drawdown_pct = None
            min_daily_headroom = None
            min_max_headroom = None
            notes.append(f"{day}: no metrics or status")

        safe_mode_events = []
        restart_events = 0
        disconnect_events = 0
        buffer_breaches = 0
        hard_limit_breaches = 0

        for event in events:
            event_name = event.get("event")
            reason = _extract_reason(event)
            if event_name == "run_start":
                restart_events += 1
            if event_name == "safe_mode":
                payload = event.get("payload") or {}
                if payload.get("enabled"):
                    safe_mode_events.append({"reason": payload.get("reason", "")})
                    if "connection" in str(payload.get("reason", "")).lower():
                        disconnect_events += 1
            if event_name in {"state_check", "pre_trade"}:
                reason_lower = reason.lower()
                if "buffer" in reason_lower:
                    buffer_breaches += 1
                if "hard limit" in reason_lower:
                    hard_limit_breaches += 1

        summaries.append(
            DaySummary(
                day=day,
                trades=trades,
                trading_day=trades > 0,
                max_drawdown_pct=max_drawdown_pct,
                min_daily_headroom=min_daily_headroom,
                min_max_headroom=min_max_headroom,
                safe_mode_events=safe_mode_events,
                restart_events=restart_events,
                disconnect_events=disconnect_events,
                buffer_breaches=buffer_breaches,
                hard_limit_breaches=hard_limit_breaches,
            )
        )

    total_trades = sum(day.trades for day in summaries)
    trading_days = sum(1 for day in summaries if day.trading_day)
    max_intraday_dd = max(
        (day.max_drawdown_pct for day in summaries if day.max_drawdown_pct is not None),
        default=None,
    )
    min_daily_headroom = min(
        (day.min_daily_headroom for day in summaries if day.min_daily_headroom is not None),
        default=None,
    )
    min_max_headroom = min(
        (day.min_max_headroom for day in summaries if day.min_max_headroom is not None),
        default=None,
    )
    total_safe_modes = sum(len(day.safe_mode_events) for day in summaries)
    total_restarts = sum(day.restart_events for day in summaries)
    total_disconnects = sum(day.disconnect_events for day in summaries)
    total_buffer_breaches = sum(day.buffer_breaches for day in summaries)
    total_hard_limits = sum(day.hard_limit_breaches for day in summaries)

    pass_internal_buffers = total_buffer_breaches <= 1 and total_hard_limits == 0

    summary = {
        "run_id": run_dir.name,
        "days": [day.day for day in summaries],
        "totals": {
            "total_trades": total_trades,
            "trades_per_day": {day.day: day.trades for day in summaries},
            "trading_days": trading_days,
            "max_intraday_drawdown_pct": max_intraday_dd,
            "min_daily_headroom": min_daily_headroom,
            "min_max_headroom": min_max_headroom,
            "safe_mode_events": total_safe_modes,
            "restart_events": total_restarts,
            "disconnect_events": total_disconnects,
            "buffer_breaches": total_buffer_breaches,
            "hard_limit_breaches": total_hard_limits,
            "pass_internal_buffers": pass_internal_buffers,
        },
        "notes": notes,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    table_lines = [
        "day,trades,min_daily_headroom,min_max_headroom,max_drawdown_pct,safe_modes,restarts,buffer_breaches",
    ]
    for day in summaries:
        table_lines.append(
            f"{day.day},{day.trades},{day.min_daily_headroom},{day.min_max_headroom},"
            f"{day.max_drawdown_pct},{len(day.safe_mode_events)},{day.restart_events},{day.buffer_breaches}"
        )
    table_path = output_dir / "summary_table.csv"
    table_path.write_text("\n".join(table_lines), encoding="utf-8")

    print(f"Summary written to {summary_path}")
    print(f"Table written to {table_path}")


if __name__ == "__main__":
    main()
