import uuid, enum
from datetime import datetime
from sqlalchemy import (Column, String, Text, Boolean, Integer, Float,
    DateTime, ForeignKey, JSON, Enum as SAEnum, UniqueConstraint)
from sqlalchemy.orm import relationship
from database import Base


def gen_uuid(): return str(uuid.uuid4())


class SourceType(str, enum.Enum):
    POSTGRES="postgres"; MYSQL="mysql"; SQLITE="sqlite"; BIGQUERY="bigquery"
    SNOWFLAKE="snowflake"; CSV="csv"; EXCEL="excel"; JSON="json"
    API_REST="api_rest"; GOOGLE_SHEETS="google_sheets"; S3="s3"; PDF="pdf"; DOCX="docx"


class PipelineStatus(str, enum.Enum):
    DRAFT="draft"; ACTIVE="active"; PAUSED="paused"; ARCHIVED="archived"


class RunStatus(str, enum.Enum):
    PENDING="pending"; RUNNING="running"; SUCCESS="success"
    FAILED="failed"; RETRYING="retrying"; CANCELLED="cancelled"


class IncidentSeverity(str, enum.Enum):
    LOW="low"; MEDIUM="medium"; HIGH="high"; CRITICAL="critical"


class IncidentStatus(str, enum.Enum):
    OPEN="open"; INVESTIGATING="investigating"; RESOLVED="resolved"; SUPPRESSED="suppressed"


class PersonalityMode(str, enum.Enum):
    ENGINEER="engineer"; FOUNDER="founder"; ANALYST="analyst"; AUDITOR="auditor"


class OperationMode(str, enum.Enum):
    ADVISORY="advisory"; ASSISTED="assisted"; AUTONOMOUS="autonomous"; AUDIT="audit"


class ApprovalStatus(str, enum.Enum):
    PENDING="pending"; APPROVED="approved"; REJECTED="rejected"
    EXECUTED="executed"; FAILED="failed"


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    plan = Column(String(50), default="starter")
    is_active = Column(Boolean, default=True)
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    users = relationship("User", back_populates="tenant")
    sources = relationship("DataSource", back_populates="tenant")
    pipelines = relationship("Pipeline", back_populates="tenant")


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    email = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=True)
    google_id = Column(String(255), nullable=True, index=True)
    email_verified = Column(Boolean, default=False)
    full_name = Column(String(255))
    role = Column(String(50), default="member")
    is_active = Column(Boolean, default=True)
    personality_mode = Column(SAEnum(PersonalityMode), default=PersonalityMode.ENGINEER)
    operation_mode = Column(SAEnum(OperationMode), default=OperationMode.ASSISTED)
    # Personal UI preference, not tenant-wide (each user picks their own) -
    # deliberately not a JWT claim, same staleness reasoning already
    # applied to personality_mode/operation_mode (Phase 3 decisions):
    # read fresh from the DB per-request via GET /auth/me instead.
    theme = Column(String(20), nullable=True)  # "light" | "dark" | "system" | None (unset)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)
    tenant = relationship("Tenant", back_populates="users")


class DataSource(Base):
    __tablename__ = "data_sources"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(255), nullable=False)
    source_type = Column(SAEnum(SourceType), nullable=False)
    connection_config = Column(JSON, nullable=False)
    schema_snapshot = Column(JSON, default=dict)
    last_profiled_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    tags = Column(JSON, default=list)
    owner = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tenant = relationship("Tenant", back_populates="sources")
    pipelines = relationship("Pipeline", back_populates="source")


