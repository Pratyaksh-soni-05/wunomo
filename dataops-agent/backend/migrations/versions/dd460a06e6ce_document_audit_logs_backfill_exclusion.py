"""document audit_logs backfill exclusion

Revision ID: dd460a06e6ce
Revises: aa4569de4785
Create Date: 2026-09-22 19:06:11.677102

Integration Phase 2: the decision record for a cross-branch collision found
while merging pratyaksh-workforce onto master.

d7c4e29a1f83 (Wunomo Projects Phase 0, 2026-09-02, his branch) backfills
agent_id onto pre-existing rows in four tables so history reads correctly
once "AXIOM" becomes a real agent_instances row instead of a hardcoded
singleton. Written well before master's Item #9 (audit-log tamper-evidence,
migration a7c2e9f1b3d4, 2026-09-13) existed on his branch's own timeline --
at the time, updating audit_logs.agent_id was completely ordinary.

Once both branches merged onto one chain, that UPDATE became impossible:
a7c2e9f1b3d4's BEFORE UPDATE OR DELETE trigger on audit_logs rejects the
write for every role, no exception, by design -- and because the update
ran last inside d7c4e29a1f83's own transaction, its failure was rolling
back that migration's harmless work too (the AXIOM INSERT, and the
tasks/chat_messages/llm_usage_events backfills).

DECISION: Option 1 -- do not backfill historical audit_logs rows. The
append-only guarantee takes precedence over backfill completeness for
this one column. d7c4e29a1f83 was edited directly (not superseded here)
to drop audit_logs from its backfill loop, in both upgrade() and
downgrade() -- safe because that migration has never been applied to any
real database (confirmed via `alembic current` before the edit: every
environment this branch has run in sat at e5a9c3d7b2f1, master's
pre-merge head), so there is no shipped `alembic_version` bookkeeping
anywhere for this edit to desync.

This migration is the permanent record of that decision, at the schema
level where a future reader would actually see it -- not just in a
migration docstring or GOTCHAS.md (both also updated). No data is
touched; COMMENT ON COLUMN is metadata only and is not subject to the
append-only trigger (it targets pg_description, not the table's own
rows).

GENERAL LESSON, for the next migration collision like this one: a
migration written before a security invariant existed can violate that
invariant the moment the two branches share a chain. Any migration that
writes to a security-guarded table (audit_logs' append-only trigger,
Row-Level Security policies, anything with a BEFORE trigger) needs a
fresh look at merge time, not just a fresh `alembic merge heads` -- the
schema graph is compatible; the runtime behavior on already-existing
rows may not be.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'dd460a06e6ce'
down_revision: Union[str, None] = 'aa4569de4785'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        COMMENT ON COLUMN audit_logs.agent_id IS
        'Nullable by design. Rows written before Wunomo Projects Phase 0 '
        '(2026-09-02) keep this NULL permanently -- Item #9''s append-only '
        'trigger (a7c2e9f1b3d4) blocks any UPDATE to this table for every '
        'role, so historical rows were deliberately never backfilled. See '
        'migration dd460a06e6ce and docs/context/GOTCHAS.md.'
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("COMMENT ON COLUMN audit_logs.agent_id IS NULL"))
