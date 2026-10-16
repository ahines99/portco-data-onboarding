# Agent 02: workflow correctness, leases, approvals and publication recovery

Audit date: 2026-10-10. Read-only review of tracked implementation; no tracked changes. Four isolated reproductions executed using `.venv/Scripts/python.exe`. Preserved runnable script: `var/audit-2026-10-10/agent-02-repros.py`; observed output: `agent-02-repros.json`. Service state and publication directories are under the temporary root recorded in that JSON. The coordinator owns full-suite verification.

## Verified defects

### W02-1 — P1: A resumed stale worker adopts its replacement's lease token and can publish

Locations: `src/workflows/base.py:284`, especially the unguarded run load at 287 and `StepContext(run=run)` at 308; `src/workflows/contracts.py:48-59`; publication boundary at `src/services/publish.py:267-288`.

The engine's immutable local `owner` identifies the original claim, but `_run_step` reloads the current database run without checking that owner. It then places the reloaded run, including its possibly replaced `lease_owner`, in the step context. Publication fences compare the database owner against `ctx.run.lease_owner`, so the old worker can present its replacement's token. Only `_persist` compares against the original local owner, after filesystem publication has already completed.

Feasible public-engine interleaving: old worker A successfully renews in `_heartbeat`; A is descheduled longer than the lease; B calls resume and claims the expired lease; A wakes before its `_run_step` loads the run. A reads B's token, publishes as B, then discards the step result as A. This is a concurrency safety defect, not an externally callable internal-method exploit. A long process pause is a prerequisite; the reproduction injects the scheduling boundary instead of sleeping through the production lease duration.

Reproduction uses actual `engine.run` with valid seeded upstream hashes and the real publication service. A heartbeat hook returns A's successful heartbeat result after expiring the lease and claiming `replacement-worker`. Observed: old owner `old-worker#6883ed76f617`; final owner `replacement-worker`; workflow still `running`; publication `complete`; final directory exists. An additional direct `_run_step` reproduction returned `cancelled` after creating the final publication.

Fix: explicitly pass the original execution token into `StepContext`; never derive authority from a fresh database snapshot. Lock and validate owner, running status and expiry before mutating/reusing/starting a step. Keep the final publication fence, comparing against the original token. Include owner validation in stop-after transitions and other state mutations.

Verification: preserve the heartbeat/takeover deterministic interleaving for SQLite and PostgreSQL; assert A cannot start the step, create a prepared publication, rename files, alter B's cursor, or pause B. Let B finish and assert exactly one completed attempt/publication.

### W02-2 — P1: Cached artifact generation bypasses the current mapping approval check

Locations: `src/workflows/base.py:291-296`, `src/workflows/primary.py:46`, `src/services/generation.py:639-644`, `src/domain/project_models.py:308-309`.

Artifact generation is reusable, and the engine returns a matching completed attempt before executing `generate_artifacts`. Current mapping approvals are checked only inside that function. Approval revocation/expiration does not affect the step's input hash; `ResolvedMapping.content_hash()` deliberately excludes approval IDs. Therefore cache reuse skips the fail-closed approval guard.

Reproduction uses public `OnboardingService` methods: start fixture A, submit mappings, resume through artifact generation, revoke the mapping approval in storage, then `rerun_from(ARTIFACT_GENERATION, stop_after=ARTIFACT_GENERATION)`. Directly calling the actual generation function against that same state raises `ApprovalRequired`; the engine instead reuses the exact previous step ID and advances to `automated_tests` with status `pending`.

Impact: workflow authorization depends on whether a prior cache entry exists. A revoked or expired mapping can pass the generation gate on rerun, contrary to the generation policy. This finding verifies gate bypass; it does not claim the separate human certification requirement can be bypassed.

Fix: separate authorization/preconditions from expensive computation and run them before accepting a cached output. Including approval IDs in a hash alone is insufficient because expiration happens without changing IDs. Consider a gate-specific reuse validator or always-executed generation precheck that retains deterministic content caching.

Verification: real service reruns after revocation and expiry must refuse generation reuse or return to review; valid unchanged approvals must still reuse byte-identical files. Cover newly issued equivalent approvals and an operator reopening a review.

### W02-3 — P2: Historical expired approvals poison otherwise valid replacement mapping decisions

Locations: `src/services/gates.py:215-223`, `src/services/approvals.py:37-45`, `src/services/generation.py:641-644`.

`effective_decisions` ignores expired approvals, but mapping review's `approval_ids` includes every same-subject unrevoked approval, including expired ones. Generation requires every ID in that output to remain valid. If an earlier partial approval expires while review is pending, a valid replacement decision satisfies the gate but generation still rejects its historical expired predecessor.

Reproduction: same-subject expired and fresh approvals for a row-filter review. Mapping review returns `ok`, includes both IDs, and generation raises `ApprovalRequired`. No data adapter or dbt execution is needed.

Fix: build provenance from valid approvals actually contributing the effective decisions, ideally tracking the winning approval per item rather than all historical approvals. At minimum use the same `is_valid(a, subject)` predicate in the IDs list.

