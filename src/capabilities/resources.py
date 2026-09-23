"""MCP resources and resource templates (POD-504). Every run-scoped read is tenant-checked."""

import json
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError

from src.capabilities.common import ServerState, parse_uuid
from src.domain.errors import DomainError, NotFound
from src.domain.models import StepName
from src.domain.ontology import load_ontology
from src.domain.policies import render_policies


def _dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=1, sort_keys=True, default=str)


def _guarded(fn: Any) -> Any:
    try:
        return fn()
    except NotFound as exc:
        raise ResourceNotFoundError(exc.message) from exc
    except DomainError as exc:
        raise ResourceError(f"{exc.code.value}: {exc.message}") from exc


def register(mcp: MCPServer, state: ServerState) -> None:
    @mcp.resource("project://policies", mime_type="text/markdown")
    def policies() -> str:
        """Operating and safety policies, rendered from the enforced policy registry."""
        return render_policies()

    @mcp.resource("ontology://pe/v1", mime_type="application/json")
    def ontology() -> str:
        """The canonical PE ontology: entities, fields, synonyms, relationships and metrics."""
        return _dump(load_ontology().as_resource())

    @mcp.resource("ontology://pe/v1/metrics/{metric}", mime_type="application/json")
    def ontology_metric(metric: str) -> str:
        """One metric definition: formula, grain, required fields and PE pitfalls."""
        ont = load_ontology()
        if metric not in ont.metrics:
            raise ResourceNotFoundError(f"unknown metric {metric!r}")
        return _dump({"metric": metric, **ont.metrics[metric].model_dump(mode="json")})

    def run_step(run_id: str, step: StepName) -> str:
        return _guarded(lambda: _dump(state.svc().artifact(state.principal(), parse_uuid(run_id, "run_id"), step)))

    @mcp.resource("run://{run_id}/summary", mime_type="application/json")
    def run_summary_res(run_id: str) -> str:
        """Run state, steps, gate and pending items."""
        from src.capabilities.summaries import run_summary

        def build() -> str:
            svc, principal = state.svc(), state.principal()
            return _dump(run_summary(svc, principal, svc.get_run(principal, parse_uuid(run_id, "run_id"))))

        return _guarded(build)

    @mcp.resource("run://{run_id}/profile", mime_type="application/json")
    def run_profile(run_id: str) -> str:
        """Aggregate schema profile (no row values). Flagged source comments are never included."""
        return run_step(run_id, StepName.SCHEMA_PROFILING)

    @mcp.resource("run://{run_id}/entities", mime_type="application/json")
    def run_entities(run_id: str) -> str:
        """Entity inference with feature breakdowns and primary keys."""
        return run_step(run_id, StepName.ENTITY_INFERENCE)

    @mcp.resource("run://{run_id}/joins", mime_type="application/json")
    def run_joins(run_id: str) -> str:
        """Inferred joins with containment and orphan rates."""
        return run_step(run_id, StepName.JOIN_INFERENCE)

    @mcp.resource("run://{run_id}/mapping", mime_type="application/json")
    def run_mapping(run_id: str) -> str:
        """Mapping proposals with scores, alternatives and review reason codes."""
        return run_step(run_id, StepName.CANONICAL_MAPPING)

    @mcp.resource("run://{run_id}/resolved-mapping", mime_type="application/json")
    def run_resolved(run_id: str) -> str:
        """The reviewed mapping that artifact generation is allowed to use."""
        return run_step(run_id, StepName.MAPPING_REVIEW)

    @mcp.resource("run://{run_id}/test-report", mime_type="application/json")
    def run_tests(run_id: str) -> str:
        """Sandbox dbt results and reconciliation checks."""
        return run_step(run_id, StepName.AUTOMATED_TESTS)

    @mcp.resource("run://{run_id}/certification-packet", mime_type="application/json")
    def run_packet(run_id: str) -> str:
        """Everything a reviewer certifies: joins, mapping summary, metrics, tests, open findings."""
        return run_step(run_id, StepName.HUMAN_CERTIFICATION)

    @mcp.resource("run://{run_id}/findings", mime_type="application/json")
    def run_findings(run_id: str) -> str:
        """Current findings with evidence references, separated by finding type."""
        return _guarded(
            lambda: _dump(
                [
                    f.model_dump(mode="json")
                    for f in state.svc().findings(state.principal(), parse_uuid(run_id, "run_id"))
                ]
            )
        )

    @mcp.resource("run://{run_id}/audit", mime_type="application/json")
    def run_audit(run_id: str) -> str:
        """Append-only, hash-chained audit log and its verification status."""

        def build() -> str:
            events, ok = state.svc().audit(state.principal(), parse_uuid(run_id, "run_id"))
            return _dump({"chain_intact": ok, "events": [e.model_dump(mode="json") for e in events]})

        return _guarded(build)

    @mcp.resource("run://{run_id}/metrics", mime_type="application/json")
    def run_metrics(run_id: str) -> str:
        """Per-run latency, attempts, tool/model usage and human overrides (POD-805)."""
        from src.run_metrics import compute_run_metrics

        return _guarded(
            lambda: _dump(compute_run_metrics(state.svc(), state.principal(), parse_uuid(run_id, "run_id")))
        )

    @mcp.resource("run://{run_id}/artifacts/{+path}", mime_type="text/plain")
    def run_artifact(run_id: str, path: str) -> str:
        """One generated dbt / semantic-layer file."""
        return _guarded(lambda: state.svc().bundle_file(state.principal(), parse_uuid(run_id, "run_id"), path))

    @mcp.resource("evidence://{evidence_id}", mime_type="application/json")
    def evidence(evidence_id: str) -> str:
        """An evidence record: source URI, content hash and aggregate payload."""
        return _guarded(lambda: _dump(state.svc().evidence(state.principal(), parse_uuid(evidence_id, "evidence_id"))))

    @mcp.resource("finding://{finding_id}/lineage", mime_type="application/json")
    def lineage(finding_id: str) -> str:
        """Provenance tree from a finding down to source reads."""
        return _guarded(lambda: _dump(state.svc().lineage(state.principal(), parse_uuid(finding_id, "finding_id"))))
