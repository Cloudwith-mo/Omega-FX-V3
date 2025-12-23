"""Helpers to produce runtime status snapshots."""

from __future__ import annotations

from ftmo_bot.monitoring.status import RuleHeadroom, RuntimeStatus
from ftmo_bot.risk.governor import RiskGovernor
from ftmo_bot.rule_engine.models import AccountStage, RuleState


def build_runtime_status(state: RuleState, governor: RiskGovernor) -> RuntimeStatus:
    headroom = governor.rule_headroom(state)
    target_progress = 0.0
    if governor.spec.stage != AccountStage.FUNDED:
        target = governor.spec.profit_target()
        profit = state.effective_equity() - state.initial_balance
        target_progress = 0.0 if target == 0 else profit / target

    days_since_last_trade = state.days_since_last_trade(governor.spec.timezone)
    drawdown_days = state.drawdown_days(governor.spec.timezone)
    min_remaining = max(0, governor.spec.min_trading_days - state.trading_days(governor.spec.timezone))

    return RuntimeStatus(
        now=state.now,
        stage=governor.spec.stage,
        equity=state.effective_equity(),
        balance=state.balance,
        day_start_equity=state.day_start_equity,
        day_start_time=state.day_start_time,
        open_positions=state.open_positions,
        trading_days=state.trading_days(governor.spec.timezone),
        min_trading_days_remaining=min_remaining,
        days_since_last_trade=days_since_last_trade,
        drawdown_pct=state.drawdown_pct(),
        drawdown_days=drawdown_days,
        headroom=RuleHeadroom(
            daily=headroom["daily"],
            maximum=headroom["max"],
            daily_buffer=governor.spec.effective_daily_buffer(),
            max_buffer=governor.spec.effective_max_buffer(),
        ),
        target_progress=target_progress,
    )
