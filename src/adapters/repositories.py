"""Repositories and unit of work (POD-202, POD-203, POD-204).

Repositories accept and return domain models, never rows. A `Tx` is one database
transaction: a step's outputs, evidence, findings and audit events commit atomically.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, and_, func, insert, select, update

from src.adapters import db
from src.adapters.artifact_store import ArtifactStore
from src.domain.errors import NotFound
from src.domain.hashing import canonical_json, sha256_text
from src.domain.models import (
    AuditEvent,
    Confidence,
    Evidence,
    EvidenceRef,
    Finding,
    FindingStatus,
    FindingType,
    RunStatus,
    utcnow,
)
from src.domain.project_models import Approval, ItemDecision, ReviewItem


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class RunRecord(BaseModel):
    run_id: UUID
    project_type: str
    company_id: str
    connection_id: str
    status: RunStatus
    current_step: str | None = None
    gate: str | None = None
    stop_after: str | None = None
    requested_by: str
    pending_items: list[ReviewItem] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class StepRunRecord(BaseModel):
    step_run_id: int
    run_id: UUID
    step: str
    attempt: int
    status: str
    input_hash: str
    output_ref: str | None = None
    output_hash: str | None = None
    active: bool
    started_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None
    error_detail: str | None = None


# --------------------------------------------------------------------------- runs


class RunRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def create(
        self,
        *,
        company_id: str,
        connection_id: str,
        requested_by: str,
        project_type: str = "portco_onboarding",
        stop_after: str | None = None,
    ) -> RunRecord:
        now = utcnow()
        rec = RunRecord(
            run_id=uuid4(),
            project_type=project_type,
            company_id=company_id,
            connection_id=connection_id,
            status=RunStatus.PENDING,
            requested_by=requested_by,
            stop_after=stop_after,
            created_at=now,
            updated_at=now,
        )
        self.conn.execute(
            insert(db.workflow_runs).values(**rec.model_dump(exclude={"pending_items"}), pending_items=[])
        )
        return rec

    def get(self, run_id: UUID) -> RunRecord:
        row = self.conn.execute(select(db.workflow_runs).where(db.workflow_runs.c.run_id == run_id)).mappings().first()
        if row is None:
            raise NotFound(f"run {run_id} not found")
        data = dict(row)
        data["created_at"] = _aware(data["created_at"])
        data["updated_at"] = _aware(data["updated_at"])
        data["pending_items"] = [ReviewItem.model_validate(i) for i in (data["pending_items"] or [])]
        return RunRecord.model_validate(data)

    def list(self, company_ids: list[str] | None = None, limit: int = 50) -> list[RunRecord]:
        q = select(db.workflow_runs.c.run_id).order_by(db.workflow_runs.c.created_at.desc()).limit(limit)
        if company_ids is not None and "*" not in company_ids:
            q = q.where(db.workflow_runs.c.company_id.in_(company_ids))
        return [self.get(r) for r in self.conn.execute(q).scalars()]

    def update(self, run_id: UUID, **fields: Any) -> None:
        if "pending_items" in fields:
            fields["pending_items"] = [
                i.model_dump(mode="json") if isinstance(i, BaseModel) else i for i in fields["pending_items"]
            ]
        if "status" in fields and isinstance(fields["status"], RunStatus):
            fields["status"] = fields["status"].value
        fields["updated_at"] = utcnow()
        self.conn.execute(update(db.workflow_runs).where(db.workflow_runs.c.run_id == run_id).values(**fields))


# --------------------------------------------------------------------------- step runs


class StepRunRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def _rec(self, row: Any) -> StepRunRecord:
        data = dict(row)
        data["started_at"] = _aware(data["started_at"])
        data["finished_at"] = _aware(data["finished_at"])
        return StepRunRecord.model_validate(data)

    def start(self, run_id: UUID, step: str, input_hash: str) -> StepRunRecord:
        attempt = (
            self.conn.execute(
                select(func.max(db.step_runs.c.attempt)).where(
                    and_(db.step_runs.c.run_id == run_id, db.step_runs.c.step == step)
                )
            ).scalar()
            or 0
        ) + 1
        res = self.conn.execute(
            insert(db.step_runs).values(
                run_id=run_id,
                step=step,
                attempt=attempt,
                status="running",
                input_hash=input_hash,
                active=False,
                started_at=utcnow(),
            )
        )
        pk = res.inserted_primary_key
        assert pk is not None
        return self.get(int(pk[0]))

    def get(self, step_run_id: int) -> StepRunRecord:
        row = (
            self.conn.execute(select(db.step_runs).where(db.step_runs.c.step_run_id == step_run_id)).mappings().first()
        )
        if row is None:
            raise NotFound("step run not found")
        return self._rec(row)

    def finish(
        self,
        step_run_id: int,
        *,
        status: str,
        output_ref: str | None = None,
        output_hash: str | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        rec = self.get(step_run_id)
        if status in {"completed", "needs_review"}:
            # Supersede earlier outputs of the same step: only one active attempt per step.
            self.conn.execute(
                update(db.step_runs)
                .where(and_(db.step_runs.c.run_id == rec.run_id, db.step_runs.c.step == rec.step))
                .values(active=False)
            )
        self.conn.execute(
            update(db.step_runs)
            .where(db.step_runs.c.step_run_id == step_run_id)
            .values(
                status=status,
                output_ref=output_ref,
                output_hash=output_hash,
                error_code=error_code,
                error_detail=error_detail,
                finished_at=utcnow(),
                active=status in {"completed", "needs_review"},
            )
        )

    def reuse(self, step_run_id: int) -> None:
        rec = self.get(step_run_id)
        self.conn.execute(
            update(db.step_runs)
            .where(and_(db.step_runs.c.run_id == rec.run_id, db.step_runs.c.step == rec.step))
            .values(active=False)
        )
        self.conn.execute(update(db.step_runs).where(db.step_runs.c.step_run_id == step_run_id).values(active=True))

    def find_completed(self, run_id: UUID, step: str, input_hash: str) -> StepRunRecord | None:
        row = (
            self.conn.execute(
                select(db.step_runs)
                .where(
                    and_(
                        db.step_runs.c.run_id == run_id,
                        db.step_runs.c.step == step,
                        db.step_runs.c.input_hash == input_hash,
                        db.step_runs.c.status == "completed",
                    )
                )
                .order_by(db.step_runs.c.attempt.desc())
            )
            .mappings()
            .first()
        )
        return self._rec(row) if row else None

    def active(self, run_id: UUID, step: str) -> StepRunRecord | None:
        row = (
            self.conn.execute(
                select(db.step_runs).where(
                    and_(
                        db.step_runs.c.run_id == run_id,
                        db.step_runs.c.step == step,
                        db.step_runs.c.active.is_(True),
                    )
                )
            )
            .mappings()
            .first()
        )
        return self._rec(row) if row else None

    def deactivate(self, run_id: UUID, step: str) -> None:
        self.conn.execute(
            update(db.step_runs)
            .where(and_(db.step_runs.c.run_id == run_id, db.step_runs.c.step == step))
            .values(active=False)
        )

    def list(self, run_id: UUID) -> list[StepRunRecord]:
        rows = self.conn.execute(
            select(db.step_runs).where(db.step_runs.c.run_id == run_id).order_by(db.step_runs.c.step_run_id)
        ).mappings()
        return [self._rec(r) for r in rows]


# --------------------------------------------------------------------------- audit


class AuditRepository:
    """Append-only, hash-chained audit log. There is deliberately no update or delete."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    @staticmethod
    def _hash(prev: str | None, event: AuditEvent) -> str:
        body = canonical_json(
            {
                "run_id": str(event.run_id),
                "step": event.step,
                "actor": event.actor,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at.astimezone(UTC).isoformat(),
            }
        )
        return sha256_text((prev or "") + body)

    def append(self, event: AuditEvent) -> AuditEvent:
        prev = self.conn.execute(
            select(db.audit_events.c.event_hash)
            .where(db.audit_events.c.run_id == event.run_id)
            .order_by(db.audit_events.c.event_id.desc())
            .limit(1)
        ).scalar()
        event_hash = self._hash(prev, event)
        res = self.conn.execute(
            insert(db.audit_events).values(
                run_id=event.run_id,
                step=event.step,
                actor=event.actor,
                event_type=event.event_type,
                payload=event.payload,
                created_at=event.created_at,
                prev_hash=prev,
                event_hash=event_hash,
            )
        )
        pk = res.inserted_primary_key
        return event.model_copy(
            update={"event_id": int(pk[0]) if pk else None, "prev_hash": prev, "event_hash": event_hash}
        )

    def list(self, run_id: UUID) -> list[AuditEvent]:
        rows = self.conn.execute(
            select(db.audit_events).where(db.audit_events.c.run_id == run_id).order_by(db.audit_events.c.event_id)
        ).mappings()
        out = []
        for r in rows:
            data = dict(r)
            data["created_at"] = _aware(data["created_at"])
            out.append(AuditEvent.model_validate(data))
        return out

    def verify_chain(self, run_id: UUID) -> tuple[bool, str | None]:
        prev: str | None = None
        for ev in self.list(run_id):
            if ev.prev_hash != prev or self._hash(prev, ev) != ev.event_hash:
                return False, f"chain broken at event {ev.event_id}"
            prev = ev.event_hash
        return True, None


