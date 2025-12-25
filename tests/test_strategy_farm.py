from datetime import datetime, timedelta, timezone

from ftmo_bot.config.models import FarmConfig, StrategyConfig
from ftmo_bot.rule_engine.models import RuleSpec
from ftmo_bot.rule_engine import AccountStage, FundedMode, MidnightPolicy, MtMMode
from ftmo_bot.rule_engine.models import OrderIntent
from ftmo_bot.simulator import PriceBar
from ftmo_bot.strategy import StrategyContext, StrategyFarm
from ftmo_bot.strategy.farm import ShadowLedger


def _rule_spec() -> RuleSpec:
    return RuleSpec(
        account_size=100000,
        max_daily_loss=5000,
        max_total_loss=10000,
        challenge_profit_target=10000,
        verification_profit_target=5000,
        min_trading_days=4,
        timezone="UTC",
        daily_loss_stop_pct=0.8,
        max_loss_stop_pct=0.8,
        mtm_mode=MtMMode.WORST_OHLC,
        midnight_policy=MidnightPolicy.NONE,
        stage=AccountStage.CHALLENGE,
        funded_mode=FundedMode.STANDARD,
    )


def test_shadow_ledger_score_profit():
    spec = _rule_spec()
    ledger = ShadowLedger(spec, timezone="UTC", initial_balance=100000)
    t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    bar0 = PriceBar(time=t0, bid=1.0, ask=1.0, high=1.0, low=1.0, symbol="EURUSD")
    ledger.apply_intents(
        [OrderIntent(symbol="EURUSD", side="buy", volume=1.0, time=t0, estimated_risk=100)],
        bar0,
    )
    bar1 = PriceBar(time=t0 + timedelta(minutes=15), bid=1.01, ask=1.01, high=1.01, low=1.0, symbol="EURUSD")
    ledger.apply_intents(
        [
            OrderIntent(
                symbol="EURUSD",
                side="buy",
                volume=1.0,
                time=bar1.time,
                estimated_risk=0.0,
                reduce_only=True,
            )
        ],
        bar1,
    )
    score = ledger.score(window_days=5, window_trades=0)
    assert score.net_return > 0


def test_strategy_farm_selects_leader():
    spec = _rule_spec()
    farm_config = FarmConfig(
        enabled=True,
        strategies=[
            StrategyConfig(name="mean_reversion_v1", parameters={"timeframe": "M15"}),
            StrategyConfig(name="momentum_v1", parameters={"timeframe": "M15"}),
        ],
    )
    context = StrategyContext(timezone="UTC", initial_balance=100000, symbol_specs=None)
    farm = StrategyFarm(farm_config, spec, context)

    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    for idx in range(30):
        bar = PriceBar(
            time=start + timedelta(minutes=15 * idx),
            bid=1.0 + (idx * 0.0001),
            ask=1.0 + (idx * 0.0001),
            high=1.0 + (idx * 0.0002),
            low=1.0 + (idx * 0.00005),
            symbol="EURUSD",
        )
        farm.process_bar(bar)

    assert farm.leader_id is not None
