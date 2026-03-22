"""
Agent 定义与注册中心 (ORM 版本)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.dialects.sqlite import insert

from core.data.base import db_session
from core.data.models.agent import Agent as AgentORM
from log import logger


class AgentDefinition(BaseModel):
    agent_id: str
    name: str
    description: str = ""

    model_id: str
    system_prompt: str = ""

    # v1.5: Agent 只可见 Skill；enabled_skills 为 Skill id 列表
    enabled_skills: List[str] = Field(default_factory=list)
    # 兼容旧配置：若存储中无 enabled_skills 则从 tool_ids 映射为 builtin_<tool_id>
    tool_ids: List[str] = Field(default_factory=list)
    rag_ids: List[str] = Field(default_factory=list)

    max_steps: int = 5
    temperature: float = 0.7

    # Model parameters (optional, will be passed through to LLM)
    model_params: Dict[str, Any] = Field(default_factory=dict)

    slug: Optional[str] = None  # URL-friendly identifier

    # V2: Execution mode - "legacy" or "plan_based"
    # 默认 "legacy" 保持向后兼容
    execution_mode: Optional[str] = "legacy"
    # V2.5: Agent 级 Execution Kernel 开关（None 表示跟随全局）
    use_execution_kernel: Optional[bool] = None
    
    # V2.2: RePlan 配置
    max_replan_count: int = 3  # 最大重规划次数
    on_failure_strategy: str = "stop"  # 失败策略：stop / continue / replan
    replan_prompt: str = ""  # 自定义重规划提示词
        
    # V2.3: Plan Contract 配置
    plan_contract_enabled: bool = False  # 是否启用 Plan Contract
    plan_contract_strict: bool = False  # 严格模式：发现无效 Contract 时直接失败
    plan_contract_sources: List[str] = Field(
        default_factory=lambda: ["replan_contract_plan", "plan_contract", "followup_plan_contract"],
        description="Plan Contract sources priority order"
    )

    # Optional runtime info (not persisted)
    runtime_info: Optional[Dict[str, Any]] = None


class AgentRegistry:
    """智能体注册中心（使用 SQLAlchemy ORM）"""

    def create_agent(self, agent: AgentDefinition) -> bool:
        """创建 Agent"""
        try:
            definition_json = agent.model_dump_json()
            with db_session() as db:
                db.add(
                    AgentORM(
                        agent_id=agent.agent_id,
                        name=agent.name,
                        description=agent.description,
                        definition_json=definition_json,
                    )
                )
            return True
        except Exception as e:
            logger.error(f"[AgentRegistry] create_agent failed: {e}")
            return False

    def _normalize_definition_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """兼容旧数据：若无 enabled_skills 但有 tool_ids，则映射为 builtin_<tool_id>"""
        if not data.get("enabled_skills") and data.get("tool_ids"):
            data = {**data, "enabled_skills": [f"builtin_{t}" for t in data["tool_ids"]]}
        # V2: 兼容无 execution_mode 的旧数据
        if "execution_mode" not in data:
            data["execution_mode"] = "legacy"
        # V2.5: 兼容无 use_execution_kernel 的旧数据（跟随全局）
        if "use_execution_kernel" not in data:
            data["use_execution_kernel"] = None
        # V2.2: 兼容无 RePlan 字段的旧数据
        if "max_replan_count" not in data:
            data["max_replan_count"] = 3
        if "on_failure_strategy" not in data:
            data["on_failure_strategy"] = "stop"
        if "replan_prompt" not in data:
            data["replan_prompt"] = ""
        if "plan_contract_enabled" not in data:
            data["plan_contract_enabled"] = False
        if "plan_contract_strict" not in data:
            data["plan_contract_strict"] = False
        if "plan_contract_sources" not in data or not isinstance(data.get("plan_contract_sources"), list):
            data["plan_contract_sources"] = ["replan_contract_plan", "plan_contract", "followup_plan_contract"]
        # 已移除 auto_detect_project，从旧数据中丢弃避免写入
        data.pop("auto_detect_project", None)
        return data

    def get_agent(self, agent_id: str) -> Optional[AgentDefinition]:
        """获取 Agent"""
        try:
            with db_session() as db:
                agent_orm = db.query(AgentORM).filter(AgentORM.agent_id == agent_id).first()
                if agent_orm:
                    data = json.loads(agent_orm.definition_json)
                    data = self._normalize_definition_data(data)
                    return AgentDefinition(**data)
        except Exception as e:
            logger.error(f"[AgentRegistry] get_agent failed: {e}")
        return None

    def list_agents(self) -> List[AgentDefinition]:
        """列出所有 Agent"""
        agents = []
        try:
            with db_session() as db:
                rows = db.query(AgentORM).order_by(AgentORM.created_at.desc()).all()
                for row in rows:
                    data = json.loads(row.definition_json)
                    data = self._normalize_definition_data(data)
                    agents.append(AgentDefinition(**data))
        except Exception as e:
            logger.error(f"[AgentRegistry] list_agents failed: {e}")
        return agents

    def update_agent(self, agent: AgentDefinition) -> bool:
        """更新 Agent"""
        try:
            definition_json = agent.model_dump_json()
            with db_session() as db:
                agent_orm = db.query(AgentORM).filter(AgentORM.agent_id == agent.agent_id).first()
                if agent_orm:
                    agent_orm.name = agent.name
                    agent_orm.description = agent.description
                    agent_orm.definition_json = definition_json
                    return True
        except Exception as e:
            logger.error(f"[AgentRegistry] update_agent failed: {e}")
        return False

    def delete_agent(self, agent_id: str) -> bool:
        """删除 Agent"""
        try:
            with db_session() as db:
                agent_orm = db.query(AgentORM).filter(AgentORM.agent_id == agent_id).first()
                if agent_orm:
                    db.delete(agent_orm)
                    return True
        except Exception as e:
            logger.error(f"[AgentRegistry] delete_agent failed: {e}")
        return False


_registry: Optional[AgentRegistry] = None


def get_agent_registry() -> AgentRegistry:
    """获取 Agent 注册中心单例"""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
