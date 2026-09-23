"""Golden tests scored against fixture ground truth (POD-107). Thresholds live in thresholds.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import duckdb
import pytest
import yaml

from src.adapters.repositories import RunRecord
from src.domain.models import StepName
from src.domain.project_models import EntityInference, JoinGraph, MappingSet, SchemaProfile
from src.workflows.facade import OnboardingService
from tests.conftest import AGENT, CompletedRun, make_service

pytestmark = pytest.mark.golden
THRESHOLDS = yaml.safe_load((Path(__file__).parent / "thresholds.yaml").read_text(encoding="utf-8"))


class GateRun:
    def __init__(self, svc: OnboardingService, run: RunRecord) -> None:
        self.svc, self.run = svc, run

    def get(self, step: StepName) -> Any:
        return self.svc.artifact(AGENT, self.run.run_id, step)


@pytest.fixture(scope="module", params=["portco_a", "portco_b"])
def gate_run(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory, fixtures_dir: Path
) -> tuple[str, GateRun]:
    svc = make_service(tmp_path_factory.mktemp(request.param))
    run = anyio.run(lambda: svc.start_run(AGENT, f"fixture:{request.param}"))
    return request.param, GateRun(svc, run)


def _truth(name: str) -> dict[str, Any]:
    from src.fixtures.generate import load_ground_truth

    return load_ground_truth(name)


def test_primary_keys(gate_run: tuple[str, GateRun]) -> None:
    name, g = gate_run
    truth, t = _truth(name), THRESHOLDS[name]
    ents: EntityInference = g.get(StepName.ENTITY_INFERENCE)
    found = {c.table: c.primary_key_columns for c in ents.candidates if c.primary_key_columns}
    hits = sum(1 for table, pk in truth["primary_keys"].items() if found.get(table) == pk)
    recall = hits / len(truth["primary_keys"])
    precision = hits / max(1, sum(1 for table in found if table in truth["primary_keys"]))
    assert recall >= t["pk_recall"], found
    assert precision >= t.get("pk_precision", 0.0)
    assert {c.table: c.canonical_entity for c in ents.candidates if c.canonical_entity} == truth["entities"]


def test_joins(gate_run: tuple[str, GateRun]) -> None:
    name, g = gate_run
    truth, t = _truth(name), THRESHOLDS[name]
    joins: JoinGraph = g.get(StepName.JOIN_INFERENCE)
    got = {f"{j.left_table}.{j.left_columns[0]}->{j.right_table}.{j.right_columns[0]}": j for j in joins.joins}
    expected = {f"{e['left']}->{e['right']}": e for e in truth["joins"]}
    tp = set(got) & set(expected)
    assert len(tp) / len(expected) >= t["join_recall"], set(expected) - tp
    assert len(tp) / max(1, len(got)) >= t["join_precision"], set(got) - tp
    for key in tp:
        assert got[key].cardinality == expected[key]["cardinality"]
        assert (
            abs(got[key].orphan_rate - expected[key]["orphan_rate"]) <= THRESHOLDS["portco_a"]["orphan_rate_tolerance"]
        )
        if expected[key]["orphan_rate"] > 0:
            assert got[key].requires_review and "ORPHANS" in got[key].reason_codes


def test_mapping_accuracy_and_traps(gate_run: tuple[str, GateRun]) -> None:
    name, g = gate_run
    truth, t = _truth(name), THRESHOLDS[name]
    ms: MappingSet = g.get(StepName.CANONICAL_MAPPING)
    got = {p.mapping_key: p for p in ms.proposals}
    correct = sum(
        1
        for col, exp in truth["mappings"].items()
        if (exp is None and col not in got)
        or (col in got and f"{got[col].canonical_entity}.{got[col].canonical_field}" == exp)
        or (exp is None and col in got and got[col].requires_review)
    )
    assert correct / len(truth["mappings"]) >= t["mapping_top1"]
    for trap in truth["traps"]:
        p = got[trap["column"]]
        assert p.requires_review and trap["reason"] in p.reason_codes
    if name == "portco_b":
        assert set(truth["not_applicable_metrics"]) <= set(ms.metrics_needing_evidence)


def test_pii_classification(gate_run: tuple[str, GateRun]) -> None:
    name, g = gate_run
    truth = _truth(name)
    profile: SchemaProfile = g.get(StepName.SCHEMA_PROFILING)
    got = {f"{t.qualified}.{c.column}": c.pii_class.value for t in profile.tables for c in t.columns if c.pii_class}
    for col, cls in truth["pii_columns"].items():
        assert got.get(col) == cls, (col, got.get(col))
    critical = [c for c, cls in truth["pii_columns"].items() if cls in {"national_id", "payment_card", "email"}]
    assert all(got.get(c) for c in critical)


@pytest.mark.slow
def test_end_to_end_marts_match_independent_ground_truth(completed_a: CompletedRun, truth_a: dict[str, Any]) -> None:
    """The published marts reproduce the fixture generator's own bookkeeping, exactly."""
    from src.services.sandbox import sandbox_run_dir

    wh_path = next(sandbox_run_dir(completed_a.root / "sandbox", completed_a.run_id).glob("*/warehouse.duckdb"))
    src_path = wh_path.parent / "source.duckdb"
    con = duckdb.connect(str(wh_path), read_only=True)
    con.execute(f"ATTACH '{src_path.as_posix()}' AS src (READ_ONLY)")
    exp = truth_a["expected_metrics"]
    months = set(truth_a["months"])

    billings = {
        k: str(v)
        for k, v in con.execute(
            "SELECT strftime(invoice_date, '%Y-%m') || '|' || currency, cast(sum(total_amount) AS DECIMAL(18,2)) "
            "FROM fct_invoice GROUP BY 1"
        ).fetchall()
    }
    assert billings == exp["billings"]
    arr = {
        k: str(v)
        for k, v in con.execute(
            "SELECT strftime(month_end, '%Y-%m') || '|' || currency, cast(sum(mrr) * 12 AS DECIMAL(18,2)) "
            "FROM fct_mrr_monthly GROUP BY 1"
        ).fetchall()
        if k.split("|")[0] in months
    }
    assert arr == exp["arr"]
    active = {
        k: v
        for k, v in con.execute(
            "SELECT strftime(month_end, '%Y-%m'), count(DISTINCT customer_id) FROM fct_mrr_monthly WHERE mrr > 0 "
            "GROUP BY 1"
        ).fetchall()
        if k in months
    }
    assert active == exp["active_customers"]
    revenue = {
        k: str(v)
        for k, v in con.execute(
            "SELECT strftime(posting_date, '%Y-%m'), cast(sum(credit_amount - debit_amount) AS DECIMAL(18,2)) "
            "FROM fct_gl_entry WHERE account_type = 'revenue' GROUP BY 1"
        ).fetchall()
    }
    assert revenue == exp["revenue_recognized"]
    con.close()
