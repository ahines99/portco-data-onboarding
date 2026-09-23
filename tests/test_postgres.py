"""PostgreSQL reference store (POD-201, 203, 205). Runs only when PORTCO_TEST_POSTGRES_URL is set (CI service)."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from src.adapters.artifact_store import ArtifactStore
from src.adapters.db import make_engine, metadata
from src.adapters.repositories import Store
from src.domain.models import AuditEvent, RunStatus
from src.workflows.facade import migrate
from tests.conftest import AGENT, make_service

URL = os.environ.get("PORTCO_TEST_POSTGRES_URL")
pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not URL, reason="PORTCO_TEST_POSTGRES_URL not set")]


@pytest.fixture(scope="module")
def pg_url() -> str:
    assert URL
    engine = create_engine(URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    migrate(URL)
    return URL


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
async def test_full_gate_a_run_on_postgres(pg_url: str, tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path, database_url=pg_url)
    run = await svc.start_run(AGENT, "fixture:portco_a")
    assert run.status is RunStatus.NEEDS_REVIEW and run.gate == "mapping_review"
    events, ok = svc.audit(AGENT, run.run_id)
    assert ok and events
    assert svc.get_run(AGENT, run.run_id).run_id == run.run_id
    assert uuid4() != run.run_id
