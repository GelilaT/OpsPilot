"""flows 2-4 completion: case events, outcomes, operational memory (pgvector), notes, email delivery,
schedule runs; snapshot contribution and anomaly folding columns

Revision ID: 0007
Revises: 0006
"""

from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORG = "NULLIF(current_setting('app.org_id', true), '')::uuid"
BYPASS = "current_setting('app.bypass_rls', true) = 'on'"
NEW_TABLES = ["email_delivery", "schedule_run", "case_event", "memory_entry", "note", "recommendation_outcome"]


def upgrade() -> None:
    op.create_table('email_delivery',
    sa.Column('idempotency_key', sa.String(length=200), nullable=False),
    sa.Column('to', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('subject', sa.String(length=300), nullable=False),
    sa.Column('text', sa.String(length=20000), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=True),
    sa.Column('provider_message_id', sa.String(length=200), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.String(length=2000), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ref', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('related_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('site_id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'accepted', 'sent', 'logged', 'failed')", name=op.f('ck_email_delivery_status_valid')),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisation.id'], name=op.f('fk_email_delivery_organisation_id_organisation'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_email_delivery_site_id_site'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_delivery'))
    )
    op.create_index(op.f('ix_email_delivery_organisation_id'), 'email_delivery', ['organisation_id'], unique=False)
    op.create_index('ix_email_delivery_site_created', 'email_delivery', ['site_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_email_delivery_site_id'), 'email_delivery', ['site_id'], unique=False)
    op.create_index('uq_email_delivery_key', 'email_delivery', ['idempotency_key'], unique=True)
    op.create_table('schedule_run',
    sa.Column('site_id', sa.Uuid(), nullable=False),
    sa.Column('job', sa.String(length=60), nullable=False),
    sa.Column('local_date', sa.Date(), nullable=False),
    sa.Column('enqueued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisation.id'], name=op.f('fk_schedule_run_organisation_id_organisation'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_schedule_run_site_id_site'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_schedule_run'))
    )
    op.create_index(op.f('ix_schedule_run_organisation_id'), 'schedule_run', ['organisation_id'], unique=False)
    op.create_index('uq_schedule_run', 'schedule_run', ['site_id', 'job', 'local_date'], unique=True)
    op.create_table('case_event',
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor', sa.String(length=120), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('summary', sa.String(length=600), nullable=False),
    sa.Column('ref', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('site_id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['operations_case.id'], name=op.f('fk_case_event_case_id_operations_case'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisation.id'], name=op.f('fk_case_event_organisation_id_organisation'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_case_event_site_id_site'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_case_event'))
    )
    op.create_index('ix_case_event_case_at', 'case_event', ['case_id', 'at'], unique=False)
    op.create_index(op.f('ix_case_event_organisation_id'), 'case_event', ['organisation_id'], unique=False)
    op.create_index(op.f('ix_case_event_site_id'), 'case_event', ['site_id'], unique=False)
    op.create_table('memory_entry',
    sa.Column('case_id', sa.Uuid(), nullable=True),
    sa.Column('investigation_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('subjects', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('subject_keys', sa.ARRAY(sa.String(length=120)), nullable=False),
    sa.Column('cause_code', sa.String(length=40), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('actions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('outcome', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('occurred_on', sa.Date(), nullable=False),
    sa.Column('resolved_on', sa.Date(), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True),
    sa.Column('embedding_model', sa.String(length=80), nullable=True),
    sa.Column('embedded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('site_id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("kind IN ('investigation', 'outcome')", name=op.f('ck_memory_entry_kind_valid')),
    sa.ForeignKeyConstraint(['case_id'], ['operations_case.id'], name=op.f('fk_memory_entry_case_id_operations_case'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['investigation_id'], ['investigation.id'], name=op.f('fk_memory_entry_investigation_id_investigation'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisation.id'], name=op.f('fk_memory_entry_organisation_id_organisation'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_memory_entry_site_id_site'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memory_entry'))
    )
    op.create_index(op.f('ix_memory_entry_organisation_id'), 'memory_entry', ['organisation_id'], unique=False)
    op.create_index('ix_memory_entry_site_cause', 'memory_entry', ['site_id', 'cause_code', 'occurred_on'], unique=False)
    op.create_index(op.f('ix_memory_entry_site_id'), 'memory_entry', ['site_id'], unique=False)
    op.create_index('ix_memory_entry_subjects', 'memory_entry', ['subject_keys'], unique=False, postgresql_using='gin')
    op.create_index('uq_memory_entry_case_kind', 'memory_entry', ['case_id', 'kind'], unique=True)
    op.create_table('note',
    sa.Column('target_type', sa.String(length=20), nullable=False),
    sa.Column('target_id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=True),
    sa.Column('author', sa.String(length=120), nullable=False),
    sa.Column('text', sa.String(length=4000), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('site_id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("target_type IN ('investigation', 'recommendation', 'case')", name=op.f('ck_note_target_valid')),
    sa.ForeignKeyConstraint(['case_id'], ['operations_case.id'], name=op.f('fk_note_case_id_operations_case'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisation.id'], name=op.f('fk_note_organisation_id_organisation'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_note_site_id_site'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_note'))
    )
    op.create_index(op.f('ix_note_organisation_id'), 'note', ['organisation_id'], unique=False)
    op.create_index(op.f('ix_note_site_id'), 'note', ['site_id'], unique=False)
    op.create_index('ix_note_target', 'note', ['target_type', 'target_id'], unique=False)
    op.create_table('recommendation_outcome',
    sa.Column('recommendation_id', sa.Uuid(), nullable=False),
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('metric', sa.String(length=120), nullable=False),
    sa.Column('pre_start', sa.Date(), nullable=False),
    sa.Column('post_start', sa.Date(), nullable=False),
    sa.Column('post_end', sa.Date(), nullable=False),
    sa.Column('counterfactual', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('actual', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('effect', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('effect_pct', sa.Numeric(precision=10, scale=4), nullable=True),
    sa.Column('expected_effect', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('sigma', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('verdict', sa.String(length=16), nullable=False),
    sa.Column('facts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('site_id', sa.Uuid(), nullable=False),
    sa.Column('organisation_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("verdict IN ('improved', 'no_change', 'worsened')", name=op.f('ck_recommendation_outcome_verdict_valid')),
    sa.ForeignKeyConstraint(['case_id'], ['operations_case.id'], name=op.f('fk_recommendation_outcome_case_id_operations_case'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organisation_id'], ['organisation.id'], name=op.f('fk_recommendation_outcome_organisation_id_organisation'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recommendation_id'], ['recommendation.id'], name=op.f('fk_recommendation_outcome_recommendation_id_recommendation'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_recommendation_outcome_site_id_site'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recommendation_outcome')),
    sa.UniqueConstraint('recommendation_id', name='uq_recommendation_outcome_rec')
    )
    op.create_index(op.f('ix_recommendation_outcome_organisation_id'), 'recommendation_outcome', ['organisation_id'], unique=False)
    op.create_index(op.f('ix_recommendation_outcome_site_id'), 'recommendation_outcome', ['site_id'], unique=False)
    op.add_column('anomaly', sa.Column('parent_id', sa.Uuid(), nullable=True))
    op.add_column('anomaly', sa.Column('investigated_severity', sa.String(length=16), nullable=True))
    op.create_foreign_key(op.f('fk_anomaly_parent_id_anomaly'), 'anomaly', 'anomaly', ['parent_id'], ['id'], ondelete='SET NULL')
    op.add_column('item_cost_snapshot', sa.Column('units_sold', sa.Numeric(precision=12, scale=3), nullable=False, server_default='0'))
    op.add_column('item_cost_snapshot', sa.Column('total_contribution_minor', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('operations_case', sa.Column('expected_impact_minor', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('operations_case', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('ops_task', sa.Column('due_on', sa.Date(), nullable=True))
    op.add_column('ops_task', sa.Column('closed_note', sa.String(length=2000), nullable=True))
    op.add_column('recommendation', sa.Column('notes', sa.String(length=2000), nullable=True))
    op.add_column('recommendation', sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('recommendation_execution', sa.Column('error', sa.String(length=2000), nullable=True))
    op.add_column('recommendation_execution', sa.Column('at', sa.DateTime(timezone=True), nullable=True))

    # Approximate nearest-neighbour index for memory similarity (cosine); small lists for demo volumes.
    op.execute("CREATE INDEX ix_memory_entry_embedding ON memory_entry "
               "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)")
    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ({BYPASS} OR organisation_id = {ORG}) "
            f"WITH CHECK ({BYPASS} OR organisation_id = {ORG})"
        )
    op.execute(f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opspilot_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON {", ".join(NEW_TABLES)} TO opspilot_app;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_entry_embedding")
    op.drop_column('recommendation_execution', 'at')
    op.drop_column('recommendation_execution', 'error')
    op.drop_column('recommendation', 'executed_at')
    op.drop_column('recommendation', 'notes')
    op.drop_column('ops_task', 'closed_note')
    op.drop_column('ops_task', 'due_on')
    op.drop_column('operations_case', 'closed_at')
    op.drop_column('operations_case', 'expected_impact_minor')
    op.drop_column('item_cost_snapshot', 'total_contribution_minor')
    op.drop_column('item_cost_snapshot', 'units_sold')
    op.drop_constraint(op.f('fk_anomaly_parent_id_anomaly'), 'anomaly', type_='foreignkey')
    op.drop_column('anomaly', 'investigated_severity')
    op.drop_column('anomaly', 'parent_id')
    op.drop_index(op.f('ix_recommendation_outcome_site_id'), table_name='recommendation_outcome')
    op.drop_index(op.f('ix_recommendation_outcome_organisation_id'), table_name='recommendation_outcome')
    op.drop_table('recommendation_outcome')
    op.drop_index('ix_note_target', table_name='note')
    op.drop_index(op.f('ix_note_site_id'), table_name='note')
    op.drop_index(op.f('ix_note_organisation_id'), table_name='note')
    op.drop_table('note')
    op.drop_index('uq_memory_entry_case_kind', table_name='memory_entry')
    op.drop_index('ix_memory_entry_subjects', table_name='memory_entry', postgresql_using='gin')
    op.drop_index(op.f('ix_memory_entry_site_id'), table_name='memory_entry')
    op.drop_index('ix_memory_entry_site_cause', table_name='memory_entry')
    op.drop_index(op.f('ix_memory_entry_organisation_id'), table_name='memory_entry')
    op.drop_table('memory_entry')
    op.drop_index(op.f('ix_case_event_site_id'), table_name='case_event')
    op.drop_index(op.f('ix_case_event_organisation_id'), table_name='case_event')
    op.drop_index('ix_case_event_case_at', table_name='case_event')
    op.drop_table('case_event')
    op.drop_index('uq_schedule_run', table_name='schedule_run')
    op.drop_index(op.f('ix_schedule_run_organisation_id'), table_name='schedule_run')
    op.drop_table('schedule_run')
    op.drop_index('uq_email_delivery_key', table_name='email_delivery')
    op.drop_index(op.f('ix_email_delivery_site_id'), table_name='email_delivery')
    op.drop_index('ix_email_delivery_site_created', table_name='email_delivery')
    op.drop_index(op.f('ix_email_delivery_organisation_id'), table_name='email_delivery')
    op.drop_table('email_delivery')
