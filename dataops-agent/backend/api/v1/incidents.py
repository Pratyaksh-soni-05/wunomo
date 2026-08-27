from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, desc, func
from datetime import datetime, timezone
from .auth import get_current_user, require_permission
from database import AsyncSessionLocal
from models.all_models import (
    Incident, IncidentSeverity, IncidentStatus
)
import uuid

router = APIRouter()

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)


class IncidentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    severity: Optional[str] = "medium"
    pipeline_id: Optional[str] = None
    affected_assets: Optional[list] = []


class IncidentResolve(BaseModel):
    resolution_notes: str


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    root_cause: Optional[str] = None
    remediation_actions: Optional[list] = None


@router.get("/")
async def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_current_user)
):
    async with AsyncSessionLocal() as db:
        filters = [Incident.tenant_id == user["tenant_id"]]
        if status:
            filters.append(Incident.status == IncidentStatus(status))
        if severity:
            filters.append(Incident.severity == IncidentSeverity(severity))

        # item 55 fix: "count" previously echoed len(page) - always equal to
        # whatever the truncated page returned, never the true total. A
        # real total needs its own COUNT(*) query, run against the same
        # filters as the page query, not derived from the page itself.
        count_q = select(func.count()).select_from(Incident).where(*filters)
        total = (await db.execute(count_q)).scalar_one()

        page_q = (
            select(Incident).where(*filters)
            .order_by(desc(Incident.detected_at))
            .offset(offset).limit(limit)
        )
        r = await db.execute(page_q)
        incidents = r.scalars().all()
        return {
            "incidents": [
                {
                    "id": i.id, "title": i.title,
                    "description": i.description,
                    "severity": i.severity, "status": i.status,
                    "pipeline_id": i.pipeline_id,
                    "root_cause": i.root_cause,
                    "affected_assets": i.affected_assets or [],
                    "detected_at": str(i.detected_at),
                    "resolved_at": str(i.resolved_at) if i.resolved_at else None
                }
                for i in incidents
            ],
            "count": total,
            "offset": offset,
            "limit": limit
        }


@router.post("/")
async def create_incident(req: IncidentCreate, user=Depends(require_permission("incidents.log"))):
    async with AsyncSessionLocal() as db:
        incident = Incident(
            id=str(uuid.uuid4()),
            tenant_id=user["tenant_id"],
            title=req.title,
            description=req.description,
            severity=IncidentSeverity(req.severity),
            pipeline_id=req.pipeline_id,
            affected_assets=req.affected_assets or [],
            status=IncidentStatus.OPEN,
            detected_at=utcnow(),
            created_at=utcnow()
        )
        db.add(incident)
        await db.commit()
        await db.refresh(incident)

        # NotificationService.notify_incident() existed but was never
        # called from anywhere real -- see CLAUDE.md's "notification
        # presets never fire automatically" Known-broken row. This is a
        # genuinely one-shot trigger (a real incident being logged, not a
        # recurring poll), so no spam risk the way the freshness checker's
        # known duplicate-incident gap would create if wired the same way.
        # Never raises (see NotificationService's own docstring) but
        # wrapped defensively anyway -- a notification failure must never
        # break incident creation itself.
        try:
            from modules.reporting.notification_service import NotificationService
            pipeline_name = None
            if incident.pipeline_id:
                from models.all_models import Pipeline
                p = await db.execute(select(Pipeline).where(Pipeline.id == incident.pipeline_id))
                pipeline_row = p.scalars().first()
                pipeline_name = pipeline_row.name if pipeline_row else None
            await NotificationService(user["tenant_id"]).notify_incident(
                incident_id=incident.id, title=incident.title,
                severity=incident.severity, pipeline_name=pipeline_name,
            )
        except Exception as notify_exc:
            import structlog
            structlog.get_logger().warning(
                "incident_notification_error", incident_id=incident.id, error=str(notify_exc)
            )

        return {"id": incident.id, "title": incident.title,
                "severity": incident.severity, "status": incident.status}


@router.get("/{incident_id}")
async def get_incident(incident_id: str, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Incident).where(
            Incident.id == incident_id,
            Incident.tenant_id == user["tenant_id"]
        ))
        i = r.scalars().first()
        if not i:
            raise HTTPException(status_code=404, detail="Incident not found")
        return {
            "id": i.id, "title": i.title, "description": i.description,
            "severity": i.severity, "status": i.status,
            "pipeline_id": i.pipeline_id, "run_id": i.run_id,
            "root_cause": i.root_cause,
            "remediation_actions": i.remediation_actions or [],
            "affected_assets": i.affected_assets or [],
            "detected_at": str(i.detected_at),
            "resolved_at": str(i.resolved_at) if i.resolved_at else None,
            "resolution_notes": i.resolution_notes
        }


@router.put("/{incident_id}")
async def update_incident(incident_id: str, req: IncidentUpdate,
                          user=Depends(require_permission("incidents.resolve"))):
    # Gated at incidents.resolve, not incidents.log: this endpoint can set
    # status to "resolved" (req.status), the same sensitive transition the
    # dedicated /resolve endpoint gates - gating this one lower would let a
    # role blocked from /resolve achieve the same effect through here.
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Incident).where(
            Incident.id == incident_id,
            Incident.tenant_id == user["tenant_id"]
        ))
        i = r.scalars().first()
        if not i:
            raise HTTPException(status_code=404, detail="Incident not found")
        if req.title:               i.title = req.title
        if req.description:         i.description = req.description
        if req.severity:            i.severity = IncidentSeverity(req.severity)
        if req.status:              i.status = IncidentStatus(req.status)
        if req.root_cause:          i.root_cause = req.root_cause
        if req.remediation_actions: i.remediation_actions = req.remediation_actions
        await db.commit()
        return {"message": "Incident updated", "id": incident_id}


@router.post("/{incident_id}/resolve")
async def resolve_incident(incident_id: str, req: IncidentResolve,
                           user=Depends(require_permission("incidents.resolve"))):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Incident).where(
            Incident.id == incident_id,
            Incident.tenant_id == user["tenant_id"]
        ))
        i = r.scalars().first()
        if not i:
            raise HTTPException(status_code=404, detail="Incident not found")
        i.status = IncidentStatus.RESOLVED
        i.resolved_at = utcnow()
        i.resolution_notes = req.resolution_notes
        await db.commit()
        return {"message": "Incident resolved", "id": incident_id,
                "resolved_at": i.resolved_at.isoformat()}