from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from redis.asyncio import Redis


@asynccontextmanager
async def distributed_quota(
    *,
    redis_url: str,
    key: str,
    limit: int,
    timeout_seconds: int,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[None]:
    """Acquire a bounded Redis-backed lease shared by all worker processes."""

    redis = Redis.from_url(redis_url, decode_responses=True)
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    acquired = False
    acquire_script = """
    local value = redis.call('INCR', KEYS[1])
    if value == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
    return value
    """
    release_script = """
    local value = tonumber(redis.call('GET', KEYS[1]) or '0')
    if value > 0 then return redis.call('DECR', KEYS[1]) end
    return 0
    """
    try:
        while True:
            if is_cancelled is not None and await is_cancelled():
                raise asyncio.CancelledError
            current = int(
                await redis.eval(
                    acquire_script,
                    1,
                    key,
                    max(timeout_seconds * 2, 120),
                )
            )
            if current <= limit:
                acquired = True
                break
            await redis.eval(release_script, 1, key)
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"等待并发配额超时: {key}")
            await asyncio.sleep(0.1)
        yield
    finally:
        if acquired:
            await redis.eval(release_script, 1, key)
        await redis.aclose()
