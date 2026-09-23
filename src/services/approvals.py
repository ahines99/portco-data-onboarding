"""Approval primitive bound to content hashes (POD-701, ADR-0004, ADR-0009).

- Only reviewer/admin principals may record decisions, never the principal that started the run
  (when `require_distinct_reviewer` is on).
- Every approval is bound to the subject's content hash. Any change to the subject makes the
  approval stale; stale approvals are revoked, never edited or deleted.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from src.adapters.repositories import RunRecord, Tx
from src.domain.errors import ApprovalRequired, Conflict, Forbidden, ValidationFailed
from src.domain.models import AuditEvent, Principal, ReviewDecision, ReviewGate, RunStatus, utcnow
from src.domain.policies import check_action
from src.domain.project_models import Approval, ItemDecision, ReviewItem
from src.settings import Settings

ACTION_FOR_GATE = {
    ReviewGate.MAPPING_REVIEW: "submit_review",
    ReviewGate.TEST_FAILURES: "waive_test_failures",
    ReviewGate.CERTIFICATION: "certify",
}


def is_valid(approval: Approval, subject_hash: str | None = None, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if approval.revoked_at is not None:
        return False
    if approval.expires_at is not None and approval.expires_at <= now:
        return False
    return subject_hash is None or approval.subject_hash == subject_hash


def effective_decisions(approvals: list[Approval], gate: ReviewGate, subject_hash: str) -> dict[str, ItemDecision]:
    """Latest valid decision per item for this gate and subject."""
    out: dict[str, ItemDecision] = {}
    for a in sorted(approvals, key=lambda a: a.created_at):
        if a.gate == gate and is_valid(a, subject_hash):
            for d in a.decisions:
                out[d.item_key] = d
    return out


def _validate_override(item: ReviewItem, decision: ItemDecision) -> None:
    if decision.decision is not ReviewDecision.APPROVE_WITH_OVERRIDE:
        return
    if item.kind != "mapping":
        raise ValidationFailed(f"overrides are only supported for mapping items ({item.item_key})")
    override = decision.override or {}
    unknown = set(override) - {"canonical_field", "transform", "pii_handling"}
    if unknown:
        raise ValidationFailed(f"unsupported override keys: {sorted(unknown)}")
    allowed = set(item.options.get("allowed_fields", []))
    if "canonical_field" in override and override["canonical_field"] not in allowed:
        raise ValidationFailed(f"{override['canonical_field']!r} is not a field of this entity")
    if override.get("transform") not in {None, "cents_to_major", "parse_mixed_date"}:
        raise ValidationFailed("unsupported transform")
    if override.get("pii_handling") not in {None, "hash", "exclude"}:
        raise ValidationFailed("unsupported pii_handling")


def record(
    tx: Tx,
    settings: Settings,
    principal: Principal,
    run: RunRecord,
    gate: ReviewGate,
    subject_hash: str,
    decisions: list[ItemDecision],
    comment: str | None = None,
) -> Approval:
    decision = check_action(ACTION_FOR_GATE[gate], role=principal.role)
    if not decision.allowed:
        _deny(tx, run, principal, ACTION_FOR_GATE[gate], decision.reason)
        raise Forbidden(decision.reason)
    if not principal.can_access(run.company_id):
        _deny(tx, run, principal, ACTION_FOR_GATE[gate], "principal is not scoped to this company")
        raise Forbidden("principal is not scoped to this company")
    if settings.require_distinct_reviewer and principal.principal_id == run.requested_by:
        _deny(tx, run, principal, ACTION_FOR_GATE[gate], "reviewer started this run")
        raise Forbidden("the principal that started a run cannot approve it (separation of duties)")
    if run.status is not RunStatus.NEEDS_REVIEW or run.gate != gate.value:
        raise Conflict(f"run is not waiting at gate {gate.value}")
    pending = {i.item_key: i for i in run.pending_items}
    if not pending or next(iter(pending.values())).subject_hash != subject_hash:
        raise Conflict("subject hash does not match the item under review; re-read the pending items")
    if not decisions:
        raise ValidationFailed("no decisions supplied")
    for d in decisions:
        if d.item_key not in pending:
            raise ValidationFailed(f"unknown review item {d.item_key!r}")
        _validate_override(pending[d.item_key], d)
    approval = Approval(
        run_id=run.run_id,
        gate=gate,
        subject_hash=subject_hash,
        decisions=decisions,
        reviewer=principal.principal_id,
        role=principal.role.value,
        comment=comment,
        expires_at=utcnow() + timedelta(hours=settings.approval_ttl_hours),
    )
    tx.approvals.insert(approval)
    tx.audit.append(
        AuditEvent(
            run_id=run.run_id,
            step=run.current_step or "",
            actor=principal.principal_id,
            event_type="approval_recorded",
            payload={
                "approval_id": str(approval.approval_id),
                "gate": gate.value,
                "subject_hash": subject_hash,
                "items": len(decisions),
                "decisions": sorted({d.decision.value for d in decisions}),
            },
        )
    )
    return approval


def verify(tx: Tx, approval_id: UUID, gate: ReviewGate, subject_hash: str) -> Approval:
    try:
        approval = tx.approvals.get(approval_id)
    except Exception as exc:
        raise ApprovalRequired("approval not found") from exc
    if approval.gate != gate:
        raise ApprovalRequired(f"approval is for gate {approval.gate}, not {gate.value}")
    if not is_valid(approval):
        raise ApprovalRequired("approval is revoked or expired")
    if approval.subject_hash != subject_hash:
        raise ApprovalRequired("approval was granted for different content; the subject has changed since")
    return approval


def revoke_stale(tx: Tx, run_id: UUID, gate: ReviewGate, current_hash: str, actor: str = "system") -> list[UUID]:
    revoked = []
    for a in tx.approvals.for_run(run_id, gate.value):
        if a.revoked_at is None and a.subject_hash != current_hash:
            tx.approvals.revoke(a.approval_id, "subject changed")
            revoked.append(a.approval_id)
            tx.audit.append(
                AuditEvent(
                    run_id=run_id,
                    step=gate.value,
                    actor=actor,
                    event_type="approval_invalidated",
                    payload={
                        "approval_id": str(a.approval_id),
                        "old_subject": a.subject_hash,
                        "new_subject": current_hash,
                    },
                )
            )
    return revoked


def _deny(tx: Tx, run: RunRecord, principal: Principal, action: str, reason: str) -> None:
    tx.audit.append(
        AuditEvent(
            run_id=run.run_id,
            step=run.current_step or "",
            actor=principal.principal_id,
            event_type="policy_denied",
            payload={"action": action, "reason": reason},
        )
    )
