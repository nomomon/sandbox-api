"""Cleanup worker: remove expired execution containers and Redis session keys."""

import sys
import time
from datetime import datetime, timezone

import docker
import structlog

from app.config import settings
from app.orchestrator.container_manager import CREATED_AT_LABEL, SESSION_LABEL
from app.session_manager import SessionManager

logger = structlog.get_logger()


def cleanup_expired_containers(
    docker_client: docker.DockerClient,
    session_manager: SessionManager,
    max_age_seconds: int,
) -> int:
    """Remove containers older than max_age_seconds. Return count removed."""
    removed = 0
    try:
        containers = docker_client.containers.list(
            filters={"label": SESSION_LABEL},
            all=True,
        )
    except Exception as e:
        logger.warning("cleanup_list_failed", error=str(e))
        return 0

    now = datetime.now(timezone.utc)
    for container in containers:
        try:
            created_at_str = container.labels.get(CREATED_AT_LABEL)
            if not created_at_str:
                continue
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if (now - created_at).total_seconds() < max_age_seconds:
                continue
            session_id = container.labels.get(SESSION_LABEL)
            container.remove(force=True)
            if session_id:
                session_manager.delete_session(session_id)
            removed += 1
            logger.info(
                "cleanup_removed",
                container_id=container.id[:12],
                session_id=session_id,
            )
        except Exception as e:
            logger.warning(
                "cleanup_container_failed",
                container_id=container.id[:12] if container else None,
                error=str(e),
            )
    return removed


def main() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
    )
    docker_client = docker.from_env()
    session_manager = SessionManager()
    interval = settings.cleanup_interval_seconds
    max_age = settings.cleanup_max_container_age_seconds

    logger.info(
        "cleanup_worker_started",
        interval_seconds=interval,
        max_container_age_seconds=max_age,
    )

    while True:
        try:
            removed = cleanup_expired_containers(
                docker_client,
                session_manager,
                max_age,
            )
            if removed:
                logger.info("cleanup_run_complete", removed=removed)
        except Exception as e:
            logger.exception("cleanup_run_failed", error=str(e))
        time.sleep(interval)


if __name__ == "__main__":
    main()
    sys.exit(0)
