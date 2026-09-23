"""The contract between the workflow engine and step services.

Services are pure with respect to persistence: they receive a `StepContext` holding loaded
upstream artifacts, and return a `StepResult`. The engine persists outputs, evidence,
findings and audit events atomically (POD-401).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, TypeVar
from uuid import UUID, uuid5

from pydantic import BaseModel

from src.adapters.artifact_store import ArtifactStore
from src.adapters.external import SourceAdapter
from src.adapters.repositories import RunRecord, Store
from src.domain.errors import DomainError
from src.domain.hashing import content_hash
from src.domain.models import Evidence, Finding, ReviewGate, StepName
from src.domain.ontology import Ontology
from src.domain.project_models import Approval, ReviewItem
from src.settings import Settings

M = TypeVar("M", bound=BaseModel)


@dataclass
class StepContext:
    run: RunRecord
    settings: Settings
    ontology: Ontology
    blobs: ArtifactStore
    store: Store
    open_adapter: Callable[[], SourceAdapter]
    upstream: dict[StepName, BaseModel] = field(default_factory=dict)
    approvals: list[Approval] = field(default_factory=list)
    services: dict[str, Any] = field(default_factory=dict)
    _adapter: SourceAdapter | None = None

    def adapter(self) -> SourceAdapter:
        if self._adapter is None:
            self._adapter = self.open_adapter()
        return self._adapter

    def close(self) -> None:
        if self._adapter is not None:
            self._adapter.close()
            self._adapter = None

    def get(self, step: StepName, cls: type[M]) -> M:
        value = self.upstream.get(step)
        if not isinstance(value, cls):
            raise DomainError(f"missing upstream artifact from {step.value}")
        return value


@dataclass
class StepResult:
    status: Literal["ok", "needs_review"] = "ok"
    output: BaseModel | None = None
    evidence: list[Evidence] = field(default_factory=list)
    evidence_parents: dict[UUID, list[UUID]] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    gate: ReviewGate | None = None
    pending_items: list[ReviewItem] = field(default_factory=list)
    subject_hash: str | None = None  # gates: the content hash approvals must be bound to
    audit: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


EVIDENCE_NS = UUID("6f1c2a9e-3b7d-4c55-9a51-0d2f7e1b8c44")


def make_evidence(
    ctx: StepContext, source_uri: str, source_type: str, payload: dict[str, Any], as_of: date | None = None
) -> Evidence:
    """Evidence with a deterministic id: same run + source + content -> same id (POD-404)."""
    digest = content_hash(payload)
    return Evidence(
        evidence_id=uuid5(EVIDENCE_NS, f"{ctx.run.run_id}|{source_uri}|{digest}"),
        source_uri=source_uri,
        source_type=source_type,
        content_hash=digest,
        payload=payload,
        as_of=datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC) if as_of else None,
    )
