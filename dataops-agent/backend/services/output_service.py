"""Blueprint §11 (Outputs) -- backend only this pass (see all_models.py's
Output docstring for the full unblocking rationale: §11 itself,
LiveWorkPanel's Files tab, §7.3.D's trust-score card, and "How this was
made" provenance all share this one gap).

STORAGE, investigated before writing this, not assumed: this codebase has
exactly one real place uploaded bytes live -- UPLOAD_DIR
(modules/ingestion/connector_manager.py, "~/dataops_uploads"), written by
api/v1/uploads.py's upload_file()/upload_and_register() and
api/v1/channels.py's upload_to_channel() (which itself calls the same
underlying register_uploaded_file() path). Every one of those stores the
full path string on the owning row (DataSource.connection_config
["file_path"]) -- Output.storage_ref follows the identical convention: a
full path string under UPLOAD_DIR, not a second storage mechanism
invented for this table. No S3/blob/CDN path exists anywhere in this
codebase to reuse instead.

TRUST SCORE, the engine vs. the scoring: QualityRuleEngine.run_checks()
(modules/quality/rule_engine.py) already computes a real 0-100 score and
a per-rule {rule_id, rule_name, rule_type, passed, message} result list
-- but only live, per PIPELINE, never persisted and never NULL (it
returns score=100.0, results=[] when a pipeline has zero active rules,
a sensible default for ITS OWN job -- a non-blocking pass/fail gate --
but the wrong one for an Output's trust display, which must show
nothing rather than imply a clean bill of health with nothing actually
checked). compute_trust_score() below is the real NULL correction this
module exists to add: snapshot run_checks()'s own result at the moment
an Output is created, substitute NULL for both trust_score and
trust_checks when total_rules == 0, never inherit the engine's own
100.0 default.

PROVENANCE: all four source tables already exist (Task, Handoff,
ApprovalRequest, AuditLog) -- get_provenance() is a join across them,
not new tracking. Checked directly, not assumed: the task-linked
resume/reject-step path (api/v1/tasks.py, the common case for a
structured-plan task) never calls AuditTrail.log_action at all -- only
the generic /approvals/{id}/approve|reject endpoints do (resource_type=
"approval"). So an output produced via the task-linked path will show a
real approval entry (from ApprovalRequest's own resolved_by/resolved_at/
resolution_note, which exist regardless of audit coverage) but may show
no matching audit_logs entry -- an honest gap in audit coverage, not a
bug in this join. The story includes whichever of the four sources
actually has a row; it does not require all four.
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from database import AsyncSessionLocal
from models.all_models import (
    AgentInstance, ApprovalRequest, AuditLog, Handoff, Output, Task, TaskStep,
)
from modules.quality.rule_engine import QualityRuleEngine
from services.tenant_context import tenant_scoped

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def compute_trust_score(tenant_id: str, pipeline_id: str | None) -> tuple[float | None, list[dict] | None]:
    """0-100 plus one human-readable line per check, aggregated from the
    EXISTING quality-rule engine -- never computed a second way. Returns
    (None, None) whenever there is nothing real to aggregate: no
    pipeline_id supplied (the caller doesn't know which pipeline's data
    this output came from), or the pipeline has zero active quality
    rules. Never substitutes 100 or 0 for that case -- see this module's
    own docstring for why run_checks()'s own 100.0/[] default is wrong
    to inherit here."""
    if pipeline_id is None:
        return None, None

    result = await QualityRuleEngine(tenant_id).run_checks(pipeline_id)
    if "error" in result or not result.get("results"):
        return None, None

    checks = [
        {"check": r["rule_name"], "passed": r["passed"], "message": r["message"]}
        for r in result["results"]
    ]
    return result["score"], checks


@tenant_scoped
class OutputService:
    """All methods tenant-isolated via @tenant_scoped, same convention
    PolicyEngine/QualityRuleEngine already use."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create_output(
        self,
        task_id: str,
        agent_instance_id: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        storage_ref: str,
        project_id: str | None = None,
        pipeline_id: str | None = None,
        supersedes_output_id: str | None = None,
    ) -> dict:
        """The real write side a future file-producing tool calls. No
        live caller exists yet (see all_models.py's Output docstring) --
        this function is still fully real and tested, not a stub.

        Version chain: the caller supplies supersedes_output_id directly
        when this output replaces a specific prior one it already knows
        about (version = that row's version + 1); omitted means this is
        a fresh v1 chain. Deliberately not auto-detected by matching
        filename/project -- no real producing tool exists yet to
        establish what "the same output" should mean in practice, and
        guessing a wrong heuristic now would be harder to unwind later
        than requiring the caller to be explicit."""
        try:
            async with AsyncSessionLocal() as db:
                version = 1
                if supersedes_output_id is not None:
                    r = await db.execute(select(Output).where(
                        Output.id == supersedes_output_id, Output.tenant_id == self.tenant_id,
                    ))
                    prior = r.scalar_one_or_none()
                    if prior is None:
                        return {"error": f"supersedes_output_id {supersedes_output_id} not found"}
                    version = prior.version + 1

                trust_score, trust_checks = await compute_trust_score(self.tenant_id, pipeline_id)

                output = Output(
                    id=str(uuid.uuid4()), tenant_id=self.tenant_id, project_id=project_id,
                    task_id=task_id, agent_instance_id=agent_instance_id,
                    filename=filename, content_type=content_type, size_bytes=size_bytes,
                    storage_ref=storage_ref, version=version,
                    supersedes_output_id=supersedes_output_id,
                    trust_score=trust_score, trust_checks=trust_checks,
                    created_at=utcnow(),
                )
                db.add(output)
                await db.commit()
                await db.refresh(output)
                log.info("output.created", output_id=output.id, task_id=task_id, version=version)
                return await self._serialize(output)
        except Exception as exc:
            log.error("output.create.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_outputs(self, project_id: str | None = None) -> list[dict]:
        async with AsyncSessionLocal() as db:
            q = select(Output).where(Output.tenant_id == self.tenant_id)
            if project_id:
                q = q.where(Output.project_id == project_id)
            q = q.order_by(Output.created_at.desc())
            rows = (await db.execute(q)).scalars().all()
            return [await self._serialize(o) for o in rows]

    async def get_output(self, output_id: str) -> dict | None:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Output).where(
                Output.id == output_id, Output.tenant_id == self.tenant_id,
            ))
            output = r.scalar_one_or_none()
            if output is None:
                return None
            return await self._serialize(output)

    async def get_output_row(self, output_id: str) -> Output | None:
        """Internal: the real ORM row, for the download endpoint (needs
        storage_ref/filename/content_type, not the serialized dict)."""
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Output).where(
                Output.id == output_id, Output.tenant_id == self.tenant_id,
            ))
            return r.scalar_one_or_none()

    async def get_provenance(self, output_id: str) -> dict | None:
        """One ordered story, joining the four real sources -- see this
        module's own docstring for the honest coverage gap on the
        audit_logs side. Each entry: {at, type, description}, sorted by
        `at` ascending (oldest first, the order the real events actually
        happened in)."""
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Output).where(
                Output.id == output_id, Output.tenant_id == self.tenant_id,
            ))
            output = r.scalar_one_or_none()
            if output is None:
                return None

            story = []

            task = (await db.execute(select(Task).where(Task.id == output.task_id))).scalar_one_or_none()
            if task is not None:
                story.append({
                    "at": task.created_at, "type": "task_created",
                    "description": f'Task "{task.goal}" started.',
                })
                if task.completed_at is not None:
                    story.append({
                        "at": task.completed_at, "type": "task_completed",
                        "description": f'Task reached {task.status.value}.',
                    })

            handoffs = (await db.execute(
                select(Handoff).where(Handoff.to_task_id == output.task_id)
            )).scalars().all()
            for h in handoffs:
                from_agent = await db.get(AgentInstance, h.from_agent_id)
                story.append({
                    "at": h.created_at, "type": "handoff_received",
                    "description": (
                        f'Received handoff from {from_agent.name if from_agent else "another agent"}: '
                        f'{h.payload_summary}'
                    ),
                })

            steps = (await db.execute(
                select(TaskStep).where(TaskStep.task_id == output.task_id)
            )).scalars().all()
            approval_ids = [s.approval_request_id for s in steps if s.approval_request_id is not None]
            approvals = []
            if approval_ids:
                approvals = (await db.execute(
                    select(ApprovalRequest).where(ApprovalRequest.id.in_(approval_ids))
                )).scalars().all()
            for a in approvals:
                if a.resolved_at is None:
                    continue
                verb = a.status.value.capitalize()  # "approved"/"rejected"/"executed"/"failed" -> title case
                story.append({
                    "at": a.resolved_at, "type": "approval",
                    "description": (
                        f'{verb} by {a.resolved_by or "unknown"} for "{a.action_name}"'
                        + (f' -- {a.resolution_note}' if a.resolution_note else "")
                    ),
                })

                audit_rows = (await db.execute(
                    select(AuditLog).where(
                        AuditLog.tenant_id == self.tenant_id,
                        AuditLog.resource_type == "approval",
                        AuditLog.resource_id == a.id,
                    )
                )).scalars().all()
                for log_row in audit_rows:
                    story.append({
                        "at": log_row.created_at, "type": "audit_event",
                        "description": f'{log_row.action} by {log_row.actor or "unknown"}',
                    })

            story.append({
                "at": output.created_at, "type": "output_created",
                "description": f'File "{output.filename}" produced (v{output.version}).',
            })

            story.sort(key=lambda e: e["at"] or datetime.min)
            for e in story:
                e["at"] = e["at"].isoformat() if e["at"] else None

            return {"output_id": output_id, "story": story}

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    async def _serialize(self, output: Output) -> dict:
        return {
            "id": output.id,
            "tenant_id": output.tenant_id,
            "project_id": output.project_id,
            "task_id": output.task_id,
            "agent_instance_id": output.agent_instance_id,
            "filename": output.filename,
            "content_type": output.content_type,
            "size_bytes": output.size_bytes,
            "storage_ref": output.storage_ref,
            "version": output.version,
            "supersedes_output_id": output.supersedes_output_id,
            "trust_score": output.trust_score,
            "trust_checks": output.trust_checks,
            "created_at": output.created_at.isoformat() if output.created_at else None,
        }
