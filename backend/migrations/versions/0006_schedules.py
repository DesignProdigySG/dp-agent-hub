"""recurring tasks: schedule table, task.schedule_id

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05 18:10:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')
S = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    op.add_column('task', sa.Column('schedule_id', S(), nullable=True))
    op.create_index('ix_task_schedule_id', 'task', ['schedule_id'])
    op.create_table(
        'schedule',
        sa.Column('id', S(), nullable=False),
        sa.Column('agent_id', S(), nullable=False),
        sa.Column('title', S(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('params', JSONB, nullable=False),
        sa.Column('kind', S(), nullable=False),
        sa.Column('every_minutes', sa.Integer(), nullable=False),
        sa.Column('at_time', S(), nullable=False),
        sa.Column('weekdays', JSONB, nullable=False),
        sa.Column('tz', S(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_task_id', S(), nullable=True),
        sa.Column('last_note', S(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_schedule_agent_id', 'schedule', ['agent_id'])
    op.create_index('ix_schedule_next_run_at', 'schedule', ['next_run_at'])


def downgrade() -> None:
    op.drop_index('ix_schedule_next_run_at', table_name='schedule')
    op.drop_index('ix_schedule_agent_id', table_name='schedule')
    op.drop_table('schedule')
    op.drop_index('ix_task_schedule_id', table_name='task')
    op.drop_column('task', 'schedule_id')
