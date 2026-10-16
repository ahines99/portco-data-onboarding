"""Verify actual OTLP HTTP export to a local collector, never an external endpoint."""

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

import pytest

from src import observability

EMAIL = "otlp-sentinel@example.invalid"
CARD = "4929000073377335"  # synthetic, Luhn-valid
DSN_PASSWORD = "Otlp-DSN-pw-5521"
DSN = f"postgresql+psycopg://svc:{DSN_PASSWORD}@db.internal.invalid/app"
SENTINELS = (EMAIL, CARD, DSN_PASSWORD, DSN)


@contextmanager
def local_collector(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[bytes]]:
    """A localhost OTLP/HTTP collector and the configured exporter pointing at it; yields raw payloads."""
    received: list[bytes] = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            assert self.path == "/v1/traces"
            received.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    collector = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    thread = Thread(target=collector.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{collector.server_port}"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", endpoint + "/v1/traces")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_COMPRESSION", "none")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_COMPRESSION", "none")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", raising=False)
    previous = observability._provider
    try:
        yield received
    finally:
        if observability._provider is not None and observability._provider is not previous:
            observability._provider.shutdown()
        observability._provider = previous
        collector.shutdown()
        collector.server_close()
        thread.join(timeout=5)


def decoded_spans(received: list[bytes]) -> list[Any]:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    requests = [ExportTraceServiceRequest.FromString(body) for body in received]
    return [s for req in requests for r in req.resource_spans for scope in r.scope_spans for s in scope.spans]


def test_configured_exporter_sends_a_real_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    with local_collector(monkeypatch) as received:
        provider = observability.configure_tracing()
        with observability.span("otlp.local.test", outcome="verified"):
            pass
        assert provider.force_flush()
        assert received
        spans = decoded_spans(received)
        assert [s.name for s in spans] == ["otlp.local.test"]
        assert any(a.key == "outcome" and a.value.string_value == "verified" for a in spans[0].attributes)


def test_failure_trace_reaches_the_collector_without_raw_sentinels(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC-01: decode the actual exported protobuf; errors stay countable, sentinels never leave the process."""
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    from google.protobuf.json_format import MessageToJson

    from src.domain.pii_guard import PiiGuard

    with local_collector(monkeypatch) as received:
        provider = observability.configure_tracing()
        with observability.span("otlp.parent", principal=EMAIL):
            for attempt in (1, 2):
                with (
                    pytest.raises(RuntimeError),
                    observability.span("otlp.failing", attempt=attempt, note=f"card {CARD}") as sp,
                ):
                    sp.add_event("driver.retry", {"detail": DSN})
                    try:
                        raise ConnectionError(DSN)
                    except ConnectionError as cause:
                        raise RuntimeError(f"failed for {EMAIL} card {CARD} via {DSN}") from cause
        assert provider.force_flush()
        assert received
        raw = b"".join(received)
        spans = decoded_spans(received)
        decoded = "\n".join(MessageToJson(s) for s in spans)

    for sentinel in SENTINELS:  # exact bytes, independent of the PII classifier
        assert sentinel.encode() not in raw and sentinel not in decoded, sentinel
    # The classifier over every text field (not timestamps/ids, whose long digit runs can look Luhn-valid).
    texts = [
        text
        for s in spans
        for text in (
            s.name,
            s.status.message,
            *(a.value.string_value for a in s.attributes),
            *(e.name for e in s.events),
            *(a.value.string_value for e in s.events for a in e.attributes),
        )
    ]
    assert PiiGuard().scan(texts) == []
    failing = [s for s in spans if s.name == "otlp.failing"]
    assert len(failing) == 2  # error count is preserved
    for s in failing:
        attrs = {a.key: a.value for a in s.attributes}
        assert s.status.code == s.status.STATUS_CODE_ERROR and s.status.message == "RuntimeError"
        assert attrs["error.type"].string_value == "RuntimeError"
        assert [e.name for e in s.events] == ["driver.retry", "exception"]
        assert s.trace_id == next(p for p in spans if p.name == "otlp.parent").trace_id  # correlation survives
