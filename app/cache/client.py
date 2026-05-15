from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RedisClient:
    def __init__(self) -> None:
        self._pool: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._pool = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        await self._pool.ping()
        logger.info("redis_connected", url=settings.redis_url)

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.aclose()
            logger.info("redis_disconnected")

    @property
    def client(self) -> aioredis.Redis:
        if not self._pool:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._pool

    async def get(self, key: str) -> str | None:
        return await self.client.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if ttl:
            await self.client.setex(key, ttl, str(value))
        else:
            await self.client.set(key, str(value))

    async def set_nx(self, key: str, value: Any, ttl: int) -> bool:
        """Set key only if it does not exist (atomic). Returns True if set."""
        return await self.client.set(key, str(value), nx=True, ex=ttl) is not None

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def incr(self, key: str) -> int:
        return await self.client.incr(key)

    async def expire(self, key: str, seconds: int) -> None:
        await self.client.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        return await self.client.ttl(key)

    async def exists(self, key: str) -> bool:
        return bool(await self.client.exists(key))

    # ── Rate limiting helpers ──────────────────────────────────────────────

    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """
        Sliding window rate limit.
        Returns (is_allowed, remaining_seconds_until_reset).
        """
        pipe = self.client.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        results = await pipe.execute()
        count: int = results[0]
        current_ttl: int = results[1]

        if count == 1:
            await self.client.expire(key, window_seconds)
            current_ttl = window_seconds

        if count > max_requests:
            return False, max(current_ttl, 0)
        return True, 0

    async def check_anti_flood(self, key: str, min_interval: float) -> bool:
        """Returns True if action is allowed (enough time has passed)."""
        import time
        now = time.time()
        last_str = await self.get(key)
        if last_str:
            last = float(last_str)
            if now - last < min_interval:
                return False
        ttl = max(int(min_interval) + 1, 2)
        await self.set(key, str(now), ttl=ttl)
        return True


redis_client = RedisClient()
