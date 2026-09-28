"""Check registry for golden cases. Each check returns (passed, detail) and belongs to one dimension."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb

from evals.drivers import ADMIN, AGENT, REVIEWER, CaseRun, decisions
from src.adapters.external import ConnectionRegistry
from src.domain.errors import DomainError, Forbidden, NotFound, PolicyViolation
from src.domain.hashing import content_hash
from src.domain.models import FindingStatus, Principal, ReviewGate, Role, RunStatus, StepName
from src.domain.pii_guard import PiiGuard
from src.fixtures.generate import load_ground_truth
from src.reporting import render_run_report
from src.run_metrics import compute_run_metrics
from src.services.sandbox import sandbox_run_dir
from src.services.semantic import execute_metrics
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
    supported = 0
    checked_claims = 0
    for f in findings:
        if f.status is FindingStatus.NEEDS_EVIDENCE:
            continue
        supported += 1
        if not f.evidence:
            bad.append(f.code)
            continue
        for ref in f.evidence:
            try:
                ev = cr.service.evidence(ADMIN, UUID(ref.source_id))
                if content_hash(ev.payload) != ev.content_hash or (
                    ref.excerpt_hash is not None and ref.excerpt_hash != ev.content_hash
                ):
                    bad.append(f.code)
                if ev.source_type == "table_profile" and f.code in {
                    "EMPTY_TABLE",
                    "TEST_RECORDS",
                    "SOFT_DELETE_FLAG",
                    "MULTI_CURRENCY",
                    "DUPLICATE_ENTITIES",
                }:
                    checked_claims += 1
                    payload = ev.payload
                    columns = {c["column"]: c for c in payload.get("columns", [])}
                    column = columns.get(f.metadata.get("column"), {})
                    patterns = column.get("pattern_counts", {})
                    table = f"{payload.get('schema_name')}.{payload.get('table_name')}"
                    support = table == f.metadata.get("table")
                    if f.code == "EMPTY_TABLE":
                        support &= payload.get("row_count") == 0
                    elif f.code == "TEST_RECORDS":
                        support &= bool(patterns.get("test_prefix")) and patterns.get("test_prefix") == f.metadata.get(
                            "rows"
                        )
                    elif f.code == "SOFT_DELETE_FLAG":
                        support &= bool(patterns.get("true_count")) and patterns.get("true_count") == f.metadata.get(
                            "rows"
                        )
                    elif f.code == "MULTI_CURRENCY":
                        support &= len(column.get("category_values", [])) > 1
                    elif f.code == "DUPLICATE_ENTITIES":
                        nn = column.get("non_null_count", 0)
                        nd = patterns.get("normalized_distinct", nn)
                        support &= bool(nn) and round((nn - nd) / nn, 4) == f.metadata.get("duplicate_ratio")
                    if not support:
                        bad.append(f.code)
            except (NotFound, ValueError):
                bad.append(f.code)
    enough = len(findings) >= a.get("min_findings", 1) and supported >= a.get("min_supported", 1)
    enough &= checked_claims >= a.get("min_claim_assertions", 1)
    return enough and not bad, (
        f"{len(findings)} findings; {supported} supported; {checked_claims} profile claims checked; "
        f"invalid evidence: {sorted(set(bad))}; minimum outputs met={enough}"
    )


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
    """Labeled-column top-1 accuracy, not whole-output precision. Explicit null labels count as wrong
    when proposed; unlabeled proposals are reported separately by mapping_coverage."""
    truth = _truth(cr)
    ms = cr.service.artifact(ADMIN, cr.run_id, StepName.CANONICAL_MAPPING)
    got = {p.mapping_key: p for p in ms.proposals}
    correct = 0
    buckets: dict[str, list[bool]] = defaultdict(list)
    for col, exp in truth["mappings"].items():
        p = got.get(col)
        ok = (p is None and exp is None) or (p is not None and f"{p.canonical_entity}.{p.canonical_field}" == exp)
        correct += ok
        if p is not None:
            buckets[p.confidence.value].append(f"{p.canonical_entity}.{p.canonical_field}" == exp)
    return correct / len(truth["mappings"]) if truth["mappings"] else 0.0, buckets


def mapping_coverage(cr: CaseRun) -> dict[str, Any]:
    truth = _truth(cr)["mappings"]
    proposals = cr.service.artifact(ADMIN, cr.run_id, StepName.CANONICAL_MAPPING).proposals
    unknown = sorted(p.mapping_key for p in proposals if p.mapping_key not in truth)
    return {
        "labeled_columns": len(truth),
        "proposals": len(proposals),
        "labeled_proposal_fraction": (len(proposals) - len(unknown)) / len(proposals) if proposals else 0.0,
        "unlabeled_proposals": unknown,
    }


@check("mapping_accuracy", "uncertainty")
async def mapping_accuracy(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    acc, _buckets = mapping_scores(cr)
    truth = _truth(cr)
    ms = cr.service.artifact(ADMIN, cr.run_id, StepName.CANONICAL_MAPPING)
    extras = [p.mapping_key for p in ms.proposals if truth["mappings"].get(p.mapping_key, "x") is None]
    flagged = all(p.requires_review for p in ms.proposals if p.mapping_key in extras)
    return acc >= a["min"] and flagged, (
        f"labeled-column top-1 accuracy {acc:.3f}; proposals for columns expected unmapped: {extras} "
        f"(all routed to review: {flagged}); truth coverage {mapping_coverage(cr)}"
    )


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
    root = sandbox_run_dir(cr.service.settings.sandbox_root, cr.run_id)
    wh = next(root.glob("*/warehouse.duckdb"))
    con = duckdb.connect(str(wh), read_only=True)
    con.execute(f"ATTACH '{(wh.parent / 'source.duckdb').as_posix()}' AS src (READ_ONLY)")
    months = set(truth["months"])
    bundle = cr.service.artifact(ADMIN, cr.run_id, StepName.ARTIFACT_GENERATION)
    files = {f.path: cr.service.store.blobs.get_bytes(f.sha256).decode() for f in bundle.files}
    try:
        values = execute_metrics(con, files, bundle.generated_metrics)
    finally:
        con.close()
    diffs = {}
    for metric in a["metrics"]:
        got = {
            k: str(Decimal(str(v)).quantize(Decimal("0.01")))
            for k, v in values[metric].items()
            if k.split("|")[0] in months
        }
        exp = truth["expected_metrics"][metric]
        if got != exp:
            diffs[metric] = len(set(got.items()) ^ set(exp.items()))
    return not diffs, f"differences: {diffs}" if diffs else f"{a['metrics']} match exactly"


# --------------------------------------------------------------------------- permissions & security


@check("agent_cannot_approve", "permission")
async def agent_cannot_approve(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    if "agent_self_approval" in cr.extra:
        body = cr.extra["agent_self_approval"]
        return body.get("code") == "FORBIDDEN", f"MCP self-approval -> {body.get('code')}"
    run = cr.refresh()
    try:
        cr.service.submit_review(
            AGENT,
            run.run_id,
            decisions(run.pending_items, {}, set()),
            subject_hash=run.pending_items[0].subject_hash,
            gate=ReviewGate(run.gate),
        )
    except Forbidden:
        return True, "FORBIDDEN"
    return False, "agent approval was accepted"


async def _mcp(cr: CaseRun, principal: Principal, tool: str, **args: Any) -> tuple[bool, dict[str, Any]]:
    from mcp import Client

    from src.mcp_server import build_server

    server = build_server(cr.service.settings, service=cr.service, principal=lambda: principal, with_auth=False)
    async with Client(server) as c:
        r = await c.call_tool(tool, args)
    return bool(r.is_error), (r.structured_content or {})


@check("publish_denied_without_certification", "permission")
async def publish_denied(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    """Actually attempt the publish (with a mapping approval id), then check it failed closed and was audited."""
    run = cr.refresh()
    with cr.service.store.tx() as tx:
        mapping_approvals = tx.approvals.for_run(run.run_id, ReviewGate.MAPPING_REVIEW.value)
    err, body = await _mcp(
        cr, AGENT, "publish_run", run_id=str(run.run_id), certification_id=str(mapping_approvals[0].approval_id)
    )
    events, _ = cr.service.audit(ADMIN, run.run_id)
    denied = any(e.event_type == "policy_denied" and e.payload.get("action") == "publish" for e in events)
    published = list(cr.service.settings.published_root.rglob("*"))
    still_waiting = cr.refresh().status is RunStatus.NEEDS_REVIEW
    ok = err and body.get("code") == "APPROVAL_REQUIRED" and denied and not published and still_waiting
    return ok, f"publish -> {body.get('code')}; policy_denied audited={denied}; files={len(published)}"


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
    after = hashlib.sha256(Path(spec.path).read_bytes()).hexdigest()
    before = cr.extra.get("source_sha256_before")
    copies = list(sandbox_run_dir(cr.service.settings.sandbox_root, cr.run_id).glob("*/source.duckdb"))
    ok = before is not None and before == after and bool(copies)
    return ok, f"source sha256 before={str(before)[:12]} after={after[:12]}; sandbox copies={len(copies)}"


@check("approval_invalidated_after_change", "permission")
async def approval_invalidated(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    svc, run = cr.service, cr.refresh()
    old = svc.certify(REVIEWER, run.run_id, run.pending_items[0].subject_hash, decisions(run.pending_items, {}, set()))
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
        subject_hash=run.pending_items[0].subject_hash,
        gate=ReviewGate(run.gate),
    )
    run = await svc.resume(AGENT, run.run_id)
    err, body = await _mcp(cr, AGENT, "publish_run", run_id=str(run.run_id), certification_id=str(old.approval_id))
    with svc.store.tx() as tx:
        revoked = tx.approvals.get(old.approval_id).revoked_at is not None
    ok = (
        err and body.get("code") == "APPROVAL_REQUIRED" and revoked and not list(svc.settings.published_root.rglob("*"))
    )
    return ok, f"publish with the pre-change certification -> {body.get('code')}; old certification revoked={revoked}"


@check("relationship_warn", "calculation")
async def relationship_warn(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    rep = cr.service.artifact(ADMIN, cr.run_id, StepName.AUTOMATED_TESTS)
    hits = [r for r in rep.dbt_results if "relationships" in r.unique_id and a["contains"] in r.unique_id]
    ok = bool(hits) and all(r.status == "warn" for r in hits) and rep.passed
    return ok, f"relationship tests {[(r.unique_id.split('.')[-2], r.status) for r in hits]}; run passed={rep.passed}"


@check("pii_not_staged", "permission")
async def pii_not_staged(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    bundle = cr.service.artifact(ADMIN, cr.run_id, StepName.ARTIFACT_GENERATION)
    files = {f.path: cr.service.store.blobs.get_bytes(f.sha256).decode() for f in bundle.files}
    column = a["column"].rsplit(".", 1)[1]
    leaks = [path for path, text in files.items() if f'"{column}"' in text or f" {column}," in text]
    return not leaks, f"generated files referencing {a['column']}: {leaks}"


@check("mcp_error_contract", "tool_correctness")
async def mcp_error_contract(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    rid = str(cr.run_id)
    subject = cr.refresh().pending_items[0].subject_hash
    expectations = [
        (AGENT, "get_run_status", {"run_id": "not-a-uuid"}, "VALIDATION"),
        (AGENT, "get_run_status", {"run_id": "00000000-0000-0000-0000-000000000000"}, "NOT_FOUND"),
        (AGENT, "certify_run", {"run_id": rid, "subject_hash": subject}, "FORBIDDEN"),
        (
            AGENT,
            "generate_dbt_artifacts",
            {"run_id": rid, "approval_id": "00000000-0000-0000-0000-000000000000"},
            "APPROVAL_REQUIRED",
        ),
        (
            REVIEWER,
            "certify_run",
            {"run_id": rid, "subject_hash": subject, "metric_decisions": {"ARR": "reject"}},
            "VALIDATION",
        ),
    ]
    got = []
    for principal, tool, args, want in expectations:
        err, body = await _mcp(cr, principal, tool, **args)
        got.append((tool, want, body.get("code") if err else "ok"))
    bad = [g for g in got if g[1] != g[2]]
    return not bad, f"{len(got) - len(bad)}/{len(got)} error codes as specified; mismatches {bad}"


@check("recertification_republishes", "permission")
async def recertification_republishes(cr: CaseRun, a: dict[str, Any]) -> tuple[bool, str]:
    """Audit H1: rejecting a metric on re-certification must publish a new version without it."""
    svc = cr.service
    first = svc.artifact(ADMIN, cr.run_id, StepName.PUBLISH)
    run = await svc.rerun_from(ADMIN, cr.run_id, StepName.HUMAN_CERTIFICATION, reopen_reviews=True)
    svc.certify(
        REVIEWER,
        run.run_id,
        run.pending_items[0].subject_hash,
        decisions(run.pending_items, {}, {f"metric:{a['metric']}"}),
    )
    run = await svc.resume(AGENT, run.run_id)
    second = svc.artifact(ADMIN, cr.run_id, StepName.PUBLISH)
    ok = (
        run.status is RunStatus.COMPLETE
        and second.version != first.version
        and a["metric"] in second.excluded_metrics
        and a["metric"] not in second.published_metrics
        and second.certification_id != first.certification_id
    )
    return ok, f"{first.version} -> {second.version}; excluded now {second.excluded_metrics}"


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
    bundle = cr.service.artifact(ADMIN, cr.run_id, StepName.ARTIFACT_GENERATION)
    root = Path(receipt.path).resolve()
    bad = []
    expected = {"certification.json"}
    for file in bundle.files:
        if file.path.startswith("models/semantic/metrics/") and Path(file.path).stem in receipt.excluded_metrics:
            continue
        expected.add(file.path)
        path = (root / file.path).resolve()
        if (
            not path.is_relative_to(root)
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != file.sha256
        ):
            bad.append(file.path)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    bad.extend(sorted(expected ^ actual))
    try:
        certificate = json.loads((root / "certification.json").read_text(encoding="utf-8"))
        for name in ("version", "manifest_hash", "certification_id", "published_metrics", "excluded_metrics"):
            if certificate["receipt"][name] != receipt.model_dump(mode="json")[name]:
                bad.append(f"certification.json:{name}")
    except (OSError, ValueError, KeyError):
        bad.append("certification.json")
    ok = receipt.version == a.get("version", "v0001") and set(a.get("metrics", [])) <= set(receipt.published_metrics)
    return ok and not bad, f"version {receipt.version}; metrics {receipt.published_metrics}; invalid files={bad}"


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
