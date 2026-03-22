from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from log import logger
from core.conversation.history_store import HistoryStore, Role
from core.memory.memory_injector import MemoryInjector


class Message(BaseModel):
    """基础消息单元（支持多模态内容）"""
    id: str
    role: Role
    content: Union[str, List]
    created_at: datetime
    model: Optional[str] = None
    meta: Optional[dict[str, Any]] = None

# 重建模型以解决循环引用问题
Message.model_rebuild()


class Conversation(BaseModel):
    """对话会话"""
    id: str
    title: str
    messages: List[Message] = Field(default_factory=list)
    model_id: str
    created_at: datetime
    updated_at: datetime


class ConversationManager:
    """
    对话管理器：整个推理网关的大脑
    负责：
    - 管理会话生命周期与历史
    - 过滤非法/中间态消息
    - 控制上下文长度（条数/token）
    - 注入系统提示词与长期记忆
    """

    def __init__(
        self,
        history_store: HistoryStore,
        memory_injector: Optional[MemoryInjector] = None,
        max_messages: int = 10,
        system_prompt: str = "你是一个专业、简洁的 AI 助手。",
    ):
        self.history_store = history_store
        self.memory_injector = memory_injector
        self.max_messages = max_messages
        self.system_prompt = system_prompt

    def create_conversation(self, user_id: str, model_id: str, title_hint: str = "New Chat") -> Conversation:
        """创建新会话"""
        title = (title_hint or "New Chat").strip()[:50]
        sid = self.history_store.create_session(user_id=user_id, title=title, last_model=model_id)
        
        # 构造并返回 Conversation 对象
        now = datetime.now(timezone.utc)
        return Conversation(
            id=sid,
            title=title,
            messages=[],
            model_id=model_id,
            created_at=now,
            updated_at=now,
        )

    def append_user_message(
        self,
        user_id: str,
        session_id: str,
        content: Union[str, List],
        meta: Optional[dict] = None,
        request_id: Optional[str] = None,
    ) -> Message:
        """追加用户消息（支持多模态内容）"""
        # 如果是字符串，则去除空白字符
        if isinstance(content, str):
            content = content.strip()
        # 如果是列表（多模态），保持原样
            
        mid = self.history_store.append_message(
            session_id=session_id,
            role="user",
            content=content,
            meta=meta,
            request_id=request_id,
        )
        self.history_store.touch_session(user_id=user_id, session_id=session_id)
        
        return Message(
            id=mid,
            role="user",
            content=content,
            created_at=datetime.now(timezone.utc),
            meta=meta
        )

    def append_assistant_message(
        self, 
        user_id: str, 
        session_id: str, 
        content: str, 
        model_id: str,
        meta: Optional[dict] = None,
        request_id: Optional[str] = None,
    ) -> Message:
        """追加助手消息"""
        mid = self.history_store.append_message(
            session_id=session_id,
            role="assistant",
            content=content,
            model=model_id,
            meta=meta,
            request_id=request_id,
        )
        self.history_store.touch_session(user_id=user_id, session_id=session_id, last_model=model_id)
        
        return Message(
            id=mid,
            role="assistant",
            content=content,
            created_at=datetime.now(timezone.utc),
            model=model_id,
            meta=meta
        )

    def get_messages(self, user_id: str, session_id: str, limit: int = 100) -> List[Message]:
        """获取会话历史消息"""
        raw_msgs = self.history_store.list_messages(user_id=user_id, session_id=session_id, limit=limit)
        messages = []
        for m in raw_msgs:
            # 转换 created_at 字符串为 datetime
            try:
                dt = datetime.fromisoformat(m["created_at"])
            except ValueError:
                dt = datetime.now(timezone.utc)
                
            messages.append(Message(
                id=m["id"],
                role=m["role"],
                content=m["content"],
                created_at=dt,
                model=m.get("model"),
                meta=m.get("meta")
            ))
        return messages

    def build_messages(self, raw_messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        输入：前端传来的 messages (dict 格式)
        输出：可安全送入模型的 messages
        """
        messages = copy.deepcopy(raw_messages)

        # 1. 过滤无效消息
        messages = self._filter_dict_messages(messages)
        
        # 2. 注入 System Prompt
        messages = self._inject_system_prompt(messages)
        
        # 3. 裁剪
        messages = self._final_trim(messages, self.max_messages)

        return messages

    def build_llm_context(
        self,
        user_id: str,
        session_id: str,
        max_messages: Optional[int] = None,
        system_prompt: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        构造 LLM 上下文（核心逻辑）
        顺序：[System Prompt] -> [Memory] -> [Recent Messages]
        """
        limit = max_messages or self.max_messages
        active_system_prompt = system_prompt if system_prompt is not None else self.system_prompt
        
        # 1. 获取最近的历史消息
        raw_history = self.get_messages(user_id=user_id, session_id=session_id, limit=limit)
        
        # 2. 过滤无效消息
        filtered_history = self._filter_messages(raw_history)
        
        # 转换为 dict 格式，保持多模态内容结构
        msg_dicts = []
        for m in filtered_history:
            msg_dict = {"role": m.role}
            # 保持 content 的原始类型（字符串或列表）
            msg_dict["content"] = m.content
            logger.info(f"[ConversationManager] Converting message: role={m.role}, content_type={type(m.content).__name__}, content={str(m.content)[:100]}...")
            msg_dicts.append(msg_dict)
        
        # 3. 注入 System Prompt (确保在最前面)
        # 先移除已有的 system 消息，统一由 manager 控制注入
        msg_dicts = [m for m in msg_dicts if m["role"] != "system"]
        if active_system_prompt:
            msg_dicts.insert(0, {"role": "system", "content": active_system_prompt})
            
        # 4. 注入长期记忆 (Memory)
        # 推荐顺序：System -> Memory -> History
        if self.memory_injector:
            msg_dicts = self.memory_injector.inject(msg_dicts, user_id=user_id)
            
        # 5. 角色序列修复（确保 User/Assistant 交替）
        msg_dicts = self._fix_role_sequence(msg_dicts)

        # 6. 最终裁剪
        msg_dicts = self._final_trim(msg_dicts, limit)
        
        self._debug_log(msg_dicts)
        return msg_dicts

    # ----------------------------
    # 内部方法
    # ----------------------------

    def _filter_messages(self, messages: List[Message]) -> List[Message]:
        """过滤 Mock 回复和空内容"""
        filtered = []
        for m in messages:
            if m.role == "assistant" and isinstance(m.content, str) and m.content.startswith("🤖 MockModelAgent"):
                continue
            # 对于多模态内容（列表），不过滤；对于字符串，检查是否为空
            if isinstance(m.content, str) and not m.content.strip():
                continue
            filtered.append(m)
        return filtered

    def _filter_dict_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """过滤 dict 格式的无效消息，保留多模态内容"""
        filtered = []
        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            # 过滤 Mock 回复
            if role == "assistant" and isinstance(content, str) and content.startswith("🤖 MockModelAgent"):
                continue
            # 对于多模态内容（列表），保留；对于字符串，检查是否为空
            if isinstance(content, str) and not content.strip():
                continue
            # 保留多模态消息（content 是列表）和非空文本消息
            filtered.append(m)
        return filtered

    def _inject_system_prompt(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """注入 System Prompt"""
        if not self.system_prompt:
            return messages
        
        # 移除已有的 system 消息，确保唯一性
        others = [m for m in messages if m.get("role") != "system"]
        return [{"role": "system", "content": self.system_prompt}] + others

    def _fix_role_sequence(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        确保角色序列合法：
        1. 必须以 user 结尾（对于推理请求）
        2. 不能有连续的相同角色（除了 system）
        3. 如果有连续 user，合并它们
        """
        if not messages:
            return messages
            
        fixed = []
        for m in messages:
            if not fixed:
                fixed.append(m)
                continue
                
            prev = fixed[-1]
            if m["role"] == prev["role"] and m["role"] != "system":
                # 合并连续相同角色（多模态 content 为 list 时不合并）
                prev_content, curr_content = prev["content"], m["content"]
                if isinstance(prev_content, list) or isinstance(curr_content, list):
                    fixed.append(m)
                else:
                    prev["content"] = prev_content + f"\n\n{curr_content}"
            else:
                fixed.append(m)
        
        # 确保最后一条是 user (可选，部分模型强制要求)
        # if fixed[-1]["role"] != "user":
        #    pass 
            
        return fixed

    def _final_trim(self, messages: List[Dict[str, str]], limit: int) -> List[Dict[str, str]]:
        """
        保留：
        - system 消息（通常在开头）
        - 最近的 N 条消息
        """
        system_msgs = [m for m in messages if m["role"] == "system"]
        others = [m for m in messages if m["role"] != "system"]
        
        # 限制非 system 消息的数量
        trimmed_others = others[-limit:] if limit > 0 else []
        
        return system_msgs + trimmed_others

    def _debug_log(self, messages: List[Dict[str, str]]):
        roles = [m.get("role") for m in messages]
        logger.info(f"[ConversationManager] sending {len(messages)} messages: {roles}")
