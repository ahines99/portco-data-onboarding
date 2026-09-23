"""Database integrity, evidence lineage, generated-project parsing, fixture budgets and the MCP error
contract per tool (audit P2)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from mcp import Client
from sqlalchemy.exc import IntegrityError

from src.adapters import db
from src.adapters.artifact_store import ArtifactStore
from src.adapters.faults import FaultInjector
from src.adapters.repositories import Store
from src.domain.models import StepName
from src.domain.project_models import ArtifactBundle
from src.fixtures.generate import build_fixture
from src.workflows.facade import migrate
from tests.conftest import ADMIN, AGENT, REVIEWER, CompletedRun, make_service
from tests.test_mcp import Harness, call

ZERO = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    url = f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}"
    migrate(url)
    return Store(db.make_engine(url), ArtifactStore(tmp_path / "blobs"))


# --------------------------------------------------------------------------- integrity


@pytest.mark.unit
def test_foreign_keys_are_enforced(store: Store) -> None:
    with pytest.raises(IntegrityError), store.tx() as tx:
        tx.steps.start(uuid4(), "schema_profiling", "h")


@pytest.mark.unit
def test_step_attempts_are_unique(store: Store) -> None:
    with store.tx() as tx:
        run = tx.runs.create(company_id="c", connection_id="fixture:x", requested_by="a")
        sr = tx.steps.start(run.run_id, "schema_profiling", "h")
    row = {"run_id": run.run_id, "step": "schema_profiling", "attempt": sr.attempt, "status": "running"}
    with pytest.raises(IntegrityError), store.engine.begin() as conn:
        conn.execute(db.step_runs.insert().values(**row, input_hash="h", active=False, started_at=sr.started_at))


@pytest.mark.unit
def test_publication_key_and_version_are_unique_per_company(store: Store) -> None:
    with store.tx() as tx:
        run = tx.runs.create(company_id="c", connection_id="fixture:x", requested_by="a")
        tx.publications.insert("c", "m1", "key1", "v0001", run.run_id, {})
    with pytest.raises(IntegrityError), store.tx() as tx:  # same version, different content
        tx.publications.insert("c", "m2", "key2", "v0001", run.run_id, {})
    with pytest.raises(IntegrityError), store.tx() as tx:  # same content published twice
        tx.publications.insert("c", "m1", "key1", "v0002", run.run_id, {})
    with store.tx() as tx:  # another company may reuse both
        tx.publications.insert("d", "m1", "key1", "v0001", run.run_id, {})


# --------------------------------------------------------------------------- lineage


@pytest.mark.integration
def test_derived_evidence_points_back_to_profile_evidence(completed_a: CompletedRun) -> None:
    svc = completed_a.service
    derived: dict[str, int] = {}
    with svc.store.tx() as tx:
        rows = (
            svc.store.engine.connect()
            .execute(db.evidence.select().where(db.evidence.c.run_id == completed_a.run_id))
            .mappings()
        )
        for row in rows:
            if row["source_type"] not in {"entity_scoring", "containment", "column_conflict"}:
                continue
            _, _, parents = tx.evidence.get(row["evidence_id"])
            assert parents, f"{row['source_type']} evidence {row['evidence_id']} has no lineage"
            for p in parents:
                parent, _, _ = tx.evidence.get(p)
                assert parent.source_uri.startswith("duckdb://") and "#stat=profile" in parent.source_uri
            derived[row["source_type"]] = derived.get(row["source_type"], 0) + 1
    assert derived.get("entity_scoring") and derived.get("containment")
    conflict = next(f for f in svc.findings(ADMIN, completed_a.run_id) if f.code in {"CONFLICT", "ENTITY_OVERLAP"})
    tree = svc.lineage(ADMIN, conflict.finding_id)["evidence"]
    assert any("derived_from" in node for node in tree)


# --------------------------------------------------------------------------- generated project


@pytest.mark.slow
@pytest.mark.integration
def test_generated_project_parses_with_dbt(completed_a: CompletedRun, tmp_path: Path) -> None:
    svc = completed_a.service
    bundle = svc.artifact(ADMIN, completed_a.run_id, StepName.ARTIFACT_GENERATION)
    assert isinstance(bundle, ArtifactBundle)
    project = tmp_path / "p"
    for f in bundle.files:
        target = project / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(svc.store.blobs.get_bytes(f.sha256))
    env = {
        **os.environ,
        "PORTCO_DBT_WAREHOUSE": str(tmp_path / "wh.duckdb"),
        "PORTCO_DBT_SOURCE": str(tmp_path / "src.duckdb"),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
    }
    exe = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    cmd = [str(exe), "parse", "--project-dir", str(project), "--profiles-dir", str(project)]
    cmd += ["--target-path", str(tmp_path / "t"), "--log-path", str(tmp_path / "l"), "--no-partial-parse"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300, check=False)
    assert proc.returncode == 0, proc.stdout[-2000:]
    assert (tmp_path / "t" / "manifest.json").exists()


# --------------------------------------------------------------------------- fixtures


@pytest.mark.unit
@pytest.mark.parametrize(("name", "max_rows", "max_seconds"), [("portco_a", 60_000, 20.0), ("portco_b", 30_000, 20.0)])
def test_fixture_size_and_generation_time_stay_in_budget(name: str, max_rows: int, max_seconds: float) -> None:
    started = time.monotonic()
    fx = build_fixture(name)
    elapsed = time.monotonic() - started
    rows = sum(len(t.rows) for t in fx.tables)
    assert 0 < rows <= max_rows, rows
    assert elapsed <= max_seconds, f"{name} took {elapsed:.1f}s"


# --------------------------------------------------------------------------- MCP error contract per tool

RUN_TOOLS: list[tuple[str, dict[str, Any], Any]] = [
    ("get_run_status", {}, AGENT),
    ("resume_run", {}, AGENT),
    ("list_pending_reviews", {}, AGENT),
    ("propose_canonical_mapping", {}, AGENT),
    ("run_sandbox_tests", {}, AGENT),
    ("generate_dbt_artifacts", {"approval_id": ZERO}, AGENT),
    ("publish_run", {"certification_id": ZERO}, AGENT),
    ("submit_mapping_review", {"decisions": []}, REVIEWER),
    ("certify_run", {"subject_hash": "x"}, REVIEWER),
]


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "extra", "who"), RUN_TOOLS, ids=[t[0] for t in RUN_TOOLS])
async def test_every_run_tool_rejects_bad_and_unknown_ids(
    tool: str, extra: dict[str, Any], who: Any, tmp_path: Path, fixtures_dir: Path
) -> None:
    h = Harness(make_service(tmp_path)).as_(who)
    async with Client(h.server) as c:
        err, body = await call(c, tool, run_id="not-a-uuid", **extra)
        assert err and body["code"] == "VALIDATION" and body["retryable"] is False, body
        err, body = await call(c, tool, run_id=ZERO, **extra)
        assert err and body["code"] == "NOT_FOUND", body
        assert set(body) >= {"code", "message", "retryable"}


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("spec", "code"),
    [("adapter.list_tables:unavailable:always", "SOURCE_UNAVAILABLE"), ("adapter.aggregate:timeout:always", "TIMEOUT")],
)
async def test_dependency_failures_surface_in_the_run_summary(
    spec: str, code: str, tmp_path: Path, fixtures_dir: Path
) -> None:
    h = Harness(make_service(tmp_path, faults=FaultInjector.parse(spec)))
    async with Client(h.server) as c:
        err, run = await call(c, "start_onboarding_run", connection_id="fixture:portco_a")
    assert not err, run  # the tool succeeded; the run failed in a controlled way
    assert run["status"] == "failed" and run["error"]["code"] == code and run["error"]["retryable"] is True
    assert "resume" in run["next_action"].lower()
