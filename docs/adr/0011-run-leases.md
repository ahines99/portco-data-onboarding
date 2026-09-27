# ADR-0011: Runs advance only under an execution lease; status changes follow a table

- Status: accepted
- Date: 2026-09-23

## Context
The first engine set a run to RUNNING with a plain update. Two `resume` calls could therefore both
advance the same run. Cancelling a running run was impossible, and a worker that crashed left the
run stuck in RUNNING with no way to recover it. Status changes were also not validated, so, for
example, a cancelled run could be made RUNNING again.

## Decision
- `workflow_runs` carries `lease_owner` and `lease_expires_at`. `RunRepository.claim` is a
  compare-and-set on `(status, lease_owner)`: of two workers that read the same row, exactly one
  update matches. A run can be claimed from PENDING, NEEDS_REVIEW or FAILED, or from RUNNING once
  its lease has expired, which is how a crashed run is recovered (`run_recovered` in the audit log).
- The lease lasts as long as the slowest step's timeout plus a margin, and is renewed before every
  step attempt. The step timeout must exceed the dbt timeout (enforced by a settings validator).
- Cancelling a running run is allowed. The worker notices at the next step boundary, and a step
  that finishes after cancellation is discarded (`step_discarded`), never persisted.
- Any unexpected engine exception fails the run as INTERNAL, and the lease is released in `finally`.
- Every status change goes through `src/domain/run_states.py`. CANCELLED is terminal, and a
  completed run can only be reopened by `rerun_from`.
- Step input hashes include all source implementation, ontology, dbt templates, the dependency
  lockfile, semantic configuration, judge identity and connection policy. Resume also rechecks
  skipped upstream steps, rewinds at the first mismatch and revokes affected approvals.

## Alternatives considered
- `SELECT ... FOR UPDATE` held for the whole run: rejected. It would hold a transaction open for
  minutes (dbt builds), and SQLite has no row locks.
- An external queue or lock service (Redis, a job runner): rejected for the MVP. It adds
  infrastructure the one-command demo does not need, and the database is already the source of
  truth.
- Advisory locks: Postgres-only, which does not work with the SQLite demo store.

## Consequences
A run stuck behind a crashed worker waits at most one lease period before it can be resumed.
Threads abandoned on timeout can keep running until they finish; their step results are discarded
once ownership is lost. Publication requires additional checks around its filesystem side effects,
described in [ADR-0012](0012-recoverable-publication.md).

## Evaluation
`tests/test_engine_leases.py`: the table-driven transition tests, exclusive claims, recovery of an
expired lease, cancellation during a step, crash-while-persisting, the timeout validator, and
pipeline-version sensitivity.
