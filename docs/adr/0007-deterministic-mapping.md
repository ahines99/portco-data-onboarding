# ADR-0007: Canonical mapping is deterministic; a model may only reorder or abstain

- Status: accepted
- Date: 2026-09-23

## Context
"Do not let the LLM become the system of record." Mapping quality also has to be measurable.

## Decision
Mapping scores combine synonym and token/character name similarity, type compatibility, entity
context and join-inferred key hints. The weights live in `ontology/scoring.yaml`. Proposals that are
uncertain, metric-bearing, PII, conflicting, unit-mismatched or semantic traps always go to review.
The optional judge (ADR-0010) can reorder deterministic candidates or abstain, and nothing else.

## Evaluation
G05 and G06 (top-1 accuracy of 1.00 on fixtures A and B at the time of writing), the calibration
check (HIGH-confidence accuracy of at least 0.95), and the trap cases G10, G11 and G14.
