"""Review packets must identify the exact run, gate and content the reviewer saw."""

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, get_ident
from typing import Any
from uuid import uuid4

import pytest
import yaml
from mcp import Client
from sqlalchemy import event
from typer.testing import CliRunner

from scripts.postgres_test_db import disposable_database
from src import cli
from src.adapters.repositories import RunRecord
from src.domain.errors import Conflict, ValidationFailed
from src.domain.hashing import content_hash
from src.domain.models import ReviewGate, RunStatus
from src.domain.project_models import ReviewItem
from src.workflows.facade import OnboardingService
from tests.conftest import AGENT, REVIEWER, decide_all, make_service
from tests.test_mcp import Harness, call

pytestmark = [pytest.mark.security, pytest.mark.anyio]


@pytest.fixture
def binding_service(tmp_path: Path) -> Iterator[OnboardingService]:
    service = make_service(tmp_path)
    yield service
    service.store.engine.dispose()


def pending_run(service: OnboardingService, gate: ReviewGate = ReviewGate.MAPPING_REVIEW) -> RunRecord:
    """Seed a real persisted gate without invoking unrelated fixture/dbt work."""
    item = ReviewItem(
        item_key="bundle:manifest" if gate is ReviewGate.CERTIFICATION else "mapping:billing.amount",
        gate=gate,
        kind="bundle" if gate is ReviewGate.CERTIFICATION else "mapping",
        summary="Amount in cents",
        subject_hash=content_hash({"amount_unit": "cents", "gate": gate.value}),
    )
    with service.store.tx() as tx:
        run = tx.runs.create(company_id="portco_a", connection_id="fixture:portco_a", requested_by=AGENT.principal_id)
        tx.runs.update(run.run_id, status=RunStatus.RUNNING)
        tx.runs.update(
            run.run_id, status=RunStatus.NEEDS_REVIEW, gate=gate.value, current_step=gate.value, pending_items=[item]
        )
        return tx.runs.get(run.run_id)


def assert_no_approvals(service: OnboardingService, run: RunRecord) -> None:
    with service.store.tx() as tx:
        assert tx.approvals.for_run(run.run_id) == []


def replace_packet(service: OnboardingService, run: RunRecord) -> RunRecord:
    changed = [
        item.model_copy(update={"summary": "Amount in major units", "subject_hash": content_hash("revised packet")})
        for item in run.pending_items
    ]
    with service.store.tx() as tx:
        tx.runs.update(run.run_id, pending_items=changed)
        return tx.runs.get(run.run_id)


@pytest.mark.parametrize("gate", [ReviewGate.MAPPING_REVIEW, ReviewGate.TEST_FAILURES])
def test_stale_decisions_cannot_approve_changed_content_with_identical_keys(
    binding_service: OnboardingService, gate: ReviewGate
) -> None:
    old = pending_run(binding_service, gate)
    current = replace_packet(binding_service, old)
    assert [i.item_key for i in old.pending_items] == [i.item_key for i in current.pending_items]
    with pytest.raises(Conflict, match="subject hash"):
        binding_service.submit_review(
            REVIEWER,
            old.run_id,
            decide_all(old.pending_items),
            subject_hash=old.pending_items[0].subject_hash,
            gate=gate,
        )
    assert_no_approvals(binding_service, old)
    approved = binding_service.submit_review(
        REVIEWER,
        current.run_id,
        decide_all(current.pending_items),
        subject_hash=current.pending_items[0].subject_hash,
        gate=gate,
    )
    assert approved.subject_hash == current.pending_items[0].subject_hash


