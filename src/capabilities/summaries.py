"""Builders that turn domain state into compact MCP outputs (no row values, ever)."""

from collections import Counter
from typing import Any

from src.adapters.repositories import RunRecord
from src.capabilities.schemas import (
    ErrorOut,
    ReviewItemOut,
    RunSummary,
    StepStatus,
)
from src.domain.models import Principal
from src.domain.project_models import ReviewItem

NEXT = {
    "mapping_review": (
        "A human reviewer must decide the pending mapping items (submit_mapping_review), then resume_run."
    ),
    "test_failures": "Sandbox checks failed. A reviewer may waive them (submit_mapping_review on this gate) or "
    "the mapping must change and the run be re-run from canonical_mapping.",
    "certification": "A human reviewer must certify the bundle and metrics (certify_run), then publish_run.",
}


def review_item_out(item: ReviewItem) -> ReviewItemOut:
    return ReviewItemOut(
        item_key=item.item_key,
        gate=item.gate.value,
        kind=item.kind,
        summary=item.summary,
        reason_codes=item.reason_codes,
        subject_hash=item.subject_hash,
        alternatives=list(item.options.get("alternatives", []))[:3],
        suggested_transform=item.options.get("suggested_transform"),
    )


def run_summary(svc: Any, principal: Principal, run: RunRecord) -> RunSummary:
    steps = [
        StepStatus(step=s["step"], status=s["status"], attempts=s["attempts"]) for s in svc.steps(principal, run.run_id)
    ]
    status = run.status.value
    if status == "needs_review":
        nxt = NEXT.get(run.gate or "", "Waiting for human review.")
    elif status == "failed":
        nxt = "Inspect the error; fix the cause, then resume_run (retryable) or rerun from an earlier step."
    elif status == "complete":
        nxt = "Run complete. Read run://{id}/summary or the published bundle."
    else:
        nxt = "Call resume_run to continue."
    rid = str(run.run_id)
    return RunSummary(
        run_id=rid,
        company_id=run.company_id,
        connection_id=run.connection_id,
        status=status,
        current_step=run.current_step,
        gate=run.gate,
        pending_review_count=len(run.pending_items),
        pending_items=[review_item_out(i) for i in run.pending_items[:50]],
        steps=steps,
        error=ErrorOut(
            code=run.error.get("code", "INTERNAL"),
            message=run.error.get("message", ""),
            retryable=bool(run.error.get("retryable")),
        )
        if run.error
        else None,
        next_action=nxt.replace("{id}", rid),
        resources=[f"run://{rid}/summary", f"run://{rid}/findings", f"run://{rid}/audit"],
    )


def finding_counts(findings: list[Any]) -> dict[str, int]:
    return dict(sorted(Counter(f.code for f in findings).items()))
