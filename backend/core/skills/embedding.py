"""
Skill Embedding 模块

提供向量嵌入服务，支持语义检索
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np
from log import logger


class EmbeddingService(ABC):
    """
    Embedding 服务抽象接口
    
    设计原则：
    - 可替换实现（本地模型 / API / Mock）
    - 统一接口，隐藏实现细节
    """
    
    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """
        将文本转换为向量
        
        Args:
            text: 输入文本
            
        Returns:
            向量表示（归一化）
        """
        pass
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入（默认逐个处理，子类可优化）"""
        return [self.embed(text) for text in texts]


class MockEmbeddingService(EmbeddingService):
    """
    Mock Embedding 服务
    
    用于开发和测试阶段，基于哈希生成确定性向量
    """
    
    def __init__(self, dimension: int = 384):
        self.dimension = dimension
    
    def embed(self, text: str) -> List[float]:
        """
        基于文本哈希生成确定性向量
        
        特点：
        - 相同文本总是产生相同向量
        - 无需外部依赖
        - 适合测试
        """
        # 使用哈希生成种子
        import hashlib
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
        np.random.seed(seed)
        
        # 生成随机向量并归一化
        vector = np.random.randn(self.dimension).astype(np.float32)
        vector = vector / np.linalg.norm(vector)
        
        return vector.tolist()


class LocalEmbeddingService(EmbeddingService):
    """
    本地 Embedding 服务
    
    使用 ONNX 模型在本地生成向量
    （未来实现，目前 fallback 到 Mock）
    """
    
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self._model = None
        self._fallback = MockEmbeddingService()
    
    def embed(self, text: str) -> List[float]:
        """使用本地模型或 fallback"""
        if self._model is None:
            # 暂未加载真实模型，使用 fallback
            logger.debug("[LocalEmbeddingService] Using fallback mock embedding")
            return self._fallback.embed(text)
        
        # TODO: 实现真实模型推理
        # return self._model.encode(text)
        return self._fallback.embed(text)


def get_embedding_service() -> EmbeddingService:
    """
    获取 Embedding 服务实例
    
    工厂函数，可根据配置返回不同实现
    """
    # 目前使用 Mock，未来可配置化
    return MockEmbeddingService(dimension=384)
