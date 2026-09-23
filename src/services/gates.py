"""Gate A — mapping review (ADR-0005). Pure: reads approvals, never writes them."""

from __future__ import annotations

from collections import Counter
from typing import Any

from src.domain.models import Confidence, Finding, FindingType, ReviewDecision, ReviewGate, StepName
from src.domain.project_models import (
    AcceptedMapping,
    ItemDecision,
    MappingSet,
    ResolvedMapping,
    ReviewItem,
)
from src.services.approvals import effective_decisions
from src.workflows.contracts import StepContext, StepResult, make_evidence


def review_items(ms: MappingSet, ctx: StepContext) -> list[ReviewItem]:
    h = ms.content_hash()
    items: list[ReviewItem] = []
    for p in ms.proposals:
        if not p.requires_review:
            continue
        note = f" (suggest {p.suggested_transform})" if p.suggested_transform else ""
        items.append(
            ReviewItem(
                item_key=f"mapping:{p.mapping_key}",
                gate=ReviewGate.MAPPING_REVIEW,
                kind="mapping",
                summary=f"{p.source_field} -> {p.canonical_entity}.{p.canonical_field}{note}",
                reason_codes=p.reason_codes,
                subject_hash=h,
                evidence_ids=p.evidence_ids,
                options={
                    "proposed": p.canonical_field,
                    "confidence": p.confidence.value,
                    "score": p.score,
                    "alternatives": [a.field for a in p.alternatives],
                    "allowed_fields": sorted(ctx.ontology.entities[p.canonical_entity].fields),
                    "suggested_transform": p.suggested_transform,
                    "pii_handling": p.pii_handling,
                },
            )
        )
    for f in ms.row_filters:
        if f.requires_review:
            desc = "rows where flag is true" if f.kind == "exclude_true" else f"rows starting with {f.value!r}"
            items.append(
                ReviewItem(
                    item_key=f"filter:{f.filter_key}",
                    gate=ReviewGate.MAPPING_REVIEW,
                    kind="row_filter",
                    summary=f"Exclude {desc} in {f.table}.{f.column} ({f.affected_rows} rows)",
                    reason_codes=["ROW_FILTER"],
                    subject_hash=h,
                    evidence_ids=f.evidence_ids,
                )
            )
    for j in ms.joins:
        if j.requires_review:
            items.append(
                ReviewItem(
                    item_key=f"join:{j.join_id}",
                    gate=ReviewGate.MAPPING_REVIEW,
                    kind="join",
                    summary=(
                        f"{j.join_id} ({j.cardinality}, containment {j.containment_ratio:.1%}, "
                        f"orphans {j.orphan_rate:.1%})"
                    ),
                    reason_codes=j.reason_codes,
                    subject_hash=h,
                    evidence_ids=[j.evidence_id] if j.evidence_id else [],
                )
            )
    return items


def resolve(ms: MappingSet, decisions: dict[str, ItemDecision]) -> tuple[ResolvedMapping, list[str]]:
    accepted: list[AcceptedMapping] = []
    rejected: list[str] = []
    for p in ms.proposals:
        key = f"mapping:{p.mapping_key}"
        if not p.requires_review:
            accepted.append(
                AcceptedMapping(
                    source_table=p.source_table,
                    source_column=p.source_column,
                    canonical_entity=p.canonical_entity,
                    canonical_field=p.canonical_field,
                    transform=p.suggested_transform,
                    pii_handling=p.pii_handling,
                    decided_by="auto",
                )
            )
            continue
        d = decisions[key]
        if d.decision is ReviewDecision.REJECT:
            rejected.append(key)
            continue
        override: dict[str, Any] = d.override or {}
        accepted.append(
            AcceptedMapping(
                source_table=p.source_table,
                source_column=p.source_column,
                canonical_entity=p.canonical_entity,
                canonical_field=override.get("canonical_field", p.canonical_field),
                transform=override.get("transform", p.suggested_transform),
                pii_handling=override.get("pii_handling", p.pii_handling),
                decided_by="reviewer",
                overridden=d.decision is ReviewDecision.APPROVE_WITH_OVERRIDE,
            )
        )
    counts = Counter((a.source_table, a.canonical_field) for a in accepted)
    duplicated = [
        f"mapping:{a.source_table}.{a.source_column}"
        for a in accepted
        if counts[(a.source_table, a.canonical_field)] > 1
    ]
    filters = [
        f
        for f in ms.row_filters
        if not f.requires_review or decisions[f"filter:{f.filter_key}"].decision is not ReviewDecision.REJECT
    ]
    joins = [
        j
        for j in ms.joins
        if not j.requires_review or decisions[f"join:{j.join_id}"].decision is not ReviewDecision.REJECT
    ]
    rejected += [f"filter:{f.filter_key}" for f in ms.row_filters if f not in filters]
    rejected += [f"join:{j.join_id}" for j in ms.joins if j not in joins]
    resolved = ResolvedMapping(
        mapping_hash=ms.content_hash(),
        accepted=accepted,
        filters=filters,
        joins=joins,
        entity_tables=ms.entity_tables,
        primary_tables=ms.primary_tables,
        rejected_keys=sorted(rejected),
        metrics_needing_evidence=ms.metrics_needing_evidence,
    )
    return resolved, duplicated


