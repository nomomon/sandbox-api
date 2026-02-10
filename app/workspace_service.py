"""Workspace file operations: read, write, list, delete using container get_archive/put_archive/exec."""

import base64
from typing import Any

from fastapi import HTTPException, status

from app.workspace_path import container_path


def workspace_read(container: Any, resolved_path: str, max_size: int = 0) -> dict[str, Any]:
    """
    Read file at resolved_path (relative to workspace). Returns dict with "content" (str),
    "encoding" ("utf8" or "base64"). Raises 404 if path missing, 400 if too large or directory.
    Uses exec (cat) because get_archive can fail on read-only container filesystems.
    """
    cpath = container_path(resolved_path)
    # Use cat via exec so read works on read-only root + tmpfs
    r = container.exec_run(["cat", cpath], workdir="/workspace")
    if r.exit_code != 0:
        err = (r.output or b"").decode("utf-8", errors="replace")
        if "No such file" in err or "not found" in err.lower() or "cannot open" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Path not found")
        if "directory" in err.lower() or "is a directory" in err.lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path is a directory")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err or "Read failed")
    data = r.output or b""
    if max_size > 0 and len(data) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds max size ({max_size} bytes)",
        )
    try:
        text = data.decode("utf-8")
        return {"content": text, "encoding": "utf8"}
    except UnicodeDecodeError:
        return {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"}


# Chunk size for base64 write (stay under typical exec arg limits)
_WRITE_CHUNK_RAW = 24 * 1024  # 24 KiB raw -> ~32 KiB base64


def workspace_write(
    container: Any,
    resolved_path: str,
    content: bytes,
    max_size: int = 0,
) -> None:
    """
    Write content to file at resolved_path. Creates parent dirs. Raises 400 if too large.
    Uses exec (base64) because put_archive fails on read-only container rootfs.
    """
    if max_size > 0 and len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Content exceeds max size ({max_size} bytes)",
        )

    cpath = container_path(resolved_path)
    parent = "/workspace/" + "/".join(resolved_path.split("/")[:-1]) if "/" in resolved_path else "/workspace"
    try:
        if "/" in resolved_path:
            r = container.exec_run(["mkdir", "-p", parent], workdir="/workspace")
            if r.exit_code != 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=r.output or "mkdir failed")
        if not content:
            container.exec_run(["touch", cpath], workdir="/workspace")
            return
        # Chunk raw content so each base64 chunk fits in exec arg limit (~32KB b64)
        raw_chunks = [content[i : i + _WRITE_CHUNK_RAW] for i in range(0, len(content), _WRITE_CHUNK_RAW)]
        for i, raw in enumerate(raw_chunks):
            b64 = base64.b64encode(raw).decode("ascii")
            redir = ">" if i == 0 else ">>"
            cmd = f"echo '{b64}' | base64 -d {redir} '{cpath}'"
            r = container.exec_run(["sh", "-c", cmd], workdir="/workspace")
            if r.exit_code != 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=(r.output or b"").decode(errors="replace"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


def workspace_list(container: Any, resolved_path: str) -> list[dict[str, str]]:
    """
    List entries (files and dirs) at resolved_path. Returns list of {"name": str, "type": "file"|"dir"}.
    Uses exec (ls) so list works on read-only container filesystems.
    """
    cpath = container_path(resolved_path) if resolved_path else "/workspace"
    # ls -1p: one per line, append / for dirs
    r = container.exec_run(["ls", "-1p", cpath], workdir="/workspace")
    if r.exit_code != 0:
        err = (r.output or b"").decode("utf-8", errors="replace")
        if "No such file" in err or "not found" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Path not found")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err or "List failed")
    out = (r.output or b"").decode("utf-8", errors="replace")
    entries: list[dict[str, str]] = []
    for line in out.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.endswith("/"):
            entries.append({"name": line[:-1], "type": "dir"})
        else:
            entries.append({"name": line, "type": "file"})
    return sorted(entries, key=lambda e: (e["name"].lower(), e["type"]))


def workspace_delete(container: Any, resolved_path: str) -> None:
    """
    Delete file or directory at resolved_path. Raises 404 if path does not exist.
    """
    cpath = container_path(resolved_path)
    if not cpath or cpath == "/workspace":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete workspace root")

    result = container.exec_run(["rm", "-rf", cpath], workdir="/workspace")
    if result.exit_code != 0:
        err = (result.output or b"").decode("utf-8", errors="replace") if result.output else ""
        if "No such file" in err or "not found" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Path not found")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err or "Delete failed")
