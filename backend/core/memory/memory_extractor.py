from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Tuple

from core.agents.router import get_router
from log import logger
from core.memory.memory_store import MemoryStore
from core.memory.memory_item import MemoryCandidate, MemoryType
from core.memory.key_schema import allowed_keys_markdown
from core.types import ChatCompletionRequest, Message


EXTRACTOR_SYSTEM_PROMPT = "\n".join(
    [
        "你是一个长期记忆提取器。",
        "",
        "请从以下对话中，提取：",
        "- 与用户长期偏好、背景、目标相关的信息",
        "- 用简短、客观、可复用的陈述句表达",
        "- 如果没有长期价值，返回空数组",
        "",
        allowed_keys_markdown(),
        "",
        "输出 JSON 数组：",
        "[",
        "  {",
        '    "type": "preference | profile | project | fact",',
        '    "key": "必须使用上面的规范 key（例如 preference.language）",',
        '    "value": "对应的稳定值（字符串）",',
        '    "content": "可选：人类可读的简短陈述句"',
        "  }",
        "]",
        "",
        "要求：",
        "- key/value 尽量填写，便于系统做确定性合并与冲突处理",
        "- 不得编造事实；不得重复已有记忆",
    ]
)


@dataclass(frozen=True)
class MemoryExtractorConfig:
    enabled: bool = False
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 256


class MemoryExtractor:
    """
    长期记忆提取器（能力模块）

    - 在“一轮对话完成后”运行：输入 (user_text, assistant_text)
    - 输出 0..N 条 MemoryItem（写入 MemoryStore）
    """

    def __init__(self, store: MemoryStore, config: MemoryExtractorConfig):
        self.store = store
        self.config = config

    async def extract_and_store(
        self,
        *,
        user_id: str,
        model_id: str,
        user_text: str,
        assistant_text: str,
        meta: Optional[dict[str, Any]] = None,
    ) -> int:
        if not self.config.enabled:
            return 0

        try:
            candidates = await self.extract(model_id=model_id, user_text=user_text, assistant_text=assistant_text)
            if not candidates:
                return 0
            created = self.store.add_candidates(candidates, user_id=user_id, source="memory_extractor", meta=meta)
            logger.info(f"[MemoryExtractor] stored {len(created)} memories")
            return len(created)
        except Exception as e:
            logger.error(f"[MemoryExtractor] extract/store failed: {e}", exc_info=True)
            return 0

    async def extract(self, *, model_id: str, user_text: str, assistant_text: str) -> List[MemoryCandidate]:
        # 跟随当前聊天模型（用户指定）
        agent = get_router().get_agent(model_id)

        dialog = f"""User:\n{user_text}\n\nAssistant:\n{assistant_text}"""
        req = ChatCompletionRequest(
            model=model_id,
            messages=[
                Message(role="system", content=EXTRACTOR_SYSTEM_PROMPT),
                Message(role="user", content=dialog),
            ],
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            max_tokens=self.config.max_tokens,
            stream=False,
        )

        raw = await agent.chat(req)
        parsed = self._parse_json_array(raw)
        return self._validate_items(parsed)

    @staticmethod
    def _parse_json_array(text: str) -> list:
        if not text:
            return []
        s = text.strip()

        # 去掉可能的 ```json ... ``` 包裹
        if s.startswith("```"):
            # 找到第一个换行后开始
            first_nl = s.find("\n")
            if first_nl != -1:
                s = s[first_nl + 1 :]
            if s.endswith("```"):
                s = s[:-3].strip()

        # 找 [] 的最大包围
        l = s.find("[")
        r = s.rfind("]")
        if l != -1 and r != -1 and r > l:
            s = s[l : r + 1]

        try:
            data = json.loads(s)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    @staticmethod
    def _validate_items(items: Iterable[Any]) -> List[MemoryCandidate]:
        out: List[MemoryCandidate] = []
        allowed = {"preference", "profile", "project", "fact"}
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("type")
            if not isinstance(t, str) or t not in allowed:
                continue
            key = it.get("key")
            value = it.get("value")
            content = it.get("content")
            conf = it.get("confidence")

            key = key.strip() if isinstance(key, str) else None
            value = value.strip() if isinstance(value, str) else None
            content = content.strip() if isinstance(content, str) else None
            if isinstance(conf, (int, float)):
                conf = float(conf)
            else:
                conf = None

            # 兼容旧格式：{type, content}
            if not content:
                legacy_content = it.get("content")
                if isinstance(legacy_content, str) and legacy_content.strip():
                    content = legacy_content.strip()

            # 如果没有 content，生成一个可读陈述句
            if not content:
                if key and value:
                    content = f"{key} = {value}"
                else:
                    continue

            out.append(
                MemoryCandidate(
                    type=t,
                    key=key,
                    value=value,
                    content=content,
                    confidence=conf,
                )
            )
        return out

