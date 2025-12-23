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
