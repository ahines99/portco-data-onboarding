"""MCP surface through the in-process client (POD-501..509): typed tools, errors, resources, prompts, guard."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.server import MCPServer

from src.capabilities.tools import TOOL_ANNOTATIONS
from src.domain.models import Principal, Role
from src.domain.policies import ACTIONS
from src.mcp_server import build_server
from src.workflows.facade import OnboardingService
from tests.conftest import AGENT, REVIEWER, make_service, make_settings

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
CANARIES = ("Canary7f3a", "canary-7f3a@canary.invalid")


class Harness:
    def __init__(self, svc: OnboardingService) -> None:
        self.svc = svc
        self.who: Principal = AGENT
        self.server: MCPServer = build_server(
            svc.settings, service=svc, principal=lambda: self.who, canaries=CANARIES, with_auth=False
        )

    def as_(self, p: Principal) -> Harness:
        self.who = p
        return self


@pytest.fixture
def h(tmp_path: Path, fixtures_dir: Path) -> Harness:
    return Harness(make_service(tmp_path))


async def call(c: Client, tool: str, **args: Any) -> tuple[bool, dict[str, Any]]:
    r = await c.call_tool(tool, args)
    return bool(r.is_error), (r.structured_content or {})


async def test_tools_have_schemas_and_consistent_annotations(h: Harness) -> None:
    async with Client(h.server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == set(TOOL_ANNOTATIONS)
    for name, tool in tools.items():
        assert tool.input_schema and tool.output_schema, name
        ann = tool.annotations
        assert ann is not None
        if name in {"submit_mapping_review", "certify_run"}:
            assert ACTIONS["submit_review"].roles == ACTIONS["certify"].roles
            assert not ann.read_only_hint
        if name == "publish_run":
            assert ann.destructive_hint and ACTIONS["publish"].gate is not None
        if name in {"healthcheck", "get_run_status", "list_pending_reviews"}:
            assert ann.read_only_hint


async def test_healthcheck(h: Harness) -> None:
    async with Client(h.server) as c:
        err, body = await call(c, "healthcheck")
    assert not err and body["status"] == "ok" and body["database"] == "ok"


async def test_error_contract(h: Harness) -> None:
    async with Client(h.server) as c:
        err, body = await call(c, "get_run_status", run_id="not-a-uuid")
        assert err and body["code"] == "VALIDATION" and body["retryable"] is False
        err, body = await call(c, "get_run_status", run_id="00000000-0000-0000-0000-000000000000")
        assert err and body["code"] == "NOT_FOUND"
        err, body = await call(c, "start_onboarding_run", connection_id="fixture:nope")
        assert err and body["code"] == "NOT_FOUND"
        err, body = await call(c, "start_onboarding_run", connection_id="fixture:portco_a", company_id="portco_b")
        assert err and body["code"] == "VALIDATION"
        for text in (json.dumps(body),):
            assert "Traceback" not in text and "SELECT" not in text


async def test_internal_errors_return_a_correlation_id_only(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("SELECT ssn FROM hr.employees -- 123-45-6789")

    monkeypatch.setattr(h.svc, "get_run", boom)
    async with Client(h.server) as c:
        err, body = await call(c, "get_run_status", run_id="00000000-0000-0000-0000-000000000000")
    assert err and body["code"] == "INTERNAL" and "correlation id" in body["message"]
    assert "SELECT" not in body["message"] and "123-45" not in body["message"]


async def test_review_flow_guards(h: Harness) -> None:
    async with Client(h.server) as c:
        err, run = await call(c, "start_onboarding_run", connection_id="fixture:portco_a")
        assert not err and run["status"] == "needs_review" and run["gate"] == "mapping_review"
        rid = run["run_id"]
        decisions = [{"item_key": i["item_key"], "decision": "approve"} for i in run["pending_items"]]
        err, body = await call(c, "submit_mapping_review", run_id=rid, decisions=decisions)
        assert err and body["code"] == "FORBIDDEN"  # G23: the agent cannot approve its own proposals
        h.as_(REVIEWER)
        err, body = await call(c, "submit_mapping_review", run_id=rid, decisions=decisions)
        assert not err
        approval = body["approval_id"]
        h.as_(AGENT)
        for forged in ("00000000-0000-0000-0000-000000000000", "garbage"):
            err, body = await call(c, "generate_dbt_artifacts", run_id=rid, approval_id=forged)
            assert err and body["code"] in {"APPROVAL_REQUIRED", "VALIDATION"}
        err, body = await call(c, "publish_run", run_id=rid, certification_id=approval)
        assert err and body["code"] in {"APPROVAL_REQUIRED", "NOT_FOUND"}  # G22
        err, body = await call(c, "list_pending_reviews", run_id=rid)
        err, bundle = await call(c, "generate_dbt_artifacts", run_id=rid, approval_id=approval)
        assert not err and "billings" in bundle["generated_metrics"] and bundle["files"] > 10


async def test_profile_then_propose_mapping(h: Harness) -> None:
    async with Client(h.server) as c:
        err, prof = await call(c, "profile_schema", connection_id="fixture:portco_a", schemas=["billing"])
        assert not err and prof["status"] == "pending"
        assert {t["table"].split(".")[0] for t in prof["tables"]} == {"billing"}
        assert prof["pii_column_count"] >= 2 and "POSSIBLE_MINOR_UNITS" in prof["findings"]
        err, ms = await call(c, "propose_canonical_mapping", run_id=prof["run_id"])
        assert not err and ms["status"] == "needs_review" and ms["requires_review"] > 0
        assert ms["mapping_hash"] and ms["review_items"]


async def test_resources_and_templates(h: Harness) -> None:
    async with Client(h.server) as c:
        _, run = await call(c, "start_onboarding_run", connection_id="fixture:portco_a")
        rid = run["run_id"]
        templates = {t.uri_template for t in (await c.list_resource_templates()).resource_templates}
        assert "run://{run_id}/artifacts/{+path}" in templates
        assert "# Operating and safety policies" in (await c.read_resource("project://policies")).contents[0].text
        ont = json.loads((await c.read_resource("ontology://pe/v1")).contents[0].text)
        assert "customer" in ont["entities"]
        metric = json.loads((await c.read_resource("ontology://pe/v1/metrics/arr")).contents[0].text)
        assert metric["metric"] == "arr"
        for suffix in ("summary", "profile", "entities", "joins", "mapping", "findings", "audit", "metrics"):
            text = (await c.read_resource(f"run://{rid}/{suffix}")).contents[0].text
            assert text and not any(canary in text for canary in CANARIES), suffix
        findings = json.loads((await c.read_resource(f"run://{rid}/findings")).contents[0].text)
        fid = next(f for f in findings if f["evidence"])
        lineage = json.loads((await c.read_resource(f"finding://{fid['finding_id']}/lineage")).contents[0].text)
        assert lineage["evidence"] and lineage["evidence"][0]["source_uri"]
        ev = json.loads((await c.read_resource(f"evidence://{fid['evidence'][0]['source_id']}")).contents[0].text)
        assert ev["content_hash"]
        with pytest.raises(Exception, match=r"(?i)unknown|traversal|not found"):
            await c.read_resource(f"run://{rid}/artifacts/../../secrets")
        with pytest.raises(Exception):  # noqa: B017
            await c.read_resource(f"run://{rid}/test-report")  # not produced yet


async def test_prompts(h: Harness) -> None:
    async with Client(h.server) as c:
        names = {p.name for p in (await c.list_prompts()).prompts}
        assert names == {"review_run", "explain_mapping", "onboarding_kickoff"}
        got = await c.get_prompt("review_run", {"run_id": "abc"})
        assert "run://abc/findings" in got.messages[0].content.text  # type: ignore[union-attr]


async def test_pii_guard_middleware_blocks_leaking_output(h: Harness) -> None:
    @h.server.tool()
    def leaky() -> str:
        """A deliberately broken tool used to prove the guard works."""
        return "contact Canary7f3a at canary-7f3a@canary.invalid"

    async with Client(h.server) as c:
        err, body = await call(c, "leaky")
    assert err and body["code"] == "POLICY_VIOLATION"
    assert h.server._portco_guard.blocked == 1  # type: ignore[attr-defined]


async def test_cross_tenant_access_through_mcp(h: Harness) -> None:
    async with Client(h.server) as c:
        err, run = await call(c, "start_onboarding_run", connection_id="fixture:portco_a")
        h.as_(Principal(principal_id="bob", role=Role.REVIEWER, company_ids=("portco_b",)))
        err, body = await call(c, "get_run_status", run_id=run["run_id"])
        assert err and body["code"] == "NOT_FOUND"
        err, body = await call(c, "start_onboarding_run", connection_id="fixture:portco_a")
        assert err and body["code"] == "FORBIDDEN"


@pytest.mark.slow
async def test_full_flow_to_publish_through_mcp(h: Harness) -> None:
    async with Client(h.server) as c:
        _, run = await call(c, "start_onboarding_run", connection_id="fixture:portco_a")
        rid = run["run_id"]
        decisions = [{"item_key": i["item_key"], "decision": "approve"} for i in run["pending_items"]]
        decisions = [
            d
            | (
                {"decision": "approve_with_override", "override": {"canonical_field": "amount"}}
                if d["item_key"] == "mapping:crm.opportunities.rev"
                else {}
            )
            for d in decisions
        ]
        h.as_(REVIEWER)
        _, appr = await call(c, "submit_mapping_review", run_id=rid, decisions=decisions)
        h.as_(AGENT)
        err, _ = await call(c, "generate_dbt_artifacts", run_id=rid, approval_id=appr["approval_id"])
        assert not err
        err, tests = await call(c, "run_sandbox_tests", run_id=rid)
        assert not err and tests["passed"] and tests["status"] == "needs_review"
        assert all(ch["passed"] for ch in tests["reconciliation"])
        _, status = await call(c, "get_run_status", run_id=rid)
        subject = status["pending_items"][0]["subject_hash"]
        err, body = await call(c, "certify_run", run_id=rid, subject_hash=subject)
        assert err and body["code"] == "FORBIDDEN"
        h.as_(REVIEWER)
        err, body = await call(c, "certify_run", run_id=rid, subject_hash=subject, metric_decisions={"ARR": "reject"})
        assert err and body["code"] == "VALIDATION" and "unknown metrics" in body["message"]
        err, cert = await call(c, "certify_run", run_id=rid, subject_hash=subject, metric_decisions={"cogs": "reject"})
        assert not err
        h.as_(AGENT)
        err, pub = await call(c, "publish_run", run_id=rid, certification_id=cert["approval_id"])
        assert not err and pub["status"] == "complete" and pub["version"] == "v0001"
        assert "cogs" in pub["excluded_metrics"] and "ebitda" in pub["excluded_metrics"]
        err, again = await call(c, "publish_run", run_id=rid, certification_id=cert["approval_id"])
        assert not err and again["version"] == "v0001"  # idempotent


# --------------------------------------------------------------------------- transports


async def test_stdio_transport_smoke(tmp_path: Path, fixtures_dir: Path) -> None:
    from mcp import StdioServerParameters

    env = {
        **os.environ,
        "PORTCO_VAR_ROOT": str(tmp_path),
        "PORTCO_FIXTURES_ROOT": str(fixtures_dir),
        "PORTCO_LOG_LEVEL": "WARNING",
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "src.mcp_server"], env=env, cwd=str(Path(__file__).resolve().parents[1])
    )
    async with Client(params) as c:
        r = await c.call_tool("healthcheck", {})
        assert not r.is_error and r.structured_content["status"] == "ok"


async def test_http_transport_requires_bearer_token(tmp_path: Path, fixtures_dir: Path) -> None:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from pydantic import SecretStr

    settings = make_settings(
        tmp_path, http_tokens=SecretStr("tok-agent=agent:claude:agent:portco_a"), http_base_url="http://localhost:8000"
    )
    server = build_server(settings, service=make_service(tmp_path), with_auth=True)
    app = server.streamable_http_app()
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://localhost:8000") as anon:
            resp = await anon.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            assert resp.status_code == 401
        headers = {"Authorization": "Bearer tok-agent"}
        async with (
            httpx2.AsyncClient(transport=transport, base_url="http://localhost:8000", headers=headers) as http,
            streamable_http_client("http://localhost:8000/mcp", http_client=http) as streams,
        ):
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                r = await session.call_tool("healthcheck", {})
                assert not r.is_error
                r = await session.call_tool("start_onboarding_run", {"connection_id": "fixture:portco_b"})
                assert r.is_error and r.structured_content["code"] == "FORBIDDEN"  # token scoped to portco_a


def _unused(_: Callable[..., Any]) -> None:  # keeps type checkers quiet about helper imports
    return None
