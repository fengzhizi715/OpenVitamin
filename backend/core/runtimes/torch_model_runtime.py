"""
TorchModelRuntime: 将 Torch VLM 适配为 ModelRuntime，供 Chat 流程使用

当 runtime="torch" 的 VLM 模型被 Chat 选中时，使用此 Runtime 而非 OpenAIRuntime。
- 有图像：委托 TorchVLMRuntime.infer()
- 纯文本：InternVL3 等需 img_context_token_id，传 448x448 占位图触发 vision 编码
"""

import base64
from io import BytesIO
from typing import AsyncIterator, Dict, Any, List, Optional

try:
    from PIL import Image
except ImportError:
    Image = None

from core.runtimes.base import ModelRuntime
from core.types import ChatCompletionRequest, Message
from core.models.descriptor import ModelDescriptor
from core.runtimes.vlm_types import VLMRequest, VLMGenerationConfig


def _extract_images_from_messages(messages: List[Message]) -> tuple[List[bytes], List[Dict[str, Any]]]:
    """
    从 messages 提取图像（base64 data URL）和构建 VLM 可用的 messages。
    返回 (images_bytes_list, messages_dict_list)
    """
    images: List[bytes] = []
    out_messages: List[Dict[str, Any]] = []

    for msg in messages:
        content = msg.content
        if isinstance(content, str):
            out_messages.append({"role": msg.role, "content": content})
            continue

        # content 为 List[MessageContentItem]
        new_content: List[Dict[str, Any]] = []
        for item in content:
            if not hasattr(item, "type"):
                continue
            if getattr(item, "type", None) == "text":
                new_content.append({"type": "text", "text": getattr(item, "text", "") or ""})
            elif getattr(item, "type", None) == "image_url":
                url = (getattr(item, "image_url") or {}).get("url", "")
                if url.startswith("data:"):
                    try:
                        b64 = url.split(",", 1)[-1]
                        raw = base64.b64decode(b64)
                        images.append(raw)
                        new_content.append({"type": "image_url", "image_url": {"url": url}})
                    except Exception:
                        pass
                else:
                    new_content.append({"type": "image_url", "image_url": {"url": url}})
        out_messages.append({"role": msg.role, "content": new_content})

    return images, out_messages


def _messages_to_prompt_and_system(messages: List[Message]) -> tuple[str, str]:
    """将 messages 转为 (system_prompt, user_prompt)"""
    system_parts: List[str] = []
    user_parts: List[str] = []

    for msg in messages:
        content = msg.content
        if isinstance(content, str):
            text = content.strip()
            if msg.role == "system":
                system_parts.append(text)
            elif msg.role == "user":
                user_parts.append(text)
            elif msg.role == "assistant":
                user_parts.append(f"Assistant: {text}")
        else:
            for item in content:
                if hasattr(item, "type") and getattr(item, "type") == "text":
                    text = (getattr(item, "text") or "").strip()
                    if msg.role == "system":
                        system_parts.append(text)
                    elif msg.role == "user":
                        user_parts.append(text)
                    elif msg.role == "assistant":
                        user_parts.append(f"Assistant: {text}")

    system_prompt = "\n".join(system_parts) if system_parts else ""
    user_prompt = "\n".join(user_parts) if user_parts else ""
    return system_prompt, user_prompt


def _normalize_vlm_messages(messages: List[Dict[str, Any]], fallback_system: str) -> List[Dict[str, Any]]:
    """
    规范化消息顺序，确保 chat template 约束：
    - system 仅保留一条
    - system 必须位于首位
    """
    system_texts: List[str] = []
    non_system: List[Dict[str, Any]] = []

    for m in messages:
        role = str(m.get("role") or "").lower()
        content = m.get("content")
        if role == "system":
            if isinstance(content, str):
                t = content.strip()
                if t:
                    system_texts.append(t)
            elif isinstance(content, list):
                for it in content:
                    if isinstance(it, dict) and it.get("type") == "text":
                        t = str(it.get("text") or "").strip()
                        if t:
                            system_texts.append(t)
            continue
        non_system.append(m)

    merged_system = "\n".join([t for t in system_texts if t]).strip()
    if not merged_system:
        merged_system = (fallback_system or "").strip()

    if merged_system:
        return [{"role": "system", "content": merged_system}] + non_system
    return non_system


class TorchModelRuntime(ModelRuntime):
    """
    Torch VLM 的 ModelRuntime 适配器

    供 Chat 流程使用，将 ChatCompletionRequest 转为 VLM infer 调用。
    支持纯文本和多模态（含图像）消息。
    """

    async def chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> str:
        from core.runtimes.factory import get_runtime_factory
        vlm = get_runtime_factory().create_vlm_runtime(descriptor)
        if not vlm.is_loaded:
            await vlm.initialize()

        images, vlm_messages = _extract_images_from_messages(req.messages)
        system_prompt, user_prompt = _messages_to_prompt_and_system(req.messages)

        if images:
            # 多模态：使用 infer(image=..., prompt=...)
            image_bytes = images[0]
            result = await vlm.infer(
                image=image_bytes,
                prompt=user_prompt or "Describe the image.",
                system_prompt=system_prompt or None,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                top_p=req.top_p,
            )
        else:
            # 纯文本：直接走 generate(messages, images=None)
            # InternVL3 优先走 model.chat(pixel_values=None) 路径，不需要占位图
            normalized_messages = _normalize_vlm_messages(vlm_messages, system_prompt)
            vlm_req = VLMRequest(
                messages=normalized_messages if normalized_messages else [{"role": "user", "content": user_prompt or "Hello."}],
                images=None,
                generation_config=VLMGenerationConfig(
                    max_tokens=req.max_tokens if (req.max_tokens is not None and req.max_tokens > 0) else 2048,
                    temperature=req.temperature,
                    top_p=req.top_p,
                ),
            )
            resp = await vlm.generate(vlm_req)
            result = ""
            if resp.choices:
                msg = resp.choices[0].get("message", {})
                result = msg.get("content", "")

        return result

    async def stream_chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> AsyncIterator[str]:
        # TorchVLMRuntime 暂不支持流式，一次性返回
        text = await self.chat(descriptor, req)
        if text:
            yield text

    async def load(self, descriptor: ModelDescriptor) -> bool:
        try:
            from core.runtimes.factory import get_runtime_factory
            vlm = get_runtime_factory().create_vlm_runtime(descriptor)
            await vlm.initialize()
            return True
        except Exception:
            return False

    async def unload(self, descriptor: ModelDescriptor) -> bool:
        try:
            from core.runtimes.factory import get_runtime_factory
            await get_runtime_factory().unload_vlm_runtime(descriptor.id)
            return True
        except Exception:
            return False

    async def is_loaded(self, descriptor: ModelDescriptor) -> bool:
        try:
            from core.runtimes.factory import get_runtime_factory
            vlm = get_runtime_factory().create_vlm_runtime(descriptor)
            return vlm.is_loaded
        except Exception:
            return False
