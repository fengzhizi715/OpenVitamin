"""
OpenAI 兼容协议模型代理基类
适用于 LM Studio, OpenAI, DashScope, DeepSeek 等支持 OpenAI 格式的后端
"""
import asyncio
import json
import httpx
from typing import AsyncIterator
from core.agents.base import ModelAgent
from core.types import ChatCompletionRequest
from log import logger

# 429/503 重试：最多次数、基础退避秒数
LLM_RETRY_MAX_ATTEMPTS = 3
LLM_RETRY_BASE_DELAY = 2.0


class OpenAICompatibleAgent(ModelAgent):
    """
    OpenAI 兼容协议适配器
    使用 httpx 直接进行调用，不依赖官方 SDK，便于处理各种兼容后端
    """

    def __init__(self, base_url: str, api_key: str = "sk-not-needed", backend_name: str = "openai-compatible"):
        """
        初始化兼容代理
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.backend_name = backend_name

    async def chat(self, req: ChatCompletionRequest) -> str:
        """非流式聊天完成"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": req.model,
            "messages": [m.model_dump() for m in req.messages],
            "temperature": req.temperature,
            "top_p": req.top_p,
            "max_tokens": req.max_tokens,
            "stream": False
        }
        
        payload = await self._pre_process_payload(payload)

        # 估算 Token (简单估算：字符数 / 4)
        total_chars = sum(len(m.get("content", "")) for m in payload["messages"])
        est_tokens = total_chars // 4
        logger.info(f"[{self.backend_name}] sending {len(payload['messages'])} messages (estimated {est_tokens} tokens)")

        # 强制禁用代理，确保直连本地或内网后端；对 429/503 做有限次重试 + 退避
        async with httpx.AsyncClient(
            timeout=60.0,
            proxy=None,
            trust_env=False
        ) as client:
            last_error = None
            for attempt in range(LLM_RETRY_MAX_ATTEMPTS):
                try:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=headers
                    )
                    if resp.status_code in (429, 503):
                        retry_after = resp.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after and retry_after.isdigit() else (LLM_RETRY_BASE_DELAY * (2 ** attempt))
                        delay = min(delay, 60.0)
                        if attempt < LLM_RETRY_MAX_ATTEMPTS - 1:
                            logger.warning(f"[{self.backend_name}] {resp.status_code} Too Many Requests, retry in {delay:.1f}s (attempt {attempt + 1}/{LLM_RETRY_MAX_ATTEMPTS})")
                            await asyncio.sleep(delay)
                            continue
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                except httpx.HTTPStatusError as e:
                    last_error = e
                    if e.response.status_code not in (429, 503) or attempt >= LLM_RETRY_MAX_ATTEMPTS - 1:
                        raise Exception(f"{self.backend_name} API error: {e.response.status_code} - {e.response.text}")
                    delay = LLM_RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"[{self.backend_name}] {e.response.status_code}, retry in {delay:.1f}s (attempt {attempt + 1}/{LLM_RETRY_MAX_ATTEMPTS})")
                    await asyncio.sleep(delay)
                except Exception as e:
                    raise Exception(f"Connection error to {self.backend_name}: {str(e)}")
            if last_error:
                raise Exception(f"{self.backend_name} API error: {last_error.response.status_code} - {last_error.response.text}")

    async def stream_chat(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        """流式聊天完成"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": req.model,
            "messages": [m.model_dump() for m in req.messages],
            "temperature": req.temperature,
            "top_p": req.top_p,
            "max_tokens": req.max_tokens,
            "stream": True
        }
        
        payload = await self._pre_process_payload(payload)

        # 估算 Token (简单估算：字符数 / 4)
        total_chars = sum(len(m.get("content", "")) for m in payload["messages"])
        est_tokens = total_chars // 4
        logger.info(f"[{self.backend_name}] sending {len(payload['messages'])} messages (estimated {est_tokens} tokens)")

        # 强制禁用代理，确保直连本地或内网后端
        async with httpx.AsyncClient(
            timeout=None,
            proxy=None,
            trust_env=False
        ) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise Exception(f"{self.backend_name} stream error: {response.status_code} - {error_text.decode()}")
                    
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data_str)
                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                delta = chunk["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                yield f"\n[Error connecting to {self.backend_name}]: {str(e)}"

    def model_info(self) -> dict:
        """模型元信息"""
        return {
            "backend": self.backend_name,
            "base_url": self.base_url,
            "supports_stream": True
        }

    async def _pre_process_payload(self, payload: dict) -> dict:
        """子类可重写此方法以在发送请求前处理 payload"""
        return payload
