import anyio
import asyncio
import copy
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence
from log import logger
from core.runtimes.base import ModelRuntime
from core.types import ChatCompletionRequest, Message as LLMMessage
from core.models.descriptor import ModelDescriptor
from core.utils.async_rwlock import AsyncRWLock

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None
    logger.warning("llama-cpp-python not installed. LlamaCppRuntime will be unavailable.")

_LLM_CACHE = {}
_LOADED_INSTANCES = {}  # Track actual Llama instances for proper cleanup
_MODEL_LOCKS: Dict[str, AsyncRWLock] = {}
_FALLBACK_LOCK = AsyncRWLock()


def _get_model_lock(model_path: str) -> AsyncRWLock:
    lock = _MODEL_LOCKS.get(model_path)
    if lock is None:
        lock = AsyncRWLock()
        _MODEL_LOCKS[model_path] = lock
    return lock

class LlamaCppRuntime(ModelRuntime):
    """
    llama.cpp 运行时实现 (基于 llama-cpp-python)
    """
    
    def _tokenize_len(self, llm: "Llama", text: str) -> int:
        """
        返回 prompt 的 token 数（用 llama.cpp 的 tokenizer，最准确）。
        """
        data = text.encode("utf-8")
        try:
            # llama-cpp-python 常见签名：tokenize(bytes, add_bos=False, special=True/False)
            return len(llm.tokenize(data, add_bos=False))
        except TypeError:
            # 兼容旧版本签名
            return len(llm.tokenize(data))

    def _truncate_messages_to_fit(
        self,
        *,
        llm: "Llama",
        descriptor: ModelDescriptor,
        messages: Sequence[Any],
        max_tokens: int,
    ) -> List[Any]:
        """
        确保 prompt_tokens + max_tokens <= n_ctx，否则按以下顺序裁剪：
        1) 丢弃最旧的非 system 历史消息（保留第一个 system）
        2) 如果只剩 system 仍超限，则截断 system 内容
        """
        n_ctx = int(descriptor.metadata.get("n_ctx", 4096) or 4096)
        # 给 stop tokens / 格式化留一点余量，避免边界抖动
        safety = 64
        budget = max(256, n_ctx - int(max_tokens) - safety)

        trimmed = list(messages)
        if not trimmed:
            return trimmed

        def _prompt_tokens(msgs: Sequence[Any]) -> int:
            req_copy = copy.copy(messages)  # not used; keep structure
            # 直接复用当前 runtime 的 prompt 模板
            tmp_req = copy.copy  # placeholder to satisfy type check
            # 构造一个最小 req 对象用于 _build_prompt
            class _TmpReq:
                def __init__(self, msgs):
                    self.messages = msgs
            prompt = self._build_prompt(descriptor, _TmpReq(list(msgs)))  # type: ignore[arg-type]
            return self._tokenize_len(llm, prompt)

        pt = _prompt_tokens(trimmed)
        changed = False

        # 1) 先丢弃最旧的非 system（即 index=1 的消息，保留 index=0 的 system）
        while pt > budget and len(trimmed) > 1:
            trimmed.pop(1)
            changed = True
            pt = _prompt_tokens(trimmed)

        # 2) 只剩 1 条（通常是 system）仍超限：截断 system 内容
        if pt > budget and trimmed:
            changed = True
            sys_msg = trimmed[0]
            if hasattr(sys_msg, "content") and isinstance(sys_msg.content, str):
                original = sys_msg.content
                # 迭代压缩，直到进入预算（用 tokenizer 精确计数）
                # 先粗略按比例缩，再细化
                lo, hi = 0, len(original)
                best = ""
                suffix = "\n\n[Truncated to fit context window]\n"
                # 二分找最大可用前缀长度
                while lo <= hi:
                    mid = (lo + hi) // 2
                    sys_msg.content = original[:mid] + suffix
                    pt_mid = _prompt_tokens(trimmed)
                    if pt_mid <= budget:
                        best = sys_msg.content
                        lo = mid + 1
                    else:
                        hi = mid - 1
                sys_msg.content = best or (original[: max(0, budget // 2)] + suffix)
                pt = _prompt_tokens(trimmed)

        if changed:
            logger.warning(
                f"[LlamaCppRuntime] Prompt trimmed to fit context: prompt_tokens={pt}, "
                f"budget={budget}, n_ctx={n_ctx}, max_tokens={max_tokens}, messages={len(messages)}->{len(trimmed)}"
            )

        return trimmed

    def _get_llm(self, descriptor: ModelDescriptor) -> "Llama":
        model_path = descriptor.metadata.get("path")
        if not model_path:
            raise ValueError(f"Model path missing in metadata for {descriptor.id}")
            
        if model_path not in _LLM_CACHE:
            logger.info(f"[LlamaCppRuntime] Loading model from {model_path}")
            # 从 metadata 中获取初始化参数
            n_ctx = descriptor.metadata.get("n_ctx", 4096)
            n_gpu_layers = descriptor.metadata.get("n_gpu_layers", 0)
            n_threads = descriptor.metadata.get("n_threads", 8)
            
            if Llama is None:
                raise ImportError("llama-cpp-python is not installed")
            
            # 检查是否为 VLM 模型
            model_type = descriptor.model_type if hasattr(descriptor, "model_type") else None
            is_vlm = model_type and model_type.lower() in ["vlm", "vision", "multimodal"]
            
            llm_kwargs = {
                "model_path": model_path,
                "n_ctx": n_ctx,
                "n_gpu_layers": n_gpu_layers,
                "n_threads": n_threads,
                "verbose": descriptor.metadata.get("verbose", False)
            }
            
            # 为 LLaVA 模型启用 VLM 支持
            if is_vlm and "llava" in model_path.lower():
                # 查找 mmproj 文件
                from pathlib import Path
                model_dir = Path(model_path).parent
                mmproj_files = list(model_dir.glob("*-mmproj*.gguf")) or list(model_dir.glob("mmproj-*.gguf"))
                
                if mmproj_files:
                    clip_model_path = str(mmproj_files[0])
                    logger.info(f"[LlamaCppRuntime] Found mmproj file for LLaVA: {clip_model_path}")
                    
                    try:
                        from llama_cpp.llama_chat_format import Llava15ChatHandler
                        llm_kwargs["chat_handler"] = Llava15ChatHandler(clip_model_path=clip_model_path)
                        llm_kwargs["logits_all"] = True  # Required for vision models
                        logger.info(f"[LlamaCppRuntime] Initialized LLaVA with Llava15ChatHandler")
                    except ImportError as e:
                        logger.warning(f"[LlamaCppRuntime] Llava15ChatHandler import failed: {e}")
                else:
                    logger.warning(f"[LlamaCppRuntime] No mmproj file found for LLaVA model")
            
            # 特殊处理 Qwen3-VL 模型（暂不支持）
            elif is_vlm and "qwen3-vl" in model_path.lower():
                logger.error(
                    f"[LlamaCppRuntime] Qwen3-VL model '{descriptor.id}' is not supported by current llama-cpp-python version. "
                    f"Please use a newer version or switch to a supported VLM model like LLaVA. "
                    f"The model will be loaded as text-only LLM (image inputs will be ignored)."
                )
                
            llm_instance = Llama(**llm_kwargs)
            _LLM_CACHE[model_path] = llm_instance
            _LOADED_INSTANCES[model_path] = llm_instance  # Track for cleanup
        return _LLM_CACHE[model_path]

    async def load(self, descriptor: ModelDescriptor) -> bool:
        """预加载模型"""
        try:
            await anyio.to_thread.run_sync(self._get_llm, descriptor)
            return True
        except Exception as e:
            logger.error(f"[LlamaCppRuntime] Load failed: {e}")
            return False

    async def unload(self, descriptor: ModelDescriptor) -> bool:
        """卸载模型"""
        model_path = descriptor.metadata.get("path")
        if model_path in _LLM_CACHE:
            logger.info(f"[LlamaCppRuntime] Unloading model {model_path}")
            try:
                lock = _get_model_lock(model_path)
                async with lock.write_lock():
                    # Clean up the actual Llama instance
                    if model_path in _LOADED_INSTANCES:
                        llm_instance = _LOADED_INSTANCES[model_path]
                        # Attempt to reset/clean the instance if possible
                        if hasattr(llm_instance, 'reset'):
                            llm_instance.reset()
                        elif hasattr(llm_instance, 'close'):
                            llm_instance.close()
                        # Remove reference
                        del _LOADED_INSTANCES[model_path]
                    
                    # Remove from cache
                    del _LLM_CACHE[model_path]
                    
                    # Force garbage collection
                    import gc
                    gc.collect()
                    
                    logger.info(f"[LlamaCppRuntime] Successfully unloaded {model_path}")
                    return True
            except Exception as e:
                logger.error(f"[LlamaCppRuntime] Error unloading {model_path}: {e}")
                # Still try to clean up references
                if model_path in _LOADED_INSTANCES:
                    del _LOADED_INSTANCES[model_path]
                if model_path in _LLM_CACHE:
                    del _LLM_CACHE[model_path]
                import gc
                gc.collect()
                return False
        return False

    async def is_loaded(self, descriptor: ModelDescriptor) -> bool:
        """检查模型是否已加载"""
        model_path = descriptor.metadata.get("path")
        return model_path in _LLM_CACHE

    def _get_stop_tokens(self, descriptor: ModelDescriptor) -> List[str]:
        tags = [t.lower() for t in descriptor.tags]
        is_qwen = "qwen" in tags or "qwen" in descriptor.name.lower()
        is_llama3 = "llama3" in tags or "llama-3" in descriptor.name.lower()
        
        stops = ["<|endoftext|>", "User:", "Assistant:"]
        if is_qwen:
            stops.extend(["<|im_end|>", "<|im_start|>"])
        if is_llama3:
            stops.extend(["<|eot_id|>", "<|start_header_id|>"])
        return stops

    async def chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> str:
        llm = self._get_llm(descriptor)
        max_tokens = req.max_tokens if (req.max_tokens is not None and req.max_tokens > 0) else 2048
        model_path = descriptor.metadata.get("path")
        lock = _get_model_lock(model_path) if model_path else _FALLBACK_LOCK
        
        # 检查是否为 VLM 模型且有图像输入
        is_vlm = descriptor.model_type and descriptor.model_type.lower() in ["vlm", "vision", "multimodal"]
        has_images = self._has_image_inputs(req.messages)
        
        async with lock.read_lock():
            if is_vlm and has_images:
                # 使用 create_chat_completion 处理多模态输入
                return await self._vlm_chat_completion(llm, req, max_tokens)
            else:
                # 传统文本聊天
                # 精确 token 预算裁剪，避免 exceed context window
                req.messages = self._truncate_messages_to_fit(
                    llm=llm,
                    descriptor=descriptor,
                    messages=req.messages,
                    max_tokens=max_tokens,
                )
                prompt = self._build_prompt(descriptor, req)
                stop = self._get_stop_tokens(descriptor)
                n_ctx = int(descriptor.metadata.get("n_ctx", 4096) or 4096)
                safety = 64
                prompt_tokens = self._tokenize_len(llm, prompt)
                max_tokens_cap = max(256, n_ctx - prompt_tokens - safety)
                effective_max_tokens = min(max_tokens, max_tokens_cap)
                if effective_max_tokens < max_tokens:
                    logger.info(
                        "[LlamaCppRuntime] Capping max_tokens to fit context: requested=%s effective=%s n_ctx=%s prompt_tokens=%s",
                        max_tokens, effective_max_tokens, n_ctx, prompt_tokens,
                    )
                max_tokens = effective_max_tokens
                # 使用 anyio 在线程池中运行阻塞调用
                def _generate():
                    output = llm(
                        prompt,
                        max_tokens=max_tokens,
                        temperature=req.temperature or 0.7,
                        top_p=req.top_p or 0.9,
                        stop=stop
                    )
                    return output["choices"][0]["text"]
                    
                return await anyio.to_thread.run_sync(_generate)

    async def stream_chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> AsyncIterator[str]:
        llm = self._get_llm(descriptor)
        max_tokens = req.max_tokens if (req.max_tokens is not None and req.max_tokens > 0) else 2048
        model_path = descriptor.metadata.get("path")
        lock = _get_model_lock(model_path) if model_path else _FALLBACK_LOCK
        
        # 检查是否为 VLM 模型且有图像输入
        is_vlm = descriptor.model_type and descriptor.model_type.lower() in ["vlm", "vision", "multimodal"]
        has_images = self._has_image_inputs(req.messages)

        async with lock.read_lock():
            if is_vlm and has_images:
                # 使用 create_chat_completion_stream 处理多模态流式输入
                async for token in self._vlm_stream_chat_completion(llm, req, max_tokens):
                    yield token
            else:
                # 传统文本流式聊天
                # 精确 token 预算裁剪，避免 exceed context window
                req.messages = self._truncate_messages_to_fit(
                    llm=llm,
                    descriptor=descriptor,
                    messages=req.messages,
                    max_tokens=max_tokens,
                )
                prompt = self._build_prompt(descriptor, req)
                stop = self._get_stop_tokens(descriptor)
                n_ctx = int(descriptor.metadata.get("n_ctx", 4096) or 4096)
                safety = 64
                prompt_tokens = self._tokenize_len(llm, prompt)
                max_tokens_cap = max(256, n_ctx - prompt_tokens - safety)
                effective_max_tokens = min(max_tokens, max_tokens_cap)
                if effective_max_tokens < max_tokens:
                    logger.info(
                        "[LlamaCppRuntime] Capping max_tokens to fit context: requested=%s effective=%s n_ctx=%s prompt_tokens=%s",
                        max_tokens, effective_max_tokens, n_ctx, prompt_tokens,
                    )
                max_tokens = effective_max_tokens
                temperature = req.temperature or 0.7
                top_p = req.top_p or 0.9
                
                # 这是一个生成器函数，稍后在线程中运行
                def _stream_gen():
                    for chunk in llm(
                        prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        stream=True,
                        stop=stop
                    ):
                        text = chunk["choices"][0]["text"]
                        if text:
                            yield text

                # 使用 anyio 迭代同步生成器
                sync_gen = _stream_gen()
                
                def _get_next():
                    try:
                        return next(sync_gen)
                    except StopIteration:
                        return None

                while True:
                    # 每次迭代都在线程中获取下一个值
                    token = await anyio.to_thread.run_sync(_get_next)
                    if token is None:
                        break
                    yield token

    def _build_prompt(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> str:
        """根据模型元数据构造 Prompt 模板"""
        tags = [t.lower() for t in descriptor.tags]
        is_qwen = "qwen" in tags or "qwen" in descriptor.name.lower()
        is_llama3 = "llama3" in tags or "llama-3" in descriptor.name.lower()
        
        prompt = ""
        
        if is_qwen:
            # Qwen2 ChatML 模板
            for msg in req.messages:
                prompt += f"<|im_start|>{msg.role}\n{msg.content}<|im_end|>\n"
            prompt += "<|im_start|>assistant\n"
        elif is_llama3:
            # Llama 3 模板
            prompt = "<|begin_of_text|>"
            for msg in req.messages:
                prompt += f"<|start_header_id|>{msg.role}<|end_header_id|>\n\n{msg.content}<|eot_id|>"
            prompt += "<|start_header_id|>assistant<|end_header_id|>\n\n"
        else:
            # 通用通用模板 (Simple)
            for msg in req.messages:
                role = "User" if msg.role == "user" else "Assistant"
                if msg.role == "system":
                    prompt += f"System: {msg.content}\n"
                else:
                    prompt += f"{role}: {msg.content}\n"
            prompt += "Assistant: "
            
        return prompt
    
    def _get_content_item_parts(self, item: Any) -> Optional[Dict[str, Any]]:
        """
        从 content item（dict 或 MessageContentItem）提取 type/text/image_url。
        返回 None 表示跳过该项。
        """
        if isinstance(item, dict):
            itype = item.get("type")
            text = item.get("text", "")
            url = (item.get("image_url") or {}).get("url", "")
        else:
            itype = getattr(item, "type", None)
            text = getattr(item, "text", "") or ""
            url = (getattr(item, "image_url", None) or {}).get("url", "")
        if not itype:
            return None
        return {"type": itype, "text": text, "url": url}

    def _has_image_inputs(self, messages: List[LLMMessage]) -> bool:
        """检查消息中是否包含图像输入"""
        has_images = False
        logger.info(f"[LlamaCppRuntime] Checking {len(messages)} messages for images")
        for i, msg in enumerate(messages):
            logger.info(f"[LlamaCppRuntime] Message {i} role={msg.role}, content type={type(msg.content).__name__}")
            if isinstance(msg.content, list):
                logger.info(f"[LlamaCppRuntime] Message {i} content is list with {len(msg.content)} items")
                for j, item in enumerate(msg.content):
                    logger.info(f"[LlamaCppRuntime] Item {j} type: {type(item).__name__}")
                    if hasattr(item, 'type'):
                        logger.info(f"[LlamaCppRuntime] Item {j} has type attribute: {item.type}")
                        if item.type == 'image_url':
                            has_images = True
                            logger.info(f"[LlamaCppRuntime] Found image input in message: {getattr(item, 'image_url', 'no image_url attr')}")
                    elif isinstance(item, dict) and item.get('type') == 'image_url':
                        has_images = True
                        logger.info(f"[LlamaCppRuntime] Found image input in message: {item.get('image_url', {}).get('url', '')[:50]}...")
        if has_images:
            logger.info(f"[LlamaCppRuntime] Total {len(messages)} messages, found image inputs")
        else:
            logger.info(f"[LlamaCppRuntime] Total {len(messages)} messages, NO image inputs found")
        return has_images
    
    async def _vlm_chat_completion(self, llm, req: ChatCompletionRequest, max_tokens: int) -> str:
        """处理 VLM 多模态聊天完成"""
        # 转换消息格式以适应 llama-cpp-python 的 create_chat_completion
        converted_messages = []
        for msg in req.messages:
            if isinstance(msg.content, list):
                # 多模态消息：先收集，再按 LLaVA 要求排序（图像在文本前）
                image_items: List[Dict] = []
                text_items: List[Dict] = []
                for item in msg.content:
                    parts = self._get_content_item_parts(item)
                    if not parts:
                        continue
                    if parts["type"] == "text":
                        text_items.append({"type": "text", "text": parts["text"]})
                    elif parts["type"] == "image_url":
                        url = parts["url"]
                        if url.startswith("data:image/") or url.startswith("data:application/octet-stream"):
                            image_items.append({"type": "image_url", "image_url": {"url": url}})
                        else:
                            try:
                                import base64
                                import requests
                                response = requests.get(url, timeout=10)
                                response.raise_for_status()
                                image_data = base64.b64encode(response.content).decode("utf-8")
                                mime_type = response.headers.get("content-type", "image/jpeg")
                                data_url = f"data:{mime_type};base64,{image_data}"
                                image_items.append({"type": "image_url", "image_url": {"url": data_url}})
                            except Exception as e:
                                logger.warning(f"Failed to download image from {url}: {e}")
                                continue
                content_items = image_items + text_items
                if content_items:
                    converted_messages.append({"role": msg.role, "content": content_items})
            else:
                converted_messages.append({"role": msg.role, "content": msg.content})
        
        # 使用 anyio 在线程池中运行阻塞调用
        def _generate():
            response = llm.create_chat_completion(
                messages=converted_messages,
                max_tokens=max_tokens,
                temperature=req.temperature or 0.7,
                top_p=req.top_p or 0.9,
            )
            return response['choices'][0]['message']['content']
            
        return await anyio.to_thread.run_sync(_generate)
    
    async def _vlm_stream_chat_completion(self, llm, req: ChatCompletionRequest, max_tokens: int) -> AsyncIterator[str]:
        """处理 VLM 多模态流式聊天完成"""
        # 转换消息格式（与 _vlm_chat_completion 一致：图像在文本前）
        converted_messages = []
        for msg in req.messages:
            if isinstance(msg.content, list):
                image_items = []
                text_items = []
                for item in msg.content:
                    parts = self._get_content_item_parts(item)
                    if not parts:
                        continue
                    if parts["type"] == "text":
                        text_items.append({"type": "text", "text": parts["text"]})
                    elif parts["type"] == "image_url":
                        url = parts["url"]
                        if url.startswith("data:image/") or url.startswith("data:application/octet-stream"):
                            image_items.append({"type": "image_url", "image_url": {"url": url}})
                        else:
                            try:
                                import base64
                                import requests
                                response = requests.get(url, timeout=10)
                                response.raise_for_status()
                                image_data = base64.b64encode(response.content).decode("utf-8")
                                mime_type = response.headers.get("content-type", "image/jpeg")
                                data_url = f"data:{mime_type};base64,{image_data}"
                                image_items.append({"type": "image_url", "image_url": {"url": data_url}})
                            except Exception as e:
                                logger.warning(f"Failed to download image from {url}: {e}")
                                continue
                content_items = image_items + text_items
                if content_items:
                    converted_messages.append({"role": msg.role, "content": content_items})
            else:
                converted_messages.append({"role": msg.role, "content": msg.content})
        
        # 使用 anyio 在线程池中运行阻塞调用
        def _stream_generate():
            for chunk in llm.create_chat_completion(
                messages=converted_messages,
                max_tokens=max_tokens,
                temperature=req.temperature or 0.7,
                top_p=req.top_p or 0.9,
                stream=True
            ):
                if 'choices' in chunk and len(chunk['choices']) > 0:
                    delta = chunk['choices'][0].get('delta', {})
                    content = delta.get('content', '')
                    if content:
                        yield content
        
        # 使用 anyio 将同步生成器包装为异步迭代器
        sync_gen = _stream_generate()
        
        def _get_next():
            try:
                return next(sync_gen)
            except StopIteration:
                return None
        
        while True:
            token = await anyio.to_thread.run_sync(_get_next)
            if token is None:
                break
            yield token
