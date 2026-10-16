"""The real Alembic CLI against percent-containing URLs, and bounded migration sessions (audit A17/DEL-01, DEL-02).

Every case runs `python -m alembic` as a child process, exactly like `poe migrate` and the Compose migration
command, so the `migrations/env.py` configuration boundary is what is under test.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from src.adapters import db
from src.settings import PROJECT_ROOT

PASSWORD = "Sentinel-pw@42%x"  # decoded form of the encoded password below
ENCODED_PASSWORD = "Sentinel-pw%4042%25x"


def alembic(*args: str, url: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PORTCO_DATABASE_URL": url, "PORTCO_ENV": "test"}
    env.pop("DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def head() -> str:
    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    (revision,) = ScriptDirectory.from_config(config).get_heads()
    return revision


def test_alembic_cli_upgrades_a_sqlite_path_containing_percent(tmp_path: Path) -> None:
    folder = tmp_path / "state%encoded"
    folder.mkdir()
    url = f"sqlite:///{(folder / 'portco%25.db').as_posix()}"
    upgrade = alembic("upgrade", "head", url=url)
    assert upgrade.returncode == 0, upgrade.stderr
    current = alembic("current", url=url)
    assert current.returncode == 0, current.stderr
    assert f"{head()} (head)" in current.stdout
    assert [p.name for p in folder.iterdir() if p.suffix == ".db"] == ["portco%25.db"]


def test_alembic_cli_offline_postgres_sql_with_encoded_password_never_echoes_it() -> None:
    url = f"postgresql+psycopg://svc_user:{ENCODED_PASSWORD}@db.internal.invalid:5432/app"
    result = alembic("upgrade", "head", "--sql", url=url)
    output = result.stdout + result.stderr
    assert ENCODED_PASSWORD not in output and PASSWORD not in output
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE workflow_runs" in result.stdout and "alembic_version" in result.stdout


@pytest.mark.slow
def test_alembic_cli_connection_failure_is_bounded_and_credential_free() -> None:
    # Port 1 on loopback: refused (or, on Windows, retried until the migration connect timeout).
    url = f"postgresql+psycopg://svc_user:{ENCODED_PASSWORD}@127.0.0.1:1/app?sslmode=disable"
    result = alembic("current", url=url, timeout=db.MIGRATION_CONNECT_TIMEOUT_S * 4)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert ENCODED_PASSWORD not in output and PASSWORD not in output


def test_redact_db_error_removes_encoded_and_decoded_password_from_the_whole_chain() -> None:
    url = f"postgresql+psycopg://svc_user:{ENCODED_PASSWORD}@db.internal.invalid/app"
    try:
        try:
            raise ValueError(f"could not parse {url}")
        except ValueError as cause:
            raise RuntimeError(f"login failed for password {PASSWORD}") from cause
    except RuntimeError as exc:
        message = db.redact_db_error(exc, url)
    assert message is not None
    assert PASSWORD not in message and ENCODED_PASSWORD not in message
    assert message.startswith("RuntimeError while migrating postgresql+psycopg://svc_user:***@db.internal.invalid/app")
    assert db.redact_db_error(RuntimeError("relation missing"), url) is None  # nothing secret: keep the original


def test_alembic_url_escaping_is_shared() -> None:
    assert db.escape_alembic_url("sqlite:///a%b/c%25.db") == "sqlite:///a%%b/c%%25.db"
    config = Config()
    config.set_main_option("sqlalchemy.url", db.escape_alembic_url(f"postgresql://u:{ENCODED_PASSWORD}@h/d"))
    assert config.get_main_option("sqlalchemy.url") == f"postgresql://u:{ENCODED_PASSWORD}@h/d"


# --------------------------------------------------------------------------- migration-session deadlines (DEL-02)


def test_migration_connections_have_explicit_deadlines() -> None:
    assert db.migration_connect_args("postgresql+psycopg://u:p@h/d") == {
        "connect_timeout": db.MIGRATION_CONNECT_TIMEOUT_S
    }
    assert db.migration_connect_args("sqlite:///x.db") == {"timeout": db.MIGRATION_LOCK_TIMEOUT_MS / 1000}
    assert 0 < db.MIGRATION_LOCK_TIMEOUT_MS <= 60_000 and db.MIGRATION_STATEMENT_TIMEOUT_MS > 0


def _fake_connection(dialect: str) -> tuple[Any, list[str]]:
    executed: list[str] = []
    return SimpleNamespace(dialect=SimpleNamespace(name=dialect), exec_driver_sql=executed.append), executed


def test_session_deadlines_are_session_or_transaction_scoped_and_postgres_only() -> None:
    conn, executed = _fake_connection("postgresql")
    db.set_session_deadlines(conn, statement_ms=300_000, lock_ms=15_000)
    assert executed == ["SET lock_timeout = 15000", "SET statement_timeout = 300000"]
    conn, executed = _fake_connection("postgresql")
    db.set_session_deadlines(conn, statement_ms=2_000, lock_ms=2_000, local=True)
    assert executed == ["SET LOCAL lock_timeout = 2000", "SET LOCAL statement_timeout = 2000"]
    conn, executed = _fake_connection("sqlite")
    db.set_session_deadlines(conn, statement_ms=1, lock_ms=1)
    assert executed == []


def test_application_engine_timeouts_are_unchanged(tmp_path: Path) -> None:
    """Deadlines belong to the migration/readiness sessions, not to every application client."""
    engine = db.make_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30_000
    finally:
        engine.dispose()
