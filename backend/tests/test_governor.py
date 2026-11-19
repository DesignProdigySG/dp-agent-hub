import asyncio

import pytest

from app.marketo.governor import QuotaExceeded, RateGovernor


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_window_never_exceeds_limit():
    clock = FakeClock()
    gov = RateGovernor(calls=100, window_s=20, clock=clock)
    admitted: list[float] = []
    while len(admitted) < 350:
        wait = gov.reserve()
        if wait:
            assert wait > 0
            clock.t += wait
        else:
            admitted.append(clock.t)
            clock.t += 0.01  # callers hammer as fast as they can
    for i, t in enumerate(admitted):
        in_window = [x for x in admitted[i:] if x - t < 20]
        assert len(in_window) <= 100


def test_first_100_are_immediate_then_waits():
    clock = FakeClock()
    gov = RateGovernor(calls=100, window_s=20, clock=clock)
    assert all(gov.reserve() == 0 for _ in range(100))
    assert gov.reserve() == pytest.approx(20.25)
    clock.t = 20.25
    assert gov.reserve() == 0


async def test_concurrency_cap():
    gov = RateGovernor(calls=1000, window_s=1, max_concurrent=3)
    peak = 0

    async def call():
        nonlocal peak
        peak = max(peak, gov.stats().in_flight)
        await asyncio.sleep(0.01)

    await asyncio.gather(*(gov.run("rest", call) for _ in range(20)))
    assert peak == 3
    stats = gov.stats()
    assert stats.in_flight == 0 and stats.queued == 0
    assert stats.by_channel == {"rest": 20}


async def test_rest_and_mcp_share_one_budget():
    gov = RateGovernor(calls=1000, window_s=20)

    async def noop():
        return None

    await asyncio.gather(*(gov.run(ch, noop) for ch in ["rest", "mcp"] * 5))
    assert gov.stats().calls_in_window == 10
    assert gov.stats().by_channel == {"rest": 5, "mcp": 5}


async def test_daily_quota():
    gov = RateGovernor(daily_quota=2)

    async def noop():
        return None

    await gov.run("rest", noop)
    await gov.run("mcp", noop)
    with pytest.raises(QuotaExceeded):
        await gov.run("rest", noop)
    assert gov.stats().queued == 0
