"""Structured logging and tracing (POD-803, POD-804, POD-706).

Logs go to stderr as JSON: stdout is reserved for the stdio MCP transport. A redaction
processor drops secret-looking keys and blocks raw PII detected by the PII guard.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter

from src.domain.pii_guard import SECRET as SECRET_VALUE
from src.domain.pii_guard import PiiGuard, mask

SECRET_KEY = re.compile(r"(key|token|secret|password|authorization)", re.I)
_GUARD = PiiGuard()
_configured = False


TRACEBACK_KEYS = frozenset({"exception", "exc_info", "stack"})


def _clean(key: str, value: Any) -> Any:
    if SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        if key in TRACEBACK_KEYS:  # keep the traceback useful: mask only the offending values
            return mask(value, _GUARD.canaries)
        return "[REDACTED:PII]" if _GUARD.scan_text(value) or SECRET_VALUE.search(value) else value
    if isinstance(value, dict):
        return {k: _clean(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(key, v) for v in value]
    return value


def redact(_logger: Any, _name: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Runs after `format_exc_info`, so rendered tracebacks are scanned too; recurses into nested values."""
    for k in list(event):
        event[k] = _clean(k, event[k])
    return event


class _StderrLogger:
    """Resolves sys.stderr on every write, so redirected or replaced streams are always honoured."""

    def msg(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    log = debug = info = warning = warn = error = critical = exception = fatal = msg


def _stderr_logger(*_args: Any) -> _StderrLogger:
    return _StderrLogger()


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(stream=sys.stderr, level=numeric, format="%(message)s")
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            redact,  # after format_exc_info: tracebacks are strings by now and get masked
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=_stderr_logger,
        cache_logger_on_first_use=True,
    )
    _configured = True


# --------------------------------------------------------------------------- tracing

_provider: TracerProvider | None = None


def configure_tracing(exporter: SpanExporter | None = None) -> TracerProvider:
    """Install a tracer provider. Tests pass an in-memory exporter; OTLP is used when configured."""
    global _provider
    provider = TracerProvider(resource=Resource.create({"service.name": "portco-data-onboarding"}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        import os

        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

                provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
            except ImportError as exc:
                raise RuntimeError("OTLP export is configured; install the telemetry extra to enable it") from exc
    _provider = provider
    return provider


def tracer() -> trace.Tracer:
    if _provider is None:
        configure_tracing()
    assert _provider is not None
    return _provider.get_tracer("portco")


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    with tracer().start_as_current_span(name) as sp:
        for k, v in attributes.items():
            if v is not None:
                sp.set_attribute(k, v if isinstance(v, str | int | float | bool) else str(v))
        yield sp
