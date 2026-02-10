"""Redis-backed session management for container lifecycle."""

from datetime import datetime, timezone
from typing import Any

import redis

from app.config import settings


class SessionManager:
    """Manage user sessions and container mapping with Redis and TTL."""

    def __init__(self, redis_client: redis.Redis | None = None):
        if redis_client is not None:
            self.redis = redis_client
        else:
            self.redis = redis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
        self.session_ttl = settings.session_ttl_seconds

    def _session_key(self, session_id: str) -> str:
        return f"session:{session_id}"

    def _container_key(self, session_id: str) -> str:
        return f"container:{session_id}"

    def create_session(
        self,
        session_id: str,
        user_id: str,
        container_id: str,
    ) -> None:
        """Create session with TTL (sliding window)."""
        session_key = self._session_key(session_id)
        container_key = self._container_key(session_id)
        now = datetime.now(timezone.utc).isoformat()

        self.redis.hset(
            session_key,
            mapping={
                "user_id": user_id,
                "container_id": container_id,
                "created_at": now,
                "command_count": "0",
            },
        )
        self.redis.expire(session_key, self.session_ttl)

        self.redis.set(container_key, container_id, ex=self.session_ttl)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve session data. Returns None if not found or expired."""
        session_key = self._session_key(session_id)
        if not self.redis.exists(session_key):
            return None
        raw = self.redis.hgetall(session_key)
        return raw if raw else None

    def get_container_id(self, session_id: str) -> str | None:
        """Get container id for session if it exists."""
        container_key = self._container_key(session_id)
        return self.redis.get(container_key)

    def refresh_session(self, session_id: str) -> bool:
        """Extend session TTL on activity; increment command_count. Returns True if session existed."""
        session_key = self._session_key(session_id)
        container_key = self._container_key(session_id)
        if not self.redis.exists(session_key):
            return False
        self.redis.expire(session_key, self.session_ttl)
        self.redis.expire(container_key, self.session_ttl)
        self.redis.hincrby(session_key, "command_count", 1)
        return True

    def delete_session(self, session_id: str) -> None:
        """Remove session and container keys."""
        self.redis.delete(self._session_key(session_id))
        self.redis.delete(self._container_key(session_id))

    def set_container_for_session(
        self,
        session_id: str,
        container_id: str,
    ) -> None:
        """Update container id for an existing session and refresh TTL."""
        container_key = self._container_key(session_id)
        self.redis.set(container_key, container_id, ex=self.session_ttl)
        session_key = self._session_key(session_id)
        if self.redis.exists(session_key):
            self.redis.hset(session_key, "container_id", container_id)
            self.redis.expire(session_key, self.session_ttl)
