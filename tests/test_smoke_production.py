"""Local coverage for the production entry-point smoke (audit DEL-04).

The complete smoke boots `python -m src.serve` and needs a TLS PostgreSQL, so it runs in CI. These
tests run its building blocks locally: the environment is a valid production profile for the real
entry point, and a real HTTP server with JWT authentication against the generated HTTPS JWKS
passes every HTTP/MCP check the smoke makes.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from sqlalchemy.engine import make_url

from scripts import smoke_production as smoke
from src.mcp_server import build_http_app
from src.serve import prepare_environment
from src.settings import Settings
from tests.conftest import FIXTURES

pytestmark = pytest.mark.security


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((smoke.LOOPBACK, 0))
        return int(s.getsockname()[1])


def test_server_environment_is_a_valid_production_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inherited = {
        "PATH": "/usr/bin",
        "PORTCO_ENV": "test",
        "PORTCO_FAULTS": "adapter.probe:unavailable",
        "PORTCO_HTTP_TOKENS": "static=agent:agent:portco_a",
        "PORTCO_DATABASE_URL": "sqlite:///elsewhere.db",
        "DATABASE_URL": "postgresql://other",
        "PORT": "8000",
    }
    env = smoke.server_environment(
        database_url="postgresql://portco:p%40ss@127.0.0.1:5433/portco",
        var_root=tmp_path / "data",
        port=18080,
        issuer="https://127.0.0.1:9443/",
        jwks_url="https://127.0.0.1:9443/.well-known/jwks.json",
        ca_file=tmp_path / "ca.pem",
        base_env=inherited,
    )
    assert env["PATH"] == "/usr/bin" and env["PORT"] == "18080"
    assert "PORTCO_FAULTS" not in env and "PORTCO_HTTP_TOKENS" not in env and "PORTCO_DATABASE_URL" not in env
    assert env["DATABASE_URL"] == "postgresql://portco:p%40ss@127.0.0.1:5433/portco"

    # The real entry point's preparation accepts exactly this environment as production.
    for key in [k for k in os.environ if k.startswith("PORTCO_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("PORTCO_DATABASE_URL", "")  # registers an undo; startup writes the variable
    for key, value in env.items():
        if key != "PATH":
            monkeypatch.setenv(key, value)
    settings = prepare_environment()
    url = make_url(settings.db_url)
    assert settings.env == "production" and settings.auth_mode == "jwt" and not settings.faults
    assert url.drivername == "postgresql+psycopg" and url.query["sslmode"] == "require" and url.password == "p@ss"
    assert settings.http_base_url == "https://127.0.0.1:18080" and settings.jwt_audience == smoke.AUDIENCE
    assert smoke.normalized_database_url(env["DATABASE_URL"]) == url


def test_smoke_cli_requires_a_database_and_a_non_default_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORTCO_PRODUCTION_SMOKE_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        smoke.main([])
    with pytest.raises(SystemExit):
        smoke.main(["--database-url", "postgresql://x@127.0.0.1/db", "--port", "8000"])


@pytest.mark.anyio
async def test_jwks_endpoint_is_trusted_only_through_the_generated_ca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.capabilities.jwt_auth import JwtTokenVerifier

    signing = smoke.new_rsa_key()
    ca_pem, cert_pem, key_pem = smoke.loopback_tls_material()
    (tmp_path / "ca.pem").write_bytes(ca_pem)
    with smoke.JwksServer([smoke.public_jwk(signing, "k1")], cert_pem, key_pem) as jwks:
        settings = Settings(
            _env_file=None,
            env="test",
            var_root=tmp_path,
            auth_mode="jwt",
            jwt_issuer_url=jwks.issuer,
            jwt_jwks_url=jwks.jwks_url,
            jwt_audience=smoke.AUDIENCE,
            http_base_url="https://127.0.0.1:18080",
        )
        tokens = smoke.tokens_for(jwks.issuer, signing, "k1")
        # Without the CA the HTTPS fetch fails certificate verification and every token is refused.
        monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing-ca.pem"))
        assert await JwtTokenVerifier(settings).verify_token(tokens.agent) is None
        monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "ca.pem"))
        verifier = JwtTokenVerifier(settings)
        accepted = await verifier.verify_token(tokens.agent)
        assert accepted is not None and accepted.scopes == ["role:agent", "company:portco_a"]
        assert await verifier.verify_token(tokens.wrong_audience) is None
        assert await verifier.verify_token(tokens.untrusted_key) is None
        assert jwks.requests >= 1


@pytest.mark.integration
def test_production_http_checks_pass_against_a_real_jwt_server(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every HTTP/MCP assertion of the smoke, against uvicorn with JWT auth (SQLite instead of PostgreSQL)."""
    signing = smoke.new_rsa_key()
    ca_pem, cert_pem, key_pem = smoke.loopback_tls_material()
    (tmp_path / "ca.pem").write_bytes(ca_pem)
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "ca.pem"))
    port = _free_port()
    base = f"http://{smoke.LOOPBACK}:{port}"
    with smoke.JwksServer([smoke.public_jwk(signing, "k1")], cert_pem, key_pem) as jwks:
        settings = Settings(
            _env_file=None,
            env="test",
            var_root=tmp_path / "data",
            fixtures_root=FIXTURES,
            auth_mode="jwt",
            jwt_issuer_url=jwks.issuer,
            jwt_jwks_url=jwks.jwks_url,
            jwt_audience=smoke.AUDIENCE,
            http_base_url=f"https://{smoke.LOOPBACK}:{port}",
            log_level="WARNING",
            step_backoff_base_seconds=0.0,
        )
        server = uvicorn.Server(
            uvicorn.Config(build_http_app(settings), host=smoke.LOOPBACK, port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 30
            while not server.started:
                assert time.monotonic() < deadline and thread.is_alive(), "uvicorn did not start"
                time.sleep(0.05)
            tokens = smoke.tokens_for(jwks.issuer, signing, "k1")
            observed = asyncio.run(smoke.exercise_http(base, tokens))
            assert smoke.assert_http(observed, base) == [], observed
            status = asyncio.run(smoke.run_status(base, tokens.agent, observed["run"]["run_id"]))
            assert (status["status"], status["gate"]) == ("needs_review", "mapping_review")
            assert jwks.requests >= 1
        finally:
            server.should_exit = True
            thread.join(timeout=30)
