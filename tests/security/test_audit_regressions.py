"""Regression tests for the security audit's critical/high findings (C1, H1, H2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.errors import PolicyViolation
from src.domain.identifiers import assert_safe, is_safe_identifier
from src.domain.models import RunStatus, StepName
from src.fixtures.variants import HOSTILE_COLUMN, HOSTILE_TABLE
from src.services import sandbox
from tests.conftest import ADMIN, AGENT, REVIEWER, CompletedRun, decide_all, drive, make_service

pytestmark = [pytest.mark.security, pytest.mark.anyio]


@pytest.mark.parametrize("name", [HOSTILE_COLUMN, HOSTILE_TABLE, "a\nb", "x{%raw%}", "col; drop", "#x", ""])
def test_unsafe_identifiers_are_rejected(name: str) -> None:
    assert not is_safe_identifier(name)
    with pytest.raises(PolicyViolation):
        assert_safe(name)


@pytest.mark.parametrize("name", ["KUNNR", "inv_no", "_x1", "DMBTR_S"])
def test_plain_identifiers_are_allowed(name: str) -> None:
    assert is_safe_identifier(name)


@pytest.mark.slow
async def test_c1_hostile_identifiers_never_reach_generated_code(tmp_path: Path, fixtures_dir: Path) -> None:
    from src.fixtures.generate import ensure_fixture

    ensure_fixture("portco_a__hostile_names", fixtures_dir)
    svc = make_service(tmp_path)
    run = await drive(svc, "portco_a__hostile_names")
    assert run.status is RunStatus.COMPLETE
    assert "UNSAFE_IDENTIFIER" in [f.code for f in svc.findings(AGENT, run.run_id)]
    bundle = svc.artifact(AGENT, run.run_id, StepName.ARTIFACT_GENERATION)
    blob = json.dumps({f.path: svc.store.blobs.get_bytes(f.sha256).decode() for f in bundle.files})
    profile = svc.artifact(AGENT, run.run_id, StepName.SCHEMA_PROFILING).model_dump_json()
    for text in (blob, profile):
        assert "raise_compiler_error" not in text and "pwned" not in text and "var('x')" not in text


def test_c1_dbt_gets_no_secrets_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTCO_ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("PORTCO_DATABASE_URL", "postgresql://u:p@h/db")
    import os

    passed = {k for k in os.environ if k.upper() in sandbox.DBT_ENV_ALLOWLIST}
    assert "PORTCO_ANTHROPIC_API_KEY" not in passed and "PORTCO_DATABASE_URL" not in passed


def test_h2_profiles_never_carry_sensitive_values(completed_a: CompletedRun) -> None:
    profile = completed_a.service.artifact(ADMIN, completed_a.run_id, StepName.SCHEMA_PROFILING)
    by_col = {f"{t.qualified}.{c.column}": c for t in profile.tables for c in t.columns}
    for col in ("hr.employees.dob", "hr.employees.salary", "hr.employees.ssn", "billing.payments.card_number"):
        c = by_col[col]
        assert c.min_value is None and c.max_value is None and c.mean_value is None, col
    created = by_col["billing.invoices.inv_date"]
    assert created.min_value is not None and len(created.min_value) == 7  # coarsened to YYYY-MM
    text = profile.model_dump_json()
    assert "1901-02-03" not in text and "987654.32" not in text


@pytest.mark.slow
async def test_h1_rejecting_a_metric_on_recertification_publishes_without_it(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    svc = make_service(tmp_path)
    run = await drive(svc)
    first = svc.artifact(AGENT, run.run_id, StepName.PUBLISH)
    assert "active_customers" in first.published_metrics
    run = await svc.rerun_from(ADMIN, run.run_id, StepName.HUMAN_CERTIFICATION, reopen_reviews=True)
    assert run.gate == "certification"
    svc.certify(
        REVIEWER,
        run.run_id,
        run.pending_items[0].subject_hash,
        decide_all(run.pending_items, reject={"metric:active_customers"}),
    )
    run = await svc.resume(AGENT, run.run_id)
    second = svc.artifact(AGENT, run.run_id, StepName.PUBLISH)
    assert run.status is RunStatus.COMPLETE
    assert second.version != first.version
    assert "active_customers" in second.excluded_metrics and "active_customers" not in second.published_metrics
    assert second.certification_id != first.certification_id
    events, ok = svc.audit(ADMIN, run.run_id)
    assert ok and [e.event_type for e in events].count("publish_completed") == 2
