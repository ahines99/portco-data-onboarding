"""Step 3 — entity inference (POD-304): primary keys and table -> canonical entity."""

from __future__ import annotations

from datetime import timedelta
from itertools import combinations
from uuid import UUID

from src.adapters.external import type_family
from src.domain.models import Confidence, EvidenceRef, Finding, StepName, utcnow
from src.domain.ontology import EntityDef, Ontology, load_scoring
from src.domain.project_models import (
    ColumnProfile,
    EntityCandidate,
    EntityInference,
    EntityOverlap,
    SchemaProfile,
    ScoredEntity,
    SemanticType,
    TableProfile,
)
from src.services.text import is_id_like, jaccard, singular_tokens
from src.workflows.contracts import StepContext, StepResult, make_evidence


def confidence_for(score: float) -> Confidence:
    cfg = load_scoring()["confidence"]
    if score >= cfg["high"]:
        return Confidence.HIGH
    if score >= cfg["medium"]:
        return Confidence.MEDIUM
    return Confidence.LOW


def field_owner(column: str, ontology: Ontology) -> str | None:
    """Canonical field name a source column is a known synonym of (or equals)."""
    low = column.lower()
    owner = ontology.synonym_owner().get(low)
    if owner:
        return owner
    all_fields = {f for e in ontology.entities.values() for f in e.fields}
    return low if low in all_fields else None


def _pk_rank(col: ColumnProfile) -> int:
    rank = 0
    if col.inferred_semantic_type in {SemanticType.ID, SemanticType.CODE}:
        rank += 2
    if is_id_like(col.column):
        rank += 1
    if col.ordinal == 1:
        rank += 1
    if col.pii_class:
        rank -= 5
    return rank


def primary_key(ctx: StepContext, table: TableProfile) -> list[str]:
    n = table.row_count
    if n == 0:
        return []
    canonical_ids = {f for e in ctx.ontology.entities.values() for f in e.id_fields}

    def eligible(c: ColumnProfile) -> bool:
        # Uniqueness alone is not evidence of an identifier (dates and amounts often
        # happen to be unique in small samples). Explicit canonical IDs such as
        # calendar.period remain eligible, but PII never does.
        if c.pii_class:
            return False
        return field_owner(c.column, ctx.ontology) in canonical_ids or (
            is_id_like(c.column) and c.inferred_semantic_type in {SemanticType.ID, SemanticType.CODE}
        )

    singles = [c for c in table.columns if eligible(c) and c.non_null_count == n and c.distinct_count == n]
    if singles:
        return [max(singles, key=_pk_rank).column]
    idish = sorted(
        (c for c in table.columns if c.non_null_count == n and eligible(c)),
        key=lambda c: (-_pk_rank(c), c.ordinal),
    )[:6]
    adapter = ctx.adapter()
    for a, b in combinations(idish, 2):
        if adapter.distinct_count_multi(table.schema_name, table.table_name, [a.column, b.column]) == n:
            return sorted([a.column, b.column], key=lambda name: table.column(name).ordinal)
    return []


def _name_score(table_name: str, entity: str, edef: EntityDef) -> float:
    low = table_name.lower()
    if low in {s.lower() for s in edef.table_synonyms} or low == entity:
        return 1.0
    t = singular_tokens(table_name)
    best = jaccard(t, singular_tokens(entity))
    for syn in edef.table_synonyms:
        best = max(best, jaccard(t, singular_tokens(syn)))
    return best


def _column_score(table: TableProfile, edef: EntityDef, ontology: Ontology) -> float:
    owners = {field_owner(c.column, ontology) for c in table.columns}
    num = den = 0
    for fname, fdef in edef.fields.items():
        w = 2 if fdef.required else 1
        den += w
        if fname in owners:
            num += w
    return num / den if den else 0.0


def _structural_entity(table: TableProfile, ontology: Ontology) -> tuple[str, int] | None:
    """Use known, type-compatible field anchors without needing a table alias.

    Require two anchors, including one field unique to that entity, and a unique
    best count. This is a review-only fallback, not semantic inference from values.
    """
    owners: dict[str, set[str]] = {}
    for entity, edef in ontology.entities.items():
        for name in edef.fields:
            owners.setdefault(name, set()).add(entity)
    supported = []
    for entity, edef in ontology.entities.items():
        anchors = set()
        for col in table.columns:
            field = field_owner(col.column, ontology)
            if not field or field not in edef.fields or col.pii_class or not col.non_null_count:
                continue
            expected = edef.fields[field].type
            actual = type_family(col.dtype)
            if actual == expected or (expected == "decimal" and actual == "integer"):
                anchors.add(field)
        if len(anchors) >= 2 and any(owners[field] == {entity} for field in anchors):
            supported.append((len(anchors), entity))
    supported.sort(reverse=True)
    if not supported or (len(supported) > 1 and supported[0][0] == supported[1][0]):
        return None
    count, entity = supported[0]
    return entity, count


