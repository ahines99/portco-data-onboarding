"""Shared fixtures. Fixture databases are generated once into var/fixtures and reused."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio
import pytest

os.environ.setdefault("PORTCO_ENV", "test")

from src.adapters.faults import FaultInjector
from src.adapters.repositories import RunRecord
from src.domain.models import Principal, ReviewDecision, Role, RunStatus
from src.domain.project_models import ItemDecision, ReviewItem
from src.fixtures.generate import ensure_fixture, load_ground_truth
from src.settings import PROJECT_ROOT, Settings
from src.workflows.facade import OnboardingService

FIXTURES = PROJECT_ROOT / "var" / "fixtures"
AGENT = Principal(principal_id="agent:claude", role=Role.AGENT)
REVIEWER = Principal(principal_id="alice", role=Role.REVIEWER)
ADMIN = Principal(principal_id="admin", role=Role.ADMIN)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    for name in ("portco_a", "portco_b"):
        ensure_fixture(name, FIXTURES)
    return FIXTURES


def make_settings(root: Path, **overrides: Any) -> Settings:
    return Settings(
        var_root=root,
        fixtures_root=FIXTURES,
        env="test",
        step_backoff_base_seconds=0.0,
        log_level="WARNING",
        **overrides,
    )


def make_service(root: Path, faults: FaultInjector | None = None, **overrides: Any) -> OnboardingService:
    return OnboardingService.build(make_settings(root, **overrides), faults=faults)


@pytest.fixture
def service(tmp_path: Path, fixtures_dir: Path) -> OnboardingService:
    return make_service(tmp_path)


def run_async(fn: Callable[[], Any]) -> Any:
    return anyio.run(fn)


def decide_all(
    items: list[ReviewItem], overrides: dict[str, dict[str, Any]] | None = None, reject: set[str] | None = None
) -> list[ItemDecision]:
    overrides = overrides or {}
    reject = reject or set()
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


STANDARD_OVERRIDES = {"mapping:crm.opportunities.rev": {"canonical_field": "amount"}}


async def drive(
    svc: OnboardingService,
    fixture: str = "portco_a",
    *,
    certify: bool = True,
    overrides: dict[str, dict[str, Any]] | None = None,
    waive: bool = False,
) -> RunRecord:
    """Happy-path driver: agent starts, reviewer decides every gate, agent resumes."""
    run = await svc.start_run(AGENT, f"fixture:{fixture}")
    for _ in range(4):
        if run.status is not RunStatus.NEEDS_REVIEW:
            break
        if run.gate == "certification" and not certify:
            break
        if run.gate == "test_failures" and not waive:
            break
        if run.gate == "certification":
            manifest = run.pending_items[0].subject_hash
            svc.certify(REVIEWER, run.run_id, manifest, decide_all(run.pending_items))
        else:
            svc.submit_review(
                REVIEWER,
                run.run_id,
                decide_all(run.pending_items, overrides if overrides is not None else STANDARD_OVERRIDES),
            )
        run = await svc.resume(AGENT, run.run_id)
    return run


@dataclass
class CompletedRun:
    service: OnboardingService
    run: RunRecord
    root: Path

    @property
    def run_id(self) -> UUID:
        return self.run.run_id


@pytest.fixture(scope="session")
def completed_a(tmp_path_factory: pytest.TempPathFactory, fixtures_dir: Path) -> CompletedRun:
    """One full fixture A run (dbt included), shared by many read-only assertions."""
    root = tmp_path_factory.mktemp("completed_a")
    svc = make_service(root)
    run = anyio.run(lambda: drive(svc))
    assert run.status is RunStatus.COMPLETE, run.error
    return CompletedRun(svc, run, root)


@pytest.fixture(scope="session")
def truth_a() -> dict[str, Any]:
    return load_ground_truth("portco_a")


@pytest.fixture(scope="session")
def truth_b() -> dict[str, Any]:
    return load_ground_truth("portco_b")
