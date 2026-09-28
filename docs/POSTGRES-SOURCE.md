# PostgreSQL source snapshots

The `sources import-postgres` operator command extracts declared PostgreSQL
business tables into the existing immutable CSV/DuckDB source contract. It is
read-only, bounded, and suitable for scripted execution. It adds no subscription
or hosted service. Authentication material is read only from an environment
variable; it is not accepted as a command-line argument or written to receipts.

This is a database snapshot connector, not a claim of access to a customer system,
a managed integration, ongoing synchronization, or independent human validation.
The verification fixture uses a dedicated synthetic business database, separate
from the application's workflow database.

## Installation and execution

Install the existing PostgreSQL extra:

```powershell
python -m uv sync --extra postgres --frozen
```

Set `PORTCO_SOURCE_POSTGRES_URL` through the operator's secret environment or
secret manager. The URL must contain one TCP host, database, username, password,
and an explicit `sslmode`. Do not put the actual URL in a committed file, command
history, an issue, or a report. Clear ambient `PG*` variables before running:
these can otherwise alter libpq connection behavior independently of the source
configuration. The connector never uses `PORTCO_DATABASE_URL` as its source.

Then run:

```powershell
python -m src.cli sources import-postgres path/to/postgres-manifest.json
python -m src.cli run --connection csv:business-2025-12-31
```

The registered connection retains the `csv:` prefix because PostgreSQL extraction
feeds the same immutable typed importer. `registration.json` identifies the
origin as `provenance.kind = "postgresql-snapshot"`. Downstream profiling,
company authorization, mapping, review gates and publication are unchanged.
No connector capability is exposed through MCP and no source credential is
sent to an agent.

## Manifest

```json
{
  "source_id": "business-2025-12-31",
  "company_id": "business_demo",
  "as_of": "2025-12-31",
  "max_rows": 250000,
  "max_bytes": 67108864,
  "statement_timeout_ms": 10000,
  "total_timeout_seconds": 120,
  "tables": [
    {
      "schema_name": "billing",
      "table_name": "invoices",
      "primary_key": ["id"],
      "columns": {
        "id": "INTEGER",
        "amount": "DECIMAL(18,2)",
        "memo": "VARCHAR"
      }
    }
  ]
}
```

The manifest must declare every physical column in order and the actual primary
key in key order. It accepts no query, filter, join, expression, incremental
watermark, or file path. New source data requires a new `source_id`; existing
registrations cannot be overwritten. `as_of` is an operator-supplied business
interpretation date, not a historical database query or a verified capture date.
Optional `category_domains` uses the same contract as CSV ingestion.

| PostgreSQL type | Manifest type |
|---|---|
| `text`, `varchar` | `VARCHAR` |
| `integer` | `INTEGER` |
| `bigint` | `BIGINT` |
| `boolean` | `BOOLEAN` |
| `date` | `DATE` |
| `timestamp without time zone` | `TIMESTAMP` |
| `numeric(p,s)` | `DECIMAL(p,s)`, precision at most 38, nonnegative scale no larger than precision |

Floating point, unconstrained numeric, timezone-bearing timestamps, JSON, arrays,
UUID, enums, domains and other custom types are rejected. Normalize unsupported
representations into authorized ordinary staging tables before extraction. The
connector does not silently round money or strip timezone information. Literal
text `\N` is rejected because the shared CSV contract reserves it for SQL NULL.
Newlines and commas in ordinary text are quoted correctly. Empty text stays
empty, and NULL stays NULL.

## Authority and transport

Use a dedicated login with schema `USAGE` and table `SELECT`, with no source-table
write privileges. The connector rejects superusers, `BYPASSRLS` roles, table or
column write privileges, row-level-security tables, views, foreign tables,
partitioned tables and inherited tables. Only ordinary tables with a declared,
verified primary key are accepted. The checked role need not be a database owner
and should not be granted privileges on unrelated application data.