class Pipeline(Base):
    __tablename__ = "pipelines"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    source_id = Column(String, ForeignKey("data_sources.id"))
    name = Column(String(255), nullable=False)
    description = Column(Text)
    status = Column(SAEnum(PipelineStatus), default=PipelineStatus.DRAFT)
    schedule_cron = Column(String(100))
    pipeline_config = Column(JSON, default=dict)
    sla_minutes = Column(Integer)
    retry_policy = Column(JSON, default=dict)
    tags = Column(JSON, default=list)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tenant = relationship("Tenant", back_populates="pipelines")
    source = relationship("DataSource", back_populates="pipelines")
    runs = relationship("PipelineRun", back_populates="pipeline")
    quality_rules = relationship("QualityRule", back_populates="pipeline")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id = Column(String, primary_key=True, default=gen_uuid)
    pipeline_id = Column(String, ForeignKey("pipelines.id"), nullable=False)
    tenant_id = Column(String, nullable=False)
    status = Column(SAEnum(RunStatus), default=RunStatus.PENDING)
    triggered_by = Column(String(100), default="schedule")
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_seconds = Column(Float)
    rows_processed = Column(Integer, default=0)
    rows_failed = Column(Integer, default=0)
    quality_score = Column(Float)
    run_logs = Column(JSON, default=list)
    output_summary = Column(JSON, default=dict)
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    pipeline = relationship("Pipeline", back_populates="runs")


class QualityRule(Base):
    __tablename__ = "quality_rules"
    id = Column(String, primary_key=True, default=gen_uuid)
    pipeline_id = Column(String, ForeignKey("pipelines.id"))
    tenant_id = Column(String, nullable=False)
    name = Column(String(255), nullable=False)
    rule_type = Column(String(100), nullable=False)
    column_name = Column(String(255))
    rule_config = Column(JSON, default=dict)
    severity = Column(String(50), default="high")
    is_blocking = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    pass_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    pipeline = relationship("Pipeline", back_populates="quality_rules")


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False)
    pipeline_id = Column(String, ForeignKey("pipelines.id"))
    run_id = Column(String, ForeignKey("pipeline_runs.id"))
    title = Column(String(500), nullable=False)
    description = Column(Text)
    severity = Column(SAEnum(IncidentSeverity), default=IncidentSeverity.MEDIUM)
    status = Column(SAEnum(IncidentStatus), default=IncidentStatus.OPEN)
    root_cause = Column(Text)
    remediation_actions = Column(JSON, default=list)
    affected_assets = Column(JSON, default=list)
    detected_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)
    resolution_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class LineageNode(Base):
    __tablename__ = "lineage_nodes"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False)
    node_type = Column(String(100))
    name = Column(String(255), nullable=False)
    node_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class LineageEdge(Base):
    __tablename__ = "lineage_edges"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False)
    upstream_id = Column(String, ForeignKey("lineage_nodes.id"), nullable=False)
    downstream_id = Column(String, ForeignKey("lineage_nodes.id"), nullable=False)
    relationship_type = Column(String(100), default="transforms_to")
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False)
    # Nullable, no FK - matches this table's own tenant_id (also no FK):
    # an audit log must never fail to record an action over a referential-
    # integrity check. History predates agents-as-records, backfills to
    # AXIOM's row-one agent per tenant.
    agent_id = Column(String, nullable=True)
    actor = Column(String(255))
    action = Column(String(255), nullable=False)
    resource_type = Column(String(100))
    resource_id = Column(String(255))
    payload = Column(JSON, default=dict)
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    action_name = Column(String(255), nullable=False)
    action_args = Column(JSON, default=dict)
    risk_level = Column(String(50), default="high")
    reason = Column(Text, default="")
    status = Column(SAEnum(ApprovalStatus), default=ApprovalStatus.PENDING, index=True)
    resolution_note = Column(Text, default="")
    resolved_by = Column(String(255), nullable=True)
    execution_result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    # Nullable: history predates agents-as-records, backfills to AXIOM's
    # new row-one agent. No FK - matches this table's own existing
    # convention (tenant_id/user_id above are plain columns too, not FKs).
    agent_id = Column(String, nullable=True)
    # Wunomo Projects Phase 2: which agent this message @mentions, if
    # any - singular, matching "the tagged agent responds, nobody else"
    # (multi-mention would need a join table instead; not needed for v1).
    # Nullable and FK-less for the same reason agent_id above is: every
    # message before this column existed, and every private 1:1 message
    # after it, simply has none. @mention ROUTING resolves this against
    # real ChannelAgent membership (services/channels.py), never trusts
    # this column alone - an agent removed from a channel after being
    # mentioned in an old message must not retroactively become
    # reachable through it.
    mentioned_agent_id = Column(String, nullable=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    personality_mode = Column(String(50))
    operation_mode = Column(String(50))
    tool_calls = Column(JSON, default=list)
    msg_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class DataContract(Base):
    __tablename__ = "data_contracts"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False)
    name = Column(String(255), nullable=False)
    producer_source_id = Column(String, ForeignKey("data_sources.id"))
    consumer_description = Column(Text)
    schema_expectations = Column(JSON, default=dict)
    quality_conditions = Column(JSON, default=list)
    sla_hours = Column(Integer)
    is_active = Column(Boolean, default=True)
    last_validated_at = Column(DateTime)
    validation_status = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


