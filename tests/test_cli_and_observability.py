"""CLI (POD-407) and observability (POD-706, 803, 804, 805)."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
import structlog
import yaml
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from typer.testing import CliRunner

from src import observability
from src.cli import app
from src.run_metrics import compute_run_metrics
from src.settings import get_settings
from tests.conftest import ADMIN, CompletedRun

runner = CliRunner()


@pytest.fixture
def cli_env(tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PORTCO_VAR_ROOT", str(tmp_path))
    monkeypatch.setenv("PORTCO_FIXTURES_ROOT", str(fixtures_dir))
    monkeypatch.setenv("PORTCO_LOG_LEVEL", "WARNING")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _run_id(output: str) -> str:
    m = re.search(r"run ([0-9a-f-]{36})", output)
    assert m, output
    return m.group(1)


@pytest.mark.integration
@pytest.mark.slow
def test_cli_review_loop(cli_env: Path) -> None:
    res = runner.invoke(app, ["run", "--fixture", "portco_a"])
    assert res.exit_code == 0, res.output
    assert "status=needs_review" in res.output and "gate=mapping_review" in res.output
    rid = _run_id(res.output)

    res = runner.invoke(app, ["status", rid])
    assert res.exit_code == 0 and "schema_profiling" in res.output and "[review]" in res.output

    review = cli_env / "review.yaml"
    assert runner.invoke(app, ["review", rid, "--export", str(review)]).exit_code == 0
    doc = yaml.safe_load(review.read_text(encoding="utf-8"))
    for item in doc["items"]:
        if item["item_key"] == "mapping:crm.opportunities.rev":
            item["decision"], item["override"] = "approve_with_override", {"canonical_field": "amount"}
    review.write_text(yaml.safe_dump(doc), encoding="utf-8")

    res = runner.invoke(app, ["review", rid, "--import", str(review), "--reviewer", "agent:cli"])
    assert res.exit_code == 2 and "FORBIDDEN" in res.output  # the run was started by agent:cli

    res = runner.invoke(app, ["review", rid, "--import", str(review), "--reviewer", "alice", "--default", "approve"])
    assert res.exit_code == 0, res.output

    res = runner.invoke(app, ["resume", rid])
    assert res.exit_code == 0 and "gate=certification" in res.output, res.output

    res = runner.invoke(app, ["audit", rid, "--verify"])
    assert res.exit_code == 0 and "intact" in res.output
    res = runner.invoke(app, ["findings", rid])
    assert "ARTIFACTS_GENERATED" in res.output
    out = cli_env / "report.md"
    assert runner.invoke(app, ["report", rid, "--out", str(out)]).exit_code == 0
    assert "## Sandbox tests" in out.read_text(encoding="utf-8")


def test_cli_reports_domain_errors(cli_env: Path) -> None:
    res = runner.invoke(app, ["run", "--fixture", "does_not_exist"])
    assert res.exit_code == 2 and "NOT_FOUND" in res.output


# --------------------------------------------------------------------------- observability


def test_redaction_processor_drops_secrets_and_pii() -> None:
    event = observability.redact(None, "info", {"event": "x", "api_key": "sk-123", "note": "mail a@b.io", "ok": "fine"})
    assert event["api_key"] == "[REDACTED]" and event["note"] == "[REDACTED:PII]" and event["ok"] == "fine"


def test_logs_go_to_stderr_never_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    observability.configure_logging("INFO")
    structlog.get_logger("t").info("hello", anthropic_api_key="sk-live-abc")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sk-live-abc" not in captured.err


def test_secret_settings_are_never_rendered() -> None:
    from pydantic import SecretStr

    from src.settings import Settings

    s = Settings(anthropic_api_key=SecretStr("sk-live-abc"))
    assert "sk-live-abc" not in repr(s) and "sk-live-abc" not in s.model_dump_json()


@pytest.mark.anyio
async def test_span_tree_for_a_run(tmp_path: Path, fixtures_dir: Path) -> None:
    from tests.conftest import AGENT, make_service

    exporter = InMemorySpanExporter()
    observability.configure_tracing(exporter)
    try:
        svc = make_service(tmp_path)
        run = await svc.start_run(AGENT, "fixture:portco_a")
        spans = [s for s in exporter.get_finished_spans() if s.name == "workflow.step"]
        steps = [s.attributes["step"] for s in spans]
        assert steps[:6] == [
            "connection_validation",
            "schema_profiling",
            "entity_inference",
            "join_inference",
            "canonical_mapping",
            "mapping_review",
        ]
        assert all(s.attributes["run_id"] == str(run.run_id) for s in spans)
    finally:
        observability.configure_tracing()


@pytest.mark.slow
def test_run_metrics(completed_a: CompletedRun) -> None:
    m = compute_run_metrics(completed_a.service, ADMIN, completed_a.run_id)
    from src.domain.models import StepName

    proposals = completed_a.service.artifact(ADMIN, completed_a.run_id, StepName.CANONICAL_MAPPING)
    original = next(p for p in proposals.proposals if p.mapping_key == "crm.opportunities.rev")
    # The demo review explicitly selects `amount`, which is already the proposal.
    # Count actual changes, not an approve_with_override label on a no-op decision.
    assert original.canonical_field == "amount"
    assert m["outcome"] == "complete" and m["overrides"] == 0 and m["human_changed_recommendation"] == 0
    assert m["steps"]["automated_tests"]["attempts"] >= 1 and m["evidence_cited"] > 10
    assert m["llm"]["calls"] == 0  # deterministic path
    json.dumps(m)


def test_stringio_is_unused() -> None:
    assert io.StringIO().getvalue() == ""
