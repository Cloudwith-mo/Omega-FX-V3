from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ftmo_bot.execution import (
    ExecutionEngine,
    ExecutionOrder,
    OrderJournal,
    PaperBroker,
    RequestThrottle,
)
from ftmo_bot.monitoring import AuditLog, build_runtime_status
from ftmo_bot.risk import RiskGovernor
from ftmo_bot.rule_engine import AccountStage, FundedMode, MidnightPolicy, RuleEngine, RuleSpec
from ftmo_bot.rule_engine.models import OrderIntent, RuleState


tz = ZoneInfo("Europe/Prague")

spec = RuleSpec(
    account_size=10000,
    max_daily_loss=1000,
    max_total_loss=2000,
    challenge_profit_target=1000,
    verification_profit_target=500,
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
    equity=9100,
    balance=9300,
    day_start_equity=10000,
    day_start_time=datetime(2024, 6, 1, 0, 0, tzinfo=tz),
    initial_balance=10000,
    trades=[],
)

intent = OrderIntent(
    symbol="EURUSD",
    side="buy",
    volume=1.0,
    time=state.now,
    estimated_risk=150,
)

audit = AuditLog(Path("runtime") / "audit.log")
risk = RiskGovernor(engine, audit_log=audit)
print("Risk decision:", risk.pre_trade(intent, state))
print("Runtime status:", build_runtime_status(state, risk))

journal_path = Path("runtime") / "journal.db"
journal_path.parent.mkdir(exist_ok=True)

journal = OrderJournal(journal_path)
broker = PaperBroker(fill_on_place=True)
throttle = RequestThrottle(max_requests_per_day=1500, max_modifications_per_minute=30, timezone=spec.timezone)
executor = ExecutionEngine(broker, journal, throttle=throttle, audit_log=audit)

order = ExecutionOrder(
    client_order_id="demo-001",
    symbol="EURUSD",
    side="buy",
    volume=1.0,
    time=datetime(2024, 6, 1, 12, 5, tzinfo=tz),
    price=1.1,
    intent_id="demo-intent-001",
    strategy_id="demo",
)

first = executor.place_order(order)
print("First order:", first)

executor = ExecutionEngine(broker, journal, throttle=throttle, audit_log=audit)
second = executor.place_order(order)
print("After restart:", second)

executor.reconcile()
