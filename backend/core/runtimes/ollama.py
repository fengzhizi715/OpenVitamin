import httpx
import json
from typing import AsyncIterator
from log import logger
from core.runtimes.base import ModelRuntime
from core.types import ChatCompletionRequest
from core.models.descriptor import ModelDescriptor

class OllamaRuntime(ModelRuntime):
    """
    Ollama 运行时实现
    """
    async def chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> str:
        payload = {
            "model": descriptor.provider_model_id,
            "messages": [m.model_dump() for m in req.messages],
            "stream": False,
            "options": {
                "temperature": req.temperature,
                "top_p": req.top_p,
                "num_predict": req.max_tokens,
            }
        }
        
        base_url = descriptor.base_url or "http://localhost:11434"
        async with httpx.AsyncClient(timeout=None) as client:
            resp = await client.post(
                f"{base_url}/api/chat",
                json=payload
            )
            if resp.status_code == 404:
                error_msg = resp.json().get("error", "Model not found")
                raise ValueError(f"Ollama error: {error_msg}. Please ensure model is pulled.")
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]

    async def stream_chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> AsyncIterator[str]:
        payload = {
            "model": descriptor.provider_model_id,
            "messages": [m.model_dump() for m in req.messages],
            "stream": True,
            "options": {
                "temperature": req.temperature,
                "top_p": req.top_p,
                "num_predict": req.max_tokens,
            }
        }
        
        base_url = descriptor.base_url or "http://localhost:11434"
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{base_url}/api/chat",
                json=payload
            ) as response:
                if response.status_code == 404:
                    await response.aread()
                    error_msg = response.json().get("error", "Model not found")
                    raise ValueError(f"Ollama error: {error_msg}. Please ensure model is pulled.")
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            yield data["message"]["content"]
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

    async def is_loaded(self, descriptor: ModelDescriptor) -> bool:
        """检查 Ollama 模型是否已加载"""
        base_url = descriptor.base_url or "http://localhost:11434"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{base_url}/api/ps")
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("models", [])
                    # Ollama 的 ps 结果中 name 可能包含 :latest
                    target = descriptor.provider_model_id
                    for m in models:
                        if m.get("name") == target or m.get("model") == target:
                            return True
        except Exception:
            pass
        return False
