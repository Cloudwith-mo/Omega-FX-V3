"""Strategy base interfaces for the farm."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ftmo_bot.execution.models import SymbolSpec
from ftmo_bot.rule_engine.models import OrderIntent
from ftmo_bot.simulator.models import PriceBar


@dataclass(frozen=True)
class StrategyContext:
    timezone: str
    initial_balance: float
    symbol_specs: dict[str, SymbolSpec] | None = None


class TradingStrategy(ABC):
    strategy_id: str

    @abstractmethod
    def initialize(self, config: dict, context: StrategyContext) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_market_data(self, bar: PriceBar) -> None:
        raise NotImplementedError

    @abstractmethod
    def generate_intents(self) -> list[OrderIntent]:
        raise NotImplementedError

    @abstractmethod
    def get_state(self) -> dict:
        raise NotImplementedError