def mapping_review(ctx: StepContext) -> StepResult:
    ms = ctx.get(StepName.CANONICAL_MAPPING, MappingSet)
    h = ms.content_hash()
    items = review_items(ms, ctx)
    decisions = effective_decisions(ctx.approvals, ReviewGate.MAPPING_REVIEW, h)
    pending = [i for i in items if i.item_key not in decisions]
    if pending:
        return StepResult(
            status="needs_review",
            gate=ReviewGate.MAPPING_REVIEW,
            pending_items=pending,
            subject_hash=h,
            audit=[("review_requested", {"gate": "mapping_review", "items": len(pending), "subject_hash": h})],
        )
    resolved, duplicated = resolve(ms, decisions)
    if duplicated:
        again = [
            i.model_copy(update={"reason_codes": [*i.reason_codes, "DUPLICATE_TARGET_AFTER_REVIEW"]})
            for i in items
            if i.item_key in duplicated
        ]
        return StepResult(
            status="needs_review",
            gate=ReviewGate.MAPPING_REVIEW,
            pending_items=again,
            subject_hash=h,
            audit=[("review_conflict", {"items": duplicated})],
        )
    approval_ids = sorted(
        {
            a.approval_id
            for a in ctx.approvals
            if a.gate == ReviewGate.MAPPING_REVIEW and a.subject_hash == h and a.revoked_at is None
        },
        key=str,
    )
    resolved = resolved.model_copy(update={"approval_ids": approval_ids})
    payload = {
        "mapping_hash": h,
        "approval_ids": [str(a) for a in approval_ids],
        "decisions": {k: d.decision.value for k, d in sorted(decisions.items())},
        "overrides": {k: d.override for k, d in sorted(decisions.items()) if d.override},
    }
    ev = make_evidence(ctx, f"review://{ctx.run.run_id}/mapping_review", "human_review", payload)
    overrides = sum(1 for a in resolved.accepted if a.overridden)
    findings = [
        Finding(
            code="MAPPING_REVIEWED",
            title="Mapping review applied",
            finding_type=FindingType.OBSERVATION,
            statement=(
                f"{len(items)} items reviewed: {len(resolved.accepted)} mappings accepted "
                f"({sum(a.decided_by == 'auto' for a in resolved.accepted)} automatically), "
                f"{overrides} overridden, {len(resolved.rejected_keys)} rejected."
            ),
            confidence=Confidence.HIGH,
            evidence=[ev.ref()],
            metadata={"overrides": overrides},
        )
    ]
    return StepResult(
        output=resolved,
        evidence=[ev],
        findings=findings,
        subject_hash=h,
        audit=[
            (
                "mapping_resolved",
                {
                    "accepted": len(resolved.accepted),
                    "overrides": overrides,
                    "rejected": len(resolved.rejected_keys),
                    "resolved_hash": resolved.content_hash(),
                },
            )
        ],
    )
