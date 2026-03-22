"""
Web Search tool: real search via DuckDuckGo (default) or Serper API.
Controlled by settings.tool_net_web_enabled and optional web_search_serper_api_key.
"""
from __future__ import annotations

import asyncio
import re
from typing import Dict, Any, List

from config.settings import settings
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult
from core.tools.schemas import create_input_schema
from log import logger


def _build_query_candidates(original_query: str) -> List[str]:
    """
    Deterministic query refinement for ambiguous keywords.

    Prefer official sources first for "updates/news" queries.
    """
    q = (original_query or "").strip()
    ql = q.lower()
    if not q:
        return [""]

    # Cursor is highly ambiguous; prioritize official sources first.
    if "cursor" in ql:
        # Respect explicit site hints.
        if "site:" in ql:
            return [q]

        base_terms = "cursor release notes changelog update"
        candidates = [
            f"site:cursor.com {base_terms}",
            f"site:docs.cursor.com {base_terms}",
            f"site:github.com/getcursor {base_terms}",
            # Fallback: general query with disambiguation terms
            f"{q} Cursor AI code editor release notes changelog update",
        ]

        # De-dup while preserving order
        seen: set[str] = set()
        out: List[str] = []
        for c in candidates:
            c = re.sub(r"\s+", " ", c).strip()
            if not c or c in seen:
                continue
            seen.add(c)
            out.append(c)
        return out or [q]

    return [q]


def _search_duckduckgo_sync(query: str, top_k: int) -> List[Dict[str, str]]:
    """Synchronous DuckDuckGo text search. Run in thread to avoid blocking."""
    logger.info(f"[web.search] DuckDuckGo: start query={query!r} max_results={top_k}")
    try:
        # Prefer the newer `ddgs` package (duckduckgo-search is renamed and may fail with "Document is empty").
        try:
            from ddgs.ddgs import DDGS  # type: ignore
            provider = "ddgs"
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore
            provider = "duckduckgo_search"
    except ImportError as e:
        logger.warning(f"[web.search] DuckDuckGo: import failed: {e}")
        raise RuntimeError(
            f"ddgs/duckduckgo-search is not installed or failed to import: {e}. "
            "Recommended: pip install ddgs (fallback: pip install duckduckgo-search)"
        ) from e
    results: List[Dict[str, str]] = []
    try:
        logger.info(f"[web.search] DuckDuckGo provider={provider} query={query!r}")
        # ddgs supports `timeout` (seconds); duckduckgo_search may not. Use kwargs defensively.
        try:
            ddgs_ctx = DDGS(timeout=8)  # type: ignore[arg-type]
        except TypeError:
            ddgs_ctx = DDGS()  # type: ignore[call-arg]
        with ddgs_ctx as ddgs:
            for r in ddgs.text(query, max_results=min(top_k, 20)):
                results.append({
                    "title": (r.get("title") or "").strip(),
                    "snippet": (r.get("body") or r.get("snippet") or "").strip(),
                    "url": (r.get("href") or r.get("link") or "").strip(),
                })
                if len(results) >= top_k:
                    break
        logger.info(f"[web.search] DuckDuckGo: done query={query!r} got={len(results)}")
    except Exception as e:
        logger.warning(f"[web.search] DuckDuckGo search failed: {e}")
        raise
    return results


async def _search_serper(query: str, top_k: int, api_key: str) -> List[Dict[str, str]]:
    """Serper (Google) search via API."""
    logger.info(f"[web.search] Serper: start query={query!r} num={top_k}")
    try:
        import httpx
    except ImportError:
        raise RuntimeError("httpx is required for Serper. Run: pip install httpx")
    url = "https://google.serper.dev/search"
    payload = {"q": query, "num": min(top_k, 20)}
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    results: List[Dict[str, str]] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    for item in (data.get("organic") or data.get("results") or [])[:top_k]:
        results.append({
            "title": (item.get("title") or "").strip(),
            "snippet": (item.get("snippet") or "").strip(),
            "url": (item.get("link") or "").strip(),
        })
    logger.info(f"[web.search] Serper: done query={query!r} got={len(results)}")
    return results


