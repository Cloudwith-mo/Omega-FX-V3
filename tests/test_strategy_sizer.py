from datetime import datetime
from zoneinfo import ZoneInfo

from ftmo_bot.simulator import PriceBar
from ftmo_bot.strategy import InstrumentConfig, MeanReversionStrategy, Sizer, SizerConfig
from ftmo_bot.strategy.mean_reversion import MeanReversionParams


def test_sizer_risk_cap():
    instruments = {
        "EURUSD": InstrumentConfig(
            pip_size=0.0001,
            pip_value_usd_per_lot=10.0,
            min_lot=0.01,
            lot_step=0.01,
            max_lot=5.0,
        )
    }
    sizer = Sizer(SizerConfig(risk_per_trade_pct=0.0025), instruments)
    result = sizer.size_for_risk("EURUSD", entry_price=1.1000, stop_price=1.0990, initial_balance=100000)
    assert result.allow is True
    assert result.estimated_risk <= 250.0


def test_strategy_emits_order_intent_with_risk():
    tz = "Europe/Prague"
    params = MeanReversionParams(
        symbols=["EURUSD"],
        bollinger_window=3,
        bollinger_stddev=1.0,
        rsi_period=2,
        rsi_oversold=60.0,
        rsi_overbought=40.0,
        atr_period=2,
        atr_multiplier=1.0,
        trade_window_start=datetime.strptime("00:00", "%H:%M").time(),
        trade_window_end=datetime.strptime("23:59", "%H:%M").time(),
        max_trades_per_day=1,
    )
    instruments = {
        "EURUSD": InstrumentConfig(
            pip_size=0.0001,
            pip_value_usd_per_lot=10.0,
            min_lot=0.01,
            lot_step=0.01,
            max_lot=5.0,
        )
    }
    sizer = Sizer(SizerConfig(risk_per_trade_pct=0.0025), instruments)
    strategy = MeanReversionStrategy(params, sizer, tz, initial_balance=100000)
    tzinfo = ZoneInfo(tz)

    bars = [
        PriceBar(
            time=datetime(2024, 6, 1, 9, 0, tzinfo=tzinfo),
            bid=1.0,
            ask=1.0,
            high=1.0,
            low=1.0,
            symbol="EURUSD",
        ),
        PriceBar(
            time=datetime(2024, 6, 1, 9, 15, tzinfo=tzinfo),
            bid=1.0,
            ask=1.0,
            high=1.0,
            low=1.0,
            symbol="EURUSD",
        ),
        PriceBar(
            time=datetime(2024, 6, 1, 9, 30, tzinfo=tzinfo),
            bid=1.0,
            ask=1.0,
            high=1.0,
            low=1.0,
            symbol="EURUSD",
        ),
        PriceBar(
            time=datetime(2024, 6, 1, 9, 45, tzinfo=tzinfo),
            bid=0.9,
            ask=0.9,
            high=0.95,
            low=0.85,
            symbol="EURUSD",
        ),
    ]

    decisions = []
    for bar in bars:
        decisions.extend(strategy.on_bar(bar))

    intents = [decision.order_intent for decision in decisions if decision.order_intent]
    assert len(intents) == 1
    assert intents[0].estimated_risk > 0
