import json
import hmac
import hashlib
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Any


from database import get_db
from api.v1.auth import get_current_user
from models.cicd import PipelineCommit, PipelineDeployment, CICDStatus, GateDecision, DeploymentStatus
from schemas.cicd import WebhookResponse, PipelineCommitResponse, PipelineDeploymentResponse
from config import settings
from models.cicd import PipelineCommit, PipelineDeployment, CICDStatus, GateDecision, DeploymentStatus, CICDIncident

log = structlog.get_logger()
router = APIRouter()


PIPELINE_FILE_PATTERNS = [
    "pipelines/", ".pipeline.yaml", ".pipeline.yml", "pipeline_config", "dataops/"
]


# ─── Swagger Schema for Webhook ───────────────────────────────────────────────

class GitCommitAuthor(BaseModel):
    name: str = Field(..., example="dakshgupta")
    email: str = Field(..., example="dakshgupta.ajm@gmail.com")

class GitCommit(BaseModel):
    id: str = Field(..., example="112233445566778899aa")
    message: str = Field(..., example="feat: add risk scoring to pipeline")
    added: list[str] = Field(default=[], example=["pipelines/new_pipeline.yaml"])
    modified: list[str] = Field(default=[], example=["pipelines/etl_pipeline.yaml"])
    removed: list[str] = Field(default=[])

class GitRepository(BaseModel):
    clone_url: str = Field(..., example="https://github.com/org/repo.git")

class GitPusher(BaseModel):
    name: str = Field(..., example="dakshgupta")

class GitHubPushPayload(BaseModel):
    ref: str = Field(..., example="refs/heads/main")
    after: str = Field(..., example="112233445566778899aabbccddeeff1122334455")
    commits: list[GitCommit] = Field(default=[])
    repository: GitRepository = Field(...)
    pusher: GitPusher = Field(...)

    class Config:
        json_schema_extra = {
            "example": {
                "ref": "refs/heads/main",
                "after": "112233445566778899aabbccddeeff1122334455",
                "commits": [{
                    "id": "112233445566778899aa",
                    "message": "feat: add DROP TABLE check",
                    "added": [],
                    "modified": ["pipelines/etl_pipeline.yaml"],
                    "removed": []
                }],
                "repository": {"clone_url": "https://github.com/org/repo.git"},
                "pusher": {"name": "dakshgupta"}
            }
        }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def is_pipeline_file(filename: str) -> bool:
    lower = filename.lower()
    return any(pattern in lower for pattern in PIPELINE_FILE_PATTERNS)


def get_changed_files(payload: dict) -> list:
    files = []
    for c in payload.get("commits", []):
        files.extend(c.get("added", []))
        files.extend(c.get("modified", []))
        files.extend(c.get("removed", []))
    return list(set(files))


# ─── Webhook ─────────────────────────────────────────────────────────────────

@router.post("/webhook", response_model=WebhookResponse)
async def github_webhook(
    request: Request,
    payload: GitHubPushPayload,                               # ✅ Swagger fix — typed body
    db: AsyncSession = Depends(get_db),
    x_github_event: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),       # ✅ HMAC security
):
    payload_bytes = await request.body()

    # ── HMAC signature verification ──────────────────────────────
    if getattr(settings, "GITHUB_WEBHOOK_SECRET", None):
        expected = "sha256=" + hmac.new(
            settings.GITHUB_WEBHOOK_SECRET.encode(),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256 or ""):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if x_github_event and x_github_event != "push":
        return WebhookResponse(
            message=f"Ignored event type: {x_github_event}",
            ci_task_queued=False
        )

    raw = payload.model_dump()                                # ✅ use validated Pydantic data

    changed = get_changed_files(raw)
    pipeline_files_changed = [f for f in changed if is_pipeline_file(f)]

    if changed and not pipeline_files_changed:
        return WebhookResponse(
            message="No pipeline definition files changed — CI skipped",
            ci_task_queued=False,
        )

    tenant_id_str = request.headers.get("X-Tenant-ID") or request.query_params.get("tenant_id")
    if not tenant_id_str:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID header or tenant_id query param")

    branch         = raw.get("ref", "").replace("refs/heads/", "")
    commit_sha     = raw.get("after", "")
    author         = (raw.get("pusher") or {}).get("name", "unknown")
    repo_url       = (raw.get("repository") or {}).get("clone_url", "")
    commit_message = raw.get("commits", [{}])[-1].get("message", "") if raw.get("commits") else ""

    # ── Resolve which Pipeline this push belongs to ──────────────────────
    # Pipelines opt in by setting {"repo_url": "..."} in their pipeline_config.
    matched_pipeline_id = None
    if repo_url:
        from models.all_models import Pipeline
        result = await db.execute(
            select(Pipeline).where(Pipeline.tenant_id == tenant_id_str)
        )
        for p in result.scalars().all():
            if (p.pipeline_config or {}).get("repo_url") == repo_url:
                matched_pipeline_id = p.id
                break
        if not matched_pipeline_id:
            log.warning("cicd.webhook_no_pipeline_match", repo_url=repo_url, tenant_id=tenant_id_str)

    import uuid
    commit = PipelineCommit(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id_str,
        pipeline_id=matched_pipeline_id,
        commit_sha=commit_sha,
        branch=branch,
        author=author,
        repo_url=repo_url,
        changed_files=changed,
        commit_message=commit_message,
        ci_status=CICDStatus.pending,
        check_results={},
        risk_score=0.0,
    )
    db.add(commit)
    await db.commit()
    await db.refresh(commit)

    log.info("cicd.webhook_received", commit_id=commit.id, sha=commit_sha[:8])

    task_queued = False
    try:
        from services.cicd_tasks import run_ci_pipeline
        run_ci_pipeline.delay(commit.id, tenant_id_str)      # ✅ no redundant str() cast
        task_queued = True
    except Exception as e:
        log.warning("cicd.task_queue_failed", error=str(e))

    return WebhookResponse(
        message="Webhook received — CI pipeline queued",
        commit_id=commit.id,
        ci_task_queued=task_queued,
    )


