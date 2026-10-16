# Agent 4/10 — performance, resource use, and scalability audit

Audit date: 2026-10-10. Scope: read-only code review, official documentation, bounded synthetic mechanism benchmarks; no tracked source edits. The parent ran the full suite/evaluation concurrently. All timings are shared-host observations, not isolated capacity claims, cloud measurements, SLA predictions, or production load tests.

## Findings, ordered by practical priority

### PERF-1 — P1 for remote ingestion: a server-cursor network round trip for every source row

Location: `src/adapters/postgres_source.py:252` and `:260`.

The named Psycopg cursor calls `fetchone()` in its loop. Inspection of installed Psycopg 3.3.6 proves `ServerCursor.fetchone()` invokes `_fetch_gen(1)`, which executes `FETCH FORWARD 1 FROM ...`. Raising `itersize` alone does not change this loop. For N rows the extraction therefore needs approximately N network round trips, before local parsing/import. This makes otherwise valid inputs fail the 120-second default overall extraction budget (`PostgresManifest.total_timeout_seconds`).

Analytical latency floor only, not a remote measurement: 100,000 rows at 1 ms round-trip latency consume roughly 100 s; at 10 ms they consume 1,000 s. With the 250,000-row ceiling, the corresponding floors are 250 s and 2,500 s. Catalog/locking and serialization make actual totals larger. A 120 s budget with 10 ms RTT admits fewer than 12,000 rows even before other costs.

Fix: fetch explicit bounded batches, or use cursor iteration with a chosen `itersize`. Choose batch size from a byte budget and the existing 1 MiB per-row guard; 100 or 1,000 arbitrary worst-case rows would permit ~100 MiB or ~1 GiB payloads, so a smaller/adaptive bound is necessary. Preserve per-row row/byte checks and deadline checks. `fetchmany(32)` reduces fetch round trips by approximately 32x while bounding server-validated payload to ~32 MiB plus object overhead. Consider server-side COPY streaming only after preserving existing type/row-size guarantees.

Verification: add a counting fake server cursor that asserts batches, not N fetches; preserve all boundary/oversize/failure cleanup cases; run a dedicated network-latency integration case with injected 1/10 ms delay. Do not claim these analytical gains as end-to-end speedups.

