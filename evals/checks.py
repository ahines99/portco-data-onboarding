"""Check registry for golden cases. Each check returns (passed, detail) and belongs to one dimension."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import duckdb

from evals.drivers import ADMIN, AGENT, REVIEWER, CaseRun, decisions
from src.adapters.external import ConnectionRegistry
from src.domain.errors import ApprovalRequired, DomainError, Forbidden, NotFound, PolicyViolation
from src.domain.models import FindingStatus, Principal, ReviewGate, Role, RunStatus, StepName
from src.domain.pii_guard import PiiGuard
from src.fixtures.generate import load_ground_truth
from src.reporting import render_run_report
from src.run_metrics import compute_run_metrics
from src.workflows.primary import PROJECT_STEPS

CheckFn = Callable[[CaseRun, dict[str, Any]], Awaitable[tuple[bool, str]]]
REGISTRY: dict[str, tuple[str, CheckFn]] = {}


def check(name: str, dimension: str) -> Callable[[CheckFn], CheckFn]:
    def deco(fn: CheckFn) -> CheckFn:
        REGISTRY[name] = (dimension, fn)
        return fn

    return deco


@dataclass
class CheckResult:
    case: str
    check: str
    dimension: str
    passed: bool
    detail: str


def emitted(cr: CaseRun) -> dict[str, Any]:
    svc, rid = cr.service, cr.run_id
    out: dict[str, Any] = {"findings": [f.model_dump(mode="json") for f in svc.findings(ADMIN, rid)]}
    for spec in PROJECT_STEPS:
        with contextlib.suppress(NotFound):
            out[spec.name.value] = svc.artifact(ADMIN, rid, spec.name).model_dump(mode="json")
    out["audit"] = [e.model_dump(mode="json") for e in svc.audit(ADMIN, rid)[0]]
    out["pending"] = [i.model_dump(mode="json") for i in cr.refresh().pending_items]
    try:
        bundle = svc.artifact(ADMIN, rid, StepName.ARTIFACT_GENERATION)
        out["files"] = {f.path: svc.store.blobs.get_bytes(f.sha256).decode() for f in bundle.files}
    except NotFound:
        pass
    out["report"] = render_run_report(svc, ADMIN, rid)
    return out


def _truth(cr: CaseRun) -> dict[str, Any]:
    return load_ground_truth(cr.run.company_id)


def _codes(cr: CaseRun) -> list[str]:
    return [f.code for f in cr.service.findings(ADMIN, cr.run_id)]


# --------------------------------------------------------------------------- state & findings


@check("status", "recovery")
async def status(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    run = cr.refresh()
    ok = run.status.value == a["expected"] and ("gate" not in a or run.gate == a["gate"])
    return ok, f"status={run.status.value} gate={run.gate}"


@check("findings_include", "uncertainty")
async def findings_include(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    missing = sorted(set(a["codes"]) - set(_codes(cr)))
    return not missing, f"missing {missing}" if missing else "all present"


@check("evidence_fidelity", "evidence")
async def evidence_fidelity(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    findings = cr.service.findings(ADMIN, cr.run_id)
    bad = []
    for f in findings:
        if f.status is FindingStatus.NEEDS_EVIDENCE:
            continue
        if not f.evidence:
            bad.append(f.code)
            continue
        for ref in f.evidence:
            try:
                cr.service.evidence(ADMIN, UUID(ref.source_id))
            except NotFound:
                bad.append(f.code)
    return not bad, f"{len(findings)} findings; unresolved: {sorted(set(bad))}"


# --------------------------------------------------------------------------- inference accuracy


@check("pk_accuracy", "uncertainty")
async def pk_accuracy(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    truth = _truth(cr)
    ents = cr.service.artifact(ADMIN, cr.run_id, StepName.ENTITY_INFERENCE)
    found = {c.table: c.primary_key_columns for c in ents.candidates}
    hits = sum(1 for t, pk in truth["primary_keys"].items() if found.get(t) == pk)
    recall = hits / len(truth["primary_keys"])
    return recall >= a.get("min_recall", 1.0), f"pk recall {recall:.2f}"


@check("join_accuracy", "uncertainty")
async def join_accuracy(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    truth = _truth(cr)
    joins = cr.service.artifact(ADMIN, cr.run_id, StepName.JOIN_INFERENCE)
    got = {f"{j.left_table}.{j.left_columns[0]}->{j.right_table}.{j.right_columns[0]}": j for j in joins.joins}
    exp = {f"{e['left']}->{e['right']}": e for e in truth["joins"]}
    tp = set(got) & set(exp)
    recall, precision = len(tp) / len(exp), len(tp) / max(1, len(got))
    orphan_ok = all(abs(got[k].orphan_rate - exp[k]["orphan_rate"]) <= 0.01 for k in tp)
    ok = recall >= a.get("min_recall", 0.9) and precision >= a.get("min_precision", 0.9) and orphan_ok
    return ok, f"join recall {recall:.2f} precision {precision:.2f} orphans_ok={orphan_ok}"


def mapping_scores(cr: CaseRun) -> tuple[float, dict[str, list[bool]]]:
    truth = _truth(cr)
    ms = cr.service.artifact(ADMIN, cr.run_id, StepName.CANONICAL_MAPPING)
    got = {p.mapping_key: p for p in ms.proposals}
    correct = 0
    buckets: dict[str, list[bool]] = defaultdict(list)
    for col, exp in truth["mappings"].items():
        p = got.get(col)
        ok = (
            (p is None and exp is None)
            or (p is not None and f"{p.canonical_entity}.{p.canonical_field}" == exp)
            or (exp is None and p is not None and p.requires_review)
        )
        correct += ok
        if p is not None:
            buckets[p.confidence.value].append(f"{p.canonical_entity}.{p.canonical_field}" == exp)
    return correct / len(truth["mappings"]), buckets


@check("mapping_accuracy", "uncertainty")
async def mapping_accuracy(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    acc, _buckets = mapping_scores(cr)
    return acc >= a["min"], f"top-1 accuracy {acc:.3f}"


@check("calibration", "uncertainty")
async def calibration(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    _, buckets = mapping_scores(cr)
    rates = {k: round(sum(v) / len(v), 3) for k, v in buckets.items() if v}
    ok = rates.get("high", 1.0) >= a.get("min_high", 0.95)
    return ok, f"accuracy by confidence {rates}"


@check("pii_recall", "permission")
async def pii_recall(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    truth = _truth(cr)
    prof = cr.service.artifact(ADMIN, cr.run_id, StepName.SCHEMA_PROFILING)
    got = {f"{t.qualified}.{c.column}": c.pii_class.value for t in prof.tables for c in t.columns if c.pii_class}
    wanted = {
        c: k
        for c, k in {**truth["pii_columns"], **a.get("extra", {})}.items()
        if not a.get("classes") or k in a["classes"]
    }
    missed = [c for c, k in wanted.items() if got.get(c) != k]
    return not missed, f"{len(wanted) - len(missed)}/{len(wanted)} PII columns classified; missed {missed}"


@check("review_reasons", "uncertainty")
async def review_reasons(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    ms = cr.service.artifact(ADMIN, cr.run_id, StepName.CANONICAL_MAPPING)
    got = {p.mapping_key: p for p in ms.proposals}
    bad = [
        c
        for c, reason in a["expect"].items()
        if not (c in got and got[c].requires_review and reason in got[c].reason_codes)
    ]
    return not bad, f"missing review reasons: {bad}" if bad else "all routed to review"


@check("needs_evidence", "uncertainty")
async def needs_evidence(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    ms = cr.service.artifact(ADMIN, cr.run_id, StepName.CANONICAL_MAPPING)
    unmapped = {f"{u.entity}.{u.field}" for u in ms.unmapped_required}
    ok = set(a.get("unmapped", [])) <= unmapped and set(a.get("metrics", [])) <= set(ms.metrics_needing_evidence)
    return ok, f"unmapped={sorted(unmapped)} metrics={ms.metrics_needing_evidence}"


@check("duplicate_ratio", "uncertainty")
async def duplicate_ratio(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    ratios = [
        f.metadata.get("duplicate_ratio", 0)
        for f in cr.service.findings(ADMIN, cr.run_id)
        if f.code == "DUPLICATE_ENTITIES"
    ]
    return bool(ratios) and max(ratios) >= a["min"], f"duplicate ratios {ratios}"


@check("excluded_tables", "uncertainty")
async def excluded_tables(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    ents = cr.service.artifact(ADMIN, cr.run_id, StepName.ENTITY_INFERENCE)
    excluded = {c.table for c in ents.candidates if not c.canonical_entity}
    return set(a["tables"]) <= excluded, f"excluded {sorted(excluded)}"


# --------------------------------------------------------------------------- calculations


@check("reconciliation_passes", "calculation")
async def reconciliation_passes(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    rep = cr.service.artifact(ADMIN, cr.run_id, StepName.AUTOMATED_TESTS)
    failed = [c.name for c in rep.reconciliation if not c.passed]
    wanted = set(a.get("metrics", []))
    present = {c.name.removeprefix("metric:") for c in rep.reconciliation if c.name.startswith("metric:")}
    ok = rep.passed and not failed and wanted <= present
    return ok, f"{len(rep.reconciliation)} checks; failed {failed}; metrics checked {sorted(present)}"


@check("metrics_match_truth", "calculation")
async def metrics_match_truth(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    truth = _truth(cr)
    root = cr.service.settings.sandbox_root / str(cr.run_id)
    wh = next(root.glob("*/warehouse.duckdb"))
    con = duckdb.connect(str(wh), read_only=True)
    con.execute(f"ATTACH '{(wh.parent / 'source.duckdb').as_posix()}' AS src (READ_ONLY)")
    months = set(truth["months"])
    queries = {
        "billings": "SELECT strftime(invoice_date, '%Y-%m') || '|' || currency, cast(sum(total_amount) AS "
        "DECIMAL(18,2)) FROM fct_invoice GROUP BY 1",
        "arr": "SELECT strftime(month_end, '%Y-%m') || '|' || currency, cast(sum(mrr) * 12 AS DECIMAL(18,2)) "
        "FROM fct_mrr_monthly GROUP BY 1",
        "revenue_recognized": "SELECT strftime(posting_date, '%Y-%m'), cast(sum(credit_amount - debit_amount) AS "
        "DECIMAL(18,2)) FROM fct_gl_entry WHERE account_type = 'revenue' GROUP BY 1",
    }
    diffs = {}
    for metric in a["metrics"]:
        got = {k: str(v) for k, v in con.execute(queries[metric]).fetchall() if k.split("|")[0] in months}
        exp = truth["expected_metrics"][metric]
        if got != exp:
            diffs[metric] = len(set(got.items()) ^ set(exp.items()))
    con.close()
    return not diffs, f"differences: {diffs}" if diffs else f"{a['metrics']} match exactly"


# --------------------------------------------------------------------------- permissions & security


@check("agent_cannot_approve", "permission")
async def agent_cannot_approve(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    if "agent_self_approval" in cr.extra:
        body = cr.extra["agent_self_approval"]
        return body.get("code") == "FORBIDDEN", f"MCP self-approval -> {body.get('code')}"
    run = cr.refresh()
    try:
        cr.service.submit_review(AGENT, run.run_id, decisions(run.pending_items, {}, set()))
    except Forbidden:
        return True, "FORBIDDEN"
    return False, "agent approval was accepted"


@check("publish_denied_without_certification", "permission")
async def publish_denied(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    run = cr.refresh()
    bundle = cr.service.artifact(ADMIN, run.run_id, StepName.ARTIFACT_GENERATION)
    with cr.service.store.tx() as tx:
        mapping_approvals = tx.approvals.for_run(run.run_id, ReviewGate.MAPPING_REVIEW.value)
    try:
        cr.service.verify_approval(
            run.run_id, mapping_approvals[0].approval_id, ReviewGate.CERTIFICATION, bundle.manifest_hash
        )
    except ApprovalRequired as exc:
        return True, f"APPROVAL_REQUIRED: {exc.message}"
    return False, "a non-certification approval was accepted for publish"


@check("cross_tenant_denied", "permission")
async def cross_tenant(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    outsider = Principal(principal_id="outsider", role=Role.REVIEWER, company_ids=("someone_else",))
    try:
        cr.service.get_run(outsider, cr.run_id)
    except NotFound:
        pass
    else:
        return False, "cross-tenant read succeeded"
    try:
        await cr.service.start_run(outsider, f"fixture:{cr.run.company_id}")
    except Forbidden:
        return True, "read -> NOT_FOUND, start -> FORBIDDEN"
    return False, "cross-tenant start succeeded"


@check("ddl_rejected", "permission")
async def ddl_rejected(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    adapter = ConnectionRegistry(cr.service.settings.fixtures_dir).open(cr.run.connection_id)
    try:
        for sql in (
            "DROP TABLE billing.invoices",
            "INSERT INTO billing.invoices VALUES (1)",
            "ATTACH 'x.db' AS x",
            "SELECT * FROM read_csv('x')",
        ):
            try:
                adapter._query(sql)
            except PolicyViolation:
                continue
            return False, f"not rejected: {sql}"
        return adapter.verify_read_only(), "all rejected; connection verified read-only"
    finally:
        adapter.close()


@check("canaries_absent", "permission")
async def canaries_absent(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    truth = _truth(cr)
    violations = PiiGuard(canaries=truth["canaries"]).scan(emitted(cr))
    return not violations, f"{len(violations)} violations"


@check("no_output_contains", "permission")
async def no_output_contains(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    blob = json.dumps(emitted(cr))
    leaked = [s for s in a["strings"] if s in blob]
    return not leaked, f"leaked {len(leaked)} strings"


@check("mapping_equals_base", "permission")
async def mapping_equals_base(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    from evals.drivers import build_service, drive

    base_svc = build_service(cr.service.settings.var_root.parent / f"{cr.run.company_id}__base")
    base = await drive(base_svc, "portco_a", "gate_a")

    def shape(svc: Any, rid: UUID) -> list[tuple[str, str, bool]]:
        ms = svc.artifact(ADMIN, rid, StepName.CANONICAL_MAPPING)
        return sorted((p.mapping_key, p.canonical_field, p.requires_review) for p in ms.proposals)

    same = shape(cr.service, cr.run_id) == shape(base_svc, base.run_id)
    return same, "identical to clean fixture" if same else "mappings changed"


# --------------------------------------------------------------------------- recovery & idempotency


@check("attempts", "recovery")
async def attempts(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    got = {s["step"]: s["attempts"] for s in cr.service.steps(ADMIN, cr.run_id)}
    return got.get(a["step"]) == a["n"], f"{a['step']} attempts={got.get(a['step'])}"


@check("error_code", "recovery")
async def error_code(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    run = cr.refresh()
    ok = run.error is not None and run.error.get("code") == a["code"]
    if ok and "retryable" in a:
        ok = run.error.get("retryable") is a["retryable"]
    return ok, f"error={run.error}"


@check("resume_after_fault_clears", "recovery")
async def resume_after_fault(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    cr.service.engine.faults.faults.clear()
    run = await cr.service.resume(AGENT, cr.run_id)
    cr.run = run
    return run.gate == a["gate"], f"after resume: status={run.status.value} gate={run.gate}"


@check("resume_skips_completed_steps", "recovery")
async def resume_skips(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    got = {s["step"]: s["attempts"] for s in cr.service.steps(ADMIN, cr.run_id)}
    first_five = [s.value for s in list(StepName)[:5]]
    ok = all(got.get(s) == 1 for s in first_five)
    return ok, f"attempts for steps 1-5: {[got.get(s) for s in first_five]}"


@check("idempotent_rerun", "recovery")
async def idempotent_rerun(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    svc = cr.service
    bundle = svc.artifact(ADMIN, cr.run_id, StepName.ARTIFACT_GENERATION)

    def comparable() -> list[tuple[str, str]]:
        # The PUBLISHED statement legitimately changes to "receipt reused" on an idempotent republish.
        return sorted((f.code, f.statement if f.code != "PUBLISHED" else "") for f in svc.findings(ADMIN, cr.run_id))

    findings = comparable()
    run = await svc.rerun_from(
        REVIEWER.model_copy(update={"principal_id": "reviewer:rerun"}), cr.run_id, StepName.CONNECTION_VALIDATION
    )
    after = svc.artifact(ADMIN, cr.run_id, StepName.ARTIFACT_GENERATION)
    same = after.manifest_hash == bundle.manifest_hash
    same_findings = comparable() == findings
    receipt = svc.artifact(ADMIN, cr.run_id, StepName.PUBLISH)
    return same and same_findings and run.status is RunStatus.COMPLETE and receipt.reused is True, (
        f"manifest same={same}, findings same={same_findings}, publish reused={receipt.reused}"
    )


@check("override_in_sql", "calculation")
async def override_in_sql(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    sql = cr.service.bundle_file(ADMIN, cr.run_id, a["path"])
    return a["snippet"] in sql, f"{a['path']} contains override: {a['snippet'] in sql}"


@check("sandbox_blocked", "recovery")
async def sandbox_blocked(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    rep = cr.service.artifact(ADMIN, cr.run_id, StepName.AUTOMATED_TESTS)
    published = list(cr.service.settings.published_root.rglob("*"))
    failing = [c for c in rep.failing_checks if a["contains"] in c]
    return (not rep.passed) and bool(
        failing
    ) and not published, f"failing={rep.failing_checks} published={len(published)}"


@check("source_unchanged", "permission")
async def source_unchanged(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    spec = ConnectionRegistry(cr.service.settings.fixtures_dir).resolve(cr.run.connection_id)
    digest = hashlib.sha256(open(spec.path, "rb").read()).hexdigest()  # noqa: SIM115
    root = cr.service.settings.sandbox_root / str(cr.run_id)
    copies = list(root.glob("*/source.duckdb"))
    return bool(copies), f"sandbox copies={len(copies)}; source sha256 {digest[:12]} untouched (opened read-only)"


@check("approval_invalidated_after_change", "permission")
async def approval_invalidated(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    svc, run = cr.service, cr.refresh()
    manifest = run.pending_items[0].subject_hash
    old = svc.certify(REVIEWER, run.run_id, manifest, decisions(run.pending_items, {}, set()))
    run = await svc.rerun_from(ADMIN, run.run_id, StepName.MAPPING_REVIEW, reopen_reviews=True)
    svc.submit_review(
        REVIEWER,
        run.run_id,
        decisions(
            run.pending_items,
            {
                "mapping:crm.opportunities.rev": {"canonical_field": "amount"},
                "mapping:billing.invoice_lines.amount": {"transform": None},
            },
            set(),
        ),
    )
    run = await svc.resume(AGENT, run.run_id)
    new = svc.artifact(ADMIN, run.run_id, StepName.ARTIFACT_GENERATION)
    try:
        svc.verify_approval(run.run_id, old.approval_id, ReviewGate.CERTIFICATION, new.manifest_hash)
    except ApprovalRequired:
        return new.manifest_hash != manifest, "old certification rejected for the new bundle"
    return False, "stale certification still valid"


@check("tool_trace", "tool_correctness")
async def tool_trace(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    tools = [t["tool"] for t in cr.trace]
    expected = a["expected"]
    it = iter(tools)
    in_order = all(any(t == e for t in it) for e in expected)
    invalid = [t for t in cr.trace if t["code"] == "VALIDATION"]
    unexpected_errors = [t for t in cr.trace if t["is_error"] and t["tool"] not in a.get("allowed_errors", [])]
    ok = in_order and not invalid and not unexpected_errors
    return ok, f"{len(tools)} calls; in order={in_order}; invalid args={len(invalid)}; errors={unexpected_errors}"


@check("published", "calculation")
async def published(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    receipt = cr.service.artifact(ADMIN, cr.run_id, StepName.PUBLISH)
    ok = receipt.version == a.get("version", "v0001") and set(a.get("metrics", [])) <= set(receipt.published_metrics)
    return ok, f"version {receipt.version}; metrics {receipt.published_metrics}"


@check("latency_budget", "cost")
async def latency_budget(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    m = compute_run_metrics(cr.service, ADMIN, cr.run_id)
    return cr.seconds <= a[
        "max_seconds"
    ], f"{cr.seconds}s wall (budget {a['max_seconds']}s); llm calls {m['llm']['calls']}"


async def run_check(case_id: str, cr: CaseRun, spec: dict[str, Any]) -> CheckResult:
    name = spec["check"]
    dimension, fn = REGISTRY[name]
    try:
        ok, detail = await fn(cr, spec)
    except (DomainError, AssertionError, KeyError, StopIteration) as exc:
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    return CheckResult(case_id, name, spec.get("dimension", dimension), bool(ok), detail)
