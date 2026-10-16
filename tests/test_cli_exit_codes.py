"""CLI completion policy (audit A22) and the reviewer-only review reopen option.

Workflow-mutating commands must not report success when the workflow they drove failed: shell
automation relies on the process status. Faults are injected through the real service and
adapter fault injector, never by stubbing the run record.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from typer.testing import CliRunner

from src.adapters.faults import FaultInjector
from src.cli import EXIT_DOMAIN_ERROR, EXIT_RUN_CANCELLED, EXIT_RUN_FAILED, app
from src.domain.models import ReviewGate, RunStatus
from src.workflows.facade import OnboardingService
from tests.conftest import REVIEWER, decide_all, make_service

pytestmark = pytest.mark.integration

runner = CliRunner()


def _run_id(output: str) -> str:
    m = re.search(r"run ([0-9a-f-]{36})", output)
    assert m, output
    return m.group(1)


def _invoke(svc: OnboardingService, *args: str):
    with patch("src.cli._service", return_value=svc):
        return runner.invoke(app, list(args))


@pytest.fixture
def failing_service(tmp_path: Path, fixtures_dir: Path):
    svc = make_service(tmp_path, faults=FaultInjector.parse("adapter.probe:unavailable"), step_max_attempts=1)
    yield svc
    svc.store.engine.dispose()


@pytest.fixture
def healthy_service(tmp_path: Path, fixtures_dir: Path):
    svc = make_service(tmp_path)
    yield svc
    svc.store.engine.dispose()


def test_failed_workflow_exits_nonzero_for_run_resume_and_rerun(failing_service: OnboardingService) -> None:
    res = _invoke(failing_service, "run", "--fixture", "portco_a")
    assert res.exit_code == EXIT_RUN_FAILED, res.output
    assert "status=failed" in res.output and "SOURCE_UNAVAILABLE" in res.output
    rid = _run_id(res.output)  # the failure output still identifies the run for follow-up

    # Inspecting a failed run is a successful command.
    res = _invoke(failing_service, "status", rid)
    assert res.exit_code == 0, res.output
    assert "status=failed" in res.output

    res = _invoke(failing_service, "resume", rid)
    assert res.exit_code == EXIT_RUN_FAILED, res.output
    assert "status=failed" in res.output and rid in res.output

    res = _invoke(failing_service, "rerun", rid, "--from", "connection_validation")
    assert res.exit_code == EXIT_RUN_FAILED, res.output
    assert "status=failed" in res.output and rid in res.output


def test_review_pause_and_requested_stop_exit_zero_cancelled_exits_distinctly(
    healthy_service: OnboardingService,
) -> None:
    res = _invoke(healthy_service, "run", "--fixture", "portco_a", "--stop-after", "connection_validation")
    assert res.exit_code == 0, res.output
    assert "status=pending" in res.output
    rid = _run_id(res.output)

    res = _invoke(healthy_service, "resume", rid)
    assert res.exit_code == 0, res.output
    assert "status=needs_review" in res.output and "gate=mapping_review" in res.output

    # Domain rejections keep their own exit code.
    res = _invoke(healthy_service, "rerun", rid, "--from", "canonical_mapping", "--as", "bot:agent")
    assert res.exit_code == EXIT_DOMAIN_ERROR and "FORBIDDEN" in res.output

    # Cancelling is the requested outcome of `cancel`; a mutation that lands on a cancelled run is not success.
    res = _invoke(healthy_service, "cancel", rid)
    assert res.exit_code == 0 and "status=cancelled" in res.output, res.output
    res = _invoke(healthy_service, "resume", rid)
    assert res.exit_code == EXIT_RUN_CANCELLED, res.output
    assert "status=cancelled" in res.output
    res = _invoke(healthy_service, "status", rid)
    assert res.exit_code == 0, res.output


def _reviewed_mapping_run(svc: OnboardingService) -> str:
    res = _invoke(svc, "run", "--fixture", "portco_a")
    assert res.exit_code == 0 and "gate=mapping_review" in res.output, res.output
    rid = _run_id(res.output)
    run = svc.get_run(REVIEWER, UUID(rid))
    svc.submit_review(
        REVIEWER,
        run.run_id,
        decide_all(run.pending_items, overrides={"mapping:crm.opportunities.rev": {"canonical_field": "amount"}}),
        None,
        subject_hash=run.pending_items[0].subject_hash,
        gate=ReviewGate.MAPPING_REVIEW,
    )
    # Pause right after the gate so the test exercises review handling, not dbt.
    with svc.store.tx() as tx:
        tx.runs.update(run.run_id, stop_after="mapping_review")
    return rid


def _open_mapping_approvals(svc: OnboardingService, rid: str) -> list:
    run = svc.get_run(REVIEWER, UUID(rid))
    with svc.store.tx() as tx:
        return [
            a for a in tx.approvals.for_run(run.run_id) if a.gate is ReviewGate.MAPPING_REVIEW and a.revoked_at is None
        ]


def test_rerun_default_keeps_existing_review_approvals(healthy_service: OnboardingService) -> None:
    svc = healthy_service
    rid = _reviewed_mapping_run(svc)
    before = _open_mapping_approvals(svc, rid)
    assert len(before) == 1

    res = _invoke(svc, "rerun", rid, "--from", "canonical_mapping")
    assert res.exit_code == 0, res.output
    assert "reopened reviews" not in res.output
    assert "status=pending" in res.output and "step=artifact_generation" in res.output
    assert [a.approval_id for a in _open_mapping_approvals(svc, rid)] == [before[0].approval_id]


def test_rerun_reopen_reviews_revokes_and_reports_approvals(healthy_service: OnboardingService) -> None:
    svc = healthy_service
    rid = _reviewed_mapping_run(svc)
    (approval,) = _open_mapping_approvals(svc, rid)

    # Only human principals may reopen; the agent is refused before anything is revoked.
    res = _invoke(svc, "rerun", rid, "--from", "canonical_mapping", "--reopen-reviews", "--as", "bot:agent")
    assert res.exit_code == EXIT_DOMAIN_ERROR and "FORBIDDEN" in res.output, res.output
    assert _open_mapping_approvals(svc, rid)

    res = _invoke(svc, "rerun", rid, "--from", "canonical_mapping", "--reopen-reviews")
    assert res.exit_code == 0, res.output
    assert "reopened reviews: revoked 1 approval(s)" in res.output
    assert f"revoked approval {approval.approval_id}" in res.output and "gate=mapping_review" in res.output
    assert "status=needs_review" in res.output and "gate=mapping_review" in res.output
    assert not _open_mapping_approvals(svc, rid)
    run = svc.get_run(REVIEWER, UUID(rid))
    assert run.status is RunStatus.NEEDS_REVIEW and run.pending_items
