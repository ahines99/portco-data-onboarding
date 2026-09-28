"""Step 4 — join inference (POD-305): name candidates validated by inclusion dependency."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from src.adapters.external import type_family
from src.domain.models import Confidence, Evidence, Finding, StepName
from src.domain.ontology import load_scoring
from src.domain.project_models import (
    Cardinality,
    ColumnProfile,
    EntityInference,
    JoinCandidate,
    JoinGraph,
    SchemaProfile,
    SemanticType,
    TableProfile,
)
from src.services.entities import confidence_for, field_owner
from src.services.text import char_ratio, jaccard, singular_tokens, tokens
from src.workflows.contracts import StepContext, StepResult, make_evidence

NOT_KEYS = {
    SemanticType.MONEY,
    SemanticType.DATE,
    SemanticType.TIMESTAMP,
    SemanticType.BOOLEAN,
    SemanticType.QUANTITY,
    SemanticType.FREE_TEXT,
    SemanticType.DATE_STRING,
    SemanticType.MIXED,
}


def _compatible(a: ColumnProfile, b: ColumnProfile) -> bool:
    fa, fb = type_family(a.dtype), type_family(b.dtype)
    return fa == fb or {fa, fb} <= {"integer", "string"}


def name_score(left: ColumnProfile, right: ColumnProfile, right_table: TableProfile, ctx: StepContext) -> float:
    if left.column.lower() == right.column.lower():
        return 1.0
    ont = ctx.ontology
    lo, ro = field_owner(left.column, ont), field_owner(right.column, ont)
    if lo and lo == ro:
        return 0.9
    tok = jaccard(tokens(left.column), tokens(right.column) | singular_tokens(right_table.table_name))
    return max(tok, 0.7 * char_ratio(left.column, right.column))


def infer_joins(ctx: StepContext) -> StepResult:
    profile = ctx.get(StepName.SCHEMA_PROFILING, SchemaProfile)
    entities = ctx.get(StepName.ENTITY_INFERENCE, EntityInference)
    cfg = load_scoring()["join"]
    adapter = ctx.adapter()
    rels = {(r.from_.split(".")[0], r.to.split(".")[0]) for r in ctx.ontology.relationships}
    overlap_tables = {frozenset(o.tables) for o in entities.overlaps}

    tables = {t.qualified: t for t in profile.tables if t.row_count > 0}
    entity_of = {c.table: c.canonical_entity for c in entities.candidates if c.canonical_entity}
    pk_of = {c.table: c.primary_key_columns for c in entities.candidates if c.canonical_entity}

    best: dict[tuple[str, str], JoinCandidate] = {}
    contenders: dict[tuple[str, str], list[JoinCandidate]] = defaultdict(list)
    evidence: list[Evidence] = []
    parents: dict[UUID, list[UUID]] = {}  # lineage: containment evidence -> both tables' profile evidence
    for rq, rpk in pk_of.items():
        if len(rpk) != 1:
            continue
        rt = tables[rq]
        rc = rt.column(rpk[0])
        if rc.pii_class:
            continue
        for lq, lt in tables.items():
            if lq == rq or lq not in entity_of:
                continue
            for lc in lt.columns:
                if lc.inferred_semantic_type in NOT_KEYS or lc.pii_class or not _compatible(lc, rc):
                    continue
                own_pk = pk_of.get(lq, [])
                same_field = (
                    lc.column.lower() == rc.column.lower()
                    or field_owner(lc.column, ctx.ontology) == field_owner(rc.column, ctx.ontology) is not None
                )
                if lc.column in own_pk and not same_field:
                    continue  # a table's own key (or key part, e.g. a line number) rarely references another key
                ns = name_score(lc, rc, rt, ctx)
                if (entity_of[lq], entity_of[rq]) in rels:
                    ns = min(1.0, ns + cfg["relationship_bonus"])
                weak_name = ns < cfg["min_name_score"]
                structural = weak_name or (field_owner(lc.column, ctx.ontology) is None and not same_field)
                if weak_name and not (
                    (entity_of[lq], entity_of[rq]) in rels
                    and lc.inferred_semantic_type is SemanticType.ID
                    and lc.column not in own_pk
                    and lc.non_null_count >= 5
                    and (lc.distinct_count or 0) >= 3
                    and type_family(lc.dtype) == type_family(rc.dtype)
                ):
                    continue
                cont = adapter.containment(
                    (lt.schema_name, lt.table_name, lc.column), (rt.schema_name, rt.table_name, rc.column)
                )
                if cont.ratio < cfg["min_containment"]:
                    continue
                if weak_name and cont.ratio < cfg["review_containment_below"]:
                    continue
                w = cfg["weights"]
                score = round(w["name"] * ns + w["containment"] * cont.ratio, 4)
                left_unique = lc.distinct_count == lc.non_null_count
                cardinality: Cardinality = "1:1" if left_unique else "N:1"
                reasons: list[str] = []
                if structural:
                    reasons.append("STRUCTURAL_JOIN")
                if cont.ratio < cfg["review_containment_below"]:
                    reasons.append("ORPHANS")
                if frozenset({lq, rq}) <= next((o for o in overlap_tables if lq in o and rq in o), frozenset()):
                    reasons.append("ENTITY_OVERLAP")
                conf = confidence_for(score)
                if conf is Confidence.LOW:
                    reasons.append("LOW_CONFIDENCE")
                join_id = f"{lq}.{lc.column}->{rq}.{rc.column}"
                payload = {
                    "join": join_id,
                    "distinct_left": cont.distinct_left,
                    "distinct_matched": cont.distinct_matched,
                    "rows_left": cont.rows_left,
                    "rows_orphan": cont.rows_orphan,
                    "name_score": round(ns, 4),
                }
                ev = make_evidence(
                    ctx,
                    f"duckdb://{ctx.run.company_id}/{join_id}#stat=containment",
                    "containment",
                    payload,
                    adapter.spec.as_of,
                )
                parents[ev.evidence_id] = [e for e in (tables[lq].evidence_id, tables[rq].evidence_id) if e]
                cand = JoinCandidate(
                    join_id=join_id,
                    left_table=lq,
                    left_columns=[lc.column],
                    right_table=rq,
                    right_columns=[rc.column],
                    containment_ratio=round(cont.ratio, 4),
                    orphan_rate=round(cont.orphan_rate, 4),
                    cardinality=cardinality,
                    name_score=round(ns, 4),
                    score=score,
                    confidence=conf,
                    requires_review=bool(reasons),
                    reason_codes=reasons,
                    evidence_id=ev.evidence_id,
                )
                key = (lq, lc.column)
                contenders[key].append(cand)
                evidence.append(ev)
                if key not in best or cand.score > best[key].score:
                    best[key] = cand

    # Aggregate overlap alone cannot choose between two plausible reference
    # tables. Do not turn alphabetical iteration order into an asserted FK.
    ambiguous = {
        key: candidates
        for key, candidates in contenders.items()
        if len(candidates) > 1
        and any("STRUCTURAL_JOIN" in c.reason_codes for c in candidates)
        and sum(best[key].score - c.score <= 0.05 for c in candidates) > 1
    }
    for key in ambiguous:
        del best[key]
    joins = sorted(best.values(), key=lambda j: j.join_id)
    keep_ev = {j.evidence_id for j in joins} | {j.evidence_id for candidates in ambiguous.values() for j in candidates}
    evidence = [e for e in evidence if e.evidence_id in keep_ev]
    ev_by_id = {e.evidence_id: e for e in evidence}
    findings = []
    for (table, column), candidates in ambiguous.items():
        findings.append(
            Finding(
                code="JOIN_AMBIGUOUS",
                title=f"Ambiguous relationship for {table}.{column}",
                statement="Multiple target keys have similar aggregate support; no join was proposed.",
                confidence=Confidence.LOW,
                evidence=[ev_by_id[j.evidence_id].ref() for j in candidates if j.evidence_id],
                metadata={"table": table, "column": column, "candidate_count": len(candidates)},
            )
        )
    for j in joins:
        assert j.evidence_id is not None
        refs = [ev_by_id[j.evidence_id].ref()]
        if "ORPHANS" in j.reason_codes:
            findings.append(
                Finding(
                    code="ORPHAN_KEYS",
                    title=f"Orphan keys in {j.left_table}.{j.left_columns[0]}",
                    statement=(
                        f"{j.orphan_rate:.1%} of rows reference a {j.right_table} key that does not exist "
                        f"(containment {j.containment_ratio:.1%})."
                    ),
                    confidence=Confidence.HIGH,
                    evidence=refs,
                    metadata={"join": j.join_id, "orphan_rate": j.orphan_rate},
                )
            )
        findings.append(
            Finding(
                code="JOIN_INFERRED",
                title=f"Join {j.join_id}",
                statement=f"{j.join_id}: {j.cardinality}, score {j.score:.2f}, containment {j.containment_ratio:.1%}.",
                confidence=j.confidence,
                evidence=refs,
                metadata={"join": j.join_id, "requires_review": j.requires_review},
            )
        )
    return StepResult(
        output=JoinGraph(joins=joins),
        evidence=evidence,
        evidence_parents=parents,
        findings=findings,
        audit=[("joins_inferred", {"joins": len(joins), "requires_review": sum(j.requires_review for j in joins)})],
    )
