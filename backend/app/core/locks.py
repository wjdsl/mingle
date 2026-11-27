"""Redis 기반 분산 락. Redis가 없으면 프로세스 내 락으로 동작한다."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover
    redis = None


class DistributedLock:
    _local_locks: dict[str, asyncio.Lock] = {}

    def __init__(self, key: str, redis_url: str | None = None, ttl: int = 30) -> None:
        self.key = key
        self.redis_url = redis_url
        self.ttl = ttl
        self._redis: Any = None
        if redis_url and redis is not None:
            self._redis = redis.from_url(redis_url, decode_responses=True)
        self._local = self._local_locks.setdefault(key, asyncio.Lock())

    async def __aenter__(self) -> "DistributedLock":
        if self._redis is not None:
            try:
                while not await self._redis.set(self.key, "1", nx=True, ex=self.ttl):
                    await asyncio.sleep(0.05)
                return self
            except Exception:
                pass
        await self._local.acquire()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._redis is not None:
            try:
                await self._redis.delete(self.key)
                return
            except Exception:
                pass
        self._local.release()