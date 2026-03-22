"""
聊天完成 API 端点
使用统一的 ModelAgent 接口
"""
import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
import json
import re
import time
import uuid
from typing import Optional
from log import logger, log_structured

from config.settings import settings
from core.types import ChatCompletionRequest, ChatCompletionResponse, Message as LLMMessage
from core.agents.router import get_router
from core.conversation.manager import ConversationManager, Message as ConvMessage
from core.conversation.history_store import HistoryStore, HistoryStoreConfig
from core.memory.memory_store import MemoryStore, MemoryStoreConfig
from core.memory.memory_injector import MemoryInjector, MemoryInjectorConfig
from core.memory.memory_extractor import MemoryExtractor, MemoryExtractorConfig
from core.system.runtime_settings import get_auto_unload_local_model_on_switch

router = APIRouter()

# 0. 确定统一数据库路径
_db_path = (
    Path(__file__).resolve().parents[1] / "data" / "platform.db"
    if not settings.db_path
    else Path(settings.db_path)
)

# 1. 初始化历史存储（MVP）
_history_store = HistoryStore(
    HistoryStoreConfig(
        db_path=_db_path,
        embedding_dim=settings.memory_embedding_dim,
        vector_enabled=bool(settings.memory_vector_enabled),
    )
)

# 2. 初始化长期记忆组件（MVP）
memory_store = MemoryStore(
    MemoryStoreConfig(
        db_path=_db_path,
        embedding_dim=settings.memory_embedding_dim,
        vector_enabled=bool(settings.memory_vector_enabled),
        default_confidence=settings.memory_default_confidence,
        merge_enabled=bool(settings.memory_merge_enabled),
        merge_similarity_threshold=settings.memory_merge_similarity_threshold,
        conflict_enabled=bool(settings.memory_conflict_enabled),
        conflict_similarity_threshold=settings.memory_conflict_similarity_threshold,
        key_schema_enforced=bool(settings.memory_key_schema_enforced),
        key_schema_allow_unlisted=bool(settings.memory_key_schema_allow_unlisted),
    )
)
_memory_injector = MemoryInjector(
    memory_store,
    MemoryInjectorConfig(
        mode=(
            "vector"
            if settings.memory_inject_mode == "vector"
            else ("keyword" if settings.memory_inject_mode == "keyword" else "recent")
        ),
        top_k=settings.memory_inject_top_k,
        half_life_days=settings.memory_decay_half_life_days,
        default_confidence=settings.memory_default_confidence,
    ),
)
_memory_extractor = MemoryExtractor(
    memory_store,
    MemoryExtractorConfig(
        enabled=bool(settings.memory_extractor_enabled),
        temperature=settings.memory_extractor_temperature,
        top_p=settings.memory_extractor_top_p,
        max_tokens=settings.memory_extractor_max_tokens,
    ),
)

# 3. 初始化对话管理器（依赖 HistoryStore 和 MemoryInjector）
conv_manager = ConversationManager(
    history_store=_history_store,
    memory_injector=_memory_injector,
    max_messages=8
)


def _last_user_content(messages: list[LLMMessage]) -> str:
    for m in reversed(messages):
        if m.role == "user":
            if isinstance(m.content, str):
                return (m.content or "").strip()
            elif isinstance(m.content, list):
                # 多模态消息：提取文本内容
                text_content = ""
                for item in m.content:
                    if hasattr(item, 'type') and item.type == "text" and item.text:
                        text_content += item.text + " "
                    elif isinstance(item, dict) and item.get('type') == "text" and item.get('text'):
                        text_content += item['text'] + " "
                return text_content.strip()
            return ""
    return ""


_TRANSPORT_PREFIX_RE = re.compile(
    r"^\s*Sender\s*\(untrusted metadata\):\s*```json[\s\S]*?```\s*",
    re.IGNORECASE,
)
_LEADING_TIME_RE = re.compile(r"^\s*\[[^\]]+\]\s*")
_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_THINKING_PREFIX_RE = re.compile(r"^\s*thinking process\s*:\s*", re.IGNORECASE)