Verification: partial approval expires, remaining/replacement decisions are submitted, and generation succeeds with only the contributing current IDs. Preserve the failure for revoked/expired approvals that still supply an effective dependency.

### W02-4 — P2: Approval expiry strands an already-renamed publication after a crash

Locations: `src/services/publish.py:38`, `src/services/publish.py:270-288`, `src/workflows/facade.py:223-230`.

The existing recovery protocol handles rename-before-database-commit by retaining a prepared operation and verifying the final directory on retry. However, `publish_bundle` requires currently valid certifications before it even looks up that operation. If the service is down past the certification TTL, a directory already made visible while authorized cannot be reconciled. Cancellation is also rejected because the final directory exists.

Reproduction: inject `PublicationRepository.complete` failure after the real rename, expire the approval records, retry publication, and cancel. Observed: recovery `ApprovalRequired`; cancellation `Conflict`; publication row remains `prepared`; published directory exists. This reproduces a liveness/durable-outcome gap, not publication without prior certification. Reopening/reviewing may produce another version but does not reconcile the original prepared outcome.

Fix: explicitly distinguish authorization to perform a new side effect from reconciliation/acknowledgment of an already-finalized historical side effect. Persist sufficient authorization/finalization evidence and verify exact bytes before recording a recovered historical outcome. Keep new publication fail-closed. Do not simply ignore expired approvals on unfinalized operations.

Verification: crash at every reservation/staging/rename/commit boundary, let approvals expire or be revoked, then resume. Every visible final directory must reconcile to a durable truthful outcome; unfinalized work must still require current authorization. Exercise this on both databases.

## Additional source-confirmed risk, not integration-reproduced

**W02-R1 — P2 PostgreSQL claim/renew race:** `src/adapters/repositories.py:148-170`. `claim` reads lease expiry without `FOR UPDATE`, checks it in Python, and CASes only `(status, lease_owner)`. If claimant A reads an expired lease, old worker B renews it, then A executes its update, B's status and owner remain unchanged so A overwrites a now-live lease. SQLite's `BEGIN IMMEDIATE` excludes this interleaving; the PostgreSQL backend does not. No PostgreSQL test database was configured for this agent, so this is a traced race, not a live PG reproduction. Fix with a short row lock plus in-transaction check, or include expiry/live-lease predicates in the atomic claim update. Verify with barriers around claim read, competing renew commit and claim update.

PostgreSQL documents that Read Committed updates re-evaluate their WHERE clause against the updated row; a renewal is excluded only if the predicate actually includes the lease state. [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html).

## Performance and durability observations

- `Store.tx()` uses `BEGIN IMMEDIATE` for every SQLite transaction (`repositories.py:751-758`), including reads. This intentionally prevents audit-chain races, but serializes status/resource reads with writes and can cause head-of-line blocking. Introduce an explicit read-only transaction API for pure readers while preserving immediate transactions for read-modify-write paths; benchmark concurrent status reads during publishing. SQLite permits multiple readers but a single writer, and immediate transactions acquire the write transaction up front. [SQLite transactions](https://sqlite.org/lang_transaction.html).
- Publication correctly uses a durable prepared operation and idempotent replay. Treat the filesystem/database boundary as an explicit recovery state machine; dual-write failure recovery needs both an immutable operation identity and durable outcome reconciliation. This is consistent with the dual-write motivation for a transactional outbox, although the present filesystem protocol is not itself a messaging outbox. [AWS transactional outbox guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html).
- `abandon_on_cancel=True` cannot stop synchronous worker threads. Publication adds cooperative cancellation/deadline checks, which is appropriate; other lengthy worker actions may continue until their underlying operation ends. Resource closing/retry overlap deserves targeted stress testing but was not reproduced as a defect here. [AnyIO worker-thread API](https://anyio.readthedocs.io/en/stable/api.html#anyio.to_thread.run_sync).

## Strengths

- Domain state transitions are explicit and centrally checked; cancelled runs are terminal.
- Step outputs, findings, evidence metadata and audit events use a transaction; blob reads verify content hashes.
- Review writes lock the run and validate run/gate/subject together; stale-packet regression tests exercise actual SQLite and PostgreSQL locks.
- Certification binds tests, waivers, findings and evidence, rather than only bundle bytes.
- Publication reloads all certification decisions at finalization, contains paths, verifies the full published file set, reserves unique company/version keys, and handles rename/commit crashes.
- Cancellation and publication serialize on the run lock; timeout fencing and concurrent publication/audit tests are materially stronger than typical demo implementations.
- Existing migration test rehearses publication lifecycle migration with real certified PostgreSQL data; the audit findings are edge-case gaps within a substantial recovery design.

## Scope decisions

Immutable imported CSV/PostgreSQL snapshots make live-source cache freshness concerns substantially narrower than a general synchronization product. No live CDC or automatic source refresh deficiency is claimed. No broad fsync/power-loss guarantee was established, so process-crash recovery tests should not be described as proving host-power-loss durability. No changes were made to tracked code and no full suite was run by this agent.
