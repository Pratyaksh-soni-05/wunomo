from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class RunResponse(BaseModel):
    id: str
    pipeline_id: str
    tenant_id: str
    status: str
    triggered_by: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    rows_processed: Optional[int] = 0
    rows_failed: Optional[int] = 0
    quality_score: Optional[float] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True