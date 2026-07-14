from pydantic import BaseModel, field_validator
from typing import Optional, List, Any
from enum import Enum


class PersonalityModeEnum(str, Enum):
    engineer = "engineer"; founder = "founder"
    analyst = "analyst"; auditor = "auditor"

class OperationModeEnum(str, Enum):
    advisory = "advisory"; assisted = "assisted"
    autonomous = "autonomous"; audit = "audit"

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    personality_mode: PersonalityModeEnum = PersonalityModeEnum.engineer
    operation_mode: OperationModeEnum = OperationModeEnum.assisted
    context: Optional[dict] = None

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v):
        if not v.strip():
            raise ValueError("message cannot be empty")
        return v.strip()

class ChatResponse(BaseModel):
    session_id: str
    response: str
    pending_approvals: List[Any] = []
    timestamp: str

class MessageResponse(BaseModel):
    role: str
    content: str
    timestamp: str