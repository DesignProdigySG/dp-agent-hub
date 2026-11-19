"""marketo_change: what agents created or changed in Marketo, for links back to it

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-06 18:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0014'
down_revision: str | None = '0013'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'marketo_change',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('task_id', sa.String(), nullable=True),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('object_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_marketo_change_task_id', 'marketo_change', ['task_id'])
    op.create_index('ix_marketo_change_agent_id', 'marketo_change', ['agent_id'])
    op.create_index('ix_marketo_change_created_at', 'marketo_change', ['created_at'])


def downgrade() -> None:
    for c in ('created_at', 'agent_id', 'task_id'):
        op.drop_index(f'ix_marketo_change_{c}', table_name='marketo_change')
    op.drop_table('marketo_change')