def _strip_transport_wrappers(text: str) -> str:
    s = text or ""
    if bool(getattr(settings, "chat_input_strip_transport_wrappers", True)):
        s = _TRANSPORT_PREFIX_RE.sub("", s)
        s = _LEADING_TIME_RE.sub("", s)
    return s.strip()


def _sanitize_user_content(content):
    if not bool(getattr(settings, "chat_input_strip_transport_wrappers", True)):
        return content
    if isinstance(content, str):
        return _strip_transport_wrappers(content)
    if isinstance(content, list):
        cleaned = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                new_item = dict(item)
                new_item["text"] = _strip_transport_wrappers(item.get("text", ""))
                cleaned.append(new_item)
            else:
                cleaned.append(item)
        return cleaned
    return content


def _sanitize_assistant_output(text: str) -> str:
    if not bool(getattr(settings, "chat_output_strip_reasoning", True)):
        return text
    s = text or ""
    s = _THINK_BLOCK_RE.sub("", s)
    s = _THINKING_PREFIX_RE.sub("", s)
    if "</think>" in s:
        s = s.split("</think>", 1)[-1]
    return s.strip()

def _get_user_id(request: Request) -> str:
    """获取用户 ID（已统一到 core.utils.user_context）"""
    from core.utils.user_context import get_user_id
    return get_user_id(request)


def _normalized_persistence_mode() -> str:
    mode = (getattr(settings, "chat_persistence_mode", "full") or "full").strip().lower()
    if mode not in {"off", "minimal", "full"}:
        return "full"
    return mode


def _clean_session_title(title_hint: str) -> str:
    text = (title_hint or "").strip().replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    if not text or text.startswith("{") or text.startswith("["):
        return "New Chat"
    max_len = max(8, int(getattr(settings, "chat_session_title_max_len", 50) or 50))
    return text[:max_len]


def _get_idempotency_key(request: Request) -> Optional[str]:
    names = (getattr(settings, "chat_idempotency_headers", "") or "").split(",")
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        value = (request.headers.get(name) or "").strip()
        if value:
            return value[:128]
    return None


