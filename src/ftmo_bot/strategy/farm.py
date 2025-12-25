"""Strategy farm orchestrator (shadow tournament)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from ftmo_bot.config.models import FarmConfig, StrategyConfig
from ftmo_bot.rule_engine.engine import RuleEngine
from ftmo_bot.rule_engine.models import OrderIntent, RuleSpec
from ftmo_bot.rule_engine.time import day_start_for, needs_day_reset, trading_day_for
from ftmo_bot.simulator.models import PriceBar
from ftmo_bot.strategy.base import StrategyContext, TradingStrategy
from ftmo_bot.strategy.breakout import build_breakout_from_config
from ftmo_bot.strategy.mean_reversion import build_mean_reversion_from_config
from ftmo_bot.strategy.momentum import build_momentum_from_config


@dataclass
class ShadowPosition:
    symbol: str
    side: str
    size: float
    entry_price: float
    entry_time: datetime
    mark_price: float


@dataclass
class ShadowTrade:
    entry_time: datetime
    exit_time: datetime
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    profit: float


@dataclass
class StrategyScore:
    score: float
    net_return: float
    max_drawdown: float
    buffer_stops: int
    burst_violations: int
    trade_count: int


class ShadowLedger:
    def __init__(
        self,
        spec: RuleSpec,
        timezone: str,
        initial_balance: float,
        max_entries_per_15min: int = 0,
    ) -> None:
        self.spec = spec
        self.engine = RuleEngine(spec)
        self.timezone = timezone
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.day_start_time = day_start_for(datetime.now().astimezone(), timezone)
        self.day_start_equity = initial_balance
        self.open_positions: list[ShadowPosition] = []
        self.trades: list[ShadowTrade] = []
        self.equity_curve: list[tuple[datetime, float]] = []
        self._peak_equity = initial_balance
        self.max_drawdown = 0.0
        self._buffer_stop_day: Optional[datetime.date] = None
        self.buffer_stops: dict[datetime.date, int] = {}
        self.entry_times: list[datetime] = []
        self.burst_violations = 0
        self.max_entries_per_15min = max_entries_per_15min

    def _update_drawdown(self, now: datetime) -> None:
        if self.equity > self._peak_equity:
            self._peak_equity = self.equity
        drawdown = self._peak_equity - self.equity
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        self.equity_curve.append((now, self.equity))

    def _check_buffers(self, now: datetime) -> None:
        daily_headroom = self.engine.remaining_daily_loss(
            self.equity, self.day_start_equity, self.spec.max_daily_loss
        )
        max_headroom = self.engine.remaining_max_loss(self.equity, self.initial_balance, self.spec.max_total_loss)
        daily_buffer = self.spec.effective_daily_buffer()
        max_buffer = self.spec.effective_max_buffer()
        if daily_headroom <= daily_buffer or max_headroom <= max_buffer:
            day = trading_day_for(now, self.timezone)
            if self._buffer_stop_day != day:
                self._buffer_stop_day = day
                self.buffer_stops[day] = self.buffer_stops.get(day, 0) + 1

    def _mark_positions(self, bar: PriceBar) -> None:
        floating = 0.0
        for pos in self.open_positions:
            if pos.symbol != bar.symbol:
                floating += (pos.mark_price - pos.entry_price) * pos.size * (1 if pos.side == "buy" else -1)
                continue
            mark = bar.bid if pos.side == "buy" else bar.ask
            pos.mark_price = mark
            floating += (mark - pos.entry_price) * pos.size * (1 if pos.side == "buy" else -1)
        self.equity = self.balance + floating

    def _record_entry_time(self, now: datetime) -> None:
        self.entry_times.append(now)
        if self.max_entries_per_15min <= 0:
            return
        cutoff = now - timedelta(minutes=15)
        recent = [ts for ts in self.entry_times if ts >= cutoff]
        if len(recent) > self.max_entries_per_15min:
            self.burst_violations += 1

    def apply_intents(self, intents: list[OrderIntent], bar: PriceBar) -> None:
        if needs_day_reset(bar.time, self.day_start_time, self.timezone):
            self.day_start_time = day_start_for(bar.time, self.timezone)
            self.day_start_equity = self.equity
        self._mark_positions(bar)

        for intent in intents:
            if intent.reduce_only:
                position = next(
                    (pos for pos in self.open_positions if pos.symbol == intent.symbol and pos.side == intent.side),
                    None,
                )
                if position is None:
                    continue
                exit_price = bar.bid if position.side == "buy" else bar.ask
                profit = (exit_price - position.entry_price) * position.size * (
                    1 if position.side == "buy" else -1
                )
                self.balance += profit
                self.trades.append(
                    ShadowTrade(
                        entry_time=position.entry_time,
                        exit_time=bar.time,
                        symbol=position.symbol,
                        side=position.side,
                        size=position.size,
                        entry_price=position.entry_price,
                        exit_price=exit_price,
                        profit=profit,
                    )
                )
                self.open_positions.remove(position)
            else:
                entry_price = bar.ask if intent.side == "buy" else bar.bid
                self.open_positions.append(
                    ShadowPosition(
                        symbol=intent.symbol,
                        side=intent.side,
                        size=intent.volume,
                        entry_price=entry_price,
                        entry_time=bar.time,
                        mark_price=entry_price,
                    )
                )
                self._record_entry_time(bar.time)

        self._mark_positions(bar)
        self._update_drawdown(bar.time)
        self._check_buffers(bar.time)

    def score(self, window_days: int, window_trades: int) -> StrategyScore:
        if window_trades > 0:
            trades = self.trades[-window_trades:]
            pnl_curve: list[float] = []
            total = 0.0
            peak = 0.0
            max_dd = 0.0
            for trade in trades:
                total += trade.profit
                pnl_curve.append(total)
                if total > peak:
                    peak = total
                max_dd = max(max_dd, peak - total)
            net_return = pnl_curve[-1] if pnl_curve else 0.0
            max_drawdown = max_dd
        else:
            if not self.equity_curve:
                net_return = 0.0
                max_drawdown = 0.0
            else:
                end_time = self.equity_curve[-1][0]
                start_time = end_time - timedelta(days=max(window_days, 1))
                points = [point for point in self.equity_curve if point[0] >= start_time]
                if not points:
                    points = self.equity_curve
                start_equity = points[0][1]
                net_return = points[-1][1] - start_equity
                peak = points[0][1]
                max_drawdown = 0.0
                for _, equity in points:
                    if equity > peak:
                        peak = equity
                    max_drawdown = max(max_drawdown, peak - equity)

        buffer_stops = sum(self.buffer_stops.values())
        return StrategyScore(
            score=0.0,
            net_return=net_return,
            max_drawdown=max_drawdown,
            buffer_stops=buffer_stops,
            burst_violations=self.burst_violations,
            trade_count=len(self.trades),
        )


def build_strategy(
    config: StrategyConfig,
    context: StrategyContext,
) -> TradingStrategy:
    name = config.name
    params = config.parameters
    if name == "mean_reversion_v1":
        strategy = build_mean_reversion_from_config(params, context.timezone, context.initial_balance, context.symbol_specs)
    elif name == "momentum_v1":
        strategy = build_momentum_from_config(params, context.timezone, context.initial_balance, context.symbol_specs)
    elif name == "breakout_v1":
        strategy = build_breakout_from_config(params, context.timezone, context.initial_balance, context.symbol_specs)
    else:
        raise ValueError(f"Unknown strategy: {name}")
    strategy.initialize(params, context)
    return strategy


class StrategyFarm:
    def __init__(
        self,
        farm_config: FarmConfig,
        rule_spec: RuleSpec,
        context: StrategyContext,
        baseline_strategy: StrategyConfig | None = None,
    ) -> None:
        self.config = farm_config
        self.context = context
        self.rule_spec = rule_spec
        strategies = list(farm_config.strategies)
        if not strategies:
            strategies = [
                baseline_strategy
                if baseline_strategy is not None
                else StrategyConfig(name="mean_reversion_v1", parameters={})
            ]
        self.strategies: dict[str, TradingStrategy] = {}
        self.ledgers: dict[str, ShadowLedger] = {}
        for cfg in strategies:
            strategy = build_strategy(cfg, context)
            self.strategies[strategy.strategy_id] = strategy
            max_entries = int(cfg.parameters.get("max_entries_per_15min", 0) or 0)
            self.ledgers[strategy.strategy_id] = ShadowLedger(
                rule_spec, context.timezone, context.initial_balance, max_entries_per_15min=max_entries
            )

        self.leader_id: Optional[str] = None
        self.leader_since: Optional[datetime.date] = None
        self.benched_until: dict[str, datetime.date] = {}
        self.latest_scores: dict[str, StrategyScore] = {}

    def _score(self, now: datetime) -> None:
        for strategy_id, ledger in self.ledgers.items():
            score = ledger.score(self.config.score_window_days, self.config.score_window_trades)
            score.score = (
                score.net_return
                - (self.config.drawdown_penalty * score.max_drawdown)
                - (self.config.buffer_stop_penalty * score.buffer_stops)
                - (self.config.burst_penalty * score.burst_violations)
            )
            self.latest_scores[strategy_id] = score

    def _maybe_bench(self, now: datetime) -> None:
        for strategy_id, ledger in self.ledgers.items():
            days = sorted(ledger.buffer_stops.keys())[-self.config.demotion_window_days :]
            total = sum(ledger.buffer_stops.get(day, 0) for day in days)
            if total >= self.config.demotion_buffer_stops:
                bench_until = trading_day_for(now, self.context.timezone) + timedelta(days=self.config.bench_days)
                self.benched_until[strategy_id] = bench_until

    def _select_leader(self, now: datetime) -> None:
        self._score(now)
        self._maybe_bench(now)

        candidates = [
            (strategy_id, score)
            for strategy_id, score in self.latest_scores.items()
            if self.benched_until.get(strategy_id, now.date()) <= trading_day_for(now, self.context.timezone)
        ]
        if not candidates:
            return
        candidates.sort(key=lambda item: item[1].score, reverse=True)
        winner_id, winner_score = candidates[0]

        if self.leader_id is None:
            self.leader_id = winner_id
            self.leader_since = trading_day_for(now, self.context.timezone)
            return

        if winner_id == self.leader_id:
            return

        leader_score = self.latest_scores.get(self.leader_id)
        leader_score_value = leader_score.score if leader_score else float("-inf")
        held_days = 0
        if self.leader_since:
            held_days = (
                trading_day_for(now, self.context.timezone) - self.leader_since
            ).days

        if held_days < self.config.leader_min_days:
            return
        if winner_score.score < leader_score_value + self.config.leader_margin:
            return

        self.leader_id = winner_id
        self.leader_since = trading_day_for(now, self.context.timezone)

    def process_bar(self, bar: PriceBar) -> dict[str, list[OrderIntent]]:
        intents_by_strategy: dict[str, list[OrderIntent]] = {}
        for strategy_id, strategy in self.strategies.items():
            strategy.on_market_data(bar)
            intents = strategy.generate_intents()
            intents_by_strategy[strategy_id] = intents
            self.ledgers[strategy_id].apply_intents(intents, bar)

        self._select_leader(bar.time)
        return intents_by_strategy

    def snapshot(self, now: datetime) -> dict:
        payload = {
            "timestamp": now.isoformat(),
            "leader_id": self.leader_id,
            "leader_since": self.leader_since.isoformat() if self.leader_since else None,
            "strategies": {},
        }
        for strategy_id, score in self.latest_scores.items():
            payload["strategies"][strategy_id] = {
                "score": score.score,
                "net_return": score.net_return,
                "max_drawdown": score.max_drawdown,
                "buffer_stops": score.buffer_stops,
                "burst_violations": score.burst_violations,
                "trade_count": score.trade_count,
            }
        return payload
