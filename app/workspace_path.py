"""Path validation for workspace: resolve and restrict to /workspace."""

from fastapi import HTTPException, status


def resolve_workspace_path(path: str) -> str:
    """
    Normalize path and ensure it stays under workspace.
    - Strip whitespace, remove leading slash.
    - Resolve .. and . (no escape outside workspace).
    - Return path relative to workspace (e.g. "foo/bar").
    Raises HTTPException 400 if path escapes workspace.
    """
    if path is None:
        path = ""
    p = path.strip().lstrip("/")
    if not p:
        return ""
    parts = p.split("/")
    resolved: list[str] = []
    for part in parts:
        if part == "." or part == "":
            continue
        if part == "..":
            if resolved:
                resolved.pop()
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Path escapes workspace",
                )
        else:
            resolved.append(part)
    return "/".join(resolved)


def container_path(path: str) -> str:
    """
    Return the absolute path inside the container for the given workspace-relative path.
    Assumes path is already resolved (e.g. from resolve_workspace_path).
    """
    if not path:
        return "/workspace"
    return "/workspace/" + path