# ─── Commits ─────────────────────────────────────────────────────────────────

@router.get("/commits", response_model=list[PipelineCommitResponse])
async def list_commits(
    pipeline_id: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = select(PipelineCommit).where(PipelineCommit.tenant_id == current_user["tenant_id"])
    if pipeline_id:
        query = query.where(PipelineCommit.pipeline_id == pipeline_id)
    query = query.order_by(PipelineCommit.trigger_time.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/commits/{commit_id}", response_model=PipelineCommitResponse)
async def get_commit(
    commit_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(PipelineCommit).where(
            PipelineCommit.id == commit_id,
            PipelineCommit.tenant_id == current_user["tenant_id"],
        )
    )
    commit = result.scalar_one_or_none()
    if not commit:
        raise HTTPException(status_code=404, detail="Commit not found")
    return commit


# ─── Approval Gate ───────────────────────────────────────────────────────────

@router.post("/commits/{commit_id}/approve")
async def approve_deployment(
    commit_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Manually approve a high-risk pipeline deployment."""
    result = await db.execute(
        select(PipelineCommit).where(
            PipelineCommit.id == commit_id,
            PipelineCommit.tenant_id == current_user["tenant_id"],
        )
    )
    commit = result.scalar_one_or_none()
    if not commit:
        raise HTTPException(status_code=404, detail="Commit not found")
    if commit.gate_decision != "pending_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Commit is not pending approval (current: {commit.gate_decision})"
        )

    commit.gate_decision = "approved"
    await db.commit()

    try:
        from services.cicd_deployment import deploy_pipeline
        deploy_pipeline.delay(commit.id, str(current_user["tenant_id"]), current_user["email"])  # ✅ no redundant str()
        log.info("cicd.manual_deploy_queued", commit_id=commit_id, approved_by=current_user["email"])
    except ImportError:
        log.warning("cicd.deploy_skipped", reason="cicd_deployment not available", commit_id=commit_id)
    except Exception as e:
        log.error("cicd.deploy_queue_failed", error=str(e), commit_id=commit_id)
        raise HTTPException(status_code=500, detail=f"Approval saved but deploy queue failed: {e}")

    return {"message": "Deployment approved and queued", "commit_id": commit_id}


@router.post("/commits/{commit_id}/reject")
async def reject_deployment(
    commit_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Reject a pending deployment."""
    result = await db.execute(
        select(PipelineCommit).where(
            PipelineCommit.id == commit_id,
            PipelineCommit.tenant_id == current_user["tenant_id"],
        )
    )
    commit = result.scalar_one_or_none()
    if not commit:
        raise HTTPException(status_code=404, detail="Commit not found")
    if commit.gate_decision not in ("pending_approval", "approved"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject commit with gate decision: {commit.gate_decision}"
        )

    commit.gate_decision = "rejected"
    await db.commit()
    log.info("cicd.deployment_rejected", commit_id=commit_id, rejected_by=current_user["email"])

    return {"message": "Deployment rejected", "commit_id": commit_id}


# ─── Deployments ─────────────────────────────────────────────────────────────

@router.get("/deployments", response_model=list[PipelineDeploymentResponse])
async def list_deployments(
    pipeline_id: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = select(PipelineDeployment).where(
        PipelineDeployment.tenant_id == current_user["tenant_id"]
    )
    if pipeline_id:
        query = query.where(PipelineDeployment.pipeline_id == pipeline_id)
    query = query.order_by(PipelineDeployment.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/deployments/{deployment_id}", response_model=PipelineDeploymentResponse)
async def get_deployment(
    deployment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get a single deployment's full details including monitoring status."""
    result = await db.execute(
        select(PipelineDeployment).where(
            PipelineDeployment.id == deployment_id,
            PipelineDeployment.tenant_id == current_user["tenant_id"],
        )
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment

# ─── Post-Deploy Run Recording ───────────────────────────────────────────────

class RunResultPayload(BaseModel):
    status: str = Field(..., example="failed", description="'passed' or 'failed' or 'error'")
    run_id: Optional[str] = Field(None, example="abc-123")
    error_message: Optional[str] = Field(None, example="NullPointerException in step 2")


@router.post("/deployments/{deployment_id}/record-run")
async def record_post_deploy_run(
    deployment_id: str,
    body: RunResultPayload,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Called by the pipeline executor after each run post-deployment.
    Increments run/failure counters. Monitor task uses these to decide rollback.
    """
    result = await db.execute(
        select(PipelineDeployment).where(
            PipelineDeployment.id == deployment_id,
            PipelineDeployment.tenant_id == current_user["tenant_id"],
        )
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if not deployment.monitoring_active:
        return {"message": "Monitoring already closed for this deployment", "skipped": True}

    deployment.post_deploy_run_count += 1
    if body.status in ("failed", "error"):
        deployment.post_deploy_failure_count += 1

    await db.commit()

    log.info(
        "cicd.run_recorded",
        deployment_id=deployment_id,
        status=body.status,
        runs=deployment.post_deploy_run_count,
        failures=deployment.post_deploy_failure_count,
    )

    return {
        "message": "Run recorded",
        "post_deploy_run_count": deployment.post_deploy_run_count,
        "post_deploy_failure_count": deployment.post_deploy_failure_count,
        "monitoring_active": deployment.monitoring_active,
    }


# ─── Deployment Health ────────────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/health")
async def get_deployment_health(
    deployment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Returns live monitoring status for a deployment.
    Shows run counts, failure counts, and any linked incidents.
    """
    result = await db.execute(
        select(PipelineDeployment).where(
            PipelineDeployment.id == deployment_id,
            PipelineDeployment.tenant_id == current_user["tenant_id"],
        )
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Fetch any incidents linked to this deployment
    incidents_result = await db.execute(
        select(CICDIncident).where(
            CICDIncident.deployment_id == deployment_id
        )
    )
    incidents = incidents_result.scalars().all()

    return {
        "deployment_id": deployment_id,
        "status": deployment.status,
        "monitoring_active": deployment.monitoring_active,
        "post_deploy_run_count": deployment.post_deploy_run_count,
        "post_deploy_failure_count": deployment.post_deploy_failure_count,
        "deployed_at": deployment.deployed_at,
        "rolled_back_at": deployment.rolled_back_at,
        "health": (
            "rolled_back" if deployment.status == DeploymentStatus.rolled_back
            else "monitoring" if deployment.monitoring_active
            else "healthy"
        ),
        "incidents": [
            {
                "id": str(inc.id),
                "severity": str(inc.severity),
                "status": str(inc.status),
                "title": inc.title,
                "created_at": inc.created_at,
            }
            for inc in incidents
        ],
    }


# ─── Incidents ────────────────────────────────────────────────────────────────

@router.get("/incidents")
async def list_incidents(
    status: Optional[str] = Query(None, description="Filter by status: open, investigating, resolved"),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all CICD incidents for this tenant."""
    query = select(CICDIncident).where(
        CICDIncident.tenant_id == current_user["tenant_id"]
    )
    if status:
        query = query.where(CICDIncident.status == status)
    query = query.order_by(CICDIncident.created_at.desc()).limit(limit)
    result = await db.execute(query)
    incidents = result.scalars().all()
    return [
        {
            "id": inc.id,
            "pipeline_id": inc.pipeline_id,
            "deployment_id": inc.deployment_id,
            "severity": inc.severity,
            "status": inc.status,
            "title": inc.title,
            "description": inc.description,
            "root_cause": inc.root_cause,
            "created_at": inc.created_at,
            "resolved_at": inc.resolved_at,
        }
        for inc in incidents
    ]


@router.patch("/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Mark a CICD incident as resolved."""
    result = await db.execute(
        select(CICDIncident).where(
            CICDIncident.id == incident_id,
            CICDIncident.tenant_id == current_user["tenant_id"],
        )
    )
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.status == "RESOLVED":
        raise HTTPException(status_code=400, detail="Incident already resolved")

    incident.status = "RESOLVED"
    incident.resolved_at = datetime.now(timezone.utc)
    incident.resolved_by = current_user["email"]
    await db.commit()

    log.info("cicd.incident_resolved", incident_id=incident_id, resolved_by=current_user["email"])
    return {"message": "Incident resolved", "incident_id": incident_id}

# ─── Status Summary ──────────────────────────────────────────────────────────

@router.get("/status/summary")
async def cicd_status_summary(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from services.cicd_service import get_status_summary
    return await get_status_summary(db, current_user["tenant_id"])