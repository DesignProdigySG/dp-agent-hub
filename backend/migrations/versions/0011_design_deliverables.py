"""design_deliverable: versioned Designer outputs (landing pages, emails, form specs)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-06 00:30:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table(
        'design_deliverable',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('html', sa.Text(), nullable=False),
        sa.Column('subject', sa.String(), nullable=False),
        sa.Column('preheader', sa.String(), nullable=False),
        sa.Column('spec', JSONB, nullable=False),
        sa.Column('marketo', JSONB, nullable=False),
        sa.Column('checks', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_design_deliverable_task_id', 'design_deliverable', ['task_id'])


def downgrade() -> None:
    op.drop_index('ix_design_deliverable_task_id', table_name='design_deliverable')
    op.drop_table('design_deliverable')
