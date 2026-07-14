from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class KpiResponse(BaseModel):
    kpi_name: str
    value: float
    unit: Optional[str] = None
    recorded_at: datetime

    class Config:
        from_attributes = True

class HealthSummary(BaseModel):
    total_pipelines: int
    active_pipelines: int
    failed_runs_24h: int
    open_incidents: int
    avg_quality_score: Optional[float] = None
    data_freshness_pct: Optional[float] = None