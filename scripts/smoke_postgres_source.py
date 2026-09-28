"""PostgreSQL connector to governed publication, using only synthetic source data.

Requires PORTCO_TEST_POSTGRES_URL and PORTCO_TEST_POSTGRES_ALLOW_CREATE=1.
Creates a disposable business database and SELECT-only role, never reads or
writes workflow tables at the administrative endpoint. Source credentials exist
only in the local process environment for the extraction duration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import anyio
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from scripts.postgres_test_db import disposable_database
from scripts.smoke_csv_source import code_provenance, exercise_registered
from src.adapters.postgres_source import PostgresManifest, import_postgres
from src.fixtures.category_domains import fixture_category_domains
from src.fixtures.portco_a import build
from src.settings import Settings

# These are the fixture's business identifiers, not a heuristic over values.
# Journal-entry lines are identified by entry + line, not entry alone.
PRIMARY_KEYS = {
    "crm.accounts": ["acct_id"],
    "crm.contacts": ["contact_id"],
    "crm.opportunities": ["opp_id"],
    "billing.customers": ["cust_id"],
    "billing.subscriptions": ["sub_id"],
    "billing.invoices": ["inv_no"],
    "billing.invoice_lines": ["line_id"],
    "billing.payments": ["pmt_id"],
    "erp.gl_accounts": ["acct_code"],
    "erp.journal_lines": ["je_id", "line_no"],
    "hr.employees": ["emp_id"],
}


def synthetic_manifest() -> PostgresManifest:
    fixture = build()
    return PostgresManifest.model_validate(
        {
            "source_id": "synthetic-postgres-v1",
            "company_id": "postgres_demo",
            "as_of": fixture.as_of.isoformat(),
            "tables": [
                {
                    "schema_name": t.schema,
                    "table_name": t.name,
                    "columns": dict(t.columns),
                    "primary_key": PRIMARY_KEYS[t.qualified],
                }
                for t in fixture.tables
            ],
            "category_domains": fixture_category_domains("portco_a"),
        }
    )


@contextmanager
def synthetic_source() -> Iterator[dict[str, Any]]:
    admin_url = os.environ.get("PORTCO_TEST_POSTGRES_URL")
    if not admin_url:
        raise RuntimeError("PORTCO_TEST_POSTGRES_URL is required for isolated synthetic acceptance")
    if os.environ.get("PORTCO_TEST_POSTGRES_ALLOW_CREATE") != "1":
        raise RuntimeError("explicit disposable-database allocation permission is required")
    fixture = build()
    with disposable_database(admin_url, allow_create=True) as db_url:
        parsed = make_url(db_url).set(drivername="postgresql")
        role = f"portco_test_reader_{uuid4().hex}"
        password = secrets.token_urlsafe(32)
        with psycopg.connect(parsed.render_as_string(hide_password=False), autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(password))
            )
            try:
                for schema in sorted({t.schema for t in fixture.tables}):
                    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                    admin.execute(
                        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(role))
                    )
                for table in fixture.tables:
                    keys = PRIMARY_KEYS[table.qualified]
                    positions = [[name for name, _ in table.columns].index(k) for k in keys]
                    row_keys = [tuple(row[i] for i in positions) for row in table.rows]
                    if len(set(row_keys)) != len(table.rows) or any(None in k for k in row_keys):
                        raise RuntimeError("synthetic fixture violates its declared business key")
                    columns = sql.SQL(", ").join(
                        sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(dtype)) for name, dtype in table.columns
                    )
                    name = sql.Identifier(table.schema, table.name)
                    admin.execute(
                        sql.SQL("CREATE TABLE {} ({}, PRIMARY KEY ({}))").format(
                            name,
                            columns,
                            sql.SQL(", ").join(sql.Identifier(k) for k in keys),
                        )
                    )
                    with admin.cursor() as cursor, cursor.copy(sql.SQL("COPY {} FROM STDIN").format(name)) as copy:
                        for row in table.rows:
                            copy.write_row(row)
                    admin.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(name, sql.Identifier(role)))
                reader_url = parsed.set(username=role, password=password)
                if parsed.host in {"localhost", "127.0.0.1", "::1"}:
                    reader_url = reader_url.update_query_dict({"sslmode": "disable"})
                # Preserve a verified remote URL's existing SSL parameters; importer enforces TLS.
                previous = os.environ.get("PORTCO_SOURCE_POSTGRES_URL")
                os.environ["PORTCO_SOURCE_POSTGRES_URL"] = reader_url.render_as_string(hide_password=False)
                try:
                    yield {"tables": len(fixture.tables), "rows": sum(len(t.rows) for t in fixture.tables)}
                finally:
                    if previous is None:
                        os.environ.pop("PORTCO_SOURCE_POSTGRES_URL", None)
                    else:
                        os.environ["PORTCO_SOURCE_POSTGRES_URL"] = previous
            finally:
                admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


async def exercise(workdir: Path) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    provenance = code_provenance()
    script = Path(__file__).resolve()
    provenance["implementation_sha256"]["scripts/smoke_postgres_source.py"] = hashlib.sha256(
        script.read_bytes()
    ).hexdigest()
    manifest = workdir / "source-manifest.json"
    manifest.write_text(synthetic_manifest().model_dump_json(indent=2), encoding="utf-8")
    settings = Settings(env="test", var_root=workdir / "runtime", log_level="WARNING")
    with synthetic_source() as expected:
        receipt = import_postgres(manifest, settings.var_root / "sources")
        if (
            len(receipt["inputs"]) != expected["tables"]
            or sum(t["rows"] for t in receipt["inputs"]) != expected["rows"]
        ):
            raise RuntimeError("PostgreSQL source snapshot did not retain all synthetic input rows")
    # Live source and credentials are gone before downstream onboarding begins.
    result = await exercise_registered(
        settings,
        receipt,
        provenance,
        data_provenance="synthetic portco_a rows extracted from actual disposable PostgreSQL; no customer-data claim",
        identity_prefix="postgres-smoke",
    )
    result["shareable_summary"]["connector_provenance"] = receipt["provenance"]
    result["shareable_summary"]["source_inputs"] = receipt["inputs"]
    result["shareable_summary"]["live_source_removed_before_onboarding"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    try:
        result = anyio.run(exercise, args.workdir.resolve())
    except Exception:
        # Provisioning drivers may include endpoint/credential text in their errors.
        raise SystemExit("PostgreSQL synthetic acceptance failed; inspect private test diagnostics") from None
    output = args.summary or args.workdir / "summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result["shareable_summary"], indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "summary": str(output)}, indent=2))


if __name__ == "__main__":
    main()
