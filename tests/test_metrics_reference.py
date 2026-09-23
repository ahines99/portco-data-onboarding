"""Deterministic reference calculators (POD-108): hand-computed micro fixtures + fixture A truth."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from typing import Any

import pytest

from src.domain import metrics_reference as ref
from src.fixtures import portco_a

pytestmark = pytest.mark.unit


def sub(cust: str, mrr: str, start: date, end: date | None = None, ccy: str = "USD") -> ref.SubscriptionRec:
    return ref.SubscriptionRec(cust, D(mrr), ccy, start, end)


def test_calendar_helpers() -> None:
    assert ref.month_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert ref.month_end("2024-02") == date(2024, 2, 29)
    assert ref.shift_month("2026-01", -12) == "2025-01"
    assert ref.days_in_month("2025-02") == 28


@pytest.mark.parametrize(
    ("d", "start", "expected"),
    [(date(2025, 2, 1), 2, "FY2026-P01"), (date(2026, 1, 31), 2, "FY2026-P12"), (date(2025, 5, 3), 1, "FY2025-P05")],
)
def test_fiscal_period(d: date, start: int, expected: str) -> None:
    assert ref.fiscal_period(d, start) == expected


def test_fiscal_period_rejects_bad_month() -> None:
    with pytest.raises(ValueError):
        ref.fiscal_period(date(2025, 1, 1), 13)


def test_billings_groups_by_month_and_currency_with_bankers_rounding() -> None:
    inv = [
        ref.InvoiceRec("1", "c1", date(2025, 1, 3), D("10.005"), "USD"),
        ref.InvoiceRec("2", "c2", date(2025, 1, 9), D("0.010"), "USD"),
        ref.InvoiceRec("3", "c1", date(2025, 1, 9), D("5.00"), "EUR"),
    ]
    assert ref.billings(inv) == {("2025-01", "EUR"): D("5.00"), ("2025-01", "USD"): D("10.02")}


def test_mrr_uses_exclusive_end_dates_at_month_end() -> None:
    subs = [
        sub("a", "100", date(2025, 1, 15)),
        sub("b", "50", date(2025, 1, 1), date(2025, 1, 31)),
        sub("c", "70", date(2025, 1, 1), date(2025, 2, 1)),
    ]
    # b ends on Jan 31 (exclusive) -> not active at Jan 31; c ends Feb 1 -> active at Jan 31.
    assert ref.mrr(subs, ["2025-01"]) == {("2025-01", "USD"): D("170.00")}
    assert ref.arr(subs, ["2025-01"]) == {("2025-01", "USD"): D("2040.00")}
    assert ref.active_customers(subs, ["2025-01", "2025-02"]) == {"2025-01": 2, "2025-02": 1}


def test_arr_bridge_new_expansion_contraction_churn_and_return() -> None:
    subs = [
        sub("new", "100", date(2025, 2, 10)),
        sub("up", "100", date(2024, 12, 1), date(2025, 2, 1)),
        sub("up", "150", date(2025, 2, 1)),
        sub("down", "200", date(2024, 12, 1), date(2025, 2, 1)),
        sub("down", "120", date(2025, 2, 1)),
        sub("gone", "80", date(2024, 12, 1), date(2025, 2, 15)),
        sub("back", "60", date(2024, 12, 1), date(2025, 1, 15)),
        sub("back", "60", date(2025, 2, 20)),
    ]
    mv = ref.arr_movements(subs, ["2025-02"])[("2025-02", "USD")]
    assert mv == ref.ArrMovement(new=D("1920.00"), expansion=D("600.00"), contraction=D("960.00"), churned=D("960.00"))


def test_arr_bridge_edges_empty_window_and_flat_customers() -> None:
    assert ref.arr_movements([], []) == {}
    # A customer whose MRR is unchanged moves nothing, so the month has no bridge row at all.
    assert ref.arr_movements([sub("flat", "100", date(2024, 1, 1))], ["2025-02"]) == {}


def test_zero_mrr_subscriptions_count_nowhere() -> None:
    # A free (zero-MRR) plan is neither in the retention cohort nor an account for ARPA.
    subs = [sub("free", "0", date(2024, 1, 1)), sub("paid", "100", date(2024, 1, 1))]
    assert ref.nrr(subs, "2025-01") == {"USD": D("1.0000")}
    assert ref.arpa(subs, ["2025-01"]) == {("2025-01", "USD"): D("1200.00")}


def test_retention_undefined_without_starting_cohort() -> None:
    assert ref.nrr([sub("a", "10", date(2025, 6, 1))], "2025-12") == {"USD": None}


def test_nrr_and_grr() -> None:
    subs = [
        sub("a", "100", date(2024, 1, 1)),
        sub("b", "100", date(2024, 1, 1), date(2024, 6, 1)),
        sub("a", "50", date(2024, 6, 1)),
    ]
    # Start (Jan 2024): a=100, b=100. End (Jan 2025): a=150 (expanded), b churned.
    assert ref.nrr(subs, "2025-01") == {"USD": D("0.7500")}
    assert ref.grr(subs, "2025-01") == {"USD": D("0.5000")}


def test_arpa() -> None:
    subs = [sub("a", "100", date(2025, 1, 1)), sub("b", "300", date(2025, 1, 1))]
    assert ref.arpa(subs, ["2025-01"]) == {("2025-01", "USD"): D("2400.00")}


def test_gl_metrics_and_zero_revenue_months() -> None:
    lines = [
        ref.GlLineRec(date(2025, 1, 5), "revenue", D("0"), D("1000")),
        ref.GlLineRec(date(2025, 1, 5), "revenue", D("50"), D("0")),  # credit note
        ref.GlLineRec(date(2025, 1, 31), "cogs", D("200"), D("0")),
        ref.GlLineRec(date(2025, 1, 31), "opex", D("300"), D("0")),
        ref.GlLineRec(date(2025, 1, 31), "da", D("40"), D("0")),
        ref.GlLineRec(date(2025, 2, 28), "opex", D("10"), D("0")),
        ref.GlLineRec(date(2025, 2, 28), "cogs", D("5"), D("0")),  # costs but no revenue
    ]
    assert ref.revenue_recognized(lines) == {"2025-01": D("950.00")}
    assert ref.gross_margin_pct(lines) == {"2025-01": D("0.7895"), "2025-02": None}
    assert ref.ebitda(lines) == {"2025-01": D("450.00"), "2025-02": D("-15.00")}


def test_headcount_and_dso() -> None:
    emps = [ref.EmployeeRec(date(2024, 1, 1), None), ref.EmployeeRec(date(2024, 3, 1), date(2025, 1, 31))]
    assert ref.headcount(emps, ["2025-01"]) == {"2025-01": 1}
    inv = [
        ref.InvoiceRec("i1", "c", date(2025, 1, 1), D("300"), "USD"),
        ref.InvoiceRec("i2", "c", date(2025, 2, 1), D("0"), "USD"),
    ]
    pay = [ref.PaymentRec("i1", date(2025, 1, 20), D("100"))]
    out = ref.dso(inv, pay, ["2025-01", "2025-02", "2025-03"])
    assert out[("2025-01", "USD")] == D("20.67")  # 200 open / 300 billed * 31 days
    assert out[("2025-03", "USD")] is None  # no billings -> undefined, not zero


# --------------------------------------------------------------------------- fixture A truth


def _fixture_records() -> dict[str, Any]:
    fx = portco_a.build()
    test_customers = {r[0] for r in fx.table("billing.customers").rows if str(r[2]).startswith("TEST")}
    invoices = [
        ref.InvoiceRec(r[0], str(r[1]), r[2], r[4], r[5])
        for r in fx.table("billing.invoices").rows
        if r[1] not in test_customers
    ]
    subs = [
        ref.SubscriptionRec(str(r[1]), r[3], r[4], r[5], r[6])
        for r in fx.table("billing.subscriptions").rows
        if r[1] not in test_customers
    ]
    types = {r[0]: r[2] for r in fx.table("erp.gl_accounts").rows}
    gl = [ref.GlLineRec(r[3], types[r[2]], r[4], r[5]) for r in fx.table("erp.journal_lines").rows]
    return {"invoices": invoices, "subs": subs, "gl": gl}


@pytest.mark.golden
def test_reference_calculators_match_fixture_a_ground_truth(truth_a: dict[str, Any]) -> None:
    recs = _fixture_records()
    months = truth_a["months"]
    exp = truth_a["expected_metrics"]
    billings = {f"{m}|{c}": str(v) for (m, c), v in ref.billings(recs["invoices"]).items()}
    assert billings == exp["billings"]
    arr = {f"{m}|{c}": str(v) for (m, c), v in ref.arr(recs["subs"], months).items()}
    assert arr == exp["arr"]
    assert ref.active_customers(recs["subs"], months) == exp["active_customers"]
    assert {k: str(v) for k, v in ref.revenue_recognized(recs["gl"]).items()} == exp["revenue_recognized"]
