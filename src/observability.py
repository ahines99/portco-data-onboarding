"""Structured logging and tracing (POD-803, POD-804, POD-706).

Logs go to stderr as JSON: stdout is reserved for the stdio MCP transport. A redaction
processor drops secret-looking keys and blocks raw PII detected by the PII guard.

Every telemetry sink shares that redaction (audit A06):
- structlog events pass the `redact` processor after tracebacks are rendered;
- standard-library records (the MCP SDK, uvicorn, Alembic, any dependency, whichever handler they
  reach) are masked when they are created, including rendered exception text and stack info;
- spans never record raw exception text, and every exporter is wrapped so attributes, events,
  links and status descriptions are masked before anything leaves the process.
"""

from __future__ import annotations

import logging
import re
import sys
import traceback
from collections.abc import Callable, Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Link, Status, StatusCode

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


def mask_text(text: str) -> str:
    """`text` with detected PII and secret-looking tokens (DSN credentials, API keys) replaced."""
    return mask(text, _GUARD.canaries)


# --------------------------------------------------------------------------- standard-library logging

_REDACTED_MARK = "_portco_redacted"
_STANDARD_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime", _REDACTED_MARK}


def _mask_arg(value: Any) -> Any:
    return mask_text(value) if isinstance(value, str) else value


def sanitize_record(record: logging.LogRecord) -> logging.LogRecord:
    """Mask a standard-library record in place: message, arguments, exception text and stack info.

    The exception is rendered here and kept only as masked `exc_text` (`exc_info` is cleared), so no
    handler or formatter, including Rich tracebacks, can re-render the raw exception message later.
    """
    if getattr(record, _REDACTED_MARK, False):
        return record
    if isinstance(record.msg, str):
        record.msg = mask_text(record.msg)
    if isinstance(record.args, Mapping):
        record.args = {k: _mask_arg(v) for k, v in record.args.items()}
    elif isinstance(record.args, tuple):
        record.args = tuple(_mask_arg(a) for a in record.args)
    try:
        rendered = record.getMessage()
        if mask_text(rendered) != rendered:  # PII inside a non-string argument (an exception, a dict, ...)
            record.msg, record.args = mask_text(rendered), ()
    except Exception:  # a malformed format call: never let the handler echo the raw arguments
        record.msg, record.args = mask_text(str(record.msg)) + " [unformattable log arguments omitted]", ()
    if record.exc_info and record.exc_info[1] is not None:
        record.exc_text = mask_text("".join(traceback.format_exception(*record.exc_info)).rstrip("\n"))
        record.exc_info = None
    elif record.exc_text:
        record.exc_text = mask_text(record.exc_text)
    if record.stack_info:
        record.stack_info = mask_text(record.stack_info)
    setattr(record, _REDACTED_MARK, True)
    return record


class RedactingFilter(logging.Filter):
    """Handler filter: masks records (and `extra=` values added after record creation) before output."""

    def filter(self, record: logging.LogRecord) -> bool:
        sanitize_record(record)
        for key, value in list(record.__dict__.items()):
            if key not in _STANDARD_RECORD_KEYS:
                record.__dict__[key] = _clean_extra(key, value)
        return True


def _clean_extra(key: str, value: Any) -> Any:
    if isinstance(value, str):
        return "[REDACTED]" if SECRET_KEY.search(key) else mask_text(value)
    if isinstance(value, Mapping | list | tuple):  # keep the structure unless it actually holds PII
        rendered = str(value)
        return mask_text(rendered) if mask_text(rendered) != rendered else value
    return value


_base_factory: Callable[..., logging.LogRecord] | None = None


def _redacting_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    assert _base_factory is not None
    return sanitize_record(_base_factory(*args, **kwargs))


def install_log_redaction() -> None:
    """Mask every standard-library record at creation, whichever logger or handler it reaches.

    Handlers installed later by uvicorn, the MCP SDK (`logging.basicConfig` with Rich) or any
    dependency are covered too: they only ever see records produced by this factory. Idempotent.
    """
    global _base_factory
    current = logging.getLogRecordFactory()
    if current is _redacting_factory:
        return
    _base_factory = current
    logging.setLogRecordFactory(_redacting_factory)


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Resolves sys.stderr on every record, so redirected or replaced streams are always honoured."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self) -> Any:
        return sys.stderr

    @stream.setter
    def stream(self, _value: Any) -> None:
        pass


