# Agent 03: Source adapters and ingestion audit

Reviewed `external.py`, `csv_source.py`, `postgres_source.py`, `sql_guard.py`, profiling, connector tests, workflow input hashing and source documentation. All reproductions used disposable synthetic data with the existing `.venv` on 2026-10-10. No tracked implementation files changed, no real sources contacted, and no full test suite run.

## Verified defects

### ING-01 — SQL guard allows nonrecursive self/forward CTE references to excluded tables

- **Priority: P2 / defense in depth. Confidence: high.**
- **Location:** `src/adapters/sql_guard.py:29`, used at `:64`.
- `_cte_in_scope` regards every name in an enclosing WITH as visible everywhere, including inside its own nonrecursive definition and preceding CTE definitions. DuckDB instead resolves these references to physical default-schema tables when present.
- Reproduced with installed DuckDB:

```python
import duckdb
from src.adapters.sql_guard import check_select
c = duckdb.connect()
c.execute('CREATE TABLE main.secrets AS SELECT 123 AS secret')
sql = 'WITH secrets AS (SELECT * FROM secrets) SELECT sum(secret) FROM secrets'
check_select(sql, {'billing'})  # passes
assert c.execute(sql).fetchall() == [(123,)]  # reads excluded main
sql = 'WITH x AS (SELECT * FROM secrets), secrets AS (SELECT 1) SELECT * FROM x'
check_select(sql, {'billing'})  # also passes; also returns 123
```

- **Impact:** contradicts the guard's current-database/schema allowlist guarantee. This is **not a demonstrated remote exploit**: current public adapter methods construct fixed SQL and MCP exposes no arbitrary SQL interface.
- **Fix:** implement actual lexical CTE scope with declaration ordering, shadowing and explicit recursive semantics; reject any unqualified table reference not proven to bind to a visible CTE. Preserve valid nested CTEs.
- **Regression:** both examples must raise PolicyViolation; retain valid prior-sibling and nested CTE coverage, and explicitly test recursive policy.

### ING-02 — Accepted schema casing creates a permanently unusable registration

- **Priority: P2. Confidence: high.**
- **Locations:** `src/adapters/csv_source.py:69`, `:184`, `:219`; downstream failure at `src/adapters/external.py:221`.
- A valid manifest containing `Billing.invoices` and `billing.payments` passes validation. DuckDB merges those case-insensitive schema names into `Billing`, but the receipt records `['Billing', 'billing']`. Import returns success, `resolve_csv` succeeds, and `ConnectionRegistry.open(...).list_schemas()` raises `NotFound('requested schema is not present in the source')`. The immutable source ID is now occupied.
- **Repro:** two one-row CSVs with header `id`, declared `INTEGER`; use the two schema/table pairs above in one CsvManifest. Import, then open via ConnectionRegistry and call list_schemas.
- **Fix:** reject inconsistent spellings of a schema's case-folded name before staging, or establish one canonical spelling and consistently rewrite metadata/domain keys. PostgreSQL can have distinct quoted schemas differing only in case, so reject unsupported collisions there explicitly rather than silently merging them.
- **Regression:** mixed-case declarations must either fail before registration or import into an adapter that successfully profiles both tables; include category domain keys and case-sensitive PostgreSQL schema collisions.

### ING-03 — Import can produce a receipt larger than its own resolver accepts

- **Priority: P2. Confidence: high.**
- **Locations:** `src/adapters/csv_source.py:63`, `:220`, `:227`, `:254`.
- `category_domains` has no bound on list lengths. Input manifest is capped at 1 MiB, but pretty-printed registration is not checked before committing. Its expanded size can exceed the resolver's same 1 MiB cap.
- **Reproduction:** one `billing.records.status VARCHAR` column with CSV `status\nx\n`, and `category_domains={'billing.records.status': ['x'] * 140000}`. Write compact manifest JSON. Observed input **560,218 bytes**, successful registration **1,680,573 bytes**, followed immediately by `resolve_csv` raising `ValidationFailed('source input exceeds its byte limit')`.
- **Impact:** import reports success and consumes an immutable source ID for an unusable source. This is a local operator robustness issue, not an unauthenticated upload attack.
- **Fix:** bound/deduplicate category domains and serialize/validate the final receipt before rename; use a defined receipt limit separate from manifest limit if appropriate. Include PostgreSQL provenance in the final size check.
- **Regression:** near-limit manifest with expanded JSON/provenance must either remain resolvable or be rejected before registration with no occupied source directory.

### ING-04 — TIMESTAMP ingestion silently discards submicrosecond precision

- **Priority: P2. Confidence: high.**
- **Location:** `src/adapters/csv_source.py:130`.
- Python `datetime.fromisoformat` silently truncates fractional seconds beyond six digits. A valid typed CSV containing `2025-01-01T00:00:00.1234567` imports successfully, and querying the closed/reopened snapshot returns `2025-01-01 00:00:00.123456`.
- **Minimal proof:** `_cell('2025-01-01T00:00:00.1234567', 'TIMESTAMP')` returns a datetime with microsecond `123456`; complete import/reopen also verified.
- **Impact:** inputs differing only below microsecond precision collapse without notice. This matters for event identity/order and exact extract fidelity. PostgreSQL supported timestamps are already microsecond precision; this finding concerns external CSV inputs.
- **Fix:** explicitly reject nonzero discarded fractional digits (and document precision) before conversion, or deliberately support a higher-precision representation end to end. Zero-only excess precision can be accepted without information loss.
- **Regression:** reject `.1234567`, preserve `.123456`, and define `.1234560`, timezone, comma-fraction and compact ISO input behavior.

