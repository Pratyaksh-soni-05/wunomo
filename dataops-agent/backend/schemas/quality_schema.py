from pydantic import BaseModel, field_validator
from typing import Optional
from enum import Enum


class SeverityEnum(str, Enum):
    low = "low"; medium = "medium"; high = "high"; critical = "critical"

VALID_RULE_TYPES = {
    "not_null", "unique", "range", "regex",
    "referential_integrity", "freshness",
    "row_count", "custom_sql",
}

class RuleCreate(BaseModel):
    pipeline_id: str
    rule_type: str
    column_name: Optional[str] = None
    rule_config: dict
    severity: SeverityEnum = SeverityEnum.high
    is_blocking: bool = True

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v):
        if v not in VALID_RULE_TYPES:
            raise ValueError(f"rule_type must be one of {VALID_RULE_TYPES}")
        return v

class RuleResponse(BaseModel):
    id: str
    pipeline_id: str
    tenant_id: str
    name: str
    rule_type: str
    column_name: Optional[str] = None
    severity: str
    is_blocking: bool
    is_active: bool
    pass_count: int
    fail_count: int

    class Config:
        from_attributes = True