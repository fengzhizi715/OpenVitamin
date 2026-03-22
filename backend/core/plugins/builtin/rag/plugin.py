"""
RAG Plugin v1
实现 retrieve → inject → merge 完整流程
"""
from typing import Dict, Any, List, Optional

from core.plugins.base import Plugin
from core.plugins.context import PluginContext
from core.types import Message
from log import logger


class RAGPlugin(Plugin):
    """
    RAG (Retrieval-Augmented Generation) 插件 v1
    
    职责：
    1. retrieve: 调用 embedding runtime + sqlite-vec
    2. inject: 构造 context prompt
    3. merge: 和用户 messages 合并
    
    架构位置：
    Chat Request → RAG Plugin → Unified Agent → LLM Runtime
    """
    name = "rag"
    version = "1.0.0"
    description = "Retrieval-Augmented Generation: retrieve context from knowledge base and inject into messages"
    type = "capability"
    stage = "pre"  # 在模型推理前执行，用于增强上下文

    supported_modes = ["chat", "agent"]
    permissions = []  # RAG 不需要特殊权限

    input_schema = {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["role", "content"],
                },
                "description": "聊天消息列表",
            },
            "rag": {
                "type": "object",
                "properties": {
                    "knowledge_base_id": {"type": "string"},
                    "knowledge_base_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，支持多个知识库同时检索"
                    },
                    "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
                    # 注意：score_threshold 实际是 distance 阈值（max_distance）
                    # embedding 默认 L2 normalize，常见距离范围约 0~2
                    "score_threshold": {"type": "number", "default": 1.2, "minimum": 0, "maximum": 2},
                },
                # 取消 knowledge_base_id 的硬性要求，改为在代码中判断两者其一
            },
        },
        "required": ["messages", "rag"],
    }

    output_schema = {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
            "metadata": {
                "type": "object",
                "properties": {
                    "retrieved_chunks": {"type": "integer"},
                    "sources": {"type": "array", "items": {"type": "string"}}
                }
            }
        },
        "required": ["messages"],
    }

    async def initialize(self, context: PluginContext) -> bool:
        """
        初始化插件
        
        注意：knowledge_base_store 和 runtime_factory 在初始化时可能不可用，
        它们会在执行时通过 PluginContext 提供，所以这里不强制要求。
        """
        # 调用父类方法设置 _initialized 标志
        result = await super().initialize(context)
        if not result:
            return False
        
        # 插件初始化时这些依赖可能还未准备好，但在执行时会提供
        # 所以这里只记录警告，不阻止注册
        if context.knowledge_base_store is None:
            logger.debug("[RAGPlugin] KnowledgeBaseStore not available during initialization (will be provided at runtime)")
        
        if context.runtime_factory is None:
            logger.debug("[RAGPlugin] RuntimeFactory not available during initialization (will be provided at runtime)")
        
        # 允许插件注册，即使依赖在初始化时不可用
        return True

    async def execute(
        self,
        input: Dict[str, Any],
        context: PluginContext,
    ) -> Dict[str, Any]:
        """
        执行 RAG 流程：retrieve → inject → merge
        
        注意：在执行时检查依赖是否可用
        """
        # 在执行时检查依赖
        if context.knowledge_base_store is None:
            if context.logger:
                context.logger.error("[RAGPlugin] KnowledgeBaseStore not available in context")
            return {"messages": input.get("messages", [])}
        
        if context.runtime_factory is None:
            if context.logger:
                context.logger.error("[RAGPlugin] RuntimeFactory not available in context")
            return {"messages": input.get("messages", [])}
        
        messages: List[Dict[str, Any]] = input["messages"]
        rag_config: Dict[str, Any] = input["rag"]
        
        # 获取 KB IDs，优先支持多选，向后兼容单选
        kb_ids = rag_config.get("knowledge_base_ids") or []
        kb_id = rag_config.get("knowledge_base_id")
        if kb_id and kb_id not in kb_ids:
            kb_ids.append(kb_id)
            
        if not kb_ids:
            if context.logger:
                context.logger.warning("[RAGPlugin] No knowledge_base_id or knowledge_base_ids provided")
            return {"messages": messages}

        top_k = rag_config.get("top_k", 5)
        score_threshold = rag_config.get("score_threshold", 1.2)

        if context.logger:
            context.logger.info(
                f"[RAGPlugin] Processing RAG request: kb_ids={kb_ids}, top_k={top_k}, "
                f"score_threshold={score_threshold}"
            )

        # 1. Context-Aware Query Extraction: 结合上下文生成检索 Query
        # 简单策略：结合最后两个回合的消息，帮助解决指代消解问题
        # 限制长度避免超出 embedding 模型的 token 限制
        query_text = self._extract_context_aware_query(messages, max_length=512)
        if not query_text:
            if context.logger:
                context.logger.warning("[RAGPlugin] No query text extracted, skipping RAG")
            return {"messages": messages}

        # 2. Retrieve: 验证所有知识库使用相同的 embedding 模型
        embedding_model_ids = set()
        kb_infos = {}
        for kb_id in kb_ids:
            kb_info = context.knowledge_base_store.get_knowledge_base(kb_id)
            if not kb_info:
                if context.logger:
                    context.logger.warning(f"[RAGPlugin] Knowledge base '{kb_id}' not found, skipping")
                continue
            kb_infos[kb_id] = kb_info
            embedding_model_ids.add(kb_info["embedding_model_id"])
        
        if not kb_infos:
            if context.logger:
                context.logger.error(f"[RAGPlugin] No valid knowledge bases found")
            return {"messages": messages}
        
        # 检查 embedding 模型一致性
        if len(embedding_model_ids) > 1:
            if context.logger:
                context.logger.warning(
                    f"[RAGPlugin] Multiple embedding models detected: {embedding_model_ids}. "
                    f"Using first model '{list(embedding_model_ids)[0]}' for query embedding. "
                    f"This may cause dimension mismatch issues."
                )
        
        # 使用第一个知识库的 embedding 模型
        target_kb_id = list(kb_infos.keys())[0]
        embedding_model_id = kb_infos[target_kb_id]["embedding_model_id"]
        
        if not context.registry:
            return {"messages": messages}
        
        embedding_model = context.registry.get_model(embedding_model_id)
        if not embedding_model:
            return {"messages": messages}

        # 生成 query embedding（通过 Inference Gateway 解耦调用方）
        try:
            from core.inference import get_inference_client
            client = get_inference_client()
            resp = await client.embed(
                model=embedding_model.id,
                input_text=[query_text],
                metadata={
                    "caller": "RAGPlugin.embed_query",
                    "session_id": context.session_id or "",
                    "agent_id": context.agent_id or "",
                    "kb_ids": kb_ids,
                },
            )
            query_embeddings = resp.embeddings
            if not query_embeddings:
                return {"messages": messages}
            query_embedding = query_embeddings[0]
        except Exception as e:
            if context.logger:
                context.logger.error(f"[RAGPlugin] Failed to embed query: {e}")
            return {"messages": messages}

        # 向量检索 (支持多库)
        chunks = []
        try:
            chunks = context.knowledge_base_store.search_chunks_multi_kb(
                knowledge_base_ids=kb_ids,
                query_embedding=query_embedding,
                limit=top_k,
                max_distance=score_threshold,
            )
        except Exception as e:
            if context.logger:
                context.logger.error(f"[RAGPlugin] Vector search failed: {e}")
            # 即使搜索失败，也记录 trace（标记为失败）
            trace_id = self._record_trace_retrieve(
                context=context,
                query_text=query_text,
                embedding_model_id=embedding_model_id,
                kb_ids=kb_ids,
                top_k=top_k,
                chunks=[],  # 空列表表示搜索失败或没有结果
            )
            return {
                "messages": messages,
                "metadata": {
                    "retrieved_chunks": 0,
                    "sources": [],
                    "trace_id": trace_id,
                }
            }

        # RAG Trace: 记录检索结果（无论是否找到 chunks）
        trace_id = self._record_trace_retrieve(
            context=context,
            query_text=query_text,
            embedding_model_id=embedding_model_id,
            kb_ids=kb_ids,
            top_k=top_k,
            chunks=chunks,
        )

        if not chunks:
            if context.logger:
                context.logger.info("[RAGPlugin] No relevant chunks found")
            # 即使没有找到 chunks，也返回 trace_id，让前端知道 RAG 执行了
            return {
                "messages": messages,
                "metadata": {
                    "retrieved_chunks": 0,
                    "sources": [],
                    "trace_id": trace_id,  # 返回 trace_id，即使没有找到结果
                }
            }

        # 3. Inject: 构造 context prompt (含引用)
        # 获取模型的上下文长度（如果可用），默认使用 2000 tokens 作为 RAG 上下文预算
        # 注意：这里需要从 input 中获取模型信息，或者从 context 中获取
        # 为了安全，我们使用保守的默认值，并允许通过配置调整
        max_context_tokens = rag_config.get("max_context_tokens", 2000)
        context_text = self._build_context(chunks, max_context_tokens=max_context_tokens)

        # 4. Merge: 合并到 messages (优化合并策略)
        enhanced_messages = self._merge_context(messages, context_text)

        sources = sorted(list(set([c.get("doc_source", "Unknown") for c in chunks])))
        
        if context.logger:
            context.logger.info(
                f"[RAGPlugin] RAG completed: retrieved {len(chunks)} chunks from {len(sources)} sources"
            )

        return {
            "messages": enhanced_messages,
            "metadata": {
                "retrieved_chunks": len(chunks),
                "sources": sources,
                "trace_id": trace_id,  # 返回 trace_id 供 chat.py 使用
            }
        }

    def _extract_context_aware_query(self, messages: List[Dict[str, Any]], max_length: int = 512) -> str:
        """
        提取具有上下文意识的 Query
        简单版本：拼接最后 User + Assistant + User 消息，提高语义覆盖
        
        Args:
            messages: 消息列表
            max_length: 最大字符长度限制（避免超出 embedding 模型 token 限制）
        """
        recent_messages = []
        count = 0
        for msg in reversed(messages):
            if msg.get("role") in ["user", "assistant"]:
                content = msg.get("content", "").strip()
                if content:
                    recent_messages.append(content)
                    count += 1
            if count >= 3:  # 取最近 3 条消息
                break
        
        if not recent_messages:
            return ""
            
        # 逆序回来
        recent_messages.reverse()
        query_text = "\n".join(recent_messages).strip()
        
        # 如果查询文本太长，只保留最后一条用户消息
        if len(query_text) > max_length:
            # 只使用最后一条用户消息
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "").strip()
                    if content:
                        # 如果最后一条用户消息也很长，截断它
                        return content[:max_length]
        
        return query_text

    def _build_context(self, chunks: List[Dict[str, Any]], max_context_tokens: int = 2000) -> str:
        """
        构造包含引用信息的 context prompt
        
        格式：
        [1] source_filename: content
        [2] source_filename: content
        
        Args:
            chunks: 检索到的 chunks
            max_context_tokens: 最大上下文 token 数（粗略估算：1 token ≈ 4 chars）
        """
        if not chunks:
            return ""

        # 估算 token 数（粗略：1 token ≈ 4 chars）
        max_chars = max_context_tokens * 4
        
        context_parts = []
        total_chars = 0
        prompt_header = (
            "You are a helpful assistant. Use the following context to answer the user's question.\n"
            "If the context doesn't contain the answer, you can still use your own knowledge but prioritize the context provided.\n\n"
            "Context:\n"
            "----------\n"
        )
        prompt_footer = "\n----------\n"
        header_footer_chars = len(prompt_header) + len(prompt_footer)
        
        # 预留一些空间给 header 和 footer
        available_chars = max_chars - header_footer_chars
        
        for i, chunk in enumerate(chunks, 1):
            source = chunk.get("doc_source", "Unknown")
            content = chunk.get("content", "").strip()
            if not content:
                continue
            
            # 格式化 chunk
            chunk_text = f"[{i}] {source}:\n{content}"
            chunk_chars = len(chunk_text)
            
            # 如果加上这个 chunk 会超出限制，截断当前 chunk 的内容
            if total_chars + chunk_chars > available_chars:
                remaining_chars = available_chars - total_chars - len(f"[{i}] {source}:\n")
                if remaining_chars > 50:  # 至少保留 50 个字符
                    truncated_content = content[:remaining_chars] + "..."
                    context_parts.append(f"[{i}] {source}:\n{truncated_content}")
                break
            
            context_parts.append(chunk_text)
            total_chars += chunk_chars
        
        if not context_parts:
            return ""
        
        context_text = "\n\n".join(context_parts)
        
        prompt = prompt_header + context_text + prompt_footer
        return prompt

    def _merge_context(self, messages: List[Dict[str, Any]], context_text: str) -> List[Dict[str, Any]]:
        """
        优化合并策略：
        1. 如果已有 system 消息，合并到第一个 system 消息中
        2. 如果没有 system 消息，在最后一条用户消息前插入
        3. 避免产生多个 system 消息（某些模型可能只处理第一个）
        """
        if not messages:
            return [{"role": "system", "content": context_text}]

        enhanced = []
        system_found = False
        
        # 第一遍：查找并合并到第一个 system 消息
        for msg in messages:
            if msg.get("role") == "system" and not system_found:
                # 合并到第一个 system 消息
                original_content = msg.get("content", "").strip()
                if original_content:
                    # 如果已有内容，添加分隔符
                    msg = {
                        "role": "system",
                        "content": f"{original_content}\n\n{context_text}"
                    }
                else:
                    msg = {
                        "role": "system",
                        "content": context_text
                    }
                system_found = True
            enhanced.append(msg)
        
        # 如果没有 system 消息，在最后一条用户消息前插入
        if not system_found:
            last_user_idx = -1
            for i, msg in enumerate(enhanced):
                if msg.get("role") == "user":
                    last_user_idx = i
            
            if last_user_idx >= 0:
                # 插入在最后一条用户消息之前
                enhanced.insert(last_user_idx, {"role": "system", "content": context_text})
            else:
                # 没有用户消息，加在开头
                enhanced.insert(0, {"role": "system", "content": context_text})
        
        return enhanced
    
    def _record_trace_retrieve(
        self,
        context: PluginContext,
        query_text: str,
        embedding_model_id: str,
        kb_ids: List[str],
        top_k: int,
        chunks: List[Dict[str, Any]],
    ) -> Optional[str]:
        """
        记录 RAG Trace 的检索阶段
        
        Returns:
            trace_id 或 None（如果记录失败）
        """
        try:
            # 获取 session_id 和 message_id（从 context 中获取）
            session_id = getattr(context, "session_id", None)
            message_id = getattr(context, "message_id", None)
            
            if not session_id or not message_id:
                if context.logger:
                    context.logger.debug("[RAGPlugin] Missing session_id or message_id, skipping trace")
                return None
            
            # 直接调用 trace_store（避免 HTTP 调用）
            from core.rag.trace_store import RAGTraceStore, RAGTraceStoreConfig
            
            trace_store = RAGTraceStore(RAGTraceStoreConfig(db_path=RAGTraceStore.default_db_path()))
            
            # 获取用户 ID（多用户架构）
            user_id = context.user_id or "default"
            
            # 创建 trace
            rag_id = ",".join(kb_ids)  # 多个 KB 用逗号连接
            trace_id = trace_store.create_trace(
                session_id=session_id,
                message_id=message_id,
                rag_id=rag_id,
                rag_type="naive",
                query=query_text,
                embedding_model=embedding_model_id,
                vector_store="sqlite-vec",
                top_k=top_k,
                user_id=user_id,
            )
            
            # 添加 chunks
            trace_chunks = []
            for rank, chunk in enumerate(chunks, 1):
                trace_chunks.append({
                    "doc_id": chunk.get("document_id"),
                    "doc_name": chunk.get("doc_source"),
                    "chunk_id": chunk.get("chunk_id"),
                    "score": 1.0 - chunk.get("distance", 1.0),  # 转换为相似度分数
                    "content": chunk.get("content", ""),
                    "rank": rank,
                })
            
            if trace_chunks:
                trace_store.add_chunks(trace_id, trace_chunks)
            
            return trace_id
        except Exception as e:
            # Trace 记录失败不应该影响 RAG 流程
            if context.logger:
                context.logger.debug(f"[RAGPlugin] Failed to record trace: {e}")
            return None
