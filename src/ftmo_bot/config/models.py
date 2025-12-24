"""Configuration models for reproducible runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ftmo_bot.rule_engine.models import RuleSpec


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionConfig:
    broker: str
    account: Optional[str] = None
    throttle: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MonitoringConfig:
    audit_log_path: str = "runtime/audit.log"


@dataclass(frozen=True)
class GateConfig:
    min_pass_rate: float = 0.7
    max_buffer_breach_runs: int = 0


@dataclass(frozen=True)
class RuntimeConfig:
    fast_loop_interval_seconds: float = 0.5
    bar_loop_interval_seconds: float = 60.0
    reconcile_interval_seconds: int = 30
    health_check_interval_seconds: int = 10
    status_interval_seconds: float = 5.0
    status_path: str = "runtime/status.json"
    state_snapshot_path: str = "runtime/state_snapshot.json"
    safe_mode_path: str = "runtime/safe_mode.json"
    daily_bundle_dir: str = "reports/daily_bundles"
    daily_bundle_enabled: bool = True
    safe_mode_latched: bool = True


@dataclass(frozen=True)
class BotConfig:
    name: str
    version: str
    run_id_prefix: str
    instruments: list[str]
    rule_spec: RuleSpec
    strategy: StrategyConfig
    execution: ExecutionConfig
    monitoring: MonitoringConfig
    gate: GateConfig = GateConfig()
    runtime: RuntimeConfig = RuntimeConfig()
