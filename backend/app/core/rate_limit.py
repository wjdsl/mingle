"""Rate limiter.

기본은 프로세스 내 메모리 버킷이며, ``redis_url`` 이 주어지면 Redis를 사용해
여러 프로세스/인스턴스 간에 카운터를 공유한다.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request, status

try:  # Redis는 선택 의존성이다. 없으면 메모리 구현으로 동작한다.
    import redis.asyncio as redis
except Exception:  # pragma: no cover - import failure fallback
    redis = None


class RateLimiter:
    def __init__(self, times: int, seconds: int, redis_url: str | None = None) -> None:
        self.times = times
        self.seconds = seconds
        self.redis_url = redis_url
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._redis: Any = None
        if redis_url and redis is not None:
            self._redis = redis.from_url(redis_url, decode_responses=True)

    def _key(self, request: Request) -> str:
        client = request.client.host if request.client else "unknown"
        return f"mingle:rl:{request.url.path}:{client}"

    async def __call__(self, request: Request) -> None:
        key = self._key(request)
        if self._redis is not None:
            try:
                current = await self._redis.incr(key)
                if current == 1:
                    await self._redis.expire(key, self.seconds)
                if current > self.times:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Too many requests",
                        headers={"Retry-After": str(self.seconds)},
                    )
                return
            except HTTPException:
                raise
            except Exception:
                # Redis 장애 시 fail-open (메모리 버킷으로 폴백)
                pass

        now = time.monotonic()
        bucket = self._buckets[key]
        while bucket and bucket[0] <= now - self.seconds:
            bucket.popleft()
        if len(bucket) >= self.times:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
                headers={"Retry-After": str(self.seconds)},
            )
        bucket.append(now)