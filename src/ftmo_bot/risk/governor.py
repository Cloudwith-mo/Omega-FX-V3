"""Risk governor that enforces buffers and hard limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ftmo_bot.rule_engine.engine import RuleEngine
from ftmo_bot.rule_engine.models import MidnightPolicy, OrderIntent, RuleState
from ftmo_bot.rule_engine.time import in_midnight_window


@dataclass(frozen=True)
class RiskDecision:
    allow: bool
    reason: str
    flatten: bool = False
    reduce_only: bool = False


class RiskGovernor:
    def __init__(
        self,
        engine: RuleEngine,
        audit_log: Optional[object] = None,
        monitor: Optional[object] = None,
    ) -> None:
        self.engine = engine
        self.spec = engine.spec
        self._disabled = False
        self._disable_reason: Optional[str] = None
        self._audit_log = audit_log
        self._monitor = monitor

    def rule_headroom(self, state: RuleState) -> dict[str, float]:
        equity = state.effective_equity()
        return {
            "daily": self.engine.remaining_daily_loss(
                equity,
                state.day_start_equity,
                self.spec.max_daily_loss,
            ),
            "max": self.engine.remaining_max_loss(
                equity,
                state.initial_balance,
                self.spec.max_total_loss,
            ),
        }

    def disable(self, reason: str) -> None:
        self._disabled = True
        self._disable_reason = reason

    def reset_disable(self) -> None:
        self._disabled = False
        self._disable_reason = None

    def disabled_reason(self) -> Optional[str]:
        return self._disable_reason

    def _log(self, event: str, payload: dict) -> None:
        if self._audit_log is None:
            return
        self._audit_log.log(event, payload)

    def _notify_buffer(self, which: str, remaining: float) -> None:
        if self._monitor is None:
            return
        self._monitor.rule_buffer_breach(which, remaining)

    def _notify_flatten(self, reason: str) -> None:
        if self._monitor is None:
            return
        self._monitor.flatten_trigger(reason)

    def _notify_inactivity(self, message: str) -> None:
        if self._monitor is None:
            return
        self._monitor.inactivity_warning(message)

    def _effective_buffers(self, state: RuleState) -> tuple[float, float, bool]:
        in_window = in_midnight_window(
            state.now,
            self.spec.timezone,
            self.spec.midnight_window_minutes,
        )
        if in_window and self.spec.midnight_policy == MidnightPolicy.BUFFER:
            daily_buffer, max_buffer = self.spec.midnight_buffer()
        else:
            daily_buffer = self.spec.effective_daily_buffer()
            max_buffer = self.spec.effective_max_buffer()
        return daily_buffer, max_buffer, in_window

    def evaluate_state(self, state: RuleState) -> RiskDecision:
        state.roll_day_if_needed(self.spec.timezone)
        state.update_drawdown_start(self.spec.drawdown_limit_pct)

        if self._disabled:
            reason = self._disable_reason or "Trading disabled"
            decision = RiskDecision(False, reason, flatten=True)
            self._notify_flatten(reason)
            self._log("state_check", {"allow": decision.allow, "reason": decision.reason, "flatten": decision.flatten})
            return decision

        violations = self.engine.check_violation(state)
        if violations:
            reason = violations[0].message
            self.disable(reason)
            decision = RiskDecision(False, reason, flatten=True)
            self._notify_flatten(reason)
            self._log("state_check", {"allow": decision.allow, "reason": decision.reason, "flatten": decision.flatten})
            return decision

        headroom = self.rule_headroom(state)
        if headroom["daily"] <= 0 or headroom["max"] <= 0:
            reason = "Hard limit reached"
            self.disable(reason)
            decision = RiskDecision(False, reason, flatten=True)
            self._notify_flatten(reason)
            self._log("state_check", {"allow": decision.allow, "reason": decision.reason, "flatten": decision.flatten})
            return decision

        daily_buffer, max_buffer, in_window = self._effective_buffers(state)
        if in_window and self.spec.midnight_policy == MidnightPolicy.FLATTEN:
            decision = RiskDecision(False, "Midnight flatten policy active", flatten=True)
            self._notify_flatten(decision.reason)
            self._log(
                "state_check",
                {"allow": decision.allow, "reason": decision.reason, "flatten": decision.flatten},
            )
            return decision
        if in_window and self.spec.midnight_policy == MidnightPolicy.REDUCE:
            decision = RiskDecision(False, "Midnight reduce-only policy active", flatten=False, reduce_only=True)
            self._log(
                "state_check",
                {
                    "allow": decision.allow,
                    "reason": decision.reason,
                    "flatten": decision.flatten,
                    "reduce_only": decision.reduce_only,
                },
            )
            return decision

        if headroom["daily"] <= daily_buffer:
            self._notify_buffer("daily", headroom["daily"])
            decision = RiskDecision(False, "Daily loss buffer reached", flatten=False)
            self._log(
                "state_check",
                {"allow": decision.allow, "reason": decision.reason, "flatten": decision.flatten},
            )
            return decision

        if headroom["max"] <= max_buffer:
            self._notify_buffer("max", headroom["max"])
            decision = RiskDecision(False, "Max loss buffer reached", flatten=False)
            self._log(
                "state_check",
                {"allow": decision.allow, "reason": decision.reason, "flatten": decision.flatten},
            )
            return decision

        decision = RiskDecision(True, "Healthy")
        self._log("state_check", {"allow": decision.allow, "reason": decision.reason})
        return decision

    def check_inactivity(self, state: RuleState) -> list[str]:
        warnings: list[str] = []
        days_since = state.days_since_last_trade(self.spec.timezone)
        if days_since is not None:
            warn_after = max(0, self.spec.max_days_without_trade - self.spec.inactivity_warning_days)
            if days_since >= warn_after:
                message = f"Inactivity warning: {days_since} days since last trade"
                warnings.append(message)
                self._notify_inactivity(message)
                self._log("inactivity_warning", {"kind": "no_trade", "days": days_since})

        drawdown_days = state.drawdown_days(self.spec.timezone)
        if drawdown_days is not None:
            warn_after = max(0, self.spec.drawdown_days_limit - self.spec.drawdown_warning_days)
            if drawdown_days >= warn_after:
                message = f"Drawdown duration warning: {drawdown_days} days"
                warnings.append(message)
                self._notify_inactivity(message)
                self._log("inactivity_warning", {"kind": "drawdown", "days": drawdown_days})

        return warnings

    def pre_trade(self, order_intent: OrderIntent, state: RuleState) -> RiskDecision:
        state_check = self.evaluate_state(state)
        if not state_check.allow:
            if order_intent.reduce_only and (state_check.reduce_only or state_check.flatten):
                decision = RiskDecision(True, "Reduce-only allowed", flatten=state_check.flatten, reduce_only=True)
                self._log(
                    "pre_trade",
                    {
                        "allow": decision.allow,
                        "reason": decision.reason,
                        "flatten": decision.flatten,
                        "reduce_only": decision.reduce_only,
                        "symbol": order_intent.symbol,
                        "side": order_intent.side,
                        "volume": order_intent.volume,
                    },
                )
                return decision
            self._log(
                "pre_trade",
                {
                    "allow": state_check.allow,
                    "reason": state_check.reason,
                    "flatten": state_check.flatten,
                    "reduce_only": state_check.reduce_only,
                    "symbol": order_intent.symbol,
                    "side": order_intent.side,
                    "volume": order_intent.volume,
                },
            )
            return state_check

        pre_trade = self.engine.pre_trade_check(order_intent, state)
        if not pre_trade.allow:
            decision = RiskDecision(False, pre_trade.reason, flatten=False)
            self._log(
                "pre_trade",
                {
                    "allow": decision.allow,
                    "reason": decision.reason,
                    "flatten": decision.flatten,
                    "symbol": order_intent.symbol,
                    "side": order_intent.side,
                    "volume": order_intent.volume,
                },
            )
            return decision

        if order_intent.reduce_only:
            decision = RiskDecision(True, "Allowed reduce-only", flatten=False, reduce_only=True)
            self._log(
                "pre_trade",
                {
                    "allow": decision.allow,
                    "reason": decision.reason,
                    "reduce_only": decision.reduce_only,
                    "symbol": order_intent.symbol,
                    "side": order_intent.side,
                    "volume": order_intent.volume,
                },
            )
            return decision

        headroom = self.rule_headroom(state)
        daily_buffer, max_buffer, _ = self._effective_buffers(state)
        if order_intent.estimated_risk >= headroom["daily"] - daily_buffer:
            decision = RiskDecision(False, "Order would breach daily buffer", flatten=False)
            self._log(
                "pre_trade",
                {
                    "allow": decision.allow,
                    "reason": decision.reason,
                    "symbol": order_intent.symbol,
                    "side": order_intent.side,
                    "volume": order_intent.volume,
                },
            )
            return decision

        if order_intent.estimated_risk >= headroom["max"] - max_buffer:
            decision = RiskDecision(False, "Order would breach max buffer", flatten=False)
            self._log(
                "pre_trade",
                {
                    "allow": decision.allow,
                    "reason": decision.reason,
                    "symbol": order_intent.symbol,
                    "side": order_intent.side,
                    "volume": order_intent.volume,
                },
            )
            return decision

        decision = RiskDecision(True, "Allowed", flatten=False)
        self._log(
            "pre_trade",
            {
                "allow": decision.allow,
                "reason": decision.reason,
                "symbol": order_intent.symbol,
                "side": order_intent.side,
                "volume": order_intent.volume,
            },
        )
        return decision
