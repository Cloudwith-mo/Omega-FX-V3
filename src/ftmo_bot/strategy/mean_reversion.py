"""Mean reversion strategy with Bollinger + RSI filters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Optional

from ftmo_bot.rule_engine.models import OrderIntent
from ftmo_bot.execution.models import SymbolSpec
from ftmo_bot.rule_engine.time import trading_day_for
from ftmo_bot.simulator.models import PriceBar, Signal
from ftmo_bot.strategy.models import PositionState, StrategyDecision, StrategyState
from ftmo_bot.strategy.sizer import Sizer
from ftmo_bot.strategy.models import SizerConfig
from ftmo_bot.strategy.specs import resolve_instruments


@dataclass(frozen=True)
class MeanReversionParams:
    symbols: list[str]
    timeframe: str = "M15"
    trade_window_start: time = time(12, 0)
    trade_window_end: time = time(17, 0)
    bollinger_window: int = 20
    bollinger_stddev: float = 2.0
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    atr_period: int = 14
    atr_multiplier: float = 1.5
    take_profit_mode: str = "mid_band"
    max_hold_bars: int = 0
    max_positions_total: int = 2
    max_positions_per_symbol: int = 1
    max_trades_per_day: int = 4
    max_entries_per_15min: int = 2
    daily_loss_stop_pct: float = 0.01

    @staticmethod
    def from_dict(data: dict) -> "MeanReversionParams":
        def parse_time(value: str, default: time) -> time:
            if not value:
                return default
            hour, minute = value.split(":")
            return time(int(hour), int(minute))

        return MeanReversionParams(
            symbols=list(data.get("symbols", ["EURUSD", "GBPUSD"])),
            timeframe=str(data.get("timeframe", "M15")),
            trade_window_start=parse_time(data.get("trade_window_start", "12:00"), time(12, 0)),
            trade_window_end=parse_time(data.get("trade_window_end", "17:00"), time(17, 0)),
            bollinger_window=int(data.get("bollinger_window", 20)),
            bollinger_stddev=float(data.get("bollinger_stddev", 2.0)),
            rsi_period=int(data.get("rsi_period", 14)),
            rsi_overbought=float(data.get("rsi_overbought", 70.0)),
            rsi_oversold=float(data.get("rsi_oversold", 30.0)),
            atr_period=int(data.get("atr_period", 14)),
            atr_multiplier=float(data.get("atr_multiplier", 1.5)),
            take_profit_mode=str(data.get("take_profit_mode", "mid_band")),
            max_hold_bars=int(data.get("max_hold_bars", 0)),
            max_positions_total=int(data.get("max_positions_total", 2)),
            max_positions_per_symbol=int(data.get("max_positions_per_symbol", 1)),
            max_trades_per_day=int(data.get("max_trades_per_day", 4)),
            max_entries_per_15min=int(data.get("max_entries_per_15min", 2)),
            daily_loss_stop_pct=float(data.get("daily_loss_stop_pct", 0.01)),
        )


class IndicatorSeries:
    def __init__(self) -> None:
        self.times: list[datetime] = []
        self.closes: list[float] = []
        self.highs: list[float] = []
        self.lows: list[float] = []

    def update(self, bar: PriceBar) -> None:
        close = (bar.bid + bar.ask) / 2.0
        high = bar.high if bar.high is not None else max(bar.bid, bar.ask)
        low = bar.low if bar.low is not None else min(bar.bid, bar.ask)
        self.times.append(bar.time)
        self.closes.append(close)
        self.highs.append(high)
        self.lows.append(low)

    def sma(self, window: int) -> Optional[float]:
        if len(self.closes) < window:
            return None
        slice_ = self.closes[-window:]
        return sum(slice_) / window

    def stddev(self, window: int) -> Optional[float]:
        if len(self.closes) < window:
            return None
        slice_ = self.closes[-window:]
        mean = sum(slice_) / window
        variance = sum((value - mean) ** 2 for value in slice_) / window
        return variance**0.5

    def bollinger(self, window: int, stddevs: float) -> Optional[tuple[float, float, float]]:
        mean = self.sma(window)
        deviation = self.stddev(window)
        if mean is None or deviation is None:
            return None
        upper = mean + stddevs * deviation
        lower = mean - stddevs * deviation
        return mean, upper, lower

    def rsi(self, period: int) -> Optional[float]:
        if len(self.closes) < period + 1:
            return None
        deltas = [
            self.closes[i] - self.closes[i - 1]
            for i in range(len(self.closes) - period, len(self.closes))
        ]
        gains = sum(delta for delta in deltas if delta > 0)
        losses = -sum(delta for delta in deltas if delta < 0)
        if gains == 0 and losses == 0:
            return 50.0
        if losses == 0:
            return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def atr(self, period: int) -> Optional[float]:
        if len(self.closes) < period + 1:
            return None
        true_ranges = []
        for index in range(len(self.closes) - period, len(self.closes)):
            high = self.highs[index]
            low = self.lows[index]
            prev_close = self.closes[index - 1]
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        return sum(true_ranges) / period


class MeanReversionStrategy:
    def __init__(
        self,
        params: MeanReversionParams,
        sizer: Sizer,
        timezone: str,
        initial_balance: float,
    ) -> None:
        self.params = params
        self.sizer = sizer
        self.timezone = timezone
        self.initial_balance = initial_balance
        self.state = StrategyState()
        self.series: dict[str, IndicatorSeries] = {symbol: IndicatorSeries() for symbol in params.symbols}

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
        )
        return StrategyDecision(signal=signal, order_intent=intent, reason="Exit")

    def on_bar(self, bar: PriceBar) -> list[StrategyDecision]:
        if bar.symbol not in self.series:
            return []

        series = self.series[bar.symbol]
        series.update(bar)
        decisions: list[StrategyDecision] = []

        mid_band = series.sma(self.params.bollinger_window)
        bands = series.bollinger(self.params.bollinger_window, self.params.bollinger_stddev)
        rsi_value = series.rsi(self.params.rsi_period)
        atr_value = series.atr(self.params.atr_period)
        if bands is None or rsi_value is None or atr_value is None:
            return decisions
        mid_band, upper_band, lower_band = bands

        now = bar.time
        day = trading_day_for(now, self.timezone)
        if not self._in_window(now, self.params.trade_window_start, self.params.trade_window_end, self.timezone):
            return decisions

        realized_today = self.state.realized_pnl_today(day)
        if realized_today <= -(self.initial_balance * self.params.daily_loss_stop_pct):
            return [StrategyDecision(signal=None, order_intent=None, reason="Daily loss stop")]

        for position in list(self._positions_for_symbol(bar.symbol)):
            entry_index = position.entry_index
            current_index = len(series.closes) - 1
            bars_held = current_index - entry_index
            close_price = bar.bid if position.side == "buy" else bar.ask

            if position.side == "buy" and close_price <= position.stop_price:
                decisions.append(self._close_position(position, close_price, now))
                continue
            if position.side == "sell" and close_price >= position.stop_price:
                decisions.append(self._close_position(position, close_price, now))
                continue

            if self.params.take_profit_mode == "mid_band":
                if position.side == "buy" and close_price >= mid_band:
                    decisions.append(self._close_position(position, close_price, now))
                    continue
                if position.side == "sell" and close_price <= mid_band:
                    decisions.append(self._close_position(position, close_price, now))
                    continue
            else:
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

        close_price = (bar.bid + bar.ask) / 2.0
        side = None
        if close_price <= lower_band and rsi_value <= self.params.rsi_oversold:
            side = "buy"
        elif close_price >= upper_band and rsi_value >= self.params.rsi_overbought:
            side = "sell"

        if side is None:
            return decisions

        stop_distance = atr_value * self.params.atr_multiplier
        if stop_distance <= 0:
            return decisions

        if side == "buy":
            stop_price = close_price - stop_distance
            target_price = mid_band if self.params.take_profit_mode == "mid_band" else close_price + stop_distance
        else:
            stop_price = close_price + stop_distance
            target_price = mid_band if self.params.take_profit_mode == "mid_band" else close_price - stop_distance

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
            strategy_id="mean_reversion_v1",
        )
        decisions.append(StrategyDecision(signal=signal, order_intent=intent, reason="Entry"))
        return decisions


def build_mean_reversion_from_config(
    parameters: dict,
    timezone: str,
    initial_balance: float,
    symbol_specs: dict[str, SymbolSpec] | None = None,
) -> MeanReversionStrategy:
    params = MeanReversionParams.from_dict(parameters)
    instruments = resolve_instruments(params.symbols, parameters, symbol_specs)
    sizer_config = SizerConfig(risk_per_trade_pct=float(parameters.get("risk_per_trade_pct", 0.0025)))
    sizer = Sizer(sizer_config, instruments)
    return MeanReversionStrategy(params, sizer, timezone, initial_balance)
