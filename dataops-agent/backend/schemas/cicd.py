from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum


class CICDStatusEnum(str, Enum):
    pending = "pending"
    running = "running"
    passed = "passed"
    failed = "failed"
    skipped = "skipped"


class GateDecisionEnum(str, Enum):
    auto_approved = "auto_approved"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"


# --- Webhook Payload ---
class GitHubWebhookPayload(BaseModel):
    ref: str = Field(..., description="refs/heads/main")
    after: str = Field(..., description="commit SHA")
    before: Optional[str] = None
    repository: Dict[str, Any] = {}
    commits: List[Dict[str, Any]] = []
    pusher: Optional[Dict[str, Any]] = None

    def get_branch(self) -> str:
        return self.ref.replace("refs/heads/", "")

    def get_author(self) -> str:
        return (self.pusher or {}).get("name", "unknown")

    def get_changed_files(self) -> List[str]:
        files = []
        for c in self.commits:
            files.extend(c.get("added", []))
            files.extend(c.get("modified", []))
            files.extend(c.get("removed", []))
        return list(set(files))

    def get_commit_message(self) -> str:
        if self.commits:
            return self.commits[-1].get("message", "")
        return ""


# --- Response Schemas ---
class PipelineCommitResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    pipeline_id: Optional[UUID]
    commit_sha: str
    branch: str
    author: Optional[str]
    ci_status: CICDStatusEnum
    gate_decision: Optional[GateDecisionEnum]
    risk_score: float
    check_results: Dict[str, Any]
    trigger_time: datetime
    completed_at: Optional[datetime]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class PipelineDeploymentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    pipeline_id: UUID
    commit_sha: str
    deployed_at: Optional[datetime]
    approved_by: Optional[str]
    approval_type: str
    risk_score: float
    status: str
    monitoring_active: bool
    post_deploy_run_count: int
    post_deploy_failure_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class WebhookResponse(BaseModel):
    message: str
    commit_id: Optional[UUID] = None
    ci_task_queued: bool = False