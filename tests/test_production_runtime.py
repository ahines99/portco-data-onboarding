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


# --------------------------------------------------------------------------- bounded readiness (audit DEL-02)


def test_readiness_query_runs_under_transaction_local_deadlines_within_the_probe_budget(tmp_path, monkeypatch):
    import src.readiness as readiness

    service = make_service(tmp_path)
    calls = []
    real = readiness.set_session_deadlines

    def record(conn, **kwargs):
        calls.append((conn.dialect.name, kwargs))
        real(conn, **kwargs)

    monkeypatch.setattr(readiness, "set_session_deadlines", record)
    assert check_ready(service)
    assert calls == [
        ("sqlite", {"statement_ms": readiness._QUERY_BUDGET_MS, "lock_ms": readiness._QUERY_BUDGET_MS, "local": True})
    ]
    assert readiness._QUERY_BUDGET_MS / 1000 < readiness.READINESS_BUDGET_S <= 5


def test_postgres_readiness_uses_its_own_unpooled_budgeted_engine(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    import src.readiness as readiness

    created = []

    def probe_engine(url, *, connect_timeout_s):
        created.append((url, connect_timeout_s))
        return create_engine(url, poolclass=NullPool)

    monkeypatch.setattr(readiness, "make_probe_engine", probe_engine)
    monkeypatch.setattr(readiness, "_probe_engines", {})
    app_engine = create_engine("postgresql+psycopg://u:p%40w@db.invalid/app")
    service = SimpleNamespace(store=SimpleNamespace(engine=app_engine))
    first = readiness._probe_engine(service)
    assert first is not app_engine and isinstance(first.pool, NullPool)
    assert readiness._probe_engine(service) is first  # built once, reused by later probes
    assert created == [("postgresql+psycopg://u:p%40w@db.invalid/app", readiness._CONNECT_BUDGET_S)]

    from src.adapters.db import make_probe_engine

    engine = make_probe_engine("postgresql+psycopg://u:p@db.invalid/app", connect_timeout_s=3)
    assert isinstance(engine.pool, NullPool)  # nothing to queue behind; the connect timeout bounds each attempt
    assert engine.pool._creator is not None


def test_concurrent_readiness_probes_never_pile_up(tmp_path, monkeypatch):
    import threading

    import src.readiness as readiness

    service = make_service(tmp_path)
    entered, release = threading.Event(), threading.Event()
    calls = []
    real = readiness._schema_current

    def slow_schema(svc):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        return real(svc)

    monkeypatch.setattr(readiness, "_last", None)
    monkeypatch.setattr(readiness, "_schema_current", slow_schema)
    results = []
    first = threading.Thread(target=lambda: results.append(check_ready(service)))
    first.start()
    assert entered.wait(10)
    # No completed answer yet: concurrent probes report "unavailable" at once instead of queueing more work.
    assert [check_ready(service) for _ in range(5)] == [False] * 5
    release.set()
    first.join(10)
    assert results == [True] and len(calls) == 1

    entered.clear()
    release.clear()
    second = threading.Thread(target=lambda: results.append(check_ready(service)))
    second.start()
    assert entered.wait(10)
    assert check_ready(service) is True  # the last answer is fresh (inside the budget): reuse it
    other = make_service(tmp_path / "other")
    assert check_ready(other) is False  # but never another service's answer
    release.set()
    second.join(10)
    assert len(calls) == 2
    assert check_ready(service)  # sequential probes always re-check (no stale cache)
    assert len(calls) == 3


@pytest.mark.postgres
@pytest.mark.skipif(
    not __import__("os").environ.get("PORTCO_TEST_POSTGRES_URL"), reason="PORTCO_TEST_POSTGRES_URL not set"
)
def test_postgres_readiness_fails_fast_behind_an_exclusive_schema_lock(tmp_path):
    import os
    import time

    from sqlalchemy import create_engine

    from scripts.postgres_test_db import disposable_database
    from src.readiness import READINESS_BUDGET_S
    from src.workflows.facade import migrate

    allow = os.environ.get("PORTCO_TEST_POSTGRES_ALLOW_CREATE") == "1"
    with disposable_database(os.environ["PORTCO_TEST_POSTGRES_URL"], allow_create=allow) as url:
        migrate(url)
        service = make_service(tmp_path, database_url=url)
        assert check_ready(service)
        holder = create_engine(url)
        try:
            with holder.connect() as conn, conn.begin():
                conn.execute(text("LOCK TABLE alembic_version IN ACCESS EXCLUSIVE MODE"))
                checked_out = service.store.engine.pool.checkedout()
                start = time.monotonic()
                assert not check_ready(service)
                assert time.monotonic() - start < READINESS_BUDGET_S + 1
                assert service.store.engine.pool.checkedout() == checked_out  # the app pool is untouched
            assert check_ready(service)  # recovers once the lock is released, without a restart
        finally:
            holder.dispose()
            service.store.engine.dispose()
