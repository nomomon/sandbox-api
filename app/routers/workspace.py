"""Workspace file tools: list, read, write, delete within a session's /workspace."""

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response

from app.auth.deps import get_current_user_id
from app.config import settings
from app.orchestrator.container_manager import ContainerOrchestrator
from app.rate_limit import ensure_rate_limit, get_redis
from app.schemas import (
    WorkspaceContentResponse,
    WorkspaceEntry,
    WorkspaceListResponse,
)
from app.session_manager import SessionManager
from app.workspace_path import resolve_workspace_path
from app.workspace_service import (
    workspace_delete,
    workspace_list,
    workspace_read,
    workspace_write,
)

router = APIRouter(prefix="/sessions", tags=["workspace"])
logger = structlog.get_logger()


def get_orchestrator() -> ContainerOrchestrator:
    return ContainerOrchestrator(session_manager=SessionManager())


def _get_container_and_path(
    session_id: str,
    path: str,
    user_id: str,
    orchestrator: ContainerOrchestrator,
):
    """Resolve container, refresh session, validate path. Returns (container, resolved_path)."""
    redis_client = get_redis()
    ensure_rate_limit(redis_client, user_id)
    container = orchestrator.get_or_create_container(session_id, user_id)
    orchestrator.session_manager.refresh_session(session_id)
    resolved = resolve_workspace_path(path if path is not None else "")
    return container, resolved


@router.get("/{session_id}/workspace", response_model=WorkspaceListResponse)
async def list_workspace(
    session_id: str,
    path: str = Query(default="", description="Path relative to /workspace"),
    user_id: str = Depends(get_current_user_id),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
):
    """List directory entries at path (relative to /workspace). Default path is workspace root."""
    container, resolved = _get_container_and_path(session_id, path or "", user_id, orchestrator)
    entries = workspace_list(container, resolved)
    return WorkspaceListResponse(
        entries=[WorkspaceEntry(name=e["name"], type=e["type"]) for e in entries],
    )


@router.get("/{session_id}/workspace/content", response_model=WorkspaceContentResponse)
async def read_workspace_content(
    session_id: str,
    path: str = Query(..., min_length=1, description="Path relative to /workspace"),
    user_id: str = Depends(get_current_user_id),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
):
    """Read file at path (relative to /workspace). Returns content and encoding (utf8 or base64)."""
    container, resolved = _get_container_and_path(session_id, path, user_id, orchestrator)
    max_size = settings.workspace_max_file_size_bytes
    result = workspace_read(container, resolved, max_size=max_size)
    return WorkspaceContentResponse(content=result["content"], encoding=result["encoding"])


@router.put("/{session_id}/workspace/content")
async def write_workspace_content(
    request: Request,
    session_id: str,
    path: str = Query(..., min_length=1, description="Path relative to /workspace"),
    user_id: str = Depends(get_current_user_id),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
):
    """Write content to file at path. Body: raw bytes or JSON {"content": "..."}. Creates parent dirs."""
    container, resolved = _get_container_and_path(session_id, path, user_id, orchestrator)
    max_size = settings.workspace_max_file_size_bytes
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        content = (body.get("content") or "").encode("utf-8")
    else:
        content = await request.body()
    workspace_write(container, resolved, content, max_size=max_size)
    return Response(status_code=204)


@router.delete("/{session_id}/workspace")
async def delete_workspace_path(
    session_id: str,
    path: str = Query(..., min_length=1, description="Path relative to /workspace"),
    user_id: str = Depends(get_current_user_id),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
):
    """Delete file or directory at path (relative to /workspace)."""
    container, resolved = _get_container_and_path(session_id, path, user_id, orchestrator)
    workspace_delete(container, resolved)
    return Response(status_code=204)
