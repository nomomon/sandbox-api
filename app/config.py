"""Environment-based configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API
    app_name: str = "Isolated Command Execution API"
    debug: bool = False

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    api_key_header: str = "X-API-Key"
    api_keys: str = ""  # Comma-separated list of valid API keys (optional)

    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60

    # Session
    session_ttl_seconds: int = 600

    # Container execution (default: Python image for agent/MCP use)
    container_image: str = "python:3.12-slim"
    container_mem_limit: str = "256m"
    container_memswap_limit: str = "256m"
    container_cpu_period: int = 100_000
    container_cpu_quota: int = 50_000
    container_pids_limit: int = 50
    container_tmpfs_tmp_size: str = "100m"
    container_tmpfs_workspace_size: str = "500m"
    container_ulimit_nofile_soft: int = 64
    container_ulimit_nofile_hard: int = 128
    container_ulimit_nproc_soft: int = 50
    container_ulimit_nproc_hard: int = 100
    default_exec_timeout_seconds: int = 30
    max_exec_timeout_seconds: int = 120

    # Cleanup worker
    cleanup_interval_seconds: int = 60
    cleanup_max_container_age_seconds: int = 900  # 15 minutes

    # Command whitelist (comma-separated binaries for agent/sandbox use)
    allowed_commands: str = (
        "ls,cat,echo,pwd,id,whoami,sh,bash,"
        "python,python3,pip,pip3,"
        "git,curl,wget,"
        "mkdir,cp,mv,rm,grep,find,head,tail,sort,uniq,xargs,env,basename,dirname,"
        "test,diff,patch,tar"
    )

    # Workspace file tools (agent): max size per read/write in bytes; 0 = no limit
    workspace_max_file_size_bytes: int = 1 << 20  # 1 MiB

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def allowed_commands_set(self) -> set[str]:
        return {c.strip().lower() for c in self.allowed_commands.split(",") if c.strip()}


settings = Settings()
