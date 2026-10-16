import contextlib
import io
import json
import logging
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

sys.path.insert(
    0, str(next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()))
)

import anyio
from mcp import Client
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src import observability
from src.domain.models import Principal, Role
from src.mcp_server import build_server
from src.settings import Settings
from src.workflows.facade import OnboardingService

SENTINEL = "audit-only@example.invalid"


async def main():
    exporter = InMemorySpanExporter()
    provider = observability.configure_tracing(exporter)
    try:
        with observability.span("audit.exception"):
            raise ValueError(SENTINEL)
    except ValueError:
        pass
    spans = exporter.get_finished_spans()
    trace = spans[0]
    print(
        json.dumps(
            {
                "trace_exception_event_contains_sentinel": any(
                    SENTINEL in str(event.attributes) for event in trace.events
                ),
                "trace_status_contains_sentinel": SENTINEL in str(trace.status.description),
            }
        )
    )

    with tempfile.TemporaryDirectory(prefix="portco-security-audit-") as temp:
        root = Path(temp)
        settings = Settings(
            _env_file=None, env="test", var_root=root, fixtures_root=root / "fixtures", log_level="INFO"
        )
        capture = io.StringIO()
        for handler in logging.getLogger().handlers[:]:
            logging.getLogger().removeHandler(handler)
        observability._configured = False
        with contextlib.redirect_stderr(capture):
            service = OnboardingService.build(settings)
            principal = Principal(principal_id="audit-agent", role=Role.AGENT, company_ids=("portco_a",))
            server = build_server(settings, service=service, principal=lambda: principal, with_auth=False)

            def fail(*args, **kwargs):
                raise RuntimeError("synthetic database exception: " + SENTINEL)

            service.artifact = fail
            resource_error = ""
            async with Client(server) as client:
                try:
                    await client.read_resource(f"run://{uuid4()}/profile")
                except Exception as exc:
                    resource_error = str(exc)
                with service.store.tx() as tx:
                    run = tx.runs.create(company_id="portco_a", connection_id="audit", requested_by="audit-agent")
                service.artifact = lambda *args, **kwargs: {"value": SENTINEL}
                guard_rejected = False
                try:
                    await client.read_resource(f"run://{run.run_id}/profile")
                except Exception as exc:
                    guard_rejected = "PII guard" in str(exc)
                with service.store.tx() as tx:
                    guard_audits = sum(e.event_type == "pii_guard_blocked" for e in tx.audit.list(run.run_id))
            denied = ""
            path = settings.fixtures_dir / "portco_b.duckdb"
            before = path.exists()
            try:
                await service.start_run(principal, "fixture:portco_b")
            except Exception as exc:
                denied = type(exc).__name__
            after = path.exists()
            service.store.engine.dispose()
        print(
            json.dumps(
                {
                    "unexpected_resource_exception_logs_raw_sentinel": SENTINEL in capture.getvalue(),
                    "resource_error_response_contains_sentinel": SENTINEL in resource_error,
                    "pii_resource_rejected": guard_rejected,
                    "pii_resource_block_audit_count": guard_audits,
                    "unauthorized_fixture_existed_before": before,
                    "unauthorized_fixture_exists_after": after,
                    "unauthorized_request_result": denied,
                }
            )
        )
    provider.shutdown()


anyio.run(main)
