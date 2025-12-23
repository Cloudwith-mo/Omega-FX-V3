"""Core rule evaluation logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ftmo_bot.rule_engine.models import NewsPolicy, OrderIntent, RuleSpec, RuleState, Violation


@dataclass(frozen=True)
class PreTradeResult:
    allow: bool
    reason: str


class RuleEngine:
    def __init__(self, spec: RuleSpec) -> None:
        self.spec = spec

    @staticmethod
    def remaining_daily_loss(equity: float, day_start_equity: float, max_daily_loss: float) -> float:
        daily_loss = max(0.0, day_start_equity - equity)
        return max_daily_loss - daily_loss

    @staticmethod
    def remaining_max_loss(equity: float, initial_balance: float, max_total_loss: float) -> float:
        total_loss = max(0.0, initial_balance - equity)
        return max_total_loss - total_loss

    @staticmethod
    def trading_day_count(trades: Iterable, timezone: str | None = None) -> int:
        from ftmo_bot.rule_engine.models import trading_day_count

        return trading_day_count(trades, timezone=timezone)

    def trading_days_remaining(self, state: RuleState) -> int:
        trading_days = self.trading_day_count(state.trades, timezone=self.spec.timezone)
        return max(0, self.spec.min_trading_days - trading_days)

    def profit_target_reached(self, state: RuleState) -> bool:
        from ftmo_bot.rule_engine.models import AccountStage

        if self.spec.stage == AccountStage.FUNDED:
            return False
        profit = state.effective_equity() - state.initial_balance
        return profit >= self.spec.profit_target()

    def needs_min_trading_days(self, state: RuleState) -> bool:
        return self.profit_target_reached(state) and self.trading_days_remaining(state) > 0

    def check_violation(self, state: RuleState) -> list[Violation]:
        violations: list[Violation] = []

        if not self.spec.strategy_is_legit:
            violations.append(
                Violation(
                    code="STRATEGY_FORBIDDEN",
                    message="Strategy flagged as not legitimate or forbidden.",
                )
            )

        state.update_drawdown_start(self.spec.drawdown_limit_pct)

        equity = state.effective_equity()
        remaining_daily = self.remaining_daily_loss(
            equity=equity,
            day_start_equity=state.day_start_equity,
            max_daily_loss=self.spec.max_daily_loss,
        )
        if remaining_daily <= 0:
            violations.append(
                Violation(
                    code="DAILY_LOSS_LIMIT",
                    message="Max daily loss breached.",
                )
            )

        remaining_total = self.remaining_max_loss(
            equity=equity,
            initial_balance=state.initial_balance,
            max_total_loss=self.spec.max_total_loss,
        )
        if remaining_total <= 0:
            violations.append(
                Violation(
                    code="MAX_LOSS_LIMIT",
                    message="Max loss breached.",
                )
            )

        if self.spec.max_days_without_trade > 0:
            days_without_trade = state.days_since_last_trade(self.spec.timezone)
            if days_without_trade is not None and days_without_trade >= self.spec.max_days_without_trade:
                violations.append(
                    Violation(
                        code="INACTIVITY_LIMIT",
                        message="Inactivity limit exceeded.",
                    )
                )

        if self.spec.drawdown_limit_pct > 0:
            if state.drawdown_pct() >= self.spec.drawdown_limit_pct:
                violations.append(
                    Violation(
                        code="INTERNAL_DRAWDOWN_LIMIT",
                        message="Internal drawdown limit breached.",
                    )
                )

        if self.spec.drawdown_days_limit > 0:
            drawdown_days = state.drawdown_days(self.spec.timezone)
            if drawdown_days is not None and drawdown_days >= self.spec.drawdown_days_limit:
                violations.append(
                    Violation(
                        code="PROLONGED_DRAWDOWN",
                        message="Drawdown duration exceeded limit.",
                    )
                )

        return violations

    def pre_trade_check(self, order_intent: OrderIntent, state: RuleState) -> PreTradeResult:
        if not self.spec.strategy_is_legit:
            return PreTradeResult(False, "Strategy flagged as forbidden")

        if self.spec.news_policy() == NewsPolicy.APPLY and state.is_news_blackout:
            return PreTradeResult(False, "News restriction window active")

        equity = state.effective_equity()
        remaining_daily = self.remaining_daily_loss(
            equity=equity,
            day_start_equity=state.day_start_equity,
            max_daily_loss=self.spec.max_daily_loss,
        )
        if remaining_daily <= 0:
            return PreTradeResult(False, "Daily loss limit reached")

        remaining_total = self.remaining_max_loss(
            equity=equity,
            initial_balance=state.initial_balance,
            max_total_loss=self.spec.max_total_loss,
        )
        if remaining_total <= 0:
            return PreTradeResult(False, "Max loss limit reached")

        if order_intent.estimated_risk >= remaining_daily:
            return PreTradeResult(False, "Order risk exceeds remaining daily loss")

        if order_intent.estimated_risk >= remaining_total:
            return PreTradeResult(False, "Order risk exceeds remaining max loss")

        return PreTradeResult(True, "Allowed")
