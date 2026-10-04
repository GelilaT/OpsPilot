"""action centre: cases, recommendations, executions

Revision ID: 0006
Revises: 0005
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORG = "NULLIF(current_setting('app.org_id', true), '')::uuid"
BYPASS = "current_setting('app.bypass_rls', true) = 'on'"
RLS_TABLES = [
    "operations_case",
    "recommendation",
    "recommendation_transition",
    "recommendation_execution",
    "ops_task",
]


def upgrade() -> None:
    op.create_table(
        "operations_case",
        sa.Column("anomaly_id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("closed_reason", sa.String(length=400), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('detected', 'investigating', 'awaiting_approval', 'executing', 'monitoring', 'closed')",
            name="ck_operations_case_operations_case_status_valid",
        ),
        sa.ForeignKeyConstraint(["anomaly_id"], ["anomaly.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigation.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("anomaly_id", name="uq_operations_case_anomaly"),
    )
    op.create_index("ix_operations_case_site_status", "operations_case", ["site_id", "status", "updated_at"])
    op.create_index(op.f("ix_operations_case_organisation_id"), "operations_case", ["organisation_id"])
    op.create_index(op.f("ix_operations_case_site_id"), "operations_case", ["site_id"])

    op.create_table(
        "recommendation",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("subject", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expected_impact_minor", sa.BigInteger(), nullable=False),
        sa.Column("impact_inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Numeric(), nullable=False),
        sa.Column("risk", sa.String(length=8), nullable=False),
        sa.Column("required_role", sa.String(length=20), nullable=False),
        sa.Column("evidence_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("success_metric", sa.String(length=120), nullable=True),
        sa.Column("follow_up_at", sa.Date(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.String(length=120), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(length=600), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "type IN ('purchase_order', 'supplier_switch', 'par_level_change', 'price_review', "
            "'staffing_change', 'waste_reduction', 'investigate_task')",
            name="ck_recommendation_recommendation_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'proposed', 'approved', 'rejected', 'expired', 'superseded', "
            "'executing', 'completed', 'failed', 'follow_up', 'outcome_measured')",
            name="ck_recommendation_recommendation_status_valid",
        ),
        sa.CheckConstraint("risk IN ('low', 'medium', 'high')", name="ck_recommendation_recommendation_risk_valid"),
        sa.CheckConstraint(
            "required_role IN ('owner', 'general_manager', 'head_chef', 'shift_manager')",
            name="ck_recommendation_recommendation_role_valid",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["operations_case.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigation.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendation_case", "recommendation", ["case_id", "status"])
    op.create_index("ix_recommendation_site_status", "recommendation", ["site_id", "status", "created_at"])
    op.create_index(op.f("ix_recommendation_organisation_id"), "recommendation", ["organisation_id"])
    op.create_index(op.f("ix_recommendation_site_id"), "recommendation", ["site_id"])

    op.create_table(
        "recommendation_transition",
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.String(length=600), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendation_transition_rec", "recommendation_transition", ["recommendation_id", "at"])
    op.create_index(op.f("ix_recommendation_transition_organisation_id"), "recommendation_transition", ["organisation_id"])
    op.create_index(op.f("ix_recommendation_transition_site_id"), "recommendation_transition", ["site_id"])

    op.create_table(
        "recommendation_execution",
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_version", sa.Integer(), nullable=False),
        sa.Column("executor", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_recommendation_execution_key"),
    )
    op.create_index("ix_recommendation_execution_rec", "recommendation_execution", ["recommendation_id"])
    op.create_index(op.f("ix_recommendation_execution_organisation_id"), "recommendation_execution", ["organisation_id"])
    op.create_index(op.f("ix_recommendation_execution_site_id"), "recommendation_execution", ["site_id"])

    op.create_table(
        "ops_task",
        sa.Column("recommendation_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("assignee_role", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["site.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ops_task_site_status", "ops_task", ["site_id", "status"])
    op.create_index(op.f("ix_ops_task_organisation_id"), "ops_task", ["organisation_id"])
    op.create_index(op.f("ix_ops_task_site_id"), "ops_task", ["site_id"])

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
                GRANT SELECT, INSERT, UPDATE, DELETE ON operations_case, recommendation,
                    recommendation_transition, recommendation_execution, ops_task TO opspilot_app;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("ops_task")
    op.drop_table("recommendation_execution")
    op.drop_table("recommendation_transition")
    op.drop_table("recommendation")
    op.drop_table("operations_case")
