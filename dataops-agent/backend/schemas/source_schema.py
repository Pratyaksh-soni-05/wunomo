from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class SourceTypeEnum(str, Enum):
    postgres = "postgres"; mysql = "mysql"; sqlite = "sqlite"
    bigquery = "bigquery"; snowflake = "snowflake"; csv = "csv"
    excel = "excel"; json = "json"; api_rest = "api_rest"
    google_sheets = "google_sheets"; s3 = "s3"; pdf = "pdf"; docx = "docx"


class SourceCreate(BaseModel):
    name: str
    source_type: SourceTypeEnum
    connection_config: dict
    tags: Optional[List[str]] = []
    owner: Optional[str] = None

class SourceUpdate(BaseModel):
    name: Optional[str] = None
    connection_config: Optional[dict] = None
    tags: Optional[List[str]] = None
    owner: Optional[str] = None
    is_active: Optional[bool] = None

class SourceResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    source_type: str
    is_active: bool
    tags: Optional[List[str]] = []
    owner: Optional[str] = None
    last_profiled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True