"""Verify actual OTLP HTTP export to a local collector, never an external endpoint."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from src import observability


def test_configured_exporter_sends_a_real_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

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
    provider = None
    try:
        provider = observability.configure_tracing()
        with observability.span("otlp.local.test", outcome="verified"):
            pass
        assert provider.force_flush()
        assert received
        request = ExportTraceServiceRequest.FromString(received[0])
        spans = [s for r in request.resource_spans for scope in r.scope_spans for s in scope.spans]
        assert [s.name for s in spans] == ["otlp.local.test"]
        assert any(a.key == "outcome" and a.value.string_value == "verified" for a in spans[0].attributes)
    finally:
        if provider is not None:
            provider.shutdown()
        observability._provider = previous
        collector.shutdown()
        collector.server_close()
        thread.join(timeout=5)
