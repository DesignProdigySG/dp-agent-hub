"""One rate governor in front of every Marketo call, REST and MCP alike.

Marketo enforces 100 calls per 20 s, 10 concurrent calls, and a daily quota per instance;
both channels draw from the same budget, so they must share one governor.

A sliding-window log is used rather than a token bucket: a bucket of capacity N refilling at
N/window can admit nearly 2N calls inside one window, which Marketo would reject (error 606).
"""

import asyncio
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

from app.events.schema import GovernorStats

T = TypeVar("T")


class QuotaExceeded(RuntimeError):
    pass


class RateGovernor:
    def __init__(
        self,
        calls: int = 100,
        window_s: float = 20.0,
        max_concurrent: int = 10,
        daily_quota: int = 50_000,
        margin_s: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.calls = calls
        self.window_s = window_s
        self.max_concurrent = max_concurrent
        self.daily_quota = daily_quota
        # Slots expire slightly after the window, absorbing clock skew vs. Marketo's counter.
        self._expiry = window_s + margin_s
        self._clock = clock
        self._log: deque[float] = deque()
        self._sem = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()
        self._in_flight = 0
        self._queued = 0
        self._day = datetime.now(UTC).date()
        self._daily_used = 0
        self._by_channel: Counter[str] = Counter()

    def configure(self, calls: int, window_s: float, max_concurrent: int,
                  daily_quota: int, margin_s: float = 0.25) -> None:
        """Apply new limits in place. Calls already holding a slot finish under the old ones."""
        self.calls, self.window_s, self.daily_quota = calls, window_s, daily_quota
        self._expiry = window_s + margin_s
        if max_concurrent != self.max_concurrent:
            self.max_concurrent = max_concurrent
            self._sem = asyncio.Semaphore(max_concurrent)

    def _prune(self, now: float) -> None:
        while self._log and now - self._log[0] >= self._expiry:
            self._log.popleft()

    def reserve(self) -> float:
        """Claim a slot if one is free. Returns 0 on success, else seconds to wait."""
        now = self._clock()
        self._prune(now)
        if len(self._log) < self.calls:
            self._log.append(now)
            return 0.0
        return max(self._log[0] + self._expiry - now, 1e-3)

    def _count_daily(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day, self._daily_used = today, 0
        if self._daily_used >= self.daily_quota:
            raise QuotaExceeded(f"Marketo daily quota of {self.daily_quota} calls reached")
        self._daily_used += 1

    async def run(self, channel: str, fn: Callable[[], Awaitable[T]]) -> T:
        """Run one Marketo call under the window, concurrency, and daily limits."""
        self._queued += 1
        started = False
        try:
            async with self._sem:
                while True:
                    async with self._lock:
                        wait = self.reserve()
                        if wait == 0:
                            self._count_daily()
                            break
                    await asyncio.sleep(wait)
                self._queued -= 1
                started = True
                self._in_flight += 1
                self._by_channel[channel] += 1
                try:
                    return await fn()
                finally:
                    self._in_flight -= 1
        finally:
            if not started:
                self._queued -= 1

    def stats(self) -> GovernorStats:
        self._prune(self._clock())
        return GovernorStats(
            calls_in_window=len(self._log),
            window_limit=self.calls,
            window_s=self.window_s,
            in_flight=self._in_flight,
            max_concurrent=self.max_concurrent,
            queued=self._queued,
            daily_used=self._daily_used,
            daily_quota=self.daily_quota,
            by_channel=dict(self._by_channel),
        )