# --------------------------------------------------------------------------- evidence & findings


class EvidenceRepository:
    def __init__(self, conn: Connection, store: ArtifactStore) -> None:
        self.conn = conn
        self.store = store

    def save(
        self, run_id: UUID, ev: Evidence, step_run_id: int | None = None, derived_from: list[UUID] | None = None
    ) -> None:
        exists = self.conn.execute(
            select(db.evidence.c.evidence_id).where(db.evidence.c.evidence_id == ev.evidence_id)
        ).first()
        if exists:
            return
        ref = self.store.put_json(ev.payload)
        self.conn.execute(
            insert(db.evidence).values(
                evidence_id=ev.evidence_id,
                run_id=run_id,
                step_run_id=step_run_id,
                source_uri=ev.source_uri,
                source_type=ev.source_type,
                as_of=ev.as_of,
                retrieved_at=ev.retrieved_at,
                content_hash=ev.content_hash,
                payload_ref=ref,
                metadata={"derived_from": [str(d) for d in (derived_from or [])]},
            )
        )

    def get(self, evidence_id: UUID) -> tuple[Evidence, UUID, list[UUID]]:
        row = self.conn.execute(select(db.evidence).where(db.evidence.c.evidence_id == evidence_id)).mappings().first()
        if row is None:
            raise NotFound(f"evidence {evidence_id} not found")
        ev = Evidence(
            evidence_id=row["evidence_id"],
            source_uri=row["source_uri"],
            source_type=row["source_type"],
            as_of=_aware(row["as_of"]),
            retrieved_at=_aware(row["retrieved_at"]),
            content_hash=row["content_hash"],
            payload=self.store.get_json(row["payload_ref"]),
        )
        derived = [UUID(d) for d in (row["metadata"] or {}).get("derived_from", [])]
        return ev, row["run_id"], derived

    def exists(self, evidence_id: UUID) -> bool:
        return (
            self.conn.execute(select(db.evidence.c.evidence_id).where(db.evidence.c.evidence_id == evidence_id)).first()
            is not None
        )


class FindingRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def save(self, run_id: UUID, step: str, finding: Finding, step_run_id: int | None = None) -> None:
        self.conn.execute(
            insert(db.findings).values(
                finding_id=finding.finding_id,
                run_id=run_id,
                step_run_id=step_run_id,
                step=step,
                code=finding.code,
                finding_type=finding.finding_type.value,
                title=finding.title,
                statement=finding.statement,
                confidence=finding.confidence.value,
                status=finding.status.value,
                assumptions=finding.assumptions,
                metadata={**finding.metadata, "evidence": [e.model_dump(mode="json") for e in finding.evidence]},
                created_at=utcnow(),
            )
        )
        for ref in finding.evidence:
            self.link(finding.finding_id, UUID(ref.source_id), "supports")

    def link(self, finding_id: UUID, evidence_id: UUID, relation: str) -> None:
        self.conn.execute(
            insert(db.finding_evidence).values(finding_id=finding_id, evidence_id=evidence_id, relation=relation)
        )

    def _to_model(self, row: Any) -> Finding:
        meta = dict(row["metadata"] or {})
        refs = [EvidenceRef.model_validate(e) for e in meta.pop("evidence", [])]
        return Finding(
            finding_id=row["finding_id"],
            code=row["code"],
            finding_type=FindingType(row["finding_type"]),
            title=row["title"],
            statement=row["statement"],
            confidence=Confidence(row["confidence"]),
            status=FindingStatus(row["status"]),
            evidence=refs,
            assumptions=row["assumptions"] or [],
            metadata={**meta, "step": row["step"]},
        )

    def current(self, run_id: UUID, code: str | None = None) -> list[Finding]:
        """Findings produced by the active attempt of each step."""
        q = (
            select(db.findings)
            .join(db.step_runs, db.findings.c.step_run_id == db.step_runs.c.step_run_id)
            .where(and_(db.findings.c.run_id == run_id, db.step_runs.c.active.is_(True)))
            .order_by(db.findings.c.created_at, db.findings.c.code)
        )
        if code:
            q = q.where(db.findings.c.code == code)
        return [self._to_model(r) for r in self.conn.execute(q).mappings()]

    def get(self, finding_id: UUID) -> tuple[Finding, UUID]:
        row = self.conn.execute(select(db.findings).where(db.findings.c.finding_id == finding_id)).mappings().first()
        if row is None:
            raise NotFound(f"finding {finding_id} not found")
        return self._to_model(row), row["run_id"]

    def evidence_links(self, finding_id: UUID) -> list[tuple[UUID, str]]:
        rows = self.conn.execute(select(db.finding_evidence).where(db.finding_evidence.c.finding_id == finding_id))
        return [(r.evidence_id, r.relation) for r in rows]


