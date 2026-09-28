"""Step 5 — canonical mapping (POD-306). Deterministic scoring; uncertainty routes to review.

The optional `MappingJudge` (POD-607) may reorder candidates or abstain for ambiguous
columns. It can never invent a target, clear `requires_review`, or raise confidence above
MEDIUM (ADR-0007).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Protocol
from uuid import UUID

from src.adapters.external import type_family
from src.domain.models import Confidence, EvidenceRef, Finding, FindingStatus, FindingType, StepName, utcnow
from src.domain.ontology import FieldDef, Ontology, load_scoring
from src.domain.project_models import (
    ColumnProfile,
    EntityInference,
    JoinGraph,
    MappingProposal,
    MappingSet,
    PiiClass,
    RowFilter,
    SchemaProfile,
    ScoredTarget,
    SemanticType,
    TableProfile,
    UnmappedField,
)
from src.services.entities import confidence_for, field_owner
from src.services.pii import TEST_RECORD_PATTERN
from src.services.text import char_ratio, jaccard, raw_tokens, tokens
from src.workflows.contracts import StepContext, StepResult, make_evidence

EXCLUDE_PII = {PiiClass.NATIONAL_ID, PiiClass.PAYMENT_CARD, PiiClass.DOB, PiiClass.FREE_TEXT}

TYPE_COMPAT: dict[str, dict[str, float]] = {
    "string": {"string": 1.0, "integer": 0.9, "decimal": 0.3, "date": 0.3, "timestamp": 0.3, "boolean": 0.3},
    "integer": {"integer": 1.0, "decimal": 0.6, "string": 0.5},
    "decimal": {"decimal": 1.0, "integer": 0.8},
    "date": {"date": 1.0, "timestamp": 0.8, "date_string": 0.9, "string": 0.3},
    "timestamp": {"timestamp": 1.0, "date": 0.8, "date_string": 0.6},
    "boolean": {"boolean": 1.0, "string": 0.3, "integer": 0.3},
}


class MappingJudge(Protocol):
    name: str

    def judge(
        self, proposal: MappingProposal, column: ColumnProfile, table: TableProfile, ontology: Ontology
    ) -> dict[str, Any] | None: ...


def _type_score(field: FieldDef, col: ColumnProfile) -> float:
    fam = type_family(col.dtype)
    if col.inferred_semantic_type is SemanticType.DATE_STRING:
        fam = "date_string"
    return TYPE_COMPAT.get(field.type, {}).get(fam, 0.0)


def _name_score(column: str, field_name: str, ontology: Ontology) -> float:
    if field_owner(column, ontology) == field_name:
        return 1.0
    ctoks = tokens(column)
    best = jaccard(ctoks, tokens(field_name))
    for syn in ontology.synonyms.get(field_name, []):
        best = max(best, jaccard(ctoks, tokens(syn)))
    return max(best, 0.7 * char_ratio(column, field_name))


def _score_column(
    col: ColumnProfile, entity: str, entity_conf: Confidence, ontology: Ontology, fk_hint: tuple[str, float] | None
) -> list[ScoredTarget]:
    w = load_scoring()["mapping"]["weights"]
    out = []
    for fname, fdef in ontology.entities[entity].fields.items():
        ns = _name_score(col.column, fname, ontology)
        if fk_hint and fk_hint[0] == fname:
            ns = max(ns, fk_hint[1])
        ts = _type_score(fdef, col)
        ctx_score = 1.0 if entity_conf is Confidence.HIGH else 0.5
        score = w["name"] * ns + w["type"] * ts + w["context"] * ctx_score
        if ts == 0.0:
            score *= 0.5
        out.append(ScoredTarget(entity=entity, field=fname, score=round(score, 4)))
    out.sort(key=lambda t: (-t.score, t.field))
    return out


def _fk_hints(
    joins: JoinGraph, entity_of: dict[str, str], ontology: Ontology, entities: EntityInference
) -> dict[tuple[str, str], tuple[str, float]]:
    """A column that joins to another table's key inherits that key's canonical field name."""
    hints: dict[tuple[str, str], tuple[str, float]] = {}
    for j in joins.joins:
        right_entity = entity_of.get(j.right_table)
        left_entity = entity_of.get(j.left_table)
        if not right_entity or not left_entity:
            continue
        right_field = field_owner(j.right_columns[0], ontology)
        right_candidate = entities.for_table(j.right_table)
        ids = ontology.entities[right_entity].id_fields
        if (
            right_field is None
            and len(ids) == 1
            and right_candidate
            and right_candidate.primary_key_columns == j.right_columns
        ):
            right_field = ids[0]
        if right_field is None or right_field not in ontology.entities[right_entity].fields:
            continue
        if right_field in ontology.entities[left_entity].fields:
            hints[(j.left_table, j.left_columns[0])] = (right_field, round(0.85 * j.score, 4))
    return hints


def propose_mapping(ctx: StepContext) -> StepResult:
    profile = ctx.get(StepName.SCHEMA_PROFILING, SchemaProfile)
    entities = ctx.get(StepName.ENTITY_INFERENCE, EntityInference)
    joins = ctx.get(StepName.JOIN_INFERENCE, JoinGraph)
    ontology = ctx.ontology
    cfg = load_scoring()["mapping"]
    judge: MappingJudge | None = ctx.services.get("judge")
    adapter = ctx.adapter()

    entity_of = {c.table: c.canonical_entity for c in entities.candidates if c.canonical_entity}
    conf_of = {c.table: c.confidence for c in entities.candidates}
    fk_hints = _fk_hints(joins, entity_of, ontology, entities)
    pk_hints: dict[tuple[str, str], tuple[str, float]] = {}
    structural_tables = set()
    for candidate in entities.candidates:
        if not candidate.canonical_entity:
            continue
        ids = ontology.entities[candidate.canonical_entity].id_fields
        if candidate.feature_breakdown.get("structural_anchors"):
            structural_tables.add(candidate.table)
        if (
            len(ids) == 1
            and len(candidate.primary_key_columns) == 1
            and (
                candidate.confidence is Confidence.HIGH
                or candidate.feature_breakdown.get("name") == 1.0
                or candidate.table in structural_tables
            )
        ):
            column = candidate.primary_key_columns[0]
            if field_owner(column, ontology) is None:
                pk_hints[(candidate.table, column)] = (ids[0], 0.85)
    minor_units = {
        (t.qualified, c.column)
        for t in profile.tables
        for c in t.columns
        if c.inferred_semantic_type is SemanticType.MONEY and type_family(c.dtype) == "integer"
    }
    minor_units = {k for k in minor_units if _is_minor(profile, *k)}
    traps = {t.lower() for t in ontology.semantic_traps}
    metric_bearing = ontology.metric_bearing_fields()

    proposals: list[MappingProposal] = []
    findings: list[Finding] = []
    evidence = []
    parents: dict[UUID, list[UUID]] = {}  # lineage: conflict evidence -> the table's profile evidence
    for table in profile.tables:
        entity = entity_of.get(table.qualified)
        if not entity:
            continue
        ref = EvidenceRef(source_id=str(table.evidence_id), uri=f"profile://{table.qualified}", retrieved_at=utcnow())
        ranked: dict[str, list[ScoredTarget]] = {}
        for col in table.columns:
            hint = fk_hints.get((table.qualified, col.column)) or pk_hints.get((table.qualified, col.column))
            ranked[col.column] = _score_column(col, entity, conf_of[table.qualified], ontology, hint)

        # Normally a target has one source per table. Competing interpretations
        # deliberately retain the same target and must be resolved at review.
        assigned: dict[str, str] = {}
        conflicts: dict[str, list[str]] = defaultdict(list)
        order = sorted(ranked, key=lambda c: -ranked[c][0].score)
        for colname in order:
            # Trap columns (e.g. `rev`) are always surfaced for review rather than silently dropped.
            floor = cfg["min_score"] - (0.1 if set(raw_tokens(colname)) & traps else 0.0)
            for cand in ranked[colname]:
                if cand.score < floor:
                    break
                holder = next((c for c, f in assigned.items() if f == cand.field), None)
                if holder is None:
                    assigned[colname] = cand.field
                    break
                monetary_competition = (
                    cand is ranked[colname][0]
                    and ontology.field(entity, cand.field).unit in {"currency_major", "currency_minor"}
                    and type_family(table.column(colname).dtype) in {"integer", "decimal"}
                )
                if cand is ranked[colname][0] and (
                    monetary_competition or abs(ranked[holder][0].score - cand.score) <= cfg["conflict_margin"]
                ):
                    # An amount variant is not evidence for a different financial
                    # role simply because its first-choice target is occupied.
                    # Both the exact match and its variant require review, even
                    # when their lexical scores are far apart.
                    assigned[colname] = cand.field
                    conflicts[cand.field] += [holder, colname]
                    break
        for fieldname, cols in conflicts.items():
            conflicts[fieldname] = sorted(set(cols))

        for colname, fieldname in sorted(assigned.items(), key=lambda kv: table.column(kv[0]).ordinal):
            col = table.column(colname)
            cands = ranked[colname]
            top = next(c for c in cands if c.field == fieldname)
            fdef = ontology.field(entity, fieldname)
            reasons: list[str] = []
            conf = confidence_for(top.score)
            if table.qualified in structural_tables or (table.qualified, colname) in pk_hints:
                reasons.append("STRUCTURAL_INFERENCE")
                conf = Confidence.LOW if table.qualified in structural_tables else Confidence.MEDIUM
            entity_conf = conf_of[table.qualified]
            if entity_conf is not Confidence.HIGH:
                # An exact field-name match cannot resolve uncertainty about the
                # containing entity. Keep every dependent proposal review-bound.
                reasons.append("ENTITY_UNCERTAIN")
                if entity_conf is Confidence.LOW or conf is Confidence.HIGH:
                    conf = entity_conf
            if conf is not Confidence.HIGH:
                reasons.append("LOW_CONFIDENCE")
            if f"{entity}.{fieldname}" in metric_bearing:
                reasons.append("METRIC_BEARING")
            pii_class = col.pii_class or fdef.pii
            if pii_class:
                reasons.append("PII_FIELD")
            if fieldname in conflicts:
                reasons.append("CONFLICT")
            transform = None
            unit_tokens = set(raw_tokens(colname))
            explicit_cents = bool(unit_tokens & {"cent", "cents"})
            ambiguous_minor = "minor" in unit_tokens and not explicit_cents
            if ambiguous_minor and fdef.unit == "currency_major":
                reasons.append("UNIT_UNCERTAIN")
            elif (
                (table.qualified, colname) in minor_units
                or (explicit_cents and type_family(col.dtype) in {"integer", "decimal"})
            ) and fdef.unit == "currency_major":
                reasons.append("UNIT_MISMATCH")
                transform = "cents_to_major"
            if col.inferred_semantic_type is SemanticType.DATE_STRING and fdef.type == "date":
                reasons.append("TRANSFORM_REQUIRED")
                transform = "parse_mixed_date"
            if set(raw_tokens(colname)) & traps and fieldname not in {"revenue_recognized"}:
                reasons.append("SEMANTIC_TRAP")
            if (table.qualified, colname) in fk_hints and field_owner(colname, ontology) != fieldname:
                reasons.append("JOIN_INFERRED")
            pii_handling = None
            if pii_class:
                pii_handling = "exclude" if PiiClass(pii_class) in EXCLUDE_PII else "hash"
            rationale = (
                f"name/type/context score {top.score:.2f}"
                + (f"; synonym of {fieldname}" if field_owner(colname, ontology) == fieldname else "")
                + (f"; transform {transform}" if transform else "")
                + (f"; PII ({pii_class}) will be {pii_handling}ed in staging" if pii_class else "")
            )
            proposal = MappingProposal(
                mapping_key=f"{table.qualified}.{colname}",
                source_table=table.qualified,
                source_column=colname,
                source_field=f"{table.qualified}.{colname}",
                canonical_entity=entity,
                canonical_field=fieldname,
                confidence=conf,
                score=top.score,
                rationale=rationale,
                requires_review=bool(reasons),
                reason_codes=reasons,
                alternatives=[c for c in cands if c.field != fieldname][:3],
                suggested_transform=transform,
                pii_handling=pii_handling,
                evidence_ids=[table.evidence_id] if table.evidence_id else [],
            )
            if judge is not None and conf is not Confidence.HIGH and len(cands) > 1:
                proposal = _apply_judge(judge, proposal, col, table, ontology)
            proposals.append(proposal)

        for fieldname, cols in conflicts.items():
            payload: dict[str, Any] = {"field": f"{entity}.{fieldname}", "columns": cols}
            if len(cols) == 2 and all(type_family(table.column(c).dtype) in {"integer", "decimal"} for c in cols):
                diff = adapter.pair_difference(table.schema_name, table.table_name, cols[0], cols[1])
                payload |= diff.model_dump()
            ev = make_evidence(
                ctx,
                f"duckdb://{ctx.run.company_id}/{table.qualified}#conflict={fieldname}",
                "column_conflict",
                payload,
                adapter.spec.as_of,
            )
            evidence.append(ev)
            if table.evidence_id:
                parents[ev.evidence_id] = [table.evidence_id]
            findings.append(
                Finding(
                    code="CONFLICT",
                    title=f"{len(cols)} columns compete for {entity}.{fieldname}",
                    statement=(
                        f"{', '.join(cols)} in {table.qualified} both map to {entity}.{fieldname}"
                        + (
                            f"; values differ on {payload['rows_differing']} of {payload['rows_compared']} rows"
                            if "rows_differing" in payload
                            else ""
                        )
                        + ". Neither is chosen automatically."
                    ),
                    confidence=Confidence.HIGH,
                    evidence=[ev.ref(), ref],
                    metadata={"table": table.qualified, "columns": cols, "field": fieldname},
                )
            )

    row_filters = _row_filters(ctx, entity_of)
    primary_tables = _primary_tables(entities, entity_of, proposals, ontology)
    mapped = {(p.canonical_entity, p.canonical_field) for p in proposals}
    unmapped: list[UnmappedField] = []
    for entity in sorted(set(entity_of.values())):
        for fname, fdef in ontology.entities[entity].fields.items():
            if fdef.required and (entity, fname) not in mapped:
                unmapped.append(
                    UnmappedField(
                        entity=entity, field=fname, affected_metrics=ontology.metrics_requiring(f"{entity}.{fname}")
                    )
                )
    needs_evidence = sorted(
        m for m, d in ontology.metrics.items() if any(tuple(r.split(".", 1)) not in mapped for r in d.requires)
    )
    for uf in unmapped:
        findings.append(
            Finding(
                code="UNMAPPED_REQUIRED",
                title=f"No source column for {uf.entity}.{uf.field}",
                statement=(
                    f"Required field {uf.entity}.{uf.field} has no candidate column; "
                    f"affected metrics: {', '.join(uf.affected_metrics) or 'none'}. It is left explicitly unknown."
                ),
                confidence=Confidence.HIGH,
                status=FindingStatus.NEEDS_EVIDENCE,
                finding_type=FindingType.OBSERVATION,
                metadata={"entity": uf.entity, "field": uf.field},
            )
        )
    for m in needs_evidence:
        findings.append(
            Finding(
                code="METRIC_NEEDS_EVIDENCE",
                title=f"Metric {m} cannot be derived",
                statement=f"{m} needs fields with no approved source mapping; it will not be generated or estimated.",
                confidence=Confidence.HIGH,
                status=FindingStatus.NEEDS_EVIDENCE,
                finding_type=FindingType.ASSUMPTION,
                metadata={"metric": m},
            )
        )

    mapping_set = MappingSet(
        proposals=proposals,
        row_filters=row_filters,
        joins=joins.joins,
        entity_tables=entity_of,
        primary_tables=primary_tables,
        unmapped_required=unmapped,
        metrics_needing_evidence=needs_evidence,
    )
    n_review = sum(p.requires_review for p in proposals)
    return StepResult(
        output=mapping_set,
        evidence=evidence,
        evidence_parents=parents,
        findings=findings,
        audit=[
            (
                "mapping_proposed",
                {
                    "proposals": len(proposals),
                    "requires_review": n_review,
                    "row_filters": len(row_filters),
                    "unmapped_required": len(unmapped),
                    "mapping_hash": mapping_set.content_hash(),
                },
            )
        ],
    )


def _is_minor(profile: SchemaProfile, table: str, column: str) -> bool:
    ratio = load_scoring()["profiling"]["minor_units_ratio"]
    t = profile.table(table)
    col = t.column(column)
    decimal_means = [
        abs(c.mean_value or 0)
        for tt in profile.tables
        if tt.schema_name == t.schema_name
        for c in tt.columns
        if c.inferred_semantic_type is SemanticType.MONEY and type_family(c.dtype) == "decimal" and c.mean_value
    ]
    if not decimal_means or col.mean_value is None:
        return False
    decimal_means.sort()
    mid = (
        decimal_means[len(decimal_means) // 2]
        if len(decimal_means) % 2
        else ((decimal_means[len(decimal_means) // 2 - 1] + decimal_means[len(decimal_means) // 2]) / 2)
    )
    return bool(mid) and abs(col.mean_value) / mid >= ratio


def _row_filters(ctx: StepContext, entity_of: dict[str, str]) -> list[RowFilter]:
    profile = ctx.get(StepName.SCHEMA_PROFILING, SchemaProfile)
    out: list[RowFilter] = []
    for t in profile.tables:
        if t.qualified not in entity_of:
            continue
        for c in t.columns:
            ev = [t.evidence_id] if t.evidence_id else []
            if (
                c.inferred_semantic_type is SemanticType.BOOLEAN
                and c.pattern_counts.get("true_count")
                and c.column.lower() in {"is_deleted", "deleted", "del_flag", "loevm", "is_removed", "is_test"}
            ):
                out.append(
                    RowFilter(
                        filter_key=f"{t.qualified}.{c.column}:exclude_true",
                        table=t.qualified,
                        column=c.column,
                        kind="exclude_true",
                        rationale=f"{c.pattern_counts['true_count']} rows flagged as deleted/test",
                        affected_rows=c.pattern_counts["true_count"],
                        evidence_ids=ev,
                    )
                )
            if c.pattern_counts.get("test_prefix") and c.pii_class is None and "name" in tokens(c.column):
                out.append(
                    RowFilter(
                        filter_key=f"{t.qualified}.{c.column}:exclude_match",
                        table=t.qualified,
                        column=c.column,
                        kind="exclude_match",
                        value=TEST_RECORD_PATTERN,
                        rationale=f"{c.pattern_counts['test_prefix']} rows look like test records",
                        affected_rows=c.pattern_counts["test_prefix"],
                        evidence_ids=ev,
                    )
                )
    return out


def _primary_tables(
    entities: EntityInference, entity_of: dict[str, str], proposals: list[MappingProposal], ontology: Ontology
) -> dict[str, str]:
    out: dict[str, str] = {}
    by_entity: dict[str, list[str]] = defaultdict(list)
    for table, entity in entity_of.items():
        by_entity[entity].append(table)
    for entity, tables in by_entity.items():
        id_fields = set(ontology.entities[entity].id_fields)
        pk_tables = []
        for t in tables:
            cand = entities.for_table(t)
            pk = cand.primary_key_columns if cand else []
            maps = {p.canonical_field for p in proposals if p.source_table == t and p.source_column in pk}
            if maps & id_fields:
                pk_tables.append(t)
        scores = {t: (c.score if (c := entities.for_table(t)) else 0.0) for t in tables}
        pick = sorted(pk_tables)[0] if pk_tables else max(tables, key=lambda t: (scores[t], t))
        out[entity] = pick
    return out


def _apply_judge(
    judge: MappingJudge, proposal: MappingProposal, col: ColumnProfile, table: TableProfile, ontology: Ontology
) -> MappingProposal:
    verdict = judge.judge(proposal, col, table, ontology)
    if not verdict:
        return proposal
    allowed = {proposal.canonical_field} | {a.field for a in proposal.alternatives}
    choice = verdict.get("choice")
    meta = {"judge": judge.name, **{k: v for k, v in verdict.items() if k != "choice"}, "choice": choice}
    if choice == "ABSTAIN" or choice not in allowed:
        return proposal.model_copy(update={"judge": {**meta, "applied": False}})
    if choice == proposal.canonical_field:
        return proposal.model_copy(update={"judge": {**meta, "applied": True}})
    alt = next(a for a in proposal.alternatives if a.field == choice)
    alts = [a for a in proposal.alternatives if a.field != choice] + [
        ScoredTarget(entity=proposal.canonical_entity, field=proposal.canonical_field, score=proposal.score)
    ]
    return proposal.model_copy(
        update={
            "canonical_field": choice,
            "alternatives": alts,
            "confidence": Confidence.MEDIUM,
            "requires_review": True,
            "reason_codes": sorted(set(proposal.reason_codes) | {"JUDGE_REORDERED"}),
            "rationale": proposal.rationale + f"; judge preferred {choice} over {proposal.canonical_field} "
            f"(deterministic {alt.score:.2f})",
            "judge": {**meta, "applied": True},
        }
    )
