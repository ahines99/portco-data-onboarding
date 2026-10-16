"""Regressions for the 2026-10-10 audit's workflow-authority findings (A04, A05, A09, A10, A21, lease race).

Each test drives the real boundary the audit reproduced against: the public service for cached
generation, the actual engine for stale-worker takeover, and the real publication service for
crash recovery. Scheduling is injected deterministically (no sleeps).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import update

from src.adapters import db
from src.adapters.repositories import PublicationRepository, RunRepository
from src.domain.errors import ApprovalRequired, Conflict
from src.domain.models import ReviewDecision, ReviewGate, RunStatus, StepName, utcnow
from src.domain.project_models import (
    Approval,
    ArtifactBundle,
    CertificationPacket,
    ItemDecision,
    MappingSet,
    PublishReceipt,
    RowFilter,
)
from src.services.gates import mapping_review
from src.services.generation import check_generation_authority
from src.services.publish import publish_bundle
from src.settings import Settings
from src.workflows.base import StepSpec, WorkflowEngine, output_hash
from src.workflows.contracts import StepResult
from src.workflows.facade import OnboardingService
from tests.conftest import AGENT, REVIEWER, STANDARD_OVERRIDES, decide_all, make_service
from tests.test_publication_recovery import operations, publication_context

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def _generated(svc: OnboardingService) -> tuple[Any, Approval]:
    run = await svc.start_run(AGENT, "fixture:portco_a")
    approval = svc.submit_review(
        REVIEWER,
        run.run_id,
        decide_all(run.pending_items, STANDARD_OVERRIDES),
        subject_hash=run.pending_items[0].subject_hash,
        gate=ReviewGate(run.gate),
    )
    run = await svc.resume(AGENT, run.run_id, stop_after=StepName.ARTIFACT_GENERATION)
    assert run.current_step == StepName.AUTOMATED_TESTS.value
    return run, approval


def _active(svc: OnboardingService, run_id: Any, step: StepName) -> Any:
    with svc.store.tx() as tx:
        return tx.steps.active(run_id, step.value)


# --------------------------------------------------------------------------- A04 cached generation


@pytest.mark.parametrize("lapse", ["revoked", "expired"])
async def test_lapsed_mapping_approval_cannot_pass_through_the_generation_cache(
    tmp_path: Path, fixtures_dir: Path, lapse: str
) -> None:
    svc = make_service(tmp_path)
    run, approval = await _generated(svc)
    cached = _active(svc, run.run_id, StepName.ARTIFACT_GENERATION)
    with svc.store.tx() as tx:
        if lapse == "revoked":
            tx.approvals.revoke(approval.approval_id, "audit regression")
        else:
            tx.conn.execute(
                update(db.approvals)
                .where(db.approvals.c.approval_id == approval.approval_id)
                .values(expires_at=utcnow() - timedelta(seconds=1))
            )

    run = await svc.rerun_from(
        REVIEWER, run.run_id, StepName.ARTIFACT_GENERATION, stop_after=StepName.ARTIFACT_GENERATION
    )

    # The run returns to the mapping review instead of reusing (or advancing past) the cached bundle.
    assert run.status is RunStatus.NEEDS_REVIEW and run.gate == ReviewGate.MAPPING_REVIEW.value
    assert run.pending_items
    assert _active(svc, run.run_id, StepName.ARTIFACT_GENERATION) is None
    events, ok = svc.audit(REVIEWER, run.run_id)
    lapsed = [e for e in events if e.event_type == "authority_lapsed"]
    assert ok and len(lapsed) == 1 and lapsed[0].payload["rewind_to"] == StepName.MAPPING_REVIEW.value
    assert cached is not None

    # A fresh review restores authority; generation then produces the identical bundle again.
    svc.submit_review(
        REVIEWER,
        run.run_id,
        decide_all(run.pending_items, STANDARD_OVERRIDES),
        subject_hash=run.pending_items[0].subject_hash,
        gate=ReviewGate(run.gate),
    )
    run = await svc.resume(AGENT, run.run_id, stop_after=StepName.ARTIFACT_GENERATION)
    assert run.current_step == StepName.AUTOMATED_TESTS.value
    regenerated = _active(svc, run.run_id, StepName.ARTIFACT_GENERATION)
    assert regenerated is not None and regenerated.output_hash == cached.output_hash


async def test_valid_approval_still_reuses_the_cached_bundle(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    run, _ = await _generated(svc)
    cached = _active(svc, run.run_id, StepName.ARTIFACT_GENERATION)
    run = await svc.rerun_from(
        REVIEWER, run.run_id, StepName.ARTIFACT_GENERATION, stop_after=StepName.ARTIFACT_GENERATION
    )
    assert run.current_step == StepName.AUTOMATED_TESTS.value
    assert _active(svc, run.run_id, StepName.ARTIFACT_GENERATION).step_run_id == cached.step_run_id


# --------------------------------------------------------------------------- A09 approval provenance


def test_expired_superseded_approval_is_not_a_generation_dependency(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    ctx = publication_context(svc)
    ms = MappingSet(
        proposals=[],
        row_filters=[
            RowFilter(
                filter_key="f",
                table="crm.accounts",
                column="test",
                kind="exclude_true",
                rationale="test",
                affected_rows=1,
            )
        ],
    )

    def approval_at(expiry: Any) -> Approval:
        return Approval(
            run_id=ctx.run.run_id,
            gate=ReviewGate.MAPPING_REVIEW,
            subject_hash=ms.content_hash(),
            decisions=[ItemDecision(item_key="filter:f", decision=ReviewDecision.APPROVE)],
            reviewer="alice",
            role="reviewer",
            expires_at=expiry,
        )

    expired, fresh = approval_at(utcnow() - timedelta(seconds=1)), approval_at(utcnow() + timedelta(hours=1))
    ctx.approvals = [expired, fresh]
    ctx.upstream[StepName.CANONICAL_MAPPING] = ms
    reviewed = mapping_review(ctx)
    assert reviewed.status == "ok" and reviewed.output is not None
    assert reviewed.output.approval_ids == [fresh.approval_id]
    ctx.upstream[StepName.MAPPING_REVIEW] = reviewed.output
    check_generation_authority(ctx)  # does not raise

    # A revoked approval that still supplies the only decision remains a hard failure.
    revoked_only = reviewed.output.model_copy(update={"approval_ids": [expired.approval_id]})
    ctx.upstream[StepName.MAPPING_REVIEW] = revoked_only
    with pytest.raises(ApprovalRequired):
        check_generation_authority(ctx)


# --------------------------------------------------------------------------- A05 stale worker


def _publish_engine(svc: OnboardingService) -> WorkflowEngine:
    return WorkflowEngine(
        store=svc.store,
        settings=svc.settings,
        ontology=svc.engine.ontology,
        connections=svc.connections,
        steps=[
            StepSpec(StepName.ARTIFACT_GENERATION, lambda c: StepResult(), ArtifactBundle),
            StepSpec(StepName.HUMAN_CERTIFICATION, lambda c: StepResult(), CertificationPacket, always_execute=True),
            StepSpec(StepName.PUBLISH, publish_bundle, PublishReceipt, always_execute=True, retryable=False),
        ],
    )


def _seed_publish_run(svc: OnboardingService, engine: WorkflowEngine) -> Any:
    ctx = publication_context(svc)
    with svc.store.tx() as tx:
        tx.runs.update(ctx.run.run_id, status=RunStatus.PENDING, current_step=StepName.PUBLISH.value)
        tx.runs.release(ctx.run.run_id, "worker")
        run = tx.runs.get(ctx.run.run_id)
        hashes: dict[str, str] = {}
        for spec in engine.steps[:2]:
            model = ctx.upstream[spec.name]
            sr = tx.steps.start(run.run_id, spec.name.value, engine.input_hash(spec, hashes, run))
            oh = output_hash(model)
            tx.steps.finish(sr.step_run_id, status="completed", output_ref=ctx.blobs.put_model(model), output_hash=oh)
            hashes[spec.name.value] = oh
    return ctx


async def test_stale_worker_cannot_publish_or_touch_its_successor(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    engine = _publish_engine(svc)
    ctx = _seed_publish_run(svc, engine)
    original = engine._heartbeat
    owners: list[str] = []

    def paused_then_replaced(run_id: Any, owner: str) -> bool:
        owned = original(run_id, owner)
        owners.append(owner)
        with svc.store.tx() as tx:  # deterministic stand-in for a pause longer than the lease
            tx.runs.update(run_id, lease_expires_at=utcnow() - timedelta(seconds=1))
            tx.runs.claim(run_id, "successor", 600)
        return owned

    engine._heartbeat = paused_then_replaced  # type: ignore[method-assign]
    result = await engine.run(ctx.run.run_id, "old-worker")

    assert owners and owners[0].startswith("old-worker#")
    assert result.status is RunStatus.RUNNING and result.lease_owner == "successor" and result.lease_live()
    assert result.current_step == StepName.PUBLISH.value and result.stop_after is None
    assert operations(ctx) == []  # no prepared row, no rename
    published = svc.settings.published_root / ctx.run.company_id
    assert not published.exists() or not any(published.iterdir())

    # The successor (here: whoever next claims after its lease lapses) finishes exactly once.
    with svc.store.tx() as tx:
        tx.runs.update(ctx.run.run_id, lease_expires_at=utcnow() - timedelta(seconds=1))
    engine._heartbeat = original  # type: ignore[method-assign]
    done = await engine.run(ctx.run.run_id, "next-worker")
    assert done.status is RunStatus.COMPLETE
    rows = operations(ctx)
    assert len(rows) == 1 and rows[0]["state"] == "complete" and Path(rows[0]["receipt"]["path"]).is_dir()


# --------------------------------------------------------------------------- lease claim race (PostgreSQL)


def test_claim_does_not_overwrite_a_lease_renewed_after_it_was_read(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    with svc.store.tx() as tx:
        run = tx.runs.create(company_id="portco_a", connection_id="fixture:portco_a", requested_by="a")
        tx.runs.claim(run.run_id, "holder", 600)
        tx.runs.update(run.run_id, lease_expires_at=utcnow() - timedelta(seconds=1))
        stale = tx.runs.get(run.run_id)  # what a competing claimant read: an expired lease
        tx.runs.renew(run.run_id, "holder", 600)  # ...but the holder renewed before its update ran
    real_get = RunRepository.get

    def snapshot_get(self: RunRepository, run_id: Any, *, lock: bool = False) -> Any:
        return stale if lock else real_get(self, run_id)

    with patch.object(RunRepository, "get", snapshot_get), pytest.raises(Conflict), svc.store.tx() as tx:
        tx.runs.claim(run.run_id, "intruder", 600)
    with svc.store.tx() as tx:
        current = tx.runs.get(run.run_id)
    assert current.lease_owner == "holder" and current.lease_live()


# --------------------------------------------------------------------------- A10 recovery after expiry


def test_renamed_publication_is_recovered_after_certification_expires(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    ctx = publication_context(svc)
    with (
        patch.object(PublicationRepository, "complete", side_effect=RuntimeError("crash after rename")),
        pytest.raises(RuntimeError),
    ):
        publish_bundle(ctx)
    rows = operations(ctx)
    assert rows[0]["state"] == "prepared" and Path(rows[0]["receipt"]["path"]).is_dir()
    with svc.store.tx() as tx:
        tx.conn.execute(
            update(db.approvals)
            .where(db.approvals.c.run_id == ctx.run.run_id)
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )

    result = publish_bundle(ctx)

    rows = operations(ctx)
    assert rows[0]["state"] == "complete" and Path(rows[0]["receipt"]["path"]).is_dir()
    assert result.output is not None and result.output.version == rows[0]["receipt"]["version"]
    assert [a[0] for a in result.audit] == ["publication_recovered", "publish_completed"]


def test_unpublished_work_still_requires_current_certification(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    ctx = publication_context(svc)
    with svc.store.tx() as tx:
        tx.conn.execute(
            update(db.approvals)
            .where(db.approvals.c.run_id == ctx.run.run_id)
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
    with pytest.raises(ApprovalRequired):
        publish_bundle(ctx)
    assert operations(ctx) == []


def test_prepared_but_never_renamed_publication_requires_current_certification(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    svc = make_service(tmp_path)
    ctx = publication_context(svc)
    with patch("pathlib.Path.rename", side_effect=OSError("crash before rename")), pytest.raises(OSError):
        publish_bundle(ctx)
    rows = operations(ctx)
    assert rows[0]["state"] == "prepared" and not Path(rows[0]["receipt"]["path"]).exists()
    with svc.store.tx() as tx:
        tx.conn.execute(
            update(db.approvals)
            .where(db.approvals.c.run_id == ctx.run.run_id)
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
    with pytest.raises(ApprovalRequired):
        publish_bundle(ctx)
    assert not Path(operations(ctx)[0]["receipt"]["path"]).exists()


# --------------------------------------------------------------------------- A21 configuration bounds


@pytest.mark.parametrize(
    "override",
    [
        {"step_max_attempts": 0},
        {"step_backoff_base_seconds": -1},
        {"step_backoff_base_seconds": float("inf")},
        {"step_timeout_seconds": -20},
        {"dbt_timeout_seconds": -100},
        {"lease_margin_seconds": -200},
        {"approval_ttl_hours": -1},
        {"approval_ttl_hours": 0},
        {"sandbox_keep_attempts": -1},
        {"step_timeout_seconds": float("nan")},
    ],
)
def test_invalid_execution_settings_are_rejected(tmp_path: Path, override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(var_root=tmp_path, env="test", **override)


async def test_engine_never_leaves_a_run_running_without_a_worker(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    # Bypass validation the way a caller constructing settings by hand could.
    svc.engine.settings = svc.engine.settings.model_copy(update={"step_max_attempts": 0})
    run = await svc.start_run(AGENT, "fixture:portco_a", stop_after=StepName.SCHEMA_PROFILING)
    assert run.status is not RunStatus.RUNNING or run.lease_live()
    assert run.status in {RunStatus.PENDING, RunStatus.NEEDS_REVIEW}
    with svc.store.tx() as tx:
        assert tx.steps.active(run.run_id, StepName.SCHEMA_PROFILING.value) is not None
