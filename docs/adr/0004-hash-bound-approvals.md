# ADR-0004: Approvals are verified server-side and bound to content hashes

- Status: accepted
- Date: 2026-09-23

## Context
The handoff sketch `generate_dbt_artifacts(mapping_id, approved: bool)` lets the caller assert its
own approval. Any model can pass `approved=True`, so a flag like that is not a control.

## Decision
Tools take an `approval_id`. The server looks it up and checks that it is not revoked or expired,
that it belongs to the run, and that its `subject_hash` equals the current content hash of what it
approves: the review items for the mapping review, the whole sandbox test report for a test-failure
waiver, and the certification packet's review hash (the bundle manifest, test report and metric
list, excluding the reviewer's own decisions) for certification. When the subject changes, stale
approvals are revoked (a new row state, never an edit or a delete) and an
`approval_invalidated` audit event is written.

## Alternatives considered
- Boolean flag: rejected, because it is caller-asserted.
- Approval tied only to the run: rejected, because the content could change after approval.

## Consequences
- Any change upstream of a gate (a remapped column, a new test result) forces a new review; this is
  intended, and the reviewer sees exactly what changed.
- Approval rows are append-only and carry the revocation reason, so the audit trail explains why an
  approval stopped counting.
- Clients must fetch the current subject hash before approving (`list_pending_reviews` returns it).

## Evaluation
G22 (publish without certification is denied), G24 (a mapping change after certification revokes
it), and the forged `approval_id` tests in `tests/test_mcp.py`.
