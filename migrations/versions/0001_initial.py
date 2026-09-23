"""initial workflow state schema

Revision ID: 0001
Revises:
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("project_type", sa.String(length=64), nullable=False),
        sa.Column("company_id", sa.String(length=128), nullable=False),
        sa.Column("connection_id", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("gate", sa.String(length=64), nullable=True),
        sa.Column("stop_after", sa.String(length=64), nullable=True),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column(
            "pending_items",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "error", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_workflow_runs")),
    )
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workflow_runs_company_id"), ["company_id"], unique=False)

    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("gate", sa.String(length=64), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "decisions", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("reviewer", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.run_id"], name=op.f("fk_approvals_run_id_workflow_runs")),
        sa.PrimaryKeyConstraint("approval_id", name=op.f("pk_approvals")),
    )
    with op.batch_alter_table("approvals", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_approvals_run_id"), ["run_id"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "payload", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["workflow_runs.run_id"], name=op.f("fk_audit_events_run_id_workflow_runs")
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_audit_events")),
    )
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_events_run_id"), ["run_id"], unique=False)

    op.create_table(
        "publications",
        sa.Column("publication_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.String(length=128), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "receipt", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["workflow_runs.run_id"], name=op.f("fk_publications_run_id_workflow_runs")
        ),
        sa.PrimaryKeyConstraint("publication_id", name=op.f("pk_publications")),
        sa.UniqueConstraint("company_id", "manifest_hash", name="uq_publications_company_manifest"),
    )
    op.create_table(
        "step_runs",
        sa.Column(
            "step_run_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output_ref", sa.String(length=64), nullable=True),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.run_id"], name=op.f("fk_step_runs_run_id_workflow_runs")),
        sa.PrimaryKeyConstraint("step_run_id", name=op.f("pk_step_runs")),
        sa.UniqueConstraint("run_id", "step", "attempt", name="uq_step_runs_run_step_attempt"),
    )
    with op.batch_alter_table("step_runs", schema=None) as batch_op:
        batch_op.create_index("ix_step_runs_lookup", ["run_id", "step", "input_hash"], unique=False)

    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_run_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.run_id"], name=op.f("fk_artifacts_run_id_workflow_runs")),
        sa.ForeignKeyConstraint(
            ["step_run_id"], ["step_runs.step_run_id"], name=op.f("fk_artifacts_step_run_id_step_runs")
        ),
        sa.PrimaryKeyConstraint("artifact_id", name=op.f("pk_artifacts")),
    )
    with op.batch_alter_table("artifacts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_artifacts_run_id"), ["run_id"], unique=False)

    op.create_table(
        "evidence",
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_run_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_ref", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.run_id"], name=op.f("fk_evidence_run_id_workflow_runs")),
        sa.ForeignKeyConstraint(
            ["step_run_id"], ["step_runs.step_run_id"], name=op.f("fk_evidence_step_run_id_step_runs")
        ),
        sa.PrimaryKeyConstraint("evidence_id", name=op.f("pk_evidence")),
    )
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_evidence_run_id"), ["run_id"], unique=False)

    op.create_table(
        "findings",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_run_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("finding_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "assumptions", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column(
            "metadata", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.run_id"], name=op.f("fk_findings_run_id_workflow_runs")),
        sa.ForeignKeyConstraint(
            ["step_run_id"], ["step_runs.step_run_id"], name=op.f("fk_findings_step_run_id_step_runs")
        ),
        sa.PrimaryKeyConstraint("finding_id", name=op.f("pk_findings")),
    )
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_findings_run_id"), ["run_id"], unique=False)

    op.create_table(
        "finding_evidence",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["evidence.evidence_id"], name=op.f("fk_finding_evidence_evidence_id_evidence")
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"], ["findings.finding_id"], name=op.f("fk_finding_evidence_finding_id_findings")
        ),
        sa.PrimaryKeyConstraint("finding_id", "evidence_id", "relation", name=op.f("pk_finding_evidence")),
    )

    # POD-203: the audit log is append-only. On PostgreSQL this is enforced in the database.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION portco_audit_append_only() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_events is append-only';
            END;
            $$ LANGUAGE plpgsql;
        """)
        op.execute("""
            CREATE TRIGGER audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION portco_audit_append_only();
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
        op.execute("DROP FUNCTION IF EXISTS portco_audit_append_only()")
    op.drop_table("finding_evidence")
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_findings_run_id"))

    op.drop_table("findings")
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_evidence_run_id"))

    op.drop_table("evidence")
    with op.batch_alter_table("artifacts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artifacts_run_id"))

    op.drop_table("artifacts")
    with op.batch_alter_table("step_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_step_runs_lookup")

    op.drop_table("step_runs")
    op.drop_table("publications")
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_events_run_id"))

    op.drop_table("audit_events")
    with op.batch_alter_table("approvals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_approvals_run_id"))

    op.drop_table("approvals")
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_runs_company_id"))

    op.drop_table("workflow_runs")
