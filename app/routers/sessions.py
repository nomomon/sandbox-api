"""Optional session lifecycle: create and delete sessions explicitly."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.deps import get_current_user_id
from app.orchestrator.container_manager import ContainerOrchestrator
from app.session_manager import SessionManager

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=256)


def get_orchestrator() -> ContainerOrchestrator:
    return ContainerOrchestrator(session_manager=SessionManager())


@router.post("")
def create_session(
    body: CreateSessionRequest,
    user_id: str = Depends(get_current_user_id),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
):
    """Create a session (container) for the given session_id. Idempotent: reuses existing."""
    session_id = body.session_id
    container = orchestrator.get_or_create_container(session_id, user_id)
    return {"session_id": session_id, "container_id": container.id[:12]}


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
):
    """Tear down session: stop container and remove from Redis."""
    session = orchestrator.session_manager.get_session(session_id)
    if not session:
        return {"status": "deleted", "session_id": session_id}
    if session.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session belongs to another user")
    container_id = orchestrator.session_manager.get_container_id(session_id)
    if container_id:
        try:
            container = orchestrator.client.containers.get(container_id)
            container.remove(force=True)
        except Exception:
            pass
    orchestrator.session_manager.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}
