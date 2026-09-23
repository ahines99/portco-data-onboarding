"""hardening: run leases, audit chain head, canonical audit payloads, publication keys

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_runs") as b:
        b.add_column(sa.Column("lease_owner", sa.String(length=64), nullable=True))
        b.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("audit_count", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("audit_head", sa.String(length=64), nullable=True))
    with op.batch_alter_table("audit_events") as b:
        b.add_column(sa.Column("payload_canonical", sa.Text(), nullable=True))
    with op.batch_alter_table("publications") as b:
        b.add_column(sa.Column("publication_key", sa.String(length=64), nullable=False, server_default=""))
        b.drop_constraint("uq_publications_company_manifest", type_="unique")
        b.create_unique_constraint("uq_publications_company_key", ["company_id", "publication_key"])
        b.create_unique_constraint("uq_publications_company_version", ["company_id", "version"])
    with op.batch_alter_table("publications") as b:
        b.alter_column("publication_key", server_default=None)
    if op.get_bind().dialect.name == "postgresql":
        # TRUNCATE bypasses row triggers; block it with a statement-level trigger.
        op.execute("""
            CREATE TRIGGER audit_events_no_truncate
            BEFORE TRUNCATE ON audit_events
            FOR EACH STATEMENT EXECUTE FUNCTION portco_audit_append_only();
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events")
    with op.batch_alter_table("publications") as b:
        b.drop_constraint("uq_publications_company_version", type_="unique")
        b.drop_constraint("uq_publications_company_key", type_="unique")
        b.create_unique_constraint("uq_publications_company_manifest", ["company_id", "manifest_hash"])
        b.drop_column("publication_key")
    with op.batch_alter_table("audit_events") as b:
        b.drop_column("payload_canonical")
    with op.batch_alter_table("workflow_runs") as b:
        b.drop_column("audit_head")
        b.drop_column("audit_count")
        b.drop_column("lease_expires_at")
        b.drop_column("lease_owner")
