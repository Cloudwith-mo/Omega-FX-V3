"""Simulation gates for deployment readiness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ftmo_bot.simulator.models import SimulationResult


@dataclass(frozen=True)
class GateResult:
    pass_rate: float
    average_trading_days: float
    average_target_progress: float
    buffer_breach_runs: int
    min_daily_headroom: float
    min_max_headroom: float
    failures: dict[str, int]
    meets_threshold: bool


def assess_gate(
    results: Iterable[SimulationResult],
    min_pass_rate: float,
    max_buffer_breach_runs: int = 0,
) -> GateResult:
    results_list = list(results)
    total = len(results_list)
    if total == 0:
        return GateResult(0.0, 0.0, 0.0, 0, 0.0, 0.0, {}, False)

    passed = [result for result in results_list if result.passed]
    failures: dict[str, int] = {}
    for result in results_list:
        if result.passed:
            continue
        key = result.failure_reason or "unknown"
        failures[key] = failures.get(key, 0) + 1

    pass_rate = len(passed) / total
    average_trading_days = sum(result.trading_days for result in results_list) / total
    average_target_progress = sum(result.target_progress for result in results_list) / total
    buffer_breach_runs = sum(1 for result in results_list if result.buffer_breaches > 0)
    min_daily_headroom = min(result.min_daily_headroom for result in results_list)
    min_max_headroom = min(result.min_max_headroom for result in results_list)

    return GateResult(
        pass_rate=pass_rate,
        average_trading_days=average_trading_days,
        average_target_progress=average_target_progress,
        buffer_breach_runs=buffer_breach_runs,
        min_daily_headroom=min_daily_headroom,
        min_max_headroom=min_max_headroom,
        failures=failures,
        meets_threshold=pass_rate >= min_pass_rate and buffer_breach_runs <= max_buffer_breach_runs,
    )
