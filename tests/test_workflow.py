"""Workflow engine: persistence, gates, separation of duties, idempotency, recovery (POD-401..406, 701)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.adapters.faults import FaultInjector
from src.domain.errors import Conflict, Forbidden, ValidationFailed
from src.domain.models import Principal, ReviewDecision, Role, RunStatus, StepName
from src.domain.project_models import ConnectionSpec, ItemDecision, MappingSet
from src.workflows.facade import OnboardingService
from tests.conftest import AGENT, REVIEWER, STANDARD_OVERRIDES, decide_all, make_service

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


def _attempts(svc: OnboardingService, run_id) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {s["step"]: s["attempts"] for s in svc.steps(AGENT, run_id)}


def _events(svc: OnboardingService, run_id) -> list[str]:  # type: ignore[no-untyped-def]
    return [e.event_type for e in svc.audit(AGENT, run_id)[0]]


async def test_run_pauses_at_mapping_review_with_no_llm(service: OnboardingService) -> None:
    assert "judge" not in service.services
    run = await service.start_run(AGENT, "fixture:portco_a")
    assert run.status is RunStatus.NEEDS_REVIEW and run.gate == "mapping_review"
    assert run.pending_items and all(i.subject_hash == run.pending_items[0].subject_hash for i in run.pending_items)
    attempts = _attempts(service, run.run_id)
    assert all(attempts[s.value] == 1 for s in list(StepName)[:5])
    assert "run_paused_for_review" in _events(service, run.run_id)


async def test_resume_without_approvals_stays_paused_and_does_not_recompute(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a")
    again = await service.resume(AGENT, run.run_id)
    assert again.status is RunStatus.NEEDS_REVIEW
    assert [i.item_key for i in again.pending_items] == [i.item_key for i in run.pending_items]
    attempts = _attempts(service, run.run_id)
    assert all(attempts[s.value] == 1 for s in list(StepName)[:5])  # steps 1-5 untouched


async def test_agent_cannot_approve_and_denial_is_audited(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a")
    with pytest.raises(Forbidden):
        service.submit_review(AGENT, run.run_id, decide_all(run.pending_items))
    assert "policy_denied" in _events(service, run.run_id)


async def test_reviewer_who_started_the_run_cannot_approve_it(service: OnboardingService) -> None:
    run = await service.start_run(REVIEWER, "fixture:portco_a")
    with pytest.raises(Forbidden, match="separation of duties"):
        service.submit_review(REVIEWER, run.run_id, decide_all(run.pending_items))


async def test_out_of_scope_reviewer_is_forbidden(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a")
    other = Principal(principal_id="bob", role=Role.REVIEWER, company_ids=("portco_b",))
    with pytest.raises(Exception, match="not found"):
        service.submit_review(other, run.run_id, decide_all(run.pending_items))


async def test_unknown_items_and_bad_overrides_are_rejected(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a")
    with pytest.raises(ValidationFailed, match="unknown review item"):
        service.submit_review(
            REVIEWER, run.run_id, [ItemDecision(item_key="mapping:x.y.z", decision=ReviewDecision.APPROVE)]
        )
    with pytest.raises(ValidationFailed, match="not a field"):
        service.submit_review(
            REVIEWER,
            run.run_id,
            [
                ItemDecision(
                    item_key="mapping:crm.opportunities.rev",
                    decision=ReviewDecision.APPROVE_WITH_OVERRIDE,
                    override={"canonical_field": "revenue_recognized"},
                )
            ],
        )


async def test_partial_review_keeps_remaining_items_pending(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a")
    first = run.pending_items[:3]
    service.submit_review(REVIEWER, run.run_id, decide_all(first))
    run = await service.resume(AGENT, run.run_id)
    assert run.status is RunStatus.NEEDS_REVIEW
    assert {i.item_key for i in run.pending_items}.isdisjoint({i.item_key for i in first})


async def test_resume_after_gate_a_continues_at_generation_without_rerunning_steps(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a")
    service.submit_review(REVIEWER, run.run_id, decide_all(run.pending_items, STANDARD_OVERRIDES))
    run = await service.resume(AGENT, run.run_id, stop_after=StepName.ARTIFACT_GENERATION)
    assert run.status is RunStatus.PENDING and run.current_step == StepName.AUTOMATED_TESTS.value
    attempts = _attempts(service, run.run_id)
    assert all(attempts[s.value] == 1 for s in list(StepName)[:5])
    assert attempts[StepName.ARTIFACT_GENERATION.value] == 1


async def test_idempotent_rerun_reuses_steps_and_produces_identical_hashes(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a")
    service.submit_review(REVIEWER, run.run_id, decide_all(run.pending_items, STANDARD_OVERRIDES))
    run = await service.resume(AGENT, run.run_id, stop_after=StepName.ARTIFACT_GENERATION)
    before_bundle = service.artifact(AGENT, run.run_id, StepName.ARTIFACT_GENERATION)
    before_findings = sorted((f.code, f.statement) for f in service.findings(AGENT, run.run_id))
    run = await service.rerun_from(
        REVIEWER, run.run_id, StepName.CONNECTION_VALIDATION, stop_after=StepName.ARTIFACT_GENERATION
    )
    assert run.status is RunStatus.PENDING
    events = _events(service, run.run_id)
    assert events.count("step_reused") >= 5  # profiling, entities, joins, mapping, generation
    after_bundle = service.artifact(AGENT, run.run_id, StepName.ARTIFACT_GENERATION)
    assert after_bundle.manifest_hash == before_bundle.manifest_hash
    assert sorted((f.code, f.statement) for f in service.findings(AGENT, run.run_id)) == before_findings


async def test_transient_timeout_is_retried(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path, faults=FaultInjector.parse("adapter.aggregate:timeout:nth=3"))
    run = await svc.start_run(AGENT, "fixture:portco_a")
    assert run.status is RunStatus.NEEDS_REVIEW
    assert _attempts(svc, run.run_id)[StepName.SCHEMA_PROFILING.value] == 2
    assert "step_retried" in _events(svc, run.run_id)


async def test_persistent_outage_fails_controlled_then_resumes(tmp_path: Path, fixtures_dir: Path) -> None:
    faults = FaultInjector.parse("adapter.list_tables:unavailable")
    svc = make_service(tmp_path, faults=faults)
    run = await svc.start_run(AGENT, "fixture:portco_a")
    assert run.status is RunStatus.FAILED
    assert run.error and run.error["code"] == "SOURCE_UNAVAILABLE" and run.error["retryable"]
    assert _attempts(svc, run.run_id)[StepName.CONNECTION_VALIDATION.value] == 3
    faults.faults.clear()  # outage over
    run = await svc.resume(AGENT, run.run_id)
    assert run.status is RunStatus.NEEDS_REVIEW and run.gate == "mapping_review"


async def test_write_capable_connection_is_refused(
    service: OnboardingService, fixtures_dir: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "writable.duckdb"
    shutil.copyfile(fixtures_dir / "portco_a.duckdb", copy)
    service.connections.register(
        ConnectionSpec(connection_id="writable:a", company_id="portco_a", path=str(copy), read_only=False)
    )
    run = await service.start_run(AGENT, "writable:a")
    assert run.status is RunStatus.FAILED and run.error and run.error["code"] == "POLICY_VIOLATION"
    assert _attempts(service, run.run_id)[StepName.CONNECTION_VALIDATION.value] == 1  # terminal, no retry


async def test_internal_crash_is_contained_without_leaking_details(
    service: OnboardingService, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.services.entities as entities_mod

    def boom(ctx):  # type: ignore[no-untyped-def]
        raise ValueError("secret detail 123-45-6789")

    spec_idx = next(i for i, s in enumerate(service.engine.steps) if s.name is StepName.ENTITY_INFERENCE)
    from dataclasses import replace

    service.engine.steps = [*service.engine.steps]
    service.engine.steps[spec_idx] = replace(service.engine.steps[spec_idx], fn=boom)
    del entities_mod
    run = await service.start_run(AGENT, "fixture:portco_a")
    assert run.status is RunStatus.FAILED and run.error
    assert run.error["code"] == "INTERNAL" and "123-45" not in str(run.error)


async def test_stop_after_pauses_and_resume_continues(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a", stop_after=StepName.SCHEMA_PROFILING)
    assert run.status is RunStatus.PENDING and run.current_step == StepName.ENTITY_INFERENCE.value
    run = await service.resume(AGENT, run.run_id)
    assert run.gate == "mapping_review"


async def test_cancel_and_resume_of_cancelled_run(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a")
    run = service.cancel(REVIEWER, run.run_id, "duplicate onboarding")
    assert run.status is RunStatus.CANCELLED
    assert (await service.resume(AGENT, run.run_id)).status is RunStatus.CANCELLED
    with pytest.raises(Forbidden):
        service.cancel(AGENT, run.run_id, "agents cannot cancel")


async def test_review_on_run_not_waiting_is_conflict(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a", stop_after=StepName.SCHEMA_PROFILING)
    with pytest.raises(Conflict):
        service.submit_review(REVIEWER, run.run_id, [ItemDecision(item_key="x", decision=ReviewDecision.APPROVE)])


async def test_reject_mapping_item_removes_it(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a")
    key = "mapping:crm.opportunities.rev"
    service.submit_review(REVIEWER, run.run_id, decide_all(run.pending_items, reject={key}))
    run = await service.resume(AGENT, run.run_id, stop_after=StepName.MAPPING_REVIEW)
    resolved = service.artifact(AGENT, run.run_id, StepName.MAPPING_REVIEW)
    assert key in resolved.rejected_keys
    assert not [a for a in resolved.accepted if a.source_column == "rev"]
    ms = service.artifact(AGENT, run.run_id, StepName.CANONICAL_MAPPING)
    assert isinstance(ms, MappingSet)


@pytest.mark.parametrize(
    "step",
    [
        StepName.CONNECTION_VALIDATION,
        StepName.SCHEMA_PROFILING,
        StepName.ENTITY_INFERENCE,
        StepName.JOIN_INFERENCE,
        StepName.CANONICAL_MAPPING,
    ],
)
async def test_every_step_has_an_audited_failure_path(service: OnboardingService, step: StepName) -> None:
    """Acceptance checklist: each step produces an artifact and audit events, and fails in a controlled way."""
    from dataclasses import replace

    from src.domain.errors import DataContractError

    def broken(ctx):  # type: ignore[no-untyped-def]
        raise DataContractError(f"simulated contract violation in {step.value}")

    idx = next(i for i, s in enumerate(service.engine.steps) if s.name is step)
    service.engine.steps = [*service.engine.steps]
    service.engine.steps[idx] = replace(service.engine.steps[idx], fn=broken)
    run = await service.start_run(AGENT, "fixture:portco_a")
    assert run.status is RunStatus.FAILED and run.current_step == step.value
    assert run.error and run.error["code"] == "DATA_CONTRACT" and run.error["retryable"] is False
    events = _events(service, run.run_id)
    assert "step_failed" in events and "run_failed" in events
    for earlier in service.engine.steps[:idx]:
        assert service.artifact(AGENT, run.run_id, earlier.name) is not None


@pytest.mark.slow
async def test_rejected_certification_fails_the_run(service: OnboardingService) -> None:
    from tests.conftest import drive

    run = await drive(service, certify=False)
    assert run.gate == "certification"
    subject = run.pending_items[0].subject_hash
    bundle_key = next(i.item_key for i in run.pending_items if i.kind == "bundle")
    service.certify(REVIEWER, run.run_id, subject, decide_all(run.pending_items, reject={bundle_key}))
    run = await service.resume(AGENT, run.run_id)
    assert run.status is RunStatus.FAILED and run.error and run.error["code"] == "VALIDATION"
    assert "rejected the bundle" in run.error["message"]
