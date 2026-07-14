from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum


class PipelineStatusEnum(str, Enum):
    draft = "draft"; active = "active"; paused = "paused"; archived = "archived"


class PipelineCreate(BaseModel):
    name: str
    source_id: Optional[str] = None
    description: Optional[str] = None
    schedule_cron: Optional[str] = None
    config: Optional[dict] = {}
    sla_minutes: Optional[int] = None
    tags: Optional[List[str]] = []

class PipelineUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    schedule_cron: Optional[str] = None
    config: Optional[dict] = None
    sla_minutes: Optional[int] = None
    tags: Optional[List[str]] = None
    status: Optional[PipelineStatusEnum] = None

class ScheduleUpdate(BaseModel):
    cron_expression: str

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v):
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError("Must have exactly 5 fields: min hour dom mon dow")
        return v

class PipelineResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str] = None
    status: str
    schedule_cron: Optional[str] = None
    sla_minutes: Optional[int] = None
    tags: Optional[List[str]] = []
    version: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True