"""Volatility breakout strategy (compression then expansion)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from ftmo_bot.execution.models import SymbolSpec
from ftmo_bot.rule_engine.models import OrderIntent
from ftmo_bot.rule_engine.time import trading_day_for
from ftmo_bot.simulator.models import PriceBar, Signal
from ftmo_bot.strategy.base import TradingStrategy
from ftmo_bot.strategy.indicators import IndicatorSeries
from ftmo_bot.strategy.models import PositionState, StrategyDecision, StrategyState, SizerConfig
from ftmo_bot.strategy.sizer import Sizer
from ftmo_bot.strategy.specs import resolve_instruments


@dataclass(frozen=True)
class BreakoutParams:
    symbols: list[str]
    timeframe: str = "M15"
    trade_window_start: time = time(12, 0)
    trade_window_end: time = time(17, 0)
    bollinger_window: int = 20
    bollinger_stddev: float = 2.0
    bandwidth_lookback: int = 200
    bandwidth_percentile: float = 20.0
    donchian_window: int = 20
    atr_period: int = 14
    atr_multiplier: float = 2.0
    max_hold_bars: int = 0
    max_positions_total: int = 2
    max_positions_per_symbol: int = 1
    max_trades_per_day: int = 1
    max_entries_per_15min: int = 1
    daily_loss_stop_pct: float = 0.01

    @staticmethod
    def from_dict(data: dict) -> "BreakoutParams":
        def parse_time(value: str, default: time) -> time:
            if not value:
                return default
            hour, minute = value.split(":")
            return time(int(hour), int(minute))

        return BreakoutParams(
            symbols=list(data.get("symbols", ["EURUSD", "GBPUSD"])),
            timeframe=str(data.get("timeframe", "M15")),
            trade_window_start=parse_time(data.get("trade_window_start", "12:00"), time(12, 0)),
            trade_window_end=parse_time(data.get("trade_window_end", "17:00"), time(17, 0)),
            bollinger_window=int(data.get("bollinger_window", 20)),
            bollinger_stddev=float(data.get("bollinger_stddev", 2.0)),
            bandwidth_lookback=int(data.get("bandwidth_lookback", 200)),
            bandwidth_percentile=float(data.get("bandwidth_percentile", 20.0)),
            donchian_window=int(data.get("donchian_window", 20)),
            atr_period=int(data.get("atr_period", 14)),
            atr_multiplier=float(data.get("atr_multiplier", 2.0)),
            max_hold_bars=int(data.get("max_hold_bars", 0)),
            max_positions_total=int(data.get("max_positions_total", 2)),
            max_positions_per_symbol=int(data.get("max_positions_per_symbol", 1)),
            max_trades_per_day=int(data.get("max_trades_per_day", 1)),
            max_entries_per_15min=int(data.get("max_entries_per_15min", 1)),
            daily_loss_stop_pct=float(data.get("daily_loss_stop_pct", 0.01)),
        )


class BreakoutStrategy(TradingStrategy):
    def __init__(
        self,
        params: BreakoutParams,
        sizer: Sizer,
        timezone: str,
        initial_balance: float,
    ) -> None:
        self.strategy_id = "breakout_v1"
        self.params = params
        self.sizer = sizer
        self.timezone = timezone
        self.initial_balance = initial_balance
        self.state = StrategyState()
        self.series: dict[str, IndicatorSeries] = {symbol: IndicatorSeries() for symbol in params.symbols}
        self._pending_decisions: list[StrategyDecision] = []
        self._bandwidths: dict[str, list[float]] = {symbol: [] for symbol in params.symbols}

    def initialize(self, config: dict, context) -> None:
        return None

    def on_market_data(self, bar: PriceBar) -> None:
        self._pending_decisions = self.on_bar(bar)

    def generate_intents(self) -> list[OrderIntent]:
        intents = [decision.order_intent for decision in self._pending_decisions if decision.order_intent]
        self._pending_decisions = []
        return intents

    def get_state(self) -> dict:
        return {"strategy_id": self.strategy_id, "open_positions": len(self.state.positions)}

    @staticmethod
    def _in_window(now: datetime, start: time, end: time, timezone: str) -> bool:
        local = now.astimezone(ZoneInfo(timezone)).time().replace(tzinfo=None)
        if start <= end:
            return start <= local <= end
        return local >= start or local <= end

    def _positions_for_symbol(self, symbol: str) -> list[PositionState]:
        return [pos for pos in self.state.positions if pos.symbol == symbol]

    def _close_position(self, position: PositionState, exit_price: float, now: datetime) -> StrategyDecision:
        direction = 1 if position.side == "buy" else -1
        pnl = (exit_price - position.entry_price) * position.size * direction
        day = trading_day_for(now, self.timezone)
        self.state.positions.remove(position)
        self.state.record_realized_pnl(day, pnl)
        signal = Signal(time=now, action="close", side=position.side, size=position.size, symbol=position.symbol)
        intent = OrderIntent(
            symbol=position.symbol,
            side=position.side,
            volume=position.size,
            time=now,
            estimated_risk=0.0,
            reduce_only=True,
            strategy_id=self.strategy_id,
            risk_in_account_ccy=0.0,
        )
        return StrategyDecision(signal=signal, order_intent=intent, reason="Exit")

    def _percentile(self, values: list[float], percentile: float) -> float | None:
        if not values:
            return None
        values_sorted = sorted(values)
        rank = int(round((percentile / 100.0) * (len(values_sorted) - 1)))
        rank = max(0, min(rank, len(values_sorted) - 1))
        return values_sorted[rank]

    def _prev_atr(self, series: IndicatorSeries, period: int) -> float | None:
        if len(series.closes) < period + 2:
            return None
        highs = series.highs[:-1]
        lows = series.lows[:-1]
        closes = series.closes[:-1]
        true_ranges = []
        for index in range(len(closes) - period, len(closes)):
            high = highs[index]
            low = lows[index]
            prev_close = closes[index - 1]
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        return sum(true_ranges) / period

    def on_bar(self, bar: PriceBar) -> list[StrategyDecision]:
        if bar.symbol not in self.series:
            return []

        series = self.series[bar.symbol]
        series.update(bar)
        decisions: list[StrategyDecision] = []

        bands = series.bollinger(self.params.bollinger_window, self.params.bollinger_stddev)
        atr_value = series.atr(self.params.atr_period)
        if bands is None or atr_value is None:
            return decisions
        mid_band, upper_band, lower_band = bands

        now = bar.time
        day = trading_day_for(now, self.timezone)
        if not self._in_window(now, self.params.trade_window_start, self.params.trade_window_end, self.timezone):
            return decisions

        realized_today = self.state.realized_pnl_today(day)
        if realized_today <= -(self.initial_balance * self.params.daily_loss_stop_pct):
            return [StrategyDecision(signal=None, order_intent=None, reason="Daily loss stop")]

        bandwidth = series.bollinger_bandwidth(self.params.bollinger_window, self.params.bollinger_stddev)
        if bandwidth is not None:
            self._bandwidths[bar.symbol].append(bandwidth)

        for position in list(self._positions_for_symbol(bar.symbol)):
            entry_index = position.entry_index
            current_index = len(series.closes) - 1
            bars_held = current_index - entry_index
            close_price = bar.bid if position.side == "buy" else bar.ask

            trail_distance = atr_value * self.params.atr_multiplier
            if trail_distance > 0:
                if position.side == "buy":
                    position.stop_price = max(position.stop_price, close_price - trail_distance)
                else:
                    position.stop_price = min(position.stop_price, close_price + trail_distance)

            if position.side == "buy" and close_price <= position.stop_price:
                decisions.append(self._close_position(position, close_price, now))
                continue
            if position.side == "sell" and close_price >= position.stop_price:
                decisions.append(self._close_position(position, close_price, now))
                continue

            if position.target_price:
                if position.side == "buy" and close_price >= position.target_price:
                    decisions.append(self._close_position(position, close_price, now))
                    continue
                if position.side == "sell" and close_price <= position.target_price:
                    decisions.append(self._close_position(position, close_price, now))
                    continue

            if self.params.max_hold_bars > 0 and bars_held >= self.params.max_hold_bars:
                decisions.append(self._close_position(position, close_price, now))
                continue

        if len(self.state.positions) >= self.params.max_positions_total:
            return decisions
        if len(self._positions_for_symbol(bar.symbol)) >= self.params.max_positions_per_symbol:
            return decisions
        if self.state.trades_today(day) >= self.params.max_trades_per_day:
            return decisions
        if self.state.entries_in_last_minutes(now, 15) >= self.params.max_entries_per_15min:
            return decisions

        bw_history = self._bandwidths[bar.symbol][-self.params.bandwidth_lookback :]
        bw_threshold = self._percentile(bw_history, self.params.bandwidth_percentile)
        if bw_threshold is None or bandwidth is None or bandwidth > bw_threshold:
            return decisions

        prev_atr = self._prev_atr(series, self.params.atr_period)
        if prev_atr is None or atr_value <= prev_atr:
            return decisions

        donchian = series.donchian(self.params.donchian_window)
        if donchian is None:
            return decisions
        donchian_high, donchian_low = donchian

        close_price = (bar.bid + bar.ask) / 2.0
        side = None
        if close_price >= upper_band or close_price >= donchian_high:
            side = "buy"
        elif close_price <= lower_band or close_price <= donchian_low:
            side = "sell"
        if side is None:
            return decisions

        stop_distance = atr_value * self.params.atr_multiplier
        if stop_distance <= 0:
            return decisions

        if side == "buy":
            stop_price = close_price - stop_distance
            target_price = close_price + stop_distance
        else:
            stop_price = close_price + stop_distance
            target_price = close_price - stop_distance

        size_result = self.sizer.size_for_risk(
            symbol=bar.symbol,
            entry_price=close_price,
            stop_price=stop_price,
            initial_balance=self.initial_balance,
        )
        if not size_result.allow:
            return [StrategyDecision(signal=None, order_intent=None, reason=size_result.reason)]

        entry_index = len(series.closes) - 1
        position = PositionState(
            symbol=bar.symbol,
            side=side,
            size=size_result.lot_size,
            entry_price=close_price,
            stop_price=stop_price,
            target_price=target_price,
            entry_time=now,
            entry_index=entry_index,
        )
        self.state.positions.append(position)
        self.state.record_trade(day, now)

        signal = Signal(time=now, action="open", side=side, size=size_result.lot_size, symbol=bar.symbol)
        intent = OrderIntent(
            symbol=bar.symbol,
            side=side,
            volume=size_result.lot_size,
            time=now,
            estimated_risk=size_result.estimated_risk,
            stop_price=stop_price,
            take_profit=target_price,
            strategy_id=self.strategy_id,
            risk_in_account_ccy=size_result.estimated_risk,
        )
        decisions.append(StrategyDecision(signal=signal, order_intent=intent, reason="Entry"))
        return decisions


def build_breakout_from_config(
    parameters: dict,
    timezone: str,
    initial_balance: float,
    symbol_specs: dict[str, SymbolSpec] | None = None,
) -> BreakoutStrategy:
    params = BreakoutParams.from_dict(parameters)
    instruments = resolve_instruments(params.symbols, parameters, symbol_specs)
    sizer_config = SizerConfig(risk_per_trade_pct=float(parameters.get("risk_per_trade_pct", 0.0025)))
    sizer = Sizer(sizer_config, instruments)
    return BreakoutStrategy(params, sizer, timezone, initial_balance)
