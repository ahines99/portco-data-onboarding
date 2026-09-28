"""Snapshot manifest, transport, data bounds and provider-error redaction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import psycopg
import pytest
from typer.testing import CliRunner

from src.adapters.csv_source import resolve_csv
from src.adapters.postgres_source import (
    PostgresManifest,
    _canonical_type,
    _connection_options,
    _csv_row,
    import_postgres,
)
from src.cli import app
from src.domain.errors import DomainError, ValidationFailed


@pytest.fixture(autouse=True)
def clean_pg_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in os.environ:
        if key.startswith("PG"):
            monkeypatch.delenv(key)


def manifest(tmp_path: Path, **updates: Any) -> Path:
    doc = {
        "source_id": "pg-v1",
        "company_id": "external_co",
        "as_of": "2025-12-31",
        "tables": [
            {
                "schema_name": "billing",
                "table_name": "invoices",
                "primary_key": ["id"],
                "columns": {"id": "INTEGER", "memo": "VARCHAR"},
            }
        ],
    }
    doc.update(updates)
    path = tmp_path / "postgres.json"
    path.write_text(json.dumps(doc))
    return path


@pytest.mark.security
@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "?sslmode=prefer",
        "?sslmode=require",
        "?sslmode=verify-ca",
        "?sslmode=verify-full&options=-c%20search_path%3Dpublic",
        "?sslmode=verify-full&hostaddr=127.0.0.1",
        "?sslmode=verify-full&service=elsewhere",
    ],
)
def test_remote_connection_requires_verified_tls_and_controlled_options(suffix: str) -> None:
    with pytest.raises(ValidationFailed):
        _connection_options("postgresql://reader:private-password@db.example.test/source" + suffix)


def test_secure_connection_and_explicit_loopback_exception() -> None:
    assert (
        _connection_options("postgresql://r:p@db.example.test/source?sslmode=verify-full")["sslmode"] == "verify-full"
    )
    assert _connection_options("postgresql://r:p@127.0.0.1/source?sslmode=disable")["sslmode"] == "disable"
    with pytest.raises(ValidationFailed):
        _connection_options("postgresql://r:p@remote.example.test/source?sslmode=disable")


@pytest.mark.security
@pytest.mark.parametrize(
    "change",
    [
        {"query": "SELECT * FROM secrets"},
        {"filter": "true"},
        {"max_rows": 250001},
        {"max_bytes": 67108865},
        {"statement_timeout_ms": 0},
        {"total_timeout_seconds": 301},
        {
            "tables": [
                {
                    "schema_name": "billing",
                    "table_name": "invoices;DROP",
                    "columns": {"id": "INTEGER"},
                    "primary_key": ["id"],
                }
            ]
        },
        {
            "tables": [
                {
                    "schema_name": "billing",
                    "table_name": "invoices",
                    "columns": {"id": "INTEGER"},
                    "primary_key": ["absent"],
                }
            ]
        },
        {
            "tables": [
                {
                    "schema_name": "billing",
                    "table_name": "invoices",
                    "columns": {"id": "INTEGER"},
                    "primary_key": ["id"],
                    "file": "secret.csv",
                }
            ]
        },
    ],
)
def test_manifest_rejects_arbitrary_sql_unsafe_names_and_unbounded_limits(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    with pytest.raises((ValueError, DomainError)):
        PostgresManifest.model_validate_json(manifest(tmp_path, **change).read_bytes())


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("text", None, None, "text", None), "VARCHAR"),
        (("character varying", None, None, "varchar", None), "VARCHAR"),
        (("integer", 32, 0, "int4", None), "INTEGER"),
        (("bigint", 64, 0, "int8", None), "BIGINT"),
        (("boolean", None, None, "bool", None), "BOOLEAN"),
        (("date", None, None, "date", None), "DATE"),
        (("timestamp without time zone", None, None, "timestamp", None), "TIMESTAMP"),
        (("numeric", 18, 2, "numeric", None), "DECIMAL(18,2)"),
    ],
)
def test_supported_postgres_types(args: tuple[Any, ...], expected: str) -> None:
    assert _canonical_type(*args) == expected


@pytest.mark.parametrize(
    "args",
    [
        ("numeric", None, None, "numeric", None),
        ("timestamp with time zone", None, None, "timestamptz", None),
        ("double precision", None, None, "float8", None),
        ("jsonb", None, None, "jsonb", None),
        ("text", None, None, "text", "custom_domain"),
    ],
)
def test_lossy_or_custom_types_require_staging(args: tuple[Any, ...]) -> None:
    with pytest.raises(ValidationFailed):
        _canonical_type(*args)


def test_literal_null_marker_cannot_silently_become_null() -> None:
    assert _csv_row((None, "", True)) == b"\\N,,True\n"
    with pytest.raises(ValidationFailed):
        _csv_row((r"\N",))


class Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def fetchone(self) -> Any:
        return self.rows.pop(0) if self.rows else None

    def fetchall(self) -> Any:
        return self.rows


class FakeCursor(Rows):
    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def execute(self, query: Any) -> None:
        assert "ORDER BY" in query.as_string()
        assert "LIMIT" in query.as_string()
        assert "FROM ONLY" in query.as_string()


class FakeConnection:
    isolation_level: Any = None
    read_only = False

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.info = type("Info", (), {"server_version": 160000})()

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def cursor(self, name: str) -> FakeCursor:
        assert self.read_only
        assert self.isolation_level == psycopg.IsolationLevel.REPEATABLE_READ
        return FakeCursor(list(self.rows))

    def execute(self, query: Any, params: Any = None) -> Rows:
        if not isinstance(query, str):
            assert query.as_string().startswith(("LOCK TABLE ONLY", "SET LOCAL"))
            return Rows([])
        if "pg_roles" in query:
            return Rows([(False, False)])
        if "SHOW transaction_isolation" in query:
            return Rows([("repeatable read",)])
        if "SHOW transaction_read_only" in query:
            return Rows([("on",)])
        if "pg_class" in query:
            return Rows([(42, "r", False, False)])
        if "pg_inherits" in query or "has_table_privilege" in query:
            return Rows([(False,)])
        if "information_schema.columns" in query:
            return Rows(
                [
                    ("id", "integer", 32, 0, "int4", None, "pg_catalog"),
                    ("memo", "text", None, None, "text", None, "pg_catalog"),
                ]
            )
        if "pg_index" in query:
            return Rows([("id",)])
        raise AssertionError(f"unexpected query: {query}")


def configure(monkeypatch: pytest.MonkeyPatch, rows: list[tuple[Any, ...]]) -> FakeConnection:
    monkeypatch.setenv("PORTCO_SOURCE_POSTGRES_URL", "postgresql://r:private-password@localhost/source?sslmode=disable")
    conn = FakeConnection(rows)
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: conn)
    return conn


def test_snapshot_roundtrip_provenance_and_immutable_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch, [(1, "memo\nwith,comma", False), (2, None, False)])
    path = manifest(tmp_path)
    receipt = import_postgres(path, tmp_path / "sources")
    assert receipt["provenance"]["read_only"] is True
    assert receipt["provenance"]["kind"] == "postgresql-snapshot"
    assert receipt["inputs"][0]["rows"] == 2
    assert "private-password" not in json.dumps(receipt)
    assert "localhost" not in json.dumps(receipt)
    registered = json.loads((tmp_path / "sources/pg-v1/registration.json").read_text())
    assert registered == receipt
    spec = resolve_csv("csv:pg-v1", tmp_path / "sources")
    with duckdb.connect(spec.path, read_only=True) as conn:
        assert conn.execute("select * from billing.invoices order by id").fetchall() == [
            (1, "memo\nwith,comma"),
            (2, None),
        ]
    with pytest.raises(DomainError, match="already exists"):
        import_postgres(path, tmp_path / "sources")


@pytest.mark.security
@pytest.mark.parametrize(
    ("limit", "rows", "message"),
    [
        ({"max_rows": 1}, [(1, "x", False), (2, "y", False)], "row limit"),
        ({"max_bytes": 1}, [(1, "x", False)], "byte limit"),
        ({}, [(1, None, True)], "row exceeds"),
        ({}, [(1, r"\N", False)], "null-marker"),
    ],
)
def test_failed_partial_extract_never_registers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: dict[str, int], rows: list[tuple[Any, ...]], message: str
) -> None:
    configure(monkeypatch, rows)
    with pytest.raises(ValidationFailed, match=message):
        import_postgres(manifest(tmp_path, **limit), tmp_path / "sources")
    assert not (tmp_path / "sources").exists()


@pytest.mark.security
def test_provider_error_and_cli_do_not_disclose_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, [])

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise psycopg.OperationalError("private-password and customer-value")

    monkeypatch.setattr(psycopg, "connect", fail)
    result = CliRunner().invoke(app, ["sources", "import-postgres", str(manifest(tmp_path))])
    assert result.exit_code == 2
    assert "private-password" not in result.output
    assert "customer-value" not in result.output
    assert "PostgreSQL import failed" in result.output


@pytest.mark.security
def test_ambient_connection_overrides_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, [])
    monkeypatch.setenv("PGHOSTADDR", "other-host")
    with pytest.raises(ValidationFailed, match="ambient"):
        import_postgres(manifest(tmp_path), tmp_path / "sources")


@pytest.mark.security
@pytest.mark.parametrize(
    ("needle", "replacement", "message"),
    [
        ("pg_roles", [(True, False)], "superuser"),
        ("pg_roles", [(False, True)], "superuser"),
        ("SHOW transaction_isolation", [("read committed",)], "isolation"),
        ("SHOW transaction_read_only", [("off",)], "isolation"),
        ("pg_class", [(42, "v", False, False)], "ordinary"),
        ("pg_class", [(42, "r", True, False)], "ordinary"),
        ("pg_class", [(42, "r", False, True)], "ordinary"),
        ("pg_inherits", [(True,)], "inherited"),
        ("has_table_privilege", [(True,)], "SELECT-only"),
        ("pg_index", [], "primary key"),
        ("information_schema.columns", [("memo", "text", None, None, "text", None, "pg_catalog")], "drifted"),
        ("information_schema.columns", [("id", "integer", 32, 0, "int4", None, "attacker")], "custom"),
    ],
)
def test_authority_and_schema_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, needle: str, replacement: list[tuple[Any, ...]], message: str
) -> None:
    conn = configure(monkeypatch, [(1, "x", False)])
    execute = conn.execute

    def altered(query: Any, params: Any = None) -> Rows:
        if isinstance(query, str) and needle in query:
            return Rows(list(replacement))
        return execute(query, params)

    monkeypatch.setattr(conn, "execute", altered)
    with pytest.raises(ValidationFailed, match=message):
        import_postgres(manifest(tmp_path), tmp_path / "sources")
    assert not (tmp_path / "sources").exists()


def test_identical_contents_have_reproducible_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, [(1, "x", False)])
    first = import_postgres(manifest(tmp_path), tmp_path / "sources")
    second = import_postgres(manifest(tmp_path, source_id="pg-v2"), tmp_path / "sources")
    assert first["inputs"] == second["inputs"]
    assert first["provenance"]["schema_sha256"] == second["provenance"]["schema_sha256"]


def test_total_extraction_deadline_leaves_no_registration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, [(1, "x", False)])
    clock = iter([0.0, 0.0, 121.0])
    monkeypatch.setattr("src.adapters.postgres_source.time.monotonic", lambda: next(clock))
    with pytest.raises(ValidationFailed, match="total time"):
        import_postgres(manifest(tmp_path), tmp_path / "sources")
    assert not (tmp_path / "sources").exists()
