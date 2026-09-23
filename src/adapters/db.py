"""Relational schema for workflow state (POD-201). Portable across PostgreSQL and SQLite."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

JsonType = JSON().with_variant(JSONB(), "postgresql")
BigId = BigInteger().with_variant(Integer(), "sqlite")
TS = DateTime(timezone=True)

workflow_runs = Table(
    "workflow_runs",
    metadata,
    Column("run_id", Uuid, primary_key=True),
    Column("project_type", String(64), nullable=False),
    Column("company_id", String(128), nullable=False, index=True),
    Column("connection_id", String(256), nullable=False),
    Column("status", String(32), nullable=False),
    Column("current_step", String(64)),
    Column("gate", String(64)),
    Column("stop_after", String(64)),
    Column("requested_by", String(128), nullable=False),
    Column("pending_items", JsonType, nullable=False, default=list),
    Column("error", JsonType),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
)

step_runs = Table(
    "step_runs",
    metadata,
    Column("step_run_id", BigId, primary_key=True, autoincrement=True),
    Column("run_id", Uuid, ForeignKey("workflow_runs.run_id"), nullable=False),
    Column("step", String(64), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("input_hash", String(64), nullable=False),
    Column("output_ref", String(64)),
    Column("output_hash", String(64)),
    Column("active", Boolean, nullable=False, default=True),
    Column("started_at", TS, nullable=False),
    Column("finished_at", TS),
    Column("error_code", String(64)),
    Column("error_detail", Text),
    UniqueConstraint("run_id", "step", "attempt", name="uq_step_runs_run_step_attempt"),
    Index("ix_step_runs_lookup", "run_id", "step", "input_hash"),
)

evidence = Table(
    "evidence",
    metadata,
    Column("evidence_id", Uuid, primary_key=True),
    Column("run_id", Uuid, ForeignKey("workflow_runs.run_id"), nullable=False, index=True),
    Column("step_run_id", BigId, ForeignKey("step_runs.step_run_id")),
    Column("source_uri", Text, nullable=False),
    Column("source_type", String(64), nullable=False),
    Column("as_of", TS),
    Column("retrieved_at", TS, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("payload_ref", String(64), nullable=False),
    Column("metadata", JsonType, nullable=False, default=dict),
)

findings = Table(
    "findings",
    metadata,
    Column("finding_id", Uuid, primary_key=True),
    Column("run_id", Uuid, ForeignKey("workflow_runs.run_id"), nullable=False, index=True),
    Column("step_run_id", BigId, ForeignKey("step_runs.step_run_id")),
    Column("step", String(64), nullable=False),
    Column("code", String(64), nullable=False),
    Column("finding_type", String(32), nullable=False),
    Column("title", Text, nullable=False),
    Column("statement", Text, nullable=False),
    Column("confidence", String(16), nullable=False),
    Column("status", String(32), nullable=False),
    Column("assumptions", JsonType, nullable=False, default=list),
    Column("metadata", JsonType, nullable=False, default=dict),
    Column("created_at", TS, nullable=False),
)

finding_evidence = Table(
    "finding_evidence",
    metadata,
    Column("finding_id", Uuid, ForeignKey("findings.finding_id"), primary_key=True),
    Column("evidence_id", Uuid, ForeignKey("evidence.evidence_id"), primary_key=True),
    Column("relation", String(32), primary_key=True),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("event_id", BigId, primary_key=True, autoincrement=True),
    Column("run_id", Uuid, ForeignKey("workflow_runs.run_id"), nullable=False, index=True),
    Column("step", String(64), nullable=False),
    Column("actor", String(128), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("payload", JsonType, nullable=False, default=dict),
    Column("created_at", TS, nullable=False),
    Column("prev_hash", String(64)),
    Column("event_hash", String(64), nullable=False),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("artifact_id", Uuid, primary_key=True),
    Column("run_id", Uuid, ForeignKey("workflow_runs.run_id"), nullable=False, index=True),
    Column("step_run_id", BigId, ForeignKey("step_runs.step_run_id")),
    Column("kind", String(64), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("uri", Text, nullable=False),
    Column("schema_version", String(8), nullable=False),
    Column("created_at", TS, nullable=False),
)

approvals = Table(
    "approvals",
    metadata,
    Column("approval_id", Uuid, primary_key=True),
    Column("run_id", Uuid, ForeignKey("workflow_runs.run_id"), nullable=False, index=True),
    Column("gate", String(64), nullable=False),
    Column("subject_hash", String(64), nullable=False),
    Column("decisions", JsonType, nullable=False),
    Column("reviewer", String(128), nullable=False),
    Column("role", String(32), nullable=False),
    Column("comment", Text),
    Column("created_at", TS, nullable=False),
    Column("expires_at", TS),
    Column("revoked_at", TS),
    Column("revoked_reason", Text),
)

publications = Table(
    "publications",
    metadata,
    Column("publication_id", Uuid, primary_key=True),
    Column("company_id", String(128), nullable=False),
    Column("manifest_hash", String(64), nullable=False),
    Column("version", String(32), nullable=False),
    Column("run_id", Uuid, ForeignKey("workflow_runs.run_id"), nullable=False),
    Column("receipt", JsonType, nullable=False),
    Column("created_at", TS, nullable=False),
    UniqueConstraint("company_id", "manifest_hash", name="uq_publications_company_manifest"),
)


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True)
