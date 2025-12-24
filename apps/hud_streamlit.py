from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import streamlit as st


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _format_currency(value: float) -> str:
    return f"${value:,.2f}"


def main() -> None:
    st.set_page_config(page_title="FTMO Bot HUD", layout="wide")
    st.title("FTMO Bot v3 — Runtime HUD")

    default_status_path = os.getenv("FTMO_STATUS_PATH", "runtime/status.json")
    default_safe_mode_path = os.getenv("FTMO_SAFE_MODE_PATH", "runtime/safe_mode.json")

    status_path = Path(st.sidebar.text_input("Status path", value=default_status_path))
    safe_mode_path = Path(st.sidebar.text_input("Safe mode path", value=default_safe_mode_path))

    status = _load_json(status_path)
    safe_mode = _load_json(safe_mode_path)

    if status is None:
        st.warning(f"No status found at {status_path}")
        return

    now = status.get("now")
    if now:
        try:
            now = datetime.fromisoformat(now)
        except ValueError:
            now = None

    safe_enabled = bool(safe_mode.get("enabled")) if safe_mode else False
    safe_reason = safe_mode.get("reason") if safe_mode else None

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Equity", _format_currency(status.get("equity", 0.0)))
    col_b.metric("Balance", _format_currency(status.get("balance", 0.0)))
    col_c.metric("Daily Headroom", _format_currency(status.get("headroom", {}).get("daily", 0.0)))
    col_d.metric("Max Headroom", _format_currency(status.get("headroom", {}).get("maximum", 0.0)))

    col_e, col_f, col_g, col_h = st.columns(4)
    col_e.metric("Open Positions", str(status.get("open_positions", 0)))
    col_f.metric("Trading Days", str(status.get("trading_days", 0)))
    col_g.metric("Days Since Trade", str(status.get("days_since_last_trade", "n/a")))
    col_h.metric("Drawdown %", f"{status.get('drawdown_pct', 0.0) * 100:.2f}%")

    progress = status.get("target_progress", 0.0)
    st.subheader("Target Progress")
    st.progress(min(max(progress, 0.0), 1.0))
    st.caption(f"Progress: {progress * 100:.2f}%")

    st.subheader("Safe Mode")
    if safe_enabled:
        st.error(f"SAFE MODE: {safe_reason or 'enabled'}")
    else:
        st.success("Safe mode not active")

    st.subheader("Details")
    st.json({
        "stage": status.get("stage"),
        "day_start_equity": status.get("day_start_equity"),
        "day_start_time": status.get("day_start_time"),
        "min_trading_days_remaining": status.get("min_trading_days_remaining"),
        "drawdown_days": status.get("drawdown_days"),
        "buffer_daily": status.get("headroom", {}).get("daily_buffer"),
        "buffer_max": status.get("headroom", {}).get("max_buffer"),
        "last_update": now.isoformat() if isinstance(now, datetime) else status.get("now"),
    })


if __name__ == "__main__":
    main()
