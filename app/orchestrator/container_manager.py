"""Container lifecycle: create, exec, and teardown with security and resource limits."""

import concurrent.futures
import re
import time
from datetime import datetime, timezone
from typing import Any

import docker
from docker.types import Ulimit

from app.config import settings
from app.session_manager import SessionManager


# Label used by cleanup worker to find our containers
SESSION_LABEL = "exec.session_id"
USER_LABEL = "exec.user_id"
CREATED_AT_LABEL = "exec.created_at"


def _sanitize_name(s: str) -> str:
    """Allow only alphanumeric and hyphen for container names."""
    return re.sub(r"[^a-zA-Z0-9-]", "-", s)[:64]


class ContainerOrchestrator:
    """Get or create per-session containers and execute commands with timeouts."""

    def __init__(
        self,
        docker_client: docker.DockerClient | None = None,
        session_manager: SessionManager | None = None,
    ):
        self.client = docker_client or docker.from_env()
        self.session_manager = session_manager or SessionManager()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=32)

    def _container_config(self, session_id: str, user_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        name = f"exec-{_sanitize_name(user_id)}-{_sanitize_name(session_id)}"
        return {
            "image": settings.container_image,
            "name": name,
            "detach": True,
            "command": ["sleep", "infinity"],
            "security_opt": ["no-new-privileges"],
            "cap_drop": ["ALL"],
            "read_only": True,
            "network_mode": "none",
            "user": "1000:1000",
            "mem_limit": settings.container_mem_limit,
            "memswap_limit": settings.container_memswap_limit,
            "cpu_period": settings.container_cpu_period,
            "cpu_quota": settings.container_cpu_quota,
            "pids_limit": settings.container_pids_limit,
            "tmpfs": {
                "/tmp": f"rw,noexec,nosuid,size={settings.container_tmpfs_tmp_size}",
                "/workspace": f"rw,noexec,nosuid,size={settings.container_tmpfs_workspace_size}",
            },
            "ulimits": [
                Ulimit(
                    name="nofile",
                    soft=settings.container_ulimit_nofile_soft,
                    hard=settings.container_ulimit_nofile_hard,
                ),
                Ulimit(
                    name="nproc",
                    soft=settings.container_ulimit_nproc_soft,
                    hard=settings.container_ulimit_nproc_hard,
                ),
            ],
            "labels": {
                USER_LABEL: user_id,
                SESSION_LABEL: session_id,
                CREATED_AT_LABEL: now,
            },
        }

    def get_or_create_container(self, session_id: str, user_id: str):  # noqa: ANN201
        """
        Return existing container for session or create a new one.
        Stores container id in Redis with TTL. On Docker NotFound, clears Redis and creates new.
        """
        container_id = self.session_manager.get_container_id(session_id)
        if container_id:
            try:
                container = self.client.containers.get(container_id)
                if container.status == "running":
                    return container
                # Exited; remove and create new
                try:
                    container.remove(force=True)
                except Exception:
                    pass
                self.session_manager.delete_session(session_id)
            except docker.errors.NotFound:
                self.session_manager.delete_session(session_id)

        config = self._container_config(session_id, user_id)
        container = self.client.containers.create(**config)
        container.start()
        self.session_manager.create_session(session_id, user_id, container.id)
        return container

    def execute_in_container(
        self,
        container,  # docker.models.Container
        command: str,
        timeout_seconds: int,
        workdir: str = "/workspace",
    ) -> dict[str, Any]:
        """
        Run command in container via exec. Returns dict with stdout, stderr, exit_code, execution_time.
        Enforces timeout using thread pool; on timeout, kills exec and returns exit_code -1 and stderr message.
        """
        timeout = min(
            max(1, timeout_seconds),
            settings.max_exec_timeout_seconds,
        )
        start = time.perf_counter()

        def run_exec() -> tuple[str, str, int]:
            exec_result = container.exec_run(
                ["sh", "-c", command],
                demux=True,
                stdout=True,
                stderr=True,
                user="1000:1000",
                workdir=workdir,
            )
            out = exec_result.output
            stdout_b = out[0] if out and out[0] is not None else b""
            stderr_b = out[1] if out and len(out) > 1 and out[1] is not None else b""
            return (
                stdout_b.decode("utf-8", errors="replace"),
                stderr_b.decode("utf-8", errors="replace"),
                exec_result.exit_code or 0,
            )

        try:
            future = self._executor.submit(run_exec)
            stdout, stderr, exit_code = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            elapsed = time.perf_counter() - start
            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "exit_code": -1,
                "execution_time": round(elapsed, 3),
            }
        except Exception as e:
            elapsed = time.perf_counter() - start
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "execution_time": round(elapsed, 3),
            }

        elapsed = time.perf_counter() - start
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "execution_time": round(elapsed, 3),
        }
