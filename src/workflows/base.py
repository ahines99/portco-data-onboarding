"""Persistent workflow engine (POD-401, POD-403, POD-404, POD-405).

- `RunState` lives in the database, never in memory or a conversation.
- Each step's input hash covers its upstream outputs; a completed step with the same input
  hash is reused, not recomputed (idempotent reruns).
- A step's output, evidence, findings and audit events commit in one transaction.
- Retryable errors (source unavailable, timeouts, dependency crashes) are retried with
  exponential backoff; terminal errors fail the run with a structured, value-free error.
- Gate steps pause the run in NEEDS_REVIEW; `resume` re-enters at the gate, which re-checks
  approvals, and continues without recomputing earlier steps.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import anyio
import structlog
from pydantic import BaseModel

from src.adapters.artifact_store import ArtifactStore
from src.adapters.external import ConnectionRegistry, SourceAdapter
from src.adapters.faults import FaultInjector, FaultyAdapter
from src.adapters.repositories import RunRecord, Store, Tx
from src.domain.errors import DomainError, ErrorCode, NotImplementedStep, SourceTimeout
from src.domain.hashing import content_hash
from src.domain.models import SCHEMA_VERSION, AuditEvent, ReviewGate, RunStatus, StepName
from src.domain.ontology import Ontology
from src.observability import span
from src.services import approvals as approval_service
from src.settings import Settings
from src.workflows.contracts import StepContext, StepResult

log = structlog.get_logger(__name__)

StepFn = Callable[[StepContext], StepResult]


@dataclass(frozen=True)
class StepSpec:
    name: StepName
    fn: StepFn
    output_type: type[BaseModel] | None
    always_execute: bool = False  # gates depend on approvals, which are not part of the input hash
    gate: ReviewGate | None = None
    retryable: bool = True
    timeout_seconds: float | None = None


def output_hash(model: BaseModel) -> str:
    fn = getattr(model, "content_hash", None)
    return fn() if callable(fn) else content_hash(model)


@dataclass
class WorkflowEngine:
    store: Store
    settings: Settings
    ontology: Ontology
    connections: ConnectionRegistry
    steps: list[StepSpec]
    services: dict[str, Any] = field(default_factory=dict)
    faults: FaultInjector = field(default_factory=FaultInjector)
    sleep: Callable[[float], Any] | None = None

    @property
    def blobs(self) -> ArtifactStore:
        return self.store.blobs

    # ------------------------------------------------------------------ helpers

    def _audit(self, tx: Tx, run_id: UUID, step: str, event_type: str, actor: str = "system", **payload: Any) -> None:
        tx.audit.append(AuditEvent(run_id=run_id, step=step, actor=actor, event_type=event_type, payload=payload))

    def _open_adapter(self, run: RunRecord) -> Callable[[], SourceAdapter]:
        def opener() -> SourceAdapter:
            adapter = self.connections.open(run.connection_id)
            if self.faults.active:
                return FaultyAdapter(adapter, self.faults)  # type: ignore[return-value]
            return adapter

        return opener

    def _load_upstream(self, tx: Tx, run_id: UUID, upto: StepName) -> tuple[dict[StepName, BaseModel], dict[str, str]]:
        upstream: dict[StepName, BaseModel] = {}
        hashes: dict[str, str] = {}
        for spec in self.steps:
            if spec.name == upto:
                break
            rec = tx.steps.active(run_id, spec.name.value)
            if rec is None or rec.status != "completed" or rec.output_ref is None or spec.output_type is None:
                continue
            upstream[spec.name] = self.blobs.get_model(rec.output_ref, spec.output_type)
            hashes[spec.name.value] = rec.output_hash or ""
        return upstream, hashes

    def input_hash(self, spec: StepSpec, upstream_hashes: dict[str, str], run: RunRecord) -> str:
        return content_hash(
            {
                "step": spec.name.value,
                "schema_version": SCHEMA_VERSION,
                "upstream": upstream_hashes,
                "connection": run.connection_id,
            }
        )

    async def _sleep(self, seconds: float) -> None:
        if self.sleep is not None:
            self.sleep(seconds)
            return
        await anyio.sleep(seconds)

    # ------------------------------------------------------------------ execution

    async def run(self, run_id: UUID, actor: str = "system") -> RunRecord:
        with self.store.tx() as tx:
            run = tx.runs.get(run_id)
            if run.status in {RunStatus.COMPLETE, RunStatus.CANCELLED}:
                return run
            names = [s.name.value for s in self.steps]
            start = names.index(run.current_step) if run.current_step in names else 0
            event = (
                "run_resumed" if run.status in {RunStatus.NEEDS_REVIEW, RunStatus.FAILED} or start else "run_started"
            )
            tx.runs.update(run_id, status=RunStatus.RUNNING, error=None)
            self._audit(tx, run_id, self.steps[start].name.value, event, actor, from_step=self.steps[start].name.value)

        for idx in range(start, len(self.steps)):
            spec = self.steps[idx]
            outcome = await self._run_step(run_id, spec, actor)
            if outcome != "completed":
                with self.store.tx() as tx:
                    return tx.runs.get(run_id)
            with self.store.tx() as tx:
                run = tx.runs.get(run_id)
                nxt = self.steps[idx + 1].name.value if idx + 1 < len(self.steps) else None
                if run.stop_after == spec.name.value and nxt:
                    tx.runs.update(run_id, status=RunStatus.PENDING, current_step=nxt, stop_after=None)
                    self._audit(tx, run_id, spec.name.value, "run_paused", actor, next_step=nxt)
                    return tx.runs.get(run_id)
        with self.store.tx() as tx:
            tx.runs.update(run_id, status=RunStatus.COMPLETE, current_step=None, gate=None, pending_items=[])
            self._audit(tx, run_id, "", "run_completed", actor)
            return tx.runs.get(run_id)

    async def _run_step(self, run_id: UUID, spec: StepSpec, actor: str) -> str:
        step = spec.name.value
        with self.store.tx() as tx:
            run = tx.runs.get(run_id)
            upstream, hashes = self._load_upstream(tx, run_id, spec.name)
            ihash = self.input_hash(spec, hashes, run)
            tx.runs.update(run_id, current_step=step)
            if not spec.always_execute:
                done = tx.steps.find_completed(run_id, step, ihash)
                if done is not None:
                    tx.steps.reuse(done.step_run_id)
                    self._audit(tx, run_id, step, "step_reused", actor, input_hash=ihash, step_run_id=done.step_run_id)
                    return "completed"
            approvals = tx.approvals.for_run(run_id)

        max_attempts = self.settings.step_max_attempts if spec.retryable else 1
        for attempt in range(1, max_attempts + 1):
            with self.store.tx() as tx:
                sr = tx.steps.start(run_id, step, ihash)
                self._audit(tx, run_id, step, "step_started", actor, attempt=sr.attempt, input_hash=ihash)
            ctx = StepContext(
                run=run,
                settings=self.settings,
                ontology=self.ontology,
                blobs=self.blobs,
                store=self.store,
                open_adapter=self._open_adapter(run),
                upstream=upstream,
                approvals=approvals,
                services=self.services,
            )
            try:
                with span("workflow.step", run_id=str(run_id), step=step, attempt=sr.attempt):
                    result = await self._execute(spec, ctx)
            except DomainError as exc:
                retry = exc.retryable and attempt < max_attempts
                with self.store.tx() as tx:
                    tx.steps.finish(
                        sr.step_run_id, status="failed", error_code=exc.code.value, error_detail=exc.message
                    )
                    self._audit(
                        tx,
                        run_id,
                        step,
                        "step_failed",
                        actor,
                        attempt=sr.attempt,
                        code=exc.code.value,
                        message=exc.message,
                        will_retry=retry,
                    )
                    if not retry:
                        tx.runs.update(
                            run_id, status=RunStatus.FAILED, current_step=step, error={"step": step, **exc.to_dict()}
                        )
                        self._audit(tx, run_id, step, "run_failed", actor, code=exc.code.value)
                        return "failed"
                    self._audit(tx, run_id, step, "step_retried", actor, next_attempt=sr.attempt + 1)
                backoff = self.settings.step_backoff_base_seconds * (2 ** (attempt - 1))
                await self._sleep(backoff * (1 + random.random() * 0.1))  # noqa: S311 - jitter, not crypto
                continue
            except Exception as exc:  # crash: never leak internals to callers
                log.exception("step_crashed", run_id=str(run_id), step=step)
                with self.store.tx() as tx:
                    tx.steps.finish(
                        sr.step_run_id,
                        status="failed",
                        error_code=ErrorCode.INTERNAL.value,
                        error_detail=type(exc).__name__,
                    )
                    tx.runs.update(
                        run_id,
                        status=RunStatus.FAILED,
                        current_step=step,
                        error={
                            "step": step,
                            "code": ErrorCode.INTERNAL.value,
                            "message": f"internal error in {step}",
                            "retryable": False,
                        },
                    )
                    self._audit(
                        tx,
                        run_id,
                        step,
                        "run_failed",
                        actor,
                        code=ErrorCode.INTERNAL.value,
                        exception=type(exc).__name__,
                    )
                return "failed"
            finally:
                ctx.close()
            return self._persist(run_id, spec, sr.step_run_id, result, actor)
        return "failed"

    async def _execute(self, spec: StepSpec, ctx: StepContext) -> StepResult:
        timeout = spec.timeout_seconds or self.settings.step_timeout_seconds
        try:
            with anyio.fail_after(timeout):
                return await anyio.to_thread.run_sync(spec.fn, ctx, abandon_on_cancel=True)
        except TimeoutError as exc:
            raise SourceTimeout(f"step {spec.name.value} exceeded {timeout:.0f}s") from exc

    def _persist(self, run_id: UUID, spec: StepSpec, step_run_id: int, result: StepResult, actor: str) -> str:
        step = spec.name.value
        with self.store.tx() as tx:
            ref = ohash = None
            if result.output is not None:
                ref = self.blobs.put_model(result.output)
                ohash = output_hash(result.output)
                tx.artifacts.record(run_id, step, ohash, step_run_id)
            for ev in result.evidence:
                tx.evidence.save(run_id, ev, step_run_id, result.evidence_parents.get(ev.evidence_id))
            for f in result.findings:
                for ref_ in f.evidence:
                    if not tx.evidence.exists(UUID(ref_.source_id)):
                        raise DomainError(f"finding {f.code} cites unknown evidence")
                tx.findings.save(run_id, step, f, step_run_id)
            for event_type, payload in result.audit:
                self._audit(tx, run_id, step, event_type, actor, **payload)
            if spec.gate is not None and result.subject_hash:
                approval_service.revoke_stale(tx, run_id, spec.gate, result.subject_hash, actor)
            if result.status == "needs_review":
                tx.steps.finish(step_run_id, status="needs_review", output_ref=ref, output_hash=ohash)
                gate = result.gate or spec.gate
                tx.runs.update(
                    run_id,
                    status=RunStatus.NEEDS_REVIEW,
                    current_step=step,
                    gate=gate.value if gate else None,
                    pending_items=result.pending_items,
                )
                self._audit(
                    tx,
                    run_id,
                    step,
                    "run_paused_for_review",
                    actor,
                    gate=gate.value if gate else None,
                    items=len(result.pending_items),
                )
                return "needs_review"
            tx.steps.finish(step_run_id, status="completed", output_ref=ref, output_hash=ohash)
            tx.runs.update(run_id, gate=None, pending_items=[])
            self._audit(
                tx,
                run_id,
                step,
                "step_completed",
                actor,
                output_hash=ohash,
                evidence=len(result.evidence),
                findings=len(result.findings),
            )
        return "completed"

    # ------------------------------------------------------------------ control

    def rerun_from(self, run_id: UUID, step: StepName, actor: str) -> None:
        names = [s.name for s in self.steps]
        idx = names.index(step)
        with self.store.tx() as tx:
            for s in names[idx:]:
                tx.steps.deactivate(run_id, s.value)
            tx.runs.update(
                run_id, status=RunStatus.PENDING, current_step=step.value, gate=None, pending_items=[], error=None
            )
            self._audit(tx, run_id, step.value, "rerun_requested", actor, from_step=step.value)


def not_implemented(name: str) -> StepFn:
    def fn(ctx: StepContext) -> StepResult:
        raise NotImplementedStep(f"step {name} is not implemented yet")

    return fn
