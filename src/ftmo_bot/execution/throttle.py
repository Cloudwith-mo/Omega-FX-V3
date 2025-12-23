"""Request throttling to avoid excessive broker traffic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from ftmo_bot.rule_engine.time import day_start_for


@dataclass(frozen=True)
class ThrottleDecision:
    allow: bool
    reason: str


class RequestThrottle:
    def __init__(
        self,
        max_requests_per_day: int = 1800,
        max_modifications_per_minute: int = 60,
        min_seconds_between_requests: int = 0,
        timezone: str = "Europe/Prague",
    ) -> None:
        self.max_requests_per_day = max_requests_per_day
        self.max_modifications_per_minute = max_modifications_per_minute
        self.min_seconds_between_requests = min_seconds_between_requests
        self.timezone = timezone
        self._day_start: Optional[datetime] = None
        self._daily_count = 0
        self._mod_minute_start: Optional[datetime] = None
        self._mod_count = 0
        self._last_request_time: Optional[datetime] = None

    def allow(self, kind: str, now: Optional[datetime] = None) -> ThrottleDecision:
        if now is None:
            now = datetime.now(tz=ZoneInfo(self.timezone))
        elif now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo(self.timezone))

        day_start = day_start_for(now, self.timezone)
        if self._day_start is None or day_start > self._day_start:
            self._day_start = day_start
            self._daily_count = 0

        if self.max_requests_per_day > 0 and self._daily_count >= self.max_requests_per_day:
            return ThrottleDecision(False, "Daily request cap reached")

        if self.min_seconds_between_requests > 0 and self._last_request_time is not None:
            if (now - self._last_request_time).total_seconds() < self.min_seconds_between_requests:
                return ThrottleDecision(False, "Request rate too high")

        if kind in {"modify", "cancel"} and self.max_modifications_per_minute > 0:
            if self._mod_minute_start is None or now - self._mod_minute_start >= timedelta(minutes=1):
                self._mod_minute_start = now
                self._mod_count = 0
            if self._mod_count >= self.max_modifications_per_minute:
                return ThrottleDecision(False, "Modification rate cap reached")

        self._daily_count += 1
        self._last_request_time = now
        if kind in {"modify", "cancel"}:
            self._mod_count += 1

        return ThrottleDecision(True, "Allowed")
