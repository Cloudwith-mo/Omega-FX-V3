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
from ftmo_bot.execution.broker import BrokerAdapter
from ftmo_bot.execution.models import BrokerOrder, ExecutionOrder, Position
from dataclasses import asdict

from ftmo_bot.monitoring import AuditLog, LogNotifier, Monitor, build_runtime_status
from ftmo_bot.strategy import StrategyContext, StrategyFarm, fetch_symbol_specs
from ftmo_bot.strategy.market_data import MT5BarFeed
from ftmo_bot.risk import RiskGovernor
from ftmo_bot.rule_engine import RuleEngine
from ftmo_bot.rule_engine.models import RuleState
from ftmo_bot.rule_engine.time import day_start_for, trading_day_for
from ftmo_bot.runtime import AsyncServiceConfig, AsyncServiceLoop, DriftTracker, create_run_context
from ftmo_bot.runtime.bundles import generate_daily_bundle
from ftmo_bot.runtime.metrics import update_daily_metrics
from ftmo_bot.runtime.safe_mode import SafeModeController
from ftmo_bot.runtime.state_store import load_rule_state, save_rule_state
from ftmo_bot.runtime.status_store import write_runtime_status


def _load_run_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_run_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class DisconnectToggleBroker(BrokerAdapter):
    def __init__(self, inner: BrokerAdapter, toggle_path: Path, audit_log: AuditLog | None = None) -> None:
        self.inner = inner
        self.toggle_path = toggle_path
        self._audit_log = audit_log
        self._active = False

    def _log(self, event: str, payload: dict) -> None:
        if self._audit_log is None:
            return
        self._audit_log.log(event, payload)

    def ping(self) -> bool:
        if self.toggle_path.exists():
            if not self._active:
                self._active = True
                self._log("disconnect_simulated", {"path": str(self.toggle_path)})
            return False
        if self._active:
            self._active = False
            self._log("disconnect_simulated_clear", {"path": str(self.toggle_path)})
        return self.inner.ping()

    def place_order(self, order):
        return self.inner.place_order(order)

    def cancel_order(self, broker_order_id: str) -> None:
        return self.inner.cancel_order(broker_order_id)

    def modify_order(self, broker_order_id: str, price: float | None = None) -> None:
        return self.inner.modify_order(broker_order_id, price=price)

    def list_open_orders(self):
        return self.inner.list_open_orders()

    def list_positions(self):
        return self.inner.list_positions()

    def get_symbol_spec(self, symbol: str):
        return self.inner.get_symbol_spec(symbol)

    def get_account_snapshot(self):
        return self.inner.get_account_snapshot()


