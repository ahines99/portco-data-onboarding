"""Step 1 — connection validation (POD-301)."""

from __future__ import annotations

from src.domain.errors import PolicyViolation
from src.domain.models import Confidence, Finding
from src.domain.project_models import ConnectionCheck
from src.workflows.contracts import StepContext, StepResult, make_evidence


def validate_connection(ctx: StepContext) -> StepResult:
    adapter = ctx.adapter()
    probe = adapter.probe()
    read_only = adapter.verify_read_only()
    tables = sum(len(adapter.list_tables(s)) for s in probe.schemas)
    fingerprint = adapter.fingerprint()
    payload = {
        "reachable": probe.reachable,
        "read_only_verified": read_only,
        "schemas": probe.schemas,
        "tables": tables,
        "engine_version": probe.engine_version,
        "source_fingerprint": fingerprint,
    }
    spec = adapter.spec
    ev = make_evidence(ctx, f"duckdb://{spec.company_id}#probe=connection", "connection_probe", payload, spec.as_of)
    if not read_only:
        # Terminal: we refuse to onboard with a credential that can write to the source.
        raise PolicyViolation(
            "connection is write-capable; onboarding requires a read-only credential", evidence_id=str(ev.evidence_id)
        )
    check = ConnectionCheck(
        connection_id=spec.connection_id,
        company_id=spec.company_id,
        reachable=True,
        read_only_verified=True,
        schemas_visible=probe.schemas,
        tables_visible=tables,
        source_fingerprint=fingerprint,
        engine_version=probe.engine_version,
        evidence_id=ev.evidence_id,
    )
    finding = Finding(
        code="CONNECTION_VERIFIED",
        title="Read-only connection verified",
        statement=f"{len(probe.schemas)} schemas and {tables} tables visible; write probe was rejected.",
        confidence=Confidence.HIGH,
        evidence=[ev.ref()],
    )
    return StepResult(
        output=check,
        evidence=[ev],
        findings=[finding],
        audit=[("connection_checked", {"schemas": len(probe.schemas), "tables": tables})],
    )
