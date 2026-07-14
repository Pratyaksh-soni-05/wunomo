from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, ENUM
import uuid
import enum
from datetime import timezone, datetime
from .all_models import Base



class CICDStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    passed = "passed"
    failed = "failed"
    skipped = "skipped"



class GateDecision(str, enum.Enum):
    auto_approved = "auto_approved"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"



class DeploymentStatus(str, enum.Enum):
    queued = "queued"
    deploying = "deploying"
    active = "active"
    rolled_back = "rolled_back"
    failed = "failed"



class IncidentSeverity(str, enum.Enum):
    low      = "LOW"
    medium   = "MEDIUM"
    high     = "HIGH"
    critical = "CRITICAL"



class IncidentStatus(str, enum.Enum):
    open          = "OPEN"
    investigating = "INVESTIGATING"
    resolved      = "RESOLVED"
    suppressed    = "SUPPRESSED"



cicdstatus_pg = ENUM(
    "pending", "running", "passed", "failed", "skipped",
    name="cicdstatus", create_type=False
)
gatedecision_pg = ENUM(
    "auto_approved", "pending_approval", "approved", "rejected",
    name="gatedecision", create_type=False
)
deploymentstatus_pg = ENUM(
    "queued", "deploying", "active", "rolled_back", "failed",
    name="deploymentstatus", create_type=False
)
incidentseverity_pg = ENUM(
    "LOW", "MEDIUM", "HIGH", "CRITICAL",
    name="incidentseverity", create_type=False        # ✅ already exists in DB
)
incidentstatus_pg = ENUM(
    "OPEN", "INVESTIGATING", "RESOLVED", "SUPPRESSED",  # ✅ uppercase, all 4 values
    name="incidentstatus", create_type=False            # ✅ already exists in DB
)



class PipelineCommit(Base):
    __tablename__ = "pipeline_commits"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    pipeline_id = Column(String, ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=True)

    commit_sha = Column(String(64), nullable=False)
    branch = Column(String(255), nullable=False, default="main")
    author = Column(String(255), nullable=True)
    repo_url = Column(String(500), nullable=True)
    changed_files = Column(JSON, default=list)
    commit_message = Column(Text, nullable=True)

    trigger_time = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ci_status = Column(cicdstatus_pg, default="pending")
    gate_decision = Column(gatedecision_pg, nullable=True)

    check_results = Column(JSON, default=dict)
    risk_score = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    deployments = relationship("PipelineDeployment", back_populates="commit", cascade="all, delete-orphan")



class PipelineDeployment(Base):
    __tablename__ = "pipeline_deployments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    pipeline_id = Column(String, ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    commit_id = Column(String, ForeignKey("pipeline_commits.id", ondelete="CASCADE"), nullable=False)

    commit_sha = Column(String(64), nullable=False)
    deployed_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(String(255), nullable=True)
    approval_type = Column(String(20), default="manual")
    risk_score = Column(Float, default=0.0)

    rollback_commit_sha = Column(String(64), nullable=True)
    status = Column(deploymentstatus_pg, default="queued")

    monitoring_active = Column(Boolean, default=True)
    post_deploy_run_count = Column(Integer, default=0)
    post_deploy_failure_count = Column(Integer, default=0)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    commit = relationship("PipelineCommit", back_populates="deployments")
    incidents = relationship("CICDIncident", back_populates="deployment", cascade="all, delete-orphan")



class CICDIncident(Base):
    __tablename__ = "cicd_incidents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    pipeline_id = Column(String, ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    deployment_id = Column(String, ForeignKey("pipeline_deployments.id", ondelete="CASCADE"), nullable=False)

    severity = Column(incidentseverity_pg, default="HIGH")   # ✅ uppercase default
    status = Column(incidentstatus_pg, default="OPEN")       # ✅ uppercase default
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    root_cause = Column(Text, nullable=True)

    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    deployment = relationship("PipelineDeployment", back_populates="incidents")