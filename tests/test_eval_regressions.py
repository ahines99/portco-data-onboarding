"""Regression tests for selection, cache isolation and evaluation evidence quality."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml

from evals import checks, drivers
from evals import run as eval_run
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


# --------------------------------------------------------------------------- full-run population gate (A16)

EVALS = Path(__file__).resolve().parents[1] / "evals"
THRESHOLDS = yaml.safe_load((EVALS / "thresholds.yaml").read_text(encoding="utf-8"))


def _full_report(thresholds: dict = THRESHOLDS) -> dict:
    """A passing full report shaped exactly like the pinned population."""
    cases = [{"id": case_id, "passed": True} for case_id in thresholds["required_cases"]]
    dims = {d: {"passed": n, "total": n, "rate": 1.0} for d, n in thresholds["min_checks"].items()}
    return {
        "cases": cases,
        "cases_total": len(cases),
        "cases_passed": len(cases),
        "total_seconds": 1,
        "dimensions": dims,
    }


def test_pinned_population_matches_the_real_corpus():
    corpus = yaml.safe_load((EVALS / "cases.yaml").read_text(encoding="utf-8"))
    ids = [c["id"] for c in corpus]
    assert len(ids) == len(set(ids))
    assert ids == THRESHOLDS["required_cases"]
    assert THRESHOLDS["min_cases_passing"] == len(ids)
    assert set(THRESHOLDS["dimensions"]) == set(THRESHOLDS["min_checks"]) == set(DIMENSIONS)
    counts = Counter(spec.get("dimension", checks.REGISTRY[spec["check"]][0]) for c in corpus for spec in c["checks"])
    assert set(counts) <= set(DIMENSIONS)
    for dim, floor in THRESHOLDS["min_checks"].items():
        assert counts[dim] >= floor, dim
    assert gate(_full_report(), THRESHOLDS, full_run=True) == []


@pytest.mark.parametrize("dim", DIMENSIONS)
@pytest.mark.parametrize("how", ["zero_checks", "absent"])
def test_full_run_fails_when_a_required_dimension_is_removed(dim, how):
    report = _full_report()
    if how == "absent":
        del report["dimensions"][dim]
    else:
        report["dimensions"][dim] = {"passed": 0, "total": 0, "rate": None}
    failures = gate(report, THRESHOLDS, full_run=True)
    assert f"dimension {dim}: no checks evaluated in a full run" in failures
    # The same report from an explicit --case selection is partial: absent dimensions are not evaluated.
    assert gate(report, THRESHOLDS, full_run=False) == []


def test_full_run_fails_when_a_dimension_loses_checks():
    report = _full_report()
    report["dimensions"]["permission"] = {"passed": 1, "total": 1, "rate": 1.0}
    failures = gate(report, THRESHOLDS, full_run=True)
    assert any(f.startswith("dimension permission: only 1 checks evaluated") for f in failures), failures


def test_full_run_fails_when_a_required_case_is_removed_or_duplicated():
    report = _full_report()
    report["cases"] = [c for c in report["cases"] if c["id"] != "G17"]
    report["cases_total"] = report["cases_passed"] = len(report["cases"])
    failures = gate(report, THRESHOLDS, full_run=True)
    assert "required case(s) not evaluated: G17" in failures
    assert any(f.startswith("only 36 cases passed") for f in failures)

    # Keeping the count while replacing a case with a duplicate is not the pinned identity set.
    report = _full_report()
    report["cases"][-1] = {"id": "G01", "passed": True}
    failures = gate(report, THRESHOLDS, full_run=True)
    assert "case id(s) evaluated more than once: G01" in failures
    assert "required case(s) not evaluated: G37" in failures

    report = _full_report()
    report["cases"].append({"id": "G99", "passed": True})
    report["cases_total"] = report["cases_passed"] = len(report["cases"])
    assert "case(s) not pinned in thresholds required_cases: G99" in gate(report, THRESHOLDS, full_run=True)


@pytest.mark.parametrize("full_run", [True, False])
def test_unknown_or_misspelled_dimension_fails_every_run(full_run):
    report = _full_report()
    report["dimensions"]["permision"] = {"passed": 1, "total": 1, "rate": 1.0}
    assert "checks reported unknown dimension(s): permision" in gate(report, THRESHOLDS, full_run=full_run)

    thresholds = {**THRESHOLDS, "dimensions": {**THRESHOLDS["dimensions"], "permision": 1.0}}
    del thresholds["dimensions"]["permission"]
    failures = gate(_full_report(), thresholds, full_run=full_run)
    assert "thresholds name unknown dimension(s): permision" in failures
    assert "thresholds omit required dimension(s): permission" in failures


def test_full_run_requires_pinned_population_configuration():
    thresholds = {k: v for k, v in THRESHOLDS.items() if k not in {"required_cases", "min_checks"}}
    failures = gate(_full_report(), thresholds, full_run=True)
    assert "thresholds must pin required_cases for a full run" in failures
    assert sum(f.startswith("min_checks must pin") for f in failures) == len(DIMENSIONS)


# Exact inputs from docs/audits/2026-10-10/evidence/agent-05-gate-probe.json; both passed the old gate.
_PROBE_DIMS_PASSING = {d: {"passed": 1, "total": 1, "rate": 1.0} for d in DIMENSIONS}
AUDIT_PROBES = {
    "missing_required_dimensions_full_run": {
        "cases_total": 37,
        "cases_passed": 37,
        "total_seconds": 1,
        "dimensions": _PROBE_DIMS_PASSING
        | {d: {"passed": 0, "total": 0, "rate": None} for d in ("evidence", "permission")},
    },
    "reduced_from_37_to_25_full_run": {
        "cases_total": 25,
        "cases_passed": 25,
        "total_seconds": 1,
        "dimensions": _PROBE_DIMS_PASSING,
    },
}


def test_audit_gate_probe_inputs_now_fail_the_full_gate():
    failures = gate(AUDIT_PROBES["missing_required_dimensions_full_run"], THRESHOLDS, full_run=True)
    assert "dimension evidence: no checks evaluated in a full run" in failures
    assert "dimension permission: no checks evaluated in a full run" in failures
    failures = gate(AUDIT_PROBES["reduced_from_37_to_25_full_run"], THRESHOLDS, full_run=True)
    assert any(f.startswith("only 25 cases passed") for f in failures), failures
    assert any(f.startswith("required case(s) not evaluated: G01") for f in failures), failures


@pytest.mark.anyio
async def test_duplicate_case_ids_in_the_corpus_are_rejected(tmp_path, monkeypatch):
    (tmp_path / "cases.yaml").write_text(
        "- {id: G01, title: a, fixture: portco_a, checks: [{check: status}]}\n"
        "- {id: G01, title: b, fixture: portco_a, checks: [{check: status}]}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(eval_run, "HERE", tmp_path)
    with pytest.raises(ValueError, match="duplicate eval case ids: G01"):
        await evaluate(None, tmp_path)


# --------------------------------------------------------------------------- report provenance (T4)


def test_report_provenance_identifies_source_inputs_runtime_and_selection():
    prov = eval_run.provenance(["--case", "G01"], ["G01"])
    commit = prov["source"]["commit"]
    assert commit is None or re.fullmatch(r"[0-9a-f]{40}", commit)
    assert prov["source"]["dirty"] in {True, False, None}
    digests = {k: v for k, v in prov["digests"].items() if k != "algorithm"}
    assert {"cases_sha256", "thresholds_sha256", "lockfile_sha256", "eval_harness_sha256", "pipeline_version"} <= set(
        digests
    )
    assert all(re.fullmatch(r"[0-9a-f]{64}", v) for v in digests.values()), digests
    assert prov["runtime"]["python"].startswith("3.12")
    assert prov["invocation"] | {"portco_env_overrides": [], "ci": {}} == {
        "command": "python -m evals.run",
        "argv": ["--case", "G01"],
        "scope": "partial",
        "selected_cases": ["G01"],
        "portco_env_overrides": [],
        "ci": {},
    }
    # Line endings do not change input digests, so Windows and Linux checkouts agree.
    assert prov["digests"]["thresholds_sha256"] == eval_run._sha256_lf([EVALS / "thresholds.yaml"])
    assert json.loads(json.dumps(prov)) == prov

    report = _full_report() | {"generated_at": "t", "scope": "partial", "provenance": prov}
    report["cases"] = [{"id": "G01", "title": "x", "passed": True, "seconds": 1, "evidences": [], "checks": []}]
    report["dimensions"]["cost"] = {"passed": 0, "total": 0, "rate": None}
    markdown = eval_run.to_markdown(report, [])
    assert "**Partial run:**" in markdown and "| cost | 0/0 | not evaluated |" in markdown
    assert "## Provenance" in markdown and "lockfile_sha256" in markdown


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
