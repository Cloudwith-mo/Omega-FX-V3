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
class FarmConfig:
    enabled: bool = False
    mode: str = "shadow"
    leader_margin: float = 0.0
    leader_min_days: int = 1
    score_window_days: int = 5
    score_window_trades: int = 0
    drawdown_penalty: float = 1.0
    buffer_stop_penalty: float = 1.0
    burst_penalty: float = 1.0
    demotion_buffer_stops: int = 2
    demotion_window_days: int = 5
    bench_days: int = 3
    strategies: list[StrategyConfig] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionConfig:
    broker: str
    account: Optional[str] = None
    throttle: dict[str, Any] = field(default_factory=dict)
    duplicate_window_seconds: float = 10.0
    duplicate_block: bool = True


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
    daily_metrics_path: str = "runtime/daily_metrics.json"
    safe_mode_latched: bool = True
    drift_state_path: str = "runtime/drift_state.json"
    drift_unresolved_seconds: float = 60.0


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
    farm: FarmConfig = FarmConfig()
