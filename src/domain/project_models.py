"""Project-specific contracts (POD-102).

Design rule: no contract carries raw row values. Profiles hold aggregates; the only value
lists allowed are `category_values`, populated solely for operator-approved category domains
that passed the PII guard (see `adapters.external.DuckDBAdapter.low_cardinality_values`).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field

from src.domain.hashing import content_hash
from src.domain.models import (
    SCHEMA_VERSION,
    Confidence,
    Contract,
    ReviewDecision,
    ReviewGate,
    utcnow,
)


class PiiClass(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    NATIONAL_ID = "national_id"
    PAYMENT_CARD = "payment_card"
    PERSON_NAME = "person_name"
    ADDRESS = "address"
    DOB = "dob"
    IP_ADDRESS = "ip_address"
    FREE_TEXT = "free_text_may_contain_pii"


class SemanticType(StrEnum):
    ID = "id"
    MONEY = "money"
    QUANTITY = "quantity"
    DATE = "date"
    TIMESTAMP = "timestamp"
    DATE_STRING = "date_string"
    CATEGORY = "category"
    BOOLEAN = "boolean"
    CODE = "code"
    FREE_TEXT = "free_text"
    NUMERIC = "numeric"
    MIXED = "mixed"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------- connection


class ConnectionSpec(Contract):
    connection_id: str
    company_id: str
    kind: Literal["duckdb"] = "duckdb"
    path: str
    schemas: list[str] = Field(default_factory=list, description="Allowlisted schemas")
    category_domains: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Operator-approved labels keyed by schema.table.column; unknown labels withheld",
    )
    read_only: bool = True
    as_of: date | None = Field(default=None, description="Reference date for freshness checks")
    secret_ref: str | None = Field(default=None, description="Reference to a secret; never the secret")


class ConnectionCheck(Contract):
    connection_id: str
    company_id: str
    reachable: bool
    read_only_verified: bool
    schemas_visible: list[str]
    tables_visible: int
    source_fingerprint: str
    engine_version: str
    evidence_id: UUID | None = None
    schema_version: Literal["1"] = SCHEMA_VERSION


# --------------------------------------------------------------------------- profiling


class ColumnProfile(Contract):
    table: str
    column: str
    ordinal: int
    dtype: str
    nullable: bool = True
    row_count: int
    non_null_count: int
    null_pct: float
    distinct_count: int | None = None
    uniqueness_ratio: float | None = None
    min_value: str | None = None
    max_value: str | None = None
    mean_value: float | None = None
    integer_valued: bool | None = None
    negative_count: int | None = None
    pattern_counts: dict[str, int] = Field(default_factory=dict)
    pattern_signature: str | None = None
    inferred_semantic_type: SemanticType = SemanticType.UNKNOWN
    pii_class: PiiClass | None = None
    pii_confidence: Confidence | None = None
    category_values: list[str] | None = None
    comment_flagged: bool = False
    evidence_id: UUID | None = None


class TableProfile(Contract):
    schema_name: str
    table_name: str
    row_count: int
    freshness_max_date: date | None = None
    columns: list[ColumnProfile]
    comment_flagged: bool = False
    evidence_id: UUID | None = None

    @property
    def qualified(self) -> str:
        return f"{self.schema_name}.{self.table_name}"

    def column(self, name: str) -> ColumnProfile:
        for col in self.columns:
            if col.column == name:
                return col
        raise KeyError(name)


class SchemaProfile(Contract):
    profile_id: UUID = Field(default_factory=uuid4)
    connection_id: str
    company_id: str
    source_fingerprint: str
    tables: list[TableProfile]
    schema_version: Literal["1"] = SCHEMA_VERSION

    def table(self, qualified: str) -> TableProfile:
        for t in self.tables:
            if t.qualified == qualified:
                return t
        raise KeyError(qualified)

    def fingerprint(self) -> str:
        return content_hash(self.model_dump(mode="json", exclude={"profile_id"}))


# --------------------------------------------------------------------------- entities & joins


class ScoredEntity(Contract):
    entity: str
    score: float


class EntityCandidate(Contract):
    table: str
    canonical_entity: str | None
    score: float
    confidence: Confidence
    feature_breakdown: dict[str, float] = Field(default_factory=dict)
    primary_key_columns: list[str] = Field(default_factory=list)
    alternatives: list[ScoredEntity] = Field(default_factory=list)
    excluded_reason: str | None = None


class EntityOverlap(Contract):
    entity: str
    tables: list[str]
    system_of_record: str | None = None


class EntityInference(Contract):
    candidates: list[EntityCandidate]
    overlaps: list[EntityOverlap] = Field(default_factory=list)
    schema_version: Literal["1"] = SCHEMA_VERSION

    def for_table(self, table: str) -> EntityCandidate | None:
        return next((c for c in self.candidates if c.table == table), None)


Cardinality = Literal["1:1", "1:N", "N:1", "N:M"]


class JoinCandidate(Contract):
    join_id: str
    left_table: str
    left_columns: list[str]
    right_table: str
    right_columns: list[str]
    containment_ratio: float
    orphan_rate: float
    cardinality: Cardinality
    name_score: float
    score: float
    confidence: Confidence
    requires_review: bool
    reason_codes: list[str] = Field(default_factory=list)
    evidence_id: UUID | None = None


class JoinGraph(Contract):
    joins: list[JoinCandidate]
    schema_version: Literal["1"] = SCHEMA_VERSION


# --------------------------------------------------------------------------- mapping

Transform = Literal["cents_to_major", "parse_mixed_date"]
PiiHandling = Literal["hash", "exclude"]


class ScoredTarget(Contract):
    entity: str
    field: str
    score: float


class MappingProposal(Contract):
    mapping_key: str
    source_table: str
    source_column: str
    source_field: str
    canonical_entity: str
    canonical_field: str
    confidence: Confidence
    score: float
    rationale: str
    requires_review: bool
    reason_codes: list[str] = Field(default_factory=list)
    alternatives: list[ScoredTarget] = Field(default_factory=list)
    suggested_transform: Transform | None = None
    pii_handling: PiiHandling | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    judge: dict[str, Any] | None = None


class RowFilter(Contract):
    filter_key: str
    table: str
    column: str
    kind: Literal["exclude_true", "exclude_match"]
    value: str | None = None  # exclude_match: a regex valid in both Python `re` and DuckDB (RE2)
    rationale: str
    affected_rows: int
    requires_review: bool = True
    evidence_ids: list[UUID] = Field(default_factory=list)


class UnmappedField(Contract):
    entity: str
    field: str
    affected_metrics: list[str] = Field(default_factory=list)


class MappingSet(Contract):
    mapping_id: UUID = Field(default_factory=uuid4)
    proposals: list[MappingProposal]
    row_filters: list[RowFilter] = Field(default_factory=list)
    joins: list[JoinCandidate] = Field(default_factory=list)
    entity_tables: dict[str, str] = Field(default_factory=dict, description="table -> canonical entity")
    primary_tables: dict[str, str] = Field(default_factory=dict, description="entity -> system-of-record table")
    unmapped_required: list[UnmappedField] = Field(default_factory=list)
    metrics_needing_evidence: list[str] = Field(default_factory=list)
    schema_version: Literal["1"] = SCHEMA_VERSION

    def content_hash(self) -> str:
        return content_hash(self.model_dump(mode="json", exclude={"mapping_id"}))

    def review_keys(self) -> list[str]:
        keys = [f"mapping:{p.mapping_key}" for p in self.proposals if p.requires_review]
        keys += [f"filter:{f.filter_key}" for f in self.row_filters if f.requires_review]
        keys += [f"join:{j.join_id}" for j in self.joins if j.requires_review]
        return keys


class AcceptedMapping(Contract):
    source_table: str
    source_column: str
    canonical_entity: str
    canonical_field: str
    transform: Transform | None = None
    pii_handling: PiiHandling | None = None
    decided_by: Literal["auto", "reviewer"]
    overridden: bool = False


class ResolvedMapping(Contract):
    """Output of the mapping-review gate: what artifact generation is allowed to use."""

    mapping_hash: str
    accepted: list[AcceptedMapping]
    filters: list[RowFilter]
    joins: list[JoinCandidate]
    entity_tables: dict[str, str]
    primary_tables: dict[str, str]
    rejected_keys: list[str] = Field(default_factory=list)
    approval_ids: list[UUID] = Field(default_factory=list)
    metrics_needing_evidence: list[str] = Field(default_factory=list)
    schema_version: Literal["1"] = SCHEMA_VERSION

    def content_hash(self) -> str:
        return content_hash(self.model_dump(mode="json", exclude={"approval_ids"}))

    def for_table(self, table: str) -> list[AcceptedMapping]:
        return [m for m in self.accepted if m.source_table == table]

    def field_source(self, entity: str, field: str) -> AcceptedMapping | None:
        primary = self.primary_tables.get(entity)
        matches = [m for m in self.accepted if m.canonical_entity == entity and m.canonical_field == field]
        for m in matches:
            if m.source_table == primary:
                return m
        return matches[0] if matches else None


# --------------------------------------------------------------------------- review & approvals


class ReviewItem(Contract):
    item_key: str
    gate: ReviewGate
    kind: Literal["mapping", "row_filter", "join", "bundle", "metric", "test_failure"]
    summary: str
    reason_codes: list[str] = Field(default_factory=list)
    subject_hash: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class ItemDecision(Contract):
    item_key: str
    decision: ReviewDecision
    override: dict[str, Any] | None = None
    comment: str | None = None


class Approval(Contract):
    approval_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    gate: ReviewGate
    subject_hash: str
    decisions: list[ItemDecision]
    reviewer: str
    role: str
    comment: str | None = None
    created_at: AwareDatetime = Field(default_factory=utcnow)
    expires_at: AwareDatetime | None = None
    revoked_at: AwareDatetime | None = None
    revoked_reason: str | None = None


# --------------------------------------------------------------------------- artifacts & tests


class ArtifactFile(Contract):
    path: str
    sha256: str
    kind: str
    size: int


class ArtifactBundle(Contract):
    bundle_id: UUID = Field(default_factory=uuid4)
    mapping_hash: str
    files: list[ArtifactFile]
    manifest_hash: str
    generated_metrics: list[str]
    not_generated: dict[str, str] = Field(default_factory=dict)
    models: list[str] = Field(default_factory=list)
    schema_version: Literal["1"] = SCHEMA_VERSION


class DbtResult(Contract):
    unique_id: str
    resource_type: str
    status: str
    failures: int | None = None
    message: str | None = None


class ReconciliationCheck(Contract):
    name: str
    passed: bool
    detail: str
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)
    blocking: bool = True


class TestReport(Contract):
    __test__ = False  # not a pytest test class

    manifest_hash: str
    source_fingerprint: str
    passed: bool
    dbt_exit_code: int
    dbt_results: list[DbtResult]
    reconciliation: list[ReconciliationCheck]
    failing_checks: list[str] = Field(default_factory=list)
    waived_checks: list[str] = Field(default_factory=list)
    cached: bool = False
    duration_seconds: float = 0.0
    schema_version: Literal["1"] = SCHEMA_VERSION


class MetricCertification(Contract):
    metric: str
    description: str
    formula: str
    status: Literal["generated", "not_generated", "reference_only"]
    reason: str | None = None


class CertificationPacket(Contract):
    run_id: UUID
    manifest_hash: str
    mapping_hash: str
    joins: list[JoinCandidate]
    mapping_summary: dict[str, int]
    reviewer_overrides: list[str]
    metrics: list[MetricCertification]
    test_report_passed: bool
    failing_checks: list[str]
    waived_checks: list[str]
    open_findings: list[dict[str, Any]]
    evidence_ids: list[UUID]
    # Filled in once a reviewer has decided; part of the step output (and therefore of publish's input).
    certified_metrics: list[str] = Field(default_factory=list)
    excluded_metrics: list[str] = Field(default_factory=list)
    certification_ids: list[UUID] = Field(default_factory=list)
    schema_version: Literal["1"] = SCHEMA_VERSION

    DECISION_FIELDS: ClassVar[set[str]] = {"certified_metrics", "excluded_metrics", "certification_ids"}

    def review_hash(self) -> str:
        """What the reviewer certifies: everything in the packet except the decisions themselves."""
        return content_hash(self.model_dump(mode="json", exclude=self.DECISION_FIELDS))

    def content_hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class PublishReceipt(Contract):
    company_id: str
    version: str
    manifest_hash: str
    certification_id: UUID
    publisher: str
    published_at: AwareDatetime = Field(default_factory=utcnow)
    path: str
    published_metrics: list[str]
    excluded_metrics: list[str]
    reused: bool = False
    schema_version: Literal["1"] = SCHEMA_VERSION
