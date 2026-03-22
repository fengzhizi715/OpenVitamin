"""
Embedding Provider（占位）

MVP 阶段先不强依赖任何第三方 embedding 模型/服务。
后续接入 sqlite-vss 时，可在这里实现：
- 本地 embedding（如 sentence-transformers）
- 或通过 OpenAI 兼容后端的 /embeddings
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class EmbeddingConfig:
    dim: int = 256


class EmbeddingProvider:
    """
    轻量级 embedding（hashing trick）实现，方便后续替换。
    注意：这不是语义 embedding，只用于 MVP 的可扩展接口占位。
    """

    def __init__(self, config: EmbeddingConfig = EmbeddingConfig()):
        self.config = config

    def embed(self, text: str) -> List[float]:
        dim = self.config.dim
        vec = [0.0] * dim
        if not text:
            return vec
        # 简单哈希计数（字符级），避免外部依赖
        for ch in text:
            idx = (ord(ch) * 1315423911) % dim
            vec[idx] += 1.0
        # 归一化
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

