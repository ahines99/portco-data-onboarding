"""OnboardingService: the one entry point the CLI and the MCP server both use.

It owns principal checks (role + tenant scope) and delegates to the engine and services.
Nothing here trusts a caller-supplied flag in place of a server-side check.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic import command
from alembic.config import Config

from src.adapters.artifact_store import ArtifactStore
from src.adapters.db import make_engine
from src.adapters.external import ConnectionRegistry
from src.adapters.faults import FaultInjector
from src.adapters.repositories import RunRecord, Store
from src.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from src.domain.hashing import canonical_json
from src.domain.identifiers import assert_safe_company
from src.domain.models import (
    AuditEvent,
    Evidence,
    Finding,
    Principal,
    ReviewGate,
    Role,
    RunStatus,
    StepName,
)
from src.domain.ontology import load_ontology
from src.domain.policies import check_action
from src.domain.project_models import Approval, ItemDecision, ReviewItem
from src.domain.run_states import can_transition
from src.observability import configure_logging
from src.services import approvals as approval_service
from src.settings import PROJECT_ROOT, Settings, get_settings
from src.workflows.base import WorkflowEngine
from src.workflows.primary import OUTPUT_TYPES, PROJECT_STEPS

SYSTEM = Principal(principal_id="system", role=Role.ADMIN)


def migrate(url: str) -> None:
    logging.getLogger("alembic").setLevel(logging.WARNING)
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # configparser interpolation
    command.upgrade(cfg, "head")


@dataclass
class OnboardingService:
    settings: Settings
    store: Store
    engine: WorkflowEngine
    connections: ConnectionRegistry
    services: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        *,
        faults: FaultInjector | None = None,
        judge: Any = None,
        run_migrations: bool = True,
    ) -> OnboardingService:
        settings = settings or get_settings()
        configure_logging(settings.log_level)
        settings.var_root.mkdir(parents=True, exist_ok=True)
        if run_migrations:
            migrate(settings.db_url)
        store = Store(make_engine(settings.db_url), ArtifactStore(settings.artifact_root))
        connections = ConnectionRegistry(settings.fixtures_dir)
        faults = faults if faults is not None else FaultInjector.parse(settings.faults, settings.env)
        services: dict[str, Any] = {"faults": faults}
        if judge is None and settings.llm_enabled:
            from src.services.judge import ClaudeJudge

            judge = ClaudeJudge.from_settings(settings)
        if judge is not None:
            services["judge"] = judge
        engine = WorkflowEngine(
            store=store,
            settings=settings,
            ontology=load_ontology(),
            connections=connections,
            steps=PROJECT_STEPS,
            services=services,
            faults=faults,
        )
        return cls(settings=settings, store=store, engine=engine, connections=connections, services=services)

    # ------------------------------------------------------------------ guards

    def _authorize(
        self, principal: Principal, action: str, run: RunRecord | None = None, company_id: str | None = None
    ) -> None:
        # Gated actions (generation, publish) verify their approval inside the step itself;
        # here we check role and tenant scope only.
        decision = check_action(action, role=principal.role, has_approval=True)
        company = run.company_id if run else company_id
        reason = None
        if not decision.allowed:
            reason = decision.reason
        elif company is not None and not principal.can_access(company):
            reason = "principal is not scoped to this company"
        if reason:
            if run is not None:
                with self.store.tx() as tx:
                    tx.audit.append(
                        AuditEvent(
                            run_id=run.run_id,
                            step=run.current_step or "",
                            actor=principal.principal_id,
                            event_type="policy_denied",
                            payload={"action": action, "reason": reason},
                        )
                    )
            raise Forbidden(reason)

    def get_run(self, principal: Principal, run_id: UUID) -> RunRecord:
        with self.store.tx() as tx:
            run = tx.runs.get(run_id)
        if not principal.can_access(run.company_id):
            raise NotFound(f"run {run_id} not found")  # do not reveal other tenants' runs
        return run

    # ------------------------------------------------------------------ runs

    async def start_run(
        self,
        principal: Principal,
        connection_id: str,
        company_id: str | None = None,
        stop_after: StepName | None = None,
    ) -> RunRecord:
        spec = self.connections.resolve(connection_id)
        company = company_id or spec.company_id
        if company != spec.company_id:
            raise ValidationFailed("connection does not belong to that company")
        assert_safe_company(company)
        self._authorize(principal, "start_run", company_id=company)
        with self.store.tx() as tx:
            run = tx.runs.create(
                company_id=company,
                connection_id=connection_id,
                requested_by=principal.principal_id,
                stop_after=stop_after.value if stop_after else None,
            )
        return await self._run(run.run_id, principal.principal_id)

    async def resume(self, principal: Principal, run_id: UUID, stop_after: StepName | None = None) -> RunRecord:
        run = self.get_run(principal, run_id)
        self._authorize(principal, "resume_run", run)
        # The engine's lease claim rejects a run another worker is executing (Conflict).
        return await self._run(run_id, principal.principal_id, stop_after=stop_after.value if stop_after else None)

    async def rerun_from(
        self,
        principal: Principal,
        run_id: UUID,
        step: StepName,
        reopen_reviews: bool = False,
        stop_after: StepName | None = None,
    ) -> RunRecord:
        run = self.get_run(principal, run_id)
        self._authorize(principal, "rerun_from", run)
        self.engine.rerun_from(run_id, step, principal.principal_id, reopen_reviews=reopen_reviews)
        return await self._run(run_id, principal.principal_id, stop_after=stop_after.value if stop_after else None)

    async def _run(self, run_id: UUID, actor: str, stop_after: str | None = None) -> RunRecord:
        with self.store.tx() as tx:
            before = tx.runs.get(run_id).status
        run = await self.engine.run(run_id, actor, stop_after=stop_after)
        if before not in {RunStatus.COMPLETE, RunStatus.CANCELLED}:  # the engine did work
            self._snapshot_metrics(run)
        return run

    def _snapshot_metrics(self, run: RunRecord) -> None:
        """Persist the run's metrics at every stop (content-addressed blob + audit event)."""
        from src.run_metrics import compute_run_metrics

        try:
            metrics = compute_run_metrics(self, SYSTEM, run.run_id)
        except Exception:  # metrics must never fail a run
            logging.getLogger(__name__).warning("run_metrics_failed", exc_info=True)
            return
        ref = self.store.blobs.put_bytes(canonical_json(metrics).encode())
        with self.store.tx() as tx:
            tx.audit.append(
                AuditEvent(
                    run_id=run.run_id,
                    step=run.current_step or "",
                    actor="system",
                    event_type="run_metrics_recorded",
                    payload={
                        "metrics_ref": ref,
                        "status": metrics["status"],
                        "retries": metrics["retries"],
                        "reused_steps": metrics["reused_steps"],
                        "llm_cost_usd": metrics["llm"]["cost_usd"],
                    },
                )
            )

    def cancel(self, principal: Principal, run_id: UUID, reason: str) -> RunRecord:
        run = self.get_run(principal, run_id)
        self._authorize(principal, "cancel_run", run)
        with self.store.tx() as tx:
            # A running run is cancelled too: its worker sees the status at the next step boundary,
            # discards any in-flight step result and releases the lease.
            run = tx.runs.get(run_id, lock=True)
            if not can_transition(run.status, RunStatus.CANCELLED):
                raise Conflict(f"a {run.status.value} run cannot be cancelled")
            # Publication linearizes when the final directory is materialized while
            # holding this same run lock. Cancellation wins before that boundary;
            # afterwards the worker/recovery must persist the successful result.
            # Earlier steps of a later rerun may still be cancelled; historical
            # publications remain published and cancellation never deletes them.
            if run.current_step == StepName.PUBLISH.value and any(
                p["state"] == "complete" or Path(p["receipt"]["path"]).exists() for p in tx.publications.for_run(run_id)
            ):
                raise Conflict("publication has finalized; the run can no longer be cancelled")
            tx.runs.update(run_id, status=RunStatus.CANCELLED, pending_items=[])
            tx.audit.append(
                AuditEvent(
                    run_id=run_id,
                    step=run.current_step or "",
                    actor=principal.principal_id,
                    event_type="run_cancelled",
                    payload={"reason": reason[:200]},
                )
            )
            return tx.runs.get(run_id)

    def list_runs(self, principal: Principal, limit: int = 20) -> list[RunRecord]:
        with self.store.tx() as tx:
            return tx.runs.list(list(principal.company_ids), limit)

    # ------------------------------------------------------------------ reviews

    def pending_reviews(self, principal: Principal, run_id: UUID) -> list[ReviewItem]:
        return self.get_run(principal, run_id).pending_items

    def submit_review(
        self,
        principal: Principal,
        run_id: UUID,
        decisions: list[ItemDecision],
        comment: str | None = None,
        gate: ReviewGate | None = None,
    ) -> Approval:
        run = self.get_run(principal, run_id)
        gate = gate or (ReviewGate(run.gate) if run.gate else None)
        if gate is None:
            raise Conflict("run is not waiting for review")
        subject = run.pending_items[0].subject_hash if run.pending_items else ""
        return self._record(principal, run, gate, subject, decisions, comment)

    def certify(
        self,
        principal: Principal,
        run_id: UUID,
        manifest_hash: str,
        decisions: list[ItemDecision],
        comment: str | None = None,
    ) -> Approval:
        run = self.get_run(principal, run_id)
        return self._record(principal, run, ReviewGate.CERTIFICATION, manifest_hash, decisions, comment)

    def _record(
        self,
        principal: Principal,
        run: RunRecord,
        gate: ReviewGate,
        subject: str,
        decisions: list[ItemDecision],
        comment: str | None,
    ) -> Approval:
        try:
            with self.store.tx() as tx:
                return approval_service.record(tx, self.settings, principal, run, gate, subject, decisions, comment)
        except Forbidden as exc:
            # The failed transaction rolled back; record the denial in its own committed transaction.
            with self.store.tx() as tx:
                tx.audit.append(
                    AuditEvent(
                        run_id=run.run_id,
                        step=run.current_step or "",
                        actor=principal.principal_id,
                        event_type="policy_denied",
                        payload={"action": approval_service.ACTION_FOR_GATE[gate], "reason": exc.message},
                    )
                )
            raise

    def verify_approval(self, run_id: UUID, approval_id: UUID, gate: ReviewGate, subject_hash: str) -> Approval:
        with self.store.tx() as tx:
            approval = approval_service.verify(tx, approval_id, gate, subject_hash)
        if approval.run_id != run_id:
            raise Forbidden("approval belongs to a different run")
        return approval

    # ------------------------------------------------------------------ reads

    def artifact(self, principal: Principal, run_id: UUID, step: StepName) -> Any:
        self.get_run(principal, run_id)
        with self.store.tx() as tx:
            rec = tx.steps.active(run_id, step.value)
        cls = OUTPUT_TYPES.get(step)
        if rec is None or rec.output_ref is None or cls is None:
            raise NotFound(f"no output for {step.value} yet")
        return self.store.blobs.get_model(rec.output_ref, cls)

    def bundle_file(self, principal: Principal, run_id: UUID, path: str) -> str:
        from src.domain.project_models import ArtifactBundle

        bundle = self.artifact(principal, run_id, StepName.ARTIFACT_GENERATION)
        assert isinstance(bundle, ArtifactBundle)
        match = next((f for f in bundle.files if f.path == path), None)
        if match is None:
            raise NotFound(f"no generated file {path!r}")
        return self.store.blobs.get_bytes(match.sha256).decode("utf-8")

    def findings(self, principal: Principal, run_id: UUID, code: str | None = None) -> list[Finding]:
        self.get_run(principal, run_id)
        with self.store.tx() as tx:
            return tx.findings.current(run_id, code)

    def audit(self, principal: Principal, run_id: UUID) -> tuple[list[AuditEvent], bool]:
        self.get_run(principal, run_id)
        with self.store.tx() as tx:
            events = tx.audit.list(run_id)
            ok, _ = tx.audit.verify_chain(run_id)
        return events, ok

    def steps(self, principal: Principal, run_id: UUID) -> list[dict[str, Any]]:
        self.get_run(principal, run_id)
        with self.store.tx() as tx:
            recs = tx.steps.list(run_id)
        out: dict[str, dict[str, Any]] = {}
        for r in recs:
            cur = out.setdefault(r.step, {"step": r.step, "attempts": 0, "status": "pending", "reused": False})
            cur["attempts"] += 1
            if r.active or cur["status"] == "pending":
                cur["status"] = r.status
        return [
            out.get(s.name.value, {"step": s.name.value, "attempts": 0, "status": "pending", "reused": False})
            for s in PROJECT_STEPS
        ]

    def evidence(self, principal: Principal, evidence_id: UUID) -> Evidence:
        with self.store.tx() as tx:
            ev, run_id, _ = tx.evidence.get(evidence_id)
        self.get_run(principal, run_id)
        return ev

    def lineage(self, principal: Principal, finding_id: UUID) -> dict[str, Any]:
        with self.store.tx() as tx:
            finding, run_id = tx.findings.get(finding_id)
            self_run = run_id

            def walk(ev_id: UUID, depth: int) -> dict[str, Any]:
                ev, _, parents = tx.evidence.get(ev_id)
                node: dict[str, Any] = {
                    "evidence_id": str(ev.evidence_id),
                    "source_uri": ev.source_uri,
                    "source_type": ev.source_type,
                    "content_hash": ev.content_hash,
                }
                if parents and depth < 5:
                    node["derived_from"] = [walk(p, depth + 1) for p in parents]
                return node

            tree = [walk(ev_id, 0) | {"relation": rel} for ev_id, rel in tx.findings.evidence_links(finding_id)]
        self.get_run(principal, self_run)
        return {
            "finding_id": str(finding.finding_id),
            "code": finding.code,
            "statement": finding.statement,
            "status": finding.status.value,
            "evidence": tree,
        }
