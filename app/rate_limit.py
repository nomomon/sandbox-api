"""Per-user rate limiting using Redis."""

from fastapi import HTTPException, status

import redis

from app.config import settings


def get_redis() -> redis.Redis:
    """Return a Redis client with decode_responses=True for rate limit keys."""
    return redis.from_url(settings.redis_url, decode_responses=True)


def rate_limit_key(user_id: str) -> str:
    return f"rate:{user_id}"


def check_rate_limit(redis_client: redis.Redis, user_id: str) -> bool:
    """
    Check and increment rate limit for user. Returns True if within limit, False if exceeded.
    Uses a simple counter with TTL: each key expires after rate_limit_window_seconds.
    """
    key = rate_limit_key(user_id)
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.ttl(key)
    results = pipe.execute()
    count = results[0]
    ttl = results[1]

    if ttl == -1:
        # First request in window
        redis_client.expire(key, settings.rate_limit_window_seconds)
        ttl = settings.rate_limit_window_seconds

    if count > settings.rate_limit_requests:
        return False
    return True


def ensure_rate_limit(redis_client: redis.Redis, user_id: str) -> None:
    """
    Ensure user is within rate limit. Raises HTTP 429 if exceeded.
    """
    if not check_rate_limit(redis_client, user_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