def _is_truthy_header(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _should_force_new_session(request: Request) -> bool:
    names = (getattr(settings, "chat_force_new_session_headers", "") or "").split(",")
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        value = request.headers.get(name)
        if value and _is_truthy_header(value):
            return True
    return False


def _extract_user_attachments(last_user_msg: Optional[LLMMessage]) -> Optional[list[dict]]:
    if not last_user_msg or not isinstance(last_user_msg.content, list):
        return None
    attachments = []
    for item in last_user_msg.content:
        if isinstance(item, dict) and item.get("type") == "image_url":
            url = item.get("image_url", {}).get("url", "")
            if url:
                attachments.append({"type": "image", "url": url})
    return attachments or None


def _get_or_create_session_id(
    *,
    request: Request,
    user_id: str,
    title_hint: str,
    model_id: str,
    allow_create: bool,
    force_new: bool = False,
) -> Optional[str]:
    if force_new:
        if not allow_create:
            return None
        title = _clean_session_title(title_hint)
        return _history_store.create_session(user_id=user_id, title=title, last_model=model_id)

    sid = (request.headers.get("X-Session-Id") or "").strip()
    if sid and _history_store.session_exists(user_id=user_id, session_id=sid):
        return sid
    # 无显式会话时可按时间窗复用最近会话，避免外部客户端每轮新建会话
    reuse_minutes = int(getattr(settings, "chat_session_reuse_window_minutes", 15) or 0)
    if reuse_minutes > 0:
        recent_sid = _history_store.get_recent_active_session_id(user_id=user_id, within_minutes=reuse_minutes)
        if recent_sid:
            return recent_sid
    if not allow_create:
        return None
    # 后端自动创建会话
    title = _clean_session_title(title_hint)
    return _history_store.create_session(user_id=user_id, title=title, last_model=model_id)


async def _maybe_unload_previous_model(*, user_id: str, session_id: str, current_model_id: str) -> None:
    try:
        session = _history_store.get_session(user_id=user_id, session_id=session_id)
        last_model = (session or {}).get("last_model")
        if not last_model or last_model == current_model_id:
            return
        from core.models.registry import get_model_registry
        from core.runtimes.factory import get_runtime_factory

        reg = get_model_registry()
        prev_desc = reg.get_model(last_model)
        if not prev_desc or getattr(prev_desc, "provider", None) != "local":
            return
        await get_runtime_factory().unload_model(prev_desc.id)
        logger.info("[Chat] Unloaded previous model %s before switching to %s", last_model, current_model_id)
    except Exception as e:
        logger.warning("[Chat] Failed to unload previous model: %s", e)

@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(req: ChatCompletionRequest, request: Request, response: Response):
    """
    统一的聊天完成端点
    支持通过 model_id 或 model_require 选择模型
    
    Auto 模式智能选择：
    - 自动检测消息中是否包含图像
    - 有图像时自动切换到 VLM
    - 无图像时使用普通 LLM
    """
    # 先获取用户ID（模型选择需要用到）
    user_id = _get_user_id(request)
    
    # 1. 解析模型 (提前解析以便记录日志和管理会话)
    from core.models.selector import get_model_selector
    selector = get_model_selector()
    
    # 将消息转换为 dict 格式，用于智能模型选择
    messages_dict = [msg.model_dump() for msg in req.messages] if req.messages else None
    
    # 如果是自动模式，检查会话历史中是否包含图像
    # 这确保了后续对话（如"分析图片"）能正确选择VLM
    if req.model == "auto" and _history_store:
        try:
            # 尝试获取会话ID（从header或最近活跃会话）
            sid = (request.headers.get("X-Session-Id") or "").strip()
            if not sid or not _history_store.session_exists(user_id=user_id, session_id=sid):
                # 尝试获取最近活跃的会话
                reuse_minutes = int(getattr(settings, "chat_session_reuse_window_minutes", 15) or 0)
                if reuse_minutes > 0:
                    sid = _history_store.get_recent_active_session_id(user_id=user_id, within_minutes=reuse_minutes)
            
            if sid:
                session_messages = _history_store.list_messages(
                    user_id=user_id, 
                    session_id=sid, 
                    limit=10  # 检查最近10条消息
                )
                # 合并当前消息和会话历史用于图像检测
                all_messages = session_messages + (messages_dict or [])
                # 去重（避免当前消息已经在历史中）
                seen_ids = set()
                unique_messages = []
                for m in all_messages:
                    msg_id = m.get('id', id(m))
                    if msg_id not in seen_ids:
                        seen_ids.add(msg_id)
                        unique_messages.append(m)
                messages_dict = unique_messages
                logger.info(f"[Chat] Checking {len(messages_dict)} messages (including session history) for image detection")
        except Exception as e:
            logger.warning(f"[Chat] Failed to check session history for images: {e}")
    
    # Debug: log message structure for image detection
    if messages_dict:
        for i, msg in enumerate(messages_dict):
            content = msg.get('content')
            if isinstance(content, list):
                logger.info(f"[Chat] Message {i} has multimodal content with {len(content)} items")
                for j, item in enumerate(content):
                    if isinstance(item, dict):
                        logger.info(f"[Chat]   Item {j}: type={item.get('type')}")
    
    descriptor = selector.resolve(model_id=req.model, model_require=req.model_require, messages=messages_dict)
    
    # 使用解析后的实际模型ID替换原始请求中的模型标识
    # 这确保后续组件（如UnifiedAgent）使用已解析的模型，避免重复解析
    actual_model_id = descriptor.id
    req.model = actual_model_id

    logger.info(f"Received chat request: model={req.model} (actual={actual_model_id}), stream={req.stream}, max_tokens={req.max_tokens}")
    log_structured(
        "Chat", "chat_request",
        model_id=actual_model_id, stream=req.stream, message_count=len(req.messages or []), max_tokens=req.max_tokens,
    )

    # 验证请求
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    
    # 调试：打印接收到的消息结构
    logger.info(f"Received messages structure:")
    for i, msg in enumerate(req.messages):
        content_type = type(msg.content).__name__
        if isinstance(msg.content, list):
            logger.info(f"  Message {i} ({msg.role}): content is list with {len(msg.content)} items")
            for j, item in enumerate(msg.content):
                if isinstance(item, dict):
                    logger.info(f"    Item {j}: type={item.get('type')}, keys={list(item.keys())}")
                else:
                    logger.info(f"    Item {j}: type={type(item).__name__}")
        else:
            logger.info(f"  Message {i} ({msg.role}): content is {content_type}: {msg.content[:100]}...")
    
    # user_id was already retrieved earlier for model selection
    user_text = _strip_transport_wrappers(_last_user_content(req.messages))
    persistence_mode = _normalized_persistence_mode()
    request_id = _get_idempotency_key(request)
    force_new_session = _should_force_new_session(request)

    last_user_msg = None
    for msg in reversed(req.messages):
        if msg.role == "user":
            last_user_msg = msg
            break

    should_create_session = persistence_mode != "off" and bool(user_text)

    # 2. 在可持久化模式下按需建立/复用会话（避免空会话脏数据）
    session_id = _get_or_create_session_id(
        request=request,
        user_id=user_id,
        title_hint=user_text,
        model_id=actual_model_id,
        allow_create=should_create_session,
        force_new=force_new_session,
    )

    # 2.1 如果模型切换，按配置决定是否卸载上一个本地模型（可前端配置）
    if session_id and get_auto_unload_local_model_on_switch():
        await _maybe_unload_previous_model(
            user_id=user_id,
            session_id=session_id,
            current_model_id=actual_model_id,
        )
    # 通用资源回收：切换会话/模型时释放空闲重模型缓存
    try:
        from core.runtimes.factory import get_runtime_factory
        await get_runtime_factory().auto_release_unused_local_runtimes(
            keep_model_ids={actual_model_id},
            reason="chat_api",
        )
    except Exception:
        pass

    # Trace / IDs (必须提前初始化，避免 RAG 分支失败导致变量不存在)
    trace_id: Optional[str] = None
    retrieved_count: int = 0  # RAG 检索到的 chunks 数量
    completion_id = f"chatcmpl-{uuid.uuid4()}"
    message_id = f"msg_{uuid.uuid4().hex[:16]}"

    # 2. 将当前用户消息写入历史（仅 full 模式预写；minimal 在成功后再写）
    if persistence_mode == "full" and user_text and session_id:
        user_attachments = _extract_user_attachments(last_user_msg)
        # 保存消息到历史记录（保持多模态内容）
        conv_manager.append_user_message(
            user_id=user_id, 
            session_id=session_id, 
            content=_sanitize_user_content(last_user_msg.content if last_user_msg else user_text),
            meta={'attachments': user_attachments} if user_attachments else None,
            request_id=f"{request_id}:user" if request_id else None,
        )

    # 3. 构造 LLM 上下文（full 模式走历史拼装；minimal/off 直接使用来包消息）
    if persistence_mode == "full" and session_id:
        safe_messages_dict = conv_manager.build_llm_context(
            user_id=user_id,
            session_id=session_id,
            max_messages=req.max_history_messages,
            system_prompt=req.system_prompt
        )
    else:
        safe_messages_dict = [m.model_dump() for m in req.messages]
        if req.system_prompt:
            safe_messages_dict = [m for m in safe_messages_dict if m.get("role") != "system"]
            safe_messages_dict.insert(0, {"role": "system", "content": req.system_prompt})
    for m in safe_messages_dict:
        if m.get("role") == "user":
            m["content"] = _sanitize_user_content(m.get("content"))
    logger.info(f"Context built: {len(safe_messages_dict)} messages prepared for {req.model}")
        
    # 4. 更新请求对象中的消息（转换回 Message Pydantic 对象）
    req.messages = [LLMMessage(**m) for m in safe_messages_dict]
    
    # 4.5. RAG Plugin 处理（如果请求包含 rag 配置）
    if req.rag:
        try:
            from core.plugins.executor import get_plugin_executor
            from core.plugins.context import PluginContext
            from core.knowledge.knowledge_base_store import KnowledgeBaseStore, KnowledgeBaseConfig
            from core.runtimes.factory import get_runtime_factory
            from core.models.registry import get_model_registry
            from core.plugins.registry import get_plugin_registry
            
            # 获取知识库信息，以确定正确的 embedding_dim
            model_registry = get_model_registry()
            
            # 先创建一个临时 KnowledgeBaseStore 来获取知识库信息
            temp_kb_store = KnowledgeBaseStore(
                KnowledgeBaseConfig(
                    db_path=_db_path,
                    embedding_dim=settings.memory_embedding_dim,  # 临时值，稍后会更新
                )
            )
            
            # 获取所有相关的知识库信息（支持多知识库）
            kb_ids = []
            if req.rag.knowledge_base_ids:
                kb_ids.extend(req.rag.knowledge_base_ids)
            if req.rag.knowledge_base_id and req.rag.knowledge_base_id not in kb_ids:
                kb_ids.append(req.rag.knowledge_base_id)
            
            if not kb_ids:
                raise ValueError("No knowledge_base_id or knowledge_base_ids provided")
            
            # 获取所有知识库的信息和 embedding 模型
            kb_infos = {}
            embedding_model_ids = set()
            for kb_id in kb_ids:
                kb_info = temp_kb_store.get_knowledge_base(kb_id)
                if not kb_info:
                    logger.warning(f"[RAG] Knowledge base '{kb_id}' not found, skipping")
                    continue
                kb_infos[kb_id] = kb_info
                embedding_model_ids.add(kb_info["embedding_model_id"])
            
            if not kb_infos:
                raise ValueError("No valid knowledge bases found")
            
            # 使用第一个知识库的 embedding 模型维度（RAG Plugin 会处理多知识库的情况）
            first_kb_id = list(kb_infos.keys())[0]
            first_kb_info = kb_infos[first_kb_id]
            embedding_model_id = first_kb_info["embedding_model_id"]
            embedding_model = model_registry.get_model(embedding_model_id)
            
            if not embedding_model:
                logger.warning(
                    f"[RAG] Embedding model '{embedding_model_id}' not found, "
                    f"falling back to system default dimension {settings.memory_embedding_dim}"
                )
                actual_embedding_dim = settings.memory_embedding_dim
            else:
                # 从 model metadata 中获取 embedding_dim
                actual_embedding_dim = embedding_model.metadata.get("embedding_dim", settings.memory_embedding_dim)
                logger.info(
                    f"[RAG] Using embedding_dim={actual_embedding_dim} from model '{embedding_model_id}' "
                    f"for knowledge bases {list(kb_infos.keys())}"
                )
            
            # 使用正确的 embedding_dim 初始化 KnowledgeBaseStore
            kb_store = KnowledgeBaseStore(
                KnowledgeBaseConfig(
                    db_path=_db_path,
                    embedding_dim=actual_embedding_dim,
                )
            )
            
            # 确保所有知识库的向量表存在且维度正确
            # 注意：每个知识库有独立的表，需要为每个知识库确保表存在
            for kb_id, kb_info in kb_infos.items():
                kb_embedding_model_id = kb_info["embedding_model_id"]
                kb_embedding_model = model_registry.get_model(kb_embedding_model_id)
                if kb_embedding_model:
                    kb_dim = kb_embedding_model.metadata.get("embedding_dim", actual_embedding_dim)
                    kb_store._ensure_vec_table_dimension(kb_id, kb_dim)
            
            # 创建 PluginContext
            plugin_context = PluginContext(
                session_id=session_id,
                user_id=user_id,
                message_id=message_id,
                logger=logger,
                memory=memory_store,
                registry=model_registry,
                knowledge_base_store=kb_store,
                runtime_factory=get_runtime_factory(),
                plugin_registry=get_plugin_registry(),
            )
            
            # 执行 RAG Plugin
            plugin_executor = get_plugin_executor()
            
            rag_result = await plugin_executor.execute(
                name="rag",
                input_data={
                    "messages": [m.model_dump() for m in req.messages],
                    "rag": req.rag.model_dump(),
                },
                context=plugin_context,
            )
            
            # 更新 messages（RAG Plugin 返回增强后的 messages）
            if "messages" in rag_result:
                req.messages = [LLMMessage(**m) for m in rag_result["messages"]]
                logger.info(f"RAG Plugin enhanced messages: {len(req.messages)} messages after RAG")
                
                # 获取 trace_id 和 retrieved_count（如果 RAG Plugin 返回了）
                retrieved_count = 0
                if "metadata" in rag_result:
                    if "trace_id" in rag_result["metadata"]:
                        trace_id = rag_result["metadata"]["trace_id"]
                    if "retrieved_chunks" in rag_result["metadata"]:
                        retrieved_count = rag_result["metadata"]["retrieved_chunks"]
            
        except Exception as e:
            # RAG Plugin 失败不应该阻止正常流程，记录错误并继续
            logger.error(f"RAG Plugin execution failed: {e}", exc_info=True)
            # 继续使用原始 messages
        
    # 5. 获取模型 Agent
    agent = get_router().get_agent(req.model)
    
    created_time = int(time.time())
    
    # 辅助函数：finalize RAG trace
    async def _finalize_rag_trace(trace_id: str, final_message_id: str, response_text: str):
        """Finalize RAG trace after inference"""
        try:
            from core.rag.trace_store import RAGTraceStore, RAGTraceStoreConfig
            from pathlib import Path
            
            trace_store = RAGTraceStore(RAGTraceStoreConfig(db_path=RAGTraceStore.default_db_path()))
            
            # 估算注入的 token 数（粗略：1 token ≈ 4 chars）
            # 这里我们使用 RAG context 的长度作为 injected_token_count
            # 实际应该从 RAG Plugin 返回的 metadata 中获取，但为了简化，使用估算值
            injected_token_count = len(response_text) // 4  # 粗略估算
            
            trace_store.finalize_trace(trace_id, injected_token_count)
            
            # 更新 trace 的 message_id（如果不同）
            # 注意：这里我们假设 message_id 已经在创建时设置正确
            logger.debug(f"[RAGTrace] Finalized trace {trace_id} for message {final_message_id}")
        except Exception as e:
            logger.warning(f"[RAGTrace] Failed to finalize trace {trace_id}: {e}")

    def _persist_success_turn(assistant_text: str, is_stream: bool):
        if not session_id or not user_text or not assistant_text or persistence_mode == "off":
            return None

        # minimal 模式：仅在响应成功后补写 user，避免失败请求留下单边/空会话脏数据
        if persistence_mode == "minimal":
            conv_manager.append_user_message(
                user_id=user_id,
                session_id=session_id,
                content=_sanitize_user_content(last_user_msg.content if last_user_msg else user_text),
                meta={"attachments": _extract_user_attachments(last_user_msg)} if _extract_user_attachments(last_user_msg) else None,
                request_id=f"{request_id}:user" if request_id else None,
            )

        return conv_manager.append_assistant_message(
            user_id=user_id,
            session_id=session_id,
            content=assistant_text,
            model_id=req.model,
            meta={
                "completion_id": completion_id,
                "stream": is_stream,
                "rag": {
                    "used": bool(trace_id),
                    "trace_id": trace_id,
                    "retrieved_count": retrieved_count if trace_id else 0,
                },
                "params": {
                    "temperature": req.temperature,
                    "top_p": req.top_p,
                    "max_tokens": req.max_tokens,
                    "system_prompt": req.system_prompt
                }
            },
            request_id=f"{request_id}:assistant" if request_id else None,
        )

    # 流式响应
    if req.stream:
        async def event_generator():
            full_text = ""
            stream_start = time.perf_counter()
            log_structured("Chat", "chat_llm_start", model_id=req.model, session_id=session_id, stream=True, completion_id=completion_id)
            logger.info(f"Starting event generator for {completion_id}")
            try:
                async for token in agent.stream_chat(req):
                    # 检查客户端是否已断开连接
                    if await request.is_disconnected():
                        logger.info(f"Client disconnected for {completion_id}, stopping stream")
                        break
                    
                    full_text += token
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": req.model,
                        "choices": [{"index": 0, "delta": {"content": token}}]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                duration_ms = round((time.perf_counter() - stream_start) * 1000, 2)
                log_structured(
                    "Chat", "chat_llm_done",
                    model_id=req.model, session_id=session_id or "", stream=True, completion_id=completion_id,
                    duration_ms=duration_ms, response_len=len(full_text), rag_used=bool(trace_id),
                )
                logger.info(f"Streaming completion finished for {completion_id}")

                # 先持久化并 finalize RAG trace，再发送 [DONE]，确保前端 refetch 时能拿到带真实 message_id 的消息，RAG Trace 按 message_id 可查
                try:
                    final_text = _sanitize_assistant_output(full_text)
                    if user_text and final_text:
                        message = _persist_success_turn(final_text, True)
                        if trace_id:
                            injected_token_count = len(final_text) // 4
                            try:
                                from core.rag.trace_store import RAGTraceStore, RAGTraceStoreConfig
                                trace_store = RAGTraceStore(RAGTraceStoreConfig(db_path=RAGTraceStore.default_db_path()))
                                if message:
                                    trace_store.finalize_trace(trace_id, injected_token_count, final_message_id=message.id)
                                    logger.debug(f"[RAGTrace] Finalized trace {trace_id} for message {message.id}")
                            except Exception as e:
                                logger.warning(f"[RAGTrace] Failed to finalize trace {trace_id}: {e}")
                        if not await request.is_disconnected():
                            asyncio.create_task(
                                _memory_extractor.extract_and_store(
                                    user_id=user_id,
                                    model_id=req.model,
                                    user_text=user_text,
                                    assistant_text=final_text,
                                    meta={"completion_id": completion_id, "model": req.model, "stream": True},
                                )
                            )
                        else:
                            logger.info(f"Client disconnected for {completion_id}, skipping memory extraction")
                except Exception as e:
                    logger.warning(f"[Chat] Failed to persist/finalize after stream: {e}")
                yield "data: [DONE]\n\n"
            except Exception as e:
                # 检查是否是客户端断开（常见的断开异常）
                is_client_disconnect = (
                    "client disconnected" in str(e).lower() or
                    "connection closed" in str(e).lower() or
                    isinstance(e, (ConnectionError, BrokenPipeError))
                )
                
                if is_client_disconnect:
                    duration_ms = round((time.perf_counter() - stream_start) * 1000, 2)
                    log_structured("Chat", "chat_llm_done", model_id=req.model, session_id=session_id or "", stream=True, completion_id=completion_id, duration_ms=duration_ms, response_len=len(full_text), client_disconnected=True)
                    logger.info(f"Client disconnected during streaming for {completion_id}")
                    # 如果已有部分内容，保存它
                    if user_text and full_text:
                        try:
                            if persistence_mode == "full" and session_id:
                                partial_text = _sanitize_assistant_output(full_text)
                                if not partial_text:
                                    return
                                conv_manager.append_assistant_message(
                                    user_id=user_id,
                                    session_id=session_id,
                                    content=partial_text,
                                    model_id=req.model,
                                    meta={
                                        "completion_id": completion_id,
                                        "stream": True,
                                        "incomplete": True,  # 标记为不完整
                                        "error": "client_disconnected",
                                    },
                                    request_id=f"{request_id}:assistant:incomplete" if request_id else None,
                                )
                        except Exception as save_error:
                            logger.warning(f"Failed to save incomplete message: {save_error}")
                else:
                    duration_ms = round((time.perf_counter() - stream_start) * 1000, 2)
                    log_structured("Chat", "chat_llm_failed", model_id=req.model, session_id=session_id, stream=True, completion_id=completion_id, error=str(e)[:200], duration_ms=duration_ms)
                    logger.error(f"Streaming error for {completion_id}: {str(e)}", exc_info=True)
                    try:
                        error_chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": req.model,
                            "choices": [{"index": 0, "delta": {"content": f"\nError: {str(e)}"}}]
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                    except Exception:
                        # 如果 yield 也失败（客户端已断开），静默忽略
                        pass
        
        stream_headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        if session_id:
            stream_headers["X-Session-Id"] = session_id
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=stream_headers,
        )
    
    # 非流式响应
    log_structured("Chat", "chat_llm_start", model_id=req.model, session_id=session_id or "", stream=False, completion_id=completion_id)
    nonstream_start = time.perf_counter()
    try:
        content = _sanitize_assistant_output(await agent.chat(req))
        duration_ms = round((time.perf_counter() - nonstream_start) * 1000, 2)
        log_structured(
            "Chat", "chat_llm_done",
            model_id=req.model, session_id=session_id or "", stream=False, completion_id=completion_id,
            duration_ms=duration_ms, response_len=len(content) if content else 0, rag_used=bool(trace_id),
        )
        logger.info(f"Chat completion successful for {completion_id}")
    except Exception as e:
        duration_ms = round((time.perf_counter() - nonstream_start) * 1000, 2)
        log_structured(
            "Chat", "chat_llm_failed",
            model_id=req.model, session_id=session_id or "", stream=False, completion_id=completion_id,
            error=str(e)[:200], duration_ms=duration_ms,
        )
        logger.error(f"Chat completion error for {completion_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    # 持久化并提取长期记忆
    if user_text and content:
        message = _persist_success_turn(content, False)
        
        # Finalize RAG Trace（如果存在）
        if trace_id:
            injected_token_count = len(content) // 4  # 粗略估算
            try:
                from core.rag.trace_store import RAGTraceStore, RAGTraceStoreConfig
                trace_store = RAGTraceStore(RAGTraceStoreConfig(db_path=RAGTraceStore.default_db_path()))
                if message:
                    trace_store.finalize_trace(trace_id, injected_token_count, final_message_id=message.id)
                    logger.debug(f"[RAGTrace] Finalized trace {trace_id} for message {message.id}")
            except Exception as e:
                logger.warning(f"[RAGTrace] Failed to finalize trace {trace_id}: {e}")

        asyncio.create_task(
            _memory_extractor.extract_and_store(
                user_id=user_id,
                model_id=req.model,
                user_text=user_text,
                assistant_text=content,
                meta={"completion_id": completion_id, "model": req.model, "stream": False},
            )
        )
    
    # 非流式：通过 header 回传 session_id（方便前端保存）
    if session_id:
        response.headers["X-Session-Id"] = session_id

    return ChatCompletionResponse(
        id=completion_id,
        created=created_time,
        model=req.model,
        choices=[
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": "stop"
            }
        ],
        usage=None
    )
