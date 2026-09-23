"""dbt + semantic layer generation (POD-307): determinism, snapshots, PII handling, fail-closed approvals."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from src.domain.errors import ApprovalRequired
from src.domain.models import StepName, utcnow
from src.domain.ontology import load_ontology
from src.domain.project_models import ArtifactBundle, ResolvedMapping, SchemaProfile
from src.services.generation import Generator, generate_artifacts
from src.workflows.contracts import StepContext
from tests.conftest import AGENT, CompletedRun

pytestmark = [pytest.mark.integration, pytest.mark.slow]
SNAPSHOTS = Path(__file__).parent / "snapshots" / "portco_a"


def _inputs(c: CompletedRun) -> tuple[ResolvedMapping, SchemaProfile]:
    return (
        c.service.artifact(AGENT, c.run_id, StepName.MAPPING_REVIEW),
        c.service.artifact(AGENT, c.run_id, StepName.SCHEMA_PROFILING),
    )


def test_generation_is_deterministic(completed_a: CompletedRun) -> None:
    resolved, profile = _inputs(completed_a)
    a = Generator(resolved, profile, load_ontology(), "portco_a", None).build()
    b = Generator(resolved, profile, load_ontology(), "portco_a", None).build()
    assert a == b
    bundle = completed_a.service.artifact(AGENT, completed_a.run_id, StepName.ARTIFACT_GENERATION)
    assert isinstance(bundle, ArtifactBundle) and len(bundle.manifest_hash) == 64


def test_generated_project_matches_snapshots(completed_a: CompletedRun) -> None:
    bundle = completed_a.service.artifact(AGENT, completed_a.run_id, StepName.ARTIFACT_GENERATION)
    files = {f.path: completed_a.service.store.blobs.get_bytes(f.sha256).decode() for f in bundle.files}
    if os.environ.get("UPDATE_SNAPSHOTS"):
        for path, text in files.items():
            target = SNAPSHOTS / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    committed = {
        p.relative_to(SNAPSHOTS).as_posix(): p.read_text(encoding="utf-8") for p in SNAPSHOTS.rglob("*") if p.is_file()
    }
    assert set(committed) == set(files), "file set changed; run with UPDATE_SNAPSHOTS=1 and review the diff"
    for path, text in files.items():
        assert committed[path] == text, f"{path} changed; run with UPDATE_SNAPSHOTS=1 and review the diff"


def test_no_pii_column_is_selected_unhashed(completed_a: CompletedRun) -> None:
    _resolved, profile = _inputs(completed_a)
    bundle = completed_a.service.artifact(AGENT, completed_a.run_id, StepName.ARTIFACT_GENERATION)
    files = {f.path: completed_a.service.store.blobs.get_bytes(f.sha256).decode() for f in bundle.files}
    pii = {(t.qualified, c.column) for t in profile.tables for c in t.columns if c.pii_class}
    for table, column in pii:
        schema, name = table.split(".")
        sql = files.get(f"models/staging/{schema}/stg_{schema}__{name}.sql", "")
        body = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
        for occurrence in re.finditer(rf'"{re.escape(column)}"', body):
            window = body[max(0, occurrence.start() - 20) : occurrence.start()]
            assert "sha256(cast(" in window, f"{table}.{column} selected without hashing"


def test_review_override_reflected_in_staging_sql(completed_a: CompletedRun) -> None:
    sql = completed_a.service.bundle_file(AGENT, completed_a.run_id, "models/staging/crm/stg_crm__opportunities.sql")
    assert 'cast("rev" as decimal(18, 2)) as amount' in sql
    lines = completed_a.service.bundle_file(
        AGENT, completed_a.run_id, "models/staging/billing/stg_billing__invoice_lines.sql"
    )
    assert "/ 100 as decimal(18, 2)) as amount" in lines  # reviewed cents_to_major transform


def test_profiles_only_target_the_sandbox(completed_a: CompletedRun) -> None:
    profiles = completed_a.service.bundle_file(AGENT, completed_a.run_id, "profiles.yml")
    assert "env_var('PORTCO_DBT_WAREHOUSE')" in profiles and "read_only: true" in profiles
    assert ":\\" not in profiles and "/var/" not in profiles  # no hard-coded paths


def test_generation_fails_closed_when_mapping_approval_is_revoked(completed_a: CompletedRun) -> None:
    svc = completed_a.service
    resolved, profile = _inputs(completed_a)
    with svc.store.tx() as tx:
        approvals = [a.model_copy(update={"revoked_at": utcnow()}) for a in tx.approvals.for_run(completed_a.run_id)]
    ctx = StepContext(
        run=completed_a.run,
        settings=svc.settings,
        ontology=load_ontology(),
        blobs=svc.store.blobs,
        store=svc.store,
        open_adapter=lambda: svc.connections.open("fixture:portco_a"),
        upstream={StepName.MAPPING_REVIEW: resolved, StepName.SCHEMA_PROFILING: profile},
        approvals=approvals,
    )
    with pytest.raises(ApprovalRequired):
        generate_artifacts(ctx)
    ctx.close()
