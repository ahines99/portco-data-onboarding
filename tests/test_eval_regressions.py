"""Regression tests for selection, cache isolation and evaluation evidence quality."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from evals import checks, drivers
from evals.judge_eval import challenge_scores, enablement_decision
from evals.run import DIMENSIONS, evaluate, gate
from src.domain.hashing import content_hash
from src.domain.models import Confidence, Evidence, Finding, StepName

pytestmark = pytest.mark.unit


@pytest.mark.anyio
@pytest.mark.parametrize("ids", [[], ["G999"], ["G01", "G999"]])
async def test_selection_rejects_empty_or_unknown(ids, tmp_path):
    with pytest.raises(ValueError):
        await evaluate(ids, tmp_path)


def test_empty_and_failed_partial_reports_never_pass():
    report = {
        "cases_total": 0,
        "cases_passed": 0,
        "total_seconds": 0,
        "dimensions": {d: {"total": 0, "rate": None} for d in DIMENSIONS},
    }
    thresholds = {"min_cases_passing": 1, "dimensions": {}, "max_total_seconds": 10}
    assert gate(report, thresholds, full_run=False)
    report.update(cases_total=1)
    assert gate(report, thresholds, full_run=False)


@pytest.mark.anyio
async def test_driver_cache_accounts_for_reject_waive_and_normalizes_inputs(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(b"fixture")
    svc = SimpleNamespace(connections=SimpleNamespace(resolve=lambda _: SimpleNamespace(path=source)))
    monkeypatch.setattr(drivers, "build_service", lambda *args: svc)
    calls = []

    async def drive(*args):
        calls.append(args)
        return SimpleNamespace(run_id=uuid4())

    monkeypatch.setattr(drivers, "drive", drive)
    cache = {}
    base = {"id": "A", "fixture": "portco_a"}
    initial = await drivers.run_case(base, tmp_path, cache)
    assert await drivers.run_case(base | {"id": "B", "reject": [], "waive": False}, tmp_path, cache) is initial
    assert await drivers.run_case(base | {"reject": ["mapping:x"]}, tmp_path, cache) is not initial
    assert await drivers.run_case(base | {"waive": True}, tmp_path, cache) is not initial
    assert len(calls) == 3


def test_judge_gate_allows_saturation_but_rejects_low_bucket_regression():
    perfect = {"accuracy": 1.0, "calibration": {"high": 1.0}}
    baseline = {"accuracy": 0.5, "calibration": {"medium": 0.5, "low": 0.5}}
    better = {"accuracy": 0.75, "calibration": {"medium": 1.0, "low": 0.5}}
    pairs = [("portco_a", perfect, perfect), ("heldout_challenges", baseline, better)]
    assert enablement_decision(pairs)[0]
    better["calibration"]["low"] = 0.4
    eligible, reasons = enablement_decision(pairs)
    assert not eligible and any("low calibration" in r for r in reasons)
    assert not enablement_decision([("portco_a", perfect, perfect)])[0]


def test_challenge_cases_exercise_actual_judge_application():
    class Judge:
        name = "test"

        def judge(self, proposal, column, table, ontology):
            choices = {"KUNAG": "customer_id", "payment_due_on": "due_date"}
            return {"choice": choices.get(column.column, proposal.canonical_field)}

    base, judged = challenge_scores("replay", Judge())
    assert base["accuracy"] == 0.5 and judged["accuracy"] == 1.0
    assert judged["consulted"] == 4
    assert set(judged["calibration"]) == {"low", "medium"}


def test_mapping_metrics_explicitly_report_unlabeled_proposals(monkeypatch):
    proposals = [
        SimpleNamespace(mapping_key=k, canonical_entity="invoice", canonical_field="status", confidence=Confidence.HIGH)
        for k in ("known", "unknown")
    ]
    cr = SimpleNamespace(
        run_id=uuid4(), service=SimpleNamespace(artifact=lambda *args: SimpleNamespace(proposals=proposals))
    )
    monkeypatch.setattr(checks, "_truth", lambda cr: {"mappings": {"known": "invoice.status"}})
    assert checks.mapping_scores(cr)[0] == 1.0
    coverage = checks.mapping_coverage(cr)
    assert coverage["unlabeled_proposals"] == ["unknown"]
    assert coverage["labeled_proposal_fraction"] == 0.5


@pytest.mark.anyio
async def test_evidence_requires_outputs_and_actual_claim_support():
    payload = {"schema_name": "crm", "table_name": "accounts", "row_count": 5}
    ev = Evidence(
        source_uri="profile://crm.accounts",
        source_type="table_profile",
        payload=payload,
        content_hash=content_hash(payload),
    )
    finding = Finding(
        code="EMPTY_TABLE",
        title="Empty",
        statement="No rows",
        confidence=Confidence.HIGH,
        evidence=[ev.ref()],
        metadata={"table": "crm.accounts"},
    )
    findings = []
    cr = SimpleNamespace(
        run_id=uuid4(), service=SimpleNamespace(findings=lambda *args: findings, evidence=lambda *args: ev)
    )
    assert not (await checks.evidence_fidelity(cr, {}))[0]
    findings.append(finding)
    assert not (await checks.evidence_fidelity(cr, {}))[0]  # resolvable citation contradicts the claim
    payload["row_count"] = 0
    ev = ev.model_copy(update={"payload": payload, "content_hash": content_hash(payload)})
    findings[0] = finding.model_copy(update={"evidence": [ev.ref()]})
    assert (await checks.evidence_fidelity(cr, {}))[0]


@pytest.mark.anyio
@pytest.mark.parametrize("damage", ["missing", "altered", "extra"])
async def test_publication_check_verifies_disk_bytes(tmp_path: Path, damage):
    data = b"select 1"
    file = SimpleNamespace(path="model.sql", sha256=hashlib.sha256(data).hexdigest())
    fields = {
        "version": "v0001",
        "manifest_hash": "a",
        "certification_id": str(uuid4()),
        "published_metrics": ["billings"],
        "excluded_metrics": [],
    }
    receipt = SimpleNamespace(**fields, path=str(tmp_path), model_dump=lambda **kwargs: fields)
    artifacts = {StepName.PUBLISH: receipt, StepName.ARTIFACT_GENERATION: SimpleNamespace(files=[file])}
    cr = SimpleNamespace(run_id=uuid4(), service=SimpleNamespace(artifact=lambda p, r, s: artifacts[s]))
    (tmp_path / "model.sql").write_bytes(data)
    (tmp_path / "certification.json").write_text(json.dumps({"receipt": fields}))
    assert (await checks.published(cr, {}))[0]
    if damage == "missing":
        (tmp_path / "model.sql").unlink()
    elif damage == "altered":
        (tmp_path / "model.sql").write_bytes(b"select 2")
    else:
        (tmp_path / "unapproved.sql").write_bytes(b"select 3")
    assert not (await checks.published(cr, {}))[0]
