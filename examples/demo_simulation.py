from datetime import datetime
from zoneinfo import ZoneInfo

from ftmo_bot.rule_engine import AccountStage, FundedMode, MidnightPolicy, RuleEngine, RuleSpec
from ftmo_bot.rule_engine.models import OrderIntent, RuleState, Trade
from ftmo_bot.simulator import EvaluationSimulator


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
    midnight_window_minutes=30,
    midnight_buffer_multiplier=2.0,
    stage=AccountStage.CHALLENGE,
    funded_mode=FundedMode.STANDARD,
)
engine = RuleEngine(spec)

state = RuleState(
    now=datetime(2024, 6, 1, 12, 0, tzinfo=tz),
    equity=95500,
    balance=97000,
    day_start_equity=100000,
    day_start_time=datetime(2024, 6, 1, 0, 0, tzinfo=tz),
    initial_balance=100000,
    trades=[],
)

intent = OrderIntent(
    symbol="EURUSD",
    side="buy",
    volume=1.0,
    time=state.now,
    estimated_risk=600,
)

result = engine.pre_trade_check(intent, state)
print("Pre-trade:", result.allow, result.reason)

trades = [
    Trade(
        symbol="EURUSD",
        entry_time=datetime(2024, 6, 1, 9, 0, tzinfo=tz),
        exit_time=datetime(2024, 6, 1, 10, 0, tzinfo=tz),
        entry_price=1.1,
        exit_price=1.12,
        profit=2000,
    ),
    Trade(
        symbol="EURUSD",
        entry_time=datetime(2024, 6, 2, 9, 0, tzinfo=tz),
        exit_time=datetime(2024, 6, 2, 10, 0, tzinfo=tz),
        entry_price=1.12,
        exit_price=1.10,
        profit=-1500,
    ),
    Trade(
        symbol="EURUSD",
        entry_time=datetime(2024, 6, 3, 9, 0, tzinfo=tz),
        exit_time=datetime(2024, 6, 3, 10, 0, tzinfo=tz),
        entry_price=1.10,
        exit_price=1.13,
        profit=3000,
    ),
    Trade(
        symbol="EURUSD",
        entry_time=datetime(2024, 6, 4, 9, 0, tzinfo=tz),
        exit_time=datetime(2024, 6, 4, 10, 0, tzinfo=tz),
        entry_price=1.13,
        exit_price=1.15,
        profit=3000,
    ),
]

simulator = EvaluationSimulator(spec)
summary = simulator.simulate_trades(trades, initial_balance=100000)
print("Simulation passed:", summary.passed)
print("Failure reason:", summary.failure_reason)
print("Trading days:", summary.trading_days)
print("Target progress:", summary.target_progress)
