"""Failure telemetry never carries raw PII or credentials (audit A06 / SEC-01, SEC-02, SEC-04; T2).

Every sink is checked with exact sentinel bytes *and* the PII guard, so a defect shared by the redactor and
the classifier cannot hide a leak: span attributes, events and status (in memory and decoded OTLP lives in
tests/test_otlp_export.py), standard-library logging through handlers installed by others, structlog/stderr,
and the MCP response a client receives.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from mcp import Client
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

from src import observability
from src.domain.models import Principal, Role, StepName
from src.domain.pii_guard import PiiGuard
from src.mcp_server import build_server
from src.workflows.facade import OnboardingService
from tests.conftest import make_service

pytestmark = [pytest.mark.security, pytest.mark.anyio]

EMAIL = "telemetry-sentinel@example.invalid"
CARD = "4929000073377335"  # synthetic, Luhn-valid
DSN_PASSWORD = "Sentinel-DSN-pw-7731"
DSN = f"postgresql://svc_user:{DSN_PASSWORD}@db.internal.invalid:5432/app"
SENTINELS = (EMAIL, CARD, DSN_PASSWORD, DSN)
SECRET_TEXT = f"driver failure for {EMAIL} card {CARD} via {DSN}"
AGENT_A = Principal(principal_id="agent:telemetry", role=Role.AGENT, company_ids=("portco_a",))


def leaks(text: str) -> list[str]:
    """Exact sentinel bytes present in `text`, plus anything the PII guard still classifies as PII."""
    exact = [s for s in SENTINELS if s in text]
    return exact + [v.kind for v in PiiGuard().scan_text(text)]


def span_text(spans: Any) -> str:
    return "\n".join(s.to_json() for s in spans)


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    previous = observability._provider
    memory = InMemorySpanExporter()
    observability.configure_tracing(memory)
    try:
        yield memory
    finally:
        observability._provider = previous


@pytest.fixture
def third_party_handler() -> Iterator[io.StringIO]:
    """A plain handler installed on the root logger after our configuration, as a dependency would."""
    observability.configure_logging("INFO")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


# --------------------------------------------------------------------------- traces (SEC-01)


def test_span_failure_exports_error_type_but_no_exception_text(exporter: InMemorySpanExporter) -> None:
    with pytest.raises(ValueError), observability.span("audit.exception", run_id="r-1"):
        try:
            raise KeyError(EMAIL)
        except KeyError as cause:
            raise ValueError(SECRET_TEXT) from cause
    (sp,) = exporter.get_finished_spans()
    assert leaks(span_text([sp])) == []
    assert sp.status.status_code is StatusCode.ERROR and sp.status.description == "ValueError"
    assert sp.attributes is not None and sp.attributes["error.type"] == "ValueError"
    assert [(e.name, dict(e.attributes or {})) for e in sp.events] == [
        ("exception", {"exception.type": "builtins.ValueError"})
    ]


def test_domain_errors_keep_their_code_in_the_span_status(exporter: InMemorySpanExporter) -> None:
    from src.domain.errors import PolicyViolation

    with pytest.raises(PolicyViolation), observability.span("audit.domain"):
        raise PolicyViolation(f"refused {EMAIL}")
    (sp,) = exporter.get_finished_spans()
    assert sp.status.description == "PolicyViolation:POLICY_VIOLATION" and leaks(span_text([sp])) == []


def test_export_boundary_masks_caller_supplied_attributes_events_and_status(exporter: InMemorySpanExporter) -> None:
    with observability.span("audit.attrs", principal=EMAIL, rows=12) as sp:
        sp.set_attribute("note", SECRET_TEXT)
        sp.set_attribute("values", [EMAIL, "fine"])
        sp.set_attribute("db_password", "plain-but-secret")
        sp.add_event("driver.retry", {"detail": DSN, "attempt": 2})
        sp.set_status(Status(StatusCode.ERROR, SECRET_TEXT))
    (exported,) = exporter.get_finished_spans()
    assert isinstance(exported, ReadableSpan)
    text = span_text([exported])
    assert leaks(text) == [] and "plain-but-secret" not in text
    attrs = dict(exported.attributes or {})
    assert attrs["rows"] == 12 and attrs["values"] == ("[PII]", "fine") and attrs["db_password"] == "[REDACTED]"
    assert exported.events[0].attributes is not None and exported.events[0].attributes["attempt"] == 2


# --------------------------------------------------------------------------- standard logging (SEC-02)


def test_stdlib_exception_logs_are_redacted_on_handlers_installed_by_others(
    third_party_handler: io.StringIO, capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        try:
            raise ConnectionError(DSN)
        except ConnectionError as cause:
            raise RuntimeError(SECRET_TEXT) from cause
    except RuntimeError:
        logging.getLogger("portco.test.dependency").warning("snapshot failed for %s", EMAIL, exc_info=True)
    logging.getLogger("portco.test.dependency").error("bad value %r", {"contact": EMAIL}, stack_info=True)
    out = third_party_handler.getvalue() + capsys.readouterr().err
    assert leaks(out) == [], out
    # Still useful to an operator: the exception types and the traceback frames survive.
    assert "RuntimeError" in out and "ConnectionError" in out and "Traceback" in out


def test_redacting_filter_masks_extra_fields_added_after_record_creation() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s contact=%(contact)s auth=%(auth_token)s n=%(n)s"))
    handler.addFilter(observability.RedactingFilter())
    logger = logging.getLogger("portco.test.extra")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        logger.warning("request", extra={"contact": EMAIL, "auth_token": "opaque-value-1", "n": 3})
    finally:
        logger.removeHandler(handler)
        logger.propagate = True
    out = stream.getvalue()
    assert leaks(out) == [] and "opaque-value-1" not in out and "n=3" in out, out


def test_logging_redaction_does_not_depend_on_basic_config(capsys: pytest.CaptureFixture[str]) -> None:
    """Rich (as installed by the MCP SDK) renders tracebacks itself; it only ever sees masked records."""
    from rich.console import Console
    from rich.logging import RichHandler

    handler = RichHandler(console=Console(stderr=True), rich_tracebacks=True)
    logger = logging.getLogger("portco.test.rich")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        try:
            raise RuntimeError(SECRET_TEXT)
        except RuntimeError:
            logger.exception("unexpected failure")
    finally:
        logger.removeHandler(handler)
        logger.propagate = True
    err = capsys.readouterr().err
    assert "unexpected failure" in err and leaks(err) == [], err


# --------------------------------------------------------------------------- MCP resources (SEC-02, SEC-04)


def _server(svc: OnboardingService, who: Principal = AGENT_A) -> Any:
    return build_server(svc.settings, service=svc, principal=lambda: who, with_auth=False)


async def test_unexpected_resource_failure_is_redacted_in_logs_and_response(
    tmp_path: Path,
    fixtures_dir: Path,
    third_party_handler: io.StringIO,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = make_service(tmp_path)

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("synthetic database exception: " + SECRET_TEXT)

    monkeypatch.setattr(svc, "artifact", fail)
    # An unguarded resource reaches the SDK's own `logger.exception` path (Rich handler on the root logger).
    monkeypatch.setattr("src.capabilities.resources.load_ontology", fail)
    errors: list[str] = []
    async with Client(_server(svc)) as client:
        for uri in (f"run://{uuid4()}/profile", "ontology://pe/v1"):
            with pytest.raises(Exception) as caught:
                await client.read_resource(uri)
            errors.append(str(caught.value))
    logs = third_party_handler.getvalue() + capsys.readouterr().err
    assert leaks("\n".join(errors)) == [] and leaks(logs) == [], logs
    assert "correlation id" in errors[0]  # the client gets a correlation id, not the driver text
    assert "RuntimeError" in logs  # the failure itself is still visible to operators


async def test_blocked_resource_read_is_audited_exactly_once(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = make_service(tmp_path)
    with svc.store.tx() as tx:
        own = tx.runs.create(company_id="portco_a", connection_id="audit", requested_by=AGENT_A.principal_id)
        foreign = tx.runs.create(company_id="portco_b", connection_id="audit", requested_by="agent:other")
        foreign_before = [e.event_hash for e in tx.audit.list(foreign.run_id)]
    monkeypatch.setattr(svc, "artifact", lambda *_a, **_k: {"value": EMAIL})
    async with Client(_server(svc)) as client:
        for run_id in (own.run_id, foreign.run_id):
            with pytest.raises(Exception, match="PII guard"):
                await client.read_resource(f"run://{run_id}/profile")
    with svc.store.tx() as tx:
        own_events = [e for e in tx.audit.list(own.run_id) if e.event_type == "pii_guard_blocked"]
        foreign_after = [e.event_hash for e in tx.audit.list(foreign.run_id)]
    assert len(own_events) == 1
    assert own_events[0].payload == {"method": "resources/read", "kinds": ["email"]}
    assert own_events[0].actor == AGENT_A.principal_id
    assert foreign_after == foreign_before  # never write into another tenant's audit log


async def test_blocked_evidence_and_lineage_reads_are_audited_against_their_run(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = make_service(tmp_path)
    run = await svc.start_run(AGENT_A, "fixture:portco_a", stop_after=StepName.SCHEMA_PROFILING)
    with svc.store.tx() as tx:
        finding = next(f for f in tx.findings.current(run.run_id) if f.evidence)
    evidence_id = finding.evidence[0].source_id
    monkeypatch.setattr(svc, "evidence", lambda *_a, **_k: {"value": EMAIL})
    monkeypatch.setattr(svc, "lineage", lambda *_a, **_k: {"value": EMAIL})

    def blocked() -> int:
        with svc.store.tx() as tx:
            return sum(e.event_type == "pii_guard_blocked" for e in tx.audit.list(run.run_id))

    async with Client(_server(svc)) as client:
        for uri in (f"evidence://{evidence_id}", f"finding://{finding.finding_id}/lineage"):
            before = blocked()
            with pytest.raises(Exception, match="PII guard"):
                await client.read_resource(uri)
            assert blocked() == before + 1, uri


# --------------------------------------------------------------------------- end to end (T2)


async def test_failing_workflow_step_leaves_no_canary_in_any_telemetry_sink(
    tmp_path: Path,
    fixtures_dir: Path,
    exporter: InMemorySpanExporter,
    third_party_handler: io.StringIO,
    capsys: pytest.CaptureFixture[str],
) -> None:
    svc = make_service(tmp_path)

    def crash(_ctx: Any) -> Any:
        try:
            raise LookupError(f"row for {EMAIL}")
        except LookupError as cause:
            raise RuntimeError(SECRET_TEXT) from cause

    idx = next(i for i, s in enumerate(svc.engine.steps) if s.name is StepName.ENTITY_INFERENCE)
    svc.engine.steps = [*svc.engine.steps]
    svc.engine.steps[idx] = replace(svc.engine.steps[idx], fn=crash)
    async with Client(_server(svc)) as client:
        result = await client.call_tool("start_onboarding_run", {"connection_id": "fixture:portco_a"})
        status = json.dumps(result.model_dump(mode="json"))
    captured = capsys.readouterr()
    sinks = {
        "mcp_response": status,
        "stderr": captured.err,
        "stdout": captured.out,
        "standard_logs": third_party_handler.getvalue(),
        "spans": span_text(exporter.get_finished_spans()),
    }
    assert {name: leaks(text) for name, text in sinks.items()} == {name: [] for name in sinks}
    assert "failed" in status
    failed = [s for s in exporter.get_finished_spans() if s.status.status_code is StatusCode.ERROR]
    assert any(s.name == "workflow.step" and (s.attributes or {}).get("error.type") == "RuntimeError" for s in failed)
    assert "RuntimeError" in captured.err  # the crash is logged, just without its data
