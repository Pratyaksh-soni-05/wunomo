import json
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Any


from database import get_db, AsyncSessionLocal
from api.v1.auth import get_current_user, require_permission
from models.cicd import PipelineCommit, PipelineDeployment, CICDStatus, GateDecision, DeploymentStatus
from schemas.cicd import WebhookResponse, PipelineCommitResponse, PipelineDeploymentResponse
from config import settings
from models.cicd import PipelineCommit, PipelineDeployment, CICDStatus, GateDecision, DeploymentStatus, CICDIncident
from services.cicd_service import resolve_pipeline_for_webhook
from services.tenant_context import async_tenant_context
from services.webhook_security import (
    enforce_cheap_rejections, verify_signature, check_replay, release_replay,
    WebhookRejected, ReplayCheckUnavailable,
)

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
#
# Security Master Ranking Item #16 (full history: docs/context/GOTCHAS.md).
#
# Per-pipeline secret, never a single global one: if every tenant who
# connects a repo needed the SAME secret to paste into their own GitHub
# webhook settings, every tenant would hold a value capable of forging
# another tenant's deployment events. The URL names which pipeline a
# delivery claims to be for; the signature is what actually proves it.
# Tenant identity comes ONLY from the resolved pipeline row, never from a
# client-supplied header -- a signature proves the sender knows a secret,
# not which tenant's data the request should touch, so binding the two
# together is the fix itself, not an addition to it.
#
# Order is deliberate and load-bearing: raw bytes -> size cap -> resolve
# pipeline -> signature -> only THEN parse as JSON -> replay check ->
# tenant context -> everything else. The request body is never handed to
# Pydantic, tenant context is never established, and the replay cache is
# never consulted until the signature has already been verified.


def _webhook_rejected() -> HTTPException:
    """One identical 401 for every rejection reason -- bad/missing
    signature, unknown pipeline, no secret configured, oversized body, or
    replay -- so nothing about the response lets a caller learn which of
    those actually happened."""
    return HTTPException(status_code=401, detail="Invalid webhook request.")


@router.post("/webhook")
async def github_webhook_retired():
    """Retired in favour of POST /webhook/{pipeline_id} -- a global,
    unauthenticated webhook with no working signature check (see GOTCHAS).
    Returns 410, not a bare 404, so an existing GitHub webhook still
    pointed at this URL gets an explicit, actionable reason rather than
    looking like the whole API moved."""
    return JSONResponse(
        status_code=410,
        content={
            "detail": "This endpoint has been retired. Point your GitHub "
                      "webhook at /api/v1/cicd/webhook/{pipeline_id} instead "
                      "-- see POST /api/v1/pipelines/{pipeline_id}/webhook-secret "
                      "to generate that pipeline's secret.",
        },
    )


