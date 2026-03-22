"""
Skill v2 模块：可被 Agent 调用的能力单元，支持版本管理和统一执行契约。
"""
from core.skills.models import Skill, SkillType, SkillDefinition
from core.skills.store import SkillStore
from core.skills.service import get_skill_store, create_skill, list_skills, get_skill, update_skill, delete_skill
from core.skills.executor import SkillExecutor
from core.skills.registry import SkillRegistry
from core.skills.contract import SkillExecutionRequest, SkillExecutionResponse

# 新增：Discovery & Scope 模块
from core.skills.discovery import SkillDiscoveryEngine, get_discovery_engine, SkillVectorIndex
from core.skills.scope import SkillScopeResolver, SkillPermissionChecker
from core.skills.embedding import EmbeddingService, MockEmbeddingService, LocalEmbeddingService, get_embedding_service

__all__ = [
    # v1 兼容
    "Skill",
    "SkillType",
    
    # v2 核心
    "SkillDefinition",
    "SkillExecutionRequest",
    "SkillExecutionResponse",
    
    # Store & Service
    "SkillStore",
    "get_skill_store",
    "create_skill",
    "list_skills",
    "get_skill",
    "update_skill",
    "delete_skill",
    
    # Executor & Registry
    "SkillExecutor",
    "SkillRegistry",
    
    # Discovery & Semantic Search（新增）
    "SkillDiscoveryEngine",
    "get_discovery_engine",
    "SkillVectorIndex",
    
    # Scope & Permission（新增）
    "SkillScopeResolver",
    "SkillPermissionChecker",
    
    # Embedding（新增）
    "EmbeddingService",
    "MockEmbeddingService",
    "LocalEmbeddingService",
    "get_embedding_service",
]
