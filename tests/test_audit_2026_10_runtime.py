"""Regressions for the 2026-10-10 audit's runtime findings: A08 (authorize before source work) and the
PERF-2/4/5 responsiveness and bounded-work items. Deterministic: events and call counts, no timing."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.adapters.external import ConnectionRegistry, DuckDBAdapter
from src.domain.errors import Forbidden, PolicyViolation
from src.domain.metrics_reference import SubscriptionRec
from src.domain.models import Principal, Role, StepName
from src.services.sandbox import MAX_RECONCILIATION_MONTHS, _reconciliation_months
from src.settings import Settings
from src.workflows.facade import OnboardingService
from tests.conftest import AGENT, make_service

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


# --------------------------------------------------------------------------- A08


async def test_denied_tenant_triggers_no_fixture_generation(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path, fixtures_root=tmp_path / "fresh-fixtures", env="test")
    svc = OnboardingService.build(settings)
    scoped = Principal(principal_id="agent:a", role=Role.AGENT, company_ids=("portco_a",))
    with pytest.raises(Forbidden):
        await svc.start_run(scoped, "fixture:portco_b")
    assert not (tmp_path / "fresh-fixtures" / "portco_b.duckdb").exists()


async def test_authorization_precedes_any_source_resolution(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = make_service(tmp_path)

    def no_source_work(self: ConnectionRegistry, connection_id: str) -> Any:
        raise AssertionError("source resolved before authorization")

    monkeypatch.setattr(ConnectionRegistry, "resolve", no_source_work)
    scoped = Principal(principal_id="agent:b", role=Role.AGENT, company_ids=("portco_b",))
    with pytest.raises(Forbidden):
        await svc.start_run(scoped, "fixture:portco_a")


# --------------------------------------------------------------------------- PERF-2


def test_reads_do_not_queue_behind_a_writer(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    with svc.store.tx() as tx:
        run = tx.runs.create(company_id="portco_a", connection_id="fixture:portco_a", requested_by="a")
    db_path = str(svc.settings.db_url).removeprefix("sqlite:///")
    writer = sqlite3.connect(db_path, check_same_thread=False)
    writer.execute("BEGIN IMMEDIATE")  # another process/thread holds SQLite's single writer slot
    try:
        done = threading.Event()

        def reader() -> None:
            svc.get_run(AGENT, run.run_id)
            done.set()

        t = threading.Thread(target=reader)
        t.start()
        # The read completes while the writer lock is still held (the test releases it only afterwards).
        assert done.wait(10), "status read waited for the writer lock"
        t.join()
    finally:
        writer.rollback()
        writer.close()


async def test_workflow_driving_runs_off_the_event_loop_thread(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    loop_thread = threading.get_ident()
    seen: list[int] = []
    original = svc.engine.run

    async def recording_run(*args: Any, **kwargs: Any) -> Any:
        seen.append(threading.get_ident())
        return await original(*args, **kwargs)

    svc.engine.run = recording_run  # type: ignore[method-assign]
    run = await svc.start_run(AGENT, "fixture:portco_a", stop_after=StepName.CONNECTION_VALIDATION)
    assert run.current_step == StepName.SCHEMA_PROFILING.value
    assert seen and all(t != loop_thread for t in seen)


# --------------------------------------------------------------------------- PERF-4


async def test_source_policy_is_resolved_once_per_invocation(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = make_service(tmp_path)
    calls = {"resolve": 0, "open": 0}
    real_resolve, real_open = ConnectionRegistry.resolve, ConnectionRegistry.open

    def counting_resolve(self: ConnectionRegistry, connection_id: str) -> Any:
        calls["resolve"] += 1
        return real_resolve(self, connection_id)

    def counting_open(self: ConnectionRegistry, connection_id: str) -> Any:
        calls["open"] += 1
        return real_open(self, connection_id)

    monkeypatch.setattr(ConnectionRegistry, "resolve", counting_resolve)
    monkeypatch.setattr(ConnectionRegistry, "open", counting_open)
    await svc.start_run(AGENT, "fixture:portco_a")
    # One verification for the start call, one for all input hashes, one per opened adapter.
    assert calls["resolve"] <= calls["open"] + 2, calls


def test_table_metadata_is_cached_without_widening_the_allowlist(fixtures_dir: Path) -> None:
    adapter = ConnectionRegistry(fixtures_dir).open("fixture:portco_a?schemas=billing")
    assert isinstance(adapter, DuckDBAdapter)
    try:
        before = adapter.query_count
        adapter.describe_table("billing", "invoices")
        adapter.describe_table("billing", "invoices")
        adapter.row_count("billing", "invoices")
        # Two catalog queries once (the second describe is cached), the allowlist lookup, then the count.
        assert adapter.query_count - before == 4
        adapter.describe_table("crm", "accounts")  # metadata only
        with pytest.raises(PolicyViolation):
            adapter.row_count("crm", "accounts")
    finally:
        adapter.close()


# --------------------------------------------------------------------------- PERF-5


def test_reconciliation_horizon_is_bounded() -> None:
    sub = SubscriptionRec("c", Decimal("1"), "USD", date(2025, 1, 1), None)
    assert _reconciliation_months([sub], date(2026, 1, 31)) is not None
    ancient = SubscriptionRec("c", Decimal("1"), "USD", date(1, 1, 1), None)
    assert _reconciliation_months([ancient], date(2026, 1, 31)) is None
    edge = SubscriptionRec("c", Decimal("1"), "USD", date(2026 - MAX_RECONCILIATION_MONTHS // 12, 2, 1), None)
    months = _reconciliation_months([edge], date(2026, 1, 31))
    assert months is not None and len(months) == MAX_RECONCILIATION_MONTHS
