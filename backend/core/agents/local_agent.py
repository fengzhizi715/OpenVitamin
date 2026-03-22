from typing import AsyncIterator
from core.agents.base import ModelAgent
from core.types import ChatCompletionRequest
from core.models.registry import get_model_registry
from core.runtimes.factory import get_runtime_factory

class LocalRuntimeAgent(ModelAgent):
    """
    本地运行时代理
    专门处理 local:* 协议的模型请求，直接对接 ModelRuntime
    """
    def __init__(self):
        self.registry = get_model_registry()
        self.runtime_factory = get_runtime_factory()

    async def chat(self, req: ChatCompletionRequest) -> str:
        # 获取模型描述符
        descriptor = self.registry.get_model(req.model)
        if not descriptor:
            raise ValueError(f"Local model {req.model} not found")
            
        # 获取对应的运行时 (通常是 llama.cpp)
        runtime = self.runtime_factory.get_runtime(descriptor.runtime)
        
        # 调用运行时
        return await runtime.chat(descriptor, req)

    async def stream_chat(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        # 获取模型描述符
        descriptor = self.registry.get_model(req.model)
        if not descriptor:
            raise ValueError(f"Local model {req.model} not found")
            
        # 获取对应的运行时
        runtime = self.runtime_factory.get_runtime(descriptor.runtime)
        
        # 调用流式接口
        async for token in runtime.stream_chat(descriptor, req):
            yield token

    def model_info(self) -> dict:
        return {
            "backend": "local_runtime",
            "supports_stream": True,
            "supports_functions": False
        }
