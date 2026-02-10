"""Execute endpoint: validate, rate-limit, get/create container, exec, return result."""

import structlog
from fastapi import APIRouter, Depends

from app.auth.deps import get_current_user_id
from app.command_validation import ensure_command_allowed
from app.config import settings
from app.orchestrator.container_manager import ContainerOrchestrator
from app.rate_limit import ensure_rate_limit, get_redis
from app.schemas import CommandRequest, CommandResponse
from app.session_manager import SessionManager

router = APIRouter(prefix="", tags=["execute"])
logger = structlog.get_logger()


def get_orchestrator() -> ContainerOrchestrator:
    return ContainerOrchestrator(session_manager=SessionManager())


@router.post("/execute", response_model=CommandResponse)
async def execute_command(
    body: CommandRequest,
    user_id: str = Depends(get_current_user_id),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
):
    """Execute a command in an isolated container for the given session."""
    ensure_command_allowed(body.command)
    redis_client = get_redis()
    ensure_rate_limit(redis_client, user_id)

    container = orchestrator.get_or_create_container(body.session_id, user_id)
    orchestrator.session_manager.refresh_session(body.session_id)

    result = orchestrator.execute_in_container(
        container=container,
        command=body.command,
        timeout_seconds=body.timeout,
        workdir=body.working_dir or "/workspace",
    )

    logger.info(
        "command_executed",
        user_id=user_id,
        session_id=body.session_id,
        command=body.command[:200],
        exit_code=result["exit_code"],
        execution_time=result["execution_time"],
        container_id=container.id[:12],
    )

    return CommandResponse(
        stdout=result["stdout"],
        stderr=result["stderr"],
        exit_code=result["exit_code"],
        execution_time=result["execution_time"],
        container_id=container.id[:12],
    )
