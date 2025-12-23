from datetime import datetime
from zoneinfo import ZoneInfo

from ftmo_bot.risk import RiskGovernor
from ftmo_bot.rule_engine import MidnightPolicy, RuleEngine, RuleSpec
from ftmo_bot.rule_engine.models import RuleState
from ftmo_bot.rule_engine.time import needs_day_reset


def test_midnight_buffer_policy_blocks():
    tz = ZoneInfo("Europe/Prague")
    spec = RuleSpec(
        account_size=100000,
        max_daily_loss=5000,
        max_total_loss=10000,
        challenge_profit_target=10000,
        verification_profit_target=5000,
        min_trading_days=4,
        timezone="Europe/Prague",
        daily_loss_stop_pct=0.8,
        max_loss_stop_pct=0.8,
        midnight_policy=MidnightPolicy.BUFFER,
        midnight_window_minutes=60,
        midnight_buffer_multiplier=2.0,
    )
    engine = RuleEngine(spec)
    governor = RiskGovernor(engine)

    state = RuleState(
        now=datetime(2024, 6, 1, 23, 50, tzinfo=tz),
        equity=96500,
        balance=96500,
        day_start_equity=100000,
        day_start_time=datetime(2024, 6, 1, 0, 0, tzinfo=tz),
        initial_balance=100000,
        trades=[],
    )

    decision = governor.evaluate_state(state)
    assert decision.allow is False
    assert decision.reason == "Daily loss buffer reached"


def test_midnight_reduce_only_policy():
    tz = ZoneInfo("Europe/Prague")
    spec = RuleSpec(
        account_size=100000,
        max_daily_loss=5000,
        max_total_loss=10000,
        challenge_profit_target=10000,
        verification_profit_target=5000,
        min_trading_days=4,
        timezone="Europe/Prague",
        daily_loss_stop_pct=0.8,
        max_loss_stop_pct=0.8,
        midnight_policy=MidnightPolicy.REDUCE,
        midnight_window_minutes=60,
    )
    engine = RuleEngine(spec)
    governor = RiskGovernor(engine)

    state = RuleState(
        now=datetime(2024, 6, 1, 23, 50, tzinfo=tz),
        equity=99000,
        balance=99000,
        day_start_equity=100000,
        day_start_time=datetime(2024, 6, 1, 0, 0, tzinfo=tz),
        initial_balance=100000,
        trades=[],
    )

    decision = governor.evaluate_state(state)
    assert decision.allow is False
    assert decision.reduce_only is True


def test_roll_day_resets_to_effective_equity():
    tz = ZoneInfo("Europe/Prague")
    state = RuleState(
        now=datetime(2024, 6, 2, 0, 1, tzinfo=tz),
        equity=100000,
        balance=100000,
        floating_pnl=-3000,
        commission=50,
        day_start_equity=100000,
        day_start_time=datetime(2024, 6, 1, 0, 0, tzinfo=tz),
        initial_balance=100000,
        trades=[],
    )

    state.roll_day_if_needed("Europe/Prague")
    assert state.day_start_time.date() == state.now.date()
    assert state.day_start_equity == state.effective_equity()


def test_timezone_offset_day_reset():
    tz = ZoneInfo("Europe/Prague")
    day_start = datetime(2024, 1, 1, 0, 0, tzinfo=tz)
    now = datetime(2024, 1, 1, 23, 30, tzinfo=ZoneInfo("UTC"))

    assert needs_day_reset(now, day_start, "Europe/Prague") is True


def test_inactivity_violation_triggered():
    tz = ZoneInfo("Europe/Prague")
    spec = RuleSpec(
        account_size=100000,
        max_daily_loss=5000,
        max_total_loss=10000,
        challenge_profit_target=10000,
        verification_profit_target=5000,
        min_trading_days=4,
        timezone="Europe/Prague",
        max_days_without_trade=2,
    )
    engine = RuleEngine(spec)
    state = RuleState(
        now=datetime(2024, 6, 3, 12, 0, tzinfo=tz),
        equity=100000,
        balance=100000,
        day_start_equity=100000,
        day_start_time=datetime(2024, 6, 3, 0, 0, tzinfo=tz),
        initial_balance=100000,
        trades=[],
        stage_start_time=datetime(2024, 6, 1, 9, 0, tzinfo=tz),
    )

    violations = engine.check_violation(state)
    assert any(v.code == "INACTIVITY_LIMIT" for v in violations)


def test_prolonged_drawdown_violation_triggered():
    tz = ZoneInfo("Europe/Prague")
    spec = RuleSpec(
        account_size=100000,
        max_daily_loss=5000,
        max_total_loss=10000,
        challenge_profit_target=10000,
        verification_profit_target=5000,
        min_trading_days=4,
        timezone="Europe/Prague",
        drawdown_limit_pct=0.05,
        drawdown_days_limit=1,
    )
    engine = RuleEngine(spec)
    state = RuleState(
        now=datetime(2024, 6, 2, 12, 0, tzinfo=tz),
        equity=94000,
        balance=94000,
        day_start_equity=100000,
        day_start_time=datetime(2024, 6, 2, 0, 0, tzinfo=tz),
        initial_balance=100000,
        trades=[],
        drawdown_start_time=datetime(2024, 6, 1, 12, 0, tzinfo=tz),
    )

    violations = engine.check_violation(state)
    assert any(v.code == "PROLONGED_DRAWDOWN" for v in violations)
