"""Regression tests for the 2026-10-10 ingestion audit (A07, A08, A11-A14, PERF-1, PERF-3).

Each case goes through the real boundary: the SQL guard against actual DuckDB binding,
`import_csv`/`import_postgres` plus `resolve_csv` and `ConnectionRegistry` for reopen.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import psycopg
import pytest

from src.adapters import csv_source, postgres_source
from src.adapters.csv_source import (
    MAX_CATEGORY_LABELS,
    MAX_REGISTRATION_BYTES,
    RESERVED_SCHEMAS,
    CsvManifest,
    _cell,
    _load_connection,
    import_csv,
    resolve_csv,
    resolve_csv_owner,
)
from src.adapters.external import ConnectionRegistry
from src.adapters.postgres_source import FETCH_BATCH_ROWS, PostgresManifest, import_postgres
from src.adapters.sql_guard import check_select
from src.domain.errors import DomainError, NotFound, PolicyViolation, ValidationFailed
from tests.test_postgres_source import FakeCursor, configure
from tests.test_postgres_source import manifest as pg_manifest


@pytest.fixture(autouse=True)
def clean_pg_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in os.environ:
        if key.startswith("PG"):
            monkeypatch.delenv(key)


def write_source(
    tmp_path: Path, tables: list[tuple[str, str, dict[str, str], str]], **updates: Any
) -> tuple[Path, Path]:
    """tables: (schema, table, columns, csv text). Returns (manifest path, store path)."""
    doc: dict[str, Any] = {"source_id": "audit-v1", "company_id": "audit_co", "as_of": "2025-12-31", "tables": []}
    for n, (schema, table, columns, text) in enumerate(tables):
        (tmp_path / f"t{n}.csv").write_text(text, encoding="utf-8", newline="")
        doc["tables"].append({"schema_name": schema, "table_name": table, "file": f"t{n}.csv", "columns": columns})
    doc.update(updates)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    return path, tmp_path / "sources"


def assert_nothing_registered(store: Path) -> None:
    assert not store.exists() or not any(store.iterdir())


# --------------------------------------------------------------------------- A07 / ING-01 CTE scope

SENTINEL = 999


@pytest.fixture
def physical() -> duckdb.DuckDBPyConnection:
    """A database whose excluded default schema holds sentinel rows under every CTE name used."""
    con = duckdb.connect()
    for name in ("secrets", "a", "b", "x"):
        con.execute(f"CREATE TABLE main.{name} AS SELECT {SENTINEL} AS v, {SENTINEL} AS secret")
    con.execute("CREATE SCHEMA billing")
    con.execute("CREATE TABLE billing.invoices AS SELECT 1 AS v")
    yield con
    con.close()


@pytest.mark.security
@pytest.mark.parametrize(
    "sql",
    [
        "WITH secrets AS (SELECT * FROM secrets) SELECT sum(secret) FROM secrets",
        "WITH x AS (SELECT * FROM secrets), secrets AS (SELECT 1 AS secret) SELECT * FROM x",
        "WITH a AS (SELECT 1 AS v UNION ALL SELECT v + 1 FROM a WHERE v < 3) SELECT max(v) FROM a",
    ],
)
def test_self_and_forward_cte_references_are_physical_and_rejected(
    physical: duckdb.DuckDBPyConnection, sql: str
) -> None:
    # Actual DuckDB binds these names to the excluded physical table, not the CTE.
    result = physical.execute(sql).fetchall()
    assert any(SENTINEL in row for row in result) or result == [(1,)]
    with pytest.raises(PolicyViolation):
        check_select(sql, {"billing"})


@pytest.mark.security
@pytest.mark.parametrize(
    "sql",
    [
        # Outer CTE hidden by a same-named inner self reference: conservatively unbound.
        "WITH a AS (SELECT 1 AS v) SELECT * FROM (WITH a AS (SELECT v + 1 AS v FROM a) SELECT * FROM a)",
        # Forward sibling hides the outer CTE of that name.
        "WITH a AS (SELECT 1 AS v) SELECT * FROM (WITH x AS (SELECT * FROM a), a AS (SELECT 2 AS v) SELECT * FROM x)",
        # DuckDB folds ASCII case only; a non-ASCII case variant is a different (physical) name.
        'WITH "é" AS (SELECT 1 AS v) SELECT * FROM "É"',
        "WITH RECURSIVE a AS (SELECT 1 AS v UNION ALL SELECT v + 1 FROM a WHERE v < 3) SELECT max(v) FROM a",
        "WITH a AS (SELECT 1 AS v), a AS (SELECT 2 AS v) SELECT * FROM a",
        "SELECT * FROM (WITH l AS (SELECT 1) SELECT * FROM l) AS x, l",
        "SELECT * FROM secrets",
    ],
)
def test_unprovable_cte_bindings_and_recursion_are_rejected(sql: str) -> None:
    with pytest.raises(PolicyViolation):
        check_select(sql, {"billing"})


@pytest.mark.parametrize(
    "sql",
    [
        "WITH a AS (SELECT 1 AS v), b AS (SELECT * FROM a) SELECT * FROM b",
        "WITH a AS (SELECT 1 AS v) SELECT * FROM (WITH b AS (SELECT * FROM a) SELECT * FROM b)",
        "WITH a AS (SELECT 1 AS v) SELECT * FROM (WITH a AS (SELECT 2 AS v) SELECT * FROM a)",
        "WITH a AS (SELECT 1 AS v) SELECT (SELECT max(v) FROM a)",
        'WITH "A" AS (SELECT 1 AS v) SELECT * FROM a',
        "WITH a AS (SELECT v FROM billing.invoices), b AS (SELECT v FROM a WHERE v IN (SELECT v FROM a)) "
        "SELECT * FROM b",
    ],
)
def test_visible_cte_bindings_pass_and_never_read_physical_tables(
    physical: duckdb.DuckDBPyConnection, sql: str
) -> None:
    check_select(sql, {"billing"})
    assert all(SENTINEL not in row for row in physical.execute(sql).fetchall())


# --------------------------------------------------------------------------- A11 / ING-02 case folding


@pytest.mark.parametrize(
    "tables",
    [
        [("Billing", "invoices", {"id": "INTEGER"}, "id\n1\n"), ("billing", "payments", {"id": "INTEGER"}, "id\n1\n")],
        [("billing", "Invoices", {"id": "INTEGER"}, "id\n1\n"), ("billing", "invoices", {"id": "INTEGER"}, "id\n1\n")],
    ],
)
def test_case_folded_schema_or_table_collisions_rejected_before_staging(
    tmp_path: Path, tables: list[tuple[str, str, dict[str, str], str]]
) -> None:
    manifest, store = write_source(tmp_path, tables)
    with pytest.raises(ValidationFailed, match="letter case"):
        import_csv(manifest, tmp_path, store)
    assert not store.exists()


def test_category_domain_keys_must_match_declared_spelling(tmp_path: Path) -> None:
    manifest, store = write_source(
        tmp_path,
        [("billing", "invoices", {"status": "VARCHAR"}, "status\nopen\n")],
        category_domains={"BILLING.invoices.status": ["open"]},
    )
    with pytest.raises(ValidationFailed, match="category domain keys"):
        import_csv(manifest, tmp_path, store)
    assert not store.exists()


def test_postgres_case_sensitive_schema_collision_rejected_before_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch, [])
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: pytest.fail("must not connect"))
    table = {"table_name": "invoices", "primary_key": ["id"], "columns": {"id": "INTEGER"}}
    path = pg_manifest(tmp_path, tables=[{**table, "schema_name": "Billing"}, {**table, "schema_name": "billing"}])
    with pytest.raises(ValidationFailed, match="letter case"):
        PostgresManifest.model_validate_json(path.read_bytes())
    with pytest.raises(ValidationFailed, match="letter case"):
        import_postgres(path, tmp_path / "sources")
    assert not (tmp_path / "sources").exists()


def test_mixed_case_schema_spelling_imports_reopens_and_profiles(tmp_path: Path) -> None:
    manifest, store = write_source(
        tmp_path,
        [
            ("Billing", "Invoices", {"id": "INTEGER", "status": "VARCHAR"}, "id,status\n1,open\n2,paid\n"),
            ("Billing", "payments", {"invoice_id": "INTEGER"}, "invoice_id\n1\n3\n"),
        ],
        category_domains={"Billing.Invoices.status": ["open", "paid"]},
    )
    import_csv(manifest, tmp_path, store)
    adapter = ConnectionRegistry(tmp_path / "fixtures", store).open("csv:audit-v1")
    try:
        assert adapter.list_schemas() == ["Billing"]
        assert adapter.list_tables("Billing") == ["Invoices", "payments"]
        assert adapter.row_count("Billing", "Invoices") == 2
        assert adapter.low_cardinality_values("Billing", "Invoices", "status", 12).values == ["open", "paid"]
        contained = adapter.containment(("Billing", "payments", "invoice_id"), ("Billing", "Invoices", "id"))
        assert (contained.distinct_left, contained.distinct_matched, contained.rows_orphan) == (2, 1, 1)
    finally:
        adapter.close()


# --------------------------------------------------------------------------- A12 / ING-03 registration size


def test_duplicate_category_labels_are_deduplicated_and_registration_resolves(tmp_path: Path) -> None:
    # The audit's reproduction: 560 KB of input that previously expanded to a 1.68 MB registration.
    manifest, store = write_source(
        tmp_path,
        [("billing", "records", {"status": "VARCHAR"}, "status\nx\n")],
        category_domains={"billing.records.status": ["x"] * 140_000},
    )
    receipt = import_csv(manifest, tmp_path, store)
    assert receipt["category_domains"] == {"billing.records.status": ["x"]}
    assert (store / "audit-v1" / "registration.json").stat().st_size <= MAX_REGISTRATION_BYTES
    assert resolve_csv("csv:audit-v1", store).category_domains == {"billing.records.status": ["x"]}


def wide_domains(tmp_path: Path, columns: int) -> tuple[Path, Path]:
    names = {f"c{n:03d}": "VARCHAR" for n in range(columns)}
    domains = {f"billing.records.{name}": [f"{i:03d}" for i in range(MAX_CATEGORY_LABELS)] for name in names}
    return write_source(
        tmp_path,
        [("billing", "records", names, ",".join(names) + "\n" + ",".join("001" for _ in names) + "\n")],
        category_domains=domains,
    )


def test_registration_larger_than_resolver_limit_is_rejected_before_any_work(tmp_path: Path) -> None:
    manifest, store = wide_domains(tmp_path, 128)
    assert manifest.stat().st_size <= csv_source.MAX_MANIFEST_BYTES  # valid input size
    with pytest.raises(ValidationFailed, match="registration would exceed"):
        import_csv(manifest, tmp_path, store)
    assert not store.exists()


def test_near_limit_registration_remains_resolvable(tmp_path: Path) -> None:
    manifest, store = wide_domains(tmp_path, 60)
    import_csv(manifest, tmp_path, store)
    size = (store / "audit-v1" / "registration.json").stat().st_size
    assert MAX_REGISTRATION_BYTES // 2 < size <= MAX_REGISTRATION_BYTES
    assert len(resolve_csv("csv:audit-v1", store).category_domains) == 60


def test_too_many_distinct_labels_rejected(tmp_path: Path) -> None:
    manifest, store = write_source(
        tmp_path,
        [("billing", "records", {"status": "VARCHAR"}, "status\nx\n")],
        category_domains={"billing.records.status": [str(i) for i in range(MAX_CATEGORY_LABELS + 1)]},
    )
    with pytest.raises(ValidationFailed, match="at most"):
        import_csv(manifest, tmp_path, store)
    assert not store.exists()


def test_final_registration_check_includes_provenance(tmp_path: Path) -> None:
    manifest, store = write_source(tmp_path, [("billing", "records", {"id": "INTEGER"}, "id\n1\n")])
    with pytest.raises(ValidationFailed, match="registration would exceed"):
        import_csv(manifest, tmp_path, store, provenance={"tables": ["t" * MAX_REGISTRATION_BYTES]})
    assert_nothing_registered(store)


def test_postgres_oversized_registration_rejected_before_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch, [])
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: pytest.fail("must not connect"))
    columns = {"id": "INTEGER", **{f"c{n:03d}": "VARCHAR" for n in range(127)}}
    domains = {f"billing.invoices.c{n:03d}": [f"{i:03d}" for i in range(MAX_CATEGORY_LABELS)] for n in range(127)}
    table = {"schema_name": "billing", "table_name": "invoices", "primary_key": ["id"], "columns": columns}
    path = pg_manifest(tmp_path, tables=[table], category_domains=domains)
    with pytest.raises(ValidationFailed, match="registration would exceed"):
        import_postgres(path, tmp_path / "sources")
    assert not (tmp_path / "sources").exists()


# --------------------------------------------------------------------------- A13 / ING-04 timestamp precision


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025-01-01T00:00:00.123456", datetime(2025, 1, 1, 0, 0, 0, 123456)),
        ("2025-01-01T00:00:00.1234560", datetime(2025, 1, 1, 0, 0, 0, 123456)),
        ("2025-01-01T00:00:00.100000000", datetime(2025, 1, 1, 0, 0, 0, 100000)),
        ("2025-01-01T00:00:00,5", datetime(2025, 1, 1, 0, 0, 0, 500000)),
        ("20250101T123456", datetime(2025, 1, 1, 12, 34, 56)),
        ("2025-01-01 12:34", datetime(2025, 1, 1, 12, 34)),
    ],
)
def test_timestamp_precision_contract_accepts(value: str, expected: datetime) -> None:
    assert _cell(value, "TIMESTAMP") == expected


@pytest.mark.parametrize(
    "value",
    ["2025-01-01T00:00:00.1234567", "2025-01-01T00:00:00.0000001", "2025-01-01T00:00:00,1234561", "2025-01-01T00:00Z"],
)
def test_timestamp_precision_contract_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        _cell(value, "TIMESTAMP")


def test_submicrosecond_timestamp_import_rejected_and_microseconds_preserved(tmp_path: Path) -> None:
    columns = {"id": "INTEGER", "at": "TIMESTAMP"}
    manifest, store = write_source(tmp_path, [("events", "log", columns, "id,at\n1,2025-01-01T00:00:00.1234567\n")])
    with pytest.raises(ValidationFailed) as exc:
        import_csv(manifest, tmp_path, store)
    assert "1234567" not in str(exc.value)
    assert_nothing_registered(store)
    (tmp_path / "t0.csv").write_text(
        "id,at\n1,2025-01-01T00:00:00.123456\n2,2025-01-01T00:00:00.1234560\n", encoding="utf-8"
    )
    import_csv(manifest, tmp_path, store)
    with duckdb.connect(resolve_csv("csv:audit-v1", store).path, read_only=True) as con:
        assert con.execute('SELECT "at" FROM events.log ORDER BY id').fetchall() == [
            (datetime(2025, 1, 1, 0, 0, 0, 123456),),
            (datetime(2025, 1, 1, 0, 0, 0, 123456),),
        ]


# --------------------------------------------------------------------------- A14 / ING-05 reserved schemas


@pytest.mark.parametrize("schema", sorted(RESERVED_SCHEMAS | {"Source", "TEMP"}))
def test_reserved_schema_names_rejected_with_explanation_before_work(tmp_path: Path, schema: str) -> None:
    manifest, store = write_source(tmp_path, [(schema, "records", {"id": "INTEGER"}, "id\n1\n")])
    with pytest.raises(ValidationFailed, match="reserved"):
        import_csv(manifest, tmp_path, store)
    assert not store.exists()


def test_reserved_schema_rejected_for_postgres_manifest(tmp_path: Path) -> None:
    table = {"schema_name": "source", "table_name": "records", "primary_key": ["id"], "columns": {"id": "INTEGER"}}
    with pytest.raises(ValidationFailed, match="reserved"):
        PostgresManifest.model_validate_json(pg_manifest(tmp_path, tables=[table]).read_bytes())


def test_reserved_set_covers_names_duckdb_cannot_serve() -> None:
    # Each reserved name except the hidden `main` and `memory` actually breaks a source.duckdb snapshot.
    assert {"source", "system", "temp", "information_schema", "pg_catalog"} <= RESERVED_SCHEMAS
    assert {"main", "memory"} <= RESERVED_SCHEMAS


# --------------------------------------------------------------------------- A08 owner metadata


def test_owner_lookup_reads_registration_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, store = write_source(tmp_path, [("billing", "records", {"id": "INTEGER"}, "id\n1\n")])
    import_csv(manifest, tmp_path, store)
    snapshot = store / "audit-v1" / "source.duckdb"
    with snapshot.open("ab") as stream:
        stream.write(b"tampered")  # integrity would fail if the snapshot were touched

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("snapshot must not be opened or hashed")

    monkeypatch.setattr(csv_source, "_sha", forbidden)
    monkeypatch.setattr(duckdb, "connect", forbidden)
    assert resolve_csv_owner("csv:audit-v1", store) == "audit_co"
    with pytest.raises(NotFound):
        resolve_csv_owner("csv:missing", store)
    with pytest.raises(DomainError):
        resolve_csv_owner("csv:../audit-v1", store)
    monkeypatch.undo()
    with pytest.raises(ValidationFailed, match="integrity"):
        resolve_csv("csv:audit-v1", store)


def test_owner_lookup_rejects_invalid_or_oversized_registration(tmp_path: Path) -> None:
    directory = tmp_path / "sources" / "bad"
    directory.mkdir(parents=True)
    registration = directory / "registration.json"
    for content in (
        {"format_version": 1, "connection_id": "csv:other", "company_id": "x"},
        {"format_version": 2, "connection_id": "csv:bad", "company_id": "x"},
        {"format_version": 1, "connection_id": "csv:bad", "company_id": 7},
        {"format_version": 1, "connection_id": "csv:bad"},
    ):
        registration.write_text(json.dumps(content), encoding="utf-8")
        with pytest.raises(ValidationFailed, match="registration"):
            resolve_csv_owner("csv:bad", tmp_path / "sources")
    registration.write_text(" " * (MAX_REGISTRATION_BYTES + 1), encoding="utf-8")
    with pytest.raises(ValidationFailed, match="byte limit"):
        resolve_csv_owner("csv:bad", tmp_path / "sources")
    registration.write_text(json.dumps({"format_version": 1, "connection_id": "csv:bad", "company_id": "../x"}))
    with pytest.raises(PolicyViolation):
        resolve_csv_owner("csv:bad", tmp_path / "sources")


# --------------------------------------------------------------------------- PERF-1 PostgreSQL batching


class CountingCursor(FakeCursor):
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        super().__init__(rows)
        self.requests: list[int] = []

    def fetchone(self) -> Any:
        raise AssertionError("per-row FETCH round trips are not allowed")

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        self.requests.append(size)
        return super().fetchmany(size)


def test_postgres_rows_are_fetched_in_bounded_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [(n, None if n % 7 == 0 else f'memo {n}, "quoted"\nline', False) for n in range(1, 101)]
    conn = configure(monkeypatch, rows)
    cursors: list[CountingCursor] = []

    def cursor(name: str) -> CountingCursor:
        cursors.append(CountingCursor(list(rows)))
        return cursors[-1]

    monkeypatch.setattr(conn, "cursor", cursor)
    receipt = import_postgres(pg_manifest(tmp_path), tmp_path / "sources")
    assert FETCH_BATCH_ROWS * postgres_source.MAX_ROW_BYTES <= 32 * 1024 * 1024
    assert cursors[0].requests == [FETCH_BATCH_ROWS] * 5  # 4 data batches + end of cursor, not 101
    assert receipt["inputs"][0]["rows"] == 100
    with duckdb.connect(resolve_csv("csv:pg-v1", tmp_path / "sources").path, read_only=True) as con:
        assert con.execute("SELECT * FROM billing.invoices ORDER BY id").fetchall() == [r[:-1] for r in rows]


@pytest.mark.security
@pytest.mark.parametrize("failure", ["deadline", "oversized", "rows"])
def test_failure_inside_a_later_batch_never_registers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    rows = [(n, "x", failure == "oversized" and n == 40) for n in range(1, 50)]
    configure(monkeypatch, rows)
    limits: dict[str, Any] = {"max_rows": 45} if failure == "rows" else {}
    if failure == "deadline":
        ticks = iter(range(10_000))
        # Deadline is 120 s after the first tick; expire while reading the second batch.
        monkeypatch.setattr(
            "src.adapters.postgres_source.time.monotonic", lambda: (lambda t: 0.0 if t < 40 else 500.0)(next(ticks))
        )
    with pytest.raises(ValidationFailed):
        import_postgres(pg_manifest(tmp_path, **limits), tmp_path / "sources")
    assert not (tmp_path / "sources").exists()


# --------------------------------------------------------------------------- PERF-3 native bulk load equivalence

TYPES = {
    "s": "VARCHAR",
    "i": "INTEGER",
    "g": "BIGINT",
    "f": "BOOLEAN",
    "d": "DATE",
    "t": "TIMESTAMP",
    "m": "DECIMAL(18,2)",
    "z": "DECIMAL(38,10)",
    "w": "DECIMAL(5,0)",
}
EDGE_ROWS = [
    [
        "",
        "-2147483648",
        "-9223372036854775808",
        "true",
        "0001-01-01",
        "0001-01-01T00:00:00",
        "1234567890123456.78",
        "1234567890123456789012345678.1234567890",
        "99999",
    ],
    [
        "\\N",
        "2147483647",
        "9223372036854775807",
        "FALSE",
        "9999-12-31",
        "9999-12-31T23:59:59.999999",
        "-0.01",
        "-1e-10",
        "-99999",
    ],
    [" lead and trail ", "+5", "-0", "True", "20251231", "20250101T123456", "1E+2", "0E-10", "0"],
    ['a,b "quoted" ""', "007", "\\N", "\\N", "2024-02-29", "2025-01-01T12:34:56,25", "1.50000", "99", "\\N"],
    ["line\nbreak\r\nand\rcr", "0", "1", "false", "2025-W01-1", "2025-01-01 12:34", "-0", "0.0000000001", "12345"],
    ["é—\U0001f600 ﻿bom\ttab", "\\N", "0", "true", "\\N", "\\N", "\\N", "\\N", "1"],
    ["\\N\\", "1", "2", "true", "2025-01-01", "2025-01-01", "0.1", "1", "2"],
    ["NULL", "1", "2", "true", "2025-01-01", "2025-01-01T00:00:00.1234560", "0.10", "1.0", "2"],
    ["nul\x00inside", "1", "2", "true", "0099-05-06", "0099-05-06T01:02:03", "3", "4", "5"],
]
EXPECTED = [
    (
        "",
        -2147483648,
        -9223372036854775808,
        True,
        date(1, 1, 1),
        datetime(1, 1, 1),
        Decimal("1234567890123456.78"),
        Decimal("1234567890123456789012345678.1234567890"),
        Decimal("99999"),
    ),
    (
        None,
        2147483647,
        9223372036854775807,
        False,
        date(9999, 12, 31),
        datetime(9999, 12, 31, 23, 59, 59, 999999),
        Decimal("-0.01"),
        Decimal("-1E-10"),
        Decimal("-99999"),
    ),
    (
        " lead and trail ",
        5,
        0,
        True,
        date(2025, 12, 31),
        datetime(2025, 1, 1, 12, 34, 56),
        Decimal("100.00"),
        Decimal("0"),
        Decimal("0"),
    ),
    (
        'a,b "quoted" ""',
        7,
        None,
        None,
        date(2024, 2, 29),
        datetime(2025, 1, 1, 12, 34, 56, 250000),
        Decimal("1.50"),
        Decimal("99"),
        None,
    ),
    (
        "line\nbreak\r\nand\rcr",
        0,
        1,
        False,
        date(2024, 12, 30),
        datetime(2025, 1, 1, 12, 34),
        Decimal("0"),
        Decimal("1E-10"),
        Decimal("12345"),
    ),
    ("é—\U0001f600 ﻿bom\ttab", None, 0, True, None, None, None, None, Decimal("1")),
    ("\\N\\", 1, 2, True, date(2025, 1, 1), datetime(2025, 1, 1), Decimal("0.1"), Decimal("1"), Decimal("2")),
    (
        "NULL",
        1,
        2,
        True,
        date(2025, 1, 1),
        datetime(2025, 1, 1, 0, 0, 0, 123456),
        Decimal("0.1"),
        Decimal("1"),
        Decimal("2"),
    ),
    (
        "nul\x00inside",
        1,
        2,
        True,
        date(99, 5, 6),
        datetime(99, 5, 6, 1, 2, 3),
        Decimal("3"),
        Decimal("4"),
        Decimal("5"),
    ),
]


def edge_csv() -> str:
    import csv
    import io

    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(list(TYPES))
    writer.writerows(EDGE_ROWS)
    return out.getvalue()


def test_native_bulk_load_preserves_exact_values(tmp_path: Path) -> None:
    single = 'only\n\\N\n""\nx\n\\N\n'
    manifest, store = write_source(
        tmp_path,
        [("billing", "records", TYPES, "﻿" + edge_csv()), ("billing", "single", {"only": "VARCHAR"}, single)],
    )
    receipt = import_csv(manifest, tmp_path, store)
    assert [i["rows"] for i in receipt["inputs"]] == [len(EDGE_ROWS), 4]
    assert sorted(p.name for p in (store / "audit-v1").iterdir()) == ["registration.json", "source.duckdb"]
    with duckdb.connect(resolve_csv("csv:audit-v1", store).path, read_only=True) as con:
        actual = con.execute("SELECT * FROM billing.records").fetchall()
        assert actual == EXPECTED
        assert [str(row[6]) for row in actual if row[6] is not None][:3] == ["1234567890123456.78", "-0.01", "100.00"]
        assert con.execute("SELECT * FROM billing.single").fetchall() == [(None,), ("",), ("x",), (None,)]
        declared = con.execute(
            "SELECT column_name, data_type FROM duckdb_columns() WHERE table_name = 'records' ORDER BY column_index"
        ).fetchall()
        assert declared == [(n, "DECIMAL(18,2)" if t == "DECIMAL(18,2)" else t) for n, t in TYPES.items()]

    # Same values through the previous row-wise parameterized insert of the validated cells.
    with duckdb.connect() as ref:
        ref.execute(f"CREATE TABLE r ({', '.join(f'{n} {t}' for n, t in TYPES.items())})")
        cells = [[_cell(v, t) for v, t in zip(row, TYPES.values(), strict=True)] for row in EDGE_ROWS]
        ref.executemany(f"INSERT INTO r VALUES ({','.join('?' for _ in TYPES)})", cells)
        assert ref.execute("SELECT * FROM r").fetchall() == actual


def test_native_bulk_load_handles_rows_longer_than_duckdb_default_line(tmp_path: Path) -> None:
    columns = {f"c{n}": "VARCHAR" for n in range(20)}
    wide = "é" * 120_000  # within the CSV field limit; two UTF-8 bytes each
    text = ",".join(columns) + "\n" + ",".join(wide for _ in columns) + "\n" + ",".join("x" for _ in columns) + "\n"
    manifest, store = write_source(tmp_path, [("billing", "wide", columns, text)])
    import_csv(manifest, tmp_path, store)
    with duckdb.connect(resolve_csv("csv:audit-v1", store).path, read_only=True) as con:
        assert con.execute("SELECT length(c0), length(c19), c19 = ? FROM billing.wide", [wide]).fetchall()[0] == (
            120_000,
            120_000,
            True,
        )


@pytest.mark.security
def test_bulk_load_connection_reads_only_its_staged_files(tmp_path: Path) -> None:
    allowed = tmp_path / "load" / "table-00.csv"
    allowed.parent.mkdir()
    allowed.write_text('"1","1"\n', encoding="utf-8")
    sibling = tmp_path / "load" / "other.csv"
    sibling.write_text("secret\n", encoding="utf-8")
    con = _load_connection(tmp_path / "db.duckdb", [allowed])
    try:
        assert con.execute("SELECT count(*) FROM read_csv(?, header=false)", [str(allowed)]).fetchone() == (1,)
        for statement in (
            f"SELECT * FROM read_csv('{sibling}')",
            f"COPY (SELECT 1) TO '{tmp_path / 'out.csv'}'",
            f"ATTACH '{tmp_path / 'other.duckdb'}' AS other",
        ):
            with pytest.raises(duckdb.Error):
                con.execute(statement)
        for statement in ("SET enable_external_access = true", f"SET allowed_directories = ['{tmp_path}']"):
            with pytest.raises(duckdb.Error):
                con.execute(statement)
    finally:
        con.close()


def test_invalid_value_in_bulk_path_registers_nothing(tmp_path: Path) -> None:
    manifest, store = write_source(tmp_path, [("billing", "records", {"i": "INTEGER"}, "i\n1\n2147483648\n")])
    with pytest.raises(ValidationFailed) as exc:
        import_csv(manifest, tmp_path, store)
    assert "2147483648" not in str(exc.value)
    assert_nothing_registered(store)


def test_manifest_dedup_is_reflected_in_model() -> None:
    model = CsvManifest.model_validate(
        {
            "source_id": "s",
            "company_id": "c",
            "as_of": "2025-01-01",
            "tables": [{"schema_name": "b", "table_name": "t", "file": "t.csv", "columns": {"x": "VARCHAR"}}],
            "category_domains": {"b.t.x": ["a", "b", "a"]},
        }
    )
    assert model.category_domains == {"b.t.x": ["a", "b"]}
