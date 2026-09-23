"""Case drivers: how a golden case exercises the system before its checks run."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from src.adapters.faults import FaultInjector
from src.adapters.repositories import RunRecord
from src.domain.models import Principal, ReviewDecision, Role, RunStatus
from src.domain.project_models import ItemDecision, ReviewItem
from src.settings import Settings, get_settings
from src.workflows.facade import OnboardingService

AGENT = Principal(principal_id="agent:eval", role=Role.AGENT)
REVIEWER = Principal(principal_id="reviewer:eval", role=Role.REVIEWER)
ADMIN = Principal(principal_id="admin:eval", role=Role.ADMIN)
DEFAULT_OVERRIDES = {"mapping:crm.opportunities.rev": {"canonical_field": "amount"}}


@dataclass
class CaseRun:
    service: OnboardingService
    run: RunRecord
    seconds: float
    trace: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def run_id(self) -> UUID:
        return self.run.run_id

    def refresh(self) -> RunRecord:
        self.run = self.service.get_run(ADMIN, self.run.run_id)
        return self.run


def decisions(items: list[ReviewItem], overrides: dict[str, Any], reject: set[str]) -> list[ItemDecision]:
    out = []
    for item in items:
        if item.item_key in reject:
            out.append(ItemDecision(item_key=item.item_key, decision=ReviewDecision.REJECT))
        elif item.item_key in overrides:
            out.append(
                ItemDecision(
                    item_key=item.item_key,
                    decision=ReviewDecision.APPROVE_WITH_OVERRIDE,
                    override=overrides[item.item_key],
                )
            )
        else:
            out.append(ItemDecision(item_key=item.item_key, decision=ReviewDecision.APPROVE))
    return out


def build_service(root: Path, faults: str = "", **settings: Any) -> OnboardingService:
    s = Settings(
        var_root=root,
        fixtures_root=get_settings().fixtures_dir,
        env="test",
        step_backoff_base_seconds=0.0,
        log_level="WARNING",
        **settings,
    )
    return OnboardingService.build(s, faults=FaultInjector.parse(faults, "test"))


async def drive(
    svc: OnboardingService,
    fixture: str,
    until: str,
    overrides: dict[str, Any] | None = None,
    reject: set[str] | None = None,
    waive: bool = False,
) -> RunRecord:
    """until: 'gate_a' | 'certification' | 'complete'."""
    overrides = DEFAULT_OVERRIDES if overrides is None else overrides
    reject = reject or set()
    run = await svc.start_run(AGENT, f"fixture:{fixture}")
    for _ in range(5):
        if run.status is not RunStatus.NEEDS_REVIEW or until == "gate_a":
            return run
        if run.gate == "certification":
            if until == "certification":
                return run
            svc.certify(
                REVIEWER, run.run_id, run.pending_items[0].subject_hash, decisions(run.pending_items, {}, set())
            )
        elif run.gate == "test_failures":
            if not waive:
                return run
            svc.submit_review(REVIEWER, run.run_id, decisions(run.pending_items, {}, set()))
        else:
            svc.submit_review(REVIEWER, run.run_id, decisions(run.pending_items, overrides, reject))
        run = await svc.resume(AGENT, run.run_id)
    return run


async def run_case(case: dict[str, Any], workdir: Path, cache: dict[str, CaseRun]) -> CaseRun:
    key = f"{case['fixture']}|{case.get('driver', 'gate_a')}|{case.get('faults', '')}|{case.get('overrides')}"
    if key in cache and not case.get("fresh"):
        return cache[key]
    root = workdir / case["id"]
    svc = build_service(root, case.get("faults", ""))
    source = Path(svc.connections.resolve(f"fixture:{case['fixture']}").path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    started = time.monotonic()
    driver = case.get("driver", "gate_a")
    if driver == "mcp":
        from evals.mcp_driver import drive_mcp

        result = await drive_mcp(svc, case["fixture"])
    else:
        run = await drive(
            svc, case["fixture"], driver, case.get("overrides"), set(case.get("reject", [])), case.get("waive", False)
        )
        result = CaseRun(svc, run, 0.0)
    result.seconds = round(time.monotonic() - started, 2)
    result.extra["source_sha256_before"] = before
    if not case.get("fresh"):
        cache[key] = result  # fresh runs get mutated by their checks; never share them
    return result
