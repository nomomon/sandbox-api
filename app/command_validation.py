"""Command whitelist validation: only allow configured binaries/commands."""

import shlex
from typing import NoReturn

from fastapi import HTTPException, status

from app.config import settings


def is_command_allowed(command: str) -> bool:
    """
    Check if command is allowed by whitelist. We parse the first token (binary name)
    and allow only if it's in allowed_commands_set. Rejects empty and dangerous patterns.
    """
    stripped = command.strip()
    if not stripped:
        return False
    parts = shlex.split(stripped, posix=True)
    if not parts:
        return False
    binary = parts[0].lower()
    if "/" in binary:
        binary = binary.split("/")[-1]
    return binary in settings.allowed_commands_set


def ensure_command_allowed(command: str) -> None:
    """Raise HTTP 400 if command is not allowed."""
    if not is_command_allowed(command):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Command not allowed by whitelist",
        )
