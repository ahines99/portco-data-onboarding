"""Regressions for the 2026-10-10 audit's MCP capability findings (A20 phase bounds, A23 decision enums).

Annotations are client hints, not enforcement, so these tests check actual side effects: publication
rows and published directories, not only the returned summaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from mcp import Client

from src.domain.models import ReviewGate
from tests.conftest import AGENT, REVIEWER, make_service
from tests.test_mcp import Harness, call

pytestmark = [pytest.mark.integration, pytest.mark.anyio, pytest.mark.slow]


def _publications(h: Harness, run_id: str) -> list[dict[str, Any]]:
    with h.svc.store.tx() as tx:
        return list(tx.publications.for_run(UUID(run_id)))


def _approvals(h: Harness, run_id: str) -> list[Any]:
    with h.svc.store.tx() as tx:
        return list(tx.approvals.for_run(UUID(run_id)))


async def _certified(c: Client, h: Harness) -> tuple[str, dict[str, Any]]:
    """Drive fixture A through MCP to a valid certification without calling publish_run."""
    _, run = await call(c, "start_onboarding_run", connection_id="fixture:portco_a")
    rid = run["run_id"]
    decisions = [
        {"item_key": i["item_key"], "decision": "approve"}
        | (
            {"decision": "approve_with_override", "override": {"canonical_field": "amount"}}
            if i["item_key"] == "mapping:crm.opportunities.rev"
            else {}
        )
        for i in run["pending_items"]
    ]
    h.as_(REVIEWER)
    _, appr = await call(
        c,
        "submit_mapping_review",
        run_id=rid,
        decisions=decisions,
        subject_hash=run["pending_items"][0]["subject_hash"],
        gate=run["gate"],
    )
    h.as_(AGENT)
    err, _ = await call(c, "generate_dbt_artifacts", run_id=rid, approval_id=appr["approval_id"])
    assert not err
    err, tests = await call(c, "run_sandbox_tests", run_id=rid)
    assert not err and tests["status"] == "needs_review"
    _, status = await call(c, "get_run_status", run_id=rid)
    h.as_(REVIEWER)
    err, cert = await call(c, "certify_run", run_id=rid, subject_hash=status["pending_items"][0]["subject_hash"])
    assert not err
    h.as_(AGENT)
    return rid, cert


async def test_named_capabilities_never_publish_after_certification(tmp_path: Path, fixtures_dir: Path) -> None:
    h = Harness(make_service(tmp_path))
    async with Client(h.server) as c:
        rid, cert = await _certified(c, h)

        err, tests = await call(c, "run_sandbox_tests", run_id=rid)
        assert not err and tests["status"] != "complete" and tests["passed"]
        assert _publications(h, rid) == []

        mapping_approval = next(a for a in _approvals(h, rid) if a.gate is ReviewGate.MAPPING_REVIEW)
        err, bundle = await call(c, "generate_dbt_artifacts", run_id=rid, approval_id=str(mapping_approval.approval_id))
        assert not err and bundle["status"] != "complete"
        assert _publications(h, rid) == []

        err, resumed = await call(c, "resume_run", run_id=rid)
        assert not err and resumed["status"] != "complete"
        assert _publications(h, rid) == []
        published_root = h.svc.settings.published_root
        assert not published_root.exists() or not any(published_root.rglob("certification.json"))

        # Only the dedicated, certification-bound operation publishes.
        err, pub = await call(c, "publish_run", run_id=rid, certification_id=cert["approval_id"])
        assert not err and pub["status"] == "complete"
        rows = _publications(h, rid)
        assert len(rows) == 1 and rows[0]["state"] == "complete"


async def test_certification_decisions_are_validated_as_input(tmp_path: Path, fixtures_dir: Path) -> None:
    h = Harness(make_service(tmp_path))
    async with Client(h.server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        props = tools["certify_run"].input_schema["properties"]
        assert set(props["bundle_decision"]["enum"]) == {"approve", "reject"}

        rid, _ = await _certified(c, h)
        before = len(_approvals(h, rid))
        _, status = await call(c, "get_run_status", run_id=rid)
        subject = status["pending_items"][0]["subject_hash"] if status["pending_items"] else "x"
        h.as_(REVIEWER)
        result = await c.call_tool("certify_run", {"run_id": rid, "subject_hash": subject, "bundle_decision": "typo"})
        assert result.is_error
        assert "INTERNAL" not in str(result.content) and (result.structured_content or {}).get("code") != "INTERNAL"
        result = await c.call_tool(
            "certify_run", {"run_id": rid, "subject_hash": subject, "metric_decisions": {"billings": "maybe"}}
        )
        assert result.is_error and (result.structured_content or {}).get("code") != "INTERNAL"
        assert len(_approvals(h, rid)) == before
