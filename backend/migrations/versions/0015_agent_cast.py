"""agent_def.character: each role's agent gets its own cast model

The models live in frontend/public/assets/characters.
Matched on the agent's id or name, so renamed copies of a role get theirs too.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-16 17:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0015'
down_revision: str | None = '0014'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (word in the id or name, cast model); first match wins
CAST = [
    ('doctor', 'the-data-doctor'),
    ('qualif', 'the-qualifier'),
    ('design', 'the-designer'),
    ('investigat', 'the-private-investigator'),
    ('campaign', 'the-campaigner'),
    ('audit', 'the-auditor'),
]


def upgrade() -> None:
    conn = op.get_bind()
    for agent_id, name in conn.execute(sa.text("SELECT id, name FROM agent_def")).all():
        key = f"{agent_id} {name}".lower()
        model = next((m for word, m in CAST if word in key), None)
        if model:
            conn.execute(sa.text("UPDATE agent_def SET character = :c WHERE id = :i"),
                         {"c": model, "i": agent_id})


def downgrade() -> None:
    op.execute("UPDATE agent_def SET character = '' WHERE character LIKE 'the-%'")
