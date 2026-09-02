"""backfill_axiom_agent_instances

Revision ID: d7c4e29a1f83
Revises: b3f8a1d92c56
Create Date: 2026-09-02 00:00:01.000000

Wunomo Projects Phase 0 -- data migration, not schema. AXIOM becomes a
real agent_instances row, one per tenant, instead of a hardcoded
singleton; existing tasks/chat_messages/llm_usage_events/audit_logs
backfill their new agent_id to it.

Set-based throughout, not a per-tenant Python loop: this dev DB alone has
16,000+ tenant rows, and a per-row round trip at that scale is a real
operational concern, not a style preference. gen_random_uuid() (native in
Postgres since v13, confirmed live against this project's postgres:16-alpine
image) is used here instead of this codebase's usual Python-side
uuid.uuid4() deliberately, only for this one bulk INSERT -- a Python loop
issuing one round trip per tenant is the wrong shape for this many rows.

model seeds from the tenant's current ai_model_override (a JSON key on
tenants.settings) when it's set and still a supported value
(SUPPORTED_MODEL_OVERRIDES in services/llm_service.py: gemini-3.5-flash,
llama-3.3-70b-versatile -- hardcoded as literals below, not imported, since
a migration must not depend on application code whose allowlist can change
independently of this migration's own frozen intent), falling back to
gemini-3.5-flash otherwise. This matches the confirmed decision that a
tenant's model override becomes a newly-created agent's *starting* value,
not a live reference that keeps tracking the tenant setting afterward.

personality/operation_mode seed to ENGINEER/ASSISTED -- the same defaults
chat already falls back to when a request omits them (api/v1/chat.py's
ChatRequest), since there is no existing per-tenant setting to migrate
from: User.personality_mode/operation_mode exist as columns but were never
actually read by the chat path (confirmed by tracing the real call site,
not assumed) -- request-body values only, now legacy per the same decision.

The UPDATE ... WHERE agent_id IS NULL guard makes this idempotent in the
sense that matters (a second real run can't clobber anything), though the
(tenant_id, name) unique constraint on agent_instances means Alembic's own
apply-once bookkeeping is really what prevents a genuine double-run of the
INSERT half.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd7c4e29a1f83'
down_revision: Union[str, None] = 'b3f8a1d92c56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("""
        INSERT INTO agent_instances
            (id, tenant_id, name, employee_type, personality, operation_mode, model, status, created_at, updated_at)
        SELECT
            gen_random_uuid()::text,
            t.id,
            'AXIOM',
            'DATAOPS',
            'ENGINEER',
            'ASSISTED',
            CASE
                WHEN t.settings->>'ai_model_override' IN ('gemini-3.5-flash', 'llama-3.3-70b-versatile')
                    THEN t.settings->>'ai_model_override'
                ELSE 'gemini-3.5-flash'
            END,
            'ACTIVE',
            now(),
            now()
        FROM tenants t
    """))

    for table in ('tasks', 'chat_messages', 'llm_usage_events', 'audit_logs'):
        conn.execute(sa.text(f"""
            UPDATE {table} AS target
            SET agent_id = a.id
            FROM agent_instances a
            WHERE a.tenant_id = target.tenant_id AND a.name = 'AXIOM' AND target.agent_id IS NULL
        """))


def downgrade() -> None:
    conn = op.get_bind()
    for table in ('tasks', 'chat_messages', 'llm_usage_events', 'audit_logs'):
        conn.execute(sa.text(f"""
            UPDATE {table} AS target
            SET agent_id = NULL
            FROM agent_instances a
            WHERE a.id = target.agent_id AND a.name = 'AXIOM'
        """))
    conn.execute(sa.text("DELETE FROM agent_instances WHERE name = 'AXIOM'"))
