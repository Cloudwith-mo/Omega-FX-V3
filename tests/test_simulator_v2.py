from datetime import datetime
from zoneinfo import ZoneInfo

from ftmo_bot.rule_engine import AccountStage, FeeSchedule, MtMMode, RuleSpec
from ftmo_bot.simulator import EvaluationSimulator, PriceBar, Signal


def _spec_with_fees(fees):
    return RuleSpec(
        account_size=1000,
        max_daily_loss=50,
        max_total_loss=200,
        challenge_profit_target=100,
        verification_profit_target=50,
        min_trading_days=4,
        timezone="Europe/Prague",
        mtm_mode=MtMMode.WORST_OHLC,
        fees=fees,
        stage=AccountStage.CHALLENGE,
    )


def test_floating_loss_breach_without_close():
    tz = ZoneInfo("Europe/Prague")
    spec = _spec_with_fees({"EURUSD": FeeSchedule(7.0, 0.0)})
    simulator = EvaluationSimulator(spec)

    bars = [
        PriceBar(
            time=datetime(2024, 6, 1, 9, 0, tzinfo=tz),
            bid=1.0,
            ask=1.0,
            high=1.0,
            low=1.0,
            symbol="EURUSD",
        ),
        PriceBar(
            time=datetime(2024, 6, 1, 9, 15, tzinfo=tz),
            bid=0.5,
            ask=0.5,
            high=0.5,
            low=0.4,
            symbol="EURUSD",
        ),
    ]
    signals = [
        Signal(time=bars[0].time, action="open", side="buy", size=100.0, symbol="EURUSD"),
    ]

    result = simulator.simulate_signals(bars, signals, initial_balance=spec.account_size)

    assert result.passed is False
    assert any(event.reason == "DAILY_LOSS_LIMIT" for event in result.breach_events)


def test_midnight_floating_loss_trap():
    tz = ZoneInfo("Europe/Prague")
    spec = RuleSpec(
        account_size=1000,
        max_daily_loss=50,
        max_total_loss=200,
        challenge_profit_target=100,
        verification_profit_target=50,
        min_trading_days=4,
        timezone="Europe/Prague",
        mtm_mode=MtMMode.WORST_OHLC,
        fees={"EURUSD": FeeSchedule(0.0, 0.0)},
        stage=AccountStage.CHALLENGE,
    )
    simulator = EvaluationSimulator(spec)

    bars = [
        PriceBar(
            time=datetime(2024, 6, 1, 23, 50, tzinfo=tz),
            bid=1.0,
            ask=1.0,
            high=1.0,
            low=1.0,
            symbol="EURUSD",
        ),
        PriceBar(
            time=datetime(2024, 6, 1, 23, 55, tzinfo=tz),
            bid=1.1,
            ask=1.1,
            high=1.1,
            low=1.1,
            symbol="EURUSD",
        ),
        PriceBar(
            time=datetime(2024, 6, 2, 0, 5, tzinfo=tz),
            bid=0.5,
            ask=0.5,
            high=0.5,
            low=0.4,
            symbol="EURUSD",
        ),
    ]
    signals = [
        Signal(time=bars[0].time, action="open", side="buy", size=100.0, symbol="EURUSD"),
    ]

    result = simulator.simulate_signals(bars, signals, initial_balance=spec.account_size)

    assert result.passed is False
    assert any(event.time == bars[2].time for event in result.breach_events)
    assert any(event.reason == "DAILY_LOSS_LIMIT" for event in result.breach_events)


def test_fees_can_trigger_total_loss_breach():
    tz = ZoneInfo("Europe/Prague")
    fees = {"EURUSD": FeeSchedule(commission_usd_per_lot_round_trip=10.0, swap_usd_per_lot_per_day=0.0)}
    spec = RuleSpec(
        account_size=1000,
        max_daily_loss=500,
        max_total_loss=5,
        challenge_profit_target=100,
        verification_profit_target=50,
        min_trading_days=4,
        timezone="Europe/Prague",
        mtm_mode=MtMMode.WORST_OHLC,
        fees=fees,
        stage=AccountStage.CHALLENGE,
    )
    simulator = EvaluationSimulator(spec)

    bars = [
        PriceBar(
            time=datetime(2024, 6, 1, 9, 0, tzinfo=tz),
            bid=1.0,
            ask=1.0,
            high=1.0,
            low=1.0,
            symbol="EURUSD",
        ),
    ]
    signals = [
        Signal(time=bars[0].time, action="open", side="buy", size=1.0, symbol="EURUSD"),
    ]

    result = simulator.simulate_signals(bars, signals, initial_balance=spec.account_size)

    assert result.passed is False
    assert any(event.reason == "MAX_LOSS_LIMIT" for event in result.breach_events)
