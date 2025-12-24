"""Resolve instrument configs from broker specs with YAML fallback."""

from __future__ import annotations

from ftmo_bot.execution.broker import BrokerAdapter
from ftmo_bot.execution.models import SymbolSpec
from ftmo_bot.strategy.models import InstrumentConfig


def _pick_float(primary: float | None, fallback: float | None, default: float) -> float:
    if primary is not None and primary > 0:
        return float(primary)
    if fallback is not None and fallback > 0:
        return float(fallback)
    return float(default)


def resolve_instruments(
    symbols: list[str],
    parameters: dict,
    symbol_specs: dict[str, SymbolSpec] | None = None,
) -> dict[str, InstrumentConfig]:
    instrument_params = parameters.get("instruments", {}) or {}
    instruments: dict[str, InstrumentConfig] = {}

    for symbol in symbols:
        payload = instrument_params.get(symbol, {})
        spec = symbol_specs.get(symbol) if symbol_specs else None
        instruments[symbol] = InstrumentConfig(
            pip_size=_pick_float(
                getattr(spec, "pip_size", None) if spec else None,
                payload.get("pip_size"),
                0.0001,
            ),
            pip_value_usd_per_lot=_pick_float(
                getattr(spec, "pip_value_usd_per_lot", None) if spec else None,
                payload.get("pip_value_usd_per_lot"),
                10.0,
            ),
            min_lot=_pick_float(
                getattr(spec, "min_lot", None) if spec else None,
                payload.get("min_lot"),
                0.01,
            ),
            lot_step=_pick_float(
                getattr(spec, "lot_step", None) if spec else None,
                payload.get("lot_step"),
                0.01,
            ),
            max_lot=_pick_float(
                getattr(spec, "max_lot", None) if spec else None,
                payload.get("max_lot"),
                100.0,
            ),
        )

    return instruments


def fetch_symbol_specs(broker: BrokerAdapter, symbols: list[str]) -> dict[str, SymbolSpec]:
    specs: dict[str, SymbolSpec] = {}
    for symbol in symbols:
        spec = broker.get_symbol_spec(symbol)
        if spec is not None:
            specs[symbol] = spec
    return specs
