import logging
import time

from fastapi import Request

from app.core.errors import AppError

log = logging.getLogger(__name__)


class RateLimited(AppError):
    status_code, code = 429, "rate_limited"


class RateLimiter:
    """Fixed-window limiter backed by Redis (app.state.redis). Fails open if Redis is down."""

    def __init__(self, limit_getter, scope: str, window: int = 60):
        self.limit_getter, self.scope, self.window = limit_getter, scope, window

    async def __call__(self, request: Request) -> None:
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
        key = f"rl:{self.scope}:{ip}:{int(time.time() // self.window)}"
        try:
            n = await redis.incr(key)
            if n == 1:
                await redis.expire(key, self.window)
        except Exception:  # noqa: BLE001
            log.warning("rate limiter unavailable; failing open")
            return
        if n > self.limit_getter():
            raise RateLimited("Too many requests. Please slow down.")