def test_submission_rechecks_persisted_gate_instead_of_cached_run(
    binding_service: OnboardingService, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = pending_run(binding_service)
    with binding_service.store.tx() as tx:
        tx.runs.update(old.run_id, status=RunStatus.CANCELLED, pending_items=[], gate=None)
    # A previously fetched application snapshot is insufficient authorization to write.
    monkeypatch.setattr(binding_service, "get_run", lambda *_args: old)
    with pytest.raises(Conflict, match="not waiting"):
        binding_service.submit_review(
            REVIEWER,
            old.run_id,
            decide_all(old.pending_items),
            subject_hash=old.pending_items[0].subject_hash,
            gate=ReviewGate.MAPPING_REVIEW,
        )
    assert_no_approvals(binding_service, old)


def assert_concurrent_packet_change_rejected(service: OnboardingService) -> None:
    old = pending_run(service)
    changed = [
        item.model_copy(update={"summary": "Changed while being reviewed", "subject_hash": content_hash("new packet")})
        for item in old.pending_items
    ]
    approval_lock_attempted = Event()
    writer_thread = get_ident()

    def observe_lock_attempt(
        _conn: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _executemany: bool
    ) -> None:
        # Signal before the real database call blocks, without replacing its locking behavior.
        if get_ident() != writer_thread and (statement == "BEGIN IMMEDIATE" or "FOR UPDATE" in statement):
            approval_lock_attempted.set()

    event.listen(service.store.engine, "before_cursor_execute", observe_lock_attempt)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with service.store.tx() as tx:
                tx.runs.get(old.run_id, lock=True)
                tx.runs.update(old.run_id, pending_items=changed)
                approval = pool.submit(
                    service.submit_review,
                    REVIEWER,
                    old.run_id,
                    decide_all(old.pending_items),
                    subject_hash=old.pending_items[0].subject_hash,
                    gate=ReviewGate.MAPPING_REVIEW,
                )
                assert approval_lock_attempted.wait(timeout=5), "approval never attempted the database lock"
                assert not approval.done(), "approval completed before the competing write committed"
            # Exiting the writer transaction releases the real lock. The waiting approval must
            # read the committed new packet, reject the old hash and leave no approval behind.
            with pytest.raises(Conflict, match="subject hash"):
                approval.result(timeout=10)
    finally:
        event.remove(service.store.engine, "before_cursor_execute", observe_lock_attempt)
    assert_no_approvals(service, old)


def test_concurrent_packet_change_blocks_then_rejects_sqlite(binding_service: OnboardingService) -> None:
    assert_concurrent_packet_change_rejected(binding_service)


@pytest.mark.postgres
def test_concurrent_packet_change_blocks_then_rejects_postgres(tmp_path: Path) -> None:
    admin_url = os.environ.get("PORTCO_TEST_POSTGRES_URL")
    if not admin_url:
        pytest.skip("PORTCO_TEST_POSTGRES_URL not set")
    with disposable_database(
        admin_url, allow_create=os.environ.get("PORTCO_TEST_POSTGRES_ALLOW_CREATE") == "1"
    ) as database_url:
        service = make_service(tmp_path, database_url=database_url)
        try:
            assert_concurrent_packet_change_rejected(service)
        finally:
            service.store.engine.dispose()


@pytest.mark.parametrize("field", ["run_id", "gate", "subject_hash"])
@pytest.mark.parametrize("missing", [False, True])
def test_cli_rejects_mismatched_or_missing_export_metadata(
    binding_service: OnboardingService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, missing: bool
) -> None:
    run = pending_run(binding_service)
    monkeypatch.setattr(cli, "_service", lambda: binding_service)
    runner = CliRunner()
    path = tmp_path / "review.yaml"
    assert runner.invoke(cli.app, ["review", str(run.run_id), "--export", str(path)]).exit_code == 0
    packet = yaml.safe_load(path.read_text())
    if missing:
        del packet[field]
    else:
        packet[field] = {"run_id": str(uuid4()), "gate": "certification", "subject_hash": "stale-packet"}[field]
    path.write_text(yaml.safe_dump(packet), encoding="utf-8")
    result = runner.invoke(cli.app, ["review", str(run.run_id), "--import", str(path), "--default", "approve"])
    assert result.exit_code == 2, result.output
    assert "CONFLICT" in result.output or "VALIDATION" in result.output
    assert_no_approvals(binding_service, run)


@pytest.mark.parametrize("gate", [ReviewGate.MAPPING_REVIEW, ReviewGate.CERTIFICATION])
def test_cli_imports_current_mapping_or_certification_packet(
    binding_service: OnboardingService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate: ReviewGate
) -> None:
    run = pending_run(binding_service, gate)
    monkeypatch.setattr(cli, "_service", lambda: binding_service)
    runner = CliRunner()
    path = tmp_path / "review.yaml"
    assert runner.invoke(cli.app, ["review", str(run.run_id), "--export", str(path)]).exit_code == 0
    result = runner.invoke(cli.app, ["review", str(run.run_id), "--import", str(path), "--default", "approve"])
    assert result.exit_code == 0, result.output
    with binding_service.store.tx() as tx:
        approvals = tx.approvals.for_run(run.run_id)
    assert len(approvals) == 1
    assert approvals[0].gate is gate
    assert approvals[0].subject_hash == run.pending_items[0].subject_hash


async def test_mcp_rejects_stale_mapping_hash(binding_service: OnboardingService) -> None:
    run = pending_run(binding_service)
    async with Client(Harness(binding_service).as_(REVIEWER).server) as client:
        err, body = await call(
            client,
            "submit_mapping_review",
            run_id=str(run.run_id),
            subject_hash="stale-packet",
            gate="mapping_review",
            decisions=[{"item_key": run.pending_items[0].item_key, "decision": "approve"}],
        )
    assert err and body["code"] == "CONFLICT"
    assert_no_approvals(binding_service, run)


async def test_mapping_endpoint_cannot_bypass_certification_hash(binding_service: OnboardingService) -> None:
    run = pending_run(binding_service, ReviewGate.CERTIFICATION)
    decisions = [{"item_key": run.pending_items[0].item_key, "decision": "approve"}]
    async with Client(Harness(binding_service).as_(REVIEWER).server) as client:
        err, body = await call(client, "certify_run", run_id=str(run.run_id), subject_hash="stale-packet")
        assert err and body["code"] == "CONFLICT"
        # The old alternate path accepted these certification decisions without any expected hash.
        omitted = await client.call_tool("submit_mapping_review", {"run_id": str(run.run_id), "decisions": decisions})
        assert omitted.is_error
        err, body = await call(
            client,
            "submit_mapping_review",
            run_id=str(run.run_id),
            subject_hash=run.pending_items[0].subject_hash,
            gate="mapping_review",
            decisions=decisions,
        )
        assert err and body["code"] == "CONFLICT"
        invalid_gate = await client.call_tool(
            "submit_mapping_review",
            {
                "run_id": str(run.run_id),
                "subject_hash": run.pending_items[0].subject_hash,
                "gate": "certification",
                "decisions": decisions,
            },
        )
        assert invalid_gate.is_error
    assert_no_approvals(binding_service, run)
    with pytest.raises(ValidationFailed, match="use certify"):
        binding_service.submit_review(
            REVIEWER,
            run.run_id,
            decide_all(run.pending_items),
            subject_hash=run.pending_items[0].subject_hash,
            gate=ReviewGate.CERTIFICATION,
        )
    approved = binding_service.certify(
        REVIEWER, run.run_id, run.pending_items[0].subject_hash, decide_all(run.pending_items)
    )
    assert approved.gate is ReviewGate.CERTIFICATION
