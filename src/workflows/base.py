"""Persistent workflow engine (POD-401, POD-403, POD-404, POD-405).

- `RunState` lives in the database, never in memory or a conversation.
- Each step's input hash covers its upstream outputs; a completed step with the same input
  hash is reused, not recomputed (idempotent reruns).
- A step's output, evidence, findings and audit events commit in one transaction.
- Retryable errors (source unavailable, timeouts, dependency crashes) are retried with
  exponential backoff; terminal errors fail the run with a structured, value-free error.
- Gate steps pause the run in NEEDS_REVIEW; `resume` re-enters at the gate, which re-checks
  approvals, and continues without recomputing earlier steps.
- Only the worker holding the run's execution lease advances it (`RunRepository.claim` is a
  compare-and-set). The lease is renewed before every step attempt; a cancelled run stops at
  the next step boundary and a step that finishes after cancellation is discarded, not
  persisted. A worker that dies leaves an expired lease, and the next `resume` recovers it.
- Status changes follow the table in `src/domain/run_states.py`.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import anyio
import structlog
from pydantic import BaseModel

from src.adapters.artifact_store import ArtifactStore
from src.adapters.external import ConnectionRegistry, SourceAdapter
from src.adapters.faults import FaultInjector, FaultyAdapter
from src.adapters.repositories import RunRecord, Store, Tx
from src.domain.errors import Conflict, DomainError, ErrorCode, LeaseLost, NotImplementedStep, SourceTimeout
from src.domain.hashing import content_hash
from src.domain.models import SCHEMA_VERSION, AuditEvent, ReviewGate, RunStatus, StepName
from src.domain.ontology import Ontology
from src.domain.run_states import check_transition
from src.observability import span
from src.services import approvals as approval_service
from src.settings import Settings
from src.workflows.contracts import StepContext, StepResult
from src.workflows.versioning import pipeline_version

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
                return FaultyAdapter(adapter, self.faults)
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
                "pipeline_version": pipeline_version(),
                "upstream": upstream_hashes,
                "connection": run.connection_id,
            }
        )

    @property
    def lease_seconds(self) -> float:
        """Long enough to outlive the slowest step attempt; the lease is renewed before every attempt."""
        longest = max((s.timeout_seconds or self.settings.step_timeout_seconds) for s in self.steps)
        return longest + self.settings.lease_margin_seconds

    async def _sleep(self, seconds: float) -> None:
        if self.sleep is not None:
            self.sleep(seconds)
            return
        await anyio.sleep(seconds)

    def _heartbeat(self, run_id: UUID, owner: str) -> bool:
        """Renew the lease; False when the run was cancelled (or otherwise stopped) meanwhile."""
        with self.store.tx() as tx:
            return tx.runs.renew(run_id, owner, self.lease_seconds).status is RunStatus.RUNNING

    # ------------------------------------------------------------------ execution

    async def run(self, run_id: UUID, actor: str = "system", *, stop_after: str | None = None) -> RunRecord:
        with self.store.tx() as tx:
            run = tx.runs.get(run_id)
            if run.status in {RunStatus.COMPLETE, RunStatus.CANCELLED}:
                return run
        owner = f"{actor[:40]}#{uuid4().hex[:12]}"
        with self.store.tx() as tx:
            before, run = tx.runs.claim(run_id, owner, self.lease_seconds)
            if stop_after is not None:
                tx.runs.update(run_id, stop_after=stop_after)
            names = [s.name.value for s in self.steps]
            start = names.index(run.current_step) if run.current_step in names else 0
            step0 = self.steps[start].name.value
            if before.status is RunStatus.RUNNING:  # the previous worker died holding an expired lease
                self._audit(
                    tx, run_id, step0, "run_recovered", actor, from_step=step0, previous_owner=before.lease_owner
                )
            event = "run_resumed" if before.status is not RunStatus.PENDING or start else "run_started"
            self._audit(tx, run_id, step0, event, actor, from_step=step0)

        with (
            structlog.contextvars.bound_contextvars(run_id=str(run_id), principal=actor),
            span("workflow.run", run_id=str(run_id), company_id=run.company_id, schema_version=SCHEMA_VERSION) as sp,
        ):
            log.info("run_claimed", from_step=step0)
            try:
                await self._drive(run_id, start, actor, owner)
            except LeaseLost:
                log.warning("lease_lost")
            except Exception as exc:  # engine bug or database failure: fail the run, never leave it RUNNING
                log.exception("run_crashed")
                self._fail_internal(run_id, owner, actor, exc)
            finally:
                with self.store.tx() as tx:
                    tx.runs.release(run_id, owner)
            with self.store.tx() as tx:
                result = tx.runs.get(run_id)
            sp.set_attribute("outcome", result.status.value)
            log.info("run_stopped", status=result.status.value, gate=result.gate)
            return result

    async def _drive(self, run_id: UUID, start: int, actor: str, owner: str) -> RunRecord:
        for idx in range(start, len(self.steps)):
            spec = self.steps[idx]
            if not self._heartbeat(run_id, owner):
                return self._stopped(run_id, spec.name.value, actor)
            outcome = await self._run_step(run_id, spec, actor, owner)
            if outcome == "cancelled":
                return self._stopped(run_id, spec.name.value, actor)
            if outcome != "completed":
                with self.store.tx() as tx:
                    return tx.runs.get(run_id)
            with self.store.tx() as tx:
                run = tx.runs.get(run_id, lock=True)
                nxt = self.steps[idx + 1].name.value if idx + 1 < len(self.steps) else None
                if run.status is RunStatus.RUNNING and run.stop_after == spec.name.value and nxt:
                    tx.runs.update(run_id, status=RunStatus.PENDING, current_step=nxt, stop_after=None)
                    self._audit(tx, run_id, spec.name.value, "run_paused", actor, next_step=nxt)
                    return tx.runs.get(run_id)
        with self.store.tx() as tx:
            run = tx.runs.get(run_id, lock=True)
            if run.status is not RunStatus.RUNNING or run.lease_owner != owner:
                return run
            tx.runs.update(run_id, status=RunStatus.COMPLETE, current_step=None, gate=None, pending_items=[])
            self._audit(tx, run_id, "", "run_completed", actor)
            return tx.runs.get(run_id)

    def _stopped(self, run_id: UUID, step: str, actor: str) -> RunRecord:
        with self.store.tx() as tx:
            run = tx.runs.get(run_id)
            self._audit(tx, run_id, step, "run_stopped", actor, status=run.status.value)
            return run

    def _fail_internal(self, run_id: UUID, owner: str, actor: str, exc: BaseException) -> RunRecord:
        with self.store.tx() as tx:
            run = tx.runs.get(run_id, lock=True)
            if run.status is RunStatus.RUNNING and run.lease_owner == owner:
                step = run.current_step or ""
                error = {
                    "step": step,
                    "code": ErrorCode.INTERNAL.value,
                    "message": "internal error",
                    "retryable": False,
                }
                tx.runs.update(run_id, status=RunStatus.FAILED, error=error)
                self._audit(
                    tx, run_id, step, "run_failed", actor, code=ErrorCode.INTERNAL.value, exception=type(exc).__name__
                )
            return tx.runs.get(run_id)

    def _owned(self, tx: Tx, run_id: UUID, owner: str) -> bool:
        run = tx.runs.get(run_id, lock=True)
        return run.status is RunStatus.RUNNING and run.lease_owner == owner

    async def _run_step(self, run_id: UUID, spec: StepSpec, actor: str, owner: str) -> str:
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
        with structlog.contextvars.bound_contextvars(step=step):
            for attempt in range(1, max_attempts + 1):
                if attempt > 1 and not self._heartbeat(run_id, owner):
                    return "cancelled"
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
                    with span(
                        "workflow.step",
                        run_id=str(run_id),
                        step=step,
                        attempt=sr.attempt,
                        schema_version=SCHEMA_VERSION,
                    ) as sp:
                        result = await self._execute(spec, ctx)
                        sp.set_attribute("outcome", result.status)
                        sp.set_attribute("evidence_count", len(result.evidence))
                        sp.set_attribute("finding_count", len(result.findings))
                except DomainError as exc:
                    retry = exc.retryable and attempt < max_attempts
                    log.warning("step_failed", attempt=sr.attempt, code=exc.code.value, will_retry=retry)
                    error = {"step": step, **exc.to_dict()}
                    if not self._record_failure(
                        run_id, owner, step, sr.step_run_id, sr.attempt, exc, error, retry, actor
                    ):
                        return "cancelled"
                    if not retry:
                        return "failed"
                    backoff = self.settings.step_backoff_base_seconds * (2 ** (attempt - 1))
                    await self._sleep(backoff * (1 + random.random() * 0.1))  # noqa: S311 - jitter, not crypto
                    continue
                except Exception as exc:  # crash: never leak internals to callers
                    log.exception("step_crashed")
                    error = {
                        "step": step,
                        "code": ErrorCode.INTERNAL.value,
                        "message": f"internal error in {step}",
                        "retryable": False,
                    }
                    if not self._record_failure(
                        run_id, owner, step, sr.step_run_id, sr.attempt, exc, error, False, actor
                    ):
                        return "cancelled"
                    return "failed"
                finally:
                    ctx.close()
                return self._persist(run_id, spec, sr.step_run_id, result, actor, owner)
        return "failed"

    def _record_failure(
        self,
        run_id: UUID,
        owner: str,
        step: str,
        step_run_id: int,
        attempt: int,
        exc: Exception,
        error: dict[str, Any],
        retry: bool,
        actor: str,
    ) -> bool:
        """Record a failed attempt; returns False when the run is no longer ours to fail."""
        code = error["code"]
        detail = exc.message if isinstance(exc, DomainError) else type(exc).__name__
        with self.store.tx() as tx:
            tx.steps.finish(step_run_id, status="failed", error_code=code, error_detail=detail)
            if not self._owned(tx, run_id, owner):
                return False
            payload: dict[str, Any] = {"attempt": attempt, "code": code, "will_retry": retry}
            if isinstance(exc, DomainError):
                payload["message"] = exc.message
            self._audit(tx, run_id, step, "step_failed", actor, **payload)
            if retry:
                self._audit(tx, run_id, step, "step_retried", actor, next_attempt=attempt + 1)
            else:
                tx.runs.update(run_id, status=RunStatus.FAILED, current_step=step, error=error)
                extra = {} if isinstance(exc, DomainError) else {"exception": type(exc).__name__}
                self._audit(tx, run_id, step, "run_failed", actor, code=code, **extra)
        return True

    async def _execute(self, spec: StepSpec, ctx: StepContext) -> StepResult:
        timeout = spec.timeout_seconds or self.settings.step_timeout_seconds
        try:
            with anyio.fail_after(timeout):
                return await anyio.to_thread.run_sync(spec.fn, ctx, abandon_on_cancel=True)
        except TimeoutError as exc:
            raise SourceTimeout(f"step {spec.name.value} exceeded {timeout:.0f}s") from exc

    def _persist(
        self, run_id: UUID, spec: StepSpec, step_run_id: int, result: StepResult, actor: str, owner: str
    ) -> str:
        step = spec.name.value
        with self.store.tx() as tx:
            if not self._owned(tx, run_id, owner):  # cancelled (or reclaimed) while the step ran
                tx.steps.finish(step_run_id, status="cancelled")
                self._audit(tx, run_id, step, "step_discarded", actor, reason="run no longer running")
                return "cancelled"
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

    def rerun_from(self, run_id: UUID, step: StepName, actor: str, *, reopen_reviews: bool = False) -> None:
        """Invalidate `step` and everything after it. With `reopen_reviews`, approvals recorded at gates
        from `step` onward are revoked too, so a reviewer can change a decision (new approvals required)."""
        names = [s.name for s in self.steps]
        idx = names.index(step)
        with self.store.tx() as tx:
            run = tx.runs.get(run_id, lock=True)
            if run.lease_live():
                raise Conflict("run is being executed; cancel it or wait for it to stop")
            check_transition(run.status, RunStatus.PENDING)
            for s in names[idx:]:
                tx.steps.deactivate(run_id, s.value)
            if reopen_reviews:
                gates = {spec.gate.value for spec in self.steps[idx:] if spec.gate is not None}
                for a in tx.approvals.for_run(run_id):
                    if a.gate.value in gates and a.revoked_at is None:
                        tx.approvals.revoke(a.approval_id, "review reopened")
                        self._audit(
                            tx,
                            run_id,
                            step.value,
                            "approval_invalidated",
                            actor,
                            approval_id=str(a.approval_id),
                            reason="review reopened",
                        )
            tx.runs.update(
                run_id,
                status=RunStatus.PENDING,
                current_step=step.value,
                gate=None,
                pending_items=[],
                error=None,
                lease_owner=None,
                lease_expires_at=None,
            )
            self._audit(tx, run_id, step.value, "rerun_requested", actor, from_step=step.value)


def not_implemented(name: str) -> StepFn:
    def fn(ctx: StepContext) -> StepResult:
        raise NotImplementedStep(f"step {name} is not implemented yet")

    return fn
