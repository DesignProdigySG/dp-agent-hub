"""task_message: the conversation on a task (people and agents)

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-17 16:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0016'
down_revision: str | None = '0015'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'task_message',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('author_id', sa.String(), nullable=False),
        sa.Column('author_name', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_task_message_task_id', 'task_message', ['task_id'])
    op.create_index('ix_task_message_created_at', 'task_message', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_task_message_created_at', table_name='task_message')
    op.drop_index('ix_task_message_task_id', table_name='task_message')
    op.drop_table('task_message')
