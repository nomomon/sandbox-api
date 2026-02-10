"""MCP server exposing sandbox API as LLM-friendly tools. Mount at /mcp in the FastAPI app."""

from typing import Any

from fastapi import HTTPException

from app.auth.deps import get_user_id_from_headers
from app.command_validation import ensure_command_allowed
from app.config import settings
from app.orchestrator.container_manager import ContainerOrchestrator
from app.rate_limit import ensure_rate_limit, get_redis
from app.session_manager import SessionManager
from app.workspace_path import resolve_workspace_path
from app.workspace_service import (
    workspace_delete,
    workspace_list,
    workspace_read,
    workspace_write,
)

from fastmcp import FastMCP
from fastmcp.dependencies import Depends
from fastmcp.server.dependencies import get_http_headers

mcp = FastMCP("Sandbox API")


def _require_user_id() -> str:
    """Resolve user_id from request headers (API key or Bearer JWT). Injected by FastMCP."""
    headers = get_http_headers()
    return get_user_id_from_headers(headers or {})


def _get_orchestrator() -> ContainerOrchestrator:
    return ContainerOrchestrator(session_manager=SessionManager())


def _handle_http_error(e: HTTPException) -> dict[str, Any]:
    """Turn HTTPException into an MCP-friendly result dict."""
    return {"error": e.detail, "status_code": e.status_code}


# --- Session tools ---


@mcp.tool
def create_session(
    session_id: str,
    user_id: str = Depends(_require_user_id),
    orchestrator: ContainerOrchestrator = Depends(_get_orchestrator),
    redis_client=Depends(get_redis),
) -> dict[str, Any]:
    """Create or reuse a sandbox session (container). Idempotent for the same session_id."""
    try:
        ensure_rate_limit(redis_client, user_id)
        container = orchestrator.get_or_create_container(session_id, user_id)
        return {"session_id": session_id, "container_id": container.id[:12]}
    except HTTPException as e:
        return _handle_http_error(e)


@mcp.tool
def delete_session(
    session_id: str,
    user_id: str = Depends(_require_user_id),
    orchestrator: ContainerOrchestrator = Depends(_get_orchestrator),
) -> dict[str, Any]:
    """Tear down a session: stop its container and remove from session store."""
    try:
        session = orchestrator.session_manager.get_session(session_id)
        if not session:
            return {"status": "deleted", "session_id": session_id}
        if session.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Session belongs to another user")
        container_id = orchestrator.session_manager.get_container_id(session_id)
        if container_id:
            try:
                container = orchestrator.client.containers.get(container_id)
                container.remove(force=True)
            except Exception:
                pass
        orchestrator.session_manager.delete_session(session_id)
        return {"status": "deleted", "session_id": session_id}
    except HTTPException as e:
        return _handle_http_error(e)


# --- Execute tool ---


@mcp.tool
def execute(
    session_id: str,
    command: str,
    timeout: int = 30,
    working_dir: str = "/workspace",
    user_id: str = Depends(_require_user_id),
    orchestrator: ContainerOrchestrator = Depends(_get_orchestrator),
    redis_client=Depends(get_redis),
) -> dict[str, Any]:
    """Run a command in the session's container. Command must start with an allowed binary (see ALLOWED_COMMANDS)."""
    try:
        ensure_command_allowed(command)
        ensure_rate_limit(redis_client, user_id)
        timeout = max(1, min(timeout, settings.max_exec_timeout_seconds))
        container = orchestrator.get_or_create_container(session_id, user_id)
        orchestrator.session_manager.refresh_session(session_id)
        result = orchestrator.execute_in_container(
            container=container,
            command=command,
            timeout_seconds=timeout,
            workdir=working_dir or "/workspace",
        )
        return {
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "exit_code": result["exit_code"],
            "execution_time": result["execution_time"],
            "container_id": container.id[:12],
        }
    except HTTPException as e:
        return _handle_http_error(e)


# --- Workspace tools ---


@mcp.tool(name="workspace_list")
def workspace_list_dir(
    session_id: str,
    path: str = "",
    user_id: str = Depends(_require_user_id),
    orchestrator: ContainerOrchestrator = Depends(_get_orchestrator),
    redis_client=Depends(get_redis),
) -> dict[str, Any]:
    """List directory entries at path (relative to /workspace). Use empty path for workspace root."""
    try:
        ensure_rate_limit(redis_client, user_id)
        container = orchestrator.get_or_create_container(session_id, user_id)
        orchestrator.session_manager.refresh_session(session_id)
        resolved = resolve_workspace_path(path or "")
        entries = workspace_list(container, resolved)
        return {"entries": [{"name": e["name"], "type": e["type"]} for e in entries]}
    except HTTPException as e:
        return _handle_http_error(e)


@mcp.tool(name="workspace_read")
def workspace_read_file(
    session_id: str,
    path: str,
    user_id: str = Depends(_require_user_id),
    orchestrator: ContainerOrchestrator = Depends(_get_orchestrator),
    redis_client=Depends(get_redis),
) -> dict[str, Any]:
    """Read file at path (relative to /workspace). Returns content and encoding (utf8 or base64)."""
    try:
        ensure_rate_limit(redis_client, user_id)
        container = orchestrator.get_or_create_container(session_id, user_id)
        orchestrator.session_manager.refresh_session(session_id)
        resolved = resolve_workspace_path(path)
        if not resolved:
            raise HTTPException(status_code=400, detail="path is required for read")
        max_size = settings.workspace_max_file_size_bytes
        result = workspace_read(container, resolved, max_size=max_size)
        return {"content": result["content"], "encoding": result["encoding"]}
    except HTTPException as e:
        return _handle_http_error(e)


@mcp.tool(name="workspace_write")
def workspace_write_file(
    session_id: str,
    path: str,
    content: str,
    user_id: str = Depends(_require_user_id),
    orchestrator: ContainerOrchestrator = Depends(_get_orchestrator),
    redis_client=Depends(get_redis),
) -> dict[str, Any]:
    """Write content to file at path (relative to /workspace). Creates parent directories if needed."""
    try:
        ensure_rate_limit(redis_client, user_id)
        container = orchestrator.get_or_create_container(session_id, user_id)
        orchestrator.session_manager.refresh_session(session_id)
        resolved = resolve_workspace_path(path)
        if not resolved:
            raise HTTPException(status_code=400, detail="path is required for write")
        max_size = settings.workspace_max_file_size_bytes
        workspace_write(container, resolved, content.encode("utf-8"), max_size=max_size)
        return {"status": "written", "path": path}
    except HTTPException as e:
        return _handle_http_error(e)


@mcp.tool(name="workspace_delete")
def workspace_delete_path(
    session_id: str,
    path: str,
    user_id: str = Depends(_require_user_id),
    orchestrator: ContainerOrchestrator = Depends(_get_orchestrator),
    redis_client=Depends(get_redis),
) -> dict[str, Any]:
    """Delete file or directory at path (relative to /workspace)."""
    try:
        ensure_rate_limit(redis_client, user_id)
        container = orchestrator.get_or_create_container(session_id, user_id)
        orchestrator.session_manager.refresh_session(session_id)
        resolved = resolve_workspace_path(path)
        if not resolved:
            raise HTTPException(status_code=400, detail="path is required for delete")
        workspace_delete(container, resolved)
        return {"status": "deleted", "path": path}
    except HTTPException as e:
        return _handle_http_error(e)


if __name__ == "__main__":
    mcp.run()