@router.post("/webhook/{pipeline_id}", response_model=WebhookResponse)
async def github_webhook(pipeline_id: str, request: Request,
    db: AsyncSession = Depends(get_db),
    x_github_event: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_delivery: Optional[str] = Header(None),
):
    raw_body = await request.body()
    delivery_id = x_github_delivery or "missing"

    try:
        # Cheap, database-free rejections first: malformed/missing
        # signature header shape, oversized body, missing delivery id.
        # None of these need to know whether the pipeline even exists.
        enforce_cheap_rejections(raw_body, x_hub_signature_256, x_github_delivery)

        # The one cross-tenant read on this path -- through the normal
        # pooled async session, as the normal dataops_app role, via a
        # SECURITY DEFINER function scoped to exactly two columns for
        # exactly one row (see cicd_service.resolve_pipeline_for_webhook's
        # own docstring). No ADMIN_DATABASE_URL, no BYPASSRLS connection,
        # anywhere on this request path.
        resolved = await resolve_pipeline_for_webhook(db, pipeline_id)
        if resolved is None or not resolved.get("secret"):
            # Same rejection, same log reason-string shape, whether the
            # pipeline doesn't exist or just has no secret generated yet --
            # neither fact is safe to let an outside caller distinguish.
            raise WebhookRejected("unknown_pipeline_or_no_secret")

        verify_signature(raw_body, x_hub_signature_256, resolved["secret"])
        await check_replay(x_github_delivery)
    except WebhookRejected as exc:
        log.warning("cicd.webhook_rejected", delivery_id=delivery_id, reason=exc.reason, pipeline_id=pipeline_id)
        raise _webhook_rejected()
    except ReplayCheckUnavailable as exc:
        # Fails CLOSED, deliberately -- see ReplayCheckUnavailable's own
        # docstring. 503, not 401: a different kind of fact (our
        # infrastructure, not the caller's request), and GitHub redelivers
        # on its own once this clears, so nothing is lost.
        log.warning("cicd.webhook_replay_check_unavailable", delivery_id=delivery_id, pipeline_id=pipeline_id, error=str(exc))
        raise HTTPException(status_code=503, detail="Service temporarily unavailable. Please retry.")

    tenant_id = resolved["tenant_id"]

    # Ping (sent once, when the webhook is first created in GitHub's UI)
    # and any event other than push: acknowledged, never processed.
    # Checked BEFORE parsing as a push payload -- GitHubPushPayload's
    # required fields (ref/after/repository.clone_url) don't exist on a
    # ping body at all, which would otherwise surface as an unhandled 500
    # instead of a clean 200.
    if x_github_event and x_github_event != "push":
        return WebhookResponse(message=f"Ignored event type: {x_github_event}", ci_task_queued=False)

    try:
        # Everything below runs under this pipeline's own, now-verified
        # tenant -- never under anything a header or query param claimed.
        # Wrapped so ANY failure from here on (a malformed-but-signed
        # payload, a DB error, anything) releases the replay key
        # check_replay already set -- otherwise a GitHub redelivery of
        # this exact push (same X-GitHub-Delivery) would be rejected as a
        # replay for the rest of REPLAY_TTL_SECONDS even though nothing
        # was ever actually persisted for it.
        async with async_tenant_context(tenant_id):
            payload = GitHubPushPayload.model_validate_json(raw_body)

            raw = payload.model_dump()
            changed = get_changed_files(raw)
            pipeline_files_changed = [f for f in changed if is_pipeline_file(f)]
            if changed and not pipeline_files_changed:
                return WebhookResponse(
                    message="No pipeline definition files changed — CI skipped",
                    ci_task_queued=False,
                )

            branch         = raw.get("ref", "").replace("refs/heads/", "")
            commit_sha     = raw.get("after", "")
            author         = (raw.get("pusher") or {}).get("name", "unknown")
            repo_url       = (raw.get("repository") or {}).get("clone_url", "")
            commit_message = raw.get("commits", [{}])[-1].get("message", "") if raw.get("commits") else ""

            import uuid
            async with AsyncSessionLocal() as inner_db:
                commit = PipelineCommit(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    pipeline_id=pipeline_id,
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
                inner_db.add(commit)
                await inner_db.commit()
                await inner_db.refresh(commit)

            log.info("cicd.webhook_received", commit_id=commit.id, sha=commit_sha[:8], pipeline_id=pipeline_id, delivery_id=delivery_id)

            task_queued = False
            try:
                from services.cicd_tasks import run_ci_pipeline
                run_ci_pipeline.delay(commit.id, tenant_id)
                task_queued = True
            except Exception as e:
                log.warning("cicd.task_queue_failed", error=str(e))

            return WebhookResponse(
                message="Webhook received — CI pipeline queued",
                commit_id=commit.id,
                ci_task_queued=task_queued,
            )
    except Exception:
        # The PipelineCommit insert above either never ran or never
        # committed -- release the replay key so a GitHub redelivery of
        # this exact push is accepted rather than rejected as a replay
        # for something that was never actually recorded.
        await release_replay(x_github_delivery)
        raise


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
    current_user=Depends(require_permission("cicd.approve")),
):
    """Manually approve a high-risk pipeline deployment. Only owners/admins may approve."""
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
    current_user=Depends(require_permission("cicd.approve")),
):
    """Reject a pending deployment. Only owners/admins may reject."""
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
    current_user=Depends(require_permission("cicd.incidents.resolve")),
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