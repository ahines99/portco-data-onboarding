# ADR-0003: The source adapter exposes aggregate reads only

- Status: accepted
- Date: 2026-09-23

## Context
"No raw PII in model context" has to hold by construction, not by convention.

## Decision
`SourceAdapter` has no row-fetch method. Profiling, PII detection (regex and Luhn counts computed in
SQL), containment and conflict checks all run as SQL aggregates inside the adapter; only counts,
ratios, and min/max of numeric and date columns leave it. The one narrow exception is
`low_cardinality_values`, which returns category labels only for an operator-approved domain in
`ConnectionSpec.category_domains`, keyed by `schema.table.column`. Every observed label must match
that explicit domain; an unknown column or label withholds the whole list. Domains are never inferred
from source values or caller input. Synthetic fixture domains are defined in
`src/fixtures/category_domains.py`. Labels must also pass PII detectors, a safe-character check and
prompt-injection heuristics, and person-like columns (`owner`, `rep`, `manager`, `name`, `user`,
`employee`, `contact`, ...) are withheld. Every query is parsed by the SQL guard:
a single SELECT, tables only from allowlisted schemas of the current database (never
catalog-qualified), CTE names only where an enclosing WITH defines them, and no file, table,
settings or variable functions.

## Alternatives considered
- Sampled rows with masking: rejected. Masking is a filter that can fail open, and one missed
  pattern would put raw PII into model context.
- Letting the model write SQL through a generic query tool: rejected. A guard would then have to
  decide what "aggregate" means for arbitrary SQL.
- Exposing no category labels at all: rejected. `accepted_values` tests and currency detection need
  them. The narrow, guarded exception is the compromise.

## Consequences
Some heuristics are harder without sampling, which is acceptable. Operators must review domains
before labels can leave a new source; unknown labels cause a missing `accepted_values` test rather
than disclosure. Domain approval is a trust boundary: approving sensitive labels is unsafe.
Source schema requests can only narrow registered allowlists, and read-only verification requires
an explicit DuckDB read-only denial from a unique transactional write probe. Sandbox reconciliation does read
rows, but only from a disposable copy and only inside deterministic code, never through MCP.

## Evaluation
`test_adapter_has_no_row_fetch_api`, the SQL guard tests, G17 (canaries never leak) and G16
(injected values never leave the adapter), and `tests/security/test_final_security.py` (unknown labels
including varied-case names, registered schema narrowing, and false read-only verification).
