"""Generated metric execution, independent coverage, cache identity and waiver binding."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import duckdb
import pytest
import yaml

from src.domain import metrics_reference as ref
from src.domain.errors import ValidationFailed
from src.domain.hashing import content_hash
from src.domain.models import StepName
from src.domain.ontology import load_ontology
from src.domain.project_models import ReconciliationCheck, TestReport
from src.services.generation import Generator
from src.services.sandbox import report_subject, sandbox_identity
from src.services.semantic import execute_metrics
from src.settings import Settings
from tests.conftest import AGENT, CompletedRun


def semantic_files() -> tuple[dict[str, str], list[str]]:
    ont = load_ontology()
    accepted = [
        SimpleNamespace(canonical_entity=e, canonical_field=f, pii_handling=None)
        for e, entity in ont.entities.items()
        for f in entity.fields
    ]
    resolved = SimpleNamespace(accepted=accepted, metrics_needing_evidence=[])
    gen = Generator(resolved, None, ont, "test", date(2026, 2, 28))
    gen.marts = {
        "invoice": {"name": "fct_invoice", "columns": {"invoice_id", "invoice_date", "currency", "total_amount"}},
        "_mrr": {
            "name": "fct_mrr_monthly",
            "columns": {"month_end", "currency", "mrr", "customer_id", "mrr_snapshot_id"},
        },
        "gl_entry": {
            "name": "fct_gl_entry",
            "columns": {"posting_date", "account_type", "debit_amount", "credit_amount", "gl_entry_key"},
        },
    }
    gen.build_semantic()
    return gen.files, gen.generated_metrics


def warehouse() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE fct_invoice(invoice_date DATE, currency VARCHAR, total_amount DECIMAL(18,2))")
    con.execute(
        "INSERT INTO fct_invoice VALUES ('2026-01-02','USD',100),('2026-01-03','USD',-20),('2026-01-02','EUR',30),('2026-02-02','USD',10)"
    )
    con.execute(
        "CREATE TABLE fct_mrr_monthly(month_end DATE, currency VARCHAR, mrr DECIMAL(18,2), customer_id VARCHAR)"
    )
    con.execute(
        "INSERT INTO fct_mrr_monthly VALUES ('2026-01-31','USD',10,'A'),('2026-01-31','EUR',20,'A'),('2026-01-31','USD',0,'B'),('2026-02-28','USD',15,'A')"
    )
    con.execute(
        "CREATE TABLE fct_gl_entry(posting_date DATE, account_type VARCHAR, debit_amount DECIMAL(18,2), credit_amount DECIMAL(18,2))"
    )
    con.execute(
        "INSERT INTO fct_gl_entry VALUES ('2026-01-01','revenue',0,100),('2026-01-02','revenue',20,0),('2026-01-02','cogs',10,0),('2026-01-02','opex',5,0),('2026-02-01','cogs',20,0)"
    )
    return con


def test_actual_generated_definitions_handle_reversals_currencies_grain_and_zero() -> None:
    files, names = semantic_files()
    with warehouse() as con:
        values = execute_metrics(con, files, names)
    assert set(values) == {
        "billings",
        "mrr",
        "arr",
        "active_customers",
        "revenue_recognized",
        "cogs",
        "opex",
        "ebitda",
        "gross_margin_pct",
    }
    assert values["billings"] == {"2026-01|USD": Decimal(80), "2026-01|EUR": Decimal(30), "2026-02|USD": Decimal(10)}
    assert values["arr"] == {"2026-01|USD": Decimal(120), "2026-01|EUR": Decimal(240), "2026-02|USD": Decimal(180)}
    assert values["active_customers"] == {"2026-01": 1, "2026-02": 1}
    lines = [
        ref.GlLineRec(date(2026, 1, 1), "revenue", Decimal(0), Decimal(100)),
        ref.GlLineRec(date(2026, 1, 2), "revenue", Decimal(20), Decimal(0)),
        ref.GlLineRec(date(2026, 1, 2), "cogs", Decimal(10), Decimal(0)),
        ref.GlLineRec(date(2026, 1, 2), "opex", Decimal(5), Decimal(0)),
        ref.GlLineRec(date(2026, 2, 1), "cogs", Decimal(20), Decimal(0)),
    ]
    assert values["ebitda"] == ref.ebitda(lines)
    assert values["gross_margin_pct"]["2026-01"] == float(ref.gross_margin_pct(lines)["2026-01"])
    assert values["gross_margin_pct"]["2026-02"] is None


def test_artifact_expression_mutation_changes_executed_values() -> None:
    files, names = semantic_files()
    path = "models/semantic/semantic_models.yml"
    model = yaml.safe_load(files[path])
    for sm in model["semantic_models"]:
        for measure in sm["measures"]:
            if measure["name"] == "cogs":
                measure["expr"] = "999"
    files[path] = yaml.safe_dump(model)
    with warehouse() as con:
        values = execute_metrics(con, files, names)
    assert values["cogs"]["2026-02"] == Decimal(999)
    assert values["ebitda"]["2026-02"] != Decimal(-20)


def test_missing_definition_fails_closed() -> None:
    files, names = semantic_files()
    files.pop("models/semantic/metrics/ebitda.yml")
    with warehouse() as con, pytest.raises(ValidationFailed):
        execute_metrics(con, files, names)


def test_waiver_subject_covers_values_but_not_runtime_noise() -> None:
    report = TestReport(
        manifest_hash="a",
        source_fingerprint="b",
        passed=False,
        dbt_exit_code=1,
        dbt_results=[],
        reconciliation=[
            ReconciliationCheck(
                name="metric:billings", passed=False, detail="different", expected={"m": "10"}, actual={"m": "9"}
            )
        ],
        failing_checks=["metric:billings"],
    )
    subject = content_hash(report_subject(report))
    assert (
        content_hash(
            report_subject(
                report.model_copy(
                    update={"cached": True, "duration_seconds": 123, "waived_checks": ["metric:billings"]}
                )
            )
        )
        == subject
    )
    changed = report.model_copy(
        update={"reconciliation": [report.reconciliation[0].model_copy(update={"actual": {"m": "90000"}})]}
    )
    assert content_hash(report_subject(changed)) != subject


def test_cache_identity_binds_full_hashes_code_and_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = SimpleNamespace(settings=Settings(), services={})
    bundle = SimpleNamespace(manifest_hash="a" * 64)
    resolved = SimpleNamespace(content_hash=lambda: "mapping")
    first = sandbox_identity(ctx, bundle, resolved, "b" * 64)
    assert first["manifest"] == "a" * 64 and first["source"] == "b" * 64
    monkeypatch.setattr("src.services.sandbox.pipeline_version", lambda: "changed")
    assert sandbox_identity(ctx, bundle, resolved, "b" * 64) != first
    before = sandbox_identity(ctx, bundle, resolved, "b" * 64)
    ctx.settings = Settings(sandbox_keep_attempts=5)
    assert sandbox_identity(ctx, bundle, resolved, "b" * 64) != before


@pytest.mark.slow
def test_completed_bundle_has_executed_reference_check_for_every_metric(completed_a: CompletedRun) -> None:
    svc, run = completed_a.service, completed_a.run_id
    bundle = svc.artifact(AGENT, run, StepName.ARTIFACT_GENERATION)
    report = svc.artifact(AGENT, run, StepName.AUTOMATED_TESTS)
    checks = {c.name.removeprefix("metric:"): c for c in report.reconciliation if c.name.startswith("metric:")}
    assert set(checks) == set(bundle.generated_metrics)
    assert all(c.passed for c in checks.values())
