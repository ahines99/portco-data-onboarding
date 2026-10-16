"""Isolated audit reproductions; run with the repository virtualenv's Python."""

import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, str(next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()))
)

(
    next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
    / "var"
    / "audit-2026-10-10"
).mkdir(parents=True, exist_ok=True)

import anyio
from sqlalchemy import update

from src.adapters import db
from src.adapters.repositories import PublicationRepository
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
    SchemaProfile,
)
from src.services.gates import mapping_review
from src.services.generation import generate_artifacts
from src.services.publish import publish_bundle
from src.workflows.base import StepSpec, WorkflowEngine, output_hash
from src.workflows.contracts import StepContext, StepResult
from tests.conftest import AGENT, REVIEWER, STANDARD_OVERRIDES, decide_all, make_service
from tests.test_publication_recovery import operations, publication_context


async def main():
    root = Path(tempfile.mkdtemp(prefix="portco-audit02-preserved-"))
    svc = make_service(root)
    results = []
    try:
        # Real public-service path: cached generation skips revoked approval guard.
        run = await svc.start_run(AGENT, "fixture:portco_a")
        approval = svc.submit_review(
            REVIEWER,
            run.run_id,
            decide_all(run.pending_items, STANDARD_OVERRIDES),
            subject_hash=run.pending_items[0].subject_hash,
            gate=ReviewGate(run.gate),
        )
        run = await svc.resume(AGENT, run.run_id, stop_after=StepName.ARTIFACT_GENERATION)
        with svc.store.tx() as tx:
            tx.approvals.revoke(approval.approval_id, "audit reproduction")
            original = tx.steps.active(run.run_id, StepName.ARTIFACT_GENERATION.value)
            upstream, _ = svc.engine._load_upstream(tx, run.run_id, StepName.ARTIFACT_GENERATION)
            approvals = tx.approvals.for_run(run.run_id)
        ctx = StepContext(
            run=run,
            settings=svc.settings,
            ontology=svc.engine.ontology,
            blobs=svc.store.blobs,
            store=svc.store,
            open_adapter=svc.engine._open_adapter(run),
            upstream=upstream,
            approvals=approvals,
        )
        direct = "unexpected_success"
        try:
            generate_artifacts(ctx)
        except ApprovalRequired:
            direct = "ApprovalRequired"
        finally:
            ctx.close()
        run = await svc.rerun_from(
            REVIEWER,
            run.run_id,
            StepName.ARTIFACT_GENERATION,
            stop_after=StepName.ARTIFACT_GENERATION,
        )
        with svc.store.tx() as tx:
            after = tx.steps.active(run.run_id, StepName.ARTIFACT_GENERATION.value)
        results.append(
            {
                "repro": "revoked_mapping_generation_cache",
                "status": run.status.value,
                "current_step": run.current_step,
                "direct_generation": direct,
                "same_step_id": original.step_run_id == after.step_run_id,
            }
        )

        # Valid replacement approval cannot cure an expired historical approval.
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
        decisions = [ItemDecision(item_key="filter:f", decision=ReviewDecision.APPROVE)]

        def approval_at(expiry):
            return Approval(
                run_id=ctx.run.run_id,
                gate=ReviewGate.MAPPING_REVIEW,
                subject_hash=ms.content_hash(),
                decisions=decisions,
                reviewer="alice",
                role="reviewer",
                expires_at=expiry,
            )

        expired = approval_at(utcnow() - timedelta(seconds=1))
        fresh = approval_at(utcnow() + timedelta(hours=1))
        ctx.approvals = [expired, fresh]
        ctx.upstream[StepName.CANONICAL_MAPPING] = ms
        reviewed = mapping_review(ctx)
        ctx.upstream[StepName.MAPPING_REVIEW] = reviewed.output
        ctx.upstream[StepName.SCHEMA_PROFILING] = SchemaProfile(
            connection_id="fixture:portco_a",
            company_id="portco_a",
            source_fingerprint="x",
            tables=[],
        )
        gen = "unexpected_success"
        try:
            generate_artifacts(ctx)
        except ApprovalRequired:
            gen = "ApprovalRequired"
        results.append(
            {
                "repro": "expired_old_approval_poison",
                "review_status": reviewed.status,
                "expired_id_retained": expired.approval_id in reviewed.output.approval_ids,
                "fresh_id_retained": fresh.approval_id in reviewed.output.approval_ids,
                "generation": gen,
            }
        )

        # Actual engine.run; inject a process pause/lease takeover after heartbeat.
        ctx = publication_context(svc)
        engine = WorkflowEngine(
            store=svc.store,
            settings=svc.settings,
            ontology=svc.engine.ontology,
            connections=svc.connections,
            steps=[
                StepSpec(StepName.ARTIFACT_GENERATION, lambda c: StepResult(), ArtifactBundle),
                StepSpec(
                    StepName.HUMAN_CERTIFICATION, lambda c: StepResult(), CertificationPacket, always_execute=True
                ),
                StepSpec(StepName.PUBLISH, publish_bundle, PublishReceipt, always_execute=True, retryable=False),
            ],
        )
        with svc.store.tx() as tx:
            tx.runs.update(ctx.run.run_id, status=RunStatus.PENDING, current_step=StepName.PUBLISH.value)
            tx.runs.release(ctx.run.run_id, "worker")
            run = tx.runs.get(ctx.run.run_id)
            hashes = {}
            for spec in engine.steps[:2]:
                model = ctx.upstream[spec.name]
                sr = tx.steps.start(run.run_id, spec.name.value, engine.input_hash(spec, hashes, run))
                oh = output_hash(model)
                tx.steps.finish(
                    sr.step_run_id, status="completed", output_ref=ctx.blobs.put_model(model), output_hash=oh
                )
                hashes[spec.name.value] = oh
        original_heartbeat = engine._heartbeat
        owners = []

        def heartbeat(run_id, owner):
            owned = original_heartbeat(run_id, owner)
            owners.append(owner)
            with svc.store.tx() as tx:
                # Deterministic replacement for descheduling until the lease expires.
                tx.runs.update(run_id, lease_expires_at=utcnow() - timedelta(seconds=1))
                tx.runs.claim(run_id, "replacement-worker", 600)
            return owned

        engine._heartbeat = heartbeat
        result = await engine.run(ctx.run.run_id, "old-worker")
        rows = operations(ctx)
        results.append(
            {
                "repro": "engine_run_stale_worker_lease_adoption",
                "old_owner": owners[0],
                "final_owner": result.lease_owner,
                "run_status": result.status.value,
                "publication_state": rows[0]["state"],
                "destination_exists": Path(rows[0]["receipt"]["path"]).exists(),
            }
        )

        # Recovering an already-renamed publication becomes impossible after expiry.
        ctx = publication_context(svc)
        with patch.object(PublicationRepository, "complete", side_effect=RuntimeError("crash after rename")):
            try:
                publish_bundle(ctx)
            except RuntimeError:
                pass
        with svc.store.tx() as tx:
            tx.conn.execute(
                update(db.approvals)
                .where(db.approvals.c.run_id == ctx.run.run_id)
                .values(expires_at=utcnow() - timedelta(seconds=1))
            )
        recovery = cancel = "unexpected_success"
        try:
            publish_bundle(ctx)
        except ApprovalRequired:
            recovery = "ApprovalRequired"
        try:
            svc.cancel(REVIEWER, ctx.run.run_id, "audit")
        except Conflict:
            cancel = "Conflict"
        rows = operations(ctx)
        results.append(
            {
                "repro": "expiry_blocks_renamed_publication_recovery",
                "recovery": recovery,
                "cancel": cancel,
                "publication_state": rows[0]["state"],
                "destination_exists": Path(rows[0]["receipt"]["path"]).exists(),
            }
        )
    finally:
        svc.store.engine.dispose()
    report = {"temporary_root": str(root), "results": results}
    print(json.dumps(report, indent=2))
    (
        next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
        / "var"
        / "audit-2026-10-10"
        / "agent-02-repros.json"
    ).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    anyio.run(main)
