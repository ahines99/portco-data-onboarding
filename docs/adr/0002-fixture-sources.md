# ADR-0002: DuckDB fixture sources behind a SourceAdapter protocol

- Status: accepted
- Date: 2026-09-23

## Context
Handoff task 3: "Implement one adapter using fixtures, not live credentials."

## Decision
Synthetic portfolio companies are generated deterministically into DuckDB files (`src/fixtures/`),
each with a committed ground truth that records the true keys, joins, mappings, PII columns, planted
traps and expected metric values. All source access goes through the `SourceAdapter` protocol. A
Snowflake adapter is v0.2 work against the same protocol.

## Consequences
Everything is reproducible and can be scored. Live-warehouse behaviours (network, auth, quotas) are
out of scope until v0.2.

## Evaluation
`tests/test_fixtures.py` (reproducible content digest) and the golden tests.
