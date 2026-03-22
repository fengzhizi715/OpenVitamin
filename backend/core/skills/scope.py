"""
Skill Scope & Permission 模块

提供访问控制和作用域解析
"""
from __future__ import annotations

from typing import List, Optional

from log import logger


class SkillScopeResolver:
    """
    Skill 作用域解析器
    
    职责：
    - 判断 Agent 是否有权限访问 Skill
    - 支持多组织、多 Agent 隔离
    
    设计原则：
    - 与 Registry 分离（Registry 不负责权限）
    - 与 Discovery 配合（Discovery 调用 Scope 过滤）
    - 可扩展（未来支持更复杂的 ACL）
    """
    
    def is_visible(
        self,
        skill: "SkillDefinition",
        agent_id: str,
        organization_id: Optional[str] = None
    ) -> bool:
        """
        判断 Skill 对 Agent 是否可见
        
        规则（按优先级）：
        1. 如果 skill.enabled == False → 不可见
        2. public → 可见
        3. org → organization_id 必须匹配
        4. private → agent_id 必须在 allowed_agents
        
        Args:
            skill: Skill 定义
            agent_id: Agent ID
            organization_id: 组织 ID（可选）
            
        Returns:
            是否可见
        """
        # 规则 1: 未启用的 Skill 不可见
        if not skill.enabled:
            return False
        
        # 规则 2: public 可见性
        if skill.visibility == "public":
            return True
        
        # 规则 3: org 可见性
        if skill.visibility == "org":
            if organization_id is None:
                # 未提供组织 ID，无法验证
                logger.debug(f"[ScopeResolver] Org visibility check failed: no org_id provided for skill {skill.id}")
                return False
            
            if skill.organization_id == organization_id:
                return True
            else:
                logger.debug(f"[ScopeResolver] Org mismatch: skill_org={skill.organization_id}, agent_org={organization_id}")
                return False
        
        # 规则 4: private 可见性
        if skill.visibility == "private":
            if skill.allowed_agents is None:
                # 未设置允许列表，默认不可见
                logger.debug(f"[ScopeResolver] Private skill {skill.id} has no allowed_agents")
                return False
            
            if agent_id in skill.allowed_agents:
                return True
            else:
                logger.debug(f"[ScopeResolver] Agent {agent_id} not in allowed list for skill {skill.id}")
                return False
        
        # 未知可见性类型，默认不可见
        logger.warning(f"[ScopeResolver] Unknown visibility type '{skill.visibility}' for skill {skill.id}")
        return False
    
    def filter_visible(
        self,
        skills: List["SkillDefinition"],
        agent_id: str,
        organization_id: Optional[str] = None
    ) -> List["SkillDefinition"]:
        """
        批量过滤可见的 Skills
        
        Args:
            skills: Skill 列表
            agent_id: Agent ID
            organization_id: 组织 ID（可选）
            
        Returns:
            可见的 Skill 列表
        """
        visible = []
        for skill in skills:
            if self.is_visible(skill, agent_id, organization_id):
                visible.append(skill)
        
        logger.debug(f"[ScopeResolver] Filtered {len(visible)}/{len(skills)} skills visible to agent {agent_id}")
        return visible


class SkillPermissionChecker:
    """
    Skill 权限检查器（未来扩展）
    
    预留接口，用于更细粒度的权限控制：
    - 执行权限（execute）
    - 修改权限（modify）
    - 删除权限（delete）
    """
    
    def can_execute(
        self,
        skill: "SkillDefinition",
        agent_id: str,
        organization_id: Optional[str] = None
    ) -> bool:
        """检查是否有执行权限（目前等同于可见性）"""
        resolver = SkillScopeResolver()
        return resolver.is_visible(skill, agent_id, organization_id)
    
    def can_modify(
        self,
        skill: "SkillDefinition",
        agent_id: str,
        organization_id: Optional[str] = None
    ) -> bool:
        """
        检查是否有修改权限
        
        规则：
        - private: 仅 allowed_agents 中的第一个（创建者）可修改
        - org: 同组织成员可修改
        - public: 系统管理员可修改（未来实现）
        """
        if not skill.enabled:
            return False
        
        if skill.visibility == "private":
            # 假设 allowed_agents 第一个是创建者
            if skill.allowed_agents and agent_id == skill.allowed_agents[0]:
                return True
            return False
        
        if skill.visibility == "org":
            if organization_id and skill.organization_id == organization_id:
                return True
            return False
        
        # public: 暂时不允许修改（未来可扩展为管理员权限）
        return False
