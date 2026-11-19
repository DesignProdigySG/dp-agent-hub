"""remove built-in agents

Every agent is now configured in the editor and runs the tool-calling graph, so the six
built-in rows and the `kind` column go. Their open tasks are failed and pending approvals
rejected (their paused runs can't resume); finished tasks, runs and the audit log are kept.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05 11:30:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUILTINS = "(select id from agent_def where kind = 'builtin')"


def upgrade() -> None:
    op.execute(f"""
        update task set status = 'FAILED', result = 'Agent removed: built-in agents were retired',
               updated_at = now()
        where status in ('QUEUED', 'IN_PROGRESS', 'NEEDS_APPROVAL') and agent_id in {BUILTINS}
    """)
    op.execute(f"""
        update approval set status = 'REJECTED', comment = 'Agent removed', decided_at = now()
        where status = 'PENDING' and agent_id in {BUILTINS}
    """)
    op.execute("delete from agent_def where kind = 'builtin'")
    op.drop_column('agent_def', 'kind')


def downgrade() -> None:
    # The built-in agents themselves are gone from the code; only the column comes back.
    op.add_column('agent_def', sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(),
                                         nullable=False, server_default='custom'))
