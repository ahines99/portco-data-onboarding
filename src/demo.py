"""One-command demo (POD-901): `uv run poe demo` / `portco demo`.

1. Success path: fixture A is onboarded; a scripted human reviewer decides the mapping gate
   (including one override); the sandbox build reconciles exactly; the reviewer certifies; the
   bundle is published.
2. Controlled failure path: fixture A with malformed invoice lines, plus an injected source timeout.
   The timeout is retried, the malformed rows fail sandbox tests, and the run stops for review
   with nothing published.

No Docker, no API keys. Reports are written to var/demo/.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import anyio
import yaml

from src.adapters.faults import FaultInjector
from src.domain.models import Principal, ReviewDecision, Role, RunStatus, StepName
from src.domain.project_models import ItemDecision, PublishReceipt, TestReport
from src.fixtures.generate import ensure_fixture
from src.fsutil import remove_tree
from src.reporting import render_run_report
from src.settings import PROJECT_ROOT, Settings, get_settings
from src.workflows.facade import OnboardingService

AGENT = Principal(principal_id="agent:demo", role=Role.AGENT)


def _say(text: str = "") -> None:
    print(text, flush=True)


def _reviewer_decisions(items: list[Any], script: dict[str, Any]) -> list[ItemDecision]:
    out = []
    for item in items:
        override = script.get("overrides", {}).get(item.item_key)
        if override:
            comment = override.get("comment")
            out.append(
                ItemDecision(
                    item_key=item.item_key,
                    decision=ReviewDecision.APPROVE_WITH_OVERRIDE,
                    override={k: v for k, v in override.items() if k != "comment"},
                    comment=comment,
                )
            )
        else:
            out.append(ItemDecision(item_key=item.item_key, decision=ReviewDecision(script.get("default", "approve"))))
    return out


async def _success(root: Path, script: dict[str, Any]) -> tuple[bool, str]:
    reviewer = Principal(principal_id=script.get("reviewer", "alice"), role=Role.REVIEWER)
    svc = OnboardingService.build(
        Settings(var_root=root / "success", fixtures_root=get_settings().fixtures_dir, log_level="WARNING")
    )
    _say("== 1. Success path: fixture A (synthetic B2B SaaS company)")
    run = await svc.start_run(AGENT, "fixture:portco_a")
    codes = sorted({f.code for f in svc.findings(AGENT, run.run_id)})
    _say(
        f"   agent profiled, inferred entities/joins and proposed mappings -> paused at '{run.gate}' "
        f"with {len(run.pending_items)} review items"
    )
    _say(f"   findings: {', '.join(codes)}")
    traps = [i for i in run.pending_items if {"UNIT_MISMATCH", "SEMANTIC_TRAP"} & set(i.reason_codes)]
    for t in traps:
        _say(f"   trap caught -> {t.summary} [{', '.join(t.reason_codes)}]")
    try:
        svc.submit_review(AGENT, run.run_id, _reviewer_decisions(run.pending_items, script))
    except Exception as exc:  # the point: the agent cannot approve its own proposals
        _say(f"   agent tried to approve its own proposals -> {type(exc).__name__}")
    approval = svc.submit_review(reviewer, run.run_id, _reviewer_decisions(run.pending_items, script))
    _say(
        f"   reviewer '{reviewer.principal_id}' recorded approval {str(approval.approval_id)[:8]} "
        f"({len(approval.decisions)} decisions, 1 override)"
    )
    run = await svc.resume(AGENT, run.run_id)
    report = svc.artifact(AGENT, run.run_id, StepName.AUTOMATED_TESTS)
    assert isinstance(report, TestReport)
    _say(
        f"   generated dbt + semantic layer; sandbox build exit {report.dbt_exit_code}; "
        f"{sum(c.passed for c in report.reconciliation)}/{len(report.reconciliation)} reconciliation checks "
        "exact to the cent"
    )
    _say(f"   paused at '{run.gate}' for human certification")
    manifest = run.pending_items[0].subject_hash
    cert = svc.certify(
        reviewer,
        run.run_id,
        manifest,
        [ItemDecision(item_key=i.item_key, decision=ReviewDecision.APPROVE) for i in run.pending_items],
    )
    run = await svc.resume(AGENT, run.run_id)
    receipt = svc.artifact(AGENT, run.run_id, StepName.PUBLISH)
    assert isinstance(receipt, PublishReceipt)
    _say(
        f"   certified ({str(cert.approval_id)[:8]}) and published {receipt.version}: "
        f"{', '.join(receipt.published_metrics)}"
    )
    events, chain_ok = svc.audit(AGENT, run.run_id)
    _say(f"   audit log: {len(events)} events, hash chain {'intact' if chain_ok else 'BROKEN'}")
    out = root / "success_report.md"
    out.write_text(render_run_report(svc, AGENT, run.run_id), encoding="utf-8", newline="\n")
    ok = run.status is RunStatus.COMPLETE and report.passed and chain_ok
    return ok, f"success path: {run.status.value}, report {out.as_posix()}"


async def _failure(root: Path, script: dict[str, Any]) -> tuple[bool, str]:
    reviewer = Principal(principal_id=script.get("reviewer", "alice"), role=Role.REVIEWER)
    settings = Settings(
        var_root=root / "failure",
        fixtures_root=get_settings().fixtures_dir,
        log_level="WARNING",
        step_backoff_base_seconds=0.05,
    )
    svc = OnboardingService.build(settings, faults=FaultInjector.parse("adapter.aggregate:timeout:nth=3"))
    _say()
    _say("== 2. Controlled failure path: malformed invoice lines + an injected source timeout")
    run = await svc.start_run(AGENT, "fixture:portco_a__malformed")
    attempts = {s["step"]: s["attempts"] for s in svc.steps(AGENT, run.run_id)}
    _say(
        f"   injected timeout during profiling -> retried (attempts: {attempts['schema_profiling']}), "
        f"run continued to '{run.gate}'"
    )
    mixed = [f for f in svc.findings(AGENT, run.run_id) if f.code == "MIXED_TYPES"]
    _say(f"   profiling flagged {len(mixed)} mixed-type column(s)")
    svc.submit_review(reviewer, run.run_id, _reviewer_decisions(run.pending_items, script))
    run = await svc.resume(AGENT, run.run_id)
    report = svc.artifact(AGENT, run.run_id, StepName.AUTOMATED_TESTS)
    assert isinstance(report, TestReport)
    failing = [c.split(".")[-2] if c.startswith("test.") else c for c in report.failing_checks]
    _say(f"   sandbox tests failed: {', '.join(failing)}; downstream marts skipped")
    _say(f"   run stopped at '{run.gate}' - nothing is published unless a reviewer waives or the mapping changes")
    published = list((root / "failure" / "published").rglob("*"))
    out = root / "failure_report.md"
    out.write_text(render_run_report(svc, AGENT, run.run_id), encoding="utf-8", newline="\n")
    ok = (
        run.status is RunStatus.NEEDS_REVIEW
        and run.gate == "test_failures"
        and not published
        and attempts["schema_profiling"] == 2
    )
    return ok, f"failure path: stopped at {run.gate}, published files {len(published)}, report {out.as_posix()}"


def run_demo(out: Path) -> int:
    started = time.monotonic()
    root = out.resolve()
    if not remove_tree(root):  # e.g. a file still open from an earlier session: use a fresh directory
        root = root.with_name(f"{root.name}-{int(time.time())}")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("portco_a", "portco_a__malformed"):
        ensure_fixture(name, get_settings().fixtures_dir)
    script = yaml.safe_load((PROJECT_ROOT / "demo" / "reviews_gate_a.yaml").read_text(encoding="utf-8"))
    ok1, msg1 = anyio.run(_success, root, script)
    ok2, msg2 = anyio.run(_failure, root, script)
    _say()
    _say("== Summary")
    _say(f"   [{'ok' if ok1 else 'UNEXPECTED'}] {msg1}")
    _say(f"   [{'ok' if ok2 else 'UNEXPECTED'}] {msg2}")
    _say(f"   finished in {time.monotonic() - started:.0f}s")
    return 0 if ok1 and ok2 else 1
