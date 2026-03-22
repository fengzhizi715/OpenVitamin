"""
Ollama 模型代理实现
"""
import httpx
from typing import AsyncIterator
import json
from log import logger

from config.settings import settings
from core.agents.base import ModelAgent
from core.types import ChatCompletionRequest


class OllamaAgent(ModelAgent):
    """
    Ollama 本地推理引擎适配
    """
    
    def __init__(self, base_url: str | None = None):
        """
        初始化 Ollama 代理
        
        Args:
            base_url: Ollama 服务地址，默认从 settings 读取
        """
        self.base_url = base_url or settings.ollama_base_url
    
    async def _resolve_model_name(self, requested_model: str) -> str:
        """
        解析真实的 Ollama 模型名称
        1. 如果请求的是特定标签 (ollama:xxx)，提取 xxx
        2. 如果请求的是通用 'ollama' 且 settings 有默认值，使用默认值
        3. 如果请求的是通用 'ollama' 且 settings 为空，自动获取本地第一个模型
        """
        if requested_model.startswith("ollama:"):
            return requested_model.replace("ollama:", "", 1)
        
        if requested_model == "ollama":
            # 优先使用配置的默认模型
            if settings.ollama_default_model:
                return settings.ollama_default_model
            
            # 否则，尝试从本地发现
            local_models = await self.list_local_models()
            if local_models:
                # 提取 id 中的名称 (ollama:name -> name)
                first_model = local_models[0]["id"].replace("ollama:", "", 1)
                logger.info(f"[OllamaAgent] No default model configured, auto-selected: {first_model}")
                return first_model
            
            raise ValueError("No Ollama models found locally. Please run 'ollama pull' first.")
            
        return requested_model

    async def chat(self, req: ChatCompletionRequest) -> str:
        """
        调用 Ollama 生成完整响应
        """
        model_name = await self._resolve_model_name(req.model)

        payload = {
            "model": model_name,
            "messages": [m.model_dump() for m in req.messages],
            "stream": False,
            "options": {
                "temperature": req.temperature,
                "top_p": req.top_p,
            }
        }
        
        async with httpx.AsyncClient(timeout=None) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload
            )
            if resp.status_code == 404:
                error_msg = resp.json().get("error", "Model not found")
                raise ValueError(f"Ollama error: {error_msg}. Please ensure model '{model_name}' is pulled.")
            resp.raise_for_status()
            data = resp.json()
            msg = data["message"]
            # 优先使用 content,如果为空则尝试 thinking (某些模型如 glm-4.6:cloud)
            content = msg.get("content", "")
            if not content and "thinking" in msg:
                content = msg.get("thinking", "")
            return content
    
    async def stream_chat(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        """
        流式调用 Ollama
        逐个生成 token
        """
        model_name = await self._resolve_model_name(req.model)

        payload = {
            "model": model_name,
            "messages": [m.model_dump() for m in req.messages],
            "stream": True,
            "options": {
                "temperature": req.temperature,
                "top_p": req.top_p,
            }
        }
        
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload
            ) as response:
                if response.status_code == 404:
                    # 对于流式请求，我们需要读取 body 来获取错误信息
                    await response.aread()
                    error_msg = response.json().get("error", "Model not found")
                    raise ValueError(f"Ollama error: {error_msg}. Please ensure model '{model_name}' is pulled.")
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if "message" in data:
                            msg = data["message"]
                            # 优先使用 content,如果为空则尝试 thinking (某些模型如 glm-4.6:cloud)
                            content = msg.get("content", "")
                            if not content and "thinking" in msg:
                                content = msg.get("thinking", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue
    
    async def list_local_models(self) -> list[dict]:
        """
        从 Ollama 服务获取可用的本地模型列表
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                
                models = []
                for m in data.get("models", []):
                    raw_name = m["name"]
                    models.append({
                        "id": f"ollama:{raw_name}",
                        "name": raw_name,
                        "display_name": f"{raw_name} (Ollama)",
                        "backend": "ollama",
                        "supports_stream": True,
                        "description": f"Ollama local model: {raw_name}"
                    })
                return models
        except Exception as e:
            logger.error(f"Failed to list Ollama models: {e}")
            return []

    def model_info(self) -> dict:
        """获取模型信息"""
        return {
            "backend": "ollama",
            "supports_stream": True,
            "supports_functions": False
        }
