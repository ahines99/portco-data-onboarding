# External CSV source snapshots

The local operator can import business-system CSV extracts into a registered, read-only
DuckDB snapshot. This is an external file ingestion boundary, independent of the fixture
registry. It is not a network connector, SFTP client, remote upload endpoint, or claim of
customer adoption. The agent cannot import files through MCP or HTTP.

## Import and onboard

Create a UTF-8 JSON manifest describing the extract, its company and reference date:

```json
{
  "source_id": "acme-export-20251231",
  "company_id": "acme",
  "as_of": "2025-12-31",
  "tables": [
    {
      "schema_name": "billing",
      "table_name": "invoices",
      "file": "billing/invoices.csv",
      "columns": {
        "invoice_id": "VARCHAR",
        "customer_id": "VARCHAR",
        "amount": "DECIMAL(18,2)",
        "invoice_date": "DATE"
      }
    }
  ]
}
```

```powershell
uv run portco sources import-csv C:/extracts/manifest.json --root C:/extracts
uv run portco run --connection csv:acme-export-20251231
```

The table example documents the input format; a complete financial publication requires
the supported entities and columns needed by the selected metrics. Arbitrary exports may
produce incomplete mappings or stop for review. Import success is not mapping success.

CSV headers must exactly match the declared column order. Types are explicit rather than
inferred: `VARCHAR`, `INTEGER`, `BIGINT`, `BOOLEAN`, `DATE`, `TIMESTAMP`, and
`DECIMAL(p,s)` with precision up to 38. Use `VARCHAR` for identifiers with leading zeros.
Use `DECIMAL`, not binary floating point, for money. Decimal values that would round or
overflow are rejected. Dates use ISO format, timestamps have no timezone (normalize them
before import), booleans are `true` or `false`, and the literal `\N` means SQL NULL.
Empty strings remain empty strings; `\N` cannot represent literal text in this format.

Optional `category_domains` maps `schema.table.column` to operator-approved labels. The
existing adapter still applies its PII and injection checks before disclosing category values.
Do not put personal or secret data in identifiers, manifest metadata, or approved labels.

## Safety and durability

- Only local operators can import. The manifest fixes company ownership; HTTP/MCP callers
  subsequently need authorization for that company. Configure identity-provider company
  claims separately; ingestion does not grant access.
- Paths must be relative `.csv` files beneath the extract root. Absolute paths, Windows
  drive/UNC paths, traversal, symbolic links, and junctions are rejected. Identifiers and
  SQL types are validated; source values use parameterized inserts.
- Limits are 32 tables, 128 columns per table, 64 MiB of CSV input in total, 250,000 rows
  in total, and a 1 MiB manifest. The CSV parser also imposes its default field-size limit.
- Import uses a private staging directory and a database transaction. The snapshot and
  registration become visible together via a directory rename. Invalid input leaves no
  registered source. Existing source IDs cannot be overwritten; changed input needs a new ID.
- The registration contains source-file hashes, row counts, declared metadata and a SHA-256
  of the closed DuckDB snapshot. Resolution verifies the snapshot hash before returning a
  read-only connection. Changes to upstream CSV files do not mutate the snapshot.
- Registrations under `<var_root>/sources` survive service restarts. Include this directory
  in coordinated backups with the state database, artifacts and publications. Interrupted
  imports may leave unregistered `.import-*` directories for operator inspection/cleanup.
- Raw extracts and materialized source snapshots are sensitive operator-held data. Restrict
  filesystem access and encrypt storage using your environment's controls. They are not
  safe-to-share artifacts. Error messages exclude source values and underlying SQL diagnostics.

The local operator and source-store filesystem remain trusted. A privileged actor who can
rewrite both the database and its registration can change the recorded digest; this is not
an externally anchored signature. Path validation does not defend against a hostile local
process racing filesystem changes. Do not share the import directory with untrusted writers.
Atomic visibility is not a claim of power-loss durability; filesystem/database backups remain
necessary. Imports are synchronous and intentionally absent from remote agent capabilities.

## Reproducible acceptance exercise

```powershell
uv run python -m scripts.smoke_csv_source --workdir var/csv-smoke-unique
```

Use a fresh directory for each exercise. It exports existing synthetic SaaS rows to CSV,
imports them under company `csv_demo` and a `csv:` connection, restarts the service between
review gates, builds dbt, reconciles metrics and publishes. It never waives failed tests.
`evidence.json` records the source digest and workflow outputs. Its separate reviewer is an
automated test identity, not evidence of independent human review. This exercise proves the
ingestion and workflow integration; it does not prove unfamiliar-schema accuracy, real source
credential handling, production hosting, or customer business impact.
