from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from .auth import get_current_user, require_role
from services.rbac import Role, ALL_ROLES
from services.team_service import create_invite, send_invite_email, get_invite_by_token, accept_invite
from database import AsyncSessionLocal
from models.all_models import TeamInvite, Tenant, User

router = APIRouter()


class RoleChange(BaseModel):
    role: str


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


# ─── Members ──────────────────────────────────────────────────────────────

@router.get("/members")
async def list_team_members(user=Depends(get_current_user)):
    """Any authenticated tenant member can view the roster."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(User).where(User.tenant_id == user["tenant_id"]).order_by(User.created_at)
        )
        members = r.scalars().all()
    return {
        "members": [
            {
                "id": m.id, "email": m.email, "full_name": m.full_name,
                "role": m.role, "is_active": m.is_active, "created_at": m.created_at,
            }
            for m in members
        ]
    }


async def _active_owner_count(db, tenant_id: str, exclude_user_id: str = None) -> int:
    r = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id, User.role == Role.OWNER.value, User.is_active.is_(True),
        )
    )
    owners = r.scalars().all()
    return len([o for o in owners if o.id != exclude_user_id])


@router.patch("/members/{user_id}/role")
async def change_member_role(
    user_id: str,
    body: RoleChange,
    caller=Depends(require_role(Role.OWNER, Role.ADMIN)),
):
    if body.role not in ALL_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role '{body.role}'. Valid: {list(ALL_ROLES)}")

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(User).where(User.id == user_id, User.tenant_id == caller["tenant_id"])
        )
        target = r.scalars().first()
        if not target:
            raise HTTPException(status_code=404, detail="Member not found")

        # An admin (not owner) can't touch an owner's role or grant owner -
        # prevents privilege escalation via the role-change endpoint itself.
        if caller["role"] != Role.OWNER.value and (
            target.role == Role.OWNER.value or body.role == Role.OWNER.value
        ):
            raise HTTPException(status_code=403, detail="Only an owner can change an owner's role or grant owner")

        if target.role == Role.OWNER.value and body.role != Role.OWNER.value:
            if await _active_owner_count(db, caller["tenant_id"], exclude_user_id=target.id) == 0:
                raise HTTPException(status_code=400, detail="Cannot demote the last owner")

        target.role = body.role
        await db.commit()
    return {"message": "Role updated", "id": user_id, "role": body.role}


@router.delete("/members/{user_id}")
async def remove_team_member(
    user_id: str,
    caller=Depends(require_role(Role.OWNER, Role.ADMIN)),
):
    """Soft-removal (is_active=False), not a hard delete - User is
    referenced by real FKs with no cascade (OnboardingProfile.user_id,
    TeamInvite.invited_by_user_id), and preserving the historical row
    matches this codebase's established pattern (see Incident preservation
    in the pipeline-delete fix). Note: this doesn't revoke any JWT already
    issued to the removed user - it stays valid until it expires (see
    CLAUDE.md's JWT-revocation Gotcha); password login is blocked
    immediately since resolve_password_login() now filters is_active."""
    if user_id == caller["sub"]:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(User).where(User.id == user_id, User.tenant_id == caller["tenant_id"])
        )
        target = r.scalars().first()
        if not target:
            raise HTTPException(status_code=404, detail="Member not found")

        if caller["role"] != Role.OWNER.value and target.role == Role.OWNER.value:
            raise HTTPException(status_code=403, detail="Only an owner can remove an owner")

        # Combined with the self-removal block above and the admin-can't-
        # remove-an-owner check above, this is currently unreachable (the
        # only caller who could ever target the sole remaining owner is
        # that owner themselves, already blocked) - kept as defense in
        # depth in case either of those guards changes later.
        if target.role == Role.OWNER.value:
            if await _active_owner_count(db, caller["tenant_id"], exclude_user_id=target.id) == 0:
                raise HTTPException(status_code=400, detail="Cannot remove the last owner")

        target.is_active = False
        await db.commit()
    return {"message": "Member removed", "id": user_id}
