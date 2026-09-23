"""Step 2 — schema profiling (POD-302). Aggregates only; values never leave the adapter."""

from __future__ import annotations

import statistics
from datetime import UTC, date, datetime

from src.adapters.external import ColumnMeta, ColumnStats, TableMeta, type_family
from src.domain.models import Confidence, Evidence, EvidenceRef, Finding, FindingType, StepName
from src.domain.ontology import load_scoring
from src.domain.project_models import (
    ColumnProfile,
    ConnectionCheck,
    SchemaProfile,
    SemanticType,
    TableProfile,
)
from src.services import pii
from src.services.text import (
    QUANTITY_TOKENS,
    is_currency_like,
    is_id_like,
    is_money_like,
    is_name_like,
    raw_tokens,
)
from src.workflows.contracts import StepContext, StepResult, make_evidence

SOFT_DELETE_NAMES = frozenset({"is_deleted", "deleted", "del_flag", "loevm", "is_removed", "is_test"})


def _semantic(
    col: ColumnMeta, stats: ColumnStats, counts: dict[str, int], row_count: int, low_card_max: int
) -> SemanticType:
    fam = col.family
    name = col.name
    nn = stats.non_null
    if fam == "boolean":
        return SemanticType.BOOLEAN
    if fam == "date":
        return SemanticType.DATE
    if fam == "timestamp":
        return SemanticType.TIMESTAMP
    toks = set(raw_tokens(name))
    if fam in {"integer", "decimal"}:
        if is_money_like(name):
            return SemanticType.MONEY
        if toks & QUANTITY_TOKENS:
            return SemanticType.QUANTITY
        if is_id_like(name) or (fam == "integer" and stats.distinct == nn and nn == row_count and nn > 0):
            return SemanticType.ID
        return SemanticType.NUMERIC
    if fam == "string" and nn:
        dates = counts.get("iso_date", 0) + counts.get("us_date", 0)
        if dates == nn:
            return SemanticType.DATE_STRING
        numeric = counts.get("numeric_text", 0) / nn
        if 0.2 <= numeric < 0.95:
            return SemanticType.MIXED
        if is_id_like(name):
            return SemanticType.ID
        if stats.distinct <= low_card_max:
            return SemanticType.CATEGORY
        if is_name_like(name):
            return SemanticType.FREE_TEXT
        return SemanticType.CODE if numeric >= 0.95 else SemanticType.FREE_TEXT
    return SemanticType.UNKNOWN


