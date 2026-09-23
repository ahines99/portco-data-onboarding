# ADR-0004: Approvals are verified server-side and bound to content hashes

- Status: accepted
- Date: 2026-09-23

## Context
The handoff sketch `generate_dbt_artifacts(mapping_id, approved: bool)` lets the caller assert its
own approval. Any model can pass `approved=True`, so a flag like that is not a control.

## Decision
Tools take an `approval_id`. The server looks it up and checks that it is not revoked or expired,
that it belongs to the run, and that its `subject_hash` equals the current content hash of what it
approves: the mapping set for the mapping review, the bundle manifest for certification. When the
subject changes, stale approvals are revoked (a new row state, never an edit or a delete) and an
`approval_invalidated` audit event is written.

## Alternatives considered
- Boolean flag: rejected, because it is caller-asserted.
- Approval tied only to the run: rejected, because the content could change after approval.

## Evaluation
G22 (publish without certification is denied), G24 (a mapping change after certification revokes
it), and the forged `approval_id` tests in `tests/test_mcp.py`.
