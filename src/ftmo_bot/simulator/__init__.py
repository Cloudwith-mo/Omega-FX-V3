"""Simulation helpers."""

from ftmo_bot.simulator.evaluator import EvaluationSimulator, SimulationConfig
from ftmo_bot.simulator.gate import GateResult, assess_gate
from ftmo_bot.simulator.models import (
    BreachEvent,
    EquityPoint,
    MonteCarloConfig,
    PriceBar,
    Signal,
    SimulatedTrade,
    SimulationResult,
)

__all__ = [
    "EquityPoint",
    "EvaluationSimulator",
    "BreachEvent",
    "GateResult",
    "MonteCarloConfig",
    "PriceBar",
    "assess_gate",
    "Signal",
    "SimulatedTrade",
    "SimulationConfig",
    "SimulationResult",
]
