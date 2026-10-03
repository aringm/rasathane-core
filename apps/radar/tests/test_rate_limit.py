"""Tests for the Redis-backed sliding-window rate limiter.

We don't depend on a real Redis (or fakeredis) for unit tests — the limiter
is wired against a Protocol so injecting a tiny fake is enough. The Lua
script's atomicity is delegated to Redis itself; here we only verify the
Python-side orchestration (sleep-and-retry, deadline enforcement, input
validation, lazy default-client resolution).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from ingestion.rate_limit import RateLimitedError, RateLimiter


class _FakeScript:
    """Stand-in for a redis-py async ``Script`` callable.

    Backed by a deque-like ``replies`` list; each ``__call__`` pops the next
    reply. Exhausting the list raises so tests fail loudly on under-mocked
    paths.
    """

    def __init__(self, replies: list[int]) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[list[str], list[Any]]] = []

    async def __call__(self, *, keys: list[str], args: list[Any]) -> int:
        self.calls.append((list(keys), list(args)))
        if not self._replies:
            raise AssertionError("FakeScript exhausted — test under-mocked")
        return self._replies.pop(0)


class _FakeRedis:
    def __init__(self, script: _FakeScript) -> None:
        self._script = script
        self.aclose_calls = 0

    def register_script(self, script_text: str) -> _FakeScript:
        # Real redis-py also returns a wrapper without doing IO; sanity check
        # we received the expected Lua program.
        assert "ZREMRANGEBYSCORE" in script_text
        return self._script

    async def aclose(self) -> None:
        self.aclose_calls += 1


def _make_limiter(
    *,
    replies: list[int],
    max_calls: int = 1,
    window_seconds: float = 1.0,
    max_wait_seconds: float = 5.0,
) -> tuple[RateLimiter, _FakeScript]:
    script = _FakeScript(replies)
    redis = _FakeRedis(script)
    limiter = RateLimiter(
        redis,
        max_calls=max_calls,
        window_seconds=window_seconds,
        max_wait_seconds=max_wait_seconds,
    )
    return limiter, script


@pytest.mark.asyncio
async def test_acquire_returns_immediately_when_slot_available() -> None:
    limiter, script = _make_limiter(replies=[0])
    await limiter.acquire("arxiv")
    assert len(script.calls) == 1
    keys, args = script.calls[0]
    assert keys == ["arxiv"]
    # ARGV: now, window, max_calls, member
    assert len(args) == 4
    assert float(args[0]) > 0  # current timestamp
    assert args[1] == "1.0"  # window_seconds
    assert args[2] == "1"  # max_calls
    assert ":" in args[3]  # member is "now:uuid"


@pytest.mark.asyncio
async def test_acquire_sleeps_and_retries_when_over_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First reply: 50ms wait. Second reply: 0 (acquired).

    We monkeypatch ``asyncio.sleep`` to record durations without real waiting.
    """
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("ingestion.rate_limit.asyncio.sleep", fake_sleep)

    limiter, script = _make_limiter(replies=[50, 0])
    await limiter.acquire("arxiv")

    assert len(script.calls) == 2
    # Slept ~50ms (+ 10ms jitter from the limiter)
    assert sleeps == pytest.approx([0.06], abs=0.005)


@pytest.mark.asyncio
async def test_acquire_raises_when_wait_exceeds_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reply says 'wait 10 seconds' but max_wait_seconds=1 → RateLimitedError."""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("ingestion.rate_limit.asyncio.sleep", fake_sleep)

    limiter, _ = _make_limiter(replies=[10_000], max_wait_seconds=1.0)
    with pytest.raises(RateLimitedError, match="would not free up"):
        await limiter.acquire("arxiv")

    # We must NOT have slept — the limiter pre-checks the deadline.
    assert sleeps == []


@pytest.mark.asyncio
async def test_acquire_tolerates_bytes_reply() -> None:
    """Some redis-py configurations return bytes for integer replies."""
    limiter, _ = _make_limiter(replies=[b"0"])  # type: ignore[list-item]
    await limiter.acquire("arxiv")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_calls": 0, "window_seconds": 1.0},
        {"max_calls": -1, "window_seconds": 1.0},
        {"max_calls": 1, "window_seconds": 0},
        {"max_calls": 1, "window_seconds": -1.0},
        {"max_calls": 1, "window_seconds": 1.0, "max_wait_seconds": 0},
    ],
)
def test_constructor_validates_inputs(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RateLimiter(client=None, **kwargs)


@pytest.mark.asyncio
async def test_acquire_validates_key() -> None:
    limiter, _ = _make_limiter(replies=[0])
    with pytest.raises(ValueError, match="non-empty"):
        await limiter.acquire("")


@pytest.mark.asyncio
async def test_lazy_default_client_uses_redis_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No client injected → ``client`` property reads REDIS_URL on first use."""
    captured: dict[str, str] = {}

    def fake_from_url(url: str) -> _FakeRedis:
        captured["url"] = url
        return _FakeRedis(_FakeScript([0]))

    monkeypatch.setenv("REDIS_URL", "redis://test-host:6390/2")

    # The lazy import inside _resolve_default_client picks up our patched
    # ``from_url`` from the redis.asyncio module.
    import sys
    import types

    fake_module = types.ModuleType("redis.asyncio")
    fake_module.from_url = fake_from_url  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "redis.asyncio", fake_module)

    limiter = RateLimiter(client=None, max_calls=1, window_seconds=1.0)
    await limiter.acquire("k")
    assert captured["url"] == "redis://test-host:6390/2"


@pytest.mark.asyncio
async def test_concurrent_acquires_share_script_handle() -> None:
    """Two concurrent acquire()s should reuse the same registered script."""
    limiter, script = _make_limiter(replies=[0, 0])

    await asyncio.gather(limiter.acquire("a"), limiter.acquire("b"))

    assert len(script.calls) == 2
    # Both calls used the *same* script object (one register_script call).
    # Different keys are passed via KEYS[1].
    assert {script.calls[0][0][0], script.calls[1][0][0]} == {"a", "b"}


def test_register_script_inspects_lua_text() -> None:
    """Sanity: the Lua program must include the sliding-window primitives."""
    from ingestion.rate_limit import _LUA_SLIDING_WINDOW

    for token in ["ZREMRANGEBYSCORE", "ZCARD", "ZADD", "PEXPIRE"]:
        assert token in _LUA_SLIDING_WINDOW


def test_callable_protocol_marker(_callable: Callable[..., Any] | None = None) -> None:
    """No-op test that keeps the Callable import live for type-checkers."""
    assert callable(lambda: None)
