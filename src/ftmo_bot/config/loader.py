"""Load and freeze configuration files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from ftmo_bot.config.models import (
    BotConfig,
    ExecutionConfig,
    GateConfig,
    MonitoringConfig,
    RuntimeConfig,
    StrategyConfig,
)
from ftmo_bot.rule_engine.models import AccountStage, FeeSchedule, FundedMode, MidnightPolicy, MtMMode, RuleSpec


def load_config(path: str | Path) -> BotConfig:
    path = Path(path)
    data = _load_yaml(path)

    name = _require(data, "name")
    version = str(_require(data, "version"))
    run_id_prefix = data.get("run_id_prefix", name)
    instruments = list(_require(data, "instruments"))

    rule_spec = _parse_rule_spec(_require(data, "rule_spec"))
    strategy = _parse_strategy(_require(data, "strategy"))
    execution = _parse_execution(_require(data, "execution"))
    monitoring = _parse_monitoring(data.get("monitoring", {}))
    gate = _parse_gate(data.get("gate", {}))
    runtime = _parse_runtime(data.get("runtime", {}))

    return BotConfig(
        name=name,
        version=version,
        run_id_prefix=run_id_prefix,
        instruments=instruments,
        rule_spec=rule_spec,
        strategy=strategy,
        execution=execution,
        monitoring=monitoring,
        gate=gate,
        runtime=runtime,
    )


def compute_config_hash(path: str | Path) -> str:
    path = Path(path)
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def freeze_config(path: str | Path, lock_path: Optional[str | Path] = None) -> Path:
    path = Path(path)
    config_hash = compute_config_hash(path)
    if lock_path is None:
        lock_path = path.with_suffix(path.suffix + ".lock.json")
    lock_path = Path(lock_path)

    payload = {
        "config_path": str(path),
        "config_hash": config_hash,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    lock_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return lock_path


def verify_config_lock(path: str | Path, lock_path: Optional[str | Path] = None) -> bool:
    path = Path(path)
    if lock_path is None:
        lock_path = path.with_suffix(path.suffix + ".lock.json")
    lock_path = Path(lock_path)
    if not lock_path.exists():
        return False
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    expected = payload.get("config_hash")
    return expected == compute_config_hash(path)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config must be a mapping")
    return data


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def _parse_rule_spec(data: dict[str, Any]) -> RuleSpec:
    def parse_enum(enum_cls, value: Any, key: str):
        try:
            return enum_cls(value)
        except Exception as exc:
            raise ValueError(f"Invalid {key}: {value}") from exc

    def optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        return float(value)

    fees = {}
    for symbol, payload in data.get("fees", {}).items():
        fees[symbol] = FeeSchedule(
            commission_usd_per_lot_round_trip=float(payload.get("commission_usd_per_lot_round_trip", 0.0)),
            swap_usd_per_lot_per_day=float(payload.get("swap_usd_per_lot_per_day", 0.0)),
        )

    return RuleSpec(
        account_size=float(_require(data, "account_size")),
        max_daily_loss=float(_require(data, "max_daily_loss")),
        max_total_loss=float(_require(data, "max_total_loss")),
        challenge_profit_target=float(_require(data, "challenge_profit_target")),
        verification_profit_target=float(_require(data, "verification_profit_target")),
        min_trading_days=int(_require(data, "min_trading_days")),
        timezone=str(data.get("timezone", "Europe/Prague")),
        daily_loss_buffer=float(data.get("daily_loss_buffer", 0.0)),
        max_loss_buffer=float(data.get("max_loss_buffer", 0.0)),
        daily_loss_stop_pct=optional_float(data.get("daily_loss_stop_pct")),
        max_loss_stop_pct=optional_float(data.get("max_loss_stop_pct")),
        mtm_mode=parse_enum(MtMMode, data.get("mtm_mode", "worst_ohlc"), "mtm_mode"),
        fees=fees,
        midnight_policy=parse_enum(MidnightPolicy, data.get("midnight_policy", "none"), "midnight_policy"),
        midnight_window_minutes=int(data.get("midnight_window_minutes", 30)),
        midnight_buffer_multiplier=float(data.get("midnight_buffer_multiplier", 1.0)),
        max_days_without_trade=int(data.get("max_days_without_trade", 25)),
        inactivity_warning_days=int(data.get("inactivity_warning_days", 5)),
        drawdown_limit_pct=float(data.get("drawdown_limit_pct", 0.07)),
        drawdown_days_limit=int(data.get("drawdown_days_limit", 30)),
        drawdown_warning_days=int(data.get("drawdown_warning_days", 5)),
        stage=parse_enum(AccountStage, data.get("stage", "challenge"), "stage"),
        funded_mode=parse_enum(FundedMode, data.get("funded_mode", "standard"), "funded_mode"),
        strategy_is_legit=bool(data.get("strategy_is_legit", True)),
    )


def _parse_strategy(data: dict[str, Any]) -> StrategyConfig:
    return StrategyConfig(
        name=str(_require(data, "name")),
        parameters=dict(data.get("parameters", {})),
    )


def _parse_execution(data: dict[str, Any]) -> ExecutionConfig:
    return ExecutionConfig(
        broker=str(_require(data, "broker")),
        account=data.get("account"),
        throttle=dict(data.get("throttle", {})),
        duplicate_window_seconds=float(data.get("duplicate_window_seconds", 10.0)),
        duplicate_block=bool(data.get("duplicate_block", True)),
    )


def _parse_monitoring(data: dict[str, Any]) -> MonitoringConfig:
    return MonitoringConfig(
        audit_log_path=str(data.get("audit_log_path", "runtime/audit.log")),
    )


def _parse_gate(data: dict[str, Any]) -> GateConfig:
    return GateConfig(
        min_pass_rate=float(data.get("min_pass_rate", 0.7)),
        max_buffer_breach_runs=int(data.get("max_buffer_breach_runs", 0)),
    )


def _parse_runtime(data: dict[str, Any]) -> RuntimeConfig:
    return RuntimeConfig(
        fast_loop_interval_seconds=float(data.get("fast_loop_interval_seconds", 0.5)),
        bar_loop_interval_seconds=float(data.get("bar_loop_interval_seconds", 60.0)),
        reconcile_interval_seconds=int(data.get("reconcile_interval_seconds", 30)),
        health_check_interval_seconds=int(data.get("health_check_interval_seconds", 10)),
        status_interval_seconds=float(data.get("status_interval_seconds", 5.0)),
        status_path=str(data.get("status_path", "runtime/status.json")),
        state_snapshot_path=str(data.get("state_snapshot_path", "runtime/state_snapshot.json")),
        safe_mode_path=str(data.get("safe_mode_path", "runtime/safe_mode.json")),
        daily_bundle_dir=str(data.get("daily_bundle_dir", "reports/daily_bundles")),
        daily_bundle_enabled=bool(data.get("daily_bundle_enabled", True)),
        daily_metrics_path=str(data.get("daily_metrics_path", "runtime/daily_metrics.json")),
        safe_mode_latched=bool(data.get("safe_mode_latched", True)),
        drift_state_path=str(data.get("drift_state_path", "runtime/drift_state.json")),
        drift_unresolved_seconds=float(data.get("drift_unresolved_seconds", 60.0)),
    )


def serialize_config(config: BotConfig) -> dict[str, Any]:
    payload = asdict(config)
    payload["rule_spec"]["stage"] = config.rule_spec.stage.value
    payload["rule_spec"]["funded_mode"] = config.rule_spec.funded_mode.value
    payload["rule_spec"]["midnight_policy"] = config.rule_spec.midnight_policy.value
    payload["rule_spec"]["mtm_mode"] = config.rule_spec.mtm_mode.value
    return payload
