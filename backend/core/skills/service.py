"""
Skill v1 业务逻辑：创建、列表、获取。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from log import logger
from core.skills.models import Skill, SkillType
from core.skills.store import get_skill_store as _get_skill_store


def get_skill_store():
    """获取 Skill 存储单例（使用 store.py 中的实现）"""
    return _get_skill_store()


def create_skill(
    name: str,
    description: str = "",
    category: str = "",
    type: SkillType = "prompt",
    definition: Optional[Dict[str, Any]] = None,
    input_schema: Optional[Dict[str, Any]] = None,
    enabled: bool = True,
) -> Skill:
    store = get_skill_store()
    return store.create(
        name=name,
        description=description,
        category=category,
        type=type,
        definition=definition,
        input_schema=input_schema,
        enabled=enabled,
    )


def list_skills(enabled_only: bool = False) -> List[Skill]:
    return get_skill_store().list_all(enabled_only=enabled_only)


def get_skill(skill_id: str) -> Optional[Skill]:
    return get_skill_store().get(skill_id)


def update_skill(
    skill_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    type: Optional[SkillType] = None,
    definition: Optional[Dict[str, Any]] = None,
    input_schema: Optional[Dict[str, Any]] = None,
    enabled: Optional[bool] = None,
) -> Optional[Skill]:
    """Update a skill; returns updated skill or None if not found."""
    if skill_id.startswith("builtin_"):
        # backend hard-guard to keep built-ins immutable
        return None
    store = get_skill_store()
    updated = store.update(
        skill_id,
        name=name,
        description=description,
        category=category,
        type=type,
        definition=definition,
        input_schema=input_schema,
        enabled=enabled,
    )
    if updated:
        from core.skills.registry import SkillRegistry
        SkillRegistry.register(updated)
    return updated


def delete_skill(skill_id: str) -> bool:
    """Delete a skill by id; also unregister from SkillRegistry. Returns True if deleted."""
    store = get_skill_store()
    if not store.get(skill_id):
        return False
    ok = store.delete(skill_id)
    if ok:
        from core.skills.registry import SkillRegistry
        SkillRegistry.unregister(skill_id)
    return ok


def bootstrap_builtin_skills() -> int:
    """
    将 ToolRegistry 中每个 Tool 自动注册为 Built-in Skill（若尚不存在）。
    返回本次新创建的 Skill 数量。
    """
    from core.tools.registry import ToolRegistry
    from core.skills.registry import SkillRegistry

    store = get_skill_store()
    created = 0
    for tool in ToolRegistry.list():
        builtin_id = f"builtin_{tool.name}"
        existing = store.get(builtin_id)
        if existing:
            updated = store.update(
                builtin_id,
                name=tool.name,
                description=tool.description or "",
                category="builtin",
                type="tool",
                definition={"tool_name": tool.name, "tool_args_mapping": {}},
                input_schema=tool.input_schema or {"type": "object", "properties": {}, "required": []},
                enabled=True,
            )
            if updated:
                SkillRegistry.register(updated)
                logger.info(f"[Skills] Synced built-in skill: {builtin_id}")
            else:
                SkillRegistry.register(existing)
            continue
        if SkillRegistry.get(builtin_id):
            continue
        skill = store.create(
            name=tool.name,
            description=tool.description or "",
            category="builtin",
            type="tool",
            definition={"tool_name": tool.name, "tool_args_mapping": {}},
            input_schema=tool.input_schema or {"type": "object", "properties": {}, "required": []},
            enabled=True,
            skill_id=builtin_id,
        )
        SkillRegistry.register(skill)
        created += 1
        logger.info(f"[Skills] Registered built-in skill: {builtin_id}")
    
    # Register composite/workflow skills
    try:
        from core.plugins.builtin.skills import register_builtin_composite_skills
        n_composite = register_builtin_composite_skills()
        created += n_composite
        if n_composite:
            logger.info(f"[Skills] Registered {n_composite} built-in composite skills")
    except Exception as e:
        logger.error(f"[Skills] Failed to register composite skills: {e}")
    
    return created
