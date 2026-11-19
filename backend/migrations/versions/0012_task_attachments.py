"""task_attachment: files given to a task (or a schedule) as task-only reference material

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-06 10:30:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0012'
down_revision: str | None = '0011'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'task_attachment',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('task_id', sa.String(), nullable=True),
        sa.Column('schedule_id', sa.String(), nullable=True),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('mime', sa.String(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_task_attachment_task_id', 'task_attachment', ['task_id'])
    op.create_index('ix_task_attachment_schedule_id', 'task_attachment', ['schedule_id'])


def downgrade() -> None:
    op.drop_index('ix_task_attachment_schedule_id', table_name='task_attachment')
    op.drop_index('ix_task_attachment_task_id', table_name='task_attachment')
    op.drop_table('task_attachment')