Primary evidence: [Psycopg server-side cursors](https://www.psycopg.org/articles/2026/08/12/server-side-cursors/) explains that `itersize` controls iteration and fetchone/fetchmany request their explicit row count. [Cursor types](https://www.psycopg.org/psycopg3/docs/advanced/cursors.html) describes the SQL DECLARE/FETCH mechanism. The installed library source confirms the current environment rather than relying exclusively on newer online documentation.

### PERF-2 — P1 responsiveness: synchronous database waits can freeze every MCP request

Locations: `src/capabilities/tools.py:112` (async status handler calls synchronous facade), `src/workflows/facade.py:129` (get_run transaction), `src/adapters/repositories.py:752` (every Store.tx uses SQLite BEGIN IMMEDIATE), `src/adapters/db.py:190` (30-second SQLite lock wait), and `src/workflows/base.py:286` (synchronous transaction in async workflow).

The steps themselves are offloaded to a worker, but async orchestration, status/health/review handlers, database persistence, blob loads and hashing remain synchronous. A database lock/network wait blocks the event loop, so cheap status, health and cancellation calls stall with it. SQLite read-only facade operations additionally reserve a writer lock, defeating WAL reader/writer overlap. The expensive-tool capacity limiter cannot prevent this because the wait happens on the event-loop thread and status calls are outside that limiter.

Measured reproduction using the actual `make_engine` and `Store.tx`: hold a separate SQLite writer for 350 ms, invoke the synchronous transaction from an async task, and run a 20 ms heartbeat concurrently. Transaction wait was 431.888 ms; the longest heartbeat gap was 431.977 ms. The synthetic contention demonstrates the mechanism, not expected normal traffic. The configured 30 s lock timeout makes much longer stalls possible.

Fix: offload complete synchronous transaction units to a bounded worker pool or migrate the orchestration database paths to async SQLAlchemy; never move a live SQLAlchemy connection across threads. Add explicit read-only transaction/session methods that omit BEGIN IMMEDIATE, retaining immediate writer reservation for mutations/audit chains. Move filesystem hashing and artifact validation outside write transactions and off the event loop while preserving state rechecks before commit. Keep existing CAS/lease and append-chain locking.

Verification: repeat the contention reproducer with an unrelated status/health heartbeat and assert it remains responsive; retain audit concurrency and lease-race tests. Include PostgreSQL response delay as a separate integration scenario; the current reproduction used SQLite only.

Reproducer: `agent04_eventloop.py`; raw data: `agent04_eventloop.json` in this directory. Run `.venv/Scripts/python.exe var/audit-2026-10-10/agent04_eventloop.py`.

### PERF-3 — P2 throughput: CSV ingestion spends substantial time crossing Python/engine value boundaries

Location: `src/adapters/csv_source.py:201` and `:204`.

Import validates rows and inserts through 1,000-row `executemany` batches. The batch size reduces Python call count but does not turn this into native CSV/vector ingestion. Both direct CSV onboarding and PostgreSQL's staged CSV import use this path. The transaction is already correctly batched; adding another transaction is not the fix.

Measured synthetic kernel: 5,000 rows with BIGINT/VARCHAR/DATE/DECIMAL(12,2) took 9.878/10.847 s; 20,000 took 45.763/42.899 s. Both variants validated count, integer sum and exact Decimal sum. Shared host and environment-specific binding behavior mean these should be rerun on an idle host before selecting a throughput budget. Straight-line projection from 20k to the 250k ceiling would be many minutes, but that projection is not a measured maximum-size import.

The actual unmodified `import_csv()` then imported a 677,801-byte, 20,000-row CSV in **42.129 s**, producing a 536,576-byte DuckDB snapshot. This is about 475 rows/s on this shared host. This real-path measurement substantiates the kernel concern without assuming that a kernel-only ratio translates directly to onboarding.

Negative result preserved: replacing `executemany` with four Python parameter lists and SQL UNNEST did not establish a compelling solution. At 5,000 rows it took 9.790/9.743 s; at 20,000 it took 36.363/34.451 s, roughly 1.25x faster by pair means but still slow. Do not adopt that rewrite merely because it looks vectorized; the small shared-host timing difference requires isolated confirmation.

A separate tiny diagnostic isolated 1,000 rows: Python `_cell` validation took 2.780 ms; native DuckDB typed CSV ingestion took 39.714 ms. The native CSV case used a trusted temporary local file and a connection permitting file access, not the importer's restricted external-access connection. It is evidence to investigate native bulk ingestion, not a drop-in production benchmark or completed fix. A StringIO ingestion attempt failed because optional `fsspec` is not installed; no package was installed.

Fix: retain strict Python validation, null sentinel, decimal non-rounding checks, header/order validation and atomic registration; feed a validated, private typed batch/staged file into a native bulk-loading interface. Evaluate Arrow with an explicit dependency or a tightly controlled staged-file path. Do not enable unrestricted external access on the existing general source adapter to gain speed.

Verification: compare typed values and rejects against the current importer including precision/scale, literal `\\N`, empty strings, booleans, malformed dates/timezones, embedded CSV quoting/newlines and encoding. Benchmark 1k/20k/250k in isolation, recording RSS and bytes/rows per second. Raw bounded test: `agent04_bench.py`; results: `agent04_benchmark.json`.

Primary evidence: [DuckDB Python DB API](https://duckdb.org/docs/lts/clients/python/dbapi) explicitly discourages executemany for large inserts and directs readers to native ingestion options.

### PERF-4 — P2 at growing history/width: source/registry checks and metadata scans repeat inside step bookkeeping

Locations: `src/workflows/base.py:118` and `:289`, `src/adapters/csv_source.py:258`, `src/adapters/external.py:470`, `src/services/profiling.py:356` and `:121`, `src/adapters/external.py:307`.

Every `input_hash` resolves the connection. CSV resolution recomputes SHA-256 over the entire snapshot. This happens once per step and for every skipped upstream step checked during resume; `connections.open()` repeats resolution before opening an adapter. In `_run_step` and `_resume_start` these hashes run synchronously inside the database transaction. A legitimate integrity safeguard thus multiplies whole-file reads and extends lock/event-loop hold time. The immutable-source identity should be resolved as an execution-scoped object without silently removing tamper detection.

Metadata overhead also repeats: `describe_table()` returns metadata but does not populate `_tables`; profiling calls it directly, then `row_count()` invokes `_table()` and causes another two-query describe. That is two avoidable catalog queries per table per cold profiling adapter. Connection validation separately fingerprints all rows using `sum(hash(t))`, and profiling later scans for column stats and then one query per nonempty string column for patterns. Column aggregate statistics are already batched across the table, which is good.

Fix: preserve fail-closed validation at explicit execution and publish boundaries, resolve once outside write transactions, and carry a verified immutable source identity into step hashes. If caching integrity, define the operator-owned filesystem threat model and invalidation policy first; mtime alone does not establish tamper-proof contents. Cache returned table metadata, and evaluate batched pattern aggregates across bounded groups of string columns. Keep exact distinct counts where key decisions depend on exact uniqueness; approximate distinct is not an interchangeable optimization.

Verification: instrument source resolutions, whole-file hash calls, bytes hashed and query counts for a complete run plus unchanged resume. Compare resulting input hashes/artifact identities and all tamper detection tests. The benchmark includes a cached 32 MiB whole-file digest and equivalent 8-column separate/batched pattern outputs; use measured results to decide whether more complex aggregation is warranted.

Measured: SHA-256 of a cached 32 MiB file took 24.46/18.37/18.66 ms. This cost is small per call on the audit SSD but repeats on every resolution and grows with snapshot size/slower storage. For 50k rows x8 strings x11 patterns, current per-column calls took 236.59/244.87/232.63 ms versus combined 235.996/235.972/232.983 ms, with equal count outputs. The combined version reduced aggregate queries from 8 to 1 per pass but **did not establish meaningful latency savings** here; treat it as lower-priority query-count simplification until a wider/remote profile shows benefit. The more material concern is blocking hash I/O inside transactions and repeated metadata, not claiming an unmeasured regex speedup.

### PERF-5 — P2 resource ceiling: bounded source input does not bound reconciliation memory or subscription expansion

Locations: `src/services/sandbox.py:195`, `:276`, `:325`, `:491`, `:496` and `src/domain/metrics_reference.py:148`.

`SourceRows._cols` first fetches all rows as Python tuples, then constructs all row dictionaries while the tuple list is live. `_records` constructs another dictionary list and callers then construct dataclass records. Reconciliation and semantic reconciliation reread and re-materialize the same source fields. These paths bypass the adapter's per-query timer; DuckDB source and reconciliation connections have no configured memory/thread limits. The importer caps input at 64 MiB and 250k rows, but Python object expansion and metric month/customer buckets can greatly exceed that input size.

Subscription reference calculators are O(months x subscriptions), and `mrr_by_customer` retains a customer/currency dictionary for every month. `mrr`, `arr`, and `active_customers` recompute those buckets separately; `reconcile` and `reconcile_semantic` repeat them. Month ranges run from the minimum source start date to as_of, with no explicit maximum horizon. A parseable erroneous year 0001 through October 2026 is ~24k months; at 250k rows that is ~6 billion subscription checks per pass, before bucket memory. This is a mathematical workload bound, not a executed stress test.

Fix: fetch/transform rows in bounded batches and accumulate independent reference aggregates; cache only bounded reusable projections. Share one reference month/customer calculation across related metrics within an attempt, or use a verified event-sweep implementation with Decimal arithmetic. Set explicit supported date/horizon and reconciliation budgets, give operator-visible failures for exceeded bounds, and configure DuckDB threads/memory/temp storage by deployment. Preserve independent reconciliation from generated SQL.

Verification: test month-end/exclusive-end semantics, currencies, zero/negative MRR, duplicates, filtering and leap dates against the existing pure reference implementation on small randomized inputs; run bounded size/width/horizon sweeps recording peak RSS, Python allocation and step duration. The current benchmark measures actual `_cols` for 50k rows x8 short strings with tracemalloc (native engine memory excluded; tracing inflates runtime).

Measured `_cols` for 50k x8 short strings retained 34,564,455 Python bytes and peaked at 40,001,288 bytes (~38.15 MiB), before additional mapped records and native DuckDB memory. Its traced elapsed time was 564.65 ms. A 5x row-count projection is roughly 191 MiB peak for this same narrow projection alone; it is explicitly not a measurement at the 250k limit, and wider/more complex values change expansion substantially.

Primary evidence: [DuckDB configuration](https://duckdb.org/docs/current/configuration/overview) documents memory_limit/thread settings and defaults; [DuckDB slow-workload guidance](https://www.duckdb.org/docs/current/guides/performance/my_workload_is_slow) recommends tuning threads/memory to the host. These settings do not bound Python object memory, so streaming/reconciliation limits remain necessary.

## Existing strengths and evidence limits

- The 64 MiB/250k-row import cap, per-query timeout, single expensive HTTP workload limit, one dbt thread, temporary sandbox copy, run leases and input-hash reuse are useful existing guardrails.
- `docs/evidence/benchmark.json` explicitly says its three fixture-A fresh/reused runs are not a scale benchmark. Fresh times 9.740–10.247 s and reused times 0.452–0.538 s demonstrate reuse value only; they do not validate supported ingestion sizes or remote-source performance.
- No remote database latency, production throughput, long-running resource leak, cold filesystem cache or maximum-size end-to-end workload was measured in this audit. No recommendation requires changing audited correctness/security guarantees without regression coverage.
- Benchmark reproducibility note: the initial diagnostic driver omitted bind parameters only in its experimental combined-pattern query, after the insert/import measurements had completed. The driver was fixed and only its remaining scan/memory/hash phases rerun (`agent04_finish.py`); prior insertion/import observations were preserved from tool output in `agent04_benchmark.json`. This was an audit-script error, not a repository defect.
- Recommended performance evidence matrix: small fixture baseline; 20k/250k typed CSV; narrow/wide 32-table schema; moderate/high-cardinality keys; 12/120/large-invalid month horizon; 0/1/10 ms PostgreSQL latency; simultaneous status/review during one workflow; cold run and unchanged resume. Record elapsed by step, p50/p95 response lag, query/hash counts, bytes, peak RSS/temp disk, and exact output equivalence. Prefer a small dedicated benchmark job over hard timing assertions in the ordinary unit suite.
