"""Relational schema for workflow state (POD-201). Portable across PostgreSQL and SQLite."""

from __future__ import annotations

import traceback
from typing import Any

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
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import NullPool

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
    # Execution lease: only the holder may advance the run; an expired lease can be reclaimed (audit M5).
    Column("lease_owner", String(64)),
    Column("lease_expires_at", TS),
    # Audit chain head, updated in the same transaction as each append, so tail truncation is detectable.
    Column("audit_count", Integer, nullable=False, server_default="0"),
    Column("audit_head", String(64)),
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
    # Exact canonical JSON the hash was computed over (JSONB may re-render numbers).
    Column("payload_canonical", Text),
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
    # hash(manifest, excluded metrics, certification id): what exactly was published, under which approval.
    Column("publication_key", String(64), nullable=False),
    Column("version", String(32), nullable=False),
    Column("run_id", Uuid, ForeignKey("workflow_runs.run_id"), nullable=False),
    Column("receipt", JsonType, nullable=False),
    Column("state", String(16), nullable=False, server_default="complete"),
    Column("created_at", TS, nullable=False),
    UniqueConstraint("company_id", "publication_key", name="uq_publications_company_key"),
    UniqueConstraint("company_id", "version", name="uq_publications_company_version"),
)


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_timeout=5, connect_args={"connect_timeout": 5})


# --------------------------------------------------------------------------- migration / readiness sessions

# Explicit deadlines for schema migration (audit DEL-02): a missing PostgreSQL connect_timeout, lock_timeout or
# statement_timeout means "wait forever". They apply to the migration session only, never to application clients.
MIGRATION_CONNECT_TIMEOUT_S = 10
MIGRATION_LOCK_TIMEOUT_MS = 15_000
MIGRATION_STATEMENT_TIMEOUT_MS = 300_000


def escape_alembic_url(url: str) -> str:
    """`url` escaped for Alembic's ConfigParser-backed `Config.set_main_option` (`%` -> `%%`).

    Percent-encoded passwords (`%40`, `%25`) and paths containing `%` otherwise fail interpolation,
    and ConfigParser's error message echoes the whole URL, credentials included.
    """
    return url.replace("%", "%%")


def migration_connect_args(url: str) -> dict[str, Any]:
    """Connection deadline for the migration engine: libpq `connect_timeout` or the SQLite busy timeout."""
    if url.startswith("sqlite"):
        return {"timeout": MIGRATION_LOCK_TIMEOUT_MS / 1000}
    return {"connect_timeout": MIGRATION_CONNECT_TIMEOUT_S}


def set_session_deadlines(conn: Connection, *, statement_ms: int, lock_ms: int, local: bool = False) -> None:
    """Bound statement run time and lock waits on this PostgreSQL session only (no-op on SQLite).

    `local=True` scopes the settings to the current transaction (`SET LOCAL`), so a pooled connection
    goes back to the pool with the server defaults.
    """
    if conn.dialect.name != "postgresql":
        return
    scope = "LOCAL " if local else ""
    conn.exec_driver_sql(f"SET {scope}lock_timeout = {int(lock_ms)}")
    conn.exec_driver_sql(f"SET {scope}statement_timeout = {int(statement_ms)}")


def make_probe_engine(url: str, *, connect_timeout_s: int) -> Engine:
    """A separately budgeted, unpooled engine for health probes: it never queues behind application work."""
    return create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": max(2, connect_timeout_s)})


def redact_db_error(exc: BaseException, url: str) -> str | None:
    """A credential-free description of `exc`, or None when its rendered traceback holds no secret from `url`.

    Checks the whole chain (causes and contexts), and both the encoded and decoded password forms.
    """
    try:
        parsed = make_url(url)
        password = parsed.password
    except Exception:
        parsed, password = None, None
    secrets = {url}
    if password:
        secrets |= {str(password), url.split("://", 1)[-1].split("@", 1)[0].rsplit(":", 1)[-1]}
    secrets.discard("")
    rendered = "".join(traceback.format_exception(exc))
    if not any(s in rendered for s in secrets):
        return None
    message = str(exc)
    for s in sorted(secrets, key=len, reverse=True):
        message = message.replace(s, "***")
    target = parsed.render_as_string(hide_password=True) if parsed is not None else "the configured database"
    return f"{type(exc).__qualname__} while migrating {target}: {message}"
