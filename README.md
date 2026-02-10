# Isolated Command Execution API

FastAPI-based API that runs user commands in ephemeral, isolated Docker containers. Each session gets a dedicated container; containers are reused within a session TTL and torn down by a cleanup worker.

## Architecture

- **API (FastAPI)**: Auth (JWT or API key), rate limiting, command whitelist, session/container orchestration.
- **Redis**: Session and container-id mapping with TTL; rate-limit counters.
- **Orchestrator**: Get-or-create container per session with strict security and resource limits; exec with timeout.
- **Cleanup worker**: Periodically removes containers older than the configured max age and deletes Redis keys.

Execution containers use:

- Read-only root filesystem, tmpfs for `/tmp` and `/workspace`
- No network, no new privileges, all capabilities dropped
- Non-root user (UID 1000), resource limits (memory, CPU, pids, ulimits)

## Quick start

### With Docker Compose

1. Copy env example and set at least one auth method:

   ```bash
   cp .env.example .env
   # Set JWT_SECRET and/or API_KEYS (comma-separated). Example for local testing:
   # API_KEYS=dev-key
   ```

2. Start stack:

   ```bash
   docker compose up --build
   ```

3. Call the API (example with API key):

   ```bash
   curl -X POST http://localhost:8000/execute \
     -H "X-API-Key: dev-key" \
     -H "Content-Type: application/json" \
     -d '{"command": "ls -la", "session_id": "my-session-1", "timeout": 30}'
   ```

### Local development (no Docker for API)

- Install: `pip install -e .`
- Run Redis (e.g. `docker run -p 6379:6379 redis:7-alpine`) and ensure Docker daemon is available.
- Run API: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- Run cleanup worker in another terminal: `python -m app.workers.cleanup`

Set env vars as needed (e.g. `REDIS_HOST=localhost`, `API_KEYS=dev-key`).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `JWT_SECRET` | `change-me-in-production` | Secret for JWT verification |
| `API_KEYS` | (empty) | Comma-separated API keys (e.g. `key1,key2`) |
| `RATE_LIMIT_REQUESTS` | `100` | Max requests per user per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window in seconds |
| `SESSION_TTL_SECONDS` | `600` | Session (and container) TTL; refreshed on each execute |
| `CONTAINER_IMAGE` | `alpine:latest` | Base image for execution containers |
| `CONTAINER_MEM_LIMIT` | `256m` | Memory limit per container |
| `DEFAULT_EXEC_TIMEOUT_SECONDS` | `30` | Default command timeout |
| `ALLOWED_COMMANDS` | `ls,cat,echo,pwd,id,whoami,sh` | Whitelist of allowed command binaries |
| `CLEANUP_INTERVAL_SECONDS` | `60` | How often cleanup runs |
| `CLEANUP_MAX_CONTAINER_AGE_SECONDS` | `900` | Remove containers older than this |
| `WORKSPACE_MAX_FILE_SIZE_BYTES` | `1048576` (1 MiB) | Max size for workspace read/write; `0` = no limit |

See `.env.example` for the full list.

## API

- **POST /execute** — Execute a command in the session’s container. Body: `command`, `session_id`, optional `timeout`, `working_dir`. Requires auth (Bearer JWT or `X-API-Key`).
- **POST /sessions** — Create a session (body: `{"session_id": "..."}`). Idempotent.
- **DELETE /sessions/{session_id}** — Tear down session and container.
- **GET /health** — Liveness.
- **GET /ready** — Readiness.

### Workspace (agent file tools)

All paths are relative to the session container’s `/workspace`. Path traversal (`..`) is rejected. Same auth and rate limiting as the rest of the API.

| Method | Endpoint | Query | Description |
|--------|----------|-------|-------------|
| GET | `/sessions/{session_id}/workspace` | `path` (optional) | List directory entries. Returns `{"entries": [{"name", "type": "file" or "dir"}]}`. |
| GET | `/sessions/{session_id}/workspace/content` | `path` (required) | Read file. Returns `{"content": "...", "encoding": "utf8"\|"base64"}`. |
| PUT | `/sessions/{session_id}/workspace/content` | `path` (required) | Write file. Body: raw bytes or JSON `{"content": "..."}`. Creates parent dirs. |
| DELETE | `/sessions/{session_id}/workspace` | `path` (required) | Delete file or directory. |

## MCP server

The same app exposes an **MCP (Model Context Protocol) server** at **`http://localhost:8000/mcp`**, so LLM clients (e.g. Cursor, Claude Code) can use the sandbox as tools.

- **URL**: `http://localhost:8000/mcp` (when running the API on port 8000).
- **Tools**: `create_session`, `delete_session`, `execute`, `workspace_list`, `workspace_read`, `workspace_write`, `workspace_delete` — same capabilities as the REST API, with session-scoped parameters.
- **Auth**: Send the same credentials as the REST API on each request: **`X-API-Key`** header or **`Authorization: Bearer <JWT>`**. The MCP server resolves the user from these headers and applies the same rate limits and session ownership rules.

### Cursor

To use the sandbox MCP server in Cursor, add an entry to your MCP config (e.g. **Cursor Settings → MCP** or `~/.cursor/mcp.json`) so the client points at your running API:

```json
{
  "mcpServers": {
    "sandbox": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "X-API-Key": "your-api-key"
      }
    }
  }
}
```

Replace `your-api-key` with a key from your `API_KEYS` env (or use `Authorization: Bearer <token>` with a JWT). Ensure the API is running (e.g. `uvicorn app.main:app --host 0.0.0.0 --port 8000`) before connecting.

## Security notes

1. **Auth**: Use strong `JWT_SECRET` or `API_KEYS` in production; never rely on defaults.
2. **Command whitelist**: Only commands whose first token is in `ALLOWED_COMMANDS` are allowed. Adjust for your use case.
3. **Docker socket**: Mounted only in the API and cleanup containers; never in execution containers.
4. **Execution containers**: Isolated with read-only root, tmpfs, no network, non-root, and resource limits. Do not relax these without review.
5. **Rate limiting**: Applied per user to reduce abuse and DoS.
6. **Audit**: All execute requests are logged (user_id, session_id, command, exit_code, execution_time) via structlog.

## License

MIT.
