"""Common indicator helpers for strategies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ftmo_bot.simulator.models import PriceBar


@dataclass
class IndicatorSeries:
    times: list[datetime]
    closes: list[float]
    highs: list[float]
    lows: list[float]

    def __init__(self) -> None:
        self.times = []
        self.closes = []
        self.highs = []
        self.lows = []

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

    def ema(self, window: int) -> Optional[float]:
        if len(self.closes) < window:
            return None
        alpha = 2.0 / (window + 1.0)
        ema = self.closes[-window]
        for value in self.closes[-window + 1 :]:
            ema = alpha * value + (1.0 - alpha) * ema
        return ema

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

    def bollinger_bandwidth(self, window: int, stddevs: float) -> Optional[float]:
        bands = self.bollinger(window, stddevs)
        if bands is None:
            return None
        mid, upper, lower = bands
        if mid == 0:
            return None
        return (upper - lower) / mid

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

    def donchian(self, window: int) -> Optional[tuple[float, float]]:
        if len(self.highs) < window:
            return None
        highs = self.highs[-window:]
        lows = self.lows[-window:]
        return max(highs), min(lows)

    def adx(self, period: int) -> Optional[float]:
        if len(self.closes) < period + 1:
            return None
        trs: list[float] = []
        plus_dm: list[float] = []
        minus_dm: list[float] = []
        for idx in range(1, len(self.closes)):
            high = self.highs[idx]
            low = self.lows[idx]
            prev_high = self.highs[idx - 1]
            prev_low = self.lows[idx - 1]
            prev_close = self.closes[idx - 1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            up_move = high - prev_high
            down_move = prev_low - low
            plus = up_move if up_move > down_move and up_move > 0 else 0.0
            minus = down_move if down_move > up_move and down_move > 0 else 0.0
            trs.append(tr)
            plus_dm.append(plus)
            minus_dm.append(minus)

        if len(trs) < period:
            return None

        dx_values: list[float] = []
        for end in range(period, len(trs) + 1):
            tr_sum = sum(trs[end - period : end])
            plus_sum = sum(plus_dm[end - period : end])
            minus_sum = sum(minus_dm[end - period : end])
            if tr_sum <= 0:
                continue
            plus_di = 100.0 * (plus_sum / tr_sum)
            minus_di = 100.0 * (minus_sum / tr_sum)
            denom = plus_di + minus_di
            if denom <= 0:
                dx = 0.0
            else:
                dx = 100.0 * abs(plus_di - minus_di) / denom
            dx_values.append(dx)

        if not dx_values:
            return None
        window = min(period, len(dx_values))
        return sum(dx_values[-window:]) / window