class _StderrLogger:
    """Resolves sys.stderr on every write, so redirected or replaced streams are always honoured."""

    def msg(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    log = debug = info = warning = warn = error = critical = exception = fatal = msg


def _stderr_logger(*_args: Any) -> _StderrLogger:
    return _StderrLogger()


def _attach_filters() -> None:
    """Defense in depth on the output handlers that already exist (root, uvicorn, MCP SDK)."""
    for name in (None, "uvicorn", "uvicorn.error", "uvicorn.access", "mcp", "alembic"):
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactingFilter) for f in handler.filters):
                handler.addFilter(RedactingFilter())


def configure_logging(level: str = "INFO") -> None:
    global _configured
    install_log_redaction()
    _attach_filters()
    if _configured:
        return
    numeric = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    # Explicit, not `logging.basicConfig`: that is a no-op once anything else installed a handler.
    if not root.handlers:
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        handler.addFilter(RedactingFilter())
        root.addHandler(handler)
    root.setLevel(numeric)
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


def _clean_attribute(key: str, value: Any) -> Any:
    if isinstance(value, str):
        return "[REDACTED]" if SECRET_KEY.search(key) else mask_text(value)
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return tuple(mask_text(v) if isinstance(v, str) else v for v in value)
    return value


def _clean_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    return {k: _clean_attribute(k, v) for k, v in (attributes or {}).items()}


def sanitize_span(sp: ReadableSpan) -> ReadableSpan:
    """A copy of `sp` whose name, attributes, events, links and status description are masked."""
    status = sp.status
    if status.description:
        status = Status(status.status_code, mask_text(status.description))
    return ReadableSpan(
        name=mask_text(sp.name),
        context=sp.context,
        parent=sp.parent,
        resource=sp.resource,
        attributes=_clean_attributes(sp.attributes),
        events=[Event(mask_text(e.name), _clean_attributes(e.attributes), timestamp=e.timestamp) for e in sp.events],
        links=[Link(link.context, _clean_attributes(link.attributes)) for link in sp.links],
        kind=sp.kind,
        status=status,
        start_time=sp.start_time,
        end_time=sp.end_time,
        instrumentation_scope=sp.instrumentation_scope,
    )


class SanitizingSpanExporter(SpanExporter):
    """The one export boundary: nothing reaches the wrapped exporter (OTLP, in-memory) unmasked."""

    def __init__(self, delegate: SpanExporter) -> None:
        self.delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self.delegate.export([sanitize_span(s) for s in spans])

    def shutdown(self) -> None:
        self.delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.delegate.force_flush(timeout_millis)


def configure_tracing(exporter: SpanExporter | None = None) -> TracerProvider:
    """Install a tracer provider. Tests pass an in-memory exporter; OTLP is used when configured."""
    global _provider
    provider = TracerProvider(resource=Resource.create({"service.name": "portco-data-onboarding"}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(SanitizingSpanExporter(exporter)))
    else:
        import os

        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

                provider.add_span_processor(SimpleSpanProcessor(SanitizingSpanExporter(OTLPSpanExporter())))
            except ImportError as exc:
                raise RuntimeError("OTLP export is configured; install the telemetry extra to enable it") from exc
    _provider = provider
    return provider


def tracer() -> trace.Tracer:
    if _provider is None:
        configure_tracing()
    assert _provider is not None
    return _provider.get_tracer("portco")


def error_type(exc: BaseException) -> str:
    """A safe error label: the exception class, plus the domain error code when there is one."""
    code = getattr(getattr(exc, "code", None), "value", None)
    name = type(exc).__qualname__
    return f"{name}:{code}" if isinstance(code, str) else name


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    # Exception messages and stack traces can carry source values or credentials: never record them.
    with tracer().start_as_current_span(name, record_exception=False, set_status_on_exception=False) as sp:
        for k, v in attributes.items():
            if v is not None:
                sp.set_attribute(k, v if isinstance(v, str | int | float | bool) else str(v))
        try:
            yield sp
        except BaseException as exc:
            label = error_type(exc)
            sp.set_attribute("error.type", label)
            sp.add_event("exception", {"exception.type": f"{type(exc).__module__}.{type(exc).__qualname__}"})
            sp.set_status(Status(StatusCode.ERROR, label))
            raise


install_log_redaction()
