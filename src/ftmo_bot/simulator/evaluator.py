"""FTMO evaluation simulator."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from ftmo_bot.rule_engine.engine import RuleEngine
from ftmo_bot.rule_engine.models import AccountStage, MtMMode, RuleSpec, RuleState, Trade
from ftmo_bot.rule_engine.time import day_start_for, needs_day_reset, trading_day_for
from ftmo_bot.simulator.models import (
    BreachEvent,
    EquityPoint,
    MonteCarloConfig,
    PriceBar,
    Signal,
    SimulationResult,
)


@dataclass(frozen=True)
class SimulationConfig:
    initial_balance: float


class EvaluationSimulator:
    def __init__(self, spec: RuleSpec) -> None:
        self.spec = spec
        self.engine = RuleEngine(spec)

    @dataclass
    class _OpenPosition:
        symbol: str
        side: str
        size: float
        entry_time: datetime
        entry_price: float
        mark_price: float

    def simulate_trades(self, trades: Iterable[Trade], initial_balance: float) -> SimulationResult:
        ordered = sorted(trades, key=lambda trade: trade.entry_time)
        if ordered:
            now = ordered[0].entry_time
        else:
            now = datetime.now().astimezone()
        stage_start_time = now
        day_start_time = day_start_for(now, self.spec.timezone)
        day_start_equity = initial_balance

        balance = initial_balance
        equity = initial_balance
        daily_buffer = self.spec.effective_daily_buffer()
        max_buffer = self.spec.effective_max_buffer()
        min_daily_headroom = self.engine.remaining_daily_loss(
            equity, day_start_equity, self.spec.max_daily_loss
        )
        min_max_headroom = self.engine.remaining_max_loss(
            equity, initial_balance, self.spec.max_total_loss
        )
        buffer_breaches = 0
        min_equity_intraday = equity
        min_equity_overall = equity
        breach_events: list[BreachEvent] = []
        equity_curve = [EquityPoint(time=now, equity=equity)]
        violations: list[str] = []
        drawdown_start_time: Optional[datetime] = None

        for trade in ordered:
            if needs_day_reset(trade.entry_time, day_start_time, self.spec.timezone):
                day_start_time = day_start_for(trade.entry_time, self.spec.timezone)
                day_start_equity = equity
                min_equity_intraday = equity

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
            min_equity_intraday = min(min_equity_intraday, equity)
            min_equity_overall = min(min_equity_overall, equity)
            if daily_headroom <= daily_buffer or max_headroom <= max_buffer:
                buffer_breaches += 1
            if daily_headroom <= 0:
                breach_events.append(
                    BreachEvent(
                        time=now,
                        reason="DAILY_LOSS_LIMIT",
                        equity=equity,
                        daily_headroom=daily_headroom,
                        max_headroom=max_headroom,
                    )
                )
            if max_headroom <= 0:
                breach_events.append(
                    BreachEvent(
                        time=now,
                        reason="MAX_LOSS_LIMIT",
                        equity=equity,
                        daily_headroom=daily_headroom,
                        max_headroom=max_headroom,
                    )
                )

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
                trading_days = RuleEngine.trading_day_count(state.trades, timezone=self.spec.timezone)
                return self._finalize_result(
                    state,
                    equity_curve,
                    violations,
                    min_daily_headroom,
                    min_max_headroom,
                    buffer_breaches,
                    min_equity_intraday,
                    min_equity_overall,
                    breach_events,
                    trading_days,
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
        trading_days = RuleEngine.trading_day_count(final_state.trades, timezone=self.spec.timezone)
        return self._finalize_result(
            final_state,
            equity_curve,
            violations,
            min_daily_headroom,
            min_max_headroom,
            buffer_breaches,
            min_equity_intraday,
            min_equity_overall,
            breach_events,
            trading_days,
        )

    def simulate_signals(
        self,
        price_series: list[PriceBar],
        signals: list[Signal],
        initial_balance: float,
    ) -> SimulationResult:
        if not price_series:
            return self.simulate_trades([], initial_balance)

        bars = sorted(price_series, key=lambda item: item.time)
        signals_by_time: dict[datetime, list[Signal]] = {}
        for signal in signals:
            signals_by_time.setdefault(signal.time, []).append(signal)

        now = bars[0].time
        stage_start_time = now
        day_start_time = day_start_for(now, self.spec.timezone)
        balance = initial_balance
        commission_total = 0.0
        swap_total = 0.0
        floating_pnl = 0.0
        equity = balance - commission_total - swap_total
        day_start_equity = equity

        daily_buffer = self.spec.effective_daily_buffer()
        max_buffer = self.spec.effective_max_buffer()
        min_daily_headroom = self.engine.remaining_daily_loss(
            equity, day_start_equity, self.spec.max_daily_loss
        )
        min_max_headroom = self.engine.remaining_max_loss(
            equity, initial_balance, self.spec.max_total_loss
        )
        buffer_breaches = 0
        min_equity_intraday = equity
        min_equity_overall = equity
        breach_events: list[BreachEvent] = []
        equity_curve = [EquityPoint(time=now, equity=equity)]
        violations: list[str] = []
        drawdown_start_time: Optional[datetime] = None

        open_positions: list[EvaluationSimulator._OpenPosition] = []
        closed_trades: list[Trade] = []
        initiated_times: list[datetime] = []

        for bar in bars:
            if needs_day_reset(bar.time, day_start_time, self.spec.timezone):
                for pos in open_positions:
                    fee = self.spec.fee_schedule(pos.symbol).swap_usd_per_lot_per_day * pos.size
                    swap_total += fee
                equity = balance + floating_pnl - commission_total - swap_total
                day_start_time = day_start_for(bar.time, self.spec.timezone)
                day_start_equity = equity
                min_equity_intraday = equity

            for signal in signals_by_time.get(bar.time, []):
                symbol = signal.symbol or bar.symbol
                if signal.action == "open":
                    entry_price = signal.price
                    if entry_price is None:
                        entry_price = bar.ask if signal.side == "buy" else bar.bid
                    open_positions.append(
                        EvaluationSimulator._OpenPosition(
                            symbol=symbol,
                            side=signal.side,
                            size=signal.size,
                            entry_time=signal.time,
                            entry_price=entry_price,
                            mark_price=entry_price,
                        )
                    )
                    initiated_times.append(signal.time)
                    commission_total += (
                        self.spec.fee_schedule(symbol).commission_usd_per_lot_round_trip
                        * signal.size
                        / 2.0
                    )
                elif signal.action == "close":
                    position = next(
                        (pos for pos in open_positions if pos.symbol == symbol and pos.side == signal.side),
                        None,
                    )
                    if position is None:
                        continue
                    exit_price = signal.price
                    if exit_price is None:
                        exit_price = bar.bid if position.side == "buy" else bar.ask
                    direction = 1 if position.side == "buy" else -1
                    profit = (exit_price - position.entry_price) * position.size * direction
                    balance += profit
                    commission_total += (
                        self.spec.fee_schedule(symbol).commission_usd_per_lot_round_trip
                        * position.size
                        / 2.0
                    )
                    closed_trades.append(
                        Trade(
                            symbol=position.symbol,
                            entry_time=position.entry_time,
                            exit_time=signal.time,
                            entry_price=position.entry_price,
                            exit_price=exit_price,
                            profit=profit,
                        )
                    )
                    open_positions.remove(position)

            for pos in open_positions:
                if pos.symbol != bar.symbol:
                    continue
                if self.spec.mtm_mode == MtMMode.WORST_OHLC:
                    if pos.side == "buy":
                        pos.mark_price = bar.low if bar.low is not None else bar.bid
                    else:
                        pos.mark_price = bar.high if bar.high is not None else bar.ask
                else:
                    pos.mark_price = bar.bid if pos.side == "buy" else bar.ask

            floating_pnl = 0.0
            for pos in open_positions:
                direction = 1 if pos.side == "buy" else -1
                floating_pnl += (pos.mark_price - pos.entry_price) * pos.size * direction

            equity = balance + floating_pnl - commission_total - swap_total
            equity_curve.append(EquityPoint(time=bar.time, equity=equity))

            daily_headroom = self.engine.remaining_daily_loss(
                equity, day_start_equity, self.spec.max_daily_loss
            )
            max_headroom = self.engine.remaining_max_loss(
                equity, initial_balance, self.spec.max_total_loss
            )
            min_daily_headroom = min(min_daily_headroom, daily_headroom)
            min_max_headroom = min(min_max_headroom, max_headroom)
            min_equity_intraday = min(min_equity_intraday, equity)
            min_equity_overall = min(min_equity_overall, equity)
            if daily_headroom <= daily_buffer or max_headroom <= max_buffer:
                buffer_breaches += 1
            if daily_headroom <= 0:
                breach_events.append(
                    BreachEvent(
                        time=bar.time,
                        reason="DAILY_LOSS_LIMIT",
                        equity=equity,
                        daily_headroom=daily_headroom,
                        max_headroom=max_headroom,
                    )
                )
            if max_headroom <= 0:
                breach_events.append(
                    BreachEvent(
                        time=bar.time,
                        reason="MAX_LOSS_LIMIT",
                        equity=equity,
                        daily_headroom=daily_headroom,
                        max_headroom=max_headroom,
                    )
                )

            last_trade_time = initiated_times[-1] if initiated_times else None
            state = RuleState(
                now=bar.time,
                equity=equity,
                balance=balance,
                floating_pnl=floating_pnl,
                commission=commission_total,
                swap=swap_total,
                day_start_equity=day_start_equity,
                day_start_time=day_start_time,
                initial_balance=initial_balance,
                trades=closed_trades,
                stage_start_time=stage_start_time,
                drawdown_start_time=drawdown_start_time,
                last_trade_time=last_trade_time,
                open_positions=len(open_positions),
            )
            state.update_drawdown_start(self.spec.drawdown_limit_pct)
            drawdown_start_time = state.drawdown_start_time
            current_violations = [v.code for v in self.engine.check_violation(state)]
            if current_violations:
                violations.extend(current_violations)
                trading_days = len({trading_day_for(t, self.spec.timezone) for t in initiated_times})
                return self._finalize_result(
                    state,
                    equity_curve,
                    violations,
                    min_daily_headroom,
                    min_max_headroom,
                    buffer_breaches,
                    min_equity_intraday,
                    min_equity_overall,
                    breach_events,
                    trading_days,
                )

        trading_days = len({trading_day_for(t, self.spec.timezone) for t in initiated_times})
        final_state = RuleState(
            now=bars[-1].time,
            equity=equity,
            balance=balance,
            floating_pnl=floating_pnl,
            commission=commission_total,
            swap=swap_total,
            day_start_equity=day_start_equity,
            day_start_time=day_start_time,
            initial_balance=initial_balance,
            trades=closed_trades,
            stage_start_time=stage_start_time,
            drawdown_start_time=drawdown_start_time,
            last_trade_time=initiated_times[-1] if initiated_times else None,
            open_positions=len(open_positions),
        )

        return self._finalize_result(
            final_state,
            equity_curve,
            violations,
            min_daily_headroom,
            min_max_headroom,
            buffer_breaches,
            min_equity_intraday,
            min_equity_overall,
            breach_events,
            trading_days,
        )

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
        min_equity_intraday: float,
        min_equity_overall: float,
        breach_events: list[BreachEvent],
        trading_days: int,
    ) -> SimulationResult:
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
            min_equity_intraday=min_equity_intraday,
            min_equity_overall=min_equity_overall,
            breach_events=breach_events,
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
