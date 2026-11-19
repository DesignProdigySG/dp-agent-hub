"""workflow agents: agent_def.workflow, workflow_log, side_effect

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05 15:30:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.add_column('agent_def', sa.Column('workflow', sqlmodel.sql.sqltypes.AutoString(),
                                         nullable=False, server_default=''))
    op.create_table(
        'workflow_log',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                  autoincrement=True, nullable=False),
        sa.Column('workflow', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('run_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('thread_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('item_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('action', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('tool_result', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('data', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    for col in ('workflow', 'run_id', 'thread_id'):
        op.create_index(f'ix_workflow_log_{col}', 'workflow_log', [col])
    op.create_table(
        'side_effect',
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('result', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('side_effect')
    for col in ('workflow', 'run_id', 'thread_id'):
        op.drop_index(f'ix_workflow_log_{col}', table_name='workflow_log')
    op.drop_table('workflow_log')
    op.drop_column('agent_def', 'workflow')
