"""MCP tools, grouped by capability module (ADR-0006).

Tools are thin: validate input, resolve the principal, call the facade, return a typed model.
Approvals are never accepted as caller-supplied booleans: `generate_dbt_artifacts` and
`publish_run` take an approval id that the server looks up and binds to current content
(ADR-0004), and only reviewer principals can create approvals (ADR-0009).
"""

from typing import Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from src.capabilities.common import ServerState, parse_uuid, tool_errors
from src.capabilities.schemas import (
    ApprovalResult,
    ArtifactBundleSummary,
    CheckOut,
    DecisionIn,
    Health,
    MappingSetSummary,
    PublishOut,
    ReviewItemOut,
    RunSummary,
    SchemaProfileSummary,
    TableSummary,
    TestReportSummary,
)
from src.capabilities.summaries import finding_counts, review_item_out, run_summary
from src.domain.errors import ApprovalRequired, Conflict, DomainError, NotFound, ValidationFailed
from src.domain.models import SCHEMA_VERSION, AuditEvent, ReviewDecision, ReviewGate, RunStatus, StepName
from src.domain.project_models import (
    ArtifactBundle,
    CertificationPacket,
    ItemDecision,
    MappingSet,
    PublishReceipt,
    SchemaProfile,
    TestReport,
)
from src.version import VERSION

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE_STATE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
HUMAN = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
    title="Human reviewer only",
)
PUBLISH = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
    title="Publish certified artifacts (requires certification)",
)

TOOL_ANNOTATIONS = {
    "healthcheck": READ,
    "get_run_status": READ,
    "list_pending_reviews": READ,
    "start_onboarding_run": WRITE_STATE,
    "profile_schema": WRITE_STATE,
    "propose_canonical_mapping": WRITE_STATE,
    "resume_run": WRITE_STATE,
    "generate_dbt_artifacts": WRITE_STATE,
    "run_sandbox_tests": WRITE_STATE,
    "submit_mapping_review": HUMAN,
    "certify_run": HUMAN,
    "publish_run": PUBLISH,
}