class UsageMetric(Base):
    __tablename__ = "usage_metrics"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False)
    metric_type = Column(String(100), nullable=False)
    value = Column(Float, nullable=False)
    pipeline_id = Column(String)
    node_metadata = Column(JSON, default=dict)
    recorded_at = Column(DateTime, default=datetime.utcnow)


class KpiValue(Base):
    __tablename__ = "kpi_values"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False)
    kpi_name = Column(String(255), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(50))
    recorded_at = Column(DateTime, default=datetime.utcnow)


class LlmUsageEvent(Base):
    __tablename__ = "llm_usage_events"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=True)
    session_id = Column(String, nullable=True)
    # Nullable, no FK - a planning attempt can log a real row under a
    # task_id whose Task was never persisted (a failed/invalid plan means
    # nothing gets written to `tasks`, per api/v1/tasks.py's create_task()),
    # and an unattended/system-triggered call may legitimately have no task
    # at all. A hard FK here would either reject the first case's real
    # spend or force a two-phase write; a plain indexed column costs
    # nothing and lets a rollup query LEFT JOIN and treat "no matching Task
    # row" as its own honest bucket instead of failing the insert.
    task_id = Column(String, nullable=True, index=True)
    # Nullable, no FK - same reasoning as task_id above, and matches this
    # table's own tenant_id (also no FK): this table is a metering log
    # that must never fail an insert over a referential-integrity check.
    # History predates agents-as-records, backfills to AXIOM's row-one
    # agent per tenant.
    agent_id = Column(String, nullable=True, index=True)
    request_type = Column(String(50), nullable=False)
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    used_fallback = Column(Boolean, default=False)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    # Reasoning/"thinking" tokens (e.g. Gemini 3's thinking mode) are already
    # folded into total_tokens by the provider — this is a separate view onto
    # the same total, tracked distinctly since it'll matter for credit
    # pricing later (thinking tokens likely priced differently from plain
    # output tokens).
    reasoning_tokens = Column(Integer)
    total_tokens = Column(Integer)
    latency_ms = Column(Integer)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class OnboardingProfile(Base):
    __tablename__ = "onboarding_profiles"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, unique=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    role = Column(String(100))
    industry = Column(String(100), nullable=True)
    company_size = Column(String(50), nullable=True)
    use_cases = Column(JSON, default=list)
    data_stack = Column(JSON, default=list)
    completed_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserWorkspacePreference(Base):
    """Item 1 (2026-08 walkthrough): "log straight into the last workspace
    used" instead of always showing the choose-workspace picker. Keyed by
    email, not user_id -- the same email can have a separate User row per
    tenant (see User.__table_args__'s (tenant_id, email) constraint), and
    "which workspace did this person use last" is a cross-tenant, per-
    person fact, not something any single tenant-scoped User row alone can
    hold. Server-side (not localStorage) so it follows the person across
    devices, per explicit decision. Written from exactly one place --
    issue_token_for_user() -- so every real login/switch path updates it
    without each call site needing its own write."""
    __tablename__ = "user_workspace_preferences"
    email = Column(String(255), primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailLoginCode(Base):
    __tablename__ = "email_login_codes"
    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String(255), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False)
    intended_tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    attempts_used = Column(Integer, default=0)
    consumed_at = Column(DateTime, nullable=True)
    request_ip = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TransformRun(Base):
    __tablename__ = "transform_runs"
    id = Column(String, primary_key=True, default=gen_uuid)
    # Bare String, not FK'd — matches the majority convention in this codebase
    # (only User/DataSource/Pipeline get a real tenant_id FK); accepted
    # consciously, not by default, since app-level tenant scoping is what's
    # actually load-bearing here (see CLAUDE.md).
    tenant_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=True)
    source_id = Column(String, nullable=True, index=True)
    transform_type = Column(String(20), nullable=False)  # "sql" | "pandas"
    origin = Column(String(20), nullable=False)  # "chat_agent" | "manual"
    code = Column(Text, nullable=False)
    status = Column(String(20), nullable=False)  # "success" | "error"
    row_count = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    result_preview = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class TeamInvite(Base):
    __tablename__ = "team_invites"
    id = Column(String, primary_key=True, default=gen_uuid)
    # Real FK, matching User's own pattern (invites are as tenant-owned as
    # users) rather than the majority bare-String convention elsewhere.
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    role = Column(String(50), nullable=False)  # locked at invite time, see services/rbac.py Role
    invited_by_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    # SHA-256, not bcrypt - same reasoning as EmailLoginCode.code_hash: TTL +
    # single-use is the real protection, not hash slowness.
    token_hash = Column(String(64), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="pending")  # pending|accepted|revoked|expired
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    # index=True: GET /team/invites orders by this column, and the real
    # deployed table has carried this index since Phase 15 anyway (a
    # stray duplicate line, invisible in a too-short Read near EOF, had
    # silently been declaring it this whole time - see CLAUDE.md Gotchas).
    # Declaring it explicitly now instead of dropping it: the index is a
    # real, sensible fit for the real query pattern.
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ApiKey(Base):
    """Platform API keys (Phase 16) - CRUD only this phase (generate/hash/
    store, list masked, revoke). Nothing in the API accepts one of these
    as a credential yet - that's a deliberately separate, larger feature
    (a new auth dependency, every endpoint's resolution path, key-scoped
    rate limits), tracked in CLAUDE.md's Not-yet-built. Don't let a
    Settings UI imply these can authenticate anything until that lands."""
    __tablename__ = "api_keys"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(255), nullable=False)
    # SHA-256, not bcrypt - the raw key itself is a high-entropy random
    # secret (unlike a user-chosen password), so hash-slowness protection
    # against brute force isn't the relevant threat model here; same
    # reasoning as TeamInvite.token_hash/EmailLoginCode.code_hash.
    key_hash = Column(String(64), nullable=False, unique=True)
    key_prefix = Column(String(20), nullable=False)  # e.g. "axm_live_a1b2c3d4" - safe to display, not the full secret
    created_by_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentEmployeeType(str, enum.Enum):
    """Which product line this agent instance is (Wunomo Projects Phase 0
    - see docs/context/WUNOMO_PROJECTS_PROPOSAL_v2.md). Deliberately only
    the one real, backed employee type for now - LEDGER/PULSE/etc. have no
    tools or modules built yet, and adding placeholder values here before
    they exist risks the same "never imply a locked employee is
    available" mistake the proposal explicitly holds the *frontend* hire
    screen to. Extend this the day a second employee type actually ships,
    not before - a new enum value is a trivial, non-breaking migration
    later."""
    DATAOPS = "dataops"