class WebSearchTool(Tool):
    @property
    def name(self) -> str:
        return "web.search"

    @property
    def description(self) -> str:
        return "Search the web for information."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return create_input_schema({
            "query": {"type": "string", "description": "The search query."},
            "top_k": {"type": "integer", "description": "Number of results to return.", "default": 5}
        }, required=["query"])

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "snippet": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["title", "snippet", "url"],
            },
        }

    @property
    def required_permissions(self):
        return ["net.web"]

    @property
    def ui_hint(self) -> Dict[str, Any]:
        return {
            "display_name": "Web Search",
            "icon": "Globe",
            "category": "web",
            "permissions_hint": [
                {"key": "net.web", "label": "Requires network access (web)."}
            ],
        }

    def _mock_results(self, query: str, top_k: int) -> List[Dict[str, str]]:
        return [
            {
                "title": f"Result {i} for {query}",
                "snippet": f"This is a snippet for search result {i} related to '{query}'.",
                "url": f"https://example.com/result-{i}",
            }
            for i in range(1, top_k + 1)
        ]

    async def run(self, input_data: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        # Defense-in-depth: Check permissions even though ToolRegistry should have checked
        required_perms = self.required_permissions
        if required_perms:
            missing = [p for p in required_perms if not ctx.permissions.get(p)]
            if missing:
                logger.warning(f"[web.search] Permission check failed in tool.run(): missing {missing}")
                return ToolResult(success=False, data=None, error=f"Permission denied: missing {missing}")
                
        query = (input_data.get("query") or "").strip()
        top_k = min(int(input_data.get("top_k") or 5), 20)
        if top_k < 1:
            top_k = 5

        trace_id = getattr(ctx, "trace_id", "") or ""
        logger.info(
            "[web.search] run start trace_id=%s query=%r top_k=%s",
            trace_id, query, top_k,
        )

        # Real search only when explicitly enabled (default in settings is True; override via env TOOL_NET_WEB_ENABLED=false).
        enabled = getattr(settings, "tool_net_web_enabled", True)
        if not enabled:
            logger.warning(
                "[web.search] Web search disabled (tool_net_web_enabled=False). "
                "Set TOOL_NET_WEB_ENABLED=true and restart backend for real search."
            )
            err_msg = (
                "Web search is disabled (mock). 联网搜索未开启。"
                " Set TOOL_NET_WEB_ENABLED=true in backend .env or config and restart. "
                "请在后端 .env 或 config 中设置 TOOL_NET_WEB_ENABLED=true 并重启后端。"
            )
            logger.info("[web.search] run end trace_id=%s mock=True returning error", trace_id)
            return ToolResult(success=False, error=err_msg, data=[])

        # Real search: Serper if API key set, else DuckDuckGo
        serper_key = (getattr(settings, "web_search_serper_api_key", None) or "").strip()
        backend = "serper" if serper_key else "duckduckgo"
        candidates = _build_query_candidates(query)
        if candidates and candidates[0] != query:
            logger.info("[web.search] query refined original=%r candidates=%r", query, candidates)
        else:
            logger.info("[web.search] real search backend=%s query=%r", backend, query)
        try:
            merged: List[Dict[str, str]] = []
            seen_urls: set[str] = set()

            async def _run_one(q: str, k: int) -> List[Dict[str, str]]:
                if serper_key:
                    return await _search_serper(q, k, serper_key)
                return await asyncio.to_thread(_search_duckduckgo_sync, q, k)

            for idx, q in enumerate(candidates, start=1):
                if not q:
                    continue
                remaining = top_k - len(merged)
                if remaining <= 0:
                    break
                logger.info("[web.search] attempt %s/%s query=%r remaining=%s", idx, len(candidates), q, remaining)
                batch = await _run_one(q, min(max(remaining, 3), 10))
                logger.info("[web.search] attempt %s got=%s", idx, len(batch))

                for item in batch:
                    url = (item.get("url") or "").strip()
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    merged.append(item)
                    if len(merged) >= top_k:
                        break

            results = merged
            logger.info(
                "[web.search] run end trace_id=%s success=True backend=%s results=%s",
                trace_id, backend, len(results),
            )
            if results:
                first = results[0]
                first_title = (first.get("title") or "")[:80]
                first_url = (first.get("url") or first.get("href") or "")[:80]
                logger.info(
                    "[web.search] results preview first_title=%r first_url=%s",
                    first_title, first_url,
                )
            if not results:
                return ToolResult(success=True, data=[])
            return ToolResult(success=True, data=results)
        except Exception as e:
            logger.warning(
                "[web.search] run end trace_id=%s success=False backend=%s error=%s",
                trace_id, backend, e,
            )
            hint = " If DuckDuckGo is blocked in your region, set WEB_SEARCH_SERPER_API_KEY in .env for Google search via Serper."
            return ToolResult(
                success=False,
                error=f"Web search failed: {e}.{hint}",
                data=[],
            )