def register(mcp: MCPServer, state: ServerState) -> None:
    # ------------------------------------------------------------------ diagnostics

    @mcp.tool(annotations=TOOL_ANNOTATIONS["healthcheck"])
    async def healthcheck() -> Health:
        """Return service health for diagnostics."""
        db = "ok"
        try:
            from sqlalchemy import text

            with state.svc().store.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            db = "unavailable"
        return Health(
            status="ok" if db == "ok" else "degraded", version=VERSION, database=db, schema_version=SCHEMA_VERSION
        )

    # ------------------------------------------------------------------ runs (orchestration)

    @mcp.tool(annotations=TOOL_ANNOTATIONS["start_onboarding_run"])
    @tool_errors
    async def start_onboarding_run(connection_id: str, company_id: str | None = None) -> RunSummary:
        """Start read-only onboarding of a registered source (e.g. `fixture:portco_a`).

        Runs connection validation, profiling, entity and join inference and canonical mapping,
        then stops at the first human review gate. Returns the run status and pending review items.
        """
        svc, principal = state.svc(), state.principal()
        run = await svc.start_run(principal, connection_id, company_id)
        return run_summary(svc, principal, run)

    @mcp.tool(annotations=TOOL_ANNOTATIONS["get_run_status"])
    @tool_errors
    async def get_run_status(run_id: str) -> RunSummary:
        """Current status, step history, gate and pending review items of a run."""
        svc, principal = state.svc(), state.principal()
        return run_summary(svc, principal, svc.get_run(principal, parse_uuid(run_id, "run_id")))

    @mcp.tool(annotations=TOOL_ANNOTATIONS["resume_run"])
    @tool_errors
    async def resume_run(run_id: str) -> RunSummary:
        """Continue a paused or failed run. Gates re-check approvals; completed steps are reused, not recomputed."""
        svc, principal = state.svc(), state.principal()
        run = await svc.resume(principal, parse_uuid(run_id, "run_id"))
        return run_summary(svc, principal, run)

    @mcp.tool(annotations=TOOL_ANNOTATIONS["list_pending_reviews"])
    @tool_errors
    async def list_pending_reviews(run_id: str) -> list[ReviewItemOut]:
        """Review items a human must decide before the run can continue."""
        svc, principal = state.svc(), state.principal()
        return [review_item_out(i) for i in svc.pending_reviews(principal, parse_uuid(run_id, "run_id"))]

    @mcp.tool(annotations=TOOL_ANNOTATIONS["submit_mapping_review"])
    @tool_errors
    async def submit_mapping_review(
        run_id: str,
        subject_hash: str,
        gate: Literal["mapping_review", "test_failures"],
        decisions: list[DecisionIn],
        comment: str | None = None,
    ) -> ApprovalResult:
        """Record a reviewer's decisions for an observed mapping or test-failure packet.

        Decisions: approve | reject | approve_with_override (override keys: canonical_field, transform,
        pii_handling). Supply the exact subject_hash and gate returned by list_pending_reviews.
        Stale packets are rejected. Certification must use certify_run. Reviewer principals only.
        """
        svc, principal = state.svc(), state.principal()
        rid = parse_uuid(run_id, "run_id")
        approval = svc.submit_review(
            principal,
            rid,
            [ItemDecision(**d.model_dump()) for d in decisions],
            comment,
            subject_hash=subject_hash,
            gate=ReviewGate(gate),
        )
        return ApprovalResult(
            approval_id=str(approval.approval_id),
            run_id=run_id,
            gate=approval.gate.value,
            subject_hash=approval.subject_hash,
            decisions=len(approval.decisions),
            reviewer=approval.reviewer,
            next_action="resume_run or generate_dbt_artifacts",
        )

    @mcp.tool(annotations=TOOL_ANNOTATIONS["certify_run"])
    @tool_errors
    async def certify_run(
        run_id: str,
        subject_hash: str,
        bundle_decision: str = "approve",
        metric_decisions: dict[str, str] | None = None,
        comment: str | None = None,
    ) -> ApprovalResult:
        """Certify the generated bundle and its metrics. Reviewer principals only.

        `subject_hash` is the `subject_hash` of the pending certification items: it binds the approval to the
        exact packet under review (bundle, tests, waivers, open findings). `metric_decisions` maps
        metric -> approve|reject; unknown metric names are rejected, unlisted metrics are approved. Rejected
        metrics (and metrics derived from them) are not published.
        """
        svc, principal = state.svc(), state.principal()
        rid = parse_uuid(run_id, "run_id")
        run = svc.get_run(principal, rid)
        metric_decisions = metric_decisions or {}
        metric_items = {i.item_key.removeprefix("metric:"): i for i in run.pending_items if i.kind == "metric"}
        unknown = sorted(set(metric_decisions) - set(metric_items))
        if unknown:
            raise ValidationFailed(f"unknown metrics in metric_decisions: {unknown}; expected {sorted(metric_items)}")
        bundle_items = [i for i in run.pending_items if i.kind == "bundle"]
        if not bundle_items:
            raise Conflict("run is not waiting for certification")
        decisions = [ItemDecision(item_key=bundle_items[0].item_key, decision=ReviewDecision(bundle_decision))]
        decisions += [
            ItemDecision(item_key=item.item_key, decision=ReviewDecision(metric_decisions.get(name, "approve")))
            for name, item in sorted(metric_items.items())
        ]
        approval = svc.certify(principal, rid, subject_hash, decisions, comment)
        return ApprovalResult(
            approval_id=str(approval.approval_id),
            run_id=run_id,
            gate=approval.gate.value,
            subject_hash=approval.subject_hash,
            decisions=len(approval.decisions),
            reviewer=approval.reviewer,
            next_action="publish_run with this approval_id",
        )

    # ------------------------------------------------------------------ schema-profiler capability

    @mcp.tool(annotations=TOOL_ANNOTATIONS["profile_schema"])
    @tool_errors
    async def profile_schema(connection_id: str, schemas: list[str] | None = None) -> SchemaProfileSummary:
        """Profile a source read-only: row counts, null rates, distinct counts, patterns, PII classes.

        Aggregates only (`sample_rows=0` by construction); values never leave the source adapter.
        Starts a run that pauses after profiling; continue it with propose_canonical_mapping.
        """
        svc, principal = state.svc(), state.principal()
        conn = connection_id if not schemas else f"{connection_id}?schemas={','.join(sorted(schemas))}"
        run = await svc.start_run(principal, conn, None, StepName.SCHEMA_PROFILING)
        if run.status is RunStatus.FAILED:
            raise Conflict(f"profiling failed: {run.error.get('message') if run.error else 'unknown'}")
        profile = svc.artifact(principal, run.run_id, StepName.SCHEMA_PROFILING)
        assert isinstance(profile, SchemaProfile)
        findings = svc.findings(principal, run.run_id)
        return SchemaProfileSummary(
            run_id=str(run.run_id),
            profile_id=str(profile.profile_id),
            status=run.status.value,
            tables=[
                TableSummary(
                    table=t.qualified,
                    rows=t.row_count,
                    columns=len(t.columns),
                    pii_columns=sum(1 for c in t.columns if c.pii_class),
                    freshness_max_date=t.freshness_max_date,
                    comment_flagged=t.comment_flagged,
                )
                for t in profile.tables
            ],
            pii_column_count=sum(1 for t in profile.tables for c in t.columns if c.pii_class),
            findings=finding_counts(findings),
            resource_uri=f"run://{run.run_id}/profile",
        )

    # ------------------------------------------------------------------ mapping capability

    @mcp.tool(annotations=TOOL_ANNOTATIONS["propose_canonical_mapping"])
    @tool_errors
    async def propose_canonical_mapping(run_id: str) -> MappingSetSummary:
        """Infer entities and joins and propose canonical mappings for a profiled run.

        Deterministic scoring; anything uncertain, PII-bearing, metric-bearing or conflicting is routed
        to human review rather than guessed. Stops at the mapping-review gate.
        """
        svc, principal = state.svc(), state.principal()
        rid = parse_uuid(run_id, "run_id")
        run = svc.get_run(principal, rid)
        if run.status is RunStatus.PENDING:
            run = await svc.resume(principal, rid)
        ms = svc.artifact(principal, rid, StepName.CANONICAL_MAPPING)
        assert isinstance(ms, MappingSet)
        n_review = sum(p.requires_review for p in ms.proposals)
        return MappingSetSummary(
            run_id=run_id,
            status=run.status.value,
            mapping_hash=ms.content_hash(),
            proposals=len(ms.proposals),
            auto_accepted=len(ms.proposals) - n_review,
            requires_review=n_review,
            row_filters=len(ms.row_filters),
            joins=len(ms.joins),
            unmapped_required=[f"{u.entity}.{u.field}" for u in ms.unmapped_required],
            metrics_needing_evidence=ms.metrics_needing_evidence,
            review_items=[review_item_out(i) for i in run.pending_items[:50]],
            resource_uri=f"run://{run_id}/mapping",
        )

    # ------------------------------------------------------------------ dbt capability

    @mcp.tool(annotations=TOOL_ANNOTATIONS["generate_dbt_artifacts"])
    @tool_errors
    async def generate_dbt_artifacts(run_id: str, approval_id: str) -> ArtifactBundleSummary:
        """Generate the dbt project and semantic layer from the reviewed mapping.

        Requires `approval_id` from submit_mapping_review; the server verifies it exists, is not revoked
        or expired, belongs to this run, and is bound to the current mapping content (no boolean flags).
        """
        svc, principal = state.svc(), state.principal()
        rid = parse_uuid(run_id, "run_id")
        ms = svc.artifact(principal, rid, StepName.CANONICAL_MAPPING)
        assert isinstance(ms, MappingSet)
        svc.verify_approval(rid, parse_uuid(approval_id, "approval_id"), ReviewGate.MAPPING_REVIEW, ms.content_hash())
        run = await svc.resume(principal, rid, stop_after=StepName.ARTIFACT_GENERATION)
        try:
            bundle = svc.artifact(principal, rid, StepName.ARTIFACT_GENERATION)
        except NotFound as exc:
            raise Conflict(f"artifacts were not generated; run status is {run.status.value}") from exc
        assert isinstance(bundle, ArtifactBundle)
        return ArtifactBundleSummary(
            run_id=run_id,
            status=run.status.value,
            manifest_hash=bundle.manifest_hash,
            files=len(bundle.files),
            models=bundle.models,
            generated_metrics=bundle.generated_metrics,
            not_generated=bundle.not_generated,
            resource_uri=f"run://{run_id}/artifacts/README.md",
        )

    @mcp.tool(annotations=TOOL_ANNOTATIONS["run_sandbox_tests"])
    @tool_errors
    async def run_sandbox_tests(run_id: str) -> TestReportSummary:
        """Build the generated project with dbt in a disposable sandbox and reconcile metrics exactly.

        On success the run pauses at the certification gate; on failure at the test-failures gate.
        """
        svc, principal = state.svc(), state.principal()
        rid = parse_uuid(run_id, "run_id")
        # Continue into the certification gate: it pauses the run for a human either way.
        run = await svc.resume(principal, rid)
        with svc.store.tx() as tx:
            rec = tx.steps.active(rid, StepName.AUTOMATED_TESTS.value)
        if rec is None or rec.output_ref is None:
            raise Conflict(f"sandbox tests did not run; run status is {run.status.value}")
        report = svc.store.blobs.get_model(rec.output_ref, TestReport)
        return TestReportSummary(
            run_id=run_id,
            status=run.status.value,
            passed=report.passed,
            dbt_exit_code=report.dbt_exit_code,
            data_tests=sum(1 for r in report.dbt_results if r.resource_type == "test"),
            failing_checks=report.failing_checks,
            waived_checks=report.waived_checks,
            reconciliation=[CheckOut(name=c.name, passed=c.passed, detail=c.detail) for c in report.reconciliation],
            cached=report.cached,
            resource_uri=f"run://{run_id}/test-report",
        )

    # ------------------------------------------------------------------ catalog / publish capability

    @mcp.tool(annotations=TOOL_ANNOTATIONS["publish_run"])
    @tool_errors
    async def publish_run(run_id: str, certification_id: str) -> PublishOut:
        """Publish certified artifacts. Fails closed without a valid certification bound to the bundle."""
        svc, principal = state.svc(), state.principal()
        rid = parse_uuid(run_id, "run_id")
        svc.get_run(principal, rid)  # NOT_FOUND (unknown or other tenant's run) before any denial is audited
        try:
            try:
                packet = svc.artifact(principal, rid, StepName.HUMAN_CERTIFICATION)
            except NotFound as exc:
                raise ApprovalRequired("there is no certification packet for the current bundle") from exc
            assert isinstance(packet, CertificationPacket)
            svc.verify_approval(
                rid, parse_uuid(certification_id, "certification_id"), ReviewGate.CERTIFICATION, packet.review_hash()
            )
        except DomainError:
            with svc.store.tx() as tx:
                tx.audit.append(
                    AuditEvent(
                        run_id=rid,
                        step="publish",
                        actor=principal.principal_id,
                        event_type="policy_denied",
                        payload={"action": "publish", "reason": "invalid certification"},
                    )
                )
            raise
        run = await svc.resume(principal, rid)
        receipt = None
        if run.status is RunStatus.COMPLETE:
            receipt = svc.artifact(principal, rid, StepName.PUBLISH)
            assert isinstance(receipt, PublishReceipt)
        return PublishOut(
            run_id=run_id,
            status=run.status.value,
            version=receipt.version if receipt else None,
            manifest_hash=receipt.manifest_hash if receipt else None,
            published_metrics=receipt.published_metrics if receipt else [],
            excluded_metrics=receipt.excluded_metrics if receipt else [],
            reused=receipt.reused if receipt else False,
            path=receipt.path if receipt else None,
        )
