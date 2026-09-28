"""Deployment readiness and startup environment, without provisioning a cloud account."""

from types import SimpleNamespace

import httpx2
import pytest
from sqlalchemy import text

from src.mcp_server import build_http_app
from src.readiness import check_ready
from src.serve import prepare_environment
from tests.conftest import make_service, make_settings


def test_readiness_requires_current_schema_and_writable_disk(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    assert check_ready(service)
    with service.store.engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num='older'"))
    assert not check_ready(service)
    with service.store.engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num='0003'"))
    monkeypatch.setattr("src.readiness.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    assert not check_ready(service)


@pytest.mark.anyio
async def test_readiness_returns_503_and_no_private_diagnostics(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    app = build_http_app(make_settings(tmp_path, http_tokens="probe=agent:agent:portco_a"), service=service)

    def broken():
        raise RuntimeError("password-and-private-database-name")

    monkeypatch.setattr(service.store.engine, "connect", broken)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app), base_url="http://localhost:8000") as client,
    ):
        response = await client.get("/readyz")
        assert response.status_code == 503 and response.json() == {"status": "unavailable"}
        assert (await client.get("/healthz")).status_code == 200


def test_cloud_database_url_uses_psycopg_tls_and_preserves_escaped_password(tmp_path, monkeypatch):
    env = {
        "PORTCO_ENV": "production",
        "PORTCO_AUTH_MODE": "jwt",
        "PORTCO_VAR_ROOT": str(tmp_path),
        "PORTCO_HTTP_BASE_URL": "https://portco.example",
        "PORTCO_JWT_ISSUER_URL": "https://issuer.example/",
        "PORTCO_JWT_JWKS_URL": "https://issuer.example/jwks",
        "PORTCO_JWT_AUDIENCE": "portco-api",
        "DATABASE_URL": "postgresql://user:p%40ss%25word@database/app",
    }
    # Register an undo even when the variable was originally absent: startup mutates it.
    monkeypatch.setenv("PORTCO_DATABASE_URL", "")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings = prepare_environment()
    from sqlalchemy.engine import make_url

    url = make_url(settings.db_url)
    assert url.drivername == "postgresql+psycopg" and url.password == "p@ss%word"
    assert url.query["sslmode"] == "require"


def test_cloud_entry_point_rejects_development_mode(monkeypatch):
    monkeypatch.setenv("PORTCO_ENV", "test")
    with pytest.raises(RuntimeError, match="production"):
        prepare_environment()
