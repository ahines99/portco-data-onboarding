"""Concurrent invocations, request cancellation and shutdown across the real service boundary."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import anyio
import pytest

from src.adapters.external import ConnectionRegistry
from src.domain.errors import DependencyFailed, LeaseLost
from src.domain.models import RunStatus, StepName
from src.services.sandbox import _run_dbt_process
from src.workflows.base import StepSpec
from src.workflows.contracts import StepContext, StepResult
from src.workflows.facade import OnboardingService
from tests.conftest import AGENT, REVIEWER, make_service
from tests.test_publication_recovery import publication_context

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def wait_for(event: threading.Event) -> None:
    with anyio.fail_after(10):
        while not event.is_set():
            await anyio.sleep(0.01)


def pending_run(svc: OnboardingService) -> Any:
    with svc.store.tx() as tx:
        return tx.runs.create(company_id="portco_a", connection_id="fixture:portco_a", requested_by="test")


async def test_overlapping_workflows_keep_their_connection_policy_until_their_own_exit(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = make_service(tmp_path)
    first, second = pending_run(svc), pending_run(svc)
    resolving, second_finished = threading.Event(), threading.Event()
    resolved: list[str] = []
    original_resolve = ConnectionRegistry.resolve

    def resolve(registry: ConnectionRegistry, connection_id: str) -> Any:
        if connection_id == "fixture:portco_b":
            resolving.set()
            assert second_finished.wait(10), "the second workflow could not finish independently"
        resolved.append(connection_id)
        return original_resolve(registry, connection_id)

    def step(ctx: StepContext) -> StepResult:
        if ctx.run.run_id == first.run_id:
            # Suspend a cache miss while a second real invocation starts and exits. Previously
            # its finally reset the shared cache to None and this assignment raised TypeError.
            assert svc.engine._connection_policy("fixture:portco_b")["company_id"] == "portco_b"
            assert svc.engine._connection_policy("fixture:portco_a")["company_id"] == "portco_a"
        return StepResult()

    monkeypatch.setattr(ConnectionRegistry, "resolve", resolve)
    svc.engine.steps = [StepSpec(StepName.CONNECTION_VALIDATION, step, None)]
    outcomes: dict[str, Any] = {}

    async def run_first() -> None:
        outcomes["first"] = await svc.resume(AGENT, first.run_id)

    async def run_second() -> None:
        await wait_for(resolving)
        try:
            outcomes["second"] = await svc.resume(AGENT, second.run_id)
        finally:
            second_finished.set()

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(run_first)
        tasks.start_soon(run_second)

    assert all(run.status is RunStatus.COMPLETE and run.error is None for run in outcomes.values())
    assert resolved.count("fixture:portco_a") == 2  # exactly once per independent invocation
    assert resolved.count("fixture:portco_b") == 1
    for run in outcomes.values():
        events, valid = svc.audit(REVIEWER, run.run_id)
        assert valid and not any(event.event_type == "run_failed" for event in events)


async def test_two_complete_discovery_workflows_can_share_one_service(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = make_service(tmp_path)
    barrier = threading.Barrier(2, timeout=10)
    original = svc.engine.steps[0]

    def overlap(ctx: StepContext) -> StepResult:
        barrier.wait()
        return original.fn(ctx)

    svc.engine.steps = [StepSpec(original.name, overlap, original.output_type), *svc.engine.steps[1:]]
    results: list[Any] = []

    async def discover(fixture: str) -> None:
        results.append(await svc.start_run(AGENT, f"fixture:{fixture}"))

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(discover, "portco_a")
        tasks.start_soon(discover, "portco_b")

    assert len(results) == 2
    assert {run.company_id for run in results} == {"portco_a", "portco_b"}
    for run in results:
        assert run.status is RunStatus.NEEDS_REVIEW and run.gate == "mapping_review"
        assert run.pending_items and run.error is None and run.lease_owner is None
        assert svc.audit(REVIEWER, run.run_id)[1]


async def test_request_cancelled_during_source_resolution_creates_no_run(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = make_service(tmp_path)
    entered, release, finished = (threading.Event() for _ in range(3))
    scopes: list[anyio.CancelScope] = []
    original = ConnectionRegistry.resolve

    def resolve(registry: ConnectionRegistry, connection_id: str) -> Any:
        entered.set()
        try:
            assert release.wait(10)
            return original(registry, connection_id)
        finally:
            finished.set()

    monkeypatch.setattr(ConnectionRegistry, "resolve", resolve)

    async def request() -> None:
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await svc.start_run(AGENT, "fixture:portco_a")

    try:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(request)
                await wait_for(entered)
                scopes[0].cancel()
        assert not finished.is_set()
        assert svc.list_runs(AGENT) == []
    finally:
        release.set()
        await wait_for(finished)
    assert svc.list_runs(AGENT) == []


@pytest.mark.parametrize("interrupt", ["request", "shutdown", "cancel_run"])
async def test_interruption_stops_orchestration_before_an_inflight_step_returns(
    tmp_path: Path, fixtures_dir: Path, interrupt: str
) -> None:
    svc = make_service(tmp_path)
    run = pending_run(svc)
    started, release_step, step_finished, request_finished = (threading.Event() for _ in range(4))
    contexts: list[StepContext] = []
    close_threads: list[int] = []
    step_threads: list[int] = []
    scopes: list[anyio.CancelScope] = []
    following: list[str] = []

    class Adapter:
        def close(self) -> None:
            close_threads.append(threading.get_ident())

    def blocked(ctx: StepContext) -> StepResult:
        contexts.append(ctx)
        step_threads.append(threading.get_ident())
        ctx._adapter = Adapter()  # type: ignore[assignment]
        started.set()
        try:
            assert release_step.wait(10), "the test did not release its step"
            return StepResult(audit=[("late_result", {})])
        finally:
            step_finished.set()

    def next_step(ctx: StepContext) -> StepResult:
        following.append("ran")
        return StepResult()

    svc.engine.steps = [
        StepSpec(StepName.CONNECTION_VALIDATION, blocked, None),
        StepSpec(StepName.SCHEMA_PROFILING, next_step, None),
    ]

    async def request() -> None:
        try:
            with anyio.CancelScope() as scope:
                scopes.append(scope)
                await svc.resume(AGENT, run.run_id)
        finally:
            request_finished.set()

    try:
        with anyio.fail_after(10):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(request)
                await wait_for(started)
                if interrupt == "cancel_run":
                    assert svc.cancel(REVIEWER, run.run_id, "test cancellation").status is RunStatus.CANCELLED
                elif interrupt == "shutdown":
                    tasks.cancel_scope.cancel()  # the server cancels all request tasks during shutdown
                else:
                    scopes[0].cancel()
                if interrupt != "shutdown":
                    await wait_for(request_finished)
        assert request_finished.is_set()
        await wait_for(contexts[0].execution_cancelled)
        with anyio.fail_after(10):
            while svc.get_run(AGENT, run.run_id).lease_owner is not None:
                await anyio.sleep(0.01)
        stopped = svc.get_run(AGENT, run.run_id)
        expected = RunStatus.CANCELLED if interrupt == "cancel_run" else RunStatus.PENDING
        assert stopped.status is expected and not stopped.lease_live()
        assert not step_finished.is_set() and not close_threads and not following
        with svc.store.read() as tx:
            attempts = tx.steps.list(run.run_id)
        assert len(attempts) == 1 and attempts[0].status == "cancelled" and attempts[0].output_ref is None
        if interrupt != "cancel_run":
            # A successor can finish while the abandoned step still runs. Late completion and
            # resource cleanup must not overwrite its status, artifacts or execution lease.
            svc.engine.steps = [StepSpec(StepName.CONNECTION_VALIDATION, lambda ctx: StepResult(), None)]
            assert (await svc.resume(AGENT, run.run_id)).status is RunStatus.COMPLETE
            assert not step_finished.is_set()
    finally:
        release_step.set()
        await wait_for(step_finished)
        with anyio.fail_after(10):
            while not close_threads:
                await anyio.sleep(0.01)

    assert close_threads == step_threads  # resource cleanup belongs to the step's worker thread
    assert not following
    assert not any(event.event_type == "late_result" for event in svc.audit(REVIEWER, run.run_id)[0])
    if interrupt != "cancel_run":
        assert svc.get_run(AGENT, run.run_id).status is RunStatus.COMPLETE


@pytest.mark.parametrize("interrupt", ["cancel", "timeout"])
async def test_dbt_process_is_reaped_on_interruption(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch, interrupt: str
) -> None:
    svc = make_service(tmp_path)
    ctx = publication_context(svc)
    if interrupt == "timeout":
        ctx.settings = ctx.settings.model_copy(update={"dbt_timeout_seconds": 0.2})
    processes: list[subprocess.Popen[str]] = []
    launched, finished = threading.Event(), threading.Event()
    original = subprocess.Popen

    def capture(*args: Any, **kwargs: Any) -> Any:
        proc = original(*args, **kwargs)
        # taskkill is a separate cleanup subprocess on Windows.
        if args[0][0] == sys.executable:
            processes.append(proc)
            launched.set()
        return proc

    monkeypatch.setattr(subprocess, "Popen", capture)
    expected = LeaseLost if interrupt == "cancel" else DependencyFailed

    def run_process() -> None:
        try:
            with pytest.raises(expected):
                _run_dbt_process(ctx, [sys.executable, "-c", "import time; time.sleep(30)"], dict(os.environ))
        finally:
            finished.set()

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(anyio.to_thread.run_sync, run_process)
            await wait_for(launched)
            if interrupt == "cancel":
                ctx.execution_cancelled.set()
            await wait_for(finished)
    assert len(processes) == 1 and processes[0].poll() is not None
