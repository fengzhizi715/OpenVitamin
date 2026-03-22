"""
Skill Discovery 模块

提供语义检索和智能发现能力
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
from log import logger

from core.skills.models import SkillDefinition
from core.skills.registry import SkillRegistry
from core.skills.embedding import EmbeddingService, get_embedding_service
from core.skills.scope import SkillScopeResolver


class SkillVectorIndex:
    """
    Skill 向量索引（内存实现）
    
    职责：
    - 管理 Skill 的向量表示
    - 提供相似度搜索
    
    设计原则：
    - 不依赖外部向量数据库（第一阶段）
    - 余弦相似度
    - 内存存储，重启后重建
    """
    
    def __init__(self):
        # skill_id -> (version, vector)
        self._vectors: Dict[str, Tuple[str, List[float]]] = {}
        self._dimension: Optional[int] = None
    
    def add(self, skill: SkillDefinition) -> None:
        """
        添加 Skill 到索引
        
        Args:
            skill: Skill 定义（必须包含 embedding）
        """
        if skill.embedding is None:
            logger.debug(f"[SkillVectorIndex] Skill {skill.id} has no embedding, skipping")
            return
        
        # 验证维度一致性
        if self._dimension is None:
            self._dimension = len(skill.embedding)
        elif len(skill.embedding) != self._dimension:
            logger.warning(
                f"[SkillVectorIndex] Dimension mismatch for skill {skill.id}: "
                f"expected {self._dimension}, got {len(skill.embedding)}"
            )
            return
        
        key = f"{skill.id}@{skill.version}"
        self._vectors[key] = (skill.version, skill.embedding)
        logger.debug(f"[SkillVectorIndex] Added skill {key}")
    
    def remove(self, skill_id: str, version: Optional[str] = None) -> None:
        """
        从索引中移除 Skill
        
        Args:
            skill_id: Skill ID
            version: 版本号（不指定则移除所有版本）
        """
        if version:
            key = f"{skill_id}@{version}"
            self._vectors.pop(key, None)
            logger.debug(f"[SkillVectorIndex] Removed skill {key}")
        else:
            # 移除所有版本
            keys_to_remove = [k for k in self._vectors.keys() if k.startswith(f"{skill_id}@")]
            for key in keys_to_remove:
                self._vectors.pop(key, None)
            logger.debug(f"[SkillVectorIndex] Removed {len(keys_to_remove)} versions of skill {skill_id}")
    
    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        skill_filter: Optional[List[str]] = None
    ) -> List[Tuple[str, str, float]]:
        """
        向量相似度搜索
        
        Args:
            query_vector: 查询向量
            top_k: 返回结果数量
            skill_filter: 可选的 Skill ID 过滤列表
            
        Returns:
            列表，每项为 (skill_id, version, similarity_score)
        """
        if not self._vectors:
            return []
        
        if self._dimension and len(query_vector) != self._dimension:
            logger.warning(
                f"[SkillVectorIndex] Query dimension mismatch: "
                f"expected {self._dimension}, got {len(query_vector)}"
            )
            return []
        
        # 计算余弦相似度
        query_norm = np.linalg.norm(query_vector)
        if query_norm == 0:
            return []
        
        query_unit = np.array(query_vector) / query_norm
        
        similarities = []
        for key, (version, vector) in self._vectors.items():
            skill_id = key.rsplit("@", 1)[0]
            
            # 应用过滤
            if skill_filter and skill_id not in skill_filter:
                continue
            
            # 计算余弦相似度
            vector_norm = np.linalg.norm(vector)
            if vector_norm == 0:
                continue
            
            vector_unit = np.array(vector) / vector_norm
            similarity = float(np.dot(query_unit, vector_unit))
            
            similarities.append((skill_id, version, similarity))
        
        # 按相似度排序，返回 top_k
        similarities.sort(key=lambda x: x[2], reverse=True)
        return similarities[:top_k]
    
    def clear(self) -> None:
        """清空索引"""
        self._vectors.clear()
        self._dimension = None
        logger.debug("[SkillVectorIndex] Cleared")


class SkillDiscoveryEngine:
    """
    Skill 发现引擎
    
    职责：
    - 语义检索（基于向量相似度）
    - 结构化过滤（tag/category/visibility）
    - 权限过滤（agent 可见性）
    - Hybrid 排序（语义 + 标签匹配）
    
    设计原则：
    - 与 Registry 分离（Registry 不负责检索）
    - 与 Scope 配合（权限控制）
    - 可扩展（未来支持权重学习）
    """
    
    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        scope_resolver: Optional[SkillScopeResolver] = None
    ):
        self._embedding_service = embedding_service or get_embedding_service()
        self._scope_resolver = scope_resolver or SkillScopeResolver()
        self._vector_index = SkillVectorIndex()
        self._registry: Optional[SkillRegistry] = None
    
    def bind_registry(self, registry: SkillRegistry) -> None:
        """
        绑定 Registry，用于获取所有 Skills
        
        注意：Discovery 不拥有 Registry，只是使用它
        """
        self._registry = registry
    
    def build_index(self) -> int:
        """
        从 Registry 构建向量索引
        
        返回:
            索引的 Skill 数量
        """
        if self._registry is None:
            raise RuntimeError("Registry not bound. Call bind_registry() first.")
        
        self._vector_index.clear()
        
        # 获取所有 Skills 并生成 embedding
        all_skills = self._registry.list_all(enabled_only=False)
        indexed_count = 0
        
        for skill in all_skills:
            # 如果没有 embedding，生成一个
            if skill.embedding is None:
                skill.embedding = self._generate_embedding(skill)
            
            self._vector_index.add(skill)
            indexed_count += 1
        
        logger.info(f"[SkillDiscoveryEngine] Built index with {indexed_count} skills")
        return indexed_count
    
    def _generate_embedding(self, skill: SkillDefinition) -> List[float]:
        """
        为 Skill 生成 embedding
        
        拼接字段：
        - name
        - description
        - tags
        - category
        """
        # 构建文本
        parts = [
            skill.name,
            skill.description,
        ]
        
        if skill.tags:
            parts.append("Tags: " + ", ".join(skill.tags))
        
        if skill.category:
            parts.append("Category: " + ", ".join(skill.category))
        
        text = "\n".join(parts)
        
        # 生成向量
        return self._embedding_service.embed(text)
    
    def search(
        self,
        query: str,
        agent_id: str,
        organization_id: Optional[str] = None,
        top_k: int = 5,
        filters: Optional[Dict] = None
    ) -> List[SkillDefinition]:
        """
        搜索 Skills
        
        流程：
        1. 结构化过滤（enabled / visibility / tags / category）
        2. 权限过滤（agent 可见）
        3. 向量相似度排序
        4. Hybrid 评分（语义 + 标签匹配）
        
        Args:
            query: 自然语言查询
            agent_id: Agent ID（用于权限检查）
            organization_id: 组织 ID（可选）
            top_k: 返回结果数量
            filters: 可选过滤器
                - tags: List[str] - 必须包含的标签
                - category: str - 类别过滤
                - visibility: str - 可见性过滤
                
        Returns:
            Skill 定义列表（按相关性排序）
        """
        if self._registry is None:
            raise RuntimeError("Registry not bound. Call bind_registry() first.")
        
        filters = filters or {}
        
        # 步骤 1: 获取候选 Skills（结构化过滤）
        candidates = self._apply_structural_filters(filters)
        logger.debug(f"[SkillDiscoveryEngine] Structural filter: {len(candidates)} candidates")
        
        # 步骤 2: 权限过滤
        candidates = self._scope_resolver.filter_visible(
            candidates, agent_id, organization_id
        )
        logger.debug(f"[SkillDiscoveryEngine] Scope filter: {len(candidates)} candidates")
        
        if not candidates:
            return []
        
        # 步骤 3: 向量相似度搜索
        query_vector = self._embedding_service.embed(query)
        candidate_ids = [s.id for s in candidates]
        
        vector_results = self._vector_index.search(
            query_vector,
            top_k=len(candidates) * 2,  # 多取一些用于后续排序
            skill_filter=candidate_ids
        )
        
        # 构建相似度映射
        similarity_map = {
            (skill_id, version): score
            for skill_id, version, score in vector_results
        }
        
        # 步骤 4: Hybrid 评分和排序
        scored_skills = []
        for skill in candidates:
            # 语义相似度
            semantic_score = similarity_map.get((skill.id, skill.version), 0.0)
            
            # 标签匹配分数
            tag_score = self._calculate_tag_match_score(skill, query, filters)
            
            # Hybrid 评分（可配置权重）
            # 默认：语义 70%，标签 30%
            final_score = semantic_score * 0.7 + tag_score * 0.3
            
            scored_skills.append((skill, final_score))
        
        # 按分数排序
        scored_skills.sort(key=lambda x: x[1], reverse=True)
        
        # 返回 top_k
        result = [skill for skill, _ in scored_skills[:top_k]]
        logger.info(f"[SkillDiscoveryEngine] Search returned {len(result)} skills for query: {query[:50]}...")
        
        return result
    
    def _apply_structural_filters(
        self,
        filters: Dict
    ) -> List[SkillDefinition]:
        """
        应用结构化过滤
        
        支持的过滤器：
        - tags: List[str] - 必须包含所有指定标签
        - category: str - 类别匹配
        - visibility: str - 可见性匹配
        - enabled_only: bool - 只返回启用的
        """
        if self._registry is None:
            return []
        
        # 从 Registry 获取所有 Skills
        enabled_only = filters.get("enabled_only", True)
        candidates = self._registry.list_all(enabled_only=enabled_only)
        
        filtered = []
        for skill in candidates:
            # 标签过滤
            if "tags" in filters:
                required_tags = set(filters["tags"])
                if not required_tags.issubset(set(skill.tags)):
                    continue
            
            # 类别过滤
            if "category" in filters:
                filter_category = filters["category"]
                if filter_category not in skill.category:
                    continue
            
            # 可见性过滤
            if "visibility" in filters:
                if skill.visibility != filters["visibility"]:
                    continue
            
            filtered.append(skill)
        
        return filtered
    
    def _calculate_tag_match_score(
        self,
        skill: SkillDefinition,
        query: str,
        filters: Dict
    ) -> float:
        """
        计算标签匹配分数
        
        简单实现：查询词出现在标签中的比例
        未来可扩展为更复杂的语义匹配
        """
        if not skill.tags:
            return 0.0
        
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        matched = 0
        for tag in skill.tags:
            tag_lower = tag.lower()
            # 完全匹配
            if tag_lower in query_lower:
                matched += 1
            # 部分匹配
            elif any(word in tag_lower for word in query_words):
                matched += 0.5
        
        return min(matched / len(skill.tags), 1.0) if skill.tags else 0.0
    
    def refresh_skill(self, skill_id: str) -> bool:
        """
        刷新单个 Skill 的索引
        
        用于 Skill 更新后重建索引
        
        Args:
            skill_id: Skill ID
            
        Returns:
            是否成功
        """
        if self._registry is None:
            return False
        
        skill = self._registry.get(skill_id)
        if skill is None:
            return False
        
        # 移除旧版本
        self._vector_index.remove(skill_id)
        
        # 重新生成 embedding 并添加
        skill.embedding = self._generate_embedding(skill)
        self._vector_index.add(skill)
        
        logger.debug(f"[SkillDiscoveryEngine] Refreshed skill {skill_id}")
        return True


# 全局 Discovery 引擎实例（单例模式）
_discovery_engine: Optional[SkillDiscoveryEngine] = None


def get_discovery_engine() -> SkillDiscoveryEngine:
    """获取 Discovery 引擎单例"""
    global _discovery_engine
    if _discovery_engine is None:
        _discovery_engine = SkillDiscoveryEngine()
    return _discovery_engine
