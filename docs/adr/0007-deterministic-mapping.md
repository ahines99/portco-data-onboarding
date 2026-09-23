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

## Alternatives considered
- LLM-first mapping with human review: rejected. Accuracy could not be reproduced, the model would
  become the system of record, and every run would cost tokens.
- Embedding similarity: deferred. It adds a model dependency for what synonyms and abbreviations
  (`ontology/abbreviations.yaml`) already cover on the fixtures; it could be a scored feature later.

## Consequences
Unknown vocabularies score LOW and go to review until their synonyms are added to the ontology. That
is slower for novel sources, but every mapping decision is explainable from the score components.

## Evaluation
G05 and G06 (top-1 accuracy of 1.00 on fixtures A and B at the time of writing), the calibration
check (HIGH-confidence accuracy of at least 0.95), and the trap cases G10, G11 and G14.
