"""Market data adapters for strategy farm."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from ftmo_bot.simulator.models import PriceBar

try:  # pragma: no cover - optional dependency
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - optional dependency
    mt5 = None


TIMEFRAME_MAP: dict[str, int] = {}
if mt5 is not None:  # pragma: no cover - requires MT5 runtime
    TIMEFRAME_MAP = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }


@dataclass
class MT5BarFeed:
    symbols: list[str]
    timeframe: str
    timezone: str
    use_closed_bar: bool = True

    def __post_init__(self) -> None:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 package is not installed")
        if self.timeframe not in TIMEFRAME_MAP:
            raise ValueError(f"Unsupported timeframe: {self.timeframe}")
        self._last_bar_time: dict[str, datetime] = {}

    def fetch_new_bars(self) -> list[PriceBar]:
        bars: list[PriceBar] = []
        tz = ZoneInfo(self.timezone)
        for symbol in self.symbols:
            rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME_MAP[self.timeframe], 0, 2)
            if rates is None or len(rates) == 0:
                continue
            rate = rates[-2] if self.use_closed_bar and len(rates) > 1 else rates[-1]
            bar_time = datetime.fromtimestamp(rate["time"], tz=ZoneInfo("UTC")).astimezone(tz)
            if self._last_bar_time.get(symbol) == bar_time:
                continue
            self._last_bar_time[symbol] = bar_time
            bars.append(
                PriceBar(
                    time=bar_time,
                    bid=float(rate["close"]),
                    ask=float(rate["close"]),
                    high=float(rate["high"]),
                    low=float(rate["low"]),
                    symbol=symbol,
                )
            )
        return bars
