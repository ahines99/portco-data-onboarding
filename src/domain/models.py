"""Core domain vocabulary shared by every layer (POD-101)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Literal["1"] = "1"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    """Base for every contract: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class ValueObject(Contract):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StepName(StrEnum):
    """The nine workflow steps plus the conditional mapping-review gate (ADR-0005)."""

    CONNECTION_VALIDATION = "connection_validation"
    SCHEMA_PROFILING = "schema_profiling"
    ENTITY_INFERENCE = "entity_inference"
    JOIN_INFERENCE = "join_inference"
    CANONICAL_MAPPING = "canonical_mapping"
    MAPPING_REVIEW = "mapping_review"
    ARTIFACT_GENERATION = "artifact_generation"
    AUTOMATED_TESTS = "automated_tests"
    HUMAN_CERTIFICATION = "human_certification"
    PUBLISH = "publish"


STEP_ORDER: tuple[StepName, ...] = tuple(StepName)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewGate(StrEnum):
    MAPPING_REVIEW = "mapping_review"
    TEST_FAILURES = "test_failures"
    CERTIFICATION = "certification"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    APPROVE_WITH_OVERRIDE = "approve_with_override"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Role(StrEnum):
    AGENT = "agent"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class FindingType(StrEnum):
    OBSERVATION = "observation"
    CALCULATION = "calculation"
    ASSUMPTION = "assumption"
    RECOMMENDATION = "recommendation"


class FindingStatus(StrEnum):
    SUPPORTED = "supported"
    NEEDS_EVIDENCE = "needs_evidence"


class Principal(ValueObject):
    principal_id: str
    role: Role
    company_ids: tuple[str, ...] = ("*",)

    def can_access(self, company_id: str) -> bool:
        return "*" in self.company_ids or company_id in self.company_ids


class EvidenceRef(ValueObject):
    source_id: str
    uri: str
    retrieved_at: AwareDatetime
    as_of: AwareDatetime | None = None
    excerpt_hash: str | None = None


class Evidence(ValueObject):
    """A persisted record of one read from a source. The payload holds aggregates only."""

    evidence_id: UUID = Field(default_factory=uuid4)
    source_uri: str
    source_type: str
    as_of: AwareDatetime | None = None
    retrieved_at: AwareDatetime = Field(default_factory=utcnow)
    content_hash: str
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: Literal["1"] = SCHEMA_VERSION

    def ref(self) -> EvidenceRef:
        return EvidenceRef(
            source_id=str(self.evidence_id),
            uri=self.source_uri,
            retrieved_at=self.retrieved_at,
            as_of=self.as_of,
            excerpt_hash=self.content_hash,
        )


class Finding(Contract):
    finding_id: UUID = Field(default_factory=uuid4)
    code: str
    finding_type: FindingType = FindingType.OBSERVATION
    title: str
    statement: str
    confidence: Confidence
    status: FindingStatus = FindingStatus.SUPPORTED
    evidence: list[EvidenceRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: Literal["1"] = SCHEMA_VERSION

    @model_validator(mode="after")
    def _material_claims_need_evidence(self) -> Finding:
        if self.status is FindingStatus.SUPPORTED and not self.evidence:
            raise ValueError(
                f"finding {self.code!r} claims support but cites no evidence; cite evidence or mark it needs_evidence"
            )
        return self


class AuditEvent(Contract):
    run_id: UUID
    step: str
    event_type: str
    actor: str
    created_at: AwareDatetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)
    event_id: int | None = None
    prev_hash: str | None = None
    event_hash: str | None = None
    schema_version: Literal["1"] = SCHEMA_VERSION
