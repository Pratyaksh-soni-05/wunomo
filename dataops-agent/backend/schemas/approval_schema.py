from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
from models.approval_model import ApprovalStatus


class ApprovalResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    session_id: str
    action_name: str
    action_args: dict
    risk_level: str
    reason: str
    status: ApprovalStatus
    resolution_note: str
    resolved_by: Optional[str]
    execution_result: Optional[Any]
    created_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class ApprovalDecision(BaseModel):
    note: str = ""