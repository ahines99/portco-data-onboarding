# Audit remediation — 2026-10-11

This record covers the [ten-agent audit of 2026-10-10](AUDIT-2026-10-10.md). That audit reviewed
commit `e1f8e36`. Its reports, probes and evidence in [audits/2026-10-10](audits/2026-10-10/README.md)
are kept unchanged as the "before" state.

All 23 numbered findings (A01–A23) have been fixed, along with:
- the PostgreSQL lease-claim race;
- the performance items PERF-1 to PERF-5;
- the test-assurance items T1, T2 and T4;
- the documentation repairs DOC-01 to DOC-04;
- the delivery items DEL-01 to DEL-04.

Every reproduced defect has a regression test at the boundary the audit used. Each test failed on
the audited code and passes now. Earlier failed benchmark results and historical evidence are not
rewritten.

The work was split by file ownership:
- a lead agent: engine, workflow, financial and mapping fixes, and integration;
- three helper agents: ingestion; telemetry and operations; evaluation, CLI, documentation and CI.

At the close of the original 2026-10-11 local remediation session, nothing had been pushed or released.
That is a historical checkpoint; [release status](RELEASE-STATUS.md) records current publication and CI evidence.

## Phase 1 — financial and authority integrity

| Finding | Fix | Regression evidence |
|---|---|---|
| A01 Noncanonical categories became zero revenue | `FieldDef.allowed_values` makes closed domains such as account types executable contracts. Aggregate-only checks (`domain_conformance`, `excess_scale_count`) feed `src/services/value_contracts.py`. NULL or unknown classifications make dependent metrics `NEEDS_EVIDENCE`. Case/whitespace variants count only with the reviewer-approved `normalize_category` transform. The generated `accepted_values` list is the canonical domain, not the observed labels. Reconciliation independently fails `domain:gl_account.account_type`. | `tests/test_audit_2026_10_financial.py` covers `Revenue`, `REVENUE`, trailing space, an unknown code and NULL; balance-sheet labels still pass; reviewed normalization passes; reconciliation fails closed independently. Covered by dbt-backed slow tests. |
| A02 Rejected relationship resurrected | An ontology lookup is generated only when an accepted N:1/1:1 join links exactly those key columns. Otherwise the dependent metrics are `NEEDS_EVIDENCE` ("no approved relationship"). The reconciliation reference uses the same approval contract. | Same file: rejected, absent and approved relationship cases. |
| A03 Generic surrogate keys auto-joined | Same-name generic key-to-key matches between entities with no ontology relationship are never proposed. Other same-name generic keys get `GENERIC_KEY` review. Joins whose endpoint entities are below HIGH confidence get `ENTITY_UNCERTAIN` review. Near-tied targets are ambiguous even on exact name matches. | The audit's customer/vendor reproduction keeps all three customers and creates no join; uncertain-entity joins require review. Frozen v1/v2 results are unchanged (32/33 and 42/52 correct, joins 3/3, both safety gates pass). |
| A04 Cached generation bypassed revoked approval | `StepSpec.precondition` re-checks current mapping approvals before a cached bundle is reused. If authority has lapsed, the run rewinds to the mapping-review gate (`authority_lapsed`) instead of advancing. | `tests/test_audit_2026_10_workflow.py`: revocation and expiry through the public service; a valid approval still reuses the identical bundle. |
| A05 Stale worker adopted its successor's lease | `StepContext.execution_owner` carries the claim token fixed at claim time. Every step start, reuse, pause and publication fence checks it under the run lock; a stale worker raises `LeaseLost`. | Deterministic takeover through `engine.run`: no publication row or files, the successor's cursor and lease are untouched, and the successor finishes exactly once. |
| Lease claim race (PostgreSQL) | `claim` locks the row and also requires the observed lease to still be expired, so a renewal committed in between leaves no matching row. | A stale snapshot plus a concurrent renewal is rejected with `Conflict` (SQLite). The PostgreSQL variant is CI-only. |

## Phase 2 — reliable boundaries

| Finding | Fix | Regression evidence |
|---|---|---|
| A06 Trace/log egress of exception text | Spans no longer record raw exceptions; they keep only a safe type and code. An exporter-boundary sanitizer masks attributes, events, links and status. A log-record factory masks messages, arguments and tracebacks for every handler, including SDK, uvicorn and Rich. | `tests/security/test_telemetry_egress.py`; decoded OTLP failure payload in `tests/test_otlp_export.py`. |
| A07 SQL guard CTE scope | Lexical CTE scope with declaration order. Self and forward references count as physical tables; recursive CTEs are rejected. | Both audit queries are rejected against real DuckDB (`tests/test_ingestion_audit_fixes.py`). |
| A08 Source work before authorization | `ConnectionRegistry.owner()` reads only server-owned metadata (`resolve_csv_owner` for CSV). `start_run` authorizes first, then resolves in a worker thread. | A denied tenant creates no fixture file and triggers no resolution (`tests/test_audit_2026_10_runtime.py`); CSV owner lookup never hashes or opens the snapshot. |
| A09 Expired approvals poisoned provenance | Mapping-review provenance lists only the valid approvals whose decisions won (`decision_sources`). | Workflow regression: an expired partial approval plus a fresh replacement allows generation. |
| A10 Expiry stranded a renamed publication | A prepared operation whose final directory is visible is reconciled to `complete` after its exact files are verified (`publication_recovered`). New side effects still require current certification. | Crash after rename, then expiry: recovered. Expiry before publish, and prepared-but-never-renamed: still denied. |
| A11–A14 CSV registration defects | Case-fold collisions, oversized receipts, sub-microsecond timestamps and reserved schema names are all rejected before staging. Category domains are deduplicated and bounded. | `tests/test_ingestion_audit_fixes.py`. |
| A15 Row-level money rounding | Amounts with nonzero digits beyond cents, or fractional minor units, make dependent metrics `NEEDS_EVIDENCE` (`PRECISION_EXCEEDS_CENTS`). Minor-unit scaling is exact decimal multiplication. | Sub-cent and exact-scaling tests in the financial suite. |
| A16 Evaluation gate population | Full runs require every pinned case ID, a per-dimension check floor and known dimensions. Partial runs are labelled partial. | `tests/test_eval_regressions.py`, including the audit's probe inputs. |
| A17 Alembic `%` URLs | Shared `escape_alembic_url`. Credentials are scrubbed from migration failures; migration has connect, lock and statement deadlines. | `tests/test_migrations_cli.py` runs the real Alembic CLI. |
| A18 Blocked resource reads unaudited | The run is derived from the `run://`, `evidence://` or `finding://` URI, tenant-checked, and audited once. | Telemetry egress tests. |
| A19 Judge rerank kept stale metadata | One finalization routine recomputes score, PII handling, transform, value contract and reason codes for whichever target is selected. | PII-target rerank (direct, and through the workflow on fixture B). |
| A20 `run_sandbox_tests` published | Named MCP capabilities are server-side bounded: no work past their phase, and never into publication. `resume_run` stops before publication; only `publish_run` publishes. | `tests/test_audit_2026_10_capabilities.py` checks publication rows and directories. |
| A21 Zero attempts stranded RUNNING | Positive, finite bounds on all execution settings. The engine never leaves a finished worker's run in RUNNING. | Settings bounds and engine invariant tests. |
| A22 CLI exit status | `run`, `resume` and `rerun` exit 1 on FAILED and 4 on CANCELLED; inspection commands keep exit 0. `portco rerun --reopen-reviews` exposes reopening reviews. | `tests/test_cli_exit_codes.py`. |
| A23 Certification decision strings | `bundle_decision` and `metric_decisions` are typed `approve`/`reject` enums in the tool schema. | An invalid value returns a validation error, not INTERNAL, and no approval is written. |

## Phase 3 — measured performance

All figures are local, shared-host observations, not capacity claims.

- **PERF-1:** PostgreSQL extraction fetches bounded 32-row batches instead of one round trip per row. The batch count is verified with a counting cursor; there is no local remote-latency run.
- **PERF-2:**
  - Workflow driving runs on a worker thread with its own event loop.
  - Status and list reads use `Store.read()`, a deferred SQLite transaction on WAL, so they never queue behind the writer.
  - Tests check that a status read completes while another writer holds the lock, and that the engine runs off the server loop.
- **PERF-3:**
  - CSV import keeps the strict Python validation, then bulk-loads a canonical staged file. The load connection can read only that file.
  - 20,000 rows: 36.1 s → 0.20 s. 250,000 rows: about 1.2 s.
  - Values are identical to the previous path except one: the old path stored `1E+2` in a `DECIMAL(18,2)` column as `1.00`, a silent corruption that is now fixed.
- **PERF-4:**
  - Connection policy (which re-verifies the snapshot digest) is resolved once per workflow invocation rather than once per input hash.
  - Table metadata is cached, and the schema allowlist is still checked on every access.