class AgentInstanceStatus(str, enum.Enum):
    ACTIVE = "active"
    OFFBOARDED = "offboarded"


class AgentInstance(Base):
    """A named, tenant-owned agent (Wunomo Projects Phase 0). AXIOM
    becomes row one per tenant, backfilled by the next migration - not a
    special case; every agent, including AXIOM, is a real row here from
    this point forward.

    model is authoritative per-agent, not a live reference to
    Tenant.settings.ai_model_override - the tenant override is only the
    seed value copied in when an agent is created (application-level, not
    a DB default), so editing the tenant setting later never silently
    moves an already-created agent's model out from under it.

    updated_at (not a separate version counter, and not a new pattern -
    DataSource already does exactly this) is what get_agent()'s cache key
    incorporates going forward: editing any field on this row bumps
    updated_at automatically (onupdate=datetime.utcnow), which changes
    the cache key, which means a stale cached agent object can never be
    served after an edit - invalidation by construction, not by a call
    site remembering to bust the cache."""
    __tablename__ = "agent_instances"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_agent_instances_tenant_name"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    employee_type = Column(SAEnum(AgentEmployeeType), nullable=False, default=AgentEmployeeType.DATAOPS)
    personality = Column(SAEnum(PersonalityMode), nullable=False, default=PersonalityMode.ENGINEER)
    operation_mode = Column(SAEnum(OperationMode), nullable=False, default=OperationMode.ASSISTED)
    model = Column(String, nullable=False)
    standing_instructions = Column(Text, nullable=True)
    # None = no agent-level ceiling, draw against the tenant's plan-level
    # AI-credit quota only. Schema only this pass (Wunomo Projects Phase
    # 0) - the two-gate enforcement code path (tenant plan limit AND
    # agent budget, both must pass) lands with Phase 1, not here.
    monthly_token_budget = Column(Integer, nullable=True)
    status = Column(SAEnum(AgentInstanceStatus), nullable=False, default=AgentInstanceStatus.ACTIVE)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AgentSource(Base):
    """Scope join table (Wunomo Projects Phase 0) - deliberately a real,
    queryable table, not a JSON column on AgentInstance, so "can this
    agent touch this source" is enforceable in SQL and joinable, not just
    checked in Python after the fact. Every permission system that began
    as JSON in a column in this codebase got rewritten; this one starts
    right. Intersection-permission enforcement itself (has_permission(...)
    AND source in agent_scope) is Phase 1, not Phase 0 - this table only
    exists so Phase 1 has something real to query."""
    __tablename__ = "agent_sources"
    __table_args__ = (UniqueConstraint("agent_id", "source_id", name="uq_agent_sources_agent_source"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    agent_id = Column(String, ForeignKey("agent_instances.id"), nullable=False, index=True)
    source_id = Column(String, ForeignKey("data_sources.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Project(Base):
    """Wunomo Projects Phase 1, part two. "A project is an object inside
    a tenant" (WUNOMO_PROJECTS_PROPOSAL_v2.md's own correction to itself)
    - explicitly NOT a workspace/tenant substitute: a project just groups
    agents (via ProjectAgent below) inside the tenant that already owns
    billing, team, and sources. An agent hired outside any project (every
    agent that exists as of this migration, including every tenant's
    AXIOM row) simply has no ProjectAgent row - membership is optional,
    not a required foreign key on AgentInstance itself, since retrofitting
    a NOT NULL project_id onto every pre-existing agent would be a much
    bigger migration for a distinction (grouped vs ungrouped) this schema
    doesn't need to force."""
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_projects_tenant_name"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ProjectAgent(Base):
    """Join table, not a project_id FK on AgentInstance - same reasoning
    AgentSource already established for agent/source scope: a real,
    queryable, joinable table rather than a column that would force
    every agent into exactly one project (or none) at the schema level
    when the actual v1 rule is simpler and looser - an agent may belong
    to zero or one project for now (hiring only ever links one), but
    nothing here mechanically prevents more later without a migration."""
    __tablename__ = "project_agents"
    __table_args__ = (UniqueConstraint("project_id", "agent_id", name="uq_project_agents_project_agent"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    agent_id = Column(String, ForeignKey("agent_instances.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Channel(Base):
    """Wunomo Projects Phase 2 -- the multi-participant conversation the
    proposal calls a "channel." ChatMessage.session_id (see that model's
    own column, unchanged) stays a bare, FK-less grouping string exactly
    as it's always been; for a real channel it's simply set to this
    row's own id at creation time, by convention, not by a declared
    foreign key -- correlation is by value, checked at read time
    (routing, context-filtering), the same way ChatMessage.agent_id's
    optionality already works on this same table. No backfill needed
    for today's private 1:1 chat: it keeps generating a bare session_id
    with no matching Channel row, forever, exactly as before this
    table existed.

    project_id is nullable, not required -- same reasoning ProjectAgent
    already established for agent-project membership: a channel MAY
    live inside a project, but forcing "create a project first" before
    anyone can ever open a channel isn't a v1 requirement this schema
    needs to enforce."""
    __tablename__ = "channels"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ChannelUser(Base):
    """Human membership -- a channel's real participant set, queried by
    the ownership/membership check the same way agent_sources/
    project_agents already are, not inferred from who happens to have
    posted a message."""
    __tablename__ = "channel_users"
    __table_args__ = (UniqueConstraint("channel_id", "user_id", name="uq_channel_users_channel_user"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    channel_id = Column(String, ForeignKey("channels.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ChannelAgent(Base):
    """Agent membership -- @mention routing resolves against this table,
    never a string match on an agent's name: an agent not in
    channel_agents for a given channel cannot be mentioned in it,
    regardless of what its name looks like in the message text."""
    __tablename__ = "channel_agents"
    __table_args__ = (UniqueConstraint("channel_id", "agent_id", name="uq_channel_agents_channel_agent"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    channel_id = Column(String, ForeignKey("channels.id"), nullable=False, index=True)
    agent_id = Column(String, ForeignKey("agent_instances.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TaskShape(str, enum.Enum):
    """Deliberately narrow for v1 (see CLAUDE.md's item-6 design decisions)
    - a fixed, pre-vetted set of goal->plan-shape pairings, not open-ended
    planning. Task.task_shape must be one of these; anything else is
    rejected at creation."""
    DIAGNOSE_PIPELINE_FAILURE = "diagnose_pipeline_failure"
    INVESTIGATE_INCIDENT = "investigate_incident"
    SYNC_PROFILE_QUALITY = "sync_profile_quality"


class TaskStatus(str, enum.Enum):
    DRAFT_PLAN = "draft_plan"  # plan generated, awaiting human approval/edit/reject - nothing has executed yet
    PLAN_REJECTED = "plan_rejected"
    QUEUED = "queued"  # plan approved, not yet picked up by the stage-3 executor - a distinct, permanent state (queue depth/worker restarts/credit checks), not just a stage-2-vs-3 build-window artifact
    RUNNING = "running"
    PAUSED_NEEDS_APPROVAL = "paused_needs_approval"  # a step hit a risk-gated tool call
    PAUSED_FAILED_STEP = "paused_failed_step"  # a step exhausted its attempt budget, or the initiating user was demoted/deactivated
    PAUSED_PLAN_INVALID = "paused_plan_invalid"  # a completed step's result shows the remaining plan won't reach the goal
    PAUSED_QUOTA_EXCEEDED = "paused_quota_exceeded"  # tenant AI-credit quota exhausted mid-run; resumable once quota resets
    COMPLETED = "completed"
    COMPLETED_WITH_UNCONFIRMED_STEPS = "completed_with_unconfirmed_steps"  # a dispatched step's verification never reached a terminal state within its window - honest, not clean, success (Q2)
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"  # sat paused past the pause-timeout with no resolution


class TaskStepStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    VERIFYING = "verifying"  # structural post-dispatch polling state (Q2) - distinct from RUNNING so the UI/logic can tell "dispatched" from "confirmed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED_APPROVAL = "blocked_approval"


class TaskStepSource(str, enum.Enum):
    """Provenance of a step, so the timeline never mistakes a
    system-appended verify step (Q2) for something AXIOM chose to do, and
    so a human-edited step is visibly distinct from the original plan."""
    LLM_PLANNED = "llm_planned"
    HUMAN_EDITED = "human_edited"
    SYSTEM_INSERTED = "system_inserted"


class Task(Base):
    """A long-running, multi-step AXIOM task (item 6 - see CLAUDE.md's
    design decisions section). Deliberately does NOT store the initiating
    user's role anywhere on this row: role/is_active are re-read fresh from
    the DB immediately before every step executes (same per-request re-read
    Phase 19 built for get_current_user()), never snapshotted here - a
    snapshotted role would be a privilege-escalation hole with a built-in
    time window for any task that outlives a demotion or deactivation."""
    __tablename__ = "tasks"
    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)  # initiator - see class docstring re: role
    # Nullable: history predates agents-as-records (Wunomo Projects Phase
    # 0) and backfills to AXIOM's new row-one agent in the next migration;
    # a real FK because Task already uses FKs on its other identity
    # columns above, matching this table's own established convention.
    agent_id = Column(String, ForeignKey("agent_instances.id"), nullable=True)
    originating_session_id = Column(String, nullable=True)  # the chat session this task was spawned from, if any
    goal = Column(Text, nullable=False)
    task_shape = Column(SAEnum(TaskShape), nullable=False)
    status = Column(SAEnum(TaskStatus), nullable=False, default=TaskStatus.DRAFT_PLAN)
    # Plan provenance - did this task run the plan AXIOM proposed, or one a
    # human edited? Cheap to capture now, impossible to reconstruct later.
    plan_approved_by = Column(String, ForeignKey("users.id"), nullable=True)
    plan_approved_at = Column(DateTime, nullable=True)
    plan_edited = Column(Boolean, default=False)
    step_budget_max = Column(Integer, nullable=False)
    step_budget_used = Column(Integer, default=0)
    # None = no separate task-level ceiling, draw against the tenant's
    # plan-level AI-credit quota only (quota_service.py's existing formula).
    credit_budget_max = Column(Integer, nullable=True)
    credit_budget_used = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)  # drives the pause-timeout expiry check
    completed_at = Column(DateTime, nullable=True)
    # Real, persisted reason for a non-clean stop (stage 6, Q4): which cap
    # fired (step/wall-clock/loop) for a FAILED task, or who cancelled and
    # whether an in-flight step may have completed after, for CANCELLED.
    # Unlike pause_reason/completion_note/expiry_reason (all computed at
    # read time from a related step's own data), there's no step to derive
    # this from -- a wall-clock or loop stop isn't any one step's fault.
    termination_reason = Column(Text, nullable=True)


class TaskStep(Base):
    __tablename__ = "task_steps"
    id = Column(String, primary_key=True, default=gen_uuid)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False, index=True)
    step_index = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)  # human-readable, shown in plan review + timeline UI
    source = Column(SAEnum(TaskStepSource), nullable=False)
    tool_name = Column(String(100), nullable=True)  # null for a verify-only step with no direct tool call
    tool_args = Column(JSON, nullable=True)
    depends_on_step_index = Column(Integer, nullable=True)  # feeds the failure/verification dependency logic (Q1/Q2)
    status = Column(SAEnum(TaskStepStatus), nullable=False, default=TaskStepStatus.PENDING)
    attempt_count = Column(Integer, default=0)  # the bounded retry/adapt budget from Q1
    # Capped summary of what happened - this, not raw_result, is what a
    # resumed step replays as context (see CLAUDE.md's resume-context
    # design: goal + step list + capped summaries, never the full raw
    # tool-result blob or intermediate reasoning chatter).
    outcome_summary = Column(Text, nullable=True)
    raw_result = Column(JSON, nullable=True)  # capped like cap_tool_result() elsewhere - UI detail view only
    error_message = Column(Text, nullable=True)
    approval_request_id = Column(String, ForeignKey("approval_requests.id"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)