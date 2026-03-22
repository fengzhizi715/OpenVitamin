"""
Skill v2 models.
Skill 是可被 Agent 调用的能力单元，与具体 LLM 无关。
v2 支持版本管理、Schema 定义和统一执行契约。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

SkillType = Literal["prompt", "tool", "composite", "workflow"]
SkillVisibility = Literal["public", "org", "private"]


@dataclass
class SkillDefinition:
    """
    Skill 定义（平台级能力资产）
    
    设计原则：
    - Definition 不包含执行逻辑
    - 版本不可覆盖（id + version 唯一）
    - Schema 必须明确
    """
    id: str
    name: str
    version: str  # 语义化版本：major.minor.patch
    description: str
    input_schema: Dict[str, Any]  # JSON Schema (required)
    output_schema: Dict[str, Any]  # JSON Schema (required)
    
    # Skill 类型和执行定义
    type: SkillType = "prompt"  # prompt | tool | composite | workflow
    definition: Dict[str, Any] = field(default_factory=dict)  # prompt_template, tool_name, etc.
    
    # 分类和标签
    category: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    
    # 可见性和权限（为多 Agent/多组织预备）
    visibility: SkillVisibility = "public"  # public | org | private
    allowed_agents: Optional[List[str]] = None  # private 可见性时使用
    organization_id: Optional[str] = None  # org 可见性时使用
    
    # 向量嵌入（为语义检索预备）
    embedding: Optional[List[float]] = None
    
    # 状态和元数据
    enabled: bool = True
    composable: bool = True  # 是否可组合（为未来 Graph 引擎预留）
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """验证字段合法性"""
        if not self.version:
            raise ValueError("version is required")
        if not self.input_schema:
            raise ValueError("input_schema is required")
        if not self.output_schema:
            raise ValueError("output_schema is required")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "type": self.type,
            "definition": self.definition,
            "category": self.category,
            "tags": self.tags,
            "visibility": self.visibility,
            "allowed_agents": self.allowed_agents,
            "organization_id": self.organization_id,
            "embedding": self.embedding,  # 注意：embedding 通常很大，API 返回时可选择排除
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "enabled": self.enabled,
            "composable": self.composable,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillDefinition":
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            version=data["version"],
            description=data.get("description", ""),
            type=data.get("type", "prompt"),
            definition=data.get("definition", {}),
            category=data.get("category", []),
            tags=data.get("tags", []),
            visibility=data.get("visibility", "public"),
            allowed_agents=data.get("allowed_agents"),
            organization_id=data.get("organization_id"),
            embedding=data.get("embedding"),
            input_schema=data.get("input_schema", {}),
            output_schema=data.get("output_schema", {}),
            enabled=data.get("enabled", True),
            composable=data.get("composable", True),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
        )


# ========== v1 兼容层 ==========
# 保留原有 Skill 模型，用于向后兼容

@dataclass
class Skill:
    """Skill v1 (向后兼容)"""
    
    id: str
    name: str
    description: str
    category: str
    type: SkillType
    definition: Dict[str, Any]  # prompt_template and/or tool_name, tool_args_mapping
    input_schema: Dict[str, Any]  # JSON Schema
    enabled: bool
    created_at: datetime
    updated_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "type": self.type,
            "definition": self.definition,
            "input_schema": self.input_schema,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def to_v2(self) -> SkillDefinition:
        """转换为 v2 格式（兼容层）"""
        return SkillDefinition(
            id=self.id,
            name=self.name,
            version="1.0.0",  # v1 默认为 1.0.0
            description=self.description,
            type=self.type,
            definition=self.definition,
            category=[self.category] if self.category else [],
            tags=[],
            input_schema=self.input_schema,
            output_schema={"type": "object"},  # v1 无输出 schema，默认 object
            enabled=self.enabled,
            composable=True,
            visibility="public",
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
