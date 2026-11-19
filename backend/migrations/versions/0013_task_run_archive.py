"""task.run, task.history, task.archived_at: run a finished task again, and archive tasks

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-06 14:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0013'
down_revision: str | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.add_column('task', sa.Column('run', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('task', sa.Column('history', JSONB, nullable=False, server_default='[]'))
    op.add_column('task', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_task_archived_at', 'task', ['archived_at'])


def downgrade() -> None:
    op.drop_index('ix_task_archived_at', table_name='task')
    op.drop_column('task', 'archived_at')
    op.drop_column('task', 'history')
    op.drop_column('task', 'run')
