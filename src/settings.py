"""Runtime configuration. Every value can be overridden with a `PORTCO_`-prefixed env var."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PORTCO_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "production"] = "dev"
    var_root: Path = PROJECT_ROOT / "var"
    fixtures_root: Path | None = None  # defaults to <var_root>/fixtures
    database_url: str = ""
    log_level: str = "INFO"

    # Retry / timeout policy (POD-405)
    step_max_attempts: int = 3
    step_backoff_base_seconds: float = 0.2
    step_timeout_seconds: float = 300.0

    # Sandbox (POD-308)
    sandbox_keep_attempts: int = 2
    dbt_timeout_seconds: float = 600.0

    # Approvals (POD-701)
    require_distinct_reviewer: bool = True
    approval_ttl_hours: int = 72

    # Model judgment layer (POD-607) — off by default; the deterministic core never needs it.
    llm_enabled: bool = False
    llm_model: str = "claude-opus-5"
    llm_mode: Literal["live", "replay", "record"] = "replay"
    anthropic_api_key: SecretStr | None = None

    # MCP identity for the stdio transport (POD-509). The agent principal cannot approve.
    local_principal_id: str = "agent:local"
    local_principal_role: Literal["agent", "reviewer", "admin"] = "agent"
    # HTTP bearer tokens for dev: "token=principal_id:role:company1|company2;..."
    http_tokens: SecretStr | None = None
    http_base_url: str = "http://localhost:8000"

    # Fault injection (POD-406), e.g. "adapter.aggregate:timeout:nth=3"
    faults: str = ""

    otel_console: bool = False
    fiscal_year_start_month: int = Field(default=2, ge=1, le=12)

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.var_root / 'portco.db').as_posix()}"

    @property
    def fixtures_dir(self) -> Path:
        return self.fixtures_root or self.var_root / "fixtures"

    @property
    def artifact_root(self) -> Path:
        return self.var_root / "artifacts"

    @property
    def sandbox_root(self) -> Path:
        return self.var_root / "sandbox"

    @property
    def published_root(self) -> Path:
        return self.var_root / "published"

    @property
    def llm_cassette_dir(self) -> Path:
        return PROJECT_ROOT / "evals" / "cassettes"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
