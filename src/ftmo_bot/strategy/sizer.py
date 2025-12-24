"""Shared position sizer for risk-based sizing."""

from __future__ import annotations

import math

from ftmo_bot.strategy.models import InstrumentConfig, SizeResult, SizerConfig


class Sizer:
    def __init__(self, config: SizerConfig, instruments: dict[str, InstrumentConfig]) -> None:
        self.config = config
        self.instruments = instruments

    def size_for_risk(
        self,
        symbol: str,
        entry_price: float,
        stop_price: float,
        initial_balance: float,
    ) -> SizeResult:
        instrument = self.instruments.get(symbol)
        if instrument is None:
            return SizeResult(False, 0.0, 0.0, f"No instrument config for {symbol}")

        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return SizeResult(False, 0.0, 0.0, "Invalid stop distance")

        risk_budget = initial_balance * self.config.risk_per_trade_pct
        pips = stop_distance / instrument.pip_size
        risk_per_lot = pips * instrument.pip_value_usd_per_lot
        if risk_per_lot <= 0:
            return SizeResult(False, 0.0, 0.0, "Invalid pip value")

        raw_lots = risk_budget / risk_per_lot
        lot_steps = math.floor(raw_lots / instrument.lot_step)
        lot_size = lot_steps * instrument.lot_step
        lot_size = min(lot_size, instrument.max_lot)

        if lot_size < instrument.min_lot:
            return SizeResult(False, 0.0, 0.0, "Risk cap too small for min lot")

        estimated_risk = lot_size * risk_per_lot
        return SizeResult(True, lot_size, estimated_risk, "Sized")
