from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from .auth import get_current_user, require_role
from services.rbac import Role
from modules.quality.rule_engine import QualityRuleEngine

router = APIRouter()


class RuleCreate(BaseModel):
    pipeline_id: str
    name: str
    rule_type: str
    column_name: Optional[str] = None
    rule_config: Optional[dict] = {}
    severity: Optional[str] = "high"
    is_blocking: Optional[bool] = True


@router.get("/")
async def list_rules(pipeline_id: str = None, user=Depends(get_current_user)):
    return await QualityRuleEngine(user["tenant_id"]).list_rules(pipeline_id)


@router.post("/")
async def create_rule(req: RuleCreate, user=Depends(get_current_user)):
    result = await QualityRuleEngine(user["tenant_id"]).create_rule(
        pipeline_id=req.pipeline_id, name=req.name,
        rule_type=req.rule_type, column_name=req.column_name,
        rule_config=req.rule_config, severity=req.severity,
        is_blocking=req.is_blocking
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{pipeline_id}/run")
async def run_checks(pipeline_id: str, user=Depends(get_current_user)):
    return await QualityRuleEngine(user["tenant_id"]).run_checks(pipeline_id)


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str, user=Depends(require_role(Role.OWNER, Role.ADMIN, Role.DATA_ENGINEER))):
    result = await QualityRuleEngine(user["tenant_id"]).delete_rule(rule_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result