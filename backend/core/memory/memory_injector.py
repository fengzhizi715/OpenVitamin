from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Literal

from log import logger
from core.memory.memory_item import MemoryItem
from core.memory.memory_store import MemoryStore

MessageDict = dict[str, str]
Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class MemoryInjectorConfig:
    mode: Literal["recent", "keyword", "vector"] = "recent"
    top_k: int = 5
    half_life_days: int = 30
    default_confidence: float = 0.6


class MemoryInjector:
    """
    记忆注入策略（MVP）

    - recent: 注入最近 top_k 条
    - keyword: 用最后一条 user 内容做 LIKE 检索（简单版）

    注入方式：在 system prompt 之后插入一个 system 消息，便于审计与可关闭。
    """

    def __init__(self, store: MemoryStore, config: MemoryInjectorConfig):
        self.store = store
        self.config = config

    def inject(self, messages: list[MessageDict], *, user_id: str) -> list[MessageDict]:
        try:
            top_k = max(0, min(self.config.top_k, 5))
            mems = self._select_memories(messages, user_id=user_id, top_k=top_k)
            if not mems:
                return messages

            # 仅注入 active，并按衰减策略重排
            mems = [m for m in mems if getattr(m, "status", "active") == "active"]
            mems.sort(key=self._score, reverse=True)
            mems = mems[:top_k]

            memory_msg = self._format_memory_message(mems)
            out: list[MessageDict] = []

            inserted = False
            for m in messages:
                out.append(m)
                if not inserted and m.get("role") == "system":
                    out.append({"role": "system", "content": memory_msg})
                    inserted = True

            if not inserted:
                # 如果没有 system 消息，直接 prepend
                out = [{"role": "system", "content": memory_msg}] + out

            # 更新 last_used_at（用于后续衰减/排序）
            try:
                self.store.touch_last_used(user_id=user_id, memory_ids=[m.id for m in mems])
            except Exception:
                pass

            logger.info(f"[MemoryInjector] injected {len(mems)} memories (mode={self.config.mode}, user_id={user_id})")
            logger.info(f"[MemoryInjector] injection content:\n{memory_msg}")
            return out
        except Exception as e:
            logger.error(f"[MemoryInjector] inject failed: {e}", exc_info=True)
            return messages

    def _select_memories(self, messages: list[MessageDict], *, user_id: str, top_k: int) -> list[MemoryItem]:
        if self.config.mode == "recent":
            return self.store.list_recent(user_id=user_id, limit=top_k)

        # keyword / vector 都需要 last user
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = (m.get("content") or "").strip()
                break
        if not last_user:
            return []

        if self.config.mode == "vector":
            return self.store.search_vector(user_id=user_id, query=last_user, limit=top_k)

        return self.store.search_like(user_id=user_id, query=last_user[:64], limit=top_k)

    @staticmethod
    def _format_memory_message(mems: list[MemoryItem]) -> str:
        lines = [
            "你将看到一些与用户相关的长期记忆（来自历史对话的客观提取）。",
            "使用这些信息来提升回答质量，但：",
            "- 不要编造未出现的细节",
            "- 如果记忆与本轮无关，请忽略",
            "",
            "长期记忆：",
        ]
        for m in mems:
            lines.append(f"- ({m.type}) {m.content}")
        return "\n".join(lines)

    def _score(self, m: MemoryItem) -> float:
        """
        衰减评分：confidence × decay(last_used_at/created_at) × type_weight
        """
        base = m.confidence if m.confidence is not None else self.config.default_confidence
        ts = m.last_used_at or m.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0)
        half = max(1.0, float(self.config.half_life_days))
        decay = math.exp(-math.log(2) * (age_days / half))

        type_w = {
            "preference": 1.20,
            "project": 1.10,
            "profile": 1.00,
            "fact": 0.85,
        }.get(m.type, 1.0)
        return float(base) * float(decay) * float(type_w)

