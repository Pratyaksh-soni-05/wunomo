from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from database import AsyncSessionLocal
from models.all_models import User, Tenant
from config import settings
from jose import JWTError, jwt
from datetime import datetime, timezone, timedelta
import uuid
import bcrypt
from slugify import slugify


router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw[:72].encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw[:72].encode("utf-8"), hashed.encode("utf-8"))


def create_token(data: dict) -> str:
    exp = utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode({**data, "exp": exp}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    tenant_name: str


@router.post("/register")
async def register(req: RegisterRequest):
    async with AsyncSessionLocal() as db:
        tenant = Tenant(
            id=str(uuid.uuid4()),
            name=req.tenant_name,
            slug=slugify(req.tenant_name) + "-" + str(uuid.uuid4())[:6],
            created_at=utcnow(),
        )
        db.add(tenant)
        await db.flush()
        user = User(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            email=req.email,
            hashed_password=hash_password(req.password),
            full_name=req.full_name,
            role="owner",
            created_at=utcnow(),
        )
        db.add(user)
        await db.commit()
        token = create_token({
            "sub": user.id,
            "tenant_id": tenant.id,
            "email": user.email,
            "role": user.role,
        })
        return {
            "access_token": token,
            "token_type": "bearer",
            "tenant_id": tenant.id,
            "user_id": user.id,
        }


@router.post("/login")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.email == form.username))
        user = r.scalars().first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid credentials")
    token = create_token({
        "sub": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "role": user.role,
    })
    return {"access_token": token, "token_type": "bearer",
            "user_id": user.id,
            "tenant_id": user.tenant_id,
    }


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return user