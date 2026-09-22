import structlog
from datetime import datetime, timezone
from sqlalchemy import select, desc
from database import AsyncSessionLocal
from models.all_models import ApprovalRequest, ApprovalStatus
from services.tenant_context import tenant_scoped

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Maps risk level to a human-readable description
RISK_DESCRIPTIONS = {
    "low": "Low-risk read or report operation",
    "medium": "Medium-risk mutation (rerun, backfill, contract update)",
    "high": "High-risk destructive or schema-altering operation",
}

# Approved actions are dispatched through agent/approval_executor.py, which
# resolves the action_name against agent.tools.ALL_TOOLS -- the same registry
# the chat graph and the Tasks executor already use. There used to be a
# second, hand-maintained map here (TOOL_REGISTRY: action_name -> module /
# class / method / constructor_args). Retired 2026-09-17: measured against
# RISK_ACTIONS it covered 6 of the 20 tools that actually require approval,
# and 4 of its 10 entries were not tool names at all, so approving any of
# the other 14 -- detect_schema_drift, run_python_transform, create_pipeline,
# ... -- ended in "not registered in TOOL_REGISTRY". Two lists that describe
# the same thing drift; there is now one. See GOTCHAS, 2026-09-17.


@tenant_scoped
class PolicyEngine:
    """
    Manages approval requests for AXIOM's assisted and autonomous operation modes.

    Flow:
    1. Agent calls create_request() before executing a medium/high-risk tool
    2. User sees pending approval in UI or chat
    3. User calls approve() or reject()
    4. approve() persists approval, then calls execute_approved_action()
    5. Execution result stored on the ApprovalRequest row

    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # 1. Create approval request
    # ------------------------------------------------------------------

    async def create_request(
        self,
        user_id: str,
        session_id: str,
        action_name: str,
        action_args: dict,
        risk_level: str,
        reason: str,
    ) -> dict:
        """
        Creates an ApprovalRequest for a pending agent action.

        Args:
            user_id: UUID of requesting user
            session_id: chat session UUID
            action_name: a tool name from agent.tools.ALL_TOOLS (e.g. "run_pipeline")
            action_args: kwargs to pass to the tool on execution
            risk_level: "low" | "medium" | "high"
            reason: agent's explanation of why this action is needed

        Returns: { approval_id, action_name, risk_level, status: "pending" }
        """
        log.info(
            "policy.create_request",
            tenant_id=self.tenant_id,
            action_name=action_name,
            risk_level=risk_level,
        )
        try:
            async with AsyncSessionLocal() as db:
                req = ApprovalRequest(
                    tenant_id=self.tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                    action_name=action_name,
                    action_args=action_args,
                    risk_level=risk_level,
                    reason=reason,
                    status=ApprovalStatus.PENDING,
                    created_at=utcnow(),
                )
                db.add(req)
                await db.commit()
                await db.refresh(req)

                log.info("policy.create_request.done", approval_id=str(req.id))
                return {
                    "approval_id": str(req.id),
                    "action_name": action_name,
                    "action_args": action_args,
                    "risk_level": risk_level,
                    "risk_description": RISK_DESCRIPTIONS.get(risk_level, ""),
                    "reason": reason,
                    "status": "pending",
                    "created_at": req.created_at.isoformat(),
                }
        except Exception as exc:
            log.error("policy.create_request.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 2. List pending approvals
    # ------------------------------------------------------------------

    async def list_pending(self) -> list[dict]:
        """
        Returns all pending ApprovalRequests for this tenant, newest first.
        """
        log.info("policy.list_pending", tenant_id=self.tenant_id)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ApprovalRequest)
                    .where(
                        ApprovalRequest.tenant_id == self.tenant_id,
                        ApprovalRequest.status == ApprovalStatus.PENDING,
                    )
                    .order_by(desc(ApprovalRequest.created_at))
                )
                requests = result.scalars().all()

                output = [await self._serialize(r) for r in requests]
                log.info("policy.list_pending.done", count=len(output))
                return output

        except Exception as exc:
            log.error("policy.list_pending.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 3. Get one approval request
    # ------------------------------------------------------------------

    async def get_request(self, approval_id: str) -> dict:
        """Returns a single ApprovalRequest by ID."""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ApprovalRequest).where(
                        ApprovalRequest.id == approval_id,
                        ApprovalRequest.tenant_id == self.tenant_id,
                    )
                )
                req = result.scalar_one_or_none()
                if req is None:
                    return {"error": f"Approval {approval_id} not found"}
                return await self._serialize(req)
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 4. Approve → execute
    # ------------------------------------------------------------------

    async def approve(
        self,
        approval_id: str,
        reviewer: str,
        notes: str = "",
    ) -> dict:
        """
        Approves the request, executes the action, and stores the result.
        Returns: { approval_id, status, execution_result }
        """
        log.info(
            "policy.approve",
            tenant_id=self.tenant_id,
            approval_id=approval_id,
            reviewer=reviewer,
        )
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ApprovalRequest).where(
                        ApprovalRequest.id == approval_id,
                        ApprovalRequest.tenant_id == self.tenant_id,
                    )
                )
                req = result.scalar_one_or_none()

                if req is None:
                    return {"error": f"Approval {approval_id} not found"}
                if req.status != ApprovalStatus.PENDING:
                    return {
                        "error": f"Approval is already {req.status.value}, cannot approve",
                        "current_status": req.status.value,
                    }

                now = utcnow()
                req.status = ApprovalStatus.APPROVED
                req.resolved_by = reviewer
                req.resolution_note = notes
                req.resolved_at = now
                db.add(req)
                await db.commit()
                await db.refresh(req)

            # Execute the approved action
            execution_result = await self.execute_approved_action(req)

            # Persist execution result
            final_status = (
                ApprovalStatus.EXECUTED
                if "error" not in execution_result
                else ApprovalStatus.FAILED
            )
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ApprovalRequest).where(
                        ApprovalRequest.id == approval_id,
                        ApprovalRequest.tenant_id == self.tenant_id,
                    )
                )
                req = result.scalar_one_or_none()
                req.status = final_status
                req.execution_result = execution_result
                db.add(req)
                await db.commit()

            # If this approval was blocking a supervisor-dispatched task
            # (never a plain chat-originated one -- see
            # find_supervisor_task_for_approval's own SUPERVISOR_INTENT
            # filter), the task itself never learns the action ran unless
            # something tells it: this is that link. Lazy import to avoid
            # a module-load cycle (supervisor.py doesn't import this
            # module, but several modules it touches transitively do).
            # PolicyEngine stays domain-agnostic either way -- it only
            # ever checks "is there a task_id", never what a Task is.
            from modules.orchestration.supervisor import (
                find_supervisor_task_for_approval, resolve_task_approval,
            )
            task_id = await find_supervisor_task_for_approval(approval_id)
            if task_id is not None:
                await resolve_task_approval(task_id, approval_id, approved=True)

            log.info(
                "policy.approve.done",
                approval_id=approval_id,
                final_status=final_status.value,
            )
            return {
                "approval_id": approval_id,
                "status": final_status.value,
                "reviewer": reviewer,
                "execution_result": execution_result,
                "resolved_at": now.isoformat(),
            }

        except Exception as exc:
            log.error("policy.approve.error", approval_id=approval_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 5. Reject
    # ------------------------------------------------------------------

    async def reject(
        self,
        approval_id: str,
        reviewer: str,
        notes: str = "",
    ) -> dict:
        """
        Rejects the approval request. Action is NOT executed.
        Returns: { approval_id, status: "rejected", reviewer, resolved_at }
        """
        log.info("policy.reject", tenant_id=self.tenant_id, approval_id=approval_id)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(ApprovalRequest).where(
                        ApprovalRequest.id == approval_id,
                        ApprovalRequest.tenant_id == self.tenant_id,
                    )
                )
                req = result.scalar_one_or_none()

                if req is None:
                    return {"error": f"Approval {approval_id} not found"}
                if req.status != ApprovalStatus.PENDING:
                    return {
                        "error": f"Approval is already {req.status.value}",
                        "current_status": req.status.value,
                    }

                now = utcnow()
                req.status = ApprovalStatus.REJECTED
                req.resolved_by = reviewer
                req.resolution_note = notes
                req.resolved_at = now
                db.add(req)
                await db.commit()

            # Same task-aware link approve() uses above -- a rejection is
            # a decision, not a pause, so a supervisor task's dependents
            # must move to BLOCKED_ON_DEPENDENCY rather than keep sitting
            # queued with nothing ever telling them the wait is over.
            from modules.orchestration.supervisor import (
                find_supervisor_task_for_approval, resolve_task_approval,
            )
            task_id = await find_supervisor_task_for_approval(approval_id)
            if task_id is not None:
                await resolve_task_approval(task_id, approval_id, approved=False)

            log.info("policy.reject.done", approval_id=approval_id)
            return {
                "approval_id": approval_id,
                "status": "rejected",
                "reviewer": reviewer,
                "notes": notes,
                "resolved_at": now.isoformat(),
            }

        except Exception as exc:
            log.error("policy.reject.error", approval_id=approval_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 6. Execute approved action (dynamic dispatch)
    # ------------------------------------------------------------------

    async def execute_approved_action(self, approval: ApprovalRequest) -> dict:
        """Run the real @tool for an approved action. Never raises -- always
        returns a dict; "error" in it marks the approval FAILED.

        Identity arguments are FORCED from the approval row, never trusted
        from the stored action_args -- the same rule agent_node applies to
        every live tool call. The stored args were written by the model (via
        the chat gate) or the task planner; the row's tenant_id/user_id/
        session_id are what the server recorded when the request was made.
        """
        from agent.approval_executor import TOOL_MAP

        action_name = approval.action_name
        action_args = dict(approval.action_args or {})
        log.info("policy.execute_approved_action",
                 action_name=action_name, approval_id=str(approval.id))

        tool = TOOL_MAP.get(action_name)
        if tool is None:
            return {"error": f"Action '{action_name}' is not a registered tool",
                    "available_actions": sorted(TOOL_MAP)}

        declared = set(getattr(tool, "args", {}) or {})
        identity = {"tenant_id": self.tenant_id,
                    "user_id": approval.user_id, "session_id": approval.session_id}
        for key, value in identity.items():
            if key in declared:
                action_args[key] = value
        unknown = sorted(k for k in action_args if k not in declared)
        for k in unknown:
            action_args.pop(k)   # a stale or planner-invented argument must not 500 the call

        try:
            result = await tool.ainvoke(action_args)
        except Exception as exc:
            log.error("policy.execute_approved_action.error",
                      action_name=action_name, error=str(exc))
            return {"error": f"Execution failed: {exc}"}
        if not isinstance(result, dict):
            result = {"result": result}
        log.info("policy.execute_approved_action.done",
                 action_name=action_name, success="error" not in result)
        return result

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    async def _serialize(self, req: ApprovalRequest) -> dict:
        # §7.3.E: "Where a dependent task is held behind this one, the
        # card must say so." Only ever non-None for a PENDING approval
        # blocking a supervisor task with a real SUPERVISOR_QUEUED
        # dependent -- find_supervisor_task_for_approval's own
        # SUPERVISOR_INTENT filter means a plain chat-originated or
        # structured-task approval always gets None here, unchanged from
        # before this field existed.
        unblocks = None
        if req.status == ApprovalStatus.PENDING:
            from modules.orchestration.supervisor import (
                describe_unblocked_dependents, find_supervisor_task_for_approval,
            )
            task_id = await find_supervisor_task_for_approval(str(req.id))
            if task_id is not None:
                unblocks = await describe_unblocked_dependents(task_id)

        return {
            "approval_id": str(req.id),
            "user_id": str(req.user_id) if req.user_id else None,
            "session_id": str(req.session_id) if req.session_id else None,
            "action_name": req.action_name,
            "action_args": req.action_args or {},
            "risk_level": req.risk_level,
            "risk_description": RISK_DESCRIPTIONS.get(req.risk_level or "", ""),
            "reason": req.reason,
            "unblocks": unblocks,
            "status": req.status.value if hasattr(req.status, "value") else str(req.status),
            "resolution_note": req.resolution_note,
            "resolved_by": req.resolved_by,
            "execution_result": req.execution_result,
            "created_at": req.created_at.isoformat() if req.created_at else None,
            "resolved_at": req.resolved_at.isoformat() if req.resolved_at else None,
        }

