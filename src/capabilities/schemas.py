"""Typed outputs of the MCP surface. Compact by design; detail lives in resources."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.domain.models import ReviewDecision


class Health(BaseModel):
    status: str
    version: str
    database: str
    schema_version: str


class ErrorOut(BaseModel):
    code: str
    message: str
    retryable: bool = False


class StepStatus(BaseModel):
    step: str
    status: str
    attempts: int


class ReviewItemOut(BaseModel):
    item_key: str
    gate: str
    kind: str
    summary: str
    reason_codes: list[str]
    subject_hash: str
    alternatives: list[str] = Field(default_factory=list)
    suggested_transform: str | None = None


class RunSummary(BaseModel):
    run_id: str
    company_id: str
    connection_id: str
    status: str
    current_step: str | None
    gate: str | None
    pending_review_count: int
    pending_items: list[ReviewItemOut]
    steps: list[StepStatus]
    error: ErrorOut | None = None
    next_action: str
    resources: list[str]


class TableSummary(BaseModel):
    table: str
    rows: int
    columns: int
    pii_columns: int
    freshness_max_date: date | None
    comment_flagged: bool


class SchemaProfileSummary(BaseModel):
    run_id: str
    profile_id: str
    status: str
    tables: list[TableSummary]
    pii_column_count: int
    findings: dict[str, int]
    resource_uri: str


class MappingSetSummary(BaseModel):
    run_id: str
    status: str
    mapping_hash: str
    proposals: int
    auto_accepted: int
    requires_review: int
    row_filters: int
    joins: int
    unmapped_required: list[str]
    metrics_needing_evidence: list[str]
    review_items: list[ReviewItemOut]
    resource_uri: str


class DecisionIn(BaseModel):
    item_key: str
    decision: ReviewDecision
    override: dict[str, Any] | None = Field(default=None, description="{canonical_field, transform, pii_handling}")
    comment: str | None = None


class ApprovalResult(BaseModel):
    approval_id: str
    run_id: str
    gate: str
    subject_hash: str
    decisions: int
    reviewer: str
    next_action: str


class ArtifactBundleSummary(BaseModel):
    run_id: str
    status: str
    manifest_hash: str
    files: int
    models: list[str]
    generated_metrics: list[str]
    not_generated: dict[str, str]
    resource_uri: str


class CheckOut(BaseModel):
    name: str
    passed: bool
    detail: str


class TestReportSummary(BaseModel):
    __test__ = False

    run_id: str
    status: str
    passed: bool
    dbt_exit_code: int
    data_tests: int
    failing_checks: list[str]
    waived_checks: list[str]
    reconciliation: list[CheckOut]
    cached: bool
    resource_uri: str


class PublishOut(BaseModel):
    run_id: str
    status: Literal["complete", "needs_review", "failed", "running", "pending", "cancelled"]
    version: str | None
    manifest_hash: str | None
    published_metrics: list[str]
    excluded_metrics: list[str]
    reused: bool
    path: str | None
