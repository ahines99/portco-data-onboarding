# ADR-0005: Human gates: mapping review, test-failure waiver, certification

- Status: accepted
- Date: 2026-09-23

## Context
The mission says to route uncertain mappings for review, but the nine-step list only has human
certification near the end. The handoff's approval-gated `generate_dbt_artifacts` implies a pause
before generation.

## Decision
- **Gate A, `mapping_review`**: after canonical mapping, whenever a proposal, row filter or join
  needs review.
- **Test-failures gate**: when sandbox checks fail, a reviewer may waive them against the exact
  failing set and bundle, or decline, which fails the run.
- **Gate B, `human_certification`**: always runs before publish. Metrics can be certified
  individually; a rejected metric also excludes the metrics derived from it.

Gates are workflow steps that re-evaluate approvals each time the run resumes, so resuming never
recomputes earlier steps.

## Evaluation
G26 (resume skips steps 1-5), G28 (a test failure blocks publish), `tests/test_workflow.py`.
