"""FTMO evaluation simulator."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from ftmo_bot.rule_engine.engine import RuleEngine
from ftmo_bot.rule_engine.models import AccountStage, RuleSpec, RuleState, Trade
from ftmo_bot.rule_engine.time import day_start_for, needs_day_reset
from ftmo_bot.simulator.models import (
    EquityPoint,
    MonteCarloConfig,
    PriceBar,
    Signal,
    SimulatedTrade,
    SimulationResult,
)


@dataclass(frozen=True)
class SimulationConfig:
    initial_balance: float


class EvaluationSimulator:
    def __init__(self, spec: RuleSpec) -> None:
        self.spec = spec
        self.engine = RuleEngine(spec)

    def simulate_trades(self, trades: Iterable[Trade], initial_balance: float) -> SimulationResult:
        ordered = sorted(trades, key=lambda trade: trade.entry_time)
        if ordered:
            now = ordered[0].entry_time
        else:
            now = datetime.now().astimezone()
        stage_start_time = now
        day_start_time = day_start_for(now, self.spec.timezone)
        day_start_equity = initial_balance

        equity = initial_balance
        balance = initial_balance
        daily_buffer = self.spec.effective_daily_buffer()
        max_buffer = self.spec.effective_max_buffer()
        min_daily_headroom = self.engine.remaining_daily_loss(
            equity, day_start_equity, self.spec.max_daily_loss
        )
        min_max_headroom = self.engine.remaining_max_loss(
            equity, initial_balance, self.spec.max_total_loss
        )
        buffer_breaches = 0
        equity_curve = [EquityPoint(time=now, equity=equity)]
        violations: list[str] = []
        drawdown_start_time: Optional[datetime] = None

        for trade in ordered:
            if needs_day_reset(trade.entry_time, day_start_time, self.spec.timezone):
                day_start_time = day_start_for(trade.entry_time, self.spec.timezone)
                day_start_equity = equity

            equity += trade.profit
            balance = equity
            now = trade.exit_time or trade.entry_time
            equity_curve.append(EquityPoint(time=now, equity=equity))

            daily_headroom = self.engine.remaining_daily_loss(
                equity, day_start_equity, self.spec.max_daily_loss
            )
            max_headroom = self.engine.remaining_max_loss(
                equity, initial_balance, self.spec.max_total_loss
            )
            min_daily_headroom = min(min_daily_headroom, daily_headroom)
            min_max_headroom = min(min_max_headroom, max_headroom)
            if daily_headroom <= daily_buffer or max_headroom <= max_buffer:
                buffer_breaches += 1

            state = RuleState(
                now=now,
                equity=equity,
                balance=balance,
                day_start_equity=day_start_equity,
                day_start_time=day_start_time,
                initial_balance=initial_balance,
                trades=list(ordered),
                stage_start_time=stage_start_time,
                drawdown_start_time=drawdown_start_time,
            )
            state.update_drawdown_start(self.spec.drawdown_limit_pct)
            drawdown_start_time = state.drawdown_start_time
            current_violations = [v.code for v in self.engine.check_violation(state)]
            if current_violations:
                violations.extend(current_violations)
                return self._finalize_result(
                    state,
                    equity_curve,
                    violations,
                    min_daily_headroom,
                    min_max_headroom,
                    buffer_breaches,
                )

        final_state = RuleState(
            now=now,
            equity=equity,
            balance=balance,
            day_start_equity=day_start_equity,
            day_start_time=day_start_time,
            initial_balance=initial_balance,
            trades=list(ordered),
            stage_start_time=stage_start_time,
            drawdown_start_time=drawdown_start_time,
        )
        return self._finalize_result(
            final_state,
            equity_curve,
            violations,
            min_daily_headroom,
            min_max_headroom,
            buffer_breaches,
        )

    def simulate_signals(
        self,
        price_series: list[PriceBar],
        signals: list[Signal],
        initial_balance: float,
    ) -> SimulationResult:
        if not price_series:
            return self.simulate_trades([], initial_balance)

        bars = {bar.time: bar for bar in price_series}
        open_trade: Optional[SimulatedTrade] = None
        trades: list[Trade] = []

        for signal in sorted(signals, key=lambda item: item.time):
            bar = bars.get(signal.time)
            if bar is None:
                continue

            price = signal.price
            if price is None:
                price = bar.ask if signal.side == "buy" else bar.bid

            if signal.action == "open" and open_trade is None:
                open_trade = SimulatedTrade(
                    entry_time=signal.time,
                    exit_time=signal.time,
                    side=signal.side,
                    size=signal.size,
                    entry_price=price,
                    exit_price=price,
                    profit=0.0,
                )
            elif signal.action == "close" and open_trade is not None:
                exit_price = price
                direction = 1 if open_trade.side == "buy" else -1
                profit = (exit_price - open_trade.entry_price) * open_trade.size * direction
                trades.append(
                    Trade(
                        symbol="SIM",
                        entry_time=open_trade.entry_time,
                        exit_time=signal.time,
                        entry_price=open_trade.entry_price,
                        exit_price=exit_price,
                        profit=profit,
                    )
                )
                open_trade = None

        return self.simulate_trades(trades, initial_balance)

    def run_monte_carlo(
        self,
        trades: Iterable[Trade],
        runs: int,
        config: MonteCarloConfig,
        initial_balance: float,
    ) -> list[SimulationResult]:
        results: list[SimulationResult] = []
        trades_list = list(trades)
        for _ in range(runs):
            adjusted = []
            for trade in trades_list:
                slippage = random.uniform(*config.slippage_range)
                spread = random.uniform(*config.spread_range)
                adjusted.append(
                    Trade(
                        symbol=trade.symbol,
                        entry_time=trade.entry_time,
                        exit_time=trade.exit_time,
                        entry_price=trade.entry_price,
                        exit_price=trade.exit_price,
                        profit=trade.profit - slippage - spread,
                    )
                )
            results.append(self.simulate_trades(adjusted, initial_balance))
        return results

    def _finalize_result(
        self,
        state: RuleState,
        equity_curve: list[EquityPoint],
        violations: list[str],
        min_daily_headroom: float,
        min_max_headroom: float,
        buffer_breaches: int,
    ) -> SimulationResult:
        trading_days = RuleEngine.trading_day_count(state.trades, timezone=self.spec.timezone)
        profit = state.effective_equity() - state.initial_balance
        target = self.spec.profit_target()
        if self.spec.stage == AccountStage.FUNDED:
            target_progress = 0.0
        else:
            target_progress = 0.0 if target == 0 else profit / target

        passed, failure_reason = self._evaluate_pass(state, violations, trading_days)
        return SimulationResult(
            equity_curve=equity_curve,
            passed=passed,
            failure_reason=failure_reason,
            trading_days=trading_days,
            target_progress=target_progress,
            violations=violations,
            min_daily_headroom=min_daily_headroom,
            min_max_headroom=min_max_headroom,
            buffer_breaches=buffer_breaches,
        )

    def _evaluate_pass(
        self,
        state: RuleState,
        violations: list[str],
        trading_days: int,
    ) -> tuple[bool, Optional[str]]:
        if violations:
            return False, f"Violation: {violations[0]}"

        if self.spec.stage == AccountStage.FUNDED:
            return True, None

        profit = state.effective_equity() - state.initial_balance
        target = self.spec.profit_target()
        if profit < target:
            return False, "Profit target not reached"
        if trading_days < self.spec.min_trading_days:
            return False, "Minimum trading days not reached"

        return True, None
