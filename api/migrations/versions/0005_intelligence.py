"""intelligence: cost snapshots, anomalies, investigations

Revision ID: 0005
Revises: 0004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORG = "NULLIF(current_setting('app.org_id', true), '')::uuid"
BYPASS = "current_setting('app.bypass_rls', true) = 'on'"
RLS_TABLES = ["item_cost_snapshot", "anomaly", "investigation"]


def upgrade() -> None:
    op.create_table(
        "item_cost_snapshot",
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("recipe_version", sa.Integer(), nullable=False),
        sa.Column("price_ex_vat_minor", sa.Integer(), nullable=False),
        sa.Column("cost_minor", sa.Integer(), nullable=False),
        sa.Column("gp_pct", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("cm_minor", sa.Integer(), nullable=False),
        sa.Column("cost_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "menu_item_id", "business_date", name="uq_item_cost_snapshot_day"),
    )
    op.create_index("ix_item_cost_snapshot_site_day", "item_cost_snapshot", ["site_id", "business_date"])
    op.create_index(op.f("ix_item_cost_snapshot_organisation_id"), "item_cost_snapshot", ["organisation_id"])
    op.create_index(op.f("ix_item_cost_snapshot_site_id"), "item_cost_snapshot", ["site_id"])

    op.create_table(
        "anomaly",
        sa.Column("detector", sa.String(length=40), nullable=False),
        sa.Column("subject", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("streak", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("weekly_impact_minor", sa.Integer(), nullable=False),
        sa.Column("dismissed_until", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("severity IN ('info', 'warning', 'critical')", name="ck_anomaly_anomaly_severity_valid"),
        sa.CheckConstraint("status IN ('open', 'investigating', 'dismissed', 'closed')", name="ck_anomaly_anomaly_status_valid"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "fingerprint", name="uq_anomaly_fingerprint"),
    )
    op.create_index("ix_anomaly_site_status", "anomaly", ["site_id", "status", "created_at"])
    op.create_index(op.f("ix_anomaly_organisation_id"), "anomaly", ["organisation_id"])
    op.create_index(op.f("ix_anomaly_site_id"), "anomaly", ["site_id"])

    op.create_table(
        "investigation",
        sa.Column("anomaly_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("finding", sa.String(length=2000), nullable=False),
        sa.Column("graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("narrative", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("draft_recommendations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("status IN ('complete', 'failed')", name="ck_investigation_investigation_status_valid"),
        sa.ForeignKeyConstraint(["anomaly_id"], ["anomaly.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_investigation_anomaly", "investigation", ["anomaly_id", "version"])
    op.create_index(op.f("ix_investigation_organisation_id"), "investigation", ["organisation_id"])
    op.create_index(op.f("ix_investigation_site_id"), "investigation", ["site_id"])

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ({BYPASS} OR organisation_id = {ORG}) "
            f"WITH CHECK ({BYPASS} OR organisation_id = {ORG})"
        )
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opspilot_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON item_cost_snapshot, anomaly, investigation TO opspilot_app;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("investigation")
    op.drop_table("anomaly")
    op.drop_table("item_cost_snapshot")
