"""
模型路由器
V1 简单字符串路由，根据模型 ID 前缀自动选择对应的 Agent
"""
from typing import Optional
from core.agents.unified_agent import UnifiedModelAgent
from core.agents.base import ModelAgent
from core.models.registry import get_model_registry

class ModelRouter:
    """
    模型路由器 (重构后)
    
    现在的职责：
    1. 提供统一的消息处理入口
    2. 提供可用的模型列表
    """
    
    def __init__(self):
        """初始化路由器"""
        self._unified_agent = UnifiedModelAgent()
        self.registry = get_model_registry()
    
    def get_agent(self, model_id: str) -> ModelAgent:
        """
        获取代理。重构后统一返回 UnifiedModelAgent，
        它内部会根据 model_id 进行分发。
        """
        return self._unified_agent

    async def list_models(self, model_type: Optional[str] = None) -> list:
        """列出所有已注册的模型元信息"""
        models = []
        descriptors = self.registry.list_models(model_type=model_type)
        
        for d in descriptors:
            supports_stream = d.model_type != "image_generation"
            models.append({
                "id": d.id,
                "name": d.name,
                "model_type": d.model_type,
                "display_name": f"{d.name} ({d.provider.capitalize()})",
                "backend": d.provider,
                "supports_stream": supports_stream,
                "description": d.description,
                "device": d.device or "local",
                "quantization": d.quantization,
                "size": d.size,
                "format": d.format,
                "source": d.source,
                "base_url": d.base_url,
                "metadata": d.metadata,
                "context_length": d.context_length
            })
            
        return models


# 全局单例
_router = None


def get_router() -> ModelRouter:
    """获取全局模型路由器单例"""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