# --------------------------------------------------------------------------- artifacts (metadata)


class ArtifactRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def record(self, run_id: UUID, kind: str, content_hash: str, step_run_id: int | None) -> UUID:
        artifact_id = uuid4()
        self.conn.execute(
            insert(db.artifacts).values(
                artifact_id=artifact_id,
                run_id=run_id,
                step_run_id=step_run_id,
                kind=kind,
                content_hash=content_hash,
                uri=f"artifact://{content_hash}",
                schema_version="1",
                created_at=utcnow(),
            )
        )
        return artifact_id


# --------------------------------------------------------------------------- approvals


class ApprovalRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def insert(self, approval: Approval) -> None:
        self.conn.execute(
            insert(db.approvals).values(
                approval_id=approval.approval_id,
                run_id=approval.run_id,
                gate=approval.gate.value,
                subject_hash=approval.subject_hash,
                decisions=[d.model_dump(mode="json") for d in approval.decisions],
                reviewer=approval.reviewer,
                role=approval.role,
                comment=approval.comment,
                created_at=approval.created_at,
                expires_at=approval.expires_at,
            )
        )

    def _to_model(self, row: Any) -> Approval:
        return Approval(
            approval_id=row["approval_id"],
            run_id=row["run_id"],
            gate=row["gate"],
            subject_hash=row["subject_hash"],
            decisions=[ItemDecision.model_validate(d) for d in row["decisions"]],
            reviewer=row["reviewer"],
            role=row["role"],
            comment=row["comment"],
            created_at=_aware(row["created_at"]),
            expires_at=_aware(row["expires_at"]),
            revoked_at=_aware(row["revoked_at"]),
            revoked_reason=row["revoked_reason"],
        )

    def get(self, approval_id: UUID) -> Approval:
        row = (
            self.conn.execute(select(db.approvals).where(db.approvals.c.approval_id == approval_id)).mappings().first()
        )
        if row is None:
            raise NotFound(f"approval {approval_id} not found")
        return self._to_model(row)

    def for_run(self, run_id: UUID, gate: str | None = None) -> list[Approval]:
        q = select(db.approvals).where(db.approvals.c.run_id == run_id).order_by(db.approvals.c.created_at)
        if gate:
            q = q.where(db.approvals.c.gate == gate)
        return [self._to_model(r) for r in self.conn.execute(q).mappings()]

    def revoke(self, approval_id: UUID, reason: str) -> None:
        self.conn.execute(
            update(db.approvals)
            .where(and_(db.approvals.c.approval_id == approval_id, db.approvals.c.revoked_at.is_(None)))
            .values(revoked_at=utcnow(), revoked_reason=reason)
        )


# --------------------------------------------------------------------------- publications


class PublicationRepository:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def by_hash(self, company_id: str, manifest_hash: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            select(db.publications.c.receipt).where(
                and_(db.publications.c.company_id == company_id, db.publications.c.manifest_hash == manifest_hash)
            )
        ).first()
        return dict(row[0]) if row else None

    def next_version(self, company_id: str) -> str:
        n = (
            self.conn.execute(
                select(func.count()).select_from(db.publications).where(db.publications.c.company_id == company_id)
            ).scalar()
            or 0
        )
        return f"v{n + 1:04d}"

    def insert(self, company_id: str, manifest_hash: str, version: str, run_id: UUID, receipt: dict[str, Any]) -> None:
        self.conn.execute(
            insert(db.publications).values(
                publication_id=uuid4(),
                company_id=company_id,
                manifest_hash=manifest_hash,
                version=version,
                run_id=run_id,
                receipt=receipt,
                created_at=utcnow(),
            )
        )


# --------------------------------------------------------------------------- unit of work


class Tx:
    def __init__(self, conn: Connection, store: ArtifactStore) -> None:
        self.conn = conn
        self.blobs = store
        self.runs = RunRepository(conn)
        self.steps = StepRunRepository(conn)
        self.audit = AuditRepository(conn)
        self.evidence = EvidenceRepository(conn, store)
        self.findings = FindingRepository(conn)
        self.artifacts = ArtifactRepository(conn)
        self.approvals = ApprovalRepository(conn)
        self.publications = PublicationRepository(conn)


class Store:
    def __init__(self, engine: Engine, blobs: ArtifactStore) -> None:
        self.engine = engine
        self.blobs = blobs

    @contextmanager
    def tx(self) -> Iterator[Tx]:
        with self.engine.begin() as conn:
            yield Tx(conn, self.blobs)

    def create_schema(self) -> None:
        db.metadata.create_all(self.engine)
