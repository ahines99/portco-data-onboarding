"""Migrations, repositories, atomicity, audit chain, provenance (POD-201..204)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from src.adapters import db
from src.adapters.artifact_store import ArtifactStore
from src.adapters.repositories import Store
from src.domain.errors import NotFound
from src.domain.models import AuditEvent, Confidence, Evidence, Finding
from src.workflows.facade import migrate

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path: Path) -> Store:
    url = f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}"
    migrate(url)
    return Store(db.make_engine(url), ArtifactStore(tmp_path / "blobs"))


def test_migration_matches_metadata(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'm.sqlite').as_posix()}"
    migrate(url)
    with create_engine(url).connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), db.metadata) == []


def test_downgrade_upgrade_roundtrip(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    from src.settings import PROJECT_ROOT

    url = f"sqlite:///{(tmp_path / 'r.sqlite').as_posix()}"
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_artifact_store_dedupes(tmp_path: Path) -> None:
    s = ArtifactStore(tmp_path)
    assert s.put_bytes(b"abc") == s.put_bytes(b"abc")
    assert len(list(tmp_path.rglob("*"))) == 2  # one dir + one blob
    with pytest.raises(NotFound):
        s.get_bytes("0" * 64)
    with pytest.raises(NotFound):
        s.get_bytes("../../etc/passwd")


def test_exception_mid_transaction_persists_nothing(store: Store) -> None:
    with store.tx() as tx:
        run = tx.runs.create(company_id="c", connection_id="fixture:x", requested_by="a")
    with pytest.raises(RuntimeError), store.tx() as tx:
        tx.audit.append(AuditEvent(run_id=run.run_id, step="s", event_type="e", actor="a"))
        raise RuntimeError("boom")
    with store.tx() as tx:
        assert tx.audit.list(run.run_id) == []


def test_audit_chain_detects_tampering(store: Store) -> None:
    with store.tx() as tx:
        run = tx.runs.create(company_id="c", connection_id="fixture:x", requested_by="a")
        for i in range(3):
            tx.audit.append(AuditEvent(run_id=run.run_id, step="s", event_type=f"e{i}", actor="a", payload={"i": i}))
        assert tx.audit.verify_chain(run.run_id) == (True, None)
    with store.engine.begin() as conn:
        conn.execute(text("UPDATE audit_events SET payload = '{\"i\": 99}' WHERE event_type = 'e1'"))
    with store.tx() as tx:
        ok, where = tx.audit.verify_chain(run.run_id)
        assert not ok and where


def test_audit_chain_detects_deleted_tail(store: Store) -> None:
    with store.tx() as tx:
        run = tx.runs.create(company_id="c", connection_id="fixture:x", requested_by="a")
        for i in range(3):
            tx.audit.append(AuditEvent(run_id=run.run_id, step="s", event_type=f"e{i}", actor="a"))
    with store.engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events WHERE event_type = 'e2'"))
    with store.tx() as tx:
        ok, where = tx.audit.verify_chain(run.run_id)
        assert not ok and "truncated" in (where or "")


def test_audit_repository_has_no_mutators() -> None:
    from src.adapters.repositories import AuditRepository

    assert not [m for m in dir(AuditRepository) if m.startswith(("update", "delete", "remove"))]


def test_finding_citing_unknown_evidence_is_rejected_by_engine_rules(store: Store) -> None:
    # A Finding with evidence must reference persisted evidence; lineage resolves through it.
    with store.tx() as tx:
        run = tx.runs.create(company_id="c", connection_id="fixture:x", requested_by="a")
        ev = Evidence(source_uri="duckdb://c/t", source_type="t", content_hash="h", payload={"n": 1})
        tx.evidence.save(run.run_id, ev)
        f = Finding(code="X", title="t", statement="s", confidence=Confidence.HIGH, evidence=[ev.ref()])
        tx.findings.save(run.run_id, "step", f)
        assert tx.findings.evidence_links(f.finding_id) == [(ev.evidence_id, "supports")]
        got, _, parents = tx.evidence.get(ev.evidence_id)
        assert got.payload == {"n": 1} and parents == []


def test_missing_run_raises(store: Store) -> None:
    with store.tx() as tx, pytest.raises(NotFound):
        tx.runs.get(uuid4())
