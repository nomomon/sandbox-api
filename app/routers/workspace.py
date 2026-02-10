"""Workspace file tools: list, read, write, delete within a session's /workspace."""

import re
import structlog
from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile

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


def _sanitize_upload_filename(filename: str) -> str:
    """Use only the base name and strip path/special chars. Returns non-empty safe name."""
    if not filename or not filename.strip():
        return "upload"
    base = filename.strip().split("/")[-1].split("\\")[-1]
    # Allow alphanumeric, hyphen, underscore, dot
    safe = re.sub(r"[^\w.\-]", "_", base)
    return safe if safe else "upload"


@router.post("/{session_id}/workspace/upload", status_code=201)
async def upload_workspace_file(
    session_id: str,
    file: UploadFile = File(..., description="File to upload into the session workspace"),
    path: str | None = Query(default=None, description="Path relative to /workspace (default: filename)"),
    user_id: str = Depends(get_current_user_id),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
):
    """Upload a file into the session's workspace (e.g. for the agent to access). Uses multipart form."""
    target = (path or "").strip() or _sanitize_upload_filename(file.filename or "")
    container, resolved = _get_container_and_path(session_id, target, user_id, orchestrator)
    max_size = settings.workspace_max_file_size_bytes
    content = await file.read()
    workspace_write(container, resolved, content, max_size=max_size)
    return {
        "path": resolved,
        "session_id": session_id,
        "size": len(content),
    }


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
