# ADR-0003: The source adapter exposes aggregate reads only

- Status: accepted
- Date: 2026-09-23

## Context
"No raw PII in model context" has to hold by construction, not by convention.

## Decision
`SourceAdapter` has no row-fetch method. Profiling, PII detection (regex and Luhn counts computed in
SQL), containment and conflict checks all run as SQL aggregates inside the adapter; only counts,
ratios, and min/max of numeric and date columns leave it. The one narrow exception is
`low_cardinality_values`, which returns category labels only after they pass the PII detectors, a
safe-character check and the prompt-injection heuristics. Labels are also withheld for person-like
columns (`owner`, `rep`, `manager`, `name`, `user`, `employee`, `contact`, ...) and whenever a value
looks like a personal name (two or more capitalised words). Every query is parsed by the SQL guard:
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
Some heuristics are harder without sampling, which is acceptable. The name heuristic also withholds
some genuine labels (e.g. "Deferred Revenue"); the only cost is a missing `accepted_values` test. Sandbox reconciliation does read
rows, but only from a disposable copy and only inside deterministic code, never through MCP.

## Evaluation
`test_adapter_has_no_row_fetch_api`, the SQL guard tests, G17 (canaries never leak) and G16
(injected values never leave the adapter).
