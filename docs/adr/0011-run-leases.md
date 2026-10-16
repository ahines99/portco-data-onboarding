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
- Cancelling a running run is allowed. After committing CANCELLED, the service signals its active
  local worker to interrupt orchestration. Workers in other processes observe the persisted status
  at the next step boundary. A step that finishes after cancellation cannot persist its result.
- Any unexpected engine exception fails the run as INTERNAL, and the lease is released in `finally`.
- Every status change goes through `src/domain/run_states.py`. CANCELLED is terminal, and a
  completed run can only be reopened by `rerun_from`.
- Step input hashes include all source implementation, ontology, dbt templates, the dependency
  lockfile, semantic configuration, judge identity and connection policy. Resume also rechecks
  skipped upstream steps, rewinds at the first mismatch and revokes affected approvals.

- Amendment 2026-10-11 (audit A05 and the claim race): the claim token is immutable for the
  worker's lifetime and travels in `StepContext.execution_owner`. Step start, reuse, pause and
  publication fences compare against it under the run lock, never against a fresh database
  snapshot, which could carry a successor's token. `claim` locks the row and also requires the
  observed lease to still be expired, so a renewal committed between read and update is not
  overwritten.
- Amendment 2026-10-11 (audit A04): a step may declare a current-authority precondition that runs
  before a cached output is reused. Artifact generation re-checks its mapping approvals and, if
  they were revoked or expired, rewinds to the mapping-review gate.
- Amendment 2026-10-16 (concurrency and interruption): the connection-policy cache belongs to one
  invocation through a `ContextVar`; another workflow cannot replace or clear it. A cancellation
  event bridges the request task to the worker thread's independent event loop. Request cancellation
  and server task-group shutdown interrupt the step, record the attempt as cancelled, release its
  lease and leave an owned RUNNING run PENDING for resume (`run_interrupted`). An explicit operator
  cancellation remains terminal CANCELLED. Cancellation during initial source resolution creates
  no run. Current ownership checks prevent interruption from changing a successor's run state.

## Alternatives considered
- `SELECT ... FOR UPDATE` held for the whole run: rejected. It would hold a transaction open for
  minutes (dbt builds), and SQLite has no row locks.
- An external queue or lock service (Redis, a job runner): rejected for the MVP. It adds
  infrastructure the one-command demo does not need, and the database is already the source of
  truth.
- Advisory locks: Postgres-only, which does not work with the SQLite demo store.

## Consequences
A run stuck behind a crashed worker waits at most one lease period before it can be resumed.
The interruption watcher checks the request event every 50 ms when its event loop can run; this is
not a hard deadline for synchronous database or filesystem calls. The dbt runner checks cancellation
at most every 100 ms while waiting for output, and kills and reaps its process tree on cancellation
or timeout. Other synchronous Python steps cannot be forcibly killed: an abandoned thread may run
until its own bounded operation ends, but its result cannot persist. Its adapter is closed on that
same thread after the operation exits, avoiding concurrent close/use. Publication additionally checks
attempt cancellation, deadline and ownership around its filesystem side effects, as described in
[ADR-0012](0012-recoverable-publication.md).

## Evaluation
`tests/test_engine_leases.py`: the table-driven transition tests, exclusive claims, recovery of an
expired lease, cancellation during a step, crash-while-persisting, the timeout validator, and
pipeline-version sensitivity.

`tests/test_workflow_concurrency.py`: a deterministic overlapping cache miss and second-workflow
exit; simultaneous full discovery workflows on one service; cancellation during source resolution;
request cancellation, server task-group shutdown and operator cancellation during an unfinished
step; late-result fencing, adapter cleanup ownership and resume; real subprocess cancellation and
timeout cleanup.
