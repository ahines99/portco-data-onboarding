"""PostgreSQL reference store (POD-201, 203, 205). Runs only when PORTCO_TEST_POSTGRES_URL is set (CI service)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from scripts.postgres_test_db import disposable_database
from src.adapters.artifact_store import ArtifactStore
from src.adapters.db import make_engine, metadata
from src.adapters.repositories import Store
from src.domain.models import AuditEvent, RunStatus
from src.workflows.facade import migrate
from tests.conftest import AGENT, drive, make_service

URL = os.environ.get("PORTCO_TEST_POSTGRES_URL")
pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not URL, reason="PORTCO_TEST_POSTGRES_URL not set")]


@pytest.fixture(scope="module")
def pg_url() -> Iterator[str]:
    assert URL
    with disposable_database(URL, allow_create=os.environ.get("PORTCO_TEST_POSTGRES_ALLOW_CREATE") == "1") as url:
        migrate(url)
        yield url


def test_migration_matches_metadata_on_postgres(pg_url: str) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with create_engine(pg_url).connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), metadata) == []


def test_audit_log_is_append_only_in_the_database(pg_url: str, tmp_path: Path) -> None:
    store = Store(make_engine(pg_url), ArtifactStore(tmp_path))
    with store.tx() as tx:
        run = tx.runs.create(company_id="c", connection_id="fixture:x", requested_by="a")
        tx.audit.append(AuditEvent(run_id=run.run_id, step="s", event_type="e", actor="a"))
    for sql in ("UPDATE audit_events SET actor = 'mallory'", "DELETE FROM audit_events"):
        with pytest.raises(DBAPIError, match="append-only"), store.engine.begin() as conn:
            conn.execute(text(sql))


@pytest.mark.anyio
async def test_full_certified_publication_on_postgres(pg_url: str, tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path, database_url=pg_url)
    run = await drive(svc)
    assert run.status is RunStatus.COMPLETE
    events, ok = svc.audit(AGENT, run.run_id)
    assert ok and events
    assert svc.get_run(AGENT, run.run_id).run_id == run.run_id
    assert uuid4() != run.run_id


def test_concurrent_audit_and_publication_recovery_on_postgres(pg_url: str, tmp_path: Path, monkeypatch) -> None:
    from tests.test_publication_recovery import (
        test_concurrent_audit_appends_do_not_fork_sqlite_chain,
        test_concurrent_publication_finalizers_share_one_verified_receipt,
        test_crash_after_rename_before_db_commit_recovers,
        test_rename_failure_is_recovered_using_same_version,
    )

    svc = make_service(tmp_path, database_url=pg_url)
    test_concurrent_audit_appends_do_not_fork_sqlite_chain(svc)
    test_concurrent_publication_finalizers_share_one_verified_receipt(svc)
    test_crash_after_rename_before_db_commit_recovers(svc, monkeypatch)
    test_rename_failure_is_recovered_using_same_version(svc, monkeypatch)