def _dominant_pattern(counts: dict[str, int], nn: int) -> str | None:
    full = {k: v for k, v in counts.items() if not k.startswith(("contains_", "test_", "normalized"))}
    if not nn or not full:
        return None
    name, best = max(full.items(), key=lambda kv: kv[1])
    return name if best / nn >= 0.8 else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def profile_table(ctx: StepContext, meta: TableMeta) -> tuple[TableProfile, Evidence, list[Finding]]:
    adapter = ctx.adapter()
    cfg = load_scoring()["profiling"]
    schema, table = meta.schema_name, meta.table_name
    row_count = adapter.row_count(schema, table)
    stats = adapter.column_stats(schema, table, meta.columns) if row_count else {}
    columns: list[ColumnProfile] = []
    findings: list[Finding] = []
    flagged_comments = [c.name for c in meta.columns if c.comment and c.comment.flagged]
    table_flagged = bool(meta.comment and meta.comment.flagged) or bool(flagged_comments)
    injection_columns: list[str] = list(flagged_comments)

    for col in meta.columns:
        st = stats.get(col.name) or ColumnStats(non_null=0, distinct=0)
        fam = type_family(col.dtype)
        counts: dict[str, int] = {}
        luhn = 0
        category_values: list[str] | None = None
        if fam == "string" and st.non_null:
            counts = adapter.pattern_counts(schema, table, col.name, pii.PATTERNS)
            if counts.get("card_digits"):
                luhn = adapter.luhn_count(schema, table, col.name)
                counts["luhn_valid"] = luhn
            if is_name_like(col.name):
                counts["normalized_distinct"] = adapter.normalized_distinct(schema, table, col.name)
        pii_class, pii_conf = pii.classify(col.name, fam, st.non_null, counts, luhn)
        semantic = _semantic(col, st, counts, row_count, cfg["low_cardinality_max"])
        if (
            fam == "string"
            and pii_class is None
            and st.non_null
            and st.distinct <= cfg["low_cardinality_max"]
            and semantic in {SemanticType.CATEGORY, SemanticType.CODE, SemanticType.ID}
        ):
            cv = adapter.low_cardinality_values(schema, table, col.name, cfg["low_cardinality_max"])
            category_values = cv.values
            if cv.withheld_reason == "injection_suspected":
                injection_columns.append(col.name)
        columns.append(
            ColumnProfile(
                table=f"{schema}.{table}",
                column=col.name,
                ordinal=col.ordinal,
                dtype=col.dtype,
                nullable=col.nullable,
                row_count=row_count,
                non_null_count=st.non_null,
                null_pct=round(1 - st.non_null / row_count, 6) if row_count else 0.0,
                distinct_count=st.distinct,
                uniqueness_ratio=round(st.distinct / st.non_null, 6) if st.non_null else None,
                min_value=st.min_value,
                max_value=st.max_value,
                mean_value=st.mean_value,
                integer_valued=st.integer_valued,
                negative_count=st.negative_count,
                pattern_counts=counts | ({"true_count": st.true_count} if st.true_count is not None else {}),
                pattern_signature=_dominant_pattern(counts, st.non_null),
                inferred_semantic_type=semantic,
                pii_class=pii_class,
                pii_confidence=pii_conf,
                category_values=category_values,
                comment_flagged=col.name in flagged_comments,
            )
        )

    dates = [
        _parse_date(c.max_value)
        for c in columns
        if c.inferred_semantic_type in {SemanticType.DATE, SemanticType.TIMESTAMP} and c.pii_class is None
    ]
    freshness = max((d for d in dates if d), default=None)
    tp = TableProfile(
        schema_name=schema,
        table_name=table,
        row_count=row_count,
        freshness_max_date=freshness,
        columns=columns,
        comment_flagged=table_flagged,
    )
    payload = tp.model_dump(mode="json")
    ev = make_evidence(
        ctx,
        f"duckdb://{ctx.run.company_id}/{schema}.{table}#stat=profile",
        "table_profile",
        payload,
        ctx.adapter().spec.as_of,
    )
    tp = tp.model_copy(
        update={
            "evidence_id": ev.evidence_id,
            "columns": [c.model_copy(update={"evidence_id": ev.evidence_id}) for c in tp.columns],
        }
    )
    ref = [ev.ref()]
    q = f"{schema}.{table}"

    if row_count == 0:
        findings.append(
            Finding(
                code="EMPTY_TABLE",
                title=f"{q} is empty",
                statement=f"{q} has no rows; it is excluded from mapping.",
                confidence=Confidence.HIGH,
                evidence=ref,
                metadata={"table": q},
            )
        )
    if injection_columns or (meta.comment and meta.comment.flagged):
        signals = sorted(
            {s for c in meta.columns if c.comment for s in c.comment.signals}
            | set(meta.comment.signals if meta.comment else [])
        )
        findings.append(
            Finding(
                code="INJECTION_FLAGGED",
                title=f"Instruction-like text in {q} metadata or values",
                statement=(
                    f"Source text in {q} looks like instructions to an assistant "
                    f"(signals: {', '.join(signals) or 'value heuristics'}). It is treated as untrusted data, "
                    "withheld from summaries, and cannot change workflow state."
                ),
                confidence=Confidence.HIGH,
                evidence=ref,
                metadata={"table": q, "columns": sorted(set(injection_columns)), "table_comment": bool(meta.comment)},
            )
        )
    for c in columns:
        nn = c.non_null_count
        if c.inferred_semantic_type is SemanticType.MIXED:
            findings.append(
                Finding(
                    code="MIXED_TYPES",
                    title=f"{q}.{c.column} mixes numeric and text values",
                    statement=f"{c.pattern_counts.get('numeric_text', 0)} of {nn} values are numeric, the rest text.",
                    confidence=Confidence.HIGH,
                    evidence=ref,
                    metadata={"table": q, "column": c.column},
                )
            )
        if c.pattern_counts.get("test_prefix") and is_name_like(c.column):
            findings.append(
                Finding(
                    code="TEST_RECORDS",
                    title=f"Test records in {q}",
                    statement=f"{c.pattern_counts['test_prefix']} rows in {q}.{c.column} start with 'TEST'.",
                    confidence=Confidence.HIGH,
                    evidence=ref,
                    metadata={"table": q, "column": c.column, "rows": c.pattern_counts["test_prefix"]},
                )
            )
        if (
            c.inferred_semantic_type is SemanticType.BOOLEAN
            and c.column.lower() in SOFT_DELETE_NAMES
            and c.pattern_counts.get("true_count")
        ):
            findings.append(
                Finding(
                    code="SOFT_DELETE_FLAG",
                    title=f"Soft-delete flag {q}.{c.column}",
                    statement=f"{c.pattern_counts['true_count']} rows are flagged deleted.",
                    confidence=Confidence.HIGH,
                    evidence=ref,
                    metadata={"table": q, "column": c.column, "rows": c.pattern_counts["true_count"]},
                )
            )
        nd = c.pattern_counts.get("normalized_distinct")
        if nd is not None and nn and c.pii_class is None and (nn - nd) / nn > cfg["duplicate_name_ratio"]:
            findings.append(
                Finding(
                    code="DUPLICATE_ENTITIES",
                    title=f"Probable duplicate records in {q}",
                    statement=(
                        f"{nn - nd} of {nn} values in {q}.{c.column} collide after normalizing case and "
                        "punctuation; the same real-world entity likely has several records."
                    ),
                    confidence=Confidence.MEDIUM,
                    evidence=ref,
                    metadata={"table": q, "column": c.column, "duplicate_ratio": round((nn - nd) / nn, 4)},
                )
            )
        if is_currency_like(c.column) and c.category_values and len(c.category_values) > 1:
            findings.append(
                Finding(
                    code="MULTI_CURRENCY",
                    title=f"Multiple currencies in {q}",
                    statement=(
                        f"{q}.{c.column} holds {len(c.category_values)} currencies "
                        f"({', '.join(c.category_values)}); no FX table was found, so amounts are never summed "
                        "across currencies."
                    ),
                    confidence=Confidence.HIGH,
                    evidence=ref,
                    metadata={"table": q, "column": c.column},
                )
            )
    return tp, ev, findings


