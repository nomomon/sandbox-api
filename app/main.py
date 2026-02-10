"""FastAPI application entry point."""

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from app.config import settings
from app.mcp_server import mcp
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

mcp_app = mcp.http_app(path="/")

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=mcp_app.lifespan,
)

app.include_router(execute.router)
app.include_router(sessions.router)
app.include_router(workspace.router)
app.mount("/mcp/", mcp_app)


@app.api_route("/mcp", methods=["GET", "POST", "OPTIONS"])
def mcp_redirect_to_slash(request: Request):
    """Redirect /mcp to /mcp/ so MCP clients that omit the trailing slash still connect."""
    return RedirectResponse(url="/mcp/", status_code=307)


@app.get("/health")
def health():
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness probe (can later check Redis/Docker)."""
    return {"status": "ready"}
