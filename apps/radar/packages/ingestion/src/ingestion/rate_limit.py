"""Redis-backed sliding-window rate limiter.

Used by ingesters that hit APIs with strict request budgets (ArXiv: 1 req/3s
courtesy; Phase 8B Reddit/Twitter will piggy-back on the same primitive).

Implementation notes:
    - **Sliding window** (not fixed bucket): counts requests within the last
      ``window_seconds`` continuously, so the limit can't be gamed at window
      boundaries.
    - **Atomic via Lua**: the script does ZREMRANGEBYSCORE + ZCARD + ZADD +
      PEXPIRE in one round trip; without atomicity two concurrent workers
      could both pass the under-quota check and both add → over-quota.
    - **Sleep-and-retry**: when over quota the script returns the
      milliseconds until the oldest entry expires; client sleeps and retries.
    - **Lazy env**: if no client is injected, ``redis.asyncio.from_url`` is
      built from ``REDIS_URL``; tests inject a fake.
    - Members are caller-supplied UUIDs to guarantee uniqueness; otherwise
      simultaneous calls with identical float timestamps would collapse to a
      single ZSET member and we'd undercount.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any, Protocol

import structlog

log = structlog.get_logger()


class RateLimitedError(RuntimeError):
    """Could not acquire a slot within ``max_wait_seconds`` of waiting."""


class _LuaScriptCallable(Protocol):
    async def __call__(self, *, keys: list[str], args: list[Any]) -> Any: ...


class RedisLike(Protocol):
    """Subset of ``redis.asyncio.Redis`` we depend on (eases test injection)."""

    def register_script(self, script: str) -> _LuaScriptCallable: ...

    async def aclose(self) -> None: ...


# Returns 0 (int) when accepted; otherwise wait time in milliseconds (int).
_LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_calls = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now - window

redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)
local count = redis.call('ZCARD', key)
if count < max_calls then
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, math.ceil(window * 1000) + 1000)
    return 0
end

local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local oldest_score = tonumber(oldest[2])
local wait_ms = math.ceil((oldest_score + window - now) * 1000)
if wait_ms < 1 then
    wait_ms = 1
end
return wait_ms
"""


def _resolve_default_client() -> RedisLike:
    """Build a redis.asyncio client from REDIS_URL (lazy — only on demand)."""
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0").strip()
    from redis.asyncio import from_url

    return from_url(url)


class RateLimiter:
    """Redis-backed sliding-window limiter.

    Example::

        limiter = RateLimiter(client, max_calls=1, window_seconds=3.0)
        await limiter.acquire("arxiv")
        # → blocks (and retries) until a slot is available, then returns.
    """

    def __init__(
        self,
        client: RedisLike | None = None,
        *,
        max_calls: int,
        window_seconds: float,
        max_wait_seconds: float = 60.0,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds must be > 0")
        self._client = client
        self._max_calls = max_calls
        self._window_seconds = float(window_seconds)
        self._max_wait_seconds = float(max_wait_seconds)
        self._script: _LuaScriptCallable | None = None

    @property
    def client(self) -> RedisLike:
        if self._client is None:
            self._client = _resolve_default_client()
        return self._client

    def _get_script(self) -> _LuaScriptCallable:
        if self._script is None:
            self._script = self.client.register_script(_LUA_SLIDING_WINDOW)
        return self._script

    async def acquire(self, key: str) -> None:
        if not key:
            raise ValueError("key must be a non-empty string")

        deadline = time.monotonic() + self._max_wait_seconds
        script = self._get_script()

        while True:
            now = time.time()
            member = f"{now}:{uuid.uuid4().hex}"
            raw = await script(
                keys=[key],
                args=[
                    str(now),
                    str(self._window_seconds),
                    str(self._max_calls),
                    member,
                ],
            )
            wait_ms = _coerce_int(raw)
            if wait_ms <= 0:
                log.debug("rate_limit.acquired", key=key)
                return

            wait_seconds = wait_ms / 1000.0
            if time.monotonic() + wait_seconds > deadline:
                raise RateLimitedError(
                    f"Rate limit slot for {key!r} would not free up within "
                    f"{self._max_wait_seconds:.1f}s (next slot in {wait_seconds:.2f}s)"
                )
            log.info("rate_limit.wait", key=key, wait_seconds=round(wait_seconds, 3))
            await asyncio.sleep(wait_seconds + 0.01)


def _coerce_int(value: Any) -> int:
    """Redis-py returns int for Lua integer replies; tolerate bytes/str just in case."""
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray)):
        return int(value.decode("ascii"))
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"Unexpected reply type: {type(value).__name__}")
