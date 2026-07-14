from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class SeverityEnum(str, Enum):
    low = "low"; medium = "medium"; high = "high"; critical = "critical"

class IncidentStatusEnum(str, Enum):
    open = "open"; investigating = "investigating"
    resolved = "resolved"; suppressed = "suppressed"

class ResolveRequest(BaseModel):
    resolution_notes: str

class IncidentResponse(BaseModel):
    id: str
    tenant_id: str
    pipeline_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    severity: str
    status: str
    root_cause: Optional[str] = None
    remediation_actions: Optional[List] = []
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None

    class Config:
        from_attributes = True