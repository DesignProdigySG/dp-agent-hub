"""scene_layout.version and scene_layout_version: no silent overwrites, restorable history

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-05 23:30:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.add_column('scene_layout', sa.Column('version', sa.Integer(), nullable=False,
                                            server_default='1'))
    op.create_table(
        'scene_layout_version',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('pieces', JSONB, nullable=False),
        sa.Column('saved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('replaced_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('scene_layout_version')
    op.drop_column('scene_layout', 'version')
