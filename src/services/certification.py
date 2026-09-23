"""Step 8 — human certification (POD-309). Gate B always runs before publish.

Review items: the bundle itself (`bundle:<manifest>`) plus one item per generated metric.
The certification subject is the bundle manifest hash, so any regeneration invalidates it.
Rejecting a metric excludes it (and every metric derived from it) from publication.
Rejecting the bundle fails the run: the fix is a mapping change and `rerun_from`.
"""

from __future__ import annotations

from uuid import UUID

from src.domain.errors import ValidationFailed
from src.domain.models import Confidence, Finding, FindingType, ReviewDecision, ReviewGate, StepName
from src.domain.project_models import (
    ArtifactBundle,
    CertificationPacket,
    MetricCertification,
    ResolvedMapping,
    ReviewItem,
    TestReport,
)
from src.services.approvals import effective_decisions
from src.workflows.contracts import StepContext, StepResult, make_evidence

OPEN_FINDING_CODES = {
    "STALE_DATA",
    "DUPLICATE_ENTITIES",
    "ORPHAN_KEYS",
    "MULTI_CURRENCY",
    "INJECTION_FLAGGED",
    "UNMAPPED_REQUIRED",
    "METRIC_NEEDS_EVIDENCE",
    "MIXED_TYPES",
    "CONFLICT",
    "ENTITY_OVERLAP",
    "POSSIBLE_MINOR_UNITS",
    "EMPTY_TABLE",
}


def build_packet(ctx: StepContext) -> CertificationPacket:
    bundle = ctx.get(StepName.ARTIFACT_GENERATION, ArtifactBundle)
    resolved = ctx.get(StepName.MAPPING_REVIEW, ResolvedMapping)
    report = ctx.get(StepName.AUTOMATED_TESTS, TestReport)
    metrics = []
    for name, mdef in sorted(ctx.ontology.metrics.items()):
        if name in bundle.generated_metrics:
            status, reason = "generated", None
        elif bundle.not_generated.get(name, "").startswith("reference_only"):
            status, reason = "reference_only", bundle.not_generated[name]
        else:
            status, reason = "not_generated", bundle.not_generated.get(name, "not generated")
        metrics.append(
            MetricCertification(
                metric=name, description=mdef.description, formula=mdef.formula, status=status, reason=reason
            )
        )
    with ctx.store.tx() as tx:
        current = tx.findings.current(ctx.run.run_id)
    open_findings = sorted(
        (
            {"code": f.code, "title": f.title, "confidence": f.confidence.value, "status": f.status.value}
            for f in current
            if f.code in OPEN_FINDING_CODES
        ),
        key=lambda d: (d["code"], d["title"]),
    )
    evidence_ids = sorted({ev_id for f in current for ev_id in [e.source_id for e in f.evidence]})
    return CertificationPacket(
        run_id=ctx.run.run_id,
        manifest_hash=bundle.manifest_hash,
        mapping_hash=resolved.mapping_hash,
        joins=resolved.joins,
        mapping_summary={
            "accepted": len(resolved.accepted),
            "auto": sum(a.decided_by == "auto" for a in resolved.accepted),
            "reviewed": sum(a.decided_by == "reviewer" for a in resolved.accepted),
            "overridden": sum(a.overridden for a in resolved.accepted),
            "rejected": len(resolved.rejected_keys),
        },
        reviewer_overrides=sorted(
            f"{a.source_table}.{a.source_column} -> {a.canonical_entity}.{a.canonical_field}"
            for a in resolved.accepted
            if a.overridden
        ),
        metrics=metrics,
        test_report_passed=report.passed,
        failing_checks=report.failing_checks,
        waived_checks=report.waived_checks,
        open_findings=open_findings,
        evidence_ids=[UUID(e) for e in evidence_ids],
    )


def human_certification(ctx: StepContext) -> StepResult:
    packet = build_packet(ctx)
    subject = packet.manifest_hash
    items = [
        ReviewItem(
            item_key=f"bundle:{subject}",
            gate=ReviewGate.CERTIFICATION,
            kind="bundle",
            summary=(
                f"Certify bundle {subject[:12]}: {packet.mapping_summary['accepted']} mappings, "
                f"{len(packet.joins)} joins, tests {'passed' if packet.test_report_passed else 'waived'}"
            ),
            reason_codes=["CERTIFICATION"],
            subject_hash=subject,
        )
    ]
    items += [
        ReviewItem(
            item_key=f"metric:{m.metric}",
            gate=ReviewGate.CERTIFICATION,
            kind="metric",
            summary=f"Certify metric {m.metric}: {m.formula}",
            reason_codes=["METRIC_CERTIFICATION"],
            subject_hash=subject,
        )
        for m in packet.metrics
        if m.status == "generated"
    ]
    decisions = effective_decisions(ctx.approvals, ReviewGate.CERTIFICATION, subject)
    bundle_decision = decisions.get(f"bundle:{subject}")
    if bundle_decision is not None and bundle_decision.decision is ReviewDecision.REJECT:
        raise ValidationFailed("reviewer rejected the bundle; change the mapping and rerun from canonical_mapping")
    pending = [i for i in items if i.item_key not in decisions]
    payload = packet.model_dump(mode="json")
    ev = make_evidence(ctx, f"certification://{ctx.run.run_id}/{subject[:16]}", "certification_packet", payload)
    if pending:
        return StepResult(
            status="needs_review",
            output=packet,
            evidence=[ev],
            gate=ReviewGate.CERTIFICATION,
            pending_items=pending,
            subject_hash=subject,
            audit=[("certification_requested", {"manifest_hash": subject, "items": len(pending)})],
        )
    rejected = sorted(
        k.removeprefix("metric:")
        for k, d in decisions.items()
        if k.startswith("metric:") and d.decision is ReviewDecision.REJECT
    )
    certified = sorted(m.metric for m in packet.metrics if m.status == "generated" and m.metric not in rejected)
    findings = [
        Finding(
            code="CERTIFIED",
            title="Bundle certified by a human reviewer",
            finding_type=FindingType.OBSERVATION,
            statement=f"{len(certified)} metrics certified, {len(rejected)} rejected; bundle {subject[:12]}.",
            confidence=Confidence.HIGH,
            evidence=[ev.ref()],
            metadata={"certified": certified, "rejected": rejected},
        )
    ]
    return StepResult(
        output=packet,
        evidence=[ev],
        findings=findings,
        subject_hash=subject,
        audit=[("certified", {"manifest_hash": subject, "certified": certified, "rejected": rejected})],
    )
