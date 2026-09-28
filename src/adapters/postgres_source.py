"""Bounded operator-triggered PostgreSQL snapshots, registered through CSV ingestion.

Only trusted operators supply a manifest and environment connection secret. This
is not an agent SQL capability, synchronization service, or remote upload API.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from src.adapters.csv_source import (
    MAX_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_ROWS,
    CsvManifest,
    CsvTable,
    _no_links,
    _read,
    import_csv,
)
from src.domain.errors import Conflict, DomainError, ValidationFailed

MAX_ROW_BYTES = 1024 * 1024
SOURCE_ENV = "PORTCO_SOURCE_POSTGRES_URL"


class PostgresTable(CsvTable):
    file: str = Field(default="unused.csv", exclude=True)
    primary_key: list[str] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_postgres(self) -> PostgresTable:
        if self.file != "unused.csv":
            raise ValueError("PostgreSQL sources do not accept file paths")
        if not set(self.primary_key).issubset(self.columns) or len(set(self.primary_key)) != len(self.primary_key):
            raise ValueError("primary key must reference unique declared columns")
        if self.schema_name.lower().startswith("pg_"):
            raise ValueError("system schemas are not source tables")
        return self


class PostgresManifest(CsvManifest):
    tables: list[PostgresTable] = Field(min_length=1, max_length=32)  # type: ignore[assignment]
    max_rows: int = Field(default=MAX_ROWS, ge=1, le=MAX_ROWS)
    max_bytes: int = Field(default=MAX_BYTES, ge=1, le=MAX_BYTES)
    statement_timeout_ms: int = Field(default=10_000, ge=100, le=30_000)
    total_timeout_seconds: int = Field(default=120, ge=1, le=300)


def _connection_options(value: str) -> dict[str, str]:
    from psycopg.conninfo import conninfo_to_dict

    if not value.startswith(("postgresql://", "postgres://")):
        raise ValidationFailed("source connection must be a PostgreSQL URL in the designated environment variable")
    try:
        options = {key: str(item) for key, item in conninfo_to_dict(value).items() if item is not None}
    except Exception:
        raise ValidationFailed("invalid source connection configuration") from None
    allowed = {"host", "port", "dbname", "user", "password", "sslmode", "sslrootcert"}
    if set(options) - allowed or not all(options.get(k) for k in ("host", "dbname", "user", "password")):
        raise ValidationFailed("source URL requires one host, database, user and password, with no extra options")
    host = options["host"]
    if not re.fullmatch(r"[A-Za-z0-9.:-]+", host) or "," in host:
        raise ValidationFailed("source URL must identify one TCP host")
    if "port" in options and (not options["port"].isdigit() or not 1 <= int(options["port"]) <= 65535):
        raise ValidationFailed("invalid source port")
    if options.get("sslmode") != "verify-full" and not (
        host in {"127.0.0.1", "::1", "localhost"} and options.get("sslmode") == "disable"
    ):
        raise ValidationFailed("remote sources require sslmode=verify-full; disable is allowed only on loopback")
    # Supply controlled options explicitly, overriding ambient PGOPTIONS/PGSERVICE.
    return options | {
        "connect_timeout": "5",
        "options": "-c search_path=pg_catalog -c default_transaction_read_only=on",
        "application_name": "portco-source-snapshot",
        "client_encoding": "UTF8",
        "gssencmode": "disable",
    }


def _canonical_type(dtype: str, precision: int | None, scale: int | None, udt: str, domain: str | None) -> str:
    if domain is not None:
        raise ValidationFailed("domain and custom PostgreSQL types are unsupported")
    types = {
        "text": "VARCHAR",
        "varchar": "VARCHAR",
        "int4": "INTEGER",
        "int8": "BIGINT",
        "bool": "BOOLEAN",
        "date": "DATE",
        "timestamp": "TIMESTAMP",
    }
    if udt in types:
        return types[udt]
    if dtype == "numeric" and udt == "numeric" and precision is not None and scale is not None:
        return f"DECIMAL({precision},{scale})"
    raise ValidationFailed("unsupported PostgreSQL source type; normalize it in an authorized staging table")


def _check_table(conn: Any, table: PostgresTable) -> dict[str, Any]:
    # The caller locks every declared table before establishing its MVCC snapshot.
    row = conn.execute(
        "SELECT c.oid, c.relkind, c.relrowsecurity, c.relispartition "
        "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relname=%s",
        (table.schema_name, table.table_name),
    ).fetchone()
    if row is None or row[1:] != ("r", False, False):
        raise ValidationFailed("only ordinary non-partitioned tables without row security are supported")
    oid = row[0]
    inheritance = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_inherits WHERE inhrelid=%s OR inhparent=%s)",
        (oid, oid),
    ).fetchone()
    if inheritance != (False,):
        raise ValidationFailed("inherited and partitioned source tables are unsupported")
    unsafe = conn.execute(
        "SELECT pg_catalog.has_table_privilege(%s, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') "
        "OR pg_catalog.has_any_column_privilege(%s, 'INSERT,UPDATE,REFERENCES')",
        (oid, oid),
    ).fetchone()
    if unsafe is None or unsafe[0]:
        raise ValidationFailed("source role must have SELECT-only privileges on every requested table")
    # Include the entire physical column list: added, removed or reordered columns fail closed.
    rows = conn.execute(
        "SELECT column_name, data_type, numeric_precision, numeric_scale, udt_name, domain_name, udt_schema "
        "FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
        (table.schema_name, table.table_name),
    ).fetchall()
    if any(r[6] != "pg_catalog" for r in rows):
        raise ValidationFailed("custom PostgreSQL types are unsupported")
    actual = [(r[0], _canonical_type(*r[1:6])) for r in rows]
    if actual != list(table.columns.items()):
        raise ValidationFailed("PostgreSQL column names, order or types drifted from the manifest")
    key = conn.execute(
        "SELECT a.attname FROM pg_catalog.pg_index i "
        "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ord) "
        "JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum "
        "WHERE i.indrelid=%s AND i.indisprimary AND k.ord <= i.indnkeyatts ORDER BY k.ord",
        (oid,),
    ).fetchall()
    if [r[0] for r in key] != table.primary_key:
        raise ValidationFailed("declared primary key does not match the PostgreSQL primary key")
    return {
        "table": f"{table.schema_name}.{table.table_name}",
        "columns": [list(column) for column in actual],
        "primary_key": table.primary_key,
    }


def _csv_row(values: tuple[Any, ...]) -> bytes:
    if any(isinstance(v, str) and v == r"\N" for v in values):
        raise ValidationFailed("literal CSV null-marker text requires source normalization")
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerow([r"\N" if v is None else v for v in values])
    return output.getvalue().encode("utf-8")


def import_postgres(manifest_path: Path, sources_root: Path) -> dict[str, Any]:
    """Capture one consistent read-only snapshot and atomically register it.

    Provider errors never escape this boundary: PostgreSQL diagnostics can include
    SQL, values, endpoint names and authentication material.
    """
    try:
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
    except ImportError:
        raise ValidationFailed("install the postgres optional dependency to import PostgreSQL sources") from None
    try:
        manifest = PostgresManifest.model_validate_json(_read(manifest_path, MAX_MANIFEST_BYTES))
        if any(key.startswith("PG") and value for key, value in os.environ.items()):
            raise ValidationFailed("clear ambient PG-prefixed connection variables before importing a source")
        options = _connection_options(os.environ.get(SOURCE_ENV, ""))
        store = _no_links(sources_root)
        if (store / manifest.source_id).exists():
            raise Conflict("source id already exists; use a new id for a new snapshot")
        deadline = time.monotonic() + manifest.total_timeout_seconds
        with tempfile.TemporaryDirectory(prefix="portco-pg-extract-") as temporary:
            extract = Path(temporary)
            tables = []
            metadata = []
            total_rows = total_bytes = 0
            with psycopg.connect(make_conninfo(**options)) as conn:
                conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                conn.read_only = True
                # SELECT set_config would establish the repeatable-read snapshot too
                # early. TRUNCATE is not MVCC-safe: a later, still-unlocked table can
                # otherwise appear empty despite that older snapshot. Configure with
                # SET and lock ALL tables before the first catalog/data SELECT.
                for setting, value in (
                    ("statement_timeout", str(manifest.statement_timeout_ms)),
                    ("lock_timeout", "2000"),
                    ("idle_in_transaction_session_timeout", "30000"),
                    ("DateStyle", "ISO, YMD"),
                ):
                    conn.execute(sql.SQL("SET LOCAL {} = {}").format(sql.Identifier(setting), sql.Literal(value)))
                for table in sorted(manifest.tables, key=lambda t: (t.schema_name, t.table_name)):
                    conn.execute(
                        sql.SQL("LOCK TABLE ONLY {} IN ACCESS SHARE MODE").format(
                            sql.Identifier(table.schema_name, table.table_name)
                        )
                    )
                role = conn.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname=current_user"
                ).fetchone()
                if role != (False, False):
                    raise ValidationFailed("source role must not be superuser or bypass row-level security")
                isolation = conn.execute("SHOW transaction_isolation").fetchone()
                readonly = conn.execute("SHOW transaction_read_only").fetchone()
                if isolation != ("repeatable read",) or readonly != ("on",):
                    raise ValidationFailed("source transaction did not establish read-only repeatable-read isolation")
                for number, table in enumerate(manifest.tables):
                    if time.monotonic() > deadline:
                        raise ValidationFailed("PostgreSQL extraction exceeded its total time limit")
                    metadata.append(_check_table(conn, table))
                    filename = f"table-{number:02d}.csv"
                    tables.append(CsvTable(**table.model_dump(exclude={"primary_key"}), file=filename))
                    columns = [sql.Identifier(c) for c in table.columns]
                    # Guard individual row materialization at the server, before transfer.
                    size = sql.SQL(" + ").join(
                        sql.SQL("coalesce(octet_length({}::text), 0)").format(c) for c in columns
                    )
                    bounded = sql.SQL(", ").join(
                        sql.SQL("CASE WHEN ({}) <= {} THEN {} ELSE NULL END").format(
                            size, sql.Literal(MAX_ROW_BYTES), c
                        )
                        for c in columns
                    )
                    query = sql.SQL("SELECT {}, ({}) > {} FROM ONLY {} ORDER BY {} LIMIT {}").format(
                        bounded,
                        size,
                        sql.Literal(MAX_ROW_BYTES),
                        sql.Identifier(table.schema_name, table.table_name),
                        sql.SQL(", ").join(sql.Identifier(k) for k in table.primary_key),
                        sql.Literal(manifest.max_rows - total_rows + 1),
                    )
                    with (extract / filename).open("wb") as stream, conn.cursor(name=f"portco_{number}") as cursor:
                        header = _csv_row(tuple(table.columns))
                        total_bytes += len(header)
                        if total_bytes > manifest.max_bytes:
                            raise ValidationFailed("PostgreSQL extract exceeds its byte limit")
                        stream.write(header)
                        cursor.execute(query)
                        # One row at a time bounds client memory even for wide tables.
                        while (row := cursor.fetchone()) is not None:
                            if time.monotonic() > deadline:
                                raise ValidationFailed("PostgreSQL extraction exceeded its total time limit")
                            total_rows += 1
                            if total_rows > manifest.max_rows:
                                raise ValidationFailed("PostgreSQL extract exceeds its row limit")
                            if row[-1]:
                                raise ValidationFailed("PostgreSQL row exceeds its byte limit")
                            encoded = _csv_row(row[:-1])
                            total_bytes += len(encoded)
                            if total_bytes > manifest.max_bytes:
                                raise ValidationFailed("PostgreSQL extract exceeds its byte limit")
                            stream.write(encoded)
                provenance = {
                    "kind": "postgresql-snapshot",
                    "format_version": 1,
                    "manifest_sha256": hashlib.sha256(manifest.model_dump_json().encode()).hexdigest(),
                    "schema_sha256": hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest(),
                    "tables": metadata,
                    "isolation": "repeatable read",
                    "read_only": True,
                    "server_major": conn.info.server_version // 10000,
                    "limits": {
                        k: getattr(manifest, k)
                        for k in ("max_rows", "max_bytes", "statement_timeout_ms", "total_timeout_seconds")
                    },
                }
            csv_manifest = CsvManifest(
                source_id=manifest.source_id,
                company_id=manifest.company_id,
                as_of=manifest.as_of,
                tables=tables,
                category_domains=manifest.category_domains,
            )
            path = extract / "manifest.json"
            path.write_text(csv_manifest.model_dump_json(), encoding="utf-8")
            return import_csv(path, extract, store, provenance=provenance)
    except DomainError:
        raise
    except (psycopg.Error, OSError, ValueError, TypeError, ArithmeticError):
        raise ValidationFailed("PostgreSQL import failed; check configuration, privileges, schema and limits") from None
