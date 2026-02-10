"""FastAPI application entry point."""

import structlog
from fastapi import FastAPI

from app.config import settings
from app.routers import execute, sessions, workspace

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
)

app.include_router(execute.router)
app.include_router(sessions.router)
app.include_router(workspace.router)


@app.get("/health")
def health():
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness probe (can later check Redis/Docker)."""
    return {"status": "ready"}
