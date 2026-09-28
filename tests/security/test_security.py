"""Security enforcement suite (POD-702, 703, 704; golden cases G15, G16, G17, G22, G24, G28, G30)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from src.domain.errors import ApprovalRequired, NotFound, PolicyViolation
from src.domain.models import Principal, ReviewGate, Role, RunStatus, StepName
from src.domain.ontology import load_ontology
from src.domain.pii_guard import PiiGuard
from src.fixtures.variants import INJECTION_COLUMN_COMMENT, INJECTION_COMMENT, INJECTION_VALUE
from src.reporting import render_run_report
from src.run_metrics import compute_run_metrics
from src.services import publish, sandbox
from src.workflows.contracts import StepContext
from src.workflows.facade import OnboardingService
from src.workflows.primary import PROJECT_STEPS
from tests.conftest import ADMIN, AGENT, REVIEWER, CompletedRun, decide_all, drive, make_service

pytestmark = [pytest.mark.security, pytest.mark.anyio]


def everything_emitted(svc: OnboardingService, run_id: Any) -> dict[str, Any]:
    """Every surface a model or human could see for a run."""
    out: dict[str, Any] = {"findings": [f.model_dump(mode="json") for f in svc.findings(ADMIN, run_id)]}
    for spec in PROJECT_STEPS:
        try:
            out[spec.name.value] = svc.artifact(ADMIN, run_id, spec.name).model_dump(mode="json")
        except NotFound:
            continue
    events, _ = svc.audit(ADMIN, run_id)
    out["audit"] = [e.model_dump(mode="json") for e in events]
    out["pending"] = [i.model_dump(mode="json") for i in svc.get_run(ADMIN, run_id).pending_items]
    with svc.store.tx() as tx:
        evidence_ids = {ref.source_id for f in tx.findings.current(run_id) for ref in f.evidence}
    out["evidence"] = [svc.evidence(ADMIN, __import__("uuid").UUID(e)).model_dump(mode="json") for e in evidence_ids]
    try:
        bundle = svc.artifact(ADMIN, run_id, StepName.ARTIFACT_GENERATION)
        out["files"] = {f.path: svc.store.blobs.get_bytes(f.sha256).decode() for f in bundle.files}
    except NotFound:
        pass
    out["report"] = render_run_report(svc, ADMIN, run_id)
    out["metrics"] = compute_run_metrics(svc, ADMIN, run_id)
    return out


def test_pii_canaries_never_leak_anywhere(completed_a: CompletedRun, truth_a: dict[str, Any]) -> None:
    """G17: no canary (or any detectable raw PII) appears in outputs, artifacts, audit, evidence or reports."""
    blob = everything_emitted(completed_a.service, completed_a.run_id)
    published = Path(completed_a.service.settings.published_root)
    blob["published"] = {p.as_posix(): p.read_text(encoding="utf-8") for p in published.rglob("*") if p.is_file()}
    violations = PiiGuard(canaries=truth_a["canaries"]).scan(blob)
    assert violations == [], violations[:5]


async def test_prompt_injection_in_comments_has_no_effect(tmp_path: Path, fixtures_dir: Path) -> None:
    """G15: flagged, withheld from outputs, and mappings identical to the clean fixture."""
    svc = make_service(tmp_path)
    base = await svc.start_run(AGENT, "fixture:portco_a")
    inj = await svc.start_run(AGENT, "fixture:portco_a__inj_comment")
    assert inj.status is RunStatus.NEEDS_REVIEW  # nothing got approved by the planted text
    codes = [f.code for f in svc.findings(AGENT, inj.run_id)]
    assert "INJECTION_FLAGGED" in codes

    def shape(run_id: Any) -> list[tuple[str, str, bool]]:
        ms = svc.artifact(AGENT, run_id, StepName.CANONICAL_MAPPING)
        return sorted((p.mapping_key, p.canonical_field, p.requires_review) for p in ms.proposals)

    assert shape(inj.run_id) == shape(base.run_id)
    emitted = json.dumps(everything_emitted(svc, inj.run_id))
    assert INJECTION_COMMENT not in emitted and INJECTION_COLUMN_COMMENT not in emitted


async def test_prompt_injection_in_values_never_leaves_the_adapter(tmp_path: Path, fixtures_dir: Path) -> None:
    """G16."""
    svc = make_service(tmp_path)
    run = await svc.start_run(AGENT, "fixture:portco_a__inj_values")
    assert "INJECTION_FLAGGED" in [f.code for f in svc.findings(AGENT, run.run_id)]
    assert INJECTION_VALUE not in json.dumps(everything_emitted(svc, run.run_id))


async def test_publish_without_certification_is_denied_and_audited(completed_a: CompletedRun) -> None:
    """G22: calling the publish step directly with no approvals fails closed."""
    svc = completed_a.service
    ctx = StepContext(
        run=completed_a.run,
        settings=svc.settings,
        ontology=load_ontology(),
        blobs=svc.store.blobs,
        store=svc.store,
        open_adapter=lambda: svc.connections.open("fixture:portco_a"),
        upstream={
            s: svc.artifact(ADMIN, completed_a.run_id, s)
            for s in (StepName.ARTIFACT_GENERATION, StepName.HUMAN_CERTIFICATION)
        },
        approvals=[],
    )
    with pytest.raises(ApprovalRequired):
        publish.publish_bundle(ctx)
    events, _ = svc.audit(ADMIN, completed_a.run_id)
    assert any(e.event_type == "policy_denied" and e.payload.get("action") == "publish" for e in events)


def test_dbt_cannot_target_outside_the_sandbox(completed_a: CompletedRun, tmp_path: Path) -> None:
    svc = completed_a.service
    ctx = StepContext(
        run=completed_a.run,
        settings=svc.settings,
        ontology=load_ontology(),
        blobs=svc.store.blobs,
        store=svc.store,
        open_adapter=lambda: svc.connections.open("fixture:portco_a"),
    )
    with pytest.raises(PolicyViolation):
        sandbox.run_dbt(ctx, tmp_path / "elsewhere", tmp_path / "source.duckdb")


def test_cross_tenant_reads_are_indistinguishable_from_missing(completed_a: CompletedRun) -> None:
    """G30 at the service layer: another tenant's run 'does not exist'."""
    outsider = Principal(principal_id="bob", role=Role.REVIEWER, company_ids=("portco_b",))
    with pytest.raises(NotFound):
        completed_a.service.get_run(outsider, completed_a.run_id)
    with pytest.raises(NotFound):
        completed_a.service.findings(outsider, completed_a.run_id)


