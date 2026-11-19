"""data health scan: health_scan, lead_mirror, lead_activity_agg, lead_health, value_map,
verification_result

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-05 20:30:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')
S = sqlmodel.sql.sqltypes.AutoString
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        'health_scan',
        sa.Column('id', S(), nullable=False),
        sa.Column('task_id', S(), nullable=False),
        sa.Column('agent_id', S(), nullable=False),
        sa.Column('status', S(), nullable=False),
        sa.Column('phase', S(), nullable=False),
        sa.Column('params', JSONB, nullable=False),
        sa.Column('cursor', JSONB, nullable=False),
        sa.Column('counts', JSONB, nullable=False),
        sa.Column('kpis', JSONB, nullable=False),
        sa.Column('report', sa.Text(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('started_at', TZ, nullable=False),
        sa.Column('updated_at', TZ, nullable=False),
        sa.Column('finished_at', TZ, nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_health_scan_task_id', 'health_scan', ['task_id'])
    op.create_index('ix_health_scan_agent_id', 'health_scan', ['agent_id'])
    op.create_index('ix_health_scan_status', 'health_scan', ['status'])
    op.create_table(
        'lead_mirror',
        sa.Column('lead_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('data', JSONB, nullable=False),
        sa.Column('scan_id', S(), nullable=False),
        sa.Column('synced_at', TZ, nullable=False),
        sa.PrimaryKeyConstraint('lead_id'),
    )
    op.create_index('ix_lead_mirror_scan_id', 'lead_mirror', ['scan_id'])
    op.create_table(
        'lead_activity_agg',
        sa.Column('scan_id', S(), nullable=False),
        sa.Column('lead_id', sa.BigInteger(), autoincrement=False, nullable=False),
        *[sa.Column(c, sa.Integer(), nullable=False) for c in
          ('opens', 'clicks', 'forms', 'visits', 'hard_bounces', 'soft_bounces')],
        sa.Column('last_activity_at', TZ, nullable=True),
        sa.Column('last_engaged_at', TZ, nullable=True),
        sa.PrimaryKeyConstraint('scan_id', 'lead_id'),
    )
    op.create_table(
        'lead_health',
        sa.Column('scan_id', S(), nullable=False),
        sa.Column('lead_id', sa.BigInteger(), autoincrement=False, nullable=False),
        *[sa.Column(c, sa.Integer(), nullable=False) for c in
          ('uniqueness', 'completeness', 'normalization', 'accuracy', 'contactability',
           'recency', 'engagement', 'overall')],
        sa.Column('engagement_level', S(), nullable=False),
        sa.Column('dup_group', S(), nullable=False),
        sa.Column('dup_role', S(), nullable=False),
        sa.Column('issues', JSONB, nullable=False),
        sa.Column('created_year', sa.Integer(), nullable=True),
        sa.Column('source', S(), nullable=False),
        sa.PrimaryKeyConstraint('scan_id', 'lead_id'),
    )
    op.create_index('ix_lead_health_scan_overall', 'lead_health', ['scan_id', 'overall'])
    op.create_table(
        'value_map',
        sa.Column('field', S(), nullable=False),
        sa.Column('raw', S(), nullable=False),
        sa.Column('standard', S(), nullable=False),
        sa.Column('source', S(), nullable=False),
        sa.Column('updated_at', TZ, nullable=False),
        sa.PrimaryKeyConstraint('field', 'raw'),
    )
    op.create_table(
        'verification_result',
        sa.Column('kind', S(), nullable=False),
        sa.Column('value', S(), nullable=False),
        sa.Column('provider', S(), nullable=False),
        sa.Column('status', S(), nullable=False),
        sa.Column('usable', sa.Boolean(), nullable=False),
        sa.Column('data', JSONB, nullable=False),
        sa.Column('checked_at', TZ, nullable=False),
        sa.PrimaryKeyConstraint('kind', 'value'),
    )


def downgrade() -> None:
    op.drop_table('verification_result')
    op.drop_table('value_map')
    op.drop_index('ix_lead_health_scan_overall', table_name='lead_health')
    op.drop_table('lead_health')
    op.drop_table('lead_activity_agg')
    op.drop_index('ix_lead_mirror_scan_id', table_name='lead_mirror')
    op.drop_table('lead_mirror')
    for ix in ('status', 'agent_id', 'task_id'):
        op.drop_index(f'ix_health_scan_{ix}', table_name='health_scan')
    op.drop_table('health_scan')
