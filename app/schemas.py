"""Pydantic request/response models for the API."""

from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    """Request body for POST /execute."""

    command: str = Field(..., min_length=1, max_length=32_000)
    session_id: str = Field(..., min_length=1, max_length=256)
    timeout: int = Field(default=30, ge=1, le=120, description="Execution timeout in seconds")
    working_dir: str = Field(default="/workspace", max_length=512)


class CommandResponse(BaseModel):
    """Response for POST /execute."""

    stdout: str
    stderr: str
    exit_code: int
    execution_time: float
    container_id: str
