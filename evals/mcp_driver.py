"""Drive a full onboarding through the MCP surface and record the tool trace (tool-correctness dimension)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from mcp import Client

from evals.drivers import ADMIN, AGENT, REVIEWER, CaseRun
from src.domain.models import Principal
from src.mcp_server import build_server
from src.workflows.facade import OnboardingService


async def drive_mcp(svc: OnboardingService, fixture: str) -> CaseRun:
    who: dict[str, Principal] = {"p": AGENT}
    server = build_server(svc.settings, service=svc, principal=lambda: who["p"], with_auth=False)
    trace: list[dict[str, Any]] = []

    async def call(c: Client, tool: str, principal: Principal, **args: Any) -> dict[str, Any]:
        who["p"] = principal
        r = await c.call_tool(tool, args)
        body = r.structured_content or {}
        trace.append(
            {
                "tool": tool,
                "principal": principal.role.value,
                "is_error": bool(r.is_error),
                "code": body.get("code") if r.is_error else None,
            }
        )
        return body

    async with Client(server) as c:
        run = await call(c, "start_onboarding_run", AGENT, connection_id=f"fixture:{fixture}")
        rid = run["run_id"]
        await call(c, "list_pending_reviews", AGENT, run_id=rid)
        denied = await call(
            c,
            "submit_mapping_review",
            AGENT,
            run_id=rid,
            decisions=[{"item_key": i["item_key"], "decision": "approve"} for i in run["pending_items"]],
        )
        decisions = [{"item_key": i["item_key"], "decision": "approve"} for i in run["pending_items"]]
        for d in decisions:
            if d["item_key"] == "mapping:crm.opportunities.rev":
                d.update({"decision": "approve_with_override", "override": {"canonical_field": "amount"}})
        approval = await call(c, "submit_mapping_review", REVIEWER, run_id=rid, decisions=decisions)
        await call(c, "generate_dbt_artifacts", AGENT, run_id=rid, approval_id=approval["approval_id"])
        await call(c, "run_sandbox_tests", AGENT, run_id=rid)
        status = await call(c, "get_run_status", AGENT, run_id=rid)
        subject = status["pending_items"][0]["subject_hash"]
        cert = await call(c, "certify_run", REVIEWER, run_id=rid, subject_hash=subject)
        await call(c, "publish_run", AGENT, run_id=rid, certification_id=cert["approval_id"])
    result = CaseRun(svc, svc.get_run(ADMIN, UUID(rid)), 0.0, trace=trace)
    result.extra["agent_self_approval"] = denied
    return result
