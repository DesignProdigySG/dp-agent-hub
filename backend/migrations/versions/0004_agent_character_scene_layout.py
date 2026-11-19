"""agent character, scene layout

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05 12:20:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('agent_def', sa.Column('character', sqlmodel.sql.sqltypes.AutoString(),
                                         nullable=False, server_default=''))
    op.create_table(
        'scene_layout',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('pieces', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()),
                                                   'postgresql'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('scene_layout')
    op.drop_column('agent_def', 'character')
