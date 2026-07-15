from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import select
from .auth import get_current_user
from database import AsyncSessionLocal
from models.all_models import OnboardingProfile
from datetime import datetime
import uuid

router = APIRouter()


class OnboardingRequest(BaseModel):
    role: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    use_cases: List[str] = []
    data_stack: List[str] = []


def utcnow() -> datetime:
    return datetime.utcnow()


@router.post("/")
async def submit_onboarding(req: OnboardingRequest, user=Depends(get_current_user)):
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(OnboardingProfile).where(OnboardingProfile.tenant_id == tenant_id))
        profile = r.scalars().first()

        if profile is None:
            profile = OnboardingProfile(id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user["sub"])
            db.add(profile)

        profile.role = req.role
        profile.industry = req.industry
        profile.company_size = req.company_size
        profile.use_cases = req.use_cases
        profile.data_stack = req.data_stack
        profile.completed_at = utcnow()

        await db.commit()
        await db.refresh(profile)

        return {
            "id": profile.id,
            "tenant_id": profile.tenant_id,
            "role": profile.role,
            "industry": profile.industry,
            "company_size": profile.company_size,
            "use_cases": profile.use_cases,
            "data_stack": profile.data_stack,
            "completed_at": profile.completed_at.isoformat() if profile.completed_at else None,
        }


@router.get("/")
async def get_onboarding(user=Depends(get_current_user)):
    tenant_id = user["tenant_id"]
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(OnboardingProfile).where(OnboardingProfile.tenant_id == tenant_id))
        profile = r.scalars().first()

    if profile is None:
        return {"completed": False}

    return {
        "completed": True,
        "id": profile.id,
        "role": profile.role,
        "industry": profile.industry,
        "company_size": profile.company_size,
        "use_cases": profile.use_cases,
        "data_stack": profile.data_stack,
        "completed_at": profile.completed_at.isoformat() if profile.completed_at else None,
    }