def _minor_unit_findings(profile: SchemaProfile, ratio_threshold: float) -> list[Finding]:
    out: list[Finding] = []
    by_schema: dict[str, list[tuple[TableProfile, ColumnProfile]]] = {}
    for t in profile.tables:
        for c in t.columns:
            if c.inferred_semantic_type is SemanticType.MONEY and c.mean_value is not None:
                by_schema.setdefault(t.schema_name, []).append((t, c))
    for items in by_schema.values():
        decimal_means = [abs(c.mean_value or 0) for _, c in items if type_family(c.dtype) == "decimal" and c.mean_value]
        if not decimal_means:
            continue
        baseline = statistics.median(decimal_means)
        for t, c in items:
            if type_family(c.dtype) != "integer" or not baseline:
                continue
            ratio = abs(c.mean_value or 0) / baseline
            if ratio >= ratio_threshold:
                out.append(
                    Finding(
                        code="POSSIBLE_MINOR_UNITS",
                        title=f"{t.qualified}.{c.column} looks like minor currency units",
                        statement=(
                            f"Integer money column whose mean is {ratio:.0f}x the median of decimal money columns "
                            "in the same schema; it is probably stored in cents."
                        ),
                        confidence=Confidence.MEDIUM,
                        finding_type=FindingType.CALCULATION,
                        evidence=[_ref(profile, t)],
                        metadata={"table": t.qualified, "column": c.column, "ratio": round(ratio, 2)},
                    )
                )
    return out


def _ref(profile: SchemaProfile, table: TableProfile) -> EvidenceRef:
    assert table.evidence_id is not None
    return EvidenceRef(
        source_id=str(table.evidence_id),
        uri=f"duckdb://{profile.company_id}/{table.qualified}#stat=profile",
        retrieved_at=datetime.now(UTC),
    )


def profile_schema(ctx: StepContext) -> StepResult:
    adapter = ctx.adapter()
    cfg = load_scoring()["profiling"]
    tables: list[TableProfile] = []
    evidence: list[Evidence] = []
    findings: list[Finding] = []
    for schema in adapter.list_schemas():
        for table in adapter.list_tables(schema):
            meta = adapter.describe_table(schema, table)
            tp, ev, fs = profile_table(ctx, meta)
            tables.append(tp)
            evidence.append(ev)
            findings += fs
    check = ctx.upstream.get(StepName.CONNECTION_VALIDATION)
    fingerprint = check.source_fingerprint if isinstance(check, ConnectionCheck) else adapter.fingerprint()
    profile = SchemaProfile(
        connection_id=adapter.spec.connection_id,
        company_id=ctx.run.company_id,
        source_fingerprint=fingerprint,
        tables=tables,
    )
    findings += _minor_unit_findings(profile, cfg["minor_units_ratio"])
    pii_cols = sum(1 for t in tables for c in t.columns if c.pii_class)
    findings.append(
        Finding(
            code="PII_CLASSIFIED",
            title="PII classification complete",
            statement=f"{pii_cols} columns classified as PII; their values never leave the adapter.",
            confidence=Confidence.HIGH,
            evidence=[e.ref() for e in evidence][:50],
            metadata={
                "columns": sorted(
                    f"{t.qualified}.{c.column}:{c.pii_class.value}" for t in tables for c in t.columns if c.pii_class
                )
            },
        )
    )
    return StepResult(
        output=profile,
        evidence=evidence,
        findings=findings,
        audit=[("schema_profiled", {"tables": len(tables), "pii_columns": pii_cols, "queries": adapter.query_count})],
    )
