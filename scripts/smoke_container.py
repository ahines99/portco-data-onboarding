"""Exercise an already running Compose stack, including an actual MCP restart.

Run `docker compose --profile full up --build -d` first. Set
PORTCO_SMOKE_TOKEN to an agent token scoped to portco_a in PORTCO_HTTP_TOKENS.
Set PORTCO_SMOKE_REVIEWER_TOKEN for the synthetic CI reviewer. This is automated test
approval, not evidence of independent human review. The script recreates the whole stack.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

REPO = Path(__file__).resolve().parents[1]


def compose(*args: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "--profile", "full", *args], cwd=REPO, check=True, capture_output=True, text=True
    )
    return result.stdout


async def wait_ready(base: str) -> None:
    deadline = time.monotonic() + 120
    async with httpx2.AsyncClient(timeout=5) as client:
        while time.monotonic() < deadline:
            try:
                if (await client.get(f"{base}/healthz")).status_code == 200:
                    return
            except httpx2.HTTPError:
                pass
            await asyncio.sleep(1)
    raise RuntimeError("container did not become healthy within 120 seconds")


async def check(base: str, token: str, run_id: str | None = None) -> dict[str, Any]:
    async with httpx2.AsyncClient(timeout=60) as anonymous:
        for headers in ({}, {"Authorization": "Bearer invalid-smoke-token"}):
            response = await anonymous.post(
                f"{base}/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            )
            if response.status_code != 401:
                raise RuntimeError(f"unauthorized MCP request returned {response.status_code}, expected 401")
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=120) as client,
        streamable_http_client(f"{base}/mcp", http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        health = await session.call_tool("healthcheck", {})
        if health.is_error or not health.structured_content or health.structured_content.get("database") != "ok":
            raise RuntimeError("authenticated MCP database healthcheck failed")
        name = "get_run_status" if run_id else "start_onboarding_run"
        arguments = {"run_id": run_id} if run_id else {"connection_id": "fixture:portco_a"}
        result = await session.call_tool(name, arguments)
        if result.is_error or not result.structured_content:
            raise RuntimeError(f"{name} failed: {result.structured_content}")
        return dict(result.structured_content)


async def call(base: str, token: str, name: str, arguments: dict[str, Any], *, denied: bool = False) -> dict[str, Any]:
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=900) as client,
        streamable_http_client(f"{base}/mcp", http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, arguments)
        body = dict(result.structured_content or {})
        if denied:
            if not result.is_error or body.get("code") != "FORBIDDEN":
                raise RuntimeError("agent self-approval was not refused")
        elif result.is_error or not body:
            raise RuntimeError(f"{name} failed: {body}")
        return body


async def complete(base: str, token: str, reviewer: str, before: dict[str, Any]) -> dict[str, Any]:
    rid = before["run_id"]
    decisions = [{"item_key": i["item_key"], "decision": "approve"} for i in before["pending_items"]]
    args = {"run_id": rid, "decisions": decisions}
    await call(base, token, "submit_mapping_review", args, denied=True)
    approval = await call(base, reviewer, "submit_mapping_review", args)
    await call(base, token, "generate_dbt_artifacts", {"run_id": rid, "approval_id": approval["approval_id"]})
    report = await call(base, token, "run_sandbox_tests", {"run_id": rid})
    if not report.get("passed"):
        raise RuntimeError(f"sandbox reconciliation failed: {report}")
    status = await check(base, token, rid)
    if status["gate"] != "certification":
        raise RuntimeError("expected certification gate")
    cert = await call(
        base, reviewer, "certify_run", {"run_id": rid, "subject_hash": status["pending_items"][0]["subject_hash"]}
    )
    publication = await call(base, token, "publish_run", {"run_id": rid, "certification_id": cert["approval_id"]})
    if publication["status"] != "complete" or len(publication["published_metrics"]) != 9:
        raise RuntimeError("expected nine certified published metrics")
    return publication


def verify_publication(run_id: str, database: str | None = None) -> None:
    from uuid import UUID

    rid = str(UUID(run_id))
    code = f"""
