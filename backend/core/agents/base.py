"""
模型代理抽象基类
所有推理后端（Ollama、OpenAI、vLLM等）都必须实现此接口
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator
from core.types import ChatCompletionRequest


class ModelAgent(ABC):
    """
    统一的模型代理接口
    
    所有具体的模型后端实现都应继承此类并实现所有抽象方法。
    注意：stream_chat 只返回 token 字符串，SSE/JSON 包装由网关负责。
    """
    
    @abstractmethod
    async def chat(self, req: ChatCompletionRequest) -> str:
        """
        非流式聊天完成
        
        Args:
            req: 聊天完成请求
        
        Returns:
            模型生成的完整文本响应
        """
        pass
    
    @abstractmethod
    async def stream_chat(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        """
        流式聊天完成
        
        Args:
            req: 聊天完成请求
        
        Yields:
            逐个生成的 token（纯文本字符串）
            注意：不包含 SSE 包装或 JSON，由网关统一处理
        """
        pass
    
    @abstractmethod
    def model_info(self) -> dict:
        """
        获取模型信息
        
        Returns:
            模型能力描述字典，示例：
            {
                "backend": "ollama",
                "supports_stream": True,
                "supports_functions": False
            }
        """
        pass
