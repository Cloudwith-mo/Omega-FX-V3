from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
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


def _max_events_in_window(timestamps: list[datetime], window: timedelta) -> int:
    if not timestamps:
        return 0
    times = sorted(timestamps)
    max_count = 1
    left = 0
    for right in range(len(times)):
        while times[right] - times[left] > window:
            left += 1
        max_count = max(max_count, right - left + 1)
    return max_count


@dataclass
class DaySummary:
    day: str
    trades: int
    trading_day: bool
    max_drawdown_pct: float | None
    max_intraday_drawdown_pct: float | None
    min_daily_headroom: float | None
    min_max_headroom: float | None
    daily_buffer_stops: list[dict[str, Any]]
    breach_events: int
    unresolved_drift_events: int
    duplicate_order_events: int
    safe_mode_events: list[dict[str, str]]
    restart_events: int
    reconnect_events: int
    disconnect_events: int
    max_entries_15m: int
    max_modifications_1m: int
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
        config = _load_yaml(day_dir / "config.yaml")

        max_trades_per_day = None
        max_entries_per_15m = 2
        max_modifications_per_minute = None
        if config:
            strategy_params = (config.get("strategy") or {}).get("parameters", {})
            max_trades_per_day = strategy_params.get("max_trades_per_day")
            max_entries_per_15m = strategy_params.get("max_entries_per_15min", max_entries_per_15m)
            throttle = (config.get("execution") or {}).get("throttle", {})
            max_modifications_per_minute = throttle.get("max_modifications_per_minute")

        trades = _count_trades_from_state(state, day)
        if trades is None:
            trades = _count_trades_from_events(events)
            if events and state is None:
                notes.append(f"{day}: trades from audit log (state snapshot missing)")

        if metrics_day:
            max_drawdown_pct = metrics_day.get("max_drawdown_pct")
            max_intraday_drawdown_pct = metrics_day.get("max_intraday_drawdown_pct")
            min_daily_headroom = metrics_day.get("min_daily_headroom")
            min_max_headroom = metrics_day.get("min_max_headroom")
        elif status:
            max_drawdown_pct = status.get("drawdown_pct")
            max_intraday_drawdown_pct = None
            headroom = status.get("headroom", {})
            min_daily_headroom = headroom.get("daily")
            min_max_headroom = headroom.get("maximum")
            notes.append(f"{day}: metrics missing, using status snapshot")
        else:
            max_drawdown_pct = None
            max_intraday_drawdown_pct = None
            min_daily_headroom = None
            min_max_headroom = None
            notes.append(f"{day}: no metrics or status")

        daily_buffer_stops: list[dict[str, Any]] = []
        breach_events = 0
        unresolved_drift_events = 0
        duplicate_order_events = 0
        safe_mode_events = []
        restart_events = 0
        reconnect_events = 0
        disconnect_events = 0
        buffer_breaches = 0
        hard_limit_breaches = 0

        order_times: list[datetime] = []
        modify_times: list[datetime] = []

        for event in events:
            event_name = event.get("event")
            reason = _extract_reason(event)
            payload = event.get("payload") or {}
            ts = _parse_ts(event.get("ts", ""))

            if event_name == "run_start":
                restart_events += 1
            if event_name == "reconnect":
                reconnect_events += 1
            if event_name == "disconnect":
                disconnect_events += 1
            if event_name == "safe_mode":
                if payload.get("enabled"):
                    safe_mode_events.append({"reason": payload.get("reason", "")})
            if event_name == "daily_buffer_stop":
                daily_buffer_stops.append(payload)
            if event_name == "rule_violation":
                breach_events += 1
            if event_name == "drift_unresolved":
                unresolved_drift_events += 1
            if event_name == "duplicate_order_detected":
                duplicate_order_events += 1
            if event_name in {"state_check", "pre_trade"}:
                reason_lower = reason.lower()
                if "buffer" in reason_lower:
                    buffer_breaches += 1
                if "hard limit" in reason_lower:
                    hard_limit_breaches += 1

            if event_name == "order_submitted" and ts:
                order_times.append(ts)
            if event_name == "order_modified" and ts:
                modify_times.append(ts)

        max_entries_15m = _max_events_in_window(order_times, timedelta(minutes=15))
        max_modifications_1m = _max_events_in_window(modify_times, timedelta(minutes=1))

        if max_trades_per_day is not None and trades > max_trades_per_day:
            notes.append(f"{day}: trades exceeded max_trades_per_day ({trades} > {max_trades_per_day})")
        if max_entries_per_15m is not None and max_entries_15m > max_entries_per_15m:
            notes.append(f"{day}: max entries/15m exceeded ({max_entries_15m} > {max_entries_per_15m})")
        if max_modifications_per_minute is not None and max_modifications_1m > max_modifications_per_minute:
            notes.append(
                f"{day}: modifications/min exceeded ({max_modifications_1m} > {max_modifications_per_minute})"
            )

        summaries.append(
            DaySummary(
                day=day,
                trades=trades,
                trading_day=trades > 0,
                max_drawdown_pct=max_drawdown_pct,
                max_intraday_drawdown_pct=max_intraday_drawdown_pct,
                min_daily_headroom=min_daily_headroom,
                min_max_headroom=min_max_headroom,
                daily_buffer_stops=daily_buffer_stops,
                breach_events=breach_events,
                unresolved_drift_events=unresolved_drift_events,
                duplicate_order_events=duplicate_order_events,
                safe_mode_events=safe_mode_events,
                restart_events=restart_events,
                reconnect_events=reconnect_events,
                disconnect_events=disconnect_events,
                max_entries_15m=max_entries_15m,
                max_modifications_1m=max_modifications_1m,
                buffer_breaches=buffer_breaches,
                hard_limit_breaches=hard_limit_breaches,
            )
        )

    total_trades = sum(day.trades for day in summaries)
    trading_days = sum(1 for day in summaries if day.trading_day)
    max_intraday_dd = max(
        (day.max_intraday_drawdown_pct for day in summaries if day.max_intraday_drawdown_pct is not None),
        default=None,
    )
    max_overall_dd = max(
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
    total_reconnects = sum(day.reconnect_events for day in summaries)
    total_disconnects = sum(day.disconnect_events for day in summaries)
    total_buffer_stops = sum(len(day.daily_buffer_stops) for day in summaries)
    total_breaches = sum(day.breach_events for day in summaries)
    total_drift_unresolved = sum(day.unresolved_drift_events for day in summaries)
    total_duplicates = sum(day.duplicate_order_events for day in summaries)

    pass_daily_buffer_policy = total_buffer_stops <= 1
    pass_internal_buffers = total_breaches == 0

    summary = {
        "run_id": run_dir.name,
        "days": [day.day for day in summaries],
        "totals": {
            "total_trades": total_trades,
            "trades_per_day": {day.day: day.trades for day in summaries},
            "trading_days": trading_days,
            "max_intraday_drawdown_pct": max_intraday_dd,
            "max_overall_drawdown_pct": max_overall_dd,
            "min_daily_headroom": min_daily_headroom,
            "min_max_headroom": min_max_headroom,
            "daily_buffer_stop_count": total_buffer_stops,
            "breach_events": total_breaches,
            "unresolved_drift_events": total_drift_unresolved,
            "duplicate_order_events": total_duplicates,
            "safe_mode_events": total_safe_modes,
            "restart_events": total_restarts,
            "reconnect_events": total_reconnects,
            "disconnect_events": total_disconnects,
            "pass_daily_buffer_policy": pass_daily_buffer_policy,
            "pass_internal_buffers": pass_internal_buffers,
        },
        "daily_buffer_stop_events": {
            day.day: day.daily_buffer_stops for day in summaries if day.daily_buffer_stops
        },
        "notes": notes,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    table_lines = [
        "day,trades,min_daily_headroom,min_max_headroom,max_intraday_drawdown_pct,max_overall_drawdown_pct,"
        "buffer_stops,breaches,drift_unresolved,duplicates,restarts,reconnects,disconnections,"
        "max_entries_15m,max_modifications_1m",
    ]
    for day in summaries:
        table_lines.append(
            f"{day.day},{day.trades},{day.min_daily_headroom},{day.min_max_headroom},"
            f"{day.max_intraday_drawdown_pct},{day.max_drawdown_pct},{len(day.daily_buffer_stops)},"
            f"{day.breach_events},{day.unresolved_drift_events},{day.duplicate_order_events},"
            f"{day.restart_events},{day.reconnect_events},{day.disconnect_events},"
            f"{day.max_entries_15m},{day.max_modifications_1m}"
        )
    table_path = output_dir / "summary_table.csv"
    table_path.write_text("\n".join(table_lines), encoding="utf-8")

    print(f"Summary written to {summary_path}")
    print(f"Table written to {table_path}")


if __name__ == "__main__":
    main()
