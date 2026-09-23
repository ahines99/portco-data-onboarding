"""Per-run metrics and cost accounting (POD-805)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from src.domain.errors import NotFound
from src.domain.models import Principal, StepName
from src.domain.project_models import MappingSet, ResolvedMapping


def compute_run_metrics(svc: Any, principal: Principal, run_id: UUID) -> dict[str, Any]:
    run = svc.get_run(principal, run_id)
    with svc.store.tx() as tx:
        step_runs = tx.steps.list(run_id)
        events = tx.audit.list(run_id)
        approvals = tx.approvals.for_run(run_id)
    steps: dict[str, dict[str, Any]] = {}
    for sr in step_runs:
        s = steps.setdefault(sr.step, {"attempts": 0, "seconds": 0.0, "failures": 0})
        s["attempts"] += 1
        if sr.finished_at:
            s["seconds"] = round(s["seconds"] + (sr.finished_at - sr.started_at).total_seconds(), 3)
        if sr.status == "failed":
            s["failures"] += 1
    reused = sum(1 for e in events if e.event_type == "step_reused")
    retries = sum(1 for e in events if e.event_type == "step_retried")
    evidence_read = sorted({ref.source_id for f in svc.findings(principal, run_id) for ref in f.evidence})

    llm = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model": None}
    overrides = rejections = 0
    try:
        ms = svc.artifact(principal, run_id, StepName.CANONICAL_MAPPING)
        assert isinstance(ms, MappingSet)
        for p in ms.proposals:
            if p.judge and p.judge.get("usage"):
                u = p.judge["usage"]
                llm["calls"] += 1
                llm["input_tokens"] += int(u.get("input_tokens", 0))
                llm["output_tokens"] += int(u.get("output_tokens", 0))
                llm["cost_usd"] = round(llm["cost_usd"] + float(u.get("cost_usd", 0.0)), 6)
                llm["model"] = p.judge.get("model")
    except NotFound:
        pass
    try:
        resolved = svc.artifact(principal, run_id, StepName.MAPPING_REVIEW)
        assert isinstance(resolved, ResolvedMapping)
        overrides = sum(1 for a in resolved.accepted if a.overridden)
        rejections = len(resolved.rejected_keys)
    except NotFound:
        pass
    wall = (run.updated_at - run.created_at).total_seconds()
    return {
        "run_id": str(run_id),
        "status": run.status.value,
        "wall_seconds": round(wall, 2),
        "steps": steps,
        "reused_steps": reused,
        "retries": retries,
        "evidence_ids_read": len(evidence_read),
        "approvals": len(approvals),
        "approval_events": sum(1 for e in events if e.event_type in {"approval_recorded", "approval_invalidated"}),
        "policy_denials": sum(1 for e in events if e.event_type == "policy_denied"),
        "human_changed_recommendation": overrides + rejections,
        "overrides": overrides,
        "rejections": rejections,
        "llm": llm,
        "outcome": run.status.value,
    }