from hashlib import sha256
from pathlib import Path
from uuid import UUID
from src.workflows.facade import OnboardingService
from src.domain.models import Principal, Role, StepName
s = OnboardingService.build()
p = Principal(principal_id='ci-verifier', role=Role.ADMIN)
r = UUID('{rid}')
assert s.audit(p, r)[1]
b = s.artifact(p, r, StepName.ARTIFACT_GENERATION)
receipt = s.artifact(p, r, StepName.PUBLISH)
root = Path(receipt.path)
assert root.is_relative_to(s.settings.published_root)
assert (root / 'certification.json').is_file()
for f in b.files:
    path = root / f.path
    assert path.resolve().is_relative_to(root.resolve())
    assert sha256(path.read_bytes()).hexdigest() == f.sha256
print('PASS: published file hashes and audit chain')
"""
    args = ["exec", "-T"]
    if database:
        args += ["-e", f"PORTCO_DATABASE_URL=postgresql+psycopg://portco:portco@postgres:5432/{database}"]
    print(compose(*args, "mcp", "python", "-c", code).strip())


def verify_database_restore(run_id: str) -> None:
    from uuid import uuid4

    name = f"portco_restore_{uuid4().hex}"
    archive = f"/tmp/{name}.dump"  # noqa: S108 — random name inside the disposable Compose container
    compose("exec", "-T", "postgres", "pg_dump", "-U", "portco", "-d", "portco", "-Fc", "-f", archive)
    compose("exec", "-T", "postgres", "createdb", "-U", "portco", name)
    try:
        compose("exec", "-T", "postgres", "pg_restore", "-U", "portco", "-d", name, archive)
        verify_publication(run_id, name)
    finally:
        compose("exec", "-T", "postgres", "dropdb", "-U", "portco", name)
    print("PASS: PostgreSQL dump/restore with existing artifact volume")


async def smoke(base: str, token: str, reviewer: str) -> None:
    await wait_ready(base)
    # Inspect the actual Postgres version table, not merely the presence of migration files.
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(REPO / "alembic.ini"))
    config.set_main_option("script_location", str(REPO / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    version = compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "portco",
        "-d",
        "portco",
        "-Atc",
        "SELECT version_num FROM alembic_version",
    ).strip()
    if version != head:
        raise RuntimeError(f"database revision {version!r} differs from source head {head!r}")
    compose("exec", "-T", "mcp", "python", "-m", "src.cli", "fixtures", "generate", "--fixture", "a")
    before = await check(base, token)
    if before.get("gate") != "mapping_review":
        raise RuntimeError(f"run did not pause at mapping_review: {before}")
    compose("restart", "mcp")
    await wait_ready(base)
    after = await check(base, token, str(before["run_id"]))
    for field in ("run_id", "status", "gate", "pending_items"):
        if after.get(field) != before.get(field):
            raise RuntimeError(f"persisted {field} changed across container restart")
    publication = await complete(base, token, reviewer, after)
    verify_publication(str(before["run_id"]))
    verify_database_restore(str(before["run_id"]))
    compose("down")  # Deliberately retain BOTH named volumes.
    compose("up", "-d")
    await wait_ready(base)
    restored = await check(base, token, str(before["run_id"]))
    if restored["status"] != "complete":
        raise RuntimeError("certified run did not survive stack recreation")
    verify_publication(str(before["run_id"]))
    print(f"PASS: migration {head}, auth, publication {publication['version']}, MCP restart and full stack recreation")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    token = os.environ.get("PORTCO_SMOKE_TOKEN")
    reviewer = os.environ.get("PORTCO_SMOKE_REVIEWER_TOKEN")
    if not token or not reviewer:
        parser.error("PORTCO_SMOKE_TOKEN and PORTCO_SMOKE_REVIEWER_TOKEN must identify separate scoped roles")
    asyncio.run(smoke(args.url.rstrip("/"), token, reviewer))


if __name__ == "__main__":
    main()
