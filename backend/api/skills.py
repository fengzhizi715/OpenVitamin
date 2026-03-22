"""
Skill v1 FastAPI 接口：创建、列表、获取、执行。
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.skills import create_skill, get_skill, list_skills, SkillExecutor, update_skill, delete_skill
from core.skills.models import SkillType
from core.skills.registry import SkillRegistry

router = APIRouter(prefix="/api/skills", tags=["skills"])


class CreateSkillBody(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    category: str = ""
    type: SkillType = "prompt"
    input_schema: Optional[Dict[str, Any]] = None
    definition: Optional[Dict[str, Any]] = None
    enabled: bool = True


class UpdateSkillBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    category: Optional[str] = None
    type: Optional[SkillType] = None
    input_schema: Optional[Dict[str, Any]] = None
    definition: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class ExecuteSkillBody(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)


@router.post("")
async def api_create_skill(body: CreateSkillBody):
    """创建 Skill。"""
    skill = create_skill(
        name=body.name,
        description=body.description,
        category=body.category,
        type=body.type,
        definition=body.definition,
        input_schema=body.input_schema,
        enabled=body.enabled,
    )
    if not skill:
        raise HTTPException(status_code=500, detail="Failed to create skill")
    SkillRegistry.register(skill)
    return skill.to_dict()


@router.get("")
async def api_list_skills():
    """列出所有 Skill。"""
    skills = list_skills(enabled_only=False)
    return {
        "object": "list",
        "data": [s.to_dict() for s in skills],
    }


@router.get("/{skill_id}")
async def api_get_skill(skill_id: str):
    """获取单个 Skill。"""
    skill = get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.to_dict()


@router.put("/{skill_id}")
async def api_update_skill(skill_id: str, body: UpdateSkillBody):
    """更新 Skill。"""
    if skill_id.startswith("builtin_"):
        raise HTTPException(status_code=400, detail="Cannot update built-in skill")
    skill = get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    updated = update_skill(
        skill_id,
        name=body.name,
        description=body.description,
        category=body.category,
        type=body.type,
        definition=body.definition,
        input_schema=body.input_schema,
        enabled=body.enabled,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update skill")
    return updated.to_dict()


@router.delete("/{skill_id}")
async def api_delete_skill(skill_id: str):
    """删除 Skill。内置 builtin_* 不可删除。"""
    if skill_id.startswith("builtin_"):
        raise HTTPException(status_code=400, detail="Cannot delete built-in skill")
    if not delete_skill(skill_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"status": "ok"}


@router.post("/{skill_id}/execute")
async def api_execute_skill(skill_id: str, body: ExecuteSkillBody):
    """执行 Skill（供 Agent Runtime 使用）。返回 type + output（及可选的 error / prompt）。"""
    from core.skills.contract import SkillExecutionRequest
    
    skill = get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    # 构建执行请求
    request = SkillExecutionRequest(
        skill_id=skill_id,
        input=body.inputs,
        trace_id=f"api_{skill_id}",
        caller_id="api",
    )
    
    # 使用 SkillExecutor 统一入口执行
    response = await SkillExecutor.execute(request)
    
    # 转换响应格式
    if response.status == "success":
        return {"type": "success", "output": response.output}
    elif response.status == "timeout":
        return {"type": "error", "error": response.error.get("message", "Timeout")}
    else:
        return {"type": "error", "error": response.error.get("message", "Unknown error")}