def _build_broker(broker: str, account: str | None, initial_balance: float) -> BrokerAdapter:
    broker = broker.lower()
    if broker == "paper":
        return PaperBroker(fill_on_place=True, initial_balance=initial_balance)
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
    parser.add_argument("--simulate-disconnect-path", default=None)
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

    broker = _build_broker(config.execution.broker, config.execution.account, config.rule_spec.account_size)
    simulate_path = args.simulate_disconnect_path or os.getenv("FTMO_FORCE_DISCONNECT")
    if simulate_path:
        broker = DisconnectToggleBroker(broker, Path(simulate_path), audit_log=audit)
    engine = ExecutionEngine(
        broker,
        journal,
        throttle=throttle,
        audit_log=audit,
        monitor=monitor,
        duplicate_window_seconds=config.execution.duplicate_window_seconds,
        duplicate_block=config.execution.duplicate_block,
    )

    rule_engine = RuleEngine(config.rule_spec)
    governor = RiskGovernor(rule_engine, audit_log=audit, monitor=monitor)

    symbol_specs = fetch_symbol_specs(broker, config.instruments)
    if symbol_specs:
        audit.log(
            "symbol_specs",
            {symbol: asdict(spec) for symbol, spec in symbol_specs.items()},
        )

    farm = None
    bar_feed = None
    farm_status_path = Path("runtime") / "farm_status.json"
    if config.farm.enabled:
        if config.execution.broker != "mt5":
            audit.log("farm_disabled", {"reason": "farm requires mt5 broker"})
        else:
            context = StrategyContext(
                timezone=config.rule_spec.timezone,
                initial_balance=config.rule_spec.account_size,
                symbol_specs=symbol_specs or None,
            )
            farm = StrategyFarm(config.farm, config.rule_spec, context, baseline_strategy=config.strategy)
            farm_params = (config.farm.strategies[0].parameters if config.farm.strategies else config.strategy.parameters)
            farm_timeframe = str(farm_params.get("timeframe", "M15"))
            bar_feed = MT5BarFeed(config.instruments, farm_timeframe, config.rule_spec.timezone)

    status_path = Path(config.runtime.status_path)
    state_snapshot_path = Path(config.runtime.state_snapshot_path)
    daily_bundle_dir = Path(config.runtime.daily_bundle_dir)
    daily_metrics_path = Path(config.runtime.daily_metrics_path)
    drift_state_path = Path(config.runtime.drift_state_path)
    last_status_time = 0.0
    last_connection_ok: bool | None = None

    tz = ZoneInfo(config.rule_spec.timezone)
    state_cache = load_rule_state(state_snapshot_path) if state_snapshot_path.exists() else None

    async def fast_loop() -> None:
        nonlocal last_status_time, last_bundle_day, state_cache
        now_mono = time.monotonic()
        if now_mono - last_status_time < config.runtime.status_interval_seconds:
            return
        last_status_time = now_mono

        now = datetime.now(tz).astimezone()
        account = broker.get_account_snapshot()
        if account is None:
            audit.log("account_snapshot_missing", {"reason": "broker returned None"})
            equity = state_cache.equity if state_cache else config.rule_spec.account_size
            balance = state_cache.balance if state_cache else config.rule_spec.account_size
        else:
            equity = account.equity
            balance = account.balance

        positions = list(broker.list_positions())
        open_orders = list(broker.list_open_orders())

        if state_cache is None:
            state_cache = RuleState(
                now=now,
                equity=equity,
                balance=balance,
                day_start_equity=equity,
                day_start_time=day_start_for(now, config.rule_spec.timezone),
                initial_balance=config.rule_spec.account_size,
            )
            state_cache.stage_start_time = now

        state_cache.now = now
        state_cache.equity = equity
        state_cache.balance = balance
        state_cache.floating_pnl = equity - balance
        state_cache.open_positions = len(positions)
        state_cache.roll_day_if_needed(config.rule_spec.timezone)
        state_cache.update_drawdown_start(config.rule_spec.drawdown_limit_pct)

        decision = governor.evaluate_state(state_cache)
        status = build_runtime_status(state_cache, governor)
        write_runtime_status(status_path, status)
        update_daily_metrics(daily_metrics_path, state_cache, status, config.rule_spec.timezone)
        governor.check_inactivity(state_cache)

        local_time = state_cache.now.astimezone(tz)
        day_start_local = state_cache.day_start_time.astimezone(tz)
        day_start_utc = state_cache.day_start_time.astimezone(ZoneInfo("UTC"))

        def serialize_order(order: BrokerOrder) -> dict:
            return {
                "client_order_id": order.client_order_id,
                "broker_order_id": order.broker_order_id,
                "status": order.status,
                "symbol": order.symbol,
                "side": order.side,
                "volume": order.volume,
                "price": order.price,
                "time": order.time.isoformat(),
            }

        def serialize_position(pos: Position) -> dict:
            return {
                "symbol": pos.symbol,
                "side": pos.side,
                "volume": pos.volume,
                "entry_price": pos.entry_price,
                "unrealized_pnl": pos.unrealized_pnl,
            }
        extra = {
            "timestamp_utc": state_cache.now.isoformat(),
            "timestamp_local": local_time.isoformat(),
            "open_orders": len(open_orders),
            "open_positions": len(positions),
            "orders": [serialize_order(order) for order in open_orders],
            "positions": [serialize_position(pos) for pos in positions],
            "headroom": {"daily": status.headroom.daily, "max": status.headroom.maximum},
            "day_start_local": day_start_local.isoformat(),
            "day_start_utc": day_start_utc.isoformat(),
            "safe_mode": {
                "enabled": safe_mode.state.enabled,
                "reason": safe_mode.state.reason,
                "since": safe_mode.state.since.isoformat() if safe_mode.state.since else None,
            },
            "last_decision": {
                "allow": decision.allow,
                "reason": decision.reason,
                "flatten": decision.flatten,
                "reduce_only": decision.reduce_only,
            },
        }
        if account is not None:
            extra["account"] = {
                "equity": account.equity,
                "balance": account.balance,
                "margin": account.margin,
                "free_margin": account.free_margin,
                "currency": account.currency,
            }

        save_rule_state(state_snapshot_path, state_cache, extra=extra)

        if not config.runtime.daily_bundle_enabled:
            return

        bundle_day = trading_day_for(state_cache.now, config.rule_spec.timezone)

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
                drift_state_path=drift_state_path if drift_state_path.exists() else None,
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
        if farm is None or bar_feed is None:
            return

        def execution_side(intent) -> str:
            if intent.reduce_only:
                return "sell" if intent.side == "buy" else "buy"
            return intent.side

        for bar in bar_feed.fetch_new_bars():
            intents_by_strategy = farm.process_bar(bar)
            leader_id = farm.leader_id
            if leader_id and leader_id in intents_by_strategy:
                for intent in intents_by_strategy[leader_id]:
                    if state_cache is None:
                        continue
                    decision = governor.pre_trade(intent, state_cache)
                    if not decision.allow:
                        continue
                    order = ExecutionOrder(
                        client_order_id=intent.intent_id,
                        symbol=intent.symbol,
                        side=execution_side(intent),
                        volume=float(intent.volume),
                        time=bar.time,
                        intent_id=intent.intent_id,
                        strategy_id=intent.strategy_id,
                    )
                    engine.place_order(order)

            snapshot = farm.snapshot(bar.time)
            farm_status_path.parent.mkdir(parents=True, exist_ok=True)
            farm_status_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    drift_tracker = DriftTracker(
        drift_state_path,
        max_age_seconds=config.runtime.drift_unresolved_seconds,
        audit_log=audit,
        safe_mode=safe_mode,
    )

    async def on_reconcile(report) -> None:
        drift_tracker.update(report)

    async def on_health(ok: bool) -> None:
        nonlocal last_connection_ok
        if last_connection_ok is None:
            last_connection_ok = ok
            return
        if ok and not last_connection_ok:
            audit.log("reconnect", {"reason": "Broker connection restored"})
        last_connection_ok = ok

    service = AsyncServiceLoop(
        engine,
        config=AsyncServiceConfig(
            fast_loop_interval_seconds=config.runtime.fast_loop_interval_seconds,
            bar_loop_interval_seconds=config.runtime.bar_loop_interval_seconds,
            reconcile_interval_seconds=config.runtime.reconcile_interval_seconds,
            health_check_interval_seconds=config.runtime.health_check_interval_seconds,
        ),
        safe_mode=safe_mode,
        on_reconcile=on_reconcile,
        on_health=on_health,
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
