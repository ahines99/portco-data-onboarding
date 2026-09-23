"""Execution leases, cancellation, crash recovery and the status transition table (POD-401, audit M5)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src.domain.errors import Conflict
from src.domain.models import Confidence, EvidenceRef, Finding, RunStatus, StepName, utcnow
from src.domain.run_states import CLAIMABLE, TRANSITIONS, can_transition
from src.workflows.base import StepSpec, WorkflowEngine
from src.workflows.contracts import StepContext, StepResult
from src.workflows.facade import OnboardingService
from src.workflows.versioning import pipeline_version
from tests.conftest import ADMIN, AGENT, REVIEWER, make_settings

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

S = RunStatus
EXPECTED = {
    (S.PENDING, S.RUNNING), (S.PENDING, S.CANCELLED),
    (S.RUNNING, S.PENDING), (S.RUNNING, S.NEEDS_REVIEW), (S.RUNNING, S.COMPLETE),
    (S.RUNNING, S.FAILED), (S.RUNNING, S.CANCELLED),
    (S.NEEDS_REVIEW, S.RUNNING), (S.NEEDS_REVIEW, S.PENDING), (S.NEEDS_REVIEW, S.CANCELLED),
    (S.FAILED, S.RUNNING), (S.FAILED, S.PENDING), (S.FAILED, S.CANCELLED),
    (S.COMPLETE, S.PENDING),
}  # fmt: skip


@pytest.mark.parametrize("src", list(S))
@pytest.mark.parametrize("dst", list(S))
def test_transition_table(src: RunStatus, dst: RunStatus) -> None:
    expected = (src, dst) in EXPECTED or (src == dst and src is not S.CANCELLED)
    assert can_transition(src, dst) is expected


def test_cancelled_is_terminal_and_claimable_states_are_resumable() -> None:
    assert TRANSITIONS[S.CANCELLED] == frozenset()
    assert all(can_transition(s, S.RUNNING) for s in CLAIMABLE)


def _engine(svc: OnboardingService, *fns: Any) -> WorkflowEngine:
    names = [StepName.CONNECTION_VALIDATION, StepName.SCHEMA_PROFILING, StepName.ENTITY_INFERENCE]
    return WorkflowEngine(
        store=svc.store,
        settings=svc.settings,
        ontology=svc.engine.ontology,
        connections=svc.connections,
        steps=[StepSpec(name=n, fn=f, output_type=None) for n, f in zip(names, fns, strict=False)],
    )


def _new_run(svc: OnboardingService) -> Any:
    with svc.store.tx() as tx:
        return tx.runs.create(company_id="portco_a", connection_id="fixture:portco_a", requested_by="agent:claude")


def _ok(ctx: StepContext) -> StepResult:
    return StepResult()


async def test_claim_is_exclusive(service: OnboardingService) -> None:
    run = _new_run(service)
    with service.store.tx() as tx:
        tx.runs.claim(run.run_id, "w1", 60)
    with pytest.raises(Conflict), service.store.tx() as tx:
        tx.runs.claim(run.run_id, "w2", 60)
    with pytest.raises(Conflict):
        await service.resume(AGENT, run.run_id)


async def test_expired_lease_is_recovered_by_resume(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a", stop_after=StepName.SCHEMA_PROFILING)
    with service.store.tx() as tx:  # simulate a worker that died mid-run
        tx.runs.update(run.run_id, status=S.RUNNING)
        tx.runs.update(run.run_id, lease_owner="dead#1", lease_expires_at=utcnow() - timedelta(seconds=1))
    run = await service.resume(AGENT, run.run_id)
    assert run.status is S.NEEDS_REVIEW and run.lease_owner is None
    events, ok = service.audit(ADMIN, run.run_id)
    recovered = [e for e in events if e.event_type == "run_recovered"]
    assert ok and recovered and recovered[0].payload["previous_owner"] == "dead#1"


async def test_cancel_during_a_step_discards_its_result(service: OnboardingService) -> None:
    run = _new_run(service)
    ran: list[str] = []

    def cancel_midway(ctx: StepContext) -> StepResult:
        service.cancel(REVIEWER, ctx.run.run_id, "operator stop")
        return StepResult(evidence=[])

    def never(ctx: StepContext) -> StepResult:
        ran.append("second")
        return StepResult()

    result = await _engine(service, cancel_midway, never).run(run.run_id, "agent:claude")
    assert result.status is S.CANCELLED and result.lease_owner is None and not ran
    with service.store.tx() as tx:
        steps = tx.steps.list(run.run_id)
        types = [e.event_type for e in tx.audit.list(run.run_id)]
    assert [s.status for s in steps] == ["cancelled"]
    assert "step_discarded" in types and "run_stopped" in types and "step_completed" not in types


async def test_crash_while_persisting_fails_the_run_and_releases_the_lease(service: OnboardingService) -> None:
    run = _new_run(service)

    def bad_citation(ctx: StepContext) -> StepResult:
        ghost = EvidenceRef(source_id="00000000-0000-0000-0000-000000000000", uri="x://y", retrieved_at=utcnow())
        return StepResult(
            findings=[Finding(code="X", title="t", statement="s", confidence=Confidence.LOW, evidence=[ghost])]
        )

    result = await _engine(service, bad_citation).run(run.run_id, "agent:claude")
    assert result.status is S.FAILED and result.error and result.error["code"] == "INTERNAL"
    assert result.lease_owner is None
    # The failed run can be resumed (claimed) again.
    result = await _engine(service, _ok).run(run.run_id, "agent:claude")
    assert result.status is S.COMPLETE


async def test_invalid_transitions_are_rejected(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a", stop_after=StepName.CONNECTION_VALIDATION)
    service.cancel(REVIEWER, run.run_id, "stop")
    with pytest.raises(Conflict):
        service.cancel(REVIEWER, run.run_id, "again")
    with pytest.raises(Conflict):
        await service.rerun_from(ADMIN, run.run_id, StepName.SCHEMA_PROFILING)
    with pytest.raises(Conflict), service.store.tx() as tx:
        tx.runs.update(run.run_id, status=S.RUNNING)


async def test_rerun_is_refused_while_a_worker_holds_the_lease(service: OnboardingService) -> None:
    run = await service.start_run(AGENT, "fixture:portco_a", stop_after=StepName.CONNECTION_VALIDATION)
    with service.store.tx() as tx:
        tx.runs.claim(run.run_id, "w1", 60)
    with pytest.raises(Conflict):
        await service.rerun_from(ADMIN, run.run_id, StepName.CONNECTION_VALIDATION)


def test_step_timeout_must_outlast_dbt(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        make_settings(tmp_path, step_timeout_seconds=300, dbt_timeout_seconds=600)
    assert make_settings(tmp_path).step_timeout_seconds > make_settings(tmp_path).dbt_timeout_seconds + 60


def test_pipeline_version_tracks_code_and_ignores_line_endings(tmp_path: Path) -> None:
    (tmp_path / "ontology").mkdir()
    f = tmp_path / "ontology" / "o.yaml"
    f.write_bytes(b"a: 1\n")
    v1 = pipeline_version.__wrapped__(tmp_path)
    f.write_bytes(b"a: 1\r\n")
    assert pipeline_version.__wrapped__(tmp_path) == v1
    f.write_bytes(b"a: 2\n")
    assert pipeline_version.__wrapped__(tmp_path) != v1
