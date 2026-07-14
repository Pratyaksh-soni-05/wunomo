from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, desc
from datetime import datetime, timezone
from .auth import get_current_user
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
    user=Depends(get_current_user)
):
    async with AsyncSessionLocal() as db:
        q = select(Incident).where(
            Incident.tenant_id == user["tenant_id"]
        ).order_by(desc(Incident.detected_at)).limit(limit)
        if status:
            q = q.where(Incident.status == IncidentStatus(status))
        if severity:
            q = q.where(Incident.severity == IncidentSeverity(severity))
        r = await db.execute(q)
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
            "count": len(incidents)
        }


@router.post("/")
async def create_incident(req: IncidentCreate, user=Depends(get_current_user)):
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
                          user=Depends(get_current_user)):
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
                           user=Depends(get_current_user)):
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