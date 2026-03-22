from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any, List
from core.types import ChatCompletionRequest
from core.models.descriptor import ModelDescriptor

class ModelRuntime(ABC):
    """
    运行时适配层基类
    负责处理不同推理后端的底层通信差异
    """
    @abstractmethod
    async def chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> str:
        """非流式对话"""
        pass

    @abstractmethod
    async def stream_chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> AsyncIterator[str]:
        """流式对话"""
        pass

    async def load(self, descriptor: ModelDescriptor) -> bool:
        """预加载模型"""
        return True

    async def unload(self, descriptor: ModelDescriptor) -> bool:
        """卸载模型"""
        return True

    async def is_loaded(self, descriptor: ModelDescriptor) -> bool:
        """检查模型是否已加载"""
        return False


class EmbeddingRuntime(ABC):
    """
    Embedding Runtime 基类
    负责将文本转换为 embedding 向量
    """
    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        将文本列表转换为 embedding 向量列表
        
        Args:
            texts: 文本列表
            
        Returns:
            embedding 向量列表，每个向量是一个 float 列表
        """
        pass

    def health(self) -> Dict[str, Any]:
        """返回运行时健康状态"""
        return {"status": "ok"}
