"""
Rate limiting (tiêu chí 7) — Sliding Window trên Redis Sorted Set.

- Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây.
- Vượt giới hạn → HTTP 429 kèm header Retry-After và X-RateLimit-*.
- State lưu trong Redis để mọi worker/instance dùng chung và giữ nguyên sau restart.
"""
import hashlib
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("agent")

WINDOW_SECONDS = 60
_fallback_windows: dict[str, deque[float]] = defaultdict(deque)


def _key_id(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:24]


def _raise_429(limit: int, retry_after: int) -> None:
    raise HTTPException(
        status_code=429,
        detail={
            "error": "Rate limit exceeded",
            "limit": limit,
            "window_seconds": WINDOW_SECONDS,
            "retry_after_seconds": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": "0",
        },
    )


def check_rate_limit(key: str) -> dict:
    """Kiểm tra sliding window rate limit; trả thông tin quota còn lại hoặc raise 429."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"ratelimit:{_key_id(key)}"

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            _, current_count = pipe.execute()

            if current_count >= limit:
                oldest = r.zrange(redis_key, 0, 0, withscores=True)
                if oldest:
                    retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
                else:
                    retry_after = WINDOW_SECONDS
                _raise_429(limit, retry_after)

            member = f"{now}:{uuid.uuid4().hex}"
            pipe = r.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, WINDOW_SECONDS + 5)
            pipe.execute()

            return {
                "limit": limit,
                "remaining": max(0, limit - current_count - 1),
                "storage": "redis",
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Redis unavailable in rate limiter, falling back to memory: %s", exc)

    # Fallback in-memory chỉ khi Redis không kết nối được
    window = _fallback_windows[redis_key]
    while window and window[0] < window_start:
        window.popleft()
    if len(window) >= limit:
        retry_after = max(1, int(window[0] + WINDOW_SECONDS - now) + 1)
        _raise_429(limit, retry_after)
    window.append(now)
    return {
        "limit": limit,
        "remaining": max(0, limit - len(window)),
        "storage": "memory",
    }
