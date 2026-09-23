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
safe-character check and the prompt-injection heuristics. Every query is parsed by the SQL guard:
a single SELECT, allowlisted schemas only, and no file or table functions.

## Consequences
Some heuristics are harder without sampling, which is acceptable. Sandbox reconciliation does read
rows, but only from a disposable copy and only inside deterministic code, never through MCP.

## Evaluation
`test_adapter_has_no_row_fetch_api`, the SQL guard tests, G17 (canaries never leak) and G16
(injected values never leave the adapter).
