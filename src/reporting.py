"""Deterministic run report / certification packet renderer (POD-902). No model involved."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from src.domain.errors import NotFound
from src.domain.models import FindingType, Principal, StepName
from src.domain.project_models import (
    ArtifactBundle,
    CertificationPacket,
    MappingSet,
    PublishReceipt,
    ResolvedMapping,
    TestReport,
)
from src.run_metrics import compute_run_metrics


def _maybe(svc: Any, principal: Principal, run_id: UUID, step: StepName) -> Any:
    try:
        return svc.artifact(principal, run_id, step)
    except NotFound:
        return None


def _esc(text: str) -> str:
    return text.replace("|", "\\|")


def render_run_report(svc: Any, principal: Principal, run_id: UUID) -> str:
    run = svc.get_run(principal, run_id)
    findings = svc.findings(principal, run_id)
    ms: MappingSet | None = _maybe(svc, principal, run_id, StepName.CANONICAL_MAPPING)
    resolved: ResolvedMapping | None = _maybe(svc, principal, run_id, StepName.MAPPING_REVIEW)
    bundle: ArtifactBundle | None = _maybe(svc, principal, run_id, StepName.ARTIFACT_GENERATION)
    report: TestReport | None = _maybe(svc, principal, run_id, StepName.AUTOMATED_TESTS)
    packet: CertificationPacket | None = _maybe(svc, principal, run_id, StepName.HUMAN_CERTIFICATION)
    receipt: PublishReceipt | None = _maybe(svc, principal, run_id, StepName.PUBLISH)
    metrics = compute_run_metrics(svc, principal, run_id)
    events, chain_ok = svc.audit(principal, run_id)

    out = [
        f"# Onboarding run report: {run.company_id}",
        "",
        f"- Run: `{run.run_id}`",
        f"- Connection: `{run.connection_id}`",
        f"- Status: **{run.status.value}**" + (f" (gate: {run.gate})" if run.gate else ""),
        f"- Audit chain: {'intact' if chain_ok else 'BROKEN'} ({len(events)} events)",
        f"- Human changes to recommendations: {metrics['human_changed_recommendation']}",
        "",
    ]

    out += ["## Timeline", "", "| step | status | attempts | seconds |", "|---|---|---|---|"]
    for s in svc.steps(principal, run_id):
        m = metrics["steps"].get(s["step"], {})
        out.append(f"| {s['step']} | {s['status']} | {s['attempts']} | {m.get('seconds', 0)} |")
    out.append("")

    for ftype in FindingType:
        group = [f for f in findings if f.finding_type is ftype]
        if not group:
            continue
        out += [
            f"## {ftype.value.title()}s",
            "",
            "| code | confidence | status | statement | evidence |",
            "|---|---|---|---|---|",
        ]
        for f in group:
            ev = ", ".join(f"`{e.source_id[:8]}`" for e in f.evidence[:3]) or "_needs evidence_"
            out.append(f"| {f.code} | {f.confidence.value} | {f.status.value} | {_esc(f.statement)} | {ev} |")
        out.append("")

    if ms is not None:
        out += [
            "## Mapping proposals",
            "",
            "| source | canonical | confidence | score | review reasons | decision |",
            "|---|---|---|---|---|---|",
        ]
        accepted = {(a.source_table, a.source_column): a for a in (resolved.accepted if resolved else [])}
        for p in ms.proposals:
            a = accepted.get((p.source_table, p.source_column))
            decision = (
                "rejected"
                if resolved and f"mapping:{p.mapping_key}" in resolved.rejected_keys
                else ("override -> " + a.canonical_field if a and a.overridden else (a.decided_by if a else "pending"))
            )
            out.append(
                f"| {p.source_field} | {p.canonical_entity}.{p.canonical_field} | {p.confidence.value} | "
                f"{p.score:.2f} | {', '.join(p.reason_codes) or '-'} | {decision} |"
            )
        out.append("")
        out += ["## Join graph", "", "```mermaid", "flowchart LR"]
        for j in ms.joins:
            left, right = j.left_table.replace(".", "_"), j.right_table.replace(".", "_")
            label = f"{j.left_columns[0]} {j.cardinality} {j.containment_ratio:.0%}"
            out.append(f"  {left}[{j.left_table}] -->|{label}| {right}[{j.right_table}]")
        out += ["```", ""]

    if bundle is not None:
        out += [
            "## Generated artifacts",
            "",
            f"- Manifest: `{bundle.manifest_hash}`",
            f"- Models ({len(bundle.models)}): {', '.join(bundle.models)}",
            f"- Metrics generated: {', '.join(bundle.generated_metrics) or 'none'}",
            "",
        ]
        if bundle.not_generated:
            out += ["| metric | why not generated |", "|---|---|"]
            out += [f"| {m} | {_esc(why)} |" for m, why in sorted(bundle.not_generated.items())]
            out.append("")

    if report is not None:
        out += [
            "## Sandbox tests",
            "",
            f"- dbt exit code {report.dbt_exit_code}; "
            f"{sum(1 for r in report.dbt_results if r.resource_type == 'test')} data tests; "
            f"passed: **{report.passed}**" + (" (cached)" if report.cached else ""),
            "",
            "| reconciliation check | result | detail |",
            "|---|---|---|",
        ]
        out += [f"| {c.name} | {'pass' if c.passed else 'FAIL'} | {_esc(c.detail)} |" for c in report.reconciliation]
        if report.failing_checks:
            out += ["", "Failing checks: " + ", ".join(f"`{c}`" for c in report.failing_checks)]
        if report.waived_checks:
            out += ["", "Waived by reviewer: " + ", ".join(f"`{c}`" for c in report.waived_checks)]
        out.append("")

    if packet is not None:
        out += ["## Certification", "", "| metric | status | formula |", "|---|---|---|"]
        out += [f"| {m.metric} | {m.status} | {_esc(m.formula)} |" for m in packet.metrics]
        out.append("")
    if receipt is not None:
        out += [
            "## Publication",
            "",
            f"- Version **{receipt.version}** at `{receipt.path}`",
            f"- Certified by `{receipt.publisher}` (approval `{receipt.certification_id}`)",
            f"- Published metrics: {', '.join(receipt.published_metrics)}",
            f"- Excluded metrics: {', '.join(receipt.excluded_metrics) or 'none'}",
            "",
        ]
    if run.error:
        out += [
            "## Error",
            "",
            f"`{run.error.get('code')}` at `{run.error.get('step')}`: {run.error.get('message')}",
            "",
        ]
    return "\n".join(out)
