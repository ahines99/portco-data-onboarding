"""Regression tests for the audit's P1 findings: auth, redaction, PII detection, SQL guard,
category values, fingerprints, fail-closed gates, PII overrides and MCP accounting."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import duckdb
import pytest

from src.adapters.external import ConnectionRegistry
from src.adapters.sql_guard import check_select
from src.capabilities.auth import parse_tokens
from src.capabilities.common import principal_from_token
from src.domain.errors import PolicyViolation
from src.domain.models import ReviewDecision, ReviewGate, RunStatus
from src.domain.pii_guard import detect, mask
from src.domain.project_models import ItemDecision, ReviewItem, TestReport
from src.observability import redact
from src.services import approvals, sandbox
from src.services.pii import TEST_RECORD_PATTERN
from tests.conftest import ADMIN, AGENT, REVIEWER, decide_all, make_service, make_settings

pytestmark = [pytest.mark.security, pytest.mark.anyio]


# --------------------------------------------------------------------------- auth


def test_tokens_without_companies_reach_no_tenant() -> None:
    tokens = parse_tokens(
        "a=agent:claude:agent;r=alice:reviewer:*;x=bob:superuser:*;=nobody:agent:c1;s=svc:admin:c1|c2"
    )
    assert tokens["a"] == ("agent:claude", "agent", [])
    assert tokens["r"] == ("alice", "reviewer", ["*"])
    assert tokens["s"] == ("svc", "admin", ["c1", "c2"])
    assert "x" not in tokens and "" not in tokens  # unknown role and empty token are dropped
    unscoped = principal_from_token("agent:claude", ["role:agent"])
    assert not unscoped.can_access("portco_a")


def test_http_app_refuses_to_start_without_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.mcp_server as server

    monkeypatch.setattr(server, "get_settings", lambda: make_settings(tmp_path))
    with pytest.raises(RuntimeError, match="PORTCO_HTTP_TOKENS"):
        server._http_app()


async def test_healthz_is_public_and_mcp_is_not(tmp_path: Path, fixtures_dir: Path) -> None:
    import httpx2
    from pydantic import SecretStr

    from src.mcp_server import build_server

    settings = make_settings(tmp_path, http_tokens=SecretStr("t=agent:claude:agent:*"))
    app = build_server(settings, service=make_service(tmp_path), with_auth=True).streamable_http_app()
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://localhost:8000") as http:
            assert (await http.get("/healthz")).json() == {"status": "ok"}
            assert (
                await http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            ).status_code == 401


# --------------------------------------------------------------------------- redaction and detection


def test_redaction_is_recursive_and_masks_tracebacks() -> None:
    event = redact(
        None,
        "error",
        {
            "event": "x",
            "context": {"note": "mail jane@corp.example", "nested": [{"password": "hunter2"}]},
            "exception": 'Traceback (most recent call last):\n  ValueError: bad row "123-45-6789" for a@b.io',
        },
    )
    assert event["context"]["note"] == "[REDACTED:PII]"
    assert event["context"]["nested"][0]["password"] == "[REDACTED]"
    assert event["exception"].startswith("Traceback") and "123-45-6789" not in event["exception"]
    assert "a@b.io" not in event["exception"] and "ValueError" in event["exception"]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("ssn 123 45 6789", "national_id"),
        ("card 4111 1111 1111 1111", "payment_card"),
        ("card 4111-1111-1111-1111", "payment_card"),
        ("amex 3782 822463 10005", "payment_card"),
        ("call +44 20 7946 0958", "phone"),
        ("call (555) 123-4567", "phone"),
    ],
)
def test_pii_guard_detects_formatted_values(text: str, kind: str) -> None:
    assert kind in detect(text)
    assert "[PII]" in mask(text)


@pytest.mark.parametrize(
    "text",
    ["2026-09-23T19:08:27+00:00", "amount 1234 5678", "id 6f1c2a9e-3b7d-4c55-9a51-0d2f7e1b8c44", "v1.2.3", "4111 1111"],
)
def test_pii_guard_ignores_ordinary_text(text: str) -> None:
    assert detect(text) == []


# --------------------------------------------------------------------------- SQL guard


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT current_setting('threads')",
        "SELECT getvariable('secret')",
        'SELECT count(*) FROM "src"."billing"."invoices"',
        "SELECT * FROM (WITH l AS (SELECT 1) SELECT * FROM l) AS x, l",
        "SELECT * FROM query('SELECT 1')",
    ],
)
def test_sql_guard_rejects_settings_catalogs_and_out_of_scope_ctes(sql: str) -> None:
    with pytest.raises(PolicyViolation):
        check_select(sql, {"billing"})


def test_sql_guard_allows_nested_ctes_in_scope() -> None:
    check_select(
        "WITH l AS (SELECT 1 AS a), m AS (SELECT * FROM l) SELECT * FROM m WHERE a IN (SELECT a FROM l)", set()
    )


# --------------------------------------------------------------------------- data


def _scratch_db(tmp_path: Path, fixtures_dir: Path) -> ConnectionRegistry:
    shutil.copyfile(fixtures_dir / "portco_a.duckdb", tmp_path / "portco_a.duckdb")
    return ConnectionRegistry(tmp_path)


def test_fingerprint_changes_when_a_value_is_edited_in_place(tmp_path: Path, fixtures_dir: Path) -> None:
    reg = _scratch_db(tmp_path, fixtures_dir)
    a = reg.open("fixture:portco_a")
    before = a.fingerprint()
    a.close()
    con = duckdb.connect(str(tmp_path / "portco_a.duckdb"))
    con.execute("UPDATE billing.invoices SET total_amt = total_amt + 1 WHERE rowid = 0")
    con.close()
    a = reg.open("fixture:portco_a")
    assert a.fingerprint() != before
    a.close()


def test_person_like_columns_and_names_are_withheld(tmp_path: Path, fixtures_dir: Path) -> None:
    reg = _scratch_db(tmp_path, fixtures_dir)
    con = duckdb.connect(str(tmp_path / "portco_a.duckdb"))
    con.execute(
        "CREATE TABLE crm.regions AS SELECT * FROM (VALUES ('emea', 'Jane Smith'), ('apac', 'Raj Patel')) t(region, champion)"
    )
    con.execute("ALTER TABLE crm.regions ADD COLUMN account_owner VARCHAR DEFAULT 'ops'")
    con.close()
    a = reg.open("fixture:portco_a")
    a.spec.category_domains["crm.regions.region"] = ["apac", "emea"]
    try:
        assert a.low_cardinality_values("crm", "regions", "region", 12).values == ["apac", "emea"]
        assert (
            a.low_cardinality_values("crm", "regions", "champion", 12).withheld_reason == "unapproved_category_domain"
        )
        assert a.low_cardinality_values("crm", "regions", "account_owner", 12).withheld_reason == "person_like_column"
    finally:
        a.close()


@pytest.mark.parametrize(
    ("value", "is_test"),
    [("TEST Account 1", True), ("Test - Sandbox", True), ("test", True), ("TESTAMENT Corp", False), ("Contest", False)],
)
def test_one_test_record_rule_in_python_and_duckdb(value: str, is_test: bool) -> None:
    assert bool(re.search(TEST_RECORD_PATTERN, value)) is is_test
    got = duckdb.sql("SELECT regexp_matches($v, $p)", params={"v": value, "p": TEST_RECORD_PATTERN}).fetchone()
    assert got is not None and got[0] is is_test


def test_migrate_accepts_percent_in_the_database_url(tmp_path: Path) -> None:
    from src.workflows.facade import migrate

    folder = tmp_path / "a%20b"
    folder.mkdir()
    migrate(f"sqlite:///{(folder / 'db.sqlite').as_posix()}")
    assert (folder / "db.sqlite").exists()


# --------------------------------------------------------------------------- gates and overrides


def test_pii_handling_can_be_tightened_never_relaxed() -> None:
    item = ReviewItem(
        item_key="mapping:crm.contacts.email",
        gate=ReviewGate.MAPPING_REVIEW,
        kind="mapping",
        summary="s",
        subject_hash="h",
        options={"allowed_fields": ["email"], "pii_handling": "hash"},
    )

    def decide(override: dict[str, Any]) -> ItemDecision:
        return ItemDecision(item_key=item.item_key, decision=ReviewDecision.APPROVE_WITH_OVERRIDE, override=override)

    approvals._validate_override(item, decide({"pii_handling": "exclude"}))
    for relaxed in ({"pii_handling": None},):
        with pytest.raises(PolicyViolation):
            approvals._validate_override(item, decide(relaxed))
    strict = item.model_copy(update={"options": {"allowed_fields": ["email"], "pii_handling": "exclude"}})
    with pytest.raises(PolicyViolation):
        approvals._validate_override(strict, decide({"pii_handling": "hash"}))


async def test_test_gate_fails_closed_without_named_failures(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_build(ctx: Any, bundle: Any, resolved: Any, fingerprint: str) -> TestReport:
        return TestReport(
            manifest_hash=bundle.manifest_hash,
            source_fingerprint=fingerprint,
            passed=False,
            dbt_exit_code=2,
            dbt_results=[],
            reconciliation=[],
            failing_checks=[],
            duration_seconds=0.0,
        )

    monkeypatch.setattr(sandbox, "build_and_test", broken_build)
    svc = make_service(tmp_path)
    run = await svc.start_run(AGENT, "fixture:portco_a")
    svc.submit_review(
        REVIEWER,
        run.run_id,
        decide_all(run.pending_items),
        subject_hash=run.pending_items[0].subject_hash,
        gate=ReviewGate(run.gate),
    )
    run = await svc.resume(AGENT, run.run_id)
    assert run.status is RunStatus.NEEDS_REVIEW and run.gate == "test_failures"
    assert [i.item_key for i in run.pending_items] == ["test:dbt_exit_2"]


# --------------------------------------------------------------------------- MCP accounting


async def test_mcp_calls_and_evidence_reads_are_audited(tmp_path: Path, fixtures_dir: Path) -> None:
    from mcp import Client

    from tests.test_mcp import Harness, call

    h = Harness(make_service(tmp_path))
    async with Client(h.server) as c:
        err, run = await call(c, "start_onboarding_run", connection_id="fixture:portco_a")
        assert not err
        await call(c, "get_run_status", run_id=run["run_id"])
        from uuid import UUID

        finding = next(f for f in h.svc.findings(AGENT, UUID(run["run_id"])) if f.evidence)
        await c.read_resource(f"evidence://{finding.evidence[0].source_id}")
    events, ok = h.svc.audit(ADMIN, UUID(run["run_id"]))
    tools = [e.payload["tool"] for e in events if e.event_type == "mcp_tool_called"]
    assert ok and tools == ["start_onboarding_run", "get_run_status"]
    assert [e.event_type for e in events].count("evidence_read") == 1
    assert "run_metrics_recorded" in [e.event_type for e in events]
    from src.run_metrics import compute_run_metrics

    m = compute_run_metrics(h.svc, ADMIN, UUID(run["run_id"]))
    assert m["mcp_tool_calls"] == 2 and m["evidence_reads"] == 1 and m["evidence_cited"] > 0
