"""Publication crash boundaries, authorization freshness and execution fencing."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path, PureWindowsPath
from threading import Barrier
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import update

from src.adapters import db
from src.domain.errors import ApprovalRequired, Conflict, LeaseLost, PolicyViolation
from src.domain.models import AuditEvent, ReviewDecision, ReviewGate, RunStatus, StepName, utcnow
from src.domain.project_models import (
    Approval,
    ArtifactBundle,
    ArtifactFile,
    CertificationPacket,
    ItemDecision,
    MetricCertification,
)
from src.services.publish import _contained, publish_bundle
from src.workflows.contracts import StepContext
from tests.conftest import REVIEWER

pytestmark = pytest.mark.unit


def publication_context(service):
    with service.store.tx() as tx:
        run = tx.runs.create(
            company_id=f"pub_{uuid4().hex[:8]}", connection_id="fixture:portco_a", requested_by="agent"
        )
        _, run = tx.runs.claim(run.run_id, "worker", 600)
        tx.runs.update(run.run_id, current_step=StepName.PUBLISH.value)
        run = tx.runs.get(run.run_id)
    data = b"select 1\n"
    sha = service.store.blobs.put_bytes(data)
    bundle = ArtifactBundle(
        mapping_hash="mapping",
        files=[ArtifactFile(path="models/model.sql", sha256=sha, kind="sql", size=len(data))],
        manifest_hash="manifest",
        generated_metrics=["billings"],
    )
    packet = CertificationPacket(
        run_id=run.run_id,
        manifest_hash="manifest",
        mapping_hash="mapping",
        joins=[],
        mapping_summary={},
        reviewer_overrides=[],
        metrics=[
            MetricCertification(metric="billings", description="Billings", formula="sum(amount)", status="generated")
        ],
        test_report_passed=True,
        failing_checks=[],
        waived_checks=[],
        open_findings=[],
        evidence_ids=[],
        certified_metrics=["billings"],
    )
    approvals = [
        Approval(
            run_id=run.run_id,
            gate=ReviewGate.CERTIFICATION,
            subject_hash=packet.review_hash(),
            decisions=[ItemDecision(item_key=key, decision=ReviewDecision.APPROVE)],
            reviewer="reviewer",
            role="reviewer",
            expires_at=utcnow() + timedelta(hours=1),
        )
        for key in ("bundle:manifest", "metric:billings")
    ]
    packet.certification_ids = sorted([a.approval_id for a in approvals], key=str)
    with service.store.tx() as tx:
        for a in approvals:
            tx.approvals.insert(a)
    return StepContext(
        run=run,
        settings=service.settings,
        ontology=service.engine.ontology,
        blobs=service.store.blobs,
        store=service.store,
        open_adapter=lambda: service.connections.open("fixture:portco_a"),
        upstream={StepName.ARTIFACT_GENERATION: bundle, StepName.HUMAN_CERTIFICATION: packet},
        approvals=approvals,
    )


def operations(ctx):
    with ctx.store.tx() as tx:
        return list(
            tx.conn.execute(
                db.publications.select().where(db.publications.c.company_id == ctx.run.company_id)
            ).mappings()
        )


def test_rename_failure_is_recovered_using_same_version(service, monkeypatch):
    ctx = publication_context(service)
    rename = Path.rename
    with monkeypatch.context() as m:
        m.setattr(Path, "rename", lambda *args: (_ for _ in ()).throw(OSError("injected")))
        with pytest.raises(OSError):
            publish_bundle(ctx)
    assert operations(ctx)[0]["state"] == "prepared"
    receipt = publish_bundle(ctx).output
    assert receipt.version == "v0001" and not receipt.reused
    assert Path(receipt.path, "models/model.sql").read_bytes() == b"select 1\n"
    assert operations(ctx)[0]["state"] == "complete"
    assert publish_bundle(ctx).output.reused
    assert Path.rename is rename


def test_crash_after_rename_before_db_commit_recovers(service, monkeypatch):
    from src.adapters.repositories import PublicationRepository

    ctx = publication_context(service)
    with monkeypatch.context() as m:
        m.setattr(PublicationRepository, "complete", lambda *a: (_ for _ in ()).throw(RuntimeError("crash")))
        with pytest.raises(RuntimeError):
            publish_bundle(ctx)
    row = operations(ctx)[0]
    assert row["state"] == "prepared" and Path(row["receipt"]["path"]).exists()
    assert publish_bundle(ctx).output.version == "v0001"
    assert len(operations(ctx)) == 1 and operations(ctx)[0]["state"] == "complete"


@pytest.mark.parametrize("boundary", ["reservation", "staging"])
def test_failures_before_finalization_never_create_a_successful_receipt(service, monkeypatch, boundary):
    from src.adapters.repositories import PublicationRepository

    ctx = publication_context(service)
    with monkeypatch.context() as m:
        if boundary == "reservation":
            original = PublicationRepository.insert

            def fail(repository, *args, **kwargs):
                original(repository, *args, **kwargs)
                raise OSError("reservation interrupted before commit")

            m.setattr(PublicationRepository, "insert", fail)
        else:
            m.setattr(Path, "write_bytes", lambda *a: (_ for _ in ()).throw(OSError("staging interrupted")))
        with pytest.raises(OSError):
            publish_bundle(ctx)
    assert all(row["state"] == "prepared" for row in operations(ctx))
    assert not list(ctx.settings.published_root.rglob("model.sql"))
    assert publish_bundle(ctx).output.version == "v0001"


def test_approval_revocation_during_staging_is_rechecked_at_finalization(service, monkeypatch):
    ctx = publication_context(service)
    original = Path.write_bytes

    def write(path, data):
        result = original(path, data)
        with ctx.store.tx() as tx:
            tx.approvals.revoke(ctx.approvals[1].approval_id, "withdrawn during staging")
        return result

    monkeypatch.setattr(Path, "write_bytes", write)
    with pytest.raises(ApprovalRequired):
        publish_bundle(ctx)
    assert operations(ctx)[0]["state"] == "prepared"
    assert not Path(operations(ctx)[0]["receipt"]["path"]).exists()


@pytest.mark.parametrize("damage", ["missing", "modified", "extra"])
def test_completed_receipt_never_hides_filesystem_damage(service, damage):
    ctx = publication_context(service)
    receipt = publish_bundle(ctx).output
    path = Path(receipt.path, "models/model.sql")
    if damage == "missing":
        path.unlink()
    elif damage == "modified":
        path.write_text("tampered")
    else:
        Path(receipt.path, "unexpected.txt").write_text("extra")
    with pytest.raises(PolicyViolation):
        publish_bundle(ctx)


@pytest.mark.parametrize("change", ["expired", "revoked", "rejected"])
def test_separate_metric_approval_is_reloaded_before_publish(service, change):
    ctx = publication_context(service)
    approval = ctx.approvals[1]
    with ctx.store.tx() as tx:
        if change == "revoked":
            tx.approvals.revoke(approval.approval_id, "withdrawn")
        elif change == "expired":
            tx.conn.execute(
                update(db.approvals)
                .where(db.approvals.c.approval_id == approval.approval_id)
                .values(expires_at=utcnow() - timedelta(seconds=1))
            )
        else:
            tx.approvals.insert(
                approval.model_copy(
                    update={
                        "approval_id": uuid4(),
                        "created_at": utcnow(),
                        "decisions": [ItemDecision(item_key="metric:billings", decision=ReviewDecision.REJECT)],
                    }
                )
            )
    with pytest.raises(ApprovalRequired):
        publish_bundle(ctx)
    assert not operations(ctx)


@pytest.mark.parametrize("fence", ["cancel", "lease", "timeout"])
def test_staged_worker_cannot_publish_after_losing_authority(service, monkeypatch, fence):
    ctx = publication_context(service)
    original = Path.write_bytes
    fired = False

    def write(path, data):
        nonlocal fired
        result = original(path, data)
        if not fired:
            fired = True
            if fence == "timeout":
                ctx.execution_deadline = monotonic() - 1
            else:
                with ctx.store.tx() as tx:
                    tx.runs.update(
                        ctx.run.run_id,
                        **({"status": RunStatus.CANCELLED} if fence == "cancel" else {"lease_owner": "new-worker"}),
                    )
        return result

    monkeypatch.setattr(Path, "write_bytes", write)
    with pytest.raises(LeaseLost):
        publish_bundle(ctx)
    assert operations(ctx)[0]["state"] == "prepared"
    assert not Path(operations(ctx)[0]["receipt"]["path"]).exists()


def test_timeout_during_rename_removes_uncommitted_destination(service, monkeypatch):
    ctx = publication_context(service)
    original = Path.rename

    def rename(path, dest):
        result = original(path, dest)
        ctx.execution_deadline = monotonic() - 1
        return result

    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(LeaseLost):
        publish_bundle(ctx)
    assert not Path(operations(ctx)[0]["receipt"]["path"]).exists()


def test_cancellation_after_finalization_before_step_persistence_is_rejected(service):
    ctx = publication_context(service)
    publish_bundle(ctx)
    with pytest.raises(Conflict, match="finalized"):
        service.cancel(REVIEWER, ctx.run.run_id, "too late")
    with ctx.store.tx() as tx:
        assert tx.runs.get(ctx.run.run_id).status is RunStatus.RUNNING


def test_cancellation_of_rerun_before_publish_preserves_historical_publication(service):
    ctx = publication_context(service)
    receipt = publish_bundle(ctx).output
    with ctx.store.tx() as tx:
        tx.runs.update(ctx.run.run_id, status=RunStatus.COMPLETE, current_step=None)
        tx.runs.update(ctx.run.run_id, status=RunStatus.PENDING, current_step=StepName.SCHEMA_PROFILING.value)
        tx.runs.release(ctx.run.run_id, "worker")
        tx.runs.claim(ctx.run.run_id, "rerun-worker", 600)
    cancelled = service.cancel(REVIEWER, ctx.run.run_id, "stop the new profiling attempt")
    assert cancelled.status is RunStatus.CANCELLED
    assert Path(receipt.path, "models/model.sql").read_bytes() == b"select 1\n"
    assert operations(ctx)[0]["state"] == "complete"


@pytest.mark.parametrize("path", ["../escape.sql", "/absolute.sql", "C:\\escape.sql", "..\\escape.sql"])
def test_publication_contains_bundle_paths(service, path):
    ctx = publication_context(service)
    ctx.upstream[StepName.ARTIFACT_GENERATION].files[0].path = path
    with pytest.raises(PolicyViolation):
        publish_bundle(ctx)
    assert not list(ctx.settings.published_root.rglob("*.sql"))


@pytest.mark.parametrize(
    ("resolved_root", "resolved_target"),
    [
        (r"C:\published\company", r"\\?\C:\published\company\v0001"),
        (r"\\?\C:\published\company", r"C:\published\company\v0001"),
        (r"\\server\share\company", r"\\?\UNC\server\share\company\v0001"),
        (r"\\?\UNC\server\share\company", r"\\server\share\company\v0001"),
    ],
)
def test_windows_extended_resolution_spelling_preserves_containment(
    tmp_path, monkeypatch, resolved_root, resolved_target
):
    # Simulate realpath's two spellings without depending on a rare directory-creation race.
    root = tmp_path / "company"
    target = root / "v0001"
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path: PureWindowsPath(resolved_root if path == root else resolved_target),
    )
    assert _contained(root, "v0001") == target


@pytest.mark.parametrize("symlink", [False, True])
def test_windows_extended_resolution_does_not_allow_escape_or_symlink(tmp_path, monkeypatch, symlink):
    root = tmp_path / "company"
    target = root / "v0001"
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path: PureWindowsPath(
            r"C:\published\company"
            if path == root
            else (r"\\?\C:\published\company\v0001" if symlink else r"\\?\C:\outside\v0001")
        ),
    )
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target and symlink)
    with pytest.raises(PolicyViolation, match="escapes"):
        _contained(root, "v0001")


def test_concurrent_publication_finalizers_share_one_verified_receipt(service):
    ctx = publication_context(service)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: publish_bundle(ctx).output, range(2)))
    assert len(operations(ctx)) == 1
    assert {r.version for r in receipts} == {"v0001"}
    assert sorted(r.reused for r in receipts) == [False, True]


def test_concurrent_audit_appends_do_not_fork_sqlite_chain(service):
    ctx = publication_context(service)
    barrier = Barrier(8)

    def append(index):
        barrier.wait()
        with ctx.store.tx() as tx:
            # Prior reads used to allow two appenders to observe the same head.
            tx.runs.get(ctx.run.run_id)
            for j in range(4):
                tx.audit.append(
                    AuditEvent(
                        run_id=ctx.run.run_id, step="audit", actor=str(index), event_type="concurrent", payload={"j": j}
                    )
                )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(8)))
    with ctx.store.tx() as tx:
        assert len(tx.audit.list(ctx.run.run_id)) == 32
        assert tx.audit.verify_chain(ctx.run.run_id) == (True, None)