def classify_table(table: TableProfile, pk: list[str], ontology: Ontology) -> EntityCandidate:
    cfg = load_scoring()["entity"]
    w = cfg["weights"]
    pk_owners = {field_owner(c, ontology) for c in pk}
    scored: list[tuple[float, str, dict[str, float]]] = []
    for name, edef in ontology.entities.items():
        feats = {
            "name": round(_name_score(table.table_name, name, edef), 4),
            "columns": round(_column_score(table, edef, ontology), 4),
            "primary_key": 1.0 if pk_owners & set(edef.id_fields) else 0.0,
        }
        score = w["name"] * feats["name"] + w["columns"] * feats["columns"] + w["primary_key"] * feats["primary_key"]
        scored.append((round(score, 4), name, feats))
    scored.sort(key=lambda s: (-s[0], s[1]))
    best_score, best, feats = scored[0]
    alts = [ScoredEntity(entity=n, score=s) for s, n, _ in scored[1:4] if s > 0]
    if best_score < cfg["min_score"]:
        structural = _structural_entity(table, ontology)
        if structural:
            entity, anchors = structural
            return EntityCandidate(
                table=table.qualified,
                canonical_entity=entity,
                score=0.49,
                confidence=Confidence.LOW,
                feature_breakdown={"structural_anchors": float(anchors)},
                primary_key_columns=pk,
                alternatives=alts,
            )
        return EntityCandidate(
            table=table.qualified,
            canonical_entity=None,
            score=best_score,
            confidence=Confidence.LOW,
            feature_breakdown=feats,
            primary_key_columns=pk,
            alternatives=[ScoredEntity(entity=best, score=best_score), *alts],
            excluded_reason="no_entity_match",
        )
    return EntityCandidate(
        table=table.qualified,
        canonical_entity=best,
        score=best_score,
        confidence=confidence_for(best_score),
        feature_breakdown=feats,
        primary_key_columns=pk,
        alternatives=alts,
    )


def infer_entities(ctx: StepContext) -> StepResult:
    profile = ctx.get(StepName.SCHEMA_PROFILING, SchemaProfile)
    ontology = ctx.ontology
    stale_days = load_scoring()["profiling"]["stale_after_days"]
    as_of = ctx.adapter().spec.as_of
    candidates: list[EntityCandidate] = []
    findings: list[Finding] = []
    evidence = []
    parents: dict[UUID, list[UUID]] = {}  # lineage: derived evidence -> the profile evidence it came from
    for table in profile.tables:
        ref = EvidenceRef(source_id=str(table.evidence_id), uri=f"profile://{table.qualified}", retrieved_at=utcnow())
        if table.row_count == 0:
            candidates.append(
                EntityCandidate(
                    table=table.qualified,
                    canonical_entity=None,
                    score=0.0,
                    confidence=Confidence.LOW,
                    excluded_reason="empty_table",
                )
            )
            continue
        pk = primary_key(ctx, table)
        cand = classify_table(table, pk, ontology)
        candidates.append(cand)
        payload = {
            "table": table.qualified,
            "primary_key": pk,
            "features": cand.feature_breakdown,
            "entity": cand.canonical_entity,
            "score": cand.score,
        }
        ev = make_evidence(
            ctx, f"duckdb://{ctx.run.company_id}/{table.qualified}#stat=entity", "entity_scoring", payload, as_of
        )
        evidence.append(ev)
        if table.evidence_id:
            parents[ev.evidence_id] = [table.evidence_id]
        refs = [ev.ref(), ref]
        if cand.canonical_entity is None:
            findings.append(
                Finding(
                    code="NO_ENTITY_MATCH",
                    title=f"{table.qualified} matches no canonical entity",
                    statement=f"Best score {cand.score:.2f} is below the threshold; table excluded.",
                    confidence=Confidence.MEDIUM,
                    evidence=refs,
                    metadata={"table": table.qualified},
                )
            )
            continue
        if not pk:
            findings.append(
                Finding(
                    code="NO_PRIMARY_KEY",
                    title=f"No primary key found for {table.qualified}",
                    statement="No column or column pair is unique and complete.",
                    confidence=Confidence.HIGH,
                    evidence=refs,
                    metadata={"table": table.qualified},
                )
            )
        edef = ontology.entities[cand.canonical_entity]
        if (
            edef.kind == "fact"
            and as_of
            and table.freshness_max_date
            and table.freshness_max_date < as_of - timedelta(days=stale_days)
        ):
            lag = (as_of - table.freshness_max_date).days
            findings.append(
                Finding(
                    code="STALE_DATA",
                    title=f"{table.qualified} looks stale",
                    statement=f"Latest activity is {lag} days before the source as-of date (threshold {stale_days}).",
                    confidence=Confidence.HIGH,
                    evidence=refs,
                    metadata={"table": table.qualified, "lag_days": lag},
                )
            )

    overlaps: list[EntityOverlap] = []
    by_entity: dict[str, list[EntityCandidate]] = {}
    for c in candidates:
        if c.canonical_entity:
            by_entity.setdefault(c.canonical_entity, []).append(c)
    for entity, cands in sorted(by_entity.items()):
        if len(cands) < 2:
            continue
        id_fields = set(ontology.entities[entity].id_fields)
        sor = next(
            (c.table for c in cands if {field_owner(p, ontology) for p in c.primary_key_columns} & id_fields), None
        )
        overlaps.append(EntityOverlap(entity=entity, tables=sorted(c.table for c in cands), system_of_record=sor))
        refs = [e.ref() for e in evidence if e.payload.get("table") in {c.table for c in cands}]
        findings.append(
            Finding(
                code="ENTITY_OVERLAP",
                title=f"{len(cands)} tables describe '{entity}'",
                statement=(
                    f"{', '.join(sorted(c.table for c in cands))} all classify as {entity}. "
                    f"System of record: {sor or 'undetermined'}; the others enrich it through a reviewed join."
                ),
                confidence=Confidence.MEDIUM,
                evidence=refs,
                metadata={"entity": entity, "system_of_record": sor},
            )
        )

    result = EntityInference(candidates=candidates, overlaps=overlaps)
    return StepResult(
        output=result,
        evidence=evidence,
        evidence_parents=parents,
        findings=findings,
        audit=[
            (
                "entities_inferred",
                {
                    "classified": sum(1 for c in candidates if c.canonical_entity),
                    "excluded": sum(1 for c in candidates if not c.canonical_entity),
                },
            )
        ],
    )
