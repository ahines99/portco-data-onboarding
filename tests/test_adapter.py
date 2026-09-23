"""Read-only aggregate-only source adapter and SQL guard (POD-300, POD-704, G29)."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from src.adapters.external import ConnectionRegistry, DuckDBAdapter, SourceAdapter
from src.adapters.faults import FaultInjector, FaultyAdapter
from src.adapters.sql_guard import check_select
from src.domain.errors import NotFound, PolicyViolation, SourceTimeout, SourceUnavailable

pytestmark = pytest.mark.security


@pytest.fixture
def adapter(fixtures_dir: Path) -> DuckDBAdapter:
    a = ConnectionRegistry(fixtures_dir).open("fixture:portco_a")
    yield a
    a.close()


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE billing.invoices",
        "INSERT INTO billing.invoices VALUES (1)",
        "SELECT 1; DROP TABLE billing.invoices",
        "ATTACH 'x.db' AS y",
        "COPY billing.invoices TO 'out.csv'",
        "SELECT * FROM read_csv('secrets.csv')",
        "SELECT * FROM hr.employees",  # not allowlisted below
        "SELECT getenv('HOME')",
        "UPDATE billing.invoices SET total_amt = 0",
    ],
)
def test_sql_guard_rejects(sql: str) -> None:
    with pytest.raises(PolicyViolation):
        check_select(sql, {"billing"})


def test_sql_guard_allows_aggregate_select_and_ctes() -> None:
    check_select('WITH l AS (SELECT DISTINCT "a" FROM "billing"."invoices") SELECT count(*) FROM l', {"billing"})


def test_adapter_opens_read_only_and_verifies(adapter: DuckDBAdapter) -> None:
    assert adapter.verify_read_only() is True
    assert adapter.probe().reachable


def test_adapter_has_no_row_fetch_api() -> None:
    names = {n for n, _ in inspect.getmembers(SourceAdapter, inspect.isfunction)}
    assert not {n for n in names if any(w in n for w in ("fetch", "rows", "sample", "select", "query", "head"))}


def test_ddl_through_adapter_is_blocked(adapter: DuckDBAdapter) -> None:
    with pytest.raises(PolicyViolation):
        adapter._query("DROP TABLE billing.invoices")


def test_unknown_columns_and_schemas_rejected(adapter: DuckDBAdapter) -> None:
    with pytest.raises(NotFound):
        adapter.pattern_counts("billing", "invoices", "nope", {"x": ("a", True)})
    with pytest.raises(PolicyViolation):
        adapter.row_count("information_schema", "tables")


def test_aggregates_match_known_counts(adapter: DuckDBAdapter) -> None:
    assert adapter.row_count("billing", "customers") == 127
    cont = adapter.containment(("billing", "customers", "crm_account_ref"), ("crm", "accounts", "acct_id"))
    assert cont.rows_orphan == 10 and cont.rows_left == 127
    assert adapter.luhn_count("billing", "payments", "card_number") > 0


def test_low_cardinality_values_are_guarded(adapter: DuckDBAdapter) -> None:
    assert adapter.low_cardinality_values("billing", "customers", "currency", 12).values == ["EUR", "GBP", "USD"]
    assert adapter.low_cardinality_values("crm", "contacts", "email", 12).values is None  # too many / PII


def test_schema_allowlist_via_connection_id(fixtures_dir: Path) -> None:
    reg = ConnectionRegistry(fixtures_dir)
    a = reg.open("fixture:portco_a?schemas=billing")
    try:
        assert a.list_schemas() == ["billing"]
        with pytest.raises(PolicyViolation):
            a.list_tables("hr")
    finally:
        a.close()


def test_missing_source_is_unavailable(tmp_path: Path) -> None:
    from src.domain.project_models import ConnectionSpec

    with pytest.raises(SourceUnavailable):
        DuckDBAdapter(ConnectionSpec(connection_id="x", company_id="x", path=str(tmp_path / "missing.duckdb")))


def test_fault_injector_nth_and_once(adapter: DuckDBAdapter) -> None:
    faulty = FaultyAdapter(adapter, FaultInjector.parse("adapter.aggregate:timeout:nth=2"))
    faulty.row_count("billing", "customers")
    with pytest.raises(SourceTimeout):
        faulty.row_count("billing", "customers")
    faulty.row_count("billing", "customers")


def test_fault_injection_refuses_production() -> None:
    with pytest.raises(PolicyViolation):
        FaultInjector.parse("adapter.aggregate:timeout", env="production")
