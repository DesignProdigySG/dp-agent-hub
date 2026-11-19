"""agent_report: the standard per-run report (headline + KPI values) of every agent

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-05 22:40:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table(
        'agent_report',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('task_id', sa.String(), nullable=True),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('headline', sa.Text(), nullable=False),
        sa.Column('kpis', JSONB, nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_report_agent_at', 'agent_report', ['agent_id', 'at'])


def downgrade() -> None:
    op.drop_index('ix_agent_report_agent_at', table_name='agent_report')
    op.drop_table('agent_report')
