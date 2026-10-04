import secrets as _secrets
import structlog
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from models.cicd import PipelineCommit, PipelineDeployment, CICDStatus
from models.all_models import Pipeline, PipelineStatus
from schemas.cicd import GitHubWebhookPayload

log = structlog.get_logger()

# Pipeline definition file patterns — only trigger CI if these change
PIPELINE_FILE_PATTERNS = [
    "pipelines/",
    ".pipeline.yaml",
    ".pipeline.yml",
    "pipeline_config",
    "dataops/",
]


def is_pipeline_file(filename: str) -> bool:
    """Return True if this file path looks like a pipeline definition."""
    lower = filename.lower()
    return any(pattern in lower for pattern in PIPELINE_FILE_PATTERNS)


async def resolve_pipeline_for_webhook(db: AsyncSession, pipeline_id: str) -> Optional[dict]:
    """The one legitimate cross-tenant read on this request path, since
    the whole point is finding out which tenant a pipeline belongs to
    before any tenant context exists to scope a normal query with.

    Runs through the NORMAL pooled async session, as the normal
    unprivileged dataops_app role -- not ADMIN_DATABASE_URL, not a
    BYPASSRLS connection. The cross-tenant visibility is confined entirely
    to resolve_webhook_pipeline(), a SECURITY DEFINER SQL function
    (migration f2a6f3d01f22) that selects exactly tenant_id/webhook_secret
    for exactly one row by primary key -- the same mechanism migration
    b7d419e3f2a8's tenant_registry view already uses for the cross-tenant
    Celery sweepers (a view/function with no security_invoker runs with
    its owner's privileges, so dataops_app, granted only EXECUTE on this
    one function, reads past the pipelines RLS policy without ever
    holding BYPASSRLS itself). Every other query this route runs,
    afterward, goes through the ordinary dataops_app role with RLS fully
    in force, scoped by async_tenant_context(tenant_id) once this
    function's result establishes which tenant that is.

    Returns {"tenant_id": str, "secret": str | None} or None if no
    pipeline with this id exists at all. The secret is already decrypted
    -- this is the one place outside the ORM allowed to touch that
    column's ciphertext, and the plaintext is never logged or included in
    any exception message raised here.
    """
    result = await db.execute(
        text("SELECT tenant_id, webhook_secret FROM resolve_webhook_pipeline(:pid)"),
        {"pid": pipeline_id},
    )
    row = result.first()
    if row is None:
        return None
    secret = None
    if row.webhook_secret:
        from services.encryption_service import decrypt_config, is_encrypted
        if is_encrypted(row.webhook_secret):
            secret = decrypt_config(row.webhook_secret).get("secret")
    return {"tenant_id": row.tenant_id, "secret": secret}


async def generate_or_rotate_webhook_secret(
    db: AsyncSession, tenant_id: str, pipeline_id: str,
) -> Optional[str]:
    """Generates a new random secret for this pipeline's webhook, replacing
    any existing one outright -- rotation invalidates the old value
    immediately, there is no dual-secret grace window. Returns the new
    PLAINTEXT secret, the only time it is ever available in plaintext
    again (the caller must return it to the user once and never log or
    store it elsewhere). Returns None if no pipeline with this id exists
    for this tenant -- the caller's own tenant-scoped session already
    enforces that via RLS; this function trusts the session it is given.
    """
    result = await db.execute(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.tenant_id == tenant_id)
    )
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        return None
    new_secret = _secrets.token_urlsafe(32)
    pipeline.webhook_secret = {"secret": new_secret}
    await db.commit()
    return new_secret


async def create_pipeline_commit(
    db: AsyncSession,
    tenant_id: UUID,
    pipeline_id: Optional[UUID],
    payload: GitHubWebhookPayload,
) -> PipelineCommit:
    """Persist the incoming webhook event as a PipelineCommit record."""
    commit = PipelineCommit(
        tenant_id=tenant_id,
        pipeline_id=pipeline_id,
        commit_sha=payload.after,
        branch=payload.get_branch(),
        author=payload.get_author(),
        repo_url=payload.repository.get("clone_url") or payload.repository.get("html_url"),
        changed_files=payload.get_changed_files(),
        commit_message=payload.get_commit_message(),
        ci_status=CICDStatus.pending,
    )
    db.add(commit)
    await db.commit()
    await db.refresh(commit)
    log.info("cicd.commit_recorded", commit_id=str(commit.id), sha=commit.commit_sha[:8])
    return commit


async def get_pipeline_for_repo(
    db: AsyncSession,
    tenant_id: UUID,
    repo_url: str,
) -> Optional[Pipeline]:
    """Try to find a pipeline linked to this repository URL via its
    pipeline_config.repo_url — mirrors the matching logic already used
    inline by the webhook handler in api/v1/cicd.py."""
    result = await db.execute(
        select(Pipeline).where(
            Pipeline.tenant_id == tenant_id,
            Pipeline.status == PipelineStatus.ACTIVE,
        )
    )
    pipelines = result.scalars().all()
    for p in pipelines:
        cfg = p.pipeline_config or {}
        if repo_url and repo_url in str(cfg):
            return p
    return None


async def list_commits(
    db: AsyncSession,
    tenant_id: UUID,
    pipeline_id: Optional[UUID] = None,
    limit: int = 20,
) -> list:
    query = select(PipelineCommit).where(PipelineCommit.tenant_id == tenant_id)
    if pipeline_id:
        query = query.where(PipelineCommit.pipeline_id == pipeline_id)
    query = query.order_by(PipelineCommit.trigger_time.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_commit(db: AsyncSession, tenant_id: UUID, commit_id: UUID) -> Optional[PipelineCommit]:
    result = await db.execute(
        select(PipelineCommit).where(
            PipelineCommit.id == commit_id,
            PipelineCommit.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_status_summary(db: AsyncSession, tenant_id: UUID) -> dict:
    """CI/CD status summary for a tenant — shared by the REST endpoint
    (api/v1/cicd.py) and the agent's get_cicd_status tool, so both read the
    same tenant-scoped queries instead of the tool making an unauthenticated
    HTTP call back into the REST endpoint."""
    commit_result = await db.execute(
        select(PipelineCommit.ci_status, func.count(PipelineCommit.id).label("count"))
        .where(PipelineCommit.tenant_id == tenant_id)
        .group_by(PipelineCommit.ci_status)
    )
    commit_stats = {row.ci_status: row.count for row in commit_result}

    active = await db.execute(
        select(func.count(PipelineDeployment.id)).where(
            PipelineDeployment.tenant_id == tenant_id,
            PipelineDeployment.status == "active",
        )
    )
    rollbacks = await db.execute(
        select(func.count(PipelineDeployment.id)).where(
            PipelineDeployment.tenant_id == tenant_id,
            PipelineDeployment.status == "rolled_back",
        )
    )
    pending = await db.execute(
        select(func.count(PipelineCommit.id)).where(
            PipelineCommit.tenant_id == tenant_id,
            PipelineCommit.gate_decision == "pending_approval",
        )
    )
    active_deployments = active.scalar() or 0
    total_rollbacks    = rollbacks.scalar() or 0
    pending_approvals  = pending.scalar() or 0
    return {
        "commit_stats": commit_stats,
        "active_deployments": active_deployments,
        "total_rollbacks":   total_rollbacks,
        "pending_approvals": pending_approvals,
        "health": "degraded" if (total_rollbacks > 0 or pending_approvals > 0) else "healthy",
    }