Remote connections require `sslmode=verify-full`; `sslrootcert` may identify a
trusted CA file where required. The sole plaintext exception is explicit
`sslmode=disable` to `localhost`, `127.0.0.1`, or `::1`, intended for isolated local
synthetic verification. Other libpq URL options, multi-host configurations and
Unix sockets are rejected. Server certificate hostname verification is described
in the [PostgreSQL SSL documentation](https://www.postgresql.org/docs/18/libpq-ssl.html).

Extraction establishes and checks one `REPEATABLE READ`, `READ ONLY` transaction.
Before the first snapshot-establishing query, it sets timeouts with `SET LOCAL`
and acquires access-share locks on every declared table in deterministic order.
This prevents concurrent `TRUNCATE` or table-rewriting DDL from emptying a later
table in an older snapshot. All selected tables then use a consistent database
snapshot. These locks allow ordinary concurrent writes, which remain outside
the captured snapshot. The connector
issues only fixed metadata queries, settings, locks, and parameterized or safely
quoted SELECT statements. Table contents cannot select SQL operations.
See [PostgreSQL transaction semantics](https://www.postgresql.org/docs/16/sql-set-transaction.html)
and [Psycopg transaction controls](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

The connector checks privileges on selected tables; it does not certify all
privileges or role memberships in the source cluster. The operator and source
server are trusted administrative boundaries. A read-only transaction is an
additional safeguard, not a replacement for least-privilege credentials.

## Bounds, atomicity and evidence

- At most 32 tables and 128 columns per table.
- At most 250,000 total rows and 64 MiB of UTF-8 CSV, including headers/quoting.
- At most 1 MiB of textual field content per row, checked at the server before
  sending source values to the client.
- A five-second connection timeout; statement timeout defaults to ten seconds,
  capped at thirty; lock timeout is two seconds.
- The total extraction deadline defaults to 120 seconds, capped at 300. It is
  checked between tables and rows; a currently running statement can finish or
  time out after that deadline. Local DuckDB materialization happens afterward.

A server cursor transfers one row at a time. Primary-key order makes input CSV
hashes reproducible for unchanged values. PostgreSQL may still scan or sort data
on the server; row/byte limits are transfer limits, not a claim of zero source
load. Use an appropriate source instance and maintenance window when needed.

Schema/type/key drift, excess rows, excessive bytes, an oversized row, invalid
values, insufficient authority, or a provider error abort extraction. There is
no partial registration and no truncated success. Temporary extracts are cleaned
up. Once extraction succeeds, the existing importer writes the DuckDB snapshot,
registration and PostgreSQL provenance in one directory and atomically publishes
that directory. Source credentials, endpoints, raw values and PostgreSQL error
messages are omitted from the receipt and CLI error output.

Receipts include canonical manifest and schema hashes, per-table primary keys,
row counts and input hashes, transaction mode, PostgreSQL major version, limits,
and the existing DuckDB snapshot hash. Input hashes are deterministic; binary
DuckDB files are not promised to be byte-identical across separate imports.
Local registration is trusted operator-owned metadata, not a remote attestation.

## Verification

The first hosted acceptance on commit `25c6937ca75aeda58108e1258c441b7e0d9eea60`
passed in [CI 36443092813](https://github.com/ahines99/portco-data-onboarding/actions/runs/36443092813).
The [retained report](evidence/postgres-source-acceptance.json) records 11 tables / 14,639 rows,
nine published metrics, 58 generated file hashes checked, 59 publication files, 45 intact audit
events and zero waivers. The live synthetic source was removed before onboarding. The release
record carries a fresh exact-release-commit report; this earlier report keeps its original provenance.
PostgreSQL CI uses plaintext loopback transport. Remote `verify-full` configuration is enforced
and unit-tested; these checks do not establish a real remote provider's TLS integration.

```powershell
python -m pytest -q tests/test_postgres_source.py
```

The existing `test-postgres` CI job also discovers
`tests/test_postgres_source_integration.py`. It creates a uniquely named disposable
database through `scripts.postgres_test_db.py`, seeds two synthetic business
tables, creates a generated SELECT-only login, then verifies exact money/NULLs,
a stable multi-table snapshot during concurrent writes, blocking concurrent
truncation of a later source table, schema/type/key/RLS
rejection, row bounds, privilege rejection and lock timeout. Cleanup drops only
the generated database/role. `PORTCO_TEST_POSTGRES_ALLOW_CREATE=1` is the explicit
test-allocation permission; do not supply a production administrative account.

These tests establish connector behavior against PostgreSQL. They do not prove
customer adoption, source-system business semantics, production capacity, or
financial certification for arbitrary schemas.

For end-to-end acceptance, the same CI module also seeds the full supported
synthetic SaaS source (11 tables, 14,639 rows). It declares actual business keys,
including the composite journal-entry/line key; it does not invent keys by
searching for coincidentally unique fields. After extraction, the live database
and generated source login are removed before the registered snapshot is used.
The workflow then rebuilds its service at review gates, performs explicit
synthetic automated reviewer decisions, reconciles all nine supported metrics,
and verifies publication files and the audit chain without waiving test failures.

To run that complete acceptance outside pytest against a disposable local test
server with the two `PORTCO_TEST_POSTGRES_*` variables set:

```powershell
python -m scripts.smoke_postgres_source --workdir var/postgres-smoke --summary var/postgres-smoke-summary.json
```

The pytest acceptance test writes the same shareable evidence when
`PORTCO_POSTGRES_SOURCE_SUMMARY` names an output path. This report omits source
credentials, endpoints, absolute artifact paths and raw synthetic rows. Review
provenance is explicitly automated; successful acceptance is not human approval
or independent business validation.