### ING-05 — Valid schema `source` collides with the fixed DuckDB catalog name

- **Priority: P2. Confidence: high.**
- **Locations:** `src/adapters/csv_source.py:172`, `:183`, `:186`; related `src/adapters/external.py:258`.
- Manifest validation permits schema `source`. The fixed database file `source.duckdb` also gives the database catalog the name `source`; two-part SQL `"source"."records"` becomes ambiguous. A one-row manifest in this schema fails with sanitized ValidationFailed, whose underlying synthetic repro context was `Binder Error: Ambiguous reference to catalog or schema "source" - use a fully qualified path like "source.source"`.
- **Impact:** ordinary declared source names unexpectedly fail ingestion, including PostgreSQL snapshots flowing through this importer. Existing validation offers no explanation of the actual naming restriction.
- **Fix:** either explicitly reject/document the reserved catalog collision before import, or consistently resolve it through a validated current-catalog qualification/attachment alias. Updating creation SQL alone is insufficient: adapter queries use the same two-part form and SQL guard currently rejects all catalog-qualified references.
- **Regression:** a one-column `source.records` manifest should fail with a specific validation explanation before work, or import and profile correctly end to end.

## Performance finding / recommendation

### ING-P01 — One PostgreSQL network roundtrip per source row

- **Priority: P2 performance improvement; not an undisclosed guarantee violation. Confidence: high on mechanism.**
- **Location:** `src/adapters/postgres_source.py:260` (named server cursor created at `:252`).
- Installed psycopg **3.3.6** `ServerCursor.fetchone` source calls `self._conn.wait(self._fetch_gen(1))` on every invocation. Thus the connector issues a FETCH per row, not a locally buffered read. Documentation openly says it transfers one row at a time; acceptance uses loopback.
- **Calculated latency floor, not a measured remote benchmark:** 250,000 rows at 10 ms roundtrip requires approximately 2,500 seconds in roundtrips, versus the 120-second default and 300-second maximum extraction budgets; overhead lowers the practical ceiling further.
- **Fix:** `fetchmany` with a bounded small batch or cursor iteration with deliberate `itersize`; derive worst-case batch memory from the existing 1 MiB per-row bound (e.g., 16 rows yields about 16 MiB of raw field content before Python overhead). Preserve per-row validation, byte limits, deadline checks and no-partial-registration semantics.
- **Regression/measurement:** count FETCH commands or inject controlled cursor latency at several row counts/widths. Ensure bounded fetch count, unchanged output hashes and fail-closed row/byte/deadline behavior.
- Official Psycopg documentation describes batch iteration specifically to reduce server roundtrips: [Cursor classes](https://www.psycopg.org/psycopg3/docs/api/cursors.html#the-servercursor-class), [Server-side cursors](https://www.psycopg.org/articles/2026/08/12/server-side-cursors/).

### ING-P02 — DuckDB materialization and repeated full-file hashing deserve targeted benchmarks

- `csv_source.py:201` uses row-oriented `executemany` even though batches contain 1,000 rows. [DuckDB Python DB API](https://duckdb.org/docs/lts/clients/python/dbapi) advises against executemany for large inserts. Benchmark an explicitly typed bulk path while retaining exact Decimal validation and external-access protections; do not replace it with inference-based loading.
- `resolve_csv` hashes the whole snapshot every time. Workflow input hashing resolves the connection for every upstream step during resume (`workflows/base.py:118,144`). This is correct integrity checking but can amplify I/O as snapshots scale. Measure before optimizing; any digest cache must preserve the trusted-filesystem/invalidation model.
- No large benchmark performed; these are scalability recommendations, not asserted production regressions.

## Strengths and limits verified by inspection

- Clear operator-only boundary; no remote SQL/upload capability. Credential/environment restrictions, verified remote TLS requirements, secret-redacted provider errors and parameterized/quoted SQL.
- PostgreSQL REPEATABLE READ and READ ONLY verified, all source tables locked before the first snapshot-establishing query, deterministic key order, actual PK/type verification, RLS/inheritance/partition/write-privilege rejection, transfer limits, temporary cleanup.
- CSV staging/transaction/atomic directory registration, immutable IDs, input/snapshot hashes, read-only reopen, path and link restrictions, strict exact decimal validation.
- Aggregate-only protocol, explicit category domains and PII/injection withholding, identifier quoting, explicit read-only denial verification, source value checksums.
- Existing focused tests cover competing imports, tamper detection, tenant restrictions, provider redaction, lock/snapshot consistency, failure cleanup and full synthetic import-to-publication paths.
- **Do not report as bugs:** default CSV field-size limit is explicitly disclosed in `docs/CSV-SOURCE.md`; trusted source-store metadata is explicitly not an external signature; filesystem race and power-loss durability limitations are documented; total PostgreSQL deadline deliberately excludes local materialization and permits a currently executing statement to finish/timeout; unsupported source types require staging by design.

## Suggested order

Repair CTE binding and the two successful-but-unusable registration cases first. Define timestamp precision and schema/catalog naming behavior next. Then improve and benchmark PostgreSQL fetch batching and DuckDB insertion while preserving the strong failure/consistency boundaries.
