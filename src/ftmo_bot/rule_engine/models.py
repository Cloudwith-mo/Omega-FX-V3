"""Data models for rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable, Optional


class AccountStage(str, Enum):
    CHALLENGE = "challenge"
    VERIFICATION = "verification"
    FUNDED = "funded"

    @property
    def is_evaluation(self) -> bool:
        return self in {AccountStage.CHALLENGE, AccountStage.VERIFICATION}


class FundedMode(str, Enum):
    STANDARD = "standard"
    SWING = "swing"


class NewsPolicy(str, Enum):
    IGNORE = "ignore"
    APPLY = "apply"


class MidnightPolicy(str, Enum):
    NONE = "none"
    BUFFER = "buffer"
    REDUCE = "reduce"
    FLATTEN = "flatten"


@dataclass(frozen=True)
class RuleSpec:
    account_size: float
    max_daily_loss: float
    max_total_loss: float
    challenge_profit_target: float
    verification_profit_target: float
    min_trading_days: int
    timezone: str = "Europe/Prague"
    daily_loss_buffer: float = 0.0
    max_loss_buffer: float = 0.0
    daily_loss_stop_pct: Optional[float] = 0.8
    max_loss_stop_pct: Optional[float] = 0.8
    midnight_policy: MidnightPolicy = MidnightPolicy.NONE
    midnight_window_minutes: int = 30
    midnight_buffer_multiplier: float = 1.0
    max_days_without_trade: int = 25
    drawdown_limit_pct: float = 0.07
    drawdown_days_limit: int = 30
    stage: AccountStage = AccountStage.CHALLENGE
    funded_mode: FundedMode = FundedMode.STANDARD
    strategy_is_legit: bool = True

    def profit_target(self) -> float:
        if self.stage == AccountStage.VERIFICATION:
            return self.verification_profit_target
        if self.stage == AccountStage.CHALLENGE:
            return self.challenge_profit_target
        return 0.0

    def news_policy(self) -> NewsPolicy:
        if self.stage != AccountStage.FUNDED:
            return NewsPolicy.IGNORE
        if self.funded_mode == FundedMode.SWING:
            return NewsPolicy.IGNORE
        return NewsPolicy.APPLY

    def effective_daily_buffer(self) -> float:
        pct_buffer = 0.0
        if self.daily_loss_stop_pct is not None:
            pct_buffer = max(0.0, self.max_daily_loss * (1.0 - self.daily_loss_stop_pct))
        return max(self.daily_loss_buffer, pct_buffer)

    def effective_max_buffer(self) -> float:
        pct_buffer = 0.0
        if self.max_loss_stop_pct is not None:
            pct_buffer = max(0.0, self.max_total_loss * (1.0 - self.max_loss_stop_pct))
        return max(self.max_loss_buffer, pct_buffer)

    def midnight_buffer(self) -> tuple[float, float]:
        multiplier = max(1.0, self.midnight_buffer_multiplier)
        return self.effective_daily_buffer() * multiplier, self.effective_max_buffer() * multiplier


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str
    volume: float
    time: datetime
    estimated_risk: float
    reduce_only: bool = False


@dataclass(frozen=True)
class Trade:
    symbol: str
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    profit: float


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    severity: str = "error"


@dataclass
class RuleState:
    now: datetime
    equity: float
    balance: float
    day_start_equity: float
    day_start_time: datetime
    initial_balance: float
    floating_pnl: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    other_fees: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    is_news_blackout: bool = False
    open_positions: int = 0
    last_trade_time: Optional[datetime] = None
    stage_start_time: Optional[datetime] = None
    drawdown_start_time: Optional[datetime] = None

    def effective_equity(self) -> float:
        costs = self.commission + self.swap + self.other_fees
        if self.floating_pnl or costs:
            return self.balance + self.floating_pnl - costs
        return self.equity

    def trading_days(self, timezone: Optional[str] = None) -> int:
        return trading_day_count(self.trades, timezone=timezone)

    def last_trade_timestamp(self) -> Optional[datetime]:
        if self.last_trade_time:
            return self.last_trade_time
        if not self.trades:
            return None
        return max(trade.entry_time for trade in self.trades)

    def days_since_last_trade(self, timezone: Optional[str] = None) -> Optional[int]:
        last_trade = self.last_trade_timestamp()
        if last_trade is None:
            if self.stage_start_time is None:
                return None
            last_trade = self.stage_start_time
        if timezone is None:
            return (self.now.date() - last_trade.date()).days
        from ftmo_bot.rule_engine.time import trading_day_for

        return (trading_day_for(self.now, timezone) - trading_day_for(last_trade, timezone)).days

    def drawdown_pct(self) -> float:
        equity = self.effective_equity()
        if self.initial_balance <= 0:
            return 0.0
        return max(0.0, (self.initial_balance - equity) / self.initial_balance)

    def update_drawdown_start(self, limit_pct: float) -> None:
        if limit_pct <= 0:
            self.drawdown_start_time = None
            return
        if self.drawdown_pct() >= limit_pct:
            if self.drawdown_start_time is None:
                self.drawdown_start_time = self.now
        else:
            self.drawdown_start_time = None

    def drawdown_days(self, timezone: Optional[str] = None) -> Optional[int]:
        if self.drawdown_start_time is None:
            return None
        if timezone is None:
            return (self.now.date() - self.drawdown_start_time.date()).days
        from ftmo_bot.rule_engine.time import trading_day_for

        return (trading_day_for(self.now, timezone) - trading_day_for(self.drawdown_start_time, timezone)).days

    def roll_day_if_needed(self, timezone: str) -> None:
        from ftmo_bot.rule_engine.time import day_start_for, needs_day_reset

        if needs_day_reset(self.now, self.day_start_time, timezone):
            self.day_start_time = day_start_for(self.now, timezone)
            self.day_start_equity = self.effective_equity()


def trading_day_count(trades: Iterable[Trade], timezone: Optional[str] = None) -> int:
    if timezone is None:
        days = {trade.entry_time.date() for trade in trades}
        return len(days)
    from ftmo_bot.rule_engine.time import trading_day_for

    days = {trading_day_for(trade.entry_time, timezone) for trade in trades}
    return len(days)
