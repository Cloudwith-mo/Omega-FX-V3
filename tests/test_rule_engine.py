from datetime import datetime
from zoneinfo import ZoneInfo

from ftmo_bot.rule_engine.engine import RuleEngine
from ftmo_bot.rule_engine.models import AccountStage, FundedMode, RuleSpec, RuleState, Trade
from ftmo_bot.rule_engine.time import day_start_for, needs_day_reset


def test_midnight_reset_cest():
    tz = ZoneInfo("Europe/Prague")
    before_midnight = datetime(2024, 6, 1, 23, 59, tzinfo=tz)
    after_midnight = datetime(2024, 6, 2, 0, 1, tzinfo=tz)

    before_start = day_start_for(before_midnight, "Europe/Prague")
    after_start = day_start_for(after_midnight, "Europe/Prague")

    assert before_start.date() == before_midnight.date()
    assert after_start.date() == after_midnight.date()
    assert needs_day_reset(after_midnight, before_start, "Europe/Prague") is True


def test_equity_based_daily_loss_check():
    spec = RuleSpec(
        account_size=100000,
        max_daily_loss=5000,
        max_total_loss=10000,
        challenge_profit_target=10000,
        verification_profit_target=5000,
        min_trading_days=4,
        stage=AccountStage.CHALLENGE,
        funded_mode=FundedMode.STANDARD,
    )
    engine = RuleEngine(spec)
    state = RuleState(
        now=datetime(2024, 6, 1, 12, 0, tzinfo=ZoneInfo("Europe/Prague")),
        equity=95000,
        balance=97000,
        day_start_equity=100000,
        day_start_time=datetime(2024, 6, 1, 0, 0, tzinfo=ZoneInfo("Europe/Prague")),
        initial_balance=100000,
        trades=[],
    )

    remaining = engine.remaining_daily_loss(state.equity, state.day_start_equity, spec.max_daily_loss)
    assert remaining == 0
    violations = engine.check_violation(state)
    assert any(v.code == "DAILY_LOSS_LIMIT" for v in violations)


def test_equity_includes_costs():
    tz = ZoneInfo("Europe/Prague")
    spec = RuleSpec(
        account_size=100000,
        max_daily_loss=5000,
        max_total_loss=10000,
        challenge_profit_target=10000,
        verification_profit_target=5000,
        min_trading_days=4,
    )
    engine = RuleEngine(spec)
    state = RuleState(
        now=datetime(2024, 6, 1, 12, 0, tzinfo=tz),
        equity=100000,
        balance=100000,
        floating_pnl=-6000,
        commission=100,
        swap=50,
        day_start_equity=100000,
        day_start_time=datetime(2024, 6, 1, 0, 0, tzinfo=tz),
        initial_balance=100000,
        trades=[],
    )

    violations = engine.check_violation(state)
    assert any(v.code == "DAILY_LOSS_LIMIT" for v in violations)


def test_trading_day_count_min_days():
    tz = ZoneInfo("Europe/Prague")
    trades = [
        Trade(
            symbol="EURUSD",
            entry_time=datetime(2024, 6, 1, 9, 0, tzinfo=tz),
            exit_time=datetime(2024, 6, 1, 10, 0, tzinfo=tz),
            entry_price=1.1,
            exit_price=1.101,
            profit=100,
        ),
        Trade(
            symbol="EURUSD",
            entry_time=datetime(2024, 6, 1, 14, 0, tzinfo=tz),
            exit_time=datetime(2024, 6, 1, 15, 0, tzinfo=tz),
            entry_price=1.102,
            exit_price=1.103,
            profit=80,
        ),
        Trade(
            symbol="EURUSD",
            entry_time=datetime(2024, 6, 2, 9, 0, tzinfo=tz),
            exit_time=datetime(2024, 6, 2, 10, 0, tzinfo=tz),
            entry_price=1.104,
            exit_price=1.103,
            profit=-120,
        ),
    ]

    assert RuleEngine.trading_day_count(trades, timezone="Europe/Prague") == 2
