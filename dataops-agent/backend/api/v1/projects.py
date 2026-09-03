"""Wunomo Projects Phase 1, part two: projects.

"A project is an object inside a tenant" (WUNOMO_PROJECTS_PROPOSAL_v2.md's
own correction to itself) -- not a workspace/tenant substitute. A project
just groups agents (via ProjectAgent, see models/all_models.py) inside the
tenant that already owns billing, team, and sources. Role-gated to
agents.manage (Owner/Admin) -- same tier as hiring itself, since creating
a project is an org-structural action, not an operational one.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .auth import require_permission
from database import AsyncSessionLocal
from models.all_models import AgentInstance, Project, ProjectAgent

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str


@router.post("/")
async def create_project(body: ProjectCreate, user=Depends(require_permission("agents.manage"))):
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty.")
    tenant_id = user["tenant_id"]

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(Project).where(
            Project.tenant_id == tenant_id, Project.name == body.name.strip(),
        ))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"A project named '{body.name}' already exists.")

        project = Project(id=str(uuid.uuid4()), tenant_id=tenant_id, name=body.name.strip())
        db.add(project)
        await db.commit()
        await db.refresh(project)

    return {"id": project.id, "name": project.name, "created_at": project.created_at}


@router.get("/")
async def list_projects(user=Depends(require_permission("agents.manage"))):
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Project).where(Project.tenant_id == tenant_id).order_by(Project.created_at.desc())
        )
        projects = r.scalars().all()
    return {"projects": [{"id": p.id, "name": p.name, "created_at": p.created_at} for p in projects]}


@router.get("/{project_id}/agents")
async def list_project_agents(project_id: str, user=Depends(require_permission("agents.manage"))):
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
        if r.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        r = await db.execute(
            select(AgentInstance.id, AgentInstance.name, AgentInstance.employee_type)
            .join(ProjectAgent, ProjectAgent.agent_id == AgentInstance.id)
            .where(ProjectAgent.project_id == project_id)
        )
        agents = [{"id": aid, "name": name, "employee_type": et.value} for aid, name, et in r.all()]

    return {"project_id": project_id, "agents": agents}
