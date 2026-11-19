"""lead_health.reach and free_email: the channels each lead can be reached on

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05 21:10:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('lead_health', sa.Column('reach', sqlmodel.sql.sqltypes.AutoString(),
                                           nullable=False, server_default=''))
    op.add_column('lead_health', sa.Column('free_email', sa.Boolean(), nullable=False,
                                           server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('lead_health', 'free_email')
    op.drop_column('lead_health', 'reach')
