import importlib
import structlog
from datetime import datetime, timezone
from sqlalchemy import select, desc
from database import AsyncSessionLocal
from models.all_models import ApprovalRequest, ApprovalStatus

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Maps risk level to a human-readable description
RISK_DESCRIPTIONS = {
    "low": "Low-risk read or report operation",
    "medium": "Medium-risk mutation (rerun, backfill, contract update)",
    "high": "High-risk destructive or schema-altering operation",
}

# Tool registry: maps action_name -> the real target to dispatch to.
#
# Every target below is an instance method (tenant_id always goes to the
# constructor, never the method call) except "update_contract", whose
# target (_noop) is a real module-level function ("class": None). Any
# name in "constructor_args" is pulled out of the approval's action_args
# and passed to the constructor instead of the method call — needed
# because SchemaProfiler.__init__ requires source_id up front, unlike
# every other target class here.
#
# This replaced a (module_path, function_name) shape that resolved via a
# bare module-level getattr() — which can never find an instance method,
# so every entry failed dispatch regardless of role/approval state. See
# CLAUDE.md's "PolicyEngine.execute_approved_action()" Known-broken row
# for the full history, including two entries that had a second,
# independent bug even after the module/instance issue: "pause_pipeline"
# named a method ("pause") that doesn't exist even as an instance method
# (the real one is pause_pipeline), and "modify_business_rule" targeted
# a method (BusinessRules.update_rule) that doesn't exist under any name
# — there is no real "modify a business rule" capability anywhere in
# this codebase, so that entry is removed rather than papered over; a
# request for it now correctly surfaces "not registered".
TOOL_REGISTRY: dict[str, dict] = {
    # Ingestion
    "profile_schema": {
        "module": "modules.ingestion.schema_profiler", "class": "SchemaProfiler",
        "method": "profile", "constructor_args": ["source_id"],
    },
    "sync_source": {
        "module": "modules.ingestion.connector_manager", "class": "ConnectorManager",
        "method": "sync", "constructor_args": [],
    },
    # Orchestration
    "rerun_pipeline": {
        "module": "modules.orchestration.dag_manager", "class": "DAGManager",
        "method": "trigger_run", "constructor_args": [],
    },
    "backfill_pipeline": {
        "module": "modules.orchestration.dag_manager", "class": "DAGManager",
        "method": "backfill", "constructor_args": [],
    },
    "pause_pipeline": {
        "module": "modules.orchestration.dag_manager", "class": "DAGManager",
        "method": "pause_pipeline", "constructor_args": [],
    },
    # Quality
    "run_quality_check": {
        "module": "modules.quality.rule_engine", "class": "QualityRuleEngine",
        "method": "run_checks", "constructor_args": [],
    },
    # Observability
    "resolve_incident": {
        "module": "modules.observability.incident_manager", "class": "IncidentManager",
        "method": "resolve_incident", "constructor_args": [],
    },
    "triage_incident": {
        "module": "modules.observability.incident_manager", "class": "IncidentManager",
        "method": "triage_incident", "constructor_args": [],
    },
    # Governance
    "update_contract": {
        "module": "modules.governance.policy_engine", "class": None,
        "method": "_noop", "constructor_args": [],
    },
    # Reporting
    "generate_report": {
        "module": "modules.reporting.report_generator", "class": "ReportGenerator",
        "method": "generate_status_report", "constructor_args": [],
    },
}


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
            action_name: tool name from TOOL_REGISTRY (e.g. "rerun_pipeline")
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

                output = [self._serialize(r) for r in requests]
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
                return self._serialize(req)
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
        """
        Resolves and calls the real target for an approved action — either
        an instance method (constructed with tenant_id, plus anything in
        "constructor_args" pulled out of action_args) or a plain module-level
        function ("class": None). Never raises — always returns a dict.
        """
        action_name = approval.action_name
        action_args = dict(approval.action_args or {})

        log.info(
            "policy.execute_approved_action",
            action_name=action_name,
            approval_id=str(approval.id),
        )

        if action_name not in TOOL_REGISTRY:
            return {
                "error": f"Action '{action_name}' is not registered in TOOL_REGISTRY",
                "available_actions": list(TOOL_REGISTRY.keys()),
            }

        spec = TOOL_REGISTRY[action_name]

        try:
            module = importlib.import_module(spec["module"])
        except ImportError as e:
            return {"error": f"Could not import module '{spec['module']}': {str(e)}"}

        class_name = spec.get("class")
        fn_name = spec["method"]

        try:
            if class_name is None:
                fn = getattr(module, fn_name, None)
                if fn is None:
                    return {"error": f"Function '{fn_name}' not found in module '{spec['module']}'"}
                result = await fn(**action_args)
            else:
                cls = getattr(module, class_name, None)
                if cls is None:
                    return {"error": f"Class '{class_name}' not found in module '{spec['module']}'"}

                constructor_kwargs = {"tenant_id": self.tenant_id}
                method_kwargs = dict(action_args)
                for arg_name in spec.get("constructor_args", []):
                    if arg_name in method_kwargs:
                        constructor_kwargs[arg_name] = method_kwargs.pop(arg_name)

                instance = cls(**constructor_kwargs)
                method = getattr(instance, fn_name, None)
                if method is None:
                    return {"error": f"Method '{fn_name}' not found on {class_name}"}
                result = await method(**method_kwargs)

            log.info(
                "policy.execute_approved_action.done",
                action_name=action_name,
                success="error" not in (result or {}),
            )
            return result if isinstance(result, dict) else {"result": result}

        except Exception as exc:
            log.error(
                "policy.execute_approved_action.error",
                action_name=action_name,
                error=str(exc),
            )
            return {"error": f"Execution failed: {str(exc)}"}

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _serialize(self, req: ApprovalRequest) -> dict:
        return {
            "approval_id": str(req.id),
            "user_id": str(req.user_id) if req.user_id else None,
            "session_id": str(req.session_id) if req.session_id else None,
            "action_name": req.action_name,
            "action_args": req.action_args or {},
            "risk_level": req.risk_level,
            "risk_description": RISK_DESCRIPTIONS.get(req.risk_level or "", ""),
            "reason": req.reason,
            "status": req.status.value if hasattr(req.status, "value") else str(req.status),
            "resolution_note": req.resolution_note,
            "resolved_by": req.resolved_by,
            "execution_result": req.execution_result,
            "created_at": req.created_at.isoformat() if req.created_at else None,
            "resolved_at": req.resolved_at.isoformat() if req.resolved_at else None,
        }


async def _noop(**kwargs) -> dict:
    """Placeholder for actions not yet fully wired. Must be async: this is
    called via `await fn(**kwargs)` like every other TOOL_REGISTRY target
    -- it was a plain `def` before, which made `update_contract` raise
    `TypeError: object dict can't be used in 'await' expression` on every
    approval, not silently succeed (see CLAUDE.md's Known-broken row for
    the corrected account of this)."""
    return {"status": "noop", "kwargs": kwargs}
