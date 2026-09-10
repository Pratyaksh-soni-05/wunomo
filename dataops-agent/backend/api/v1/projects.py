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
from sqlalchemy import delete, select, update

from .auth import require_permission
from database import AsyncSessionLocal
from models.all_models import AgentInstance, Channel, Project, ProjectAgent

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str


class ProjectRename(BaseModel):
    name: str


async def _get_own_project(db, project_id: str, tenant_id: str) -> Project:
    r = await db.execute(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))
    project = r.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


async def _name_collision(db, tenant_id: str, name: str, exclude_project_id: str | None = None):
    query = select(Project).where(Project.tenant_id == tenant_id, Project.name == name)
    if exclude_project_id is not None:
        query = query.where(Project.id != exclude_project_id)
    r = await db.execute(query)
    if r.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"A project named '{name}' already exists.")


@router.post("/")
async def create_project(body: ProjectCreate, user=Depends(require_permission("agents.manage"))):
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty.")
    tenant_id = user["tenant_id"]

    async with AsyncSessionLocal() as db:
        await _name_collision(db, tenant_id, body.name.strip())

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


@router.patch("/{project_id}")
async def rename_project(project_id: str, body: ProjectRename, user=Depends(require_permission("agents.manage"))):
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty.")
    tenant_id = user["tenant_id"]

    async with AsyncSessionLocal() as db:
        project = await _get_own_project(db, project_id, tenant_id)
        await _name_collision(db, tenant_id, body.name.strip(), exclude_project_id=project_id)

        project.name = body.name.strip()
        await db.commit()
        await db.refresh(project)

    return {"id": project.id, "name": project.name, "created_at": project.created_at}


@router.delete("/{project_id}")
async def delete_project(project_id: str, user=Depends(require_permission("agents.manage"))):
    """A project just groups agents/channels (see module + model
    docstrings) -- deleting it ungroups them, never touches the grouped
    rows themselves. Neither ProjectAgent nor Channel.project_id has an
    ON DELETE clause (default NO ACTION), so this must explicitly clear
    both before the Project row itself, in this exact order, inside one
    transaction: ProjectAgent rows (the only thing that ever pointed at
    this project from the agent side -- AgentInstance has no project_id
    column at all, so there is nothing else to touch there), then
    Channel.project_id -> NULL (nullable by design -- "a channel MAY live
    inside a project," per Channel's own docstring), then the Project row.
    No task-blocking check here unlike offboard_agent's non-terminal-task
    guard -- a project is standing grouping metadata, not something with
    its own in-flight execution to protect; the agents/channels it grouped
    keep running exactly as before, just ungrouped."""
    tenant_id = user["tenant_id"]

    async with AsyncSessionLocal() as db:
        project = await _get_own_project(db, project_id, tenant_id)

        await db.execute(delete(ProjectAgent).where(ProjectAgent.project_id == project_id))
        await db.execute(update(Channel).where(Channel.project_id == project_id).values(project_id=None))
        await db.delete(project)
        await db.commit()

    return {"id": project_id, "deleted": True}


@router.get("/{project_id}/agents")
async def list_project_agents(project_id: str, user=Depends(require_permission("agents.manage"))):
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        await _get_own_project(db, project_id, tenant_id)

        r = await db.execute(
            select(AgentInstance.id, AgentInstance.name, AgentInstance.employee_type)
            .join(ProjectAgent, ProjectAgent.agent_id == AgentInstance.id)
            .where(ProjectAgent.project_id == project_id)
        )
        agents = [{"id": aid, "name": name, "employee_type": et.value} for aid, name, et in r.all()]

    return {"project_id": project_id, "agents": agents}


@router.get("/{project_id}/channels")
async def list_project_channels(project_id: str, user=Depends(require_permission("agents.manage"))):
    """Read side for the delete-confirmation dialog (explicit requirement:
    it must name what survives, not just warn generically) -- tenant-wide,
    not scoped to the caller's own channel membership the way GET /api/v1/
    channels/ is, since an Owner/Admin deleting a project needs to see
    every channel it groups, not just the ones they personally joined."""
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        await _get_own_project(db, project_id, tenant_id)

        r = await db.execute(select(Channel.id, Channel.name).where(Channel.project_id == project_id))
        channels = [{"id": cid, "name": name} for cid, name in r.all()]

    return {"project_id": project_id, "channels": channels}
