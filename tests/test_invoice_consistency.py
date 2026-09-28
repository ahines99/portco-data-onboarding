"""Every invoice must reconcile; large populations cannot hide individual discrepancies."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from src.domain.models import ReviewGate, RunStatus, StepName
from src.fixtures.generate import generate
from src.services.sandbox import reconcile
from src.settings import Settings
from src.workflows.facade import OnboardingService
from tests.conftest import AGENT, REVIEWER, decide_all


def consistency_check(count: int, adjustments: dict[int, Decimal | None]):
    with duckdb.connect() as con:
        con.execute(
            "CREATE TABLE fct_invoice AS SELECT range AS invoice_id, "
            "100.00::DECIMAL(18,2) AS total_amount FROM range(?)",
            [count],
        )
        con.execute("CREATE TABLE fct_invoice_line AS SELECT invoice_id, total_amount AS amount FROM fct_invoice")
        for invoice_id, difference in adjustments.items():
            if difference is None:
                con.execute("UPDATE fct_invoice SET total_amount=NULL WHERE invoice_id=?", [invoice_id])
            else:
                con.execute("UPDATE fct_invoice_line SET amount=amount+? WHERE invoice_id=?", [difference, invoice_id])
        checks = reconcile(
            None,
            con,
            SimpleNamespace(joins=[]),
            SimpleNamespace(models=["fct_invoice", "fct_invoice_line"], generated_metrics=[]),
            None,
            {},
        )
    return checks[0]


@pytest.mark.unit
@pytest.mark.parametrize("count", [1, 1000, 1923])
@pytest.mark.parametrize("difference", [Decimal("0.01"), Decimal("100.00"), Decimal("-100.00")])
def test_every_invoice_must_reconcile_regardless_of_population(count, difference):
    check = consistency_check(count, {0: difference})
    assert not check.passed
    assert check.blocking
    assert check.actual["mismatched_invoices"] == 1
    assert Decimal(check.actual["maximum_absolute_difference"]) == abs(difference)
    assert check.actual["matched_invoices"] == count - 1


@pytest.mark.unit
@pytest.mark.parametrize("count", [0, 1, 1923])
def test_all_matching_invoices_pass(count):
    check = consistency_check(count, {})
    assert check.passed
    assert check.actual["mismatched_invoices"] == 0


@pytest.mark.unit
def test_opposite_discrepancies_do_not_cancel():
    check = consistency_check(1923, {0: Decimal("100.00"), 1: Decimal("-100.00")})
    assert not check.passed
    assert check.actual["mismatched_invoices"] == 2
    assert Decimal(check.actual["maximum_absolute_difference"]) == Decimal("100.00")


@pytest.mark.unit
def test_unknown_header_amount_fails_without_hiding_unknown_difference():
    check = consistency_check(1923, {0: None})
    assert not check.passed
    assert check.actual["mismatched_invoices"] == 1
    assert check.actual["unknown_differences"] == 1


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.anyio
async def test_fixture_mismatch_stops_at_test_failures_before_certification(tmp_path: Path):
    fixtures = tmp_path / "fixtures"
    source = generate("portco_a", fixtures, write_truth=False)
    with duckdb.connect(str(source)) as con:
        # Pick an invoice that survives both billing and CRM scope filters.
        row = con.execute(
            "SELECT l.line_id FROM billing.invoice_lines l "
            "JOIN billing.invoices i USING(inv_no) JOIN billing.customers c USING(cust_id) "
            "JOIN crm.accounts a ON c.crm_account_ref = a.acct_id "
            "WHERE NOT a.is_deleted AND c.cust_name NOT LIKE 'TEST%' "
            "AND a.acct_nm NOT LIKE 'TEST%' AND l.amount > 0 ORDER BY l.line_id LIMIT 1"
        ).fetchone()
        assert row is not None
        con.execute("UPDATE billing.invoice_lines SET amount=amount+10000 WHERE line_id=?", [row[0]])
    svc = OnboardingService.build(
        Settings(
            _env_file=None,
            var_root=tmp_path / "state",
            fixtures_root=fixtures,
            env="test",
            log_level="WARNING",
            step_backoff_base_seconds=0,
        )
    )
    run = await svc.start_run(AGENT, "fixture:portco_a")
    assert run.gate == ReviewGate.MAPPING_REVIEW.value
    svc.submit_review(
        REVIEWER,
        run.run_id,
        decide_all(run.pending_items),
        subject_hash=run.pending_items[0].subject_hash,
        gate=ReviewGate(run.gate),
    )
    run = await svc.resume(AGENT, run.run_id)
    assert run.status is RunStatus.NEEDS_REVIEW
    assert run.gate == ReviewGate.TEST_FAILURES.value
    report = svc.artifact(AGENT, run.run_id, StepName.AUTOMATED_TESTS)
    assert not report.passed
    assert report.failing_checks == ["consistency:invoice_lines_sum_to_header"]
    check = next(c for c in report.reconciliation if c.name == report.failing_checks[0])
    assert check.actual["invoices"] >= 1000
    assert check.actual["mismatched_invoices"] == 1
    assert Decimal(check.actual["maximum_absolute_difference"]) == Decimal("100.00")
    assert not list(svc.settings.published_root.rglob("certification.json"))
