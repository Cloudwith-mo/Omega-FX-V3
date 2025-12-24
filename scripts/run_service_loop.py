from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ftmo_bot.config import compute_config_hash, freeze_config, load_config, verify_config_lock
from ftmo_bot.execution import ExecutionEngine, MT5Broker, OrderJournal, PaperBroker, RequestThrottle
from dataclasses import asdict

from ftmo_bot.monitoring import AuditLog, LogNotifier, Monitor, build_runtime_status
from ftmo_bot.strategy import fetch_symbol_specs
from ftmo_bot.risk import RiskGovernor
from ftmo_bot.rule_engine import RuleEngine
from ftmo_bot.rule_engine.time import trading_day_for
from ftmo_bot.runtime import AsyncServiceConfig, AsyncServiceLoop, create_run_context
from ftmo_bot.runtime.bundles import generate_daily_bundle
from ftmo_bot.runtime.metrics import update_daily_metrics
from ftmo_bot.runtime.safe_mode import SafeModeController
from ftmo_bot.runtime.state_store import load_rule_state
from ftmo_bot.runtime.status_store import write_runtime_status


def _load_run_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_run_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _build_broker(broker: str, account: str | None) -> object:
    broker = broker.lower()
    if broker == "paper":
        return PaperBroker(fill_on_place=True)
    if broker != "mt5":
        raise ValueError(f"Unsupported broker: {broker}")

    login = os.getenv("MT5_LOGIN") or account
    server = os.getenv("MT5_SERVER")
    password = os.getenv("MT5_PASSWORD")
    path = os.getenv("MT5_PATH") or None
    if not login or not server or not password:
        raise ValueError("MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER are required for mt5 broker")

    magic = int(os.getenv("MT5_MAGIC", "901003"))
    deviation = int(os.getenv("MT5_DEVIATION", "10"))
    filling_mode = os.getenv("MT5_FILLING", "fok")
    time_type = os.getenv("MT5_TIME_TYPE", "gtc")

    return MT5Broker(
        login=int(login),
        password=password,
        server=server,
        path=path,
        magic=magic,
        deviation=deviation,
        filling_mode=filling_mode,
        time_type=time_type,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the asyncio service loop (fast/bar/reconcile/health).")
    parser.add_argument("--config", default="configs/ftmo_v1.yaml")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--clear-safe", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)

    lock_path = freeze_config(config_path)
    if not verify_config_lock(config_path, lock_path):
        raise RuntimeError("Config lock mismatch; run freeze_config first")

    run_state_path = Path("runtime") / "run_state.json"
    config_hash = compute_config_hash(config_path)
    run_id = args.run_id
    last_bundle_day: str | None = None

    if args.resume:
        state = _load_run_state(run_state_path)
        if state:
            if state.get("config_hash") != config_hash:
                raise RuntimeError("Config changed since last run; refuse to resume")
            run_id = state.get("run_id")
            last_bundle_day = state.get("last_bundle_day")

    context = create_run_context(config_path, config.run_id_prefix, run_id=run_id)
    _save_run_state(
        run_state_path,
        {
            "run_id": context.run_id,
            "config_hash": context.config_hash,
            "config_path": str(context.config_path),
            "started_at": context.started_at.isoformat(),
            "last_bundle_day": last_bundle_day,
        },
    )

    monitor = Monitor(LogNotifier())
    audit = AuditLog(Path(config.monitoring.audit_log_path), run_id=context.run_id, config_hash=context.config_hash)
    audit.log("run_start", {"config": str(config_path), "lock": str(lock_path)})

    safe_mode = SafeModeController(
        config.runtime.safe_mode_path,
        latched=config.runtime.safe_mode_latched,
        monitor=monitor,
        audit_log=audit,
    )
    if args.clear_safe:
        safe_mode.clear("manual_clear")

    throttle_config = config.execution.throttle
    throttle = RequestThrottle(
        max_requests_per_day=int(throttle_config.get("max_requests_per_day", 1500)),
        max_modifications_per_minute=int(throttle_config.get("max_modifications_per_minute", 30)),
        min_seconds_between_requests=int(throttle_config.get("min_seconds_between_requests", 0)),
        timezone=config.rule_spec.timezone,
    )

    journal_path = Path("runtime") / f"journal-{context.run_id}.db"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal = OrderJournal(journal_path)

    broker = _build_broker(config.execution.broker, config.execution.account)
    engine = ExecutionEngine(broker, journal, throttle=throttle, audit_log=audit, monitor=monitor)

    rule_engine = RuleEngine(config.rule_spec)
    governor = RiskGovernor(rule_engine, audit_log=audit, monitor=monitor)

    symbol_specs = fetch_symbol_specs(broker, config.instruments)
    if symbol_specs:
        audit.log(
            "symbol_specs",
            {symbol: asdict(spec) for symbol, spec in symbol_specs.items()},
        )

    status_path = Path(config.runtime.status_path)
    state_snapshot_path = Path(config.runtime.state_snapshot_path)
    daily_bundle_dir = Path(config.runtime.daily_bundle_dir)
    daily_metrics_path = Path(config.runtime.daily_metrics_path)
    last_status_time = 0.0
    last_state_mtime: float | None = None

    tz = ZoneInfo(config.rule_spec.timezone)

    async def fast_loop() -> None:
        nonlocal last_status_time, last_state_mtime, last_bundle_day
        now_mono = time.monotonic()
        if now_mono - last_status_time < config.runtime.status_interval_seconds:
            return
        last_status_time = now_mono

        state = None
        if state_snapshot_path.exists():
            mtime = state_snapshot_path.stat().st_mtime
            if last_state_mtime is None or mtime != last_state_mtime:
                last_state_mtime = mtime
                state = load_rule_state(state_snapshot_path)
                state.roll_day_if_needed(config.rule_spec.timezone)
                state.update_drawdown_start(config.rule_spec.drawdown_limit_pct)
                status = build_runtime_status(state, governor)
                write_runtime_status(status_path, status)
                update_daily_metrics(daily_metrics_path, state, status, config.rule_spec.timezone)
                governor.check_inactivity(state)

        if not config.runtime.daily_bundle_enabled:
            return

        if state is None:
            now = datetime.now(tz)
            bundle_day = now.date()
        else:
            bundle_day = trading_day_for(state.now, config.rule_spec.timezone)

        if last_bundle_day != bundle_day.isoformat():
            generate_daily_bundle(
                run_id=context.run_id,
                config_path=config_path,
                output_dir=daily_bundle_dir,
                timezone=config.rule_spec.timezone,
                audit_log_path=Path(config.monitoring.audit_log_path),
                status_path=status_path,
                run_state_path=run_state_path,
                safe_mode_path=Path(config.runtime.safe_mode_path),
                daily_metrics_path=daily_metrics_path if daily_metrics_path.exists() else None,
                journal_path=journal_path if journal_path.exists() else None,
                state_snapshot_path=state_snapshot_path if state_snapshot_path.exists() else None,
                bundle_day=bundle_day,
            )
            last_bundle_day = bundle_day.isoformat()
            state_payload = _load_run_state(run_state_path) or {}
            state_payload["last_bundle_day"] = last_bundle_day
            _save_run_state(run_state_path, state_payload)

    async def bar_loop() -> None:
        if safe_mode.state.enabled:
            return

    service = AsyncServiceLoop(
        engine,
        config=AsyncServiceConfig(
            fast_loop_interval_seconds=config.runtime.fast_loop_interval_seconds,
            bar_loop_interval_seconds=config.runtime.bar_loop_interval_seconds,
            reconcile_interval_seconds=config.runtime.reconcile_interval_seconds,
            health_check_interval_seconds=config.runtime.health_check_interval_seconds,
        ),
        safe_mode=safe_mode,
        audit_log=audit,
    )

    print(f"Service loop started (run_id={context.run_id}, broker={config.execution.broker})")

    async def _runner() -> None:
        stop_event = asyncio.Event()
        await service.run_forever(stop_event, fast_callback=fast_loop, bar_callback=bar_loop)

    try:
        asyncio.run(_runner())
    except KeyboardInterrupt:
        audit.log("run_stop", {"reason": "keyboard_interrupt"})
        print("Service loop stopped")


if __name__ == "__main__":
    main()
