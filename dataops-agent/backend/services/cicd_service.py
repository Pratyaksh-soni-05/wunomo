import hmac
import hashlib
import structlog
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.cicd import PipelineCommit, CICDStatus
from models.pipeline import Pipeline  # adjust import path to match yours
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


async def verify_github_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """Verify GitHub HMAC SHA-256 webhook signature."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


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
    """Try to find a pipeline linked to this repository URL."""
    # Assumes Pipeline model has a source_config JSON column with repo_url key
    # Adjust the query if your pipeline model stores it differently
    result = await db.execute(
        select(Pipeline).where(
            Pipeline.tenant_id == tenant_id,
            Pipeline.is_active == True,
        )
    )
    pipelines = result.scalars().all()
    for p in pipelines:
        cfg = p.source_config or {}
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