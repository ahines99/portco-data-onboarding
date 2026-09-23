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
  test report (results, reconciliation outcomes, bundle and source fingerprint), or decline, which
  fails the run. The gate fails closed: a build that did not pass but named no failing check (for
  example dbt exiting with status 2) still needs a waiver of `dbt_exit_<code>`.
- **Gate B, `human_certification`**: always runs before publish. Metrics can be certified
  individually; a rejected metric also excludes the metrics derived from it.

Gates are workflow steps that re-evaluate approvals each time the run resumes, so resuming never
recomputes earlier steps.

## Alternatives considered
- One gate before publish only: rejected. A wrong mapping would be discovered after generation and
  sandbox testing, which wastes a build and buries the decision among test results.
- One gate per step: rejected as review fatigue. Most steps are deterministic and evidence-backed.
- Auto-waiving known-flaky checks: rejected. Every waiver is a human decision tied to a report.

## Consequences
A run can pause up to three times. Each pause is resumable without recomputation, and every pause
names its pending items with evidence ids, so the reviewer never works from free text.

## Evaluation
G26 (resume skips steps 1-5), G28 (a test failure blocks publish), `tests/test_workflow.py`.