- **PERF-5:**
  - Subscription reconciliation is bounded to 600 months; a longer history fails visibly as `horizon:subscriptions`.
  - Python-side streaming of reconciliation rows and sharing of monthly snapshots remain open. The bound removes the unbounded expansion, but peak memory at the 250k-row limit has not been measured.

## Documentation, delivery and assurance

- DOC-01 to DOC-04: environment-correct commands; the publication contract in the schema-profiling Skill; reason-code guidance (including the new value-contract and join codes) enforced by `tests/test_skill_contracts.py`; dated roadmap banners pointing to [release status](RELEASE-STATUS.md).
- DEL-03:
  - Actions are pinned to full SHAs, and container inputs to digests.
  - Dependabot keeps the pins current.
  - `tests/test_delivery_pins.py` guards the pins.
- DEL-04:
  - The image's health check and command share `PORT`.
  - A `production-smoke` CI job boots the real `src.serve` entry point with JWT and PostgreSQL over TLS. Its HTTP and MCP assertions run locally against SQLite; the PostgreSQL part runs only in CI.
- T2: G17 now checks failure telemetry (spans, logs, stderr) with exact canaries, and its title states the surfaces it covers.
- T4: Evaluation reports carry provenance (commit, dirty state, input digests, runtime, selection).

## Original 2026-10-11 verification limits

At that checkpoint, the following had not been executed for the remediation:
- PostgreSQL integration tests, including the lease race;
- the production-smoke job;
- the container tests, including the non-default `PORT` step;
- Dependabot.

The original session performed no push, release, deployment, paid API call or human study. Its deferred
recommendations were:
- a freshly authored, frozen source-family corpus (audit phase 4);
- a stateful property test of the review, revoke, expire and claim sequences;
- reconciliation streaming and benchmarks at the 250k-row limit;
- GL currency contracts.

## Follow-up — 2026-10-16: concurrent runs and cancellation

Review of the remediation found two regressions in its performance changes: a connection-policy cache
stored on the shared engine could be cleared by a concurrent run, and shielding a whole workflow on a
worker thread prevented request cancellation or shutdown from interrupting it.

- The cache now uses an invocation-local `ContextVar`. Concurrent workflows keep separate policies and
  reverify their own source once per invocation.
- Request cancellation is forwarded to the worker's event loop. An interrupted owned run becomes
  PENDING, its in-flight attempt becomes cancelled, and its lease is released so it can be resumed.
  Operator cancellation first commits terminal CANCELLED, then signals local execution. Persisted
  status and immutable owner tokens continue to fence other workers and publication.
- Cancelling initial source resolution returns without creating a workflow run.
- dbt output collection polls for cancellation and timeout and kills/reaps the process tree. Other
  synchronous Python steps may finish in the background, but their late results cannot persist.
  Adapters close on the step's owning thread after its operation exits.
- A real subprocess regression exposed a remaining shutdown defect: the event loop exited, but the
  interpreter waited for AnyIO's non-daemon step thread. Workflow driving and source resolution now
  use explicit daemon threads, preserving tracing context and the usual capacity limit. A bounded
  two-second handshake gives orchestration time to fence its attempt and release its lease; step
  cancellation permits up to one second for cooperative cleanup such as terminating dbt. An
  uninterruptible synchronous call can no longer hold interpreter shutdown open.

`tests/test_workflow_concurrency.py` adds ten regressions: deterministic overlapping policy resolution;
two simultaneous discovery workflows through the public service; cancellation during source resolution;
request cancellation, task-group shutdown and operator cancellation mid-step; and real subprocess
cancellation and timeout; actual interpreter shutdown with a blocked 30-second step; and service
shutdown that reaps its dbt subprocess before returning. The mid-step tests prove the caller returns before the blocked step does,
the next step does not run, no late result is recorded, cleanup stays on the owning thread, and a
successor can finish the resumed run before the abandoned step returns without being overwritten.

Local Windows validation for this follow-up:

- The engine lease, October workflow/runtime, production runtime, publication recovery and concurrency
  suites passed before the process-shutdown follow-up: **120 passed, 1 skipped**.
- The final concurrency suite passed: **10 passed**. The real-interpreter shutdown test was first
  observed failing with `LOOP_EXITED` printed while the process remained alive past its eight-second budget.
- After the daemon-thread fix, the concurrency, October runtime and engine-lease suites passed together:
  **66 passed**.
- Ruff check and format check passed for the changed implementation/test files.
- Mypy passed for `src/workflows` and `src/services/sandbox.py` (**8 source files**).

These are local results, not a substitute for hosted CI. The skipped test is the PostgreSQL-specific
case; current hosted checks and release publication belong in [release status](RELEASE-STATUS.md).
