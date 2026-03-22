"""
Node Cache
节点级缓存，基于 node_id + input hash
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import hashlib
import json
import logging

from execution_kernel.persistence.repositories import NodeCacheRepository
from execution_kernel.models.node_models import NodeCacheEntry
from execution_kernel.models.graph_definition import NodeDefinition


logger = logging.getLogger(__name__)


class NodeCache:
    """
    节点级缓存
    
    特性：
    - 基于 node_id + input hash
    - TTL 控制
    - 命中则跳过执行
    - 不允许 graph 级缓存
    """
    
    def __init__(self, repository: NodeCacheRepository, default_ttl_seconds: int = 3600):
        self.repository = repository
        self.default_ttl_seconds = default_ttl_seconds
    
    def _compute_hash(self, node_id: str, input_data: Dict[str, Any]) -> str:
        """计算输入数据哈希"""
        data = {"node_id": node_id, "input": input_data}
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, default=str).encode()
        ).hexdigest()
    
    async def get(
        self, 
        node_def: NodeDefinition, 
        input_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        获取缓存
        
        Returns:
            缓存的输出数据，如果未命中返回 None
        """
        if not node_def.cacheable:
            return None
        
        input_hash = self._compute_hash(node_def.id, input_data)
        
        cache_entry = await self.repository.get(node_def.id, input_hash)
        
        if cache_entry is None:
            logger.debug(f"Cache miss: {node_def.id}")
            return None
        
        # 检查过期
        if cache_entry.expires_at and cache_entry.expires_at < datetime.utcnow():
            logger.debug(f"Cache expired: {node_def.id}")
            return None
        
        logger.info(f"Cache hit: {node_def.id}")
        return cache_entry.output_data
    
    async def set(
        self,
        node_def: NodeDefinition,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        ttl_seconds: int = None,
    ) -> None:
        """设置缓存"""
        if not node_def.cacheable:
            return
        
        input_hash = self._compute_hash(node_def.id, input_data)
        ttl = ttl_seconds or self.default_ttl_seconds
        
        entry = NodeCacheEntry(
            node_id=node_def.id,
            input_hash=input_hash,
            output_data=output_data,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
        )
        
        await self.repository.save(entry)
        logger.info(f"Cache set: {node_def.id}, TTL={ttl}s")
    
    async def clear_expired(self) -> int:
        """清理过期缓存"""
        count = await self.repository.delete_expired()
        if count > 0:
            logger.info(f"Cleared {count} expired cache entries")
        return count
