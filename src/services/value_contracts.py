"""Value contracts that a mapped column must satisfy before metrics may depend on it (audit A01, A15).

Canonical accounting meaning and money precision are properties of the *values*, not of the column
name or type. They are measured with aggregate queries (counts only; no value leaves the adapter):

- closed domains (`FieldDef.allowed_values`, e.g. account types): NULL or unknown classifications
  make dependent metrics NEEDS_EVIDENCE. Case/whitespace variants (`Revenue `) are accepted only
  with the reviewed `normalize_category` transform; arbitrary codes need a reviewed crosswalk.
- major-unit money: values with sub-cent digits (or fractional minor units before `cents_to_major`)
  are rejected rather than rounded per row, because row-level rounding cannot agree with rounding
  at the aggregate boundary.
"""

from __future__ import annotations

from src.adapters.external import SourceAdapter, type_family
from src.domain.ontology import Ontology

BLOCKING_REASONS = {
    "null_classification": "NULL classifications",
    "noncanonical": "values outside the canonical domain",
    "case_variants": "case/whitespace variants without the reviewed normalize_category transform",
    "excess_precision": "amounts with more decimal places than the supported money precision",
}


def contract_issues(
    adapter: SourceAdapter,
    ontology: Ontology,
    source_table: str,
    source_column: str,
    dtype: str,
    entity: str,
    field: str,
    transform: str | None,
) -> dict[str, int]:
    """Row counts per blocking issue for this column mapped to `entity.field` (empty: contract holds)."""
    fdef = ontology.field(entity, field)
    schema, table = source_table.split(".", 1)
    issues: dict[str, int] = {}
    if fdef.allowed_values:
        dc = adapter.domain_conformance(schema, table, source_column, fdef.allowed_values)
        issues["null_classification"] = dc.nulls
        issues["noncanonical"] = dc.unknown
        if transform != "normalize_category":
            issues["case_variants"] = dc.case_variants
    if fdef.unit == "currency_major" and type_family(dtype) == "decimal":
        scale = 0 if transform == "cents_to_major" else 2
        issues["excess_precision"] = adapter.excess_scale_count(schema, table, source_column, scale)
    return {k: v for k, v in issues.items() if v}


def describe(issues: dict[str, int]) -> str:
    return "; ".join(f"{n} rows with {BLOCKING_REASONS[k]}" for k, n in sorted(issues.items()))
