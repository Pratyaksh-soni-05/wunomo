"""backfill_agent_sources_for_existing_agents

Revision ID: 480d5b8245f3
Revises: d7c4e29a1f83
Create Date: 2026-09-03 00:00:00.000000

Wunomo Projects Phase 1, part one (intersection permission enforcement) --
data migration, not schema. agent_sources has existed since Phase 0 but has
never had a single row written to it anywhere in this codebase: not by the
Phase 0 backfill (which only created agent_instances rows), not by
register_data_source, nowhere.

This matters now because Phase 1 makes agent scope a real, fail-closed
enforcement boundary: an agent with zero agent_sources rows is now treated
as having NO scope (denied everything), not "unscoped" (allowed
everything). Without this migration, every existing AXIOM instance --
every tenant's only agent today -- would go from "can touch every source
in its tenant" to "can touch nothing" the moment enforcement code ships,
for literally every one of this dev DB's 16,000+ tenants. That is not a
tightening, it's an outage.

The fix: for every agent instance that exists today, grant it every data
source that already exists in its own tenant -- preserving today's real
behavior (AXIOM can already touch any of its tenant's sources, with no
existing filter anywhere in agent/tools/ingestion_tools.py or elsewhere by
is_active or any other flag) exactly, rather than narrowing it as a side
effect of making the boundary real. Deliberately not scoped to name='AXIOM'
specifically -- the mechanism is "every agent instance gets its tenant's
sources," which happens to mean AXIOM today only because AXIOM is the only
agent instance that exists; this migration doesn't need to know that.

Set-based, matching the Phase 0 backfill's own reasoning: a per-tenant
Python loop is the wrong shape at this scale. gen_random_uuid() used the
same way that migration used it, for the same reason.

This is a POLICY DECISION, not just a technical backfill -- confirmed with
the person who owns this call before writing this migration: newly created
sources (registered AFTER this migration runs) are deliberately NOT
auto-granted to any agent going forward, including AXIOM. See the
CLAUDE.md/GOTCHAS entries this same commit adds for the reasoning (silent
scope auto-expansion is the same problem as no scope at all, just slower)
and how the resulting "AXIOM can't see a source I just connected" state is
made legible rather than a mysterious permission error.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '480d5b8245f3'
down_revision: Union[str, None] = 'd7c4e29a1f83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO agent_sources (id, agent_id, source_id, created_at)
        SELECT gen_random_uuid()::text, ai.id, ds.id, now()
        FROM agent_instances ai
        JOIN data_sources ds ON ds.tenant_id = ai.tenant_id
        WHERE NOT EXISTS (
            SELECT 1 FROM agent_sources existing
            WHERE existing.agent_id = ai.id AND existing.source_id = ds.id
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM agent_sources"))
