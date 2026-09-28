"""Runtime configuration. Every value can be overridden with a `PORTCO_`-prefixed env var."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from src.paths import RESOURCE_ROOT, default_var_root

PROJECT_ROOT = RESOURCE_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PORTCO_", env_file=".env", extra="ignore", hide_input_in_errors=True)

    env: Literal["dev", "test", "production"] = "dev"
    var_root: Path = Field(default_factory=default_var_root)
    fixtures_root: Path | None = None  # defaults to <var_root>/fixtures
    database_url: str = Field(default="", repr=False)
    log_level: str = "INFO"

    # Retry / timeout policy (POD-405)
    step_max_attempts: int = 3
    step_backoff_base_seconds: float = 0.2
    step_timeout_seconds: float = 900.0  # must outlast the dbt build inside the test step
    lease_margin_seconds: float = 60.0

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
    auth_mode: Literal["static", "jwt"] = "static"
    jwt_issuer_url: str = ""
    jwt_jwks_url: str = ""
    jwt_audience: str = ""
    jwt_role_claim: str = "portco_role"
    jwt_companies_claim: str = "portco_companies"
    jwt_max_lifetime_seconds: int = Field(default=3600, ge=60, le=86400)
    jwt_clock_skew_seconds: int = Field(default=15, ge=0, le=60)

    # Fault injection (POD-406), e.g. "adapter.aggregate:timeout:nth=3"
    faults: str = ""

    otel_console: bool = False
    fiscal_year_start_month: int = Field(default=2, ge=1, le=12)

    @model_validator(mode="after")
    def _timeouts_nest(self) -> Settings:
        # A step timeout shorter than dbt's would abandon a still-running build (and its sandbox).
        if self.step_timeout_seconds <= self.dbt_timeout_seconds + 60:
            raise ValueError("step_timeout_seconds must exceed dbt_timeout_seconds + 60")
        return self

    @model_validator(mode="after")
    def _authentication_policy(self) -> Settings:
        if self.auth_mode == "jwt":
            for name in ("jwt_issuer_url", "jwt_jwks_url", "http_base_url"):
                parsed = urlsplit(getattr(self, name))
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                ):
                    raise ValueError(f"{name} must be an HTTPS URL without credentials, query or fragment")
            if not self.jwt_audience.strip() or not self.jwt_role_claim.strip() or not self.jwt_companies_claim.strip():
                raise ValueError("JWT audience and authorization claim names are required")
            if self.http_tokens is not None:
                raise ValueError("JWT mode does not permit static HTTP tokens")
        if self.env == "production":
            if self.auth_mode != "jwt":
                raise ValueError("production requires JWT authentication")
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("production requires an explicit PostgreSQL psycopg database URL")
            if make_url(self.database_url).query.get("sslmode") not in ("require", "verify-ca", "verify-full"):
                raise ValueError("production database connections require TLS (sslmode=require or verified TLS)")
            if not self.var_root.is_absolute():
                raise ValueError("production requires an absolute persistent var_root")
            if not self.require_distinct_reviewer or self.faults:
                raise ValueError("production requires distinct reviewers and forbids fault injection")
        return self

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
        return self.var_root / "llm_cassettes"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
