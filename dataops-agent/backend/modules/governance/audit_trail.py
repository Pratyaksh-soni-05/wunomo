import structlog
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, desc, and_
from database import AsyncSessionLocal
from models.all_models import AuditLog

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuditTrail:
    """
    Writes and queries the AuditLog table for AXIOM.

    Every significant action taken by a user or the agent should be logged:
      - API calls that mutate state (create, update, delete, trigger, resolve)
      - Agent tool executions
      - Approval grants and rejections
      - Schema changes and lineage registrations

    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # 1. Log an action
    # ------------------------------------------------------------------

    async def log_action(
        self,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        payload: dict | None = None,
        ip_address: str | None = None,
    ) -> dict:
        """
        Writes one AuditLog entry.

        Args:
            actor:         who performed the action (user email, "agent", "system", "celery")
            action:        what happened (e.g. "pipeline.triggered", "incident.resolved",
                           "rule.deleted", "approval.granted", "schema.modified")
            resource_type: type of the affected resource (pipeline, source, incident,
                           quality_rule, approval, contract, user)
            resource_id:   UUID of the affected resource
            payload:       additional context dict (before/after state, args, etc.)
            ip_address:    requester IP (from FastAPI Request, or None for background tasks)

        Returns: { "audit_id": ..., "logged": True }
        """
        log.info(
            "audit.log_action",
            tenant_id=self.tenant_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        try:
            async with AsyncSessionLocal() as db:
                entry = AuditLog(
                    tenant_id=self.tenant_id,
                    actor=actor,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    payload=payload or {},
                    ip_address=ip_address,
                    created_at=utcnow(),
                )
                db.add(entry)
                await db.commit()
                await db.refresh(entry)

            return {
                "audit_id": str(entry.id),
                "logged": True,
                "action": action,
                "actor": actor,
                "created_at": entry.created_at.isoformat(),
            }
        except Exception as exc:
            log.error("audit.log_action.error", tenant_id=self.tenant_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 2. Get audit trail with filters
    # ------------------------------------------------------------------

    async def get_audit_trail(
        self,
        resource_id: str | None = None,
        resource_type: str | None = None,
        actor: str | None = None,
        action_prefix: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Queries audit logs with optional filters. Always scoped to tenant.

        Args:
            resource_id:    filter to a specific resource UUID
            resource_type:  filter by resource type (pipeline, incident, etc.)
            actor:          filter by who did the action
            action_prefix:  filter by action prefix (e.g. "pipeline." matches all pipeline actions)
            limit:          max rows returned (default 100)

        Returns: list of audit log dicts, newest first
        """
        log.info(
            "audit.get_audit_trail",
            tenant_id=self.tenant_id,
            resource_id=resource_id,
            resource_type=resource_type,
            actor=actor,
        )
        try:
            async with AsyncSessionLocal() as db:
                query = (
                    select(AuditLog)
                    .where(AuditLog.tenant_id == self.tenant_id)
                    .order_by(desc(AuditLog.created_at))
                    .limit(limit)
                )
                if resource_id:
                    query = query.where(AuditLog.resource_id == resource_id)
                if resource_type:
                    query = query.where(AuditLog.resource_type == resource_type)
                if actor:
                    query = query.where(AuditLog.actor == actor)
                if action_prefix:
                    query = query.where(AuditLog.action.like(f"{action_prefix}%"))

                result = await db.execute(query)
                entries = result.scalars().all()

            output = [self._serialize(e) for e in entries]
            log.info("audit.get_audit_trail.done", count=len(output))
            return output

        except Exception as exc:
            log.error("audit.get_audit_trail.error", tenant_id=self.tenant_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 3. Get recent actions within N hours
    # ------------------------------------------------------------------

    async def get_recent_actions(self, hours: int = 24, limit: int = 200) -> list[dict]:
        """
        Returns all audit events from the last `hours` hours.
        Useful for dashboards, daily summaries, and anomaly detection.

        Returns: list of audit log dicts, newest first
        """
        log.info("audit.get_recent_actions", tenant_id=self.tenant_id, hours=hours)
        try:
            since = utcnow() - timedelta(hours=hours)
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(AuditLog)
                    .where(
                        AuditLog.tenant_id == self.tenant_id,
                        AuditLog.created_at >= since,
                    )
                    .order_by(desc(AuditLog.created_at))
                    .limit(limit)
                )
                entries = result.scalars().all()

            output = [self._serialize(e) for e in entries]
            log.info("audit.get_recent_actions.done", count=len(output), hours=hours)
            return output

        except Exception as exc:
            log.error("audit.get_recent_actions.error", tenant_id=self.tenant_id, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 4. Get activity summary (counts by action type)
    # ------------------------------------------------------------------

    async def get_activity_summary(self, hours: int = 24) -> dict:
        """
        Returns a count of actions grouped by resource_type and action
        for the given time window. Useful for the analytics dashboard.

        Returns:
          {
            "window_hours": N,
            "total_actions": N,
            "by_resource_type": { "pipeline": N, "incident": N, ... },
            "by_actor": { "user@email.com": N, "agent": N, ... },
            "top_actions": [ { "action": ..., "count": N } ]
          }
        """
        log.info("audit.get_activity_summary", tenant_id=self.tenant_id, hours=hours)
        try:
            entries = await self.get_recent_actions(hours=hours, limit=1000)
            if isinstance(entries, dict) and "error" in entries:
                return entries

            by_resource: dict[str, int] = {}
            by_actor: dict[str, int] = {}
            action_counts: dict[str, int] = {}

            for e in entries:
                rt = e.get("resource_type", "unknown")
                by_resource[rt] = by_resource.get(rt, 0) + 1

                actor = e.get("actor", "unknown")
                by_actor[actor] = by_actor.get(actor, 0) + 1

                action = e.get("action", "unknown")
                action_counts[action] = action_counts.get(action, 0) + 1

            top_actions = sorted(
                [{"action": k, "count": v} for k, v in action_counts.items()],
                key=lambda x: x["count"],
                reverse=True,
            )[:10]

            return {
                "window_hours": hours,
                "total_actions": len(entries),
                "by_resource_type": by_resource,
                "by_actor": by_actor,
                "top_actions": top_actions,
            }
        except Exception as exc:
            log.error("audit.get_activity_summary.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _serialize(self, entry: AuditLog) -> dict:
        return {
            "audit_id": str(entry.id),
            "actor": entry.actor,
            "action": entry.action,
            "resource_type": entry.resource_type,
            "resource_id": entry.resource_id,
            "payload": entry.payload or {},
            "ip_address": entry.ip_address,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }