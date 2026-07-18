from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from .auth import get_current_user, require_role
from services.rbac import Role
from services.team_service import create_invite, send_invite_email, get_invite_by_token, accept_invite
from database import AsyncSessionLocal
from models.all_models import TeamInvite, Tenant

router = APIRouter()


class InviteCreate(BaseModel):
    email: EmailStr
    role: str


class InviteAccept(BaseModel):
    token: str
    password: str
    full_name: str = ""


@router.post("/invites")
async def create_team_invite(
    body: InviteCreate,
    user=Depends(require_role(Role.OWNER, Role.ADMIN)),
):
    result = await create_invite(
        tenant_id=user["tenant_id"], email=body.email, role=body.role,
        invited_by_user_id=user["sub"],
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant).where(Tenant.id == user["tenant_id"]))
        tenant = r.scalars().first()

    await send_invite_email(
        email=body.email, token=result["token"], tenant_name=tenant.name if tenant else "your workspace",
        inviter_email=user["email"], role=body.role,
    )
    invite = result["invite"]
    return {
        "id": invite.id, "email": invite.email, "role": invite.role,
        "status": invite.status, "expires_at": invite.expires_at,
        "invite_link_token": result["token"],
    }


@router.get("/invites")
async def list_team_invites(user=Depends(require_role(Role.OWNER, Role.ADMIN))):
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(TeamInvite)
            .where(TeamInvite.tenant_id == user["tenant_id"])
            .order_by(TeamInvite.created_at.desc())
        )
        invites = r.scalars().all()
    return {
        "invites": [
            {
                "id": i.id, "email": i.email, "role": i.role, "status": i.status,
                "expires_at": i.expires_at, "created_at": i.created_at,
                "accepted_at": i.accepted_at,
            }
            for i in invites
        ]
    }


@router.delete("/invites/{invite_id}")
async def revoke_team_invite(
    invite_id: str,
    user=Depends(require_role(Role.OWNER, Role.ADMIN)),
):
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(TeamInvite).where(
                TeamInvite.id == invite_id, TeamInvite.tenant_id == user["tenant_id"],
            )
        )
        invite = r.scalars().first()
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
        invite.status = "revoked"
        await db.commit()
    return {"message": "Invite revoked", "id": invite_id}


@router.get("/invites/verify")
async def verify_team_invite(token: str):
    """Public - no auth. Lets an accept-invite UI show who's inviting and
    to which workspace/role before the invitee submits a password."""
    info = await get_invite_by_token(token)
    if not info:
        raise HTTPException(status_code=404, detail="Invalid or expired invite")
    return info


@router.post("/invites/accept")
async def accept_team_invite(body: InviteAccept):
    """Public - no auth. tenant_id and role come from the invite token
    itself, never from the request body (Phase 3's locked invite-join
    design: invitee never chooses their own tenant/role)."""
    result = await accept_invite(token=body.token, password=body.password, full_name=body.full_name)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
