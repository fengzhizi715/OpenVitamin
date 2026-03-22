"""
Skill v2 Registry: 支持多版本管理的内存注册表。

设计原则：
- Registry 不负责执行
- key 改为 (id, version)
- 支持多版本并存
- 默认返回 latest active version
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from log import logger
from core.skills.models import Skill, SkillDefinition
from core.skills.service import get_skill_store


class SkillRegistry:
    """
    内存中的 Skill 注册表，启动时从 Store 加载。
    
    数据结构：
    _skills: Dict[str, Dict[str, SkillDefinition]]
    # {
    #   "email.send": {
    #       "1.0.0": SkillDefinition,
    #       "1.1.0": SkillDefinition
    #   }
    # }
    """

    _skills: Dict[str, Dict[str, SkillDefinition]] = {}  # id -> {version -> definition}

    @classmethod
    def load(cls) -> None:
        """从 Store 加载所有 Skills（v1 转 v2）"""
        store = get_skill_store()
        skills = store.list_all(enabled_only=False)
        
        cls._skills = {}
        for skill in skills:
            # v1 转 v2 - 保留原有的 type 和 definition 字段
            if isinstance(skill, Skill):
                v2_def = skill.to_v2()
                # 重要：从原始 skill 对象保留 type 和 definition，避免被 to_v2() 覆盖
                v2_def.type = skill.type
                v2_def.definition = skill.definition
            else:
                v2_def = skill
            cls.register(v2_def)
        
        logger.info(f"[SkillRegistry] Loaded {len(cls._skills)} skills (v2 format)")

    @classmethod
    def get(cls, skill_id: str, version: Optional[str] = None) -> Optional[SkillDefinition]:
        """
        获取 Skill 定义
        
        Args:
            skill_id: Skill ID
            version: 版本号（不指定则返回 latest active）
        
        Returns:
            SkillDefinition 或 None
        """
        if skill_id not in cls._skills:
            return None
        
        versions = cls._skills[skill_id]
        
        if version:
            # 指定版本
            return versions.get(version)
        else:
            # 返回 latest active version
            return cls.get_latest(skill_id)

    @classmethod
    def get_latest(cls, skill_id: str) -> Optional[SkillDefinition]:
        """
        获取最新活跃版本
        
        策略：
        1. 按语义化版本排序
        2. 只考虑 enabled=True 的版本
        3. 返回最大的版本号
        """
        if skill_id not in cls._skills:
            return None
        
        versions = cls._skills[skill_id]
        active_versions = [
            (ver, defn) for ver, defn in versions.items()
            if defn.enabled
        ]
        
        if not active_versions:
            return None
        
        # 按语义化版本排序
        def parse_version(ver_str: str) -> Tuple[int, int, int]:
            parts = ver_str.split('.')
            try:
                return (
                    int(parts[0]) if len(parts) > 0 else 0,
                    int(parts[1]) if len(parts) > 1 else 0,
                    int(parts[2]) if len(parts) > 2 else 0
                )
            except (ValueError, IndexError):
                return (0, 0, 0)
        
        # 排序并返回最大的
        active_versions.sort(key=lambda x: parse_version(x[0]), reverse=True)
        return active_versions[0][1]

    @classmethod
    def list_versions(cls, skill_id: str) -> List[str]:
        """列出某个 Skill 的所有版本"""
        if skill_id not in cls._skills:
            return []
        return list(cls._skills[skill_id].keys())

    @classmethod
    def deprecate(cls, skill_id: str, version: str) -> bool:
        """
        废弃某个版本
        
        注意：
        - 不会删除版本
        - 只设置 enabled=False
        - 如果这是最后一个活跃版本，拒绝操作
        """
        if skill_id not in cls._skills:
            return False
        
        if version not in cls._skills[skill_id]:
            return False
        
        # 检查是否是最后一个活跃版本
        versions = cls._skills[skill_id]
        active_count = sum(1 for v in versions.values() if v.enabled)
        
        if active_count <= 1 and versions[version].enabled:
            logger.warning(
                f"[SkillRegistry] Cannot deprecate last active version: {skill_id}@{version}"
            )
            return False
        
        # 设置为废弃
        versions[version].enabled = False
        versions[version].updated_at = datetime.utcnow()
        
        logger.info(f"[SkillRegistry] Deprecated {skill_id}@{version}")
        return True

    @classmethod
    def register(cls, definition: SkillDefinition) -> None:
        """
        注册 Skill
        
        规则：
        - 不允许覆盖相同 id + version
        - 自动添加到版本列表
        - 支持 v1 Skill 对象自动转换（向后兼容）
        """
        # 向后兼容：如果是 v1 Skill 对象，自动转换为 v2
        if isinstance(definition, Skill):
            v1_skill = definition
            definition = v1_skill.to_v2()
            # 保留原始的 type 和 definition
            definition.type = v1_skill.type
            definition.definition = v1_skill.definition
        
        if not isinstance(definition, SkillDefinition):
            raise TypeError(f"Expected SkillDefinition or Skill, got {type(definition)}")
        
        if definition.id not in cls._skills:
            cls._skills[definition.id] = {}
        
        versions = cls._skills[definition.id]
        
        # 检查是否已存在
        if definition.version in versions:
            logger.warning(
                f"[SkillRegistry] Skill already exists: {definition.id}@{definition.version}, skipping registration"
            )
            return
        
        # 注册新版本
        versions[definition.version] = definition
        logger.info(f"[SkillRegistry] Registered {definition.id}@{definition.version}")

    @classmethod
    def unregister(cls, skill_id: str, version: Optional[str] = None) -> None:
        """
        注销 Skill
        
        Args:
            skill_id: Skill ID
            version: 指定版本（不指定则删除整个 Skill）
        """
        if skill_id not in cls._skills:
            return
        
        if version:
            # 删除指定版本
            cls._skills[skill_id].pop(version, None)
            
            # 如果没有版本了，删除整个 Skill
            if not cls._skills[skill_id]:
                del cls._skills[skill_id]
        else:
            # 删除整个 Skill
            del cls._skills[skill_id]
        
        logger.info(f"[SkillRegistry] Unregistered {skill_id}" + (f"@{version}" if version else ""))

    @classmethod
    def list_all(cls, enabled_only: bool = False) -> List[SkillDefinition]:
        """列出所有 Skills（所有版本）"""
        out = []
        for versions in cls._skills.values():
            for definition in versions.values():
                if enabled_only and not definition.enabled:
                    continue
                out.append(definition)
        return out

    @classmethod
    def list_for_agent(cls, enabled_skill_ids: List[str], enabled_only: bool = True) -> List[SkillDefinition]:
        """
        返回 Agent 可见的 Skill 列表（按 enabled_skill_ids 顺序排列）
        
        对于每个 skill_id，只返回 latest active version
        """
        out = []
        for skill_id in enabled_skill_ids:
            definition = cls.get(skill_id)
            if definition is None:
                continue
            if enabled_only and not definition.enabled:
                continue
            out.append(definition)
        return out

    @classmethod
    def clear(cls) -> None:
        """清空注册表（用于测试）"""
        cls._skills = {}
