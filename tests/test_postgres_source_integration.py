"""Actual source-connector checks in isolated PostgreSQL business databases.

The configured CI database is only an administrative endpoint. No workflow table
is read, written or migrated by these tests.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from scripts.postgres_test_db import disposable_database
from src.adapters.csv_source import resolve_csv
from src.adapters.postgres_source import import_postgres
from src.domain.errors import ValidationFailed

URL = os.environ.get("PORTCO_TEST_POSTGRES_URL")
pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not URL, reason="PORTCO_TEST_POSTGRES_URL not set")]


@pytest.fixture
def business_source(monkeypatch: pytest.MonkeyPatch) -> Iterator[psycopg.Connection[Any]]:
    assert URL
    for key in os.environ:
        if key.startswith("PG"):
            monkeypatch.delenv(key)
    with disposable_database(URL, allow_create=os.environ.get("PORTCO_TEST_POSTGRES_ALLOW_CREATE") == "1") as db_url:
        admin_url = make_url(db_url).set(drivername="postgresql")
        role = f"portco_test_reader_{uuid4().hex}"
        password = secrets.token_urlsafe(32)
        with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(password))
            )
            try:
                admin.execute("CREATE SCHEMA billing")
                admin.execute("CREATE TABLE billing.invoices (id integer PRIMARY KEY, amount numeric(18,2), memo text)")
                admin.execute(
                    "CREATE TABLE billing.adjustments (id integer PRIMARY KEY, amount numeric(18,2), memo text)"
                )
                admin.execute(
                    "INSERT INTO billing.invoices VALUES (1, 1234567890123456.78, 'original'), (2, NULL, NULL)"
                )
                admin.execute("INSERT INTO billing.adjustments VALUES (1, 1.25, 'original')")
                admin.execute(sql.SQL("GRANT USAGE ON SCHEMA billing TO {}").format(sql.Identifier(role)))
                admin.execute(
                    sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA billing TO {}").format(sql.Identifier(role))
                )
                reader_url = admin_url.set(username=role, password=password).update_query_dict({"sslmode": "disable"})
                monkeypatch.setenv("PORTCO_SOURCE_POSTGRES_URL", reader_url.render_as_string(hide_password=False))
                yield admin
            finally:
                admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def source_manifest(tmp_path: Path, **updates: Any) -> Path:
    doc = {
        "source_id": "postgres-business-v1",
        "company_id": "synthetic_business",
        "as_of": "2025-12-31",
        "tables": [
            {
                "schema_name": "billing",
                "table_name": name,
                "primary_key": ["id"],
                "columns": {"id": "INTEGER", "amount": "DECIMAL(18,2)", "memo": "VARCHAR"},
            }
            for name in ("invoices", "adjustments")
        ],
    }
    doc.update(updates)
    path = tmp_path / "postgres.json"
    path.write_text(json.dumps(doc))
    return path


def test_actual_postgres_repeatable_snapshot_exact_money_and_no_source_writes(
    business_source: psycopg.Connection[Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.adapters import postgres_source

    original = postgres_source._check_table
    checks = 0

    def concurrent_change(conn: Any, table: Any) -> Any:
        nonlocal checks
        result = original(conn, table)
        assert conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
        assert conn.execute("SHOW transaction_isolation").fetchone() == ("repeatable read",)
        checks += 1
        if checks == 1:
            business_source.execute("UPDATE billing.invoices SET memo='concurrently changed'")
            business_source.execute("UPDATE billing.adjustments SET memo='concurrently changed'")
        return result

    monkeypatch.setattr(postgres_source, "_check_table", concurrent_change)
    receipt = import_postgres(source_manifest(tmp_path), tmp_path / "sources")
    assert checks == 2
    assert sum(t["rows"] for t in receipt["inputs"]) == 3
    spec = resolve_csv("csv:postgres-business-v1", tmp_path / "sources")
    with duckdb.connect(spec.path, read_only=True) as snapshot:
        assert snapshot.execute("SELECT amount, memo FROM billing.invoices ORDER BY id").fetchall() == [
            (Decimal("1234567890123456.78"), "original"),
            (None, None),
        ]
        assert snapshot.execute("SELECT memo FROM billing.adjustments").fetchone() == ("original",)
    assert business_source.execute("SELECT count(*) FROM billing.invoices").fetchone() == (2,)
    # Repeatability is about contents; database-file bytes need not match across captures.
    monkeypatch.setattr(postgres_source, "_check_table", original)
    again = import_postgres(source_manifest(tmp_path, source_id="postgres-business-v2"), tmp_path / "sources")
    assert again["inputs"][0]["sha256"] != receipt["inputs"][0]["sha256"]
    assert again["provenance"]["schema_sha256"] == receipt["provenance"]["schema_sha256"]
    assert "concurrently changed" not in json.dumps(again)


@pytest.mark.parametrize(
    "mutation",
    [
        "ALTER TABLE billing.adjustments ADD COLUMN unexpected integer",
        "ALTER TABLE billing.adjustments ALTER COLUMN amount TYPE numeric(18,3)",
        "ALTER TABLE billing.adjustments DROP CONSTRAINT adjustments_pkey",
        "ALTER TABLE billing.adjustments ENABLE ROW LEVEL SECURITY",
    ],
)
def test_real_schema_drift_has_no_partial_registration(
    business_source: psycopg.Connection[Any],
    tmp_path: Path,
    mutation: str,
) -> None:
    business_source.execute(mutation)
    with pytest.raises(ValidationFailed):
        import_postgres(source_manifest(tmp_path), tmp_path / "sources")
    assert not (tmp_path / "sources").exists()


def test_real_row_bound_rejects_truncation(business_source: psycopg.Connection[Any], tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed, match="row limit"):
        import_postgres(source_manifest(tmp_path, max_rows=2), tmp_path / "sources")
    assert not (tmp_path / "sources").exists()


def test_all_tables_locked_before_snapshot_blocks_later_table_truncate(
    business_source: psycopg.Connection[Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.adapters import postgres_source

    original = postgres_source._check_table
    truncate_attempted = False

    def concurrent_truncate(conn: Any, table: Any) -> Any:
        nonlocal truncate_attempted
        result = original(conn, table)
        if not truncate_attempted:
            truncate_attempted = True
            # invoices is checked first, but adjustments must already be locked.
            # TRUNCATE is not MVCC-safe and could otherwise erase rows from the
            # importer's older snapshot without changing its schema or key.
            assert table.table_name == "invoices"
            business_source.execute("SET lock_timeout = '100ms'")
            try:
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    business_source.execute("TRUNCATE billing.adjustments")
            finally:
                business_source.execute("RESET lock_timeout")
        return result

    monkeypatch.setattr(postgres_source, "_check_table", concurrent_truncate)
    receipt = import_postgres(source_manifest(tmp_path), tmp_path / "sources")
    assert truncate_attempted
    assert sum(t["rows"] for t in receipt["inputs"]) == 3
    spec = resolve_csv("csv:postgres-business-v1", tmp_path / "sources")
    with duckdb.connect(spec.path, read_only=True) as snapshot:
        assert snapshot.execute("SELECT amount, memo FROM billing.adjustments").fetchall() == [
            (Decimal("1.25"), "original")
        ]
    assert business_source.execute("SELECT count(*) FROM billing.adjustments").fetchone() == (1,)


def test_write_capable_source_credentials_are_rejected(
    business_source: psycopg.Connection[Any],
    tmp_path: Path,
) -> None:
    role = make_url(os.environ["PORTCO_SOURCE_POSTGRES_URL"]).username
    assert role
    business_source.execute(sql.SQL("GRANT UPDATE ON billing.invoices TO {}").format(sql.Identifier(role)))
    with pytest.raises(ValidationFailed, match="SELECT-only"):
        import_postgres(source_manifest(tmp_path), tmp_path / "sources")
    assert not (tmp_path / "sources").exists()


def test_statement_timeout_aborts_waiting_source_without_registration(
    business_source: psycopg.Connection[Any],
    tmp_path: Path,
) -> None:
    business_source.execute("BEGIN")
    business_source.execute("LOCK TABLE billing.invoices IN ACCESS EXCLUSIVE MODE")
    try:
        with pytest.raises(ValidationFailed, match="PostgreSQL import failed"):
            import_postgres(source_manifest(tmp_path, statement_timeout_ms=100), tmp_path / "sources")
    finally:
        business_source.execute("ROLLBACK")
    assert not (tmp_path / "sources").exists()


@pytest.mark.anyio
@pytest.mark.slow
async def test_actual_source_connector_to_certified_publication(tmp_path: Path) -> None:
    from scripts.smoke_postgres_source import exercise

    result = await exercise(tmp_path)
    summary = result["shareable_summary"]
    assert result["status"] == "complete"
    assert result["input_tables"] == 11
    assert result["input_rows"] == 14639
    assert summary["live_source_removed_before_onboarding"]
    assert summary["service_rebuilt_at_review_gates"]
    assert summary["test_report_passed"] and summary["dbt_exit_code"] == 0
    assert summary["audit_chain_valid"] and not summary["waived_checks"]
    assert len(summary["published_metrics"]) == 9
    assert summary["generated_file_hashes_verified"] == summary["published_file_count"] - 1
    output = os.environ.get("PORTCO_POSTGRES_SOURCE_SUMMARY")
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