@pytest.mark.slow
async def test_sandbox_failure_blocks_publish_and_source_is_untouched(tmp_path: Path, fixtures_dir: Path) -> None:
    """G28 + G20: malformed data fails dbt tests in the sandbox; nothing publishes; the source is unchanged."""
    source = fixtures_dir / "portco_a__malformed.duckdb"
    from src.fixtures.generate import ensure_fixture

    ensure_fixture("portco_a__malformed", fixtures_dir)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    svc = make_service(tmp_path)
    run = await drive(svc, "portco_a__malformed")
    assert "MIXED_TYPES" in [f.code for f in svc.findings(AGENT, run.run_id)]
    assert run.status is RunStatus.NEEDS_REVIEW and run.gate == "test_failures"
    report = svc.artifact(AGENT, run.run_id, StepName.AUTOMATED_TESTS)
    assert not report.passed and any("non_negative" in c for c in report.failing_checks)
    # dbt build skips everything downstream of a failing test, so the bad lines never reach the marts.
    assert any(r.status == "skipped" and "fct_invoice_line" in r.unique_id for r in report.dbt_results)
    assert not list(Path(svc.settings.published_root).rglob("*"))
    svc.submit_review(
        REVIEWER,
        run.run_id,
        decide_all(run.pending_items, reject={run.pending_items[0].item_key}),
        subject_hash=run.pending_items[0].subject_hash,
        gate=ReviewGate(run.gate),
    )
    run = await svc.resume(AGENT, run.run_id)
    assert run.status is RunStatus.FAILED and run.error and run.error["code"] == "VALIDATION"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


@pytest.mark.slow
async def test_changing_a_mapping_after_certification_revokes_it(tmp_path: Path, fixtures_dir: Path) -> None:
    """G24: reopen review -> new bundle -> the old certification is revoked and cannot publish."""
    svc = make_service(tmp_path)
    run = await drive(svc, certify=False)
    assert run.gate == "certification"
    manifest = run.pending_items[0].subject_hash
    old_cert = svc.certify(REVIEWER, run.run_id, manifest, decide_all(run.pending_items))
    run = await svc.rerun_from(REVIEWER, run.run_id, StepName.MAPPING_REVIEW, reopen_reviews=True)
    assert run.gate == "mapping_review"
    svc.submit_review(
        REVIEWER,
        run.run_id,
        decide_all(
            run.pending_items,
            {
                "mapping:crm.opportunities.rev": {"canonical_field": "amount"},
                "mapping:billing.invoice_lines.amount": {"transform": None},  # reviewer declines the cents transform
            },
        ),
        subject_hash=run.pending_items[0].subject_hash,
        gate=ReviewGate(run.gate),
    )
    run = await svc.resume(AGENT, run.run_id)
    assert run.gate in {"certification", "test_failures"}
    new_bundle = svc.artifact(AGENT, run.run_id, StepName.ARTIFACT_GENERATION)
    assert new_bundle.manifest_hash not in manifest
    with svc.store.tx() as tx:
        assert tx.approvals.get(old_cert.approval_id).revoked_at is not None
    if run.gate == "certification":
        packet = svc.artifact(AGENT, run.run_id, StepName.HUMAN_CERTIFICATION)
        with pytest.raises(ApprovalRequired):
            svc.verify_approval(run.run_id, old_cert.approval_id, ReviewGate.CERTIFICATION, packet.review_hash())
    events, ok = svc.audit(ADMIN, run.run_id)
    assert ok and any(e.event_type == "approval_invalidated" for e in events)
