import time
import uuid
import asyncio
import json
import hashlib
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from log import logger, log_structured
from core.types import Message, ChatCompletionRequest
from .definition import AgentDefinition
from .session import AgentSession, get_agent_session_store
from .parser import parse_llm_output, AgentAction
from .context import build_prompt
from .trace import AgentTraceEvent, get_agent_trace_store
from .executor import AgentExecutor
from .rag import get_rag_retrieval
from core.skills.registry import SkillRegistry


class AgentLoop:
    """
    智能体核心执行循环 (Agent Loop v1)
    """
    def __init__(self, executor: AgentExecutor):
        self.executor = executor
        self.session_store = get_agent_session_store()
        self.trace_store = get_agent_trace_store()
        self.rag_retrieval = get_rag_retrieval()
        # RAG cache: {session_id: {query_hash: (timestamp, context)}}
        self._rag_cache: Dict[str, Dict[str, tuple]] = {}
        self._cache_ttl = 300  # 5 minutes cache TTL
        
    def _get_cached_rag_context(self, session_id: str, query: str, rag_ids: List[str]) -> Optional[str]:
        """Get cached RAG context if available and not expired"""
        if session_id not in self._rag_cache:
            return None
            
        # Create cache key from query and RAG IDs
        cache_key = hashlib.md5(f"{query}:{sorted(rag_ids)}".encode()).hexdigest()
        
        if cache_key not in self._rag_cache[session_id]:
            return None
            
        timestamp, context = self._rag_cache[session_id][cache_key]
        
        # Check if cache is expired
        if time.time() - timestamp > self._cache_ttl:
            del self._rag_cache[session_id][cache_key]
            return None
            
        logger.info(f"[AgentLoop] Using cached RAG context for query")
        return context
        
    def _set_cached_rag_context(self, session_id: str, query: str, rag_ids: List[str], context: str):
        """Cache RAG context"""
        if session_id not in self._rag_cache:
            self._rag_cache[session_id] = {}
            
        cache_key = hashlib.md5(f"{query}:{sorted(rag_ids)}".encode()).hexdigest()
        self._rag_cache[session_id][cache_key] = (time.time(), context)
        logger.info(f"[AgentLoop] Cached RAG context for query")

    def _try_recover_vision_call(
        self,
        session: AgentSession,
        agent: AgentDefinition,
        workspace: str,
        raw_output: str,
    ) -> Optional[AgentAction]:
        """
        当 LLM 输出无法解析为 JSON 时，尝试恢复为 vision.detect_objects 调用。

        恢复策略（确定性优先）：
        - 若当前 workspace 内存在图片文件，且 Agent 启用了 builtin_vision.detect_objects
        - 且用户消息包含上传文件提示（我们注入的 hint），或 raw_output 看起来在做图片分析
        则自动选择 workspace 中第一个图片文件，构造 skill_call。
        """
        vision_skill = "builtin_vision.detect_objects"
        if vision_skill not in (agent.enabled_skills or []):
            return None

        # 若已经有成功的 YOLO 观测结果，则不要再次通过 recovery 触发 YOLO（避免重复跑）
        if self._find_latest_vision_observation(session) is not None:
            return None

        # 获取 workspace 内首个图像文件
        ws_path = Path(workspace) if workspace and workspace != "." else None
        if not ws_path or not ws_path.is_dir():
            return None
        img_ext = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        first_img_name: Optional[str] = None
        for f in ws_path.iterdir():
            if f.is_file() and f.suffix.lower() in img_ext:
                first_img_name = f.name
                break
        if not first_img_name:
            return None

        # 判断是否确实是“上传图片并要求分析”的场景
        last_user_text = ""
        for msg in reversed(session.messages):
            if msg.role == "user" and (msg.content or "").strip():
                last_user_text = msg.content
                break

        # 1) 我们注入的上传提示（强信号）
        has_upload_hint = (
            "[Files saved to workspace" in last_user_text
            or "[Files have been saved to the current workspace" in last_user_text
            or "Files saved to workspace" in last_user_text
        )
        # 2) 输出或用户文本包含视觉分析意图（弱信号）
        intent_keywords = ("分析", "图片", "图像", "视觉", "vision", "analyze", "image", "detect", "解释")
        has_intent = any(k in (raw_output or "") for k in intent_keywords) or any(k in (last_user_text or "") for k in intent_keywords)

        # 如果是 step=0 + 有上传 hint，我们直接恢复调用（不依赖模型输出质量）
        if session.step == 0 and has_upload_hint:
            logger.info(
                f"[AgentLoop] Recovered vision.detect_objects call (upload hint) image={first_img_name}"
            )
            return AgentAction(type="skill_call", skill_id=vision_skill, input={"image": first_img_name})

        # 否则要求有意图关键词再恢复
        if not has_intent:
            return None

        logger.info(f"[AgentLoop] Recovered vision.detect_objects call from parse failure, image={first_img_name}")
        return AgentAction(type="skill_call", skill_id=vision_skill, input={"image": first_img_name})

    def _extract_last_tool_observation_payload(self, session: AgentSession) -> Optional[Dict[str, Any]]:
        """
        从 session.messages 中提取最近一次 tool 观测的 JSON payload。

        期望格式（AgentLoop 追加的 tool message）：
        Skill result (observation):
        ```json
        {...}
        ```
        """
        for msg in reversed(session.messages):
            if msg.role != "tool":
                continue
            text = (msg.content or "").strip()
            # NOTE: 使用 \s 匹配空白；不要写成 \\s（那会匹配字面量 '\s' 导致无法命中）
            m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
            if not m:
                continue
            raw = m.group(1).strip()
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        return None

    def _find_latest_skill_observation_payload(self, session: AgentSession, skill_id: str) -> Optional[Dict[str, Any]]:
        """向后查找最近一次指定 skill_id 的 tool observation payload。"""
        # Prefer structured state if present
        state = getattr(session, "state", None) or {}
        last_map = state.get("last_skill_observation") if isinstance(state, dict) else None
        if isinstance(last_map, dict):
            payload = last_map.get(skill_id)
            if isinstance(payload, dict):
                return payload
        for msg in reversed(session.messages):
            if msg.role != "tool":
                continue
            text = (msg.content or "").strip()
            m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
            if not m:
                continue
            raw = m.group(1).strip()
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("skill_id") == skill_id:
                return data
        return None

    def _find_latest_vision_observation(self, session: AgentSession) -> Optional[Dict[str, Any]]:
        """
        返回最近一次成功的 vision.detect_objects 观测 payload（包含 output.objects 列表），
        用于去重/收敛，避免重复跑 YOLO。
        """
        payload = self._find_latest_skill_observation_payload(session, "builtin_vision.detect_objects")
        if not payload:
            return None
        out = payload.get("output")
        ok = payload.get("ok", True)
        if ok and isinstance(out, dict) and isinstance(out.get("objects"), list):
            return payload
        return None

    @staticmethod
    def _vision_cache_key(
        image: str,
        backend: Optional[str],
        confidence_threshold: Optional[float],
        model_id: Optional[str],
        image_signature: Optional[str],
    ) -> str:
        b = (backend or "default").strip()
        ct = f"{confidence_threshold:.4f}" if isinstance(confidence_threshold, (int, float)) else "default"
        mid = (model_id or "").strip()
        sig = (image_signature or "").strip()
        return f"{image}|{sig}|{b}|{ct}|{mid}"

    def _find_latest_vlm_observation(self, session: AgentSession) -> Optional[Dict[str, Any]]:
        """
        返回最近一次成功的 vlm.generate 观测 payload（包含 output.text），
        用于去重/收敛。
        """
        payload = self._find_latest_skill_observation_payload(session, "builtin_vlm.generate")
        if not payload:
            return None
        out = payload.get("output")
        ok = payload.get("ok", True)
        if ok and isinstance(out, dict) and isinstance(out.get("text"), str):
            return payload
        return None

    @staticmethod
    def _is_ocr_agent(agent: AgentDefinition) -> bool:
        """
        Heuristic: only enable OCR-specific guardrails for OCR-like agents.
        This keeps coupling low and avoids impacting other agents.
        """
        try:
            parts = [
                str(getattr(agent, "name", "") or ""),
                str(getattr(agent, "description", "") or ""),
                str(getattr(agent, "system_prompt", "") or ""),
            ]
            blob = " ".join(parts).lower()
        except Exception:
            return False
        keywords = [
            "ocr",
            "文字识别",
            "识别文字",
            "识别文本",
            "text recognition",
            "extract text",
        ]
        return any(k in blob for k in keywords)

    @staticmethod
    def _clean_user_prompt_for_vlm(text: str) -> str:
        """
        Extract a clean user query for VLM prompts.
        - Remove upload hints like [Files saved to workspace...]
        - Remove attachment markers like [File 1: ...] / [Attachments: ...]
        - Keep only human question text
        """
        if not isinstance(text, str):
            return ""
        s = text.strip()
        if not s:
            return ""
        lines: List[str] = []
        for raw in s.splitlines():
            line = (raw or "").rstrip()
            t = line.strip()
            if not t:
                lines.append("")
                continue
            if t.startswith("[") and t.endswith("]"):
                continue
            tl = t.lower()
            if tl.startswith("[file ") or tl.startswith("[attachments"):
                continue
            if "files saved to workspace" in tl:
                continue
            lines.append(line)
        # compact excessive blank lines
        out_lines: List[str] = []
        prev_blank = False
        for line in lines:
            blank = not (line or "").strip()
            if blank and prev_blank:
                continue
            out_lines.append(line)
            prev_blank = blank
        cleaned = "\n".join(out_lines).strip()
        return cleaned or s

    @staticmethod
    def _summarize_yolo_objects(output: Dict[str, Any]) -> str:
        """将 YOLO 输出摘要为简短文本（用于 VLM prompt）。"""
        objects = output.get("objects") if isinstance(output, dict) else None
        if not isinstance(objects, list) or not objects:
            return "YOLO 未检测到明显目标。"
        counts: Dict[str, int] = {}
        for o in objects:
            if not isinstance(o, dict):
                continue
            label = str(o.get("label") or "unknown")
            counts[label] = counts.get(label, 0) + 1
        # Top-N by confidence
        top_items: List[str] = []
        try:
            sorted_by_conf = sorted(
                [o for o in objects if isinstance(o, dict)],
                key=lambda x: float(x.get("confidence", 0.0)),
                reverse=True,
            )
            for o in sorted_by_conf[:5]:
                top_items.append(f"{o.get('label','unknown')}({float(o.get('confidence',0.0)):.2f})")
        except Exception:
            pass
        parts = []
        parts.append("检测到的对象统计：" + "，".join([f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]))
        if top_items:
            parts.append("最高置信度示例：" + "，".join(top_items))
        return "；".join(parts)

    @staticmethod
    def _record_skill_observation(
        session: AgentSession,
        *,
        skill_id: str,
        input_data: Dict[str, Any],
        output_data: Any,
        ok: bool,
        error: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        state = getattr(session, "state", None) or {}
        last_map = state.get("last_skill_observation")
        if not isinstance(last_map, dict):
            last_map = {}
        last_map[skill_id] = {
            "skill_id": skill_id,
            "input": input_data,
            "output": output_data,
            "ok": ok,
            "error": error,
            "meta": meta or {},
        }
        state["last_skill_observation"] = last_map
        session.state = state

    @staticmethod
    def _image_signature(workspace: str, image_name: str) -> Optional[str]:
        """
        为 workspace 内图片生成签名（size + mtime_ns），用于去重判断。
        """
        try:
            if not image_name or image_name.startswith("data:image/"):
                return None
            ws = Path(workspace) if workspace and workspace != "." else Path(".")
            p = Path(image_name)
            if not p.is_absolute():
                p = (ws / image_name)
            p = p.resolve()
            if not p.is_file():
                return None
            st = p.stat()
            return f"{st.st_size}:{st.st_mtime_ns}"
        except Exception:
            return None

    async def _run_vlm_after_yolo(
        self,
        *,
        session: AgentSession,
        agent: AgentDefinition,
        workspace: str,
        image_name: str,
        yolo_output: Dict[str, Any],
    ) -> Optional[str]:
        """
        YOLO 后自动调用 VLM（若启用 builtin_vlm.generate），并返回生成文本。
        返回 None 表示不执行或执行失败。
        """
        if "builtin_vlm.generate" not in (agent.enabled_skills or []):
            return None

        # 去重：若已存在 VLM 观测且 image 相同，则直接复用
        cached_vlm = self._find_latest_vlm_observation(session)
        if cached_vlm:
            cached_in = cached_vlm.get("input") if isinstance(cached_vlm.get("input"), dict) else {}
            cached_image = (cached_in.get("image") or "").strip() if isinstance(cached_in, dict) else ""
            if cached_image and cached_image == image_name:
                out = cached_vlm.get("output") if isinstance(cached_vlm, dict) else None
                if isinstance(out, dict) and isinstance(out.get("text"), str):
                    return out.get("text")

        # 构造 VLM prompt：用户问题 + YOLO 摘要
        last_user_text = ""
        for msg in reversed(session.messages):
            if msg.role == "user" and (msg.content or "").strip():
                last_user_text = msg.content
                break
        user_q = self._clean_user_prompt_for_vlm(last_user_text) or "请描述图像内容。"
        yolo_summary = self._summarize_yolo_objects(yolo_output or {})
        prompt = (
            "请基于图像内容与检测结果进行解释，不要编造检测结果中不存在的对象。\n"
            f"用户问题：{user_q}\n"
            f"检测结果摘要：{yolo_summary}\n"
            "请用自然语言回答用户问题，简洁清晰。"
        )

        # 调用 VLM 生成
        skill_id = "builtin_vlm.generate"
        skill_start_time = time.time()
        try:
            result = await self.executor.execute_skill(
                skill_id=skill_id,
                inputs={
                    "model_id": agent.model_id,
                    "image": image_name,
                    "prompt": prompt,
                    "temperature": agent.temperature,
                },
                agent_id=agent.agent_id,
                trace_id=f"{session.trace_id}:{session.step}:{skill_id}",
                workspace=workspace,
                permissions={"file.read": True},
            )
            tool_result = result.get("output")
            if result.get("error") and tool_result is None:
                tool_result = f"Error: {result['error']}"

            session.messages.append(
                Message(role="assistant", content=f"Calling skill `{skill_id}`.")
            )
            safe_payload = {
                "skill_id": skill_id,
                "input": {
                    "model_id": agent.model_id,
                    "image": image_name,
                    "prompt": prompt,
                    "temperature": agent.temperature,
                },
                "output": self._sanitize_tool_output_for_prompt(tool_result),
            }
            session.messages.append(
                Message(
                    role="tool",
                    content="Skill result (observation):\n```json\n"
                    + json.dumps(safe_payload, ensure_ascii=False, default=str)
                    + "\n```",
                )
            )
            skill_duration_ms = int((time.time() - skill_start_time) * 1000)
            # 确保 input_data 和 output_data 是字典类型
            input_data = safe_payload.get("input") if isinstance(safe_payload.get("input"), dict) else {"input": safe_payload.get("input")}
            output_data = tool_result if isinstance(tool_result, dict) else {"result": tool_result}
            self.trace_store.record_event(AgentTraceEvent(
                trace_id=session.trace_id,
                event_id=f"atev_{uuid.uuid4().hex[:16]}",
                session_id=session.session_id,
                step=session.step,
                event_type="skill_call",
                agent_id=agent.agent_id,
                tool_id=skill_id,
                input_data=input_data,
                output_data=output_data,
                duration_ms=skill_duration_ms,
            ))
            if isinstance(tool_result, dict) and isinstance(tool_result.get("text"), str):
                return tool_result.get("text")
        except Exception as e:
            logger.error(f"[AgentLoop] VLM generate failed: {e}")
        return None

    @staticmethod
    def _first_workspace_image(workspace: str) -> Optional[str]:
        """返回 workspace 内第一张图片文件名（仅文件名），不存在则返回 None。"""
        ws_path = Path(workspace) if workspace and workspace != "." else None
        if not ws_path or not ws_path.is_dir():
            return None
        img_ext = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        for f in ws_path.iterdir():
            if f.is_file() and f.suffix.lower() in img_ext:
                return f.name
        return None

    def _autofill_image_param(self, inputs: Dict[str, Any], session: AgentSession, workspace: str, skill_id: str) -> Dict[str, Any]:
        """
        自动补全 image 参数的公共方法。
        优先使用最近上传的图片，否则从 workspace 选择第一张图片。
        """
        if not isinstance(inputs, dict):
            inputs = {}
        if not (inputs.get("image") or "").strip():
            last_img = self._last_uploaded_image(session)
            if last_img:
                inputs = {**inputs, "image": last_img}
                logger.info(f"[AgentLoop] Autofill {skill_id} image={last_img} (last uploaded)")
            else:
                ws_path = Path(workspace) if workspace and workspace != "." else None
                if ws_path and ws_path.is_dir():
                    img_ext = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
                    for f in ws_path.iterdir():
                        if f.is_file() and f.suffix.lower() in img_ext:
                            inputs = {**inputs, "image": f.name}
                            logger.info(f"[AgentLoop] Autofill {skill_id} image={f.name} (model omitted required arg)")
                            break
        else:
            # 如果本次请求上传了新图片，避免模型继续引用旧图片
            state = getattr(session, "state", None) or {}
            last_uploaded = state.get("last_uploaded_image") if isinstance(state, dict) else None
            last_list = state.get("last_uploaded_images") if isinstance(state, dict) else None
            if isinstance(last_uploaded, str) and last_uploaded:
                if isinstance(last_list, list) and inputs.get("image") not in last_list:
                    inputs = {**inputs, "image": last_uploaded}
                    logger.info(f"[AgentLoop] Override {skill_id} image to last uploaded: {last_uploaded}")
        return inputs

    @staticmethod
    def _last_uploaded_image(session: AgentSession) -> Optional[str]:
        state = getattr(session, "state", None) or {}
        if isinstance(state, dict):
            name = state.get("last_uploaded_image")
            if isinstance(name, str) and name.strip():
                return name.strip()
        return None

    @staticmethod
    def _sanitize_tool_output_for_prompt(output: Any) -> Any:
        """
        对写入到 session.messages 的 tool observation 做瘦身，避免把超长字段（如 base64 图片）塞爆上下文。
        注意：trace 中仍保留完整 output_data，这里只影响 LLM prompt。
        """
        try:
            if isinstance(output, dict):
                out = dict(output)
                if "annotated_image" in out and isinstance(out["annotated_image"], str):
                    s = out["annotated_image"]
                    if s.startswith("data:image/"):
                        out["annotated_image"] = "(base64 omitted; see trace for preview)"
                        out["annotated_image_available"] = True
                for k, v in list(out.items()):
                    if isinstance(v, str) and len(v) > 2000:
                        out[k] = v[:2000] + "…(truncated)"
                return out
            if isinstance(output, str) and len(output) > 4000:
                return output[:4000] + "…(truncated)"
            return output
        except Exception:
            return output

    def _try_recover_final_from_last_tool(self, session: AgentSession) -> Optional[AgentAction]:
        """
        当模型在“已经有工具观测结果”的情况下仍输出非 JSON，兜底生成一个可用的 final。
        目前仅针对 vision.detect_objects 的输出做确定性总结。
        """
        # 优先使用最近一次成功的 vision.detect_objects 观测（不要求它一定是“最后一条 tool 消息”）
        payload = self._find_latest_vision_observation(session) or self._extract_last_tool_observation_payload(session)
        if not payload:
            return None
        skill_id = payload.get("skill_id")
        out = payload.get("output") if isinstance(payload, dict) else None
        if skill_id != "builtin_vision.detect_objects" or not isinstance(out, dict):
            return None

        objects = out.get("objects")
        if not isinstance(objects, list):
            return None

        annotated = out.get("annotated_image")
        has_annotated = isinstance(annotated, str) and annotated.startswith("data:image/")

        if len(objects) == 0:
            answer = "YOLO 未检测到明显的目标。"
            if has_annotated:
                answer += "（已生成标注图：无框标注。）"
            return AgentAction(type="final", answer=answer)

        # 简单汇总：按 label 计数，列出置信度最高的几个
        counts: Dict[str, int] = {}
        top_items: List[str] = []
        for o in objects:
            if not isinstance(o, dict):
                continue
            label = str(o.get("label") or "unknown")
            counts[label] = counts.get(label, 0) + 1
        # top 置信度
        try:
            sorted_by_conf = sorted(
                [o for o in objects if isinstance(o, dict)],
                key=lambda x: float(x.get("confidence", 0.0)),
                reverse=True,
            )
            for o in sorted_by_conf[:5]:
                top_items.append(f"{o.get('label','unknown')}（{float(o.get('confidence',0.0)):.2f}）")
        except Exception:
            pass

        parts = []
        parts.append(f"YOLO 检测到 {len(objects)} 个目标。")
        parts.append("按类别计数：" + "，".join([f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]))
        if top_items:
            parts.append("最高置信度示例：" + "，".join(top_items))
        if has_annotated:
            parts.append("已生成标注图。")
        return AgentAction(type="final", answer="\n".join(parts))

    async def run(self, session: AgentSession, agent: AgentDefinition, workspace: str = ".") -> AgentSession:
        """
        运行智能体循环。workspace 为 file.read / file.list 等工作目录，默认 "."。
        """
        run_start = time.perf_counter()
        # 确保 session 级 trace_id 存在（用于关联所有事件）
        if not getattr(session, "trace_id", None):
            session.trace_id = f"atrace_{uuid.uuid4().hex[:16]}"

        session.status = "running"
        self.session_store.save_session(session)
        log_structured(
            "AgentLoop", "run_start",
            agent_id=agent.agent_id, session_id=getattr(session, "session_id", ""),
            trace_id=session.trace_id, workspace=(workspace or ".")[:200],
        )

        try:
            while session.step < agent.max_steps:
                log_structured("AgentLoop", "step_start", agent_id=agent.agent_id, session_id=getattr(session, "session_id", ""), step=session.step)
                # 1. 获取可用 Skill 列表（v1.5: Agent 只可见 Skill）
                skills = SkillRegistry.list_for_agent(agent.enabled_skills, enabled_only=True)
                tools = [
                    {"name": s.name, "description": s.description, "input_schema": s.input_schema, "skill_id": s.id}
                    for s in skills
                ]
                
                # 2. 组装提示词
                # RAG 检索优化：仅在第一步或显式需要时检索，使用缓存避免重复检索
                rag_context = ""
                if agent.rag_ids and len(agent.rag_ids) > 0:
                    try:
                        # 获取用户最后的查询内容作为检索查询
                        last_user_query = ""
                        for msg in reversed(session.messages):
                            if msg.role == "user":
                                last_user_query = msg.content
                                break
                        
                        if last_user_query:
                            # 检查缓存
                            session_id = getattr(session, "session_id", "unknown")
                            cached_context = self._get_cached_rag_context(session_id, last_user_query, agent.rag_ids)
                            
                            if cached_context is not None:
                                rag_context = cached_context
                            elif session.step == 0:  # 仅在第一步进行检索
                                rag_context = await self.rag_retrieval.retrieve_context(
                                    query=last_user_query,
                                    knowledge_base_ids=agent.rag_ids,
                                    top_k=5
                                )
                                if rag_context:
                                    # 缓存检索结果
                                    self._set_cached_rag_context(session_id, last_user_query, agent.rag_ids, rag_context)
                                    logger.info(f"[AgentLoop] Retrieved and cached RAG context ({len(rag_context)} chars) from {len(agent.rag_ids)} knowledge bases")
                            else:
                                logger.debug(f"[AgentLoop] Skipping RAG retrieval on step {session.step} (not first step and no cache)")
                    except Exception as e:
                        logger.warning(f"[AgentLoop] RAG context retrieval failed: {e}")
                
                messages = build_prompt(
                    system_prompt=agent.system_prompt,
                    name=agent.name,
                    description=agent.description,
                    conversation=session.messages,
                    tools=tools,
                    rag_context=rag_context,
                    enabled_skills=agent.enabled_skills or []
                )

                # 3. 调用 LLM
                start_time = time.time()
                try:
                    llm_output = await self.executor.llm_call(
                        model_id=agent.model_id,
                        messages=messages,
                        temperature=agent.temperature,
                        model_params=getattr(agent, 'model_params', None),
                        # V2.8: Pass observability metadata
                        session_id=getattr(session, "session_id", ""),
                        trace_id=session.trace_id,
                        agent_id=agent.agent_id,
                    )
                except Exception as e:
                    log_structured("AgentLoop", "llm_call_failed", agent_id=agent.agent_id, session_id=getattr(session, "session_id", ""), step=session.step, error=str(e)[:200])
                    logger.error(f"[AgentLoop] LLM call failed: {e}")
                    session.status = "error"
                    session.error_message = f"LLM call failed: {str(e)}"
                    self.session_store.save_session(session)
                    break
                
                duration_ms = int((time.time() - start_time) * 1000)
                log_structured(
                    "AgentLoop", "llm_call_done",
                    agent_id=agent.agent_id, session_id=getattr(session, "session_id", ""), step=session.step,
                    duration_ms=duration_ms, model_id=agent.model_id or "",
                )

                # 记录 LLM Trace
                self.trace_store.record_event(AgentTraceEvent(
                    trace_id=session.trace_id,
                    event_id=f"atev_{uuid.uuid4().hex[:16]}",
                    session_id=session.session_id,
                    step=session.step,
                    event_type="llm_request",
                    agent_id=agent.agent_id,
                    model_id=agent.model_id,
                    input_data={"messages": [m.model_dump() for m in messages]},
                    output_data={"content": llm_output} if isinstance(llm_output, str) else llm_output,
                    duration_ms=duration_ms
                ))

                # 4. 解析输出（使用严格模式）
                try:
                    action = parse_llm_output(llm_output, strict_mode=True)
                except Exception as e:
                    # 解析失败：若已有工具观测结果，优先兜底生成 final（避免重复跑工具造成死循环）
                    recovered_final = self._try_recover_final_from_last_tool(session)
                    if recovered_final is not None:
                        action = recovered_final
                        logger.info(f"[AgentLoop] Using recovered final from last tool (parse failed: {e})")
                    else:
                        # 否则尝试恢复 vision.detect_objects（上传图片场景）
                        recovered = self._try_recover_vision_call(session, agent, workspace, llm_output)
                        if recovered is not None:
                            action = recovered
                            logger.info(f"[AgentLoop] Using recovered vision call (parse failed: {e})")
                        else:
                            # 无法恢复：强约束终止
                            log_structured("AgentLoop", "parse_failed", agent_id=agent.agent_id, session_id=getattr(session, "session_id", ""), step=session.step, error=str(e)[:200])
                            logger.error(f"[AgentLoop] Failed to parse agent output: {e}")
                            session.status = "error"
                            session.error_message = f"Failed to parse agent output: {str(e)}"
                            self.trace_store.record_event(AgentTraceEvent(
                                trace_id=session.trace_id,
                                event_id=f"atev_{uuid.uuid4().hex[:16]}",
                                session_id=session.session_id,
                                step=session.step,
                                event_type="error",
                                agent_id=agent.agent_id,
                                model_id=agent.model_id,
                                input_data=None,
                                output_data={"error": str(e), "raw_output": llm_output},
                                duration_ms=duration_ms
                            ))
                            self.session_store.save_session(session)
                            break

                # 5. 处理 Action
                if action.type == "final":
                    # Guardrail: for time-sensitive "updates/news" queries, force one web search before allowing final.
                    # This only applies when the agent explicitly has builtin_web.search enabled, and prevents
                    # unsourced finals when the model forgets to call the skill.
                    def _last_user_text() -> str:
                        for msg in reversed(session.messages):
                            if msg.role == "user" and (msg.content or "").strip():
                                return msg.content.strip()
                        return ""

                    def _has_called_web_search() -> bool:
                        # We append an assistant message "Calling skill `builtin_web.search`." on execution.
                        for msg in session.messages:
                            if msg.role == "assistant" and "Calling skill `builtin_web.search`." in (msg.content or ""):
                                return True
                        return False

                    def _should_force_web_search(q: str) -> bool:
                        ql = (q or "").strip().lower()
                        if not ql:
                            return False
                        triggers = [
                            "更新", "本周", "最近", "最新", "发布", "公告",
                            "changelog", "release", "what's new", "whats new", "update", "new features", "news",
                        ]
                        return any(t in ql for t in triggers)

                    last_user_q = _last_user_text()
                    if (
                        "builtin_web.search" in (agent.enabled_skills or [])
                        and _should_force_web_search(last_user_q)
                        and not _has_called_web_search()
                    ):
                        logger.info(
                            "[AgentLoop] Forcing builtin_web.search before final agent_id=%s step=%s query=%r",
                            agent.agent_id, session.step, last_user_q,
                        )
                        action = AgentAction(
                            type="skill_call",
                            skill_id="builtin_web.search",
                            input={"query": last_user_q, "top_k": 5},
                        )
                    else:
                        # OCR 懒政检测：如果模型输出包含「未提供」等关键词，或疑似假答案，且有上传图片，强制调用 VLM
                        # 只有 OCR 相关 Agent 才会触发此逻辑
                        def _is_ocr_agent() -> bool:
                            """检测是否为 OCR 相关 Agent"""
                            # 检查 agent 名称
                            agent_name = (getattr(agent, "name", "") or "").lower()
                            if any(kw in agent_name for kw in ["ocr", "识别", "文字", "text"]):
                                return True
                            # 检查 system_prompt
                            prompt = (getattr(agent, "system_prompt", "") or "").lower()
                            if any(kw in prompt for kw in ["识别", "文字", "ocr", "图片", "提取"]):
                                return True
                            return False
                        
                        def _is_suspicious_ocr_output(output: str) -> bool:
                            """检测模型输出是否疑似假答案/懒政输出"""
                            output_lower = output.lower()
                            # 明显的懒政关键词
                            lazy_keywords = ["未提供", "无法识别", "没有结果", "识别失败", "cannot", "unable", "not available", "not provided"]
                            if any(kw in output_lower for kw in lazy_keywords):
                                return True
                            # 疑似通用/假答案模式
                            suspicious_patterns = [
                                "your text content",  # VLM 的假答案模板
                                "the text in the image",
                                "contains the text",
                                "shows the text",
                                "displayed text",
                                "image shows",
                                "picture shows",
                                "i cannot see",
                                "i am unable to",
                                "unable to extract",
                                "could not find",
                                "no text found",
                                "text appears to be",
                            ]
                            return any(pat in output_lower for pat in suspicious_patterns)
                        
                        final_answer = (action.answer or llm_output or "").strip()
                        if (
                            _is_ocr_agent()
                            and "builtin_vlm.generate" in (agent.enabled_skills or [])
                            and final_answer
                            and _is_suspicious_ocr_output(final_answer)
                        ):
                            # 检查是否有新上传的图片
                            state = getattr(session, "state", None) or {}
                            last_img = self._last_uploaded_image(session)
                            if last_img:
                                # 有新图片但模型没有调用技能，强制调用
                                logger.info(
                                    "[AgentLoop] OCR lazy detection: forcing vlm.generate for image=%s (model output: %s)",
                                    last_img, final_answer[:50]
                                )
                                action = AgentAction(
                                    type="skill_call",
                                    skill_id="builtin_vlm.generate",
                                    input={"image": last_img, "prompt": "请逐行提取图片中的所有可见文字，只输出文字本身，保持原始换行与空格。"},
                                )
                            else:
                                session.messages.append(Message(role="assistant", content=final_answer))
                                session.status = "finished"
                                answer_data = {"answer": final_answer}
                                self.trace_store.record_event(AgentTraceEvent(
                                    trace_id=session.trace_id,
                                    event_id=f"atev_{uuid.uuid4().hex[:16]}",
                                    session_id=session.session_id,
                                    step=session.step,
                                    event_type="final_answer",
                                    agent_id=agent.agent_id,
                                    output_data=answer_data
                                ))
                                self.session_store.save_session(session)
                                break
                        else:
                            session.messages.append(Message(role="assistant", content=final_answer))
                            session.status = "finished"
                            
                            # 记录 Final Trace
                            # 确保 output_data 是字典类型
                            answer_data = action.answer if isinstance(action.answer, dict) else {"answer": action.answer}
                            self.trace_store.record_event(AgentTraceEvent(
                                trace_id=session.trace_id,
                                event_id=f"atev_{uuid.uuid4().hex[:16]}",
                                session_id=session.session_id,
                                step=session.step,
                                event_type="final_answer",
                                agent_id=agent.agent_id,
                                output_data=answer_data
                            ))
                            self.session_store.save_session(session)
                            break

                # v1.5: skill_call 或 tool_call（tool_call 映射为 builtin_<tool>）
                if action.type in ("skill_call", "tool_call"):
                    skill_id = action.skill_id if action.type == "skill_call" else (f"builtin_{action.tool}" if action.tool else None)
                    if not skill_id:
                        logger.error("[AgentLoop] skill_call missing skill_id or tool_call missing tool")
                        session.step += 1
                        self.session_store.save_session(session)
                        continue
                    # 常见 LLM 截断的 skill_id 别名映射（如 vision.detect -> vision.detect_objects）
                    _SKILL_ID_ALIASES = {"builtin_vision.detect": "builtin_vision.detect_objects"}
                    skill_id = _SKILL_ID_ALIASES.get(skill_id, skill_id)
                    # Security: 强制校验 skill_id 必须在该 Agent 的 enabled_skills 内
                    # 这样即使模型“猜中/构造”一个存在的 skill_id，也无法越权调用
                    allowed = set(agent.enabled_skills or [])
                    if skill_id not in allowed:
                        msg = f"Skill not enabled for this agent: {skill_id}"
                        logger.warning(f"[AgentLoop] {msg}")
                        session.messages.append(
                            Message(role="user", content=f"Skill execution error (untrusted): {msg}")
                        )
                        # 确保 input_data 是字典类型
                        error_input_data = action.input if isinstance(action.input, dict) else {"input": action.input}
                        self.trace_store.record_event(AgentTraceEvent(
                            trace_id=session.trace_id,
                            event_id=f"atev_{uuid.uuid4().hex[:16]}",
                            session_id=session.session_id,
                            step=session.step,
                            event_type="error",
                            agent_id=agent.agent_id,
                            model_id=agent.model_id,
                            tool_id=skill_id,
                            input_data=error_input_data,
                            output_data={"error": msg, "skill_id": skill_id},
                        ))
                        session.step += 1
                        self.session_store.save_session(session)
                        continue
                    skill_start_time = time.time()
                    try:
                        # 自动补全常见必填参数，避免模型给出空 input 导致校验失败
                        inputs = action.input or {}
                        if not isinstance(inputs, dict):
                            inputs = {}
                        
                        # 图片相关 skill 的自动补全
                        if skill_id in ("builtin_vision.detect_objects", "builtin_vlm.generate"):
                            inputs = self._autofill_image_param(inputs, session, workspace, skill_id)
                        
                        # VLM generate 特有的参数补全
                        if skill_id == "builtin_vlm.generate":
                            prompt_was_missing = not (inputs.get("prompt") or "").strip()
                            # 自动补全 model_id 参数（使用 agent 的 model_id）
                            if not (inputs.get("model_id") or "").strip():
                                if agent.model_id:
                                    inputs = {**inputs, "model_id": agent.model_id}
                                    logger.info(f"[AgentLoop] Autofill vlm.generate model_id={agent.model_id} (from agent config)")
                                else:
                                    logger.warning(f"[AgentLoop] vlm.generate requires model_id but agent.model_id is empty")
                            # 自动补全 prompt 参数（如果缺失）
                            if not (inputs.get("prompt") or "").strip():
                                # 尝试从用户最后一条消息提取 prompt
                                last_user_text = ""
                                for msg in reversed(session.messages):
                                    if msg.role == "user" and (msg.content or "").strip():
                                        last_user_text = msg.content
                                        break
                                cleaned_user_text = self._clean_user_prompt_for_vlm(last_user_text) if last_user_text else ""
                                if cleaned_user_text:
                                    inputs = {**inputs, "prompt": cleaned_user_text}
                                    logger.info(f"[AgentLoop] Autofill vlm.generate prompt from last user message (cleaned)")
                                else:
                                    # 使用更通用的 prompt，而不是硬编码 OCR
                                    inputs = {**inputs, "prompt": "请描述图像内容。"}
                                    logger.info(f"[AgentLoop] Autofill vlm.generate prompt with default description prompt")
                            # 检查 image 参数是否已补全（如果仍然缺失，记录警告）
                            if not (inputs.get("image") or "").strip():
                                logger.warning(f"[AgentLoop] vlm.generate requires image but autofill failed (no image in workspace or uploaded)")

                            # OCR Agent minimal guardrails: deterministic prompt + stop repeat calls
                            if self._is_ocr_agent(agent):
                                # If prompt was auto-filled (not explicitly provided), use a stable OCR instruction.
                                if prompt_was_missing:
                                    inputs = {
                                        **inputs,
                                        "prompt": "请逐行提取图片中的所有可见文字，只输出文字本身，尽量保持原始换行与空格。",
                                    }
                                # Default generation params for OCR (best-effort, only when caller didn't set)
                                if inputs.get("temperature") is None:
                                    inputs = {**inputs, "temperature": 0}
                                if inputs.get("max_tokens") is None:
                                    inputs = {**inputs, "max_tokens": 256}

                                # If we already have a successful VLM output for the same image, finish early to avoid loops.
                                cached_vlm = self._find_latest_vlm_observation(session)
                                if cached_vlm:
                                    cached_in = cached_vlm.get("input") if isinstance(cached_vlm.get("input"), dict) else {}
                                    cached_img = (cached_in.get("image") or "").strip() if isinstance(cached_in, dict) else ""
                                    cur_img = (inputs.get("image") or "").strip()
                                    out = cached_vlm.get("output")
                                    cached_text = out.get("text") if isinstance(out, dict) else None
                                    if cached_img and cur_img and cached_img == cur_img and isinstance(cached_text, str) and cached_text.strip():
                                        logger.info(
                                            "[AgentLoop] OCR guardrail: reuse cached vlm.generate output and finish (avoid repeat calls)"
                                        )
                                        session.messages.append(Message(role="assistant", content=cached_text.strip()))
                                        session.status = "finished"
                                        self.trace_store.record_event(AgentTraceEvent(
                                            trace_id=session.trace_id,
                                            event_id=f"atev_{uuid.uuid4().hex[:16]}",
                                            session_id=session.session_id,
                                            step=session.step,
                                            event_type="final_answer",
                                            agent_id=agent.agent_id,
                                            output_data={"answer": cached_text.strip()},
                                        ))
                                        self.session_store.save_session(session)
                                        return session
                        
                        action.input = inputs

                        if skill_id in ("builtin_file.read", "builtin_file.list", "builtin_web.search"):
                            logger.info(f"[AgentLoop] execute_skill workspace={workspace!r} skill_id={skill_id}")
                        if skill_id == "builtin_web.search":
                            _query = (action.input or {}).get("query", "")
                            logger.info(
                                "[AgentLoop] web_search start agent_id=%s step=%s session_id=%s query=%r",
                                agent.agent_id, session.step, getattr(session, "session_id", ""), _query,
                            )
                        # Grant permissions based on skill type (V2.3: auto-derive from tool declarations)
                        from core.tools.permissions import build_permissions_for_skills
                        permissions = build_permissions_for_skills([skill_id])
                        result = await self.executor.execute_skill(
                            skill_id=skill_id,
                            inputs=action.input or {},
                            agent_id=agent.agent_id,
                            trace_id=f"{session.trace_id}:{session.step}:{skill_id}",
                            workspace=workspace,
                            permissions=permissions,
                        )
                        tool_result = result.get("output")
                        if result.get("error") and tool_result is None:
                            tool_result = f"Error: {result['error']}"
                        obs_meta = None
                        if skill_id == "builtin_vision.detect_objects":
                            req_img = (action.input or {}).get("image") or ""
                            obs_meta = {
                                "image_signature": self._image_signature(workspace, str(req_img).strip())
                            }
                        elif skill_id == "builtin_vlm.generate":
                            req_img = (action.input or {}).get("image") or ""
                            obs_meta = {
                                "image_signature": self._image_signature(workspace, str(req_img).strip())
                            }
                        self._record_skill_observation(
                            session,
                            skill_id=skill_id,
                            input_data=action.input or {},
                            output_data=tool_result,
                            ok=not bool(result.get("error")),
                            error=result.get("error"),
                            meta=obs_meta,
                        )
                        skill_duration_ms = int((time.time() - skill_start_time) * 1000)
                        log_structured(
                            "AgentLoop", "skill_executed",
                            agent_id=agent.agent_id, session_id=getattr(session, "session_id", ""), step=session.step,
                            skill_id=skill_id, duration_ms=skill_duration_ms, has_error=bool(result.get("error")),
                        )
                        if skill_id == "builtin_web.search":
                            err = result.get("error")
                            if err:
                                err_preview = (err[:200] + "…") if isinstance(err, str) and len(err) > 200 else err
                                logger.warning(
                                    "[AgentLoop] web_search done agent_id=%s step=%s query=%r error=%s duration_ms=%s",
                                    agent.agent_id, session.step, (action.input or {}).get("query"), err_preview, skill_duration_ms,
                                )
                            else:
                                res_output = result.get("output")
                                count = len(res_output) if isinstance(res_output, list) else (None if res_output is None else "?")
                                logger.info(
                                    "[AgentLoop] web_search done agent_id=%s step=%s query=%r results_count=%s duration_ms=%s",
                                    agent.agent_id, session.step, (action.input or {}).get("query"), count, skill_duration_ms,
                                )
                        display_name = skill_id
                        session.messages.append(
                            Message(role="assistant", content=f"Calling skill `{display_name}`.")
                        )
                        safe_payload = {
                            "skill_id": skill_id,
                            "input": action.input or {},
                            "output": self._sanitize_tool_output_for_prompt(tool_result),
                        }
                        session.messages.append(
                            Message(
                                role="tool",
                                content="Skill result (observation):\n```json\n"
                                + json.dumps(safe_payload, ensure_ascii=False, default=str)
                                + "\n```"
                            )
                        )
                        self.trace_store.record_event(AgentTraceEvent(
                            trace_id=session.trace_id,
                            event_id=f"atev_{uuid.uuid4().hex[:16]}",
                            session_id=session.session_id,
                            step=session.step,
                            event_type="skill_call",
                            agent_id=agent.agent_id,
                            tool_id=skill_id,
                            input_data=action.input if isinstance(action.input, dict) else {"input": action.input},
                            output_data=tool_result if isinstance(tool_result, dict) else {"result": tool_result},
                            duration_ms=skill_duration_ms
                        ))
                        # vision.detect_objects 后尝试 VLM 生成并直接结束（若启用）
                        if skill_id == "builtin_vision.detect_objects" and isinstance(tool_result, dict):
                            image_name = (action.input or {}).get("image") or ""
                            vlm_text = await self._run_vlm_after_yolo(
                                session=session,
                                agent=agent,
                                workspace=workspace,
                                image_name=image_name,
                                yolo_output=tool_result,
                            )
                            if isinstance(vlm_text, str) and vlm_text.strip():
                                session.messages.append(Message(role="assistant", content=vlm_text.strip()))
                                session.status = "finished"
                                self.trace_store.record_event(AgentTraceEvent(
                                    trace_id=session.trace_id,
                                    event_id=f"atev_{uuid.uuid4().hex[:16]}",
                                    session_id=session.session_id,
                                    step=session.step,
                                    event_type="final_answer",
                                    agent_id=agent.agent_id,
                                    output_data={"answer": vlm_text.strip()},
                                ))
                                self.session_store.save_session(session)
                                break
                        
                        # VLM OCR Agent: builtin_vlm.generate 执行后直接返回结果
                        if skill_id == "builtin_vlm.generate" and isinstance(tool_result, dict):
                            # 提取 VLM 生成的文本
                            vlm_output = tool_result.get("output", {})
                            if isinstance(vlm_output, dict):
                                vlm_text = vlm_output.get("text", "")
                                if isinstance(vlm_text, str) and vlm_text.strip():
                                    session.messages.append(Message(role="assistant", content=vlm_text.strip()))
                                    session.status = "finished"
                                    self.trace_store.record_event(AgentTraceEvent(
                                        trace_id=session.trace_id,
                                        event_id=f"atev_{uuid.uuid4().hex[:16]}",
                                        session_id=session.session_id,
                                        step=session.step,
                                        event_type="final_answer",
                                        agent_id=agent.agent_id,
                                        output_data={"answer": vlm_text.strip()},
                                    ))
                                    self.session_store.save_session(session)
                                    break
                    except Exception as e:
                        log_structured("AgentLoop", "skill_failed", agent_id=agent.agent_id, session_id=getattr(session, "session_id", ""), step=session.step, skill_id=skill_id, error=str(e)[:200])
                        logger.error(f"[AgentLoop] Skill execution failed: {e}")
                        session.messages.append(
                            Message(role="user", content=f"Skill execution error (untrusted): {skill_id}: {str(e)}")
                        )
                        self.trace_store.record_event(AgentTraceEvent(
                            trace_id=session.trace_id,
                            event_id=f"atev_{uuid.uuid4().hex[:16]}",
                            session_id=session.session_id,
                            step=session.step,
                            event_type="error",
                            agent_id=agent.agent_id,
                            tool_id=skill_id,
                            output_data={"error": str(e)}
                        ))

                session.step += 1
                self.session_store.save_session(session)

            if session.step >= agent.max_steps and session.status == "running":
                session.status = "finished"
                session.messages.append(Message(role="assistant", content="Max steps reached."))
                self.session_store.save_session(session)

            total_run_ms = round((time.perf_counter() - run_start) * 1000, 2)
            log_structured(
                "AgentLoop", "run_finished",
                agent_id=agent.agent_id, session_id=getattr(session, "session_id", ""), trace_id=session.trace_id,
                status=session.status, step=session.step, total_run_ms=total_run_ms,
            )

        except Exception as e:
            total_run_ms = round((time.perf_counter() - run_start) * 1000, 2)
            log_structured(
                "AgentLoop", "run_failed",
                agent_id=agent.agent_id, session_id=getattr(session, "session_id", ""), trace_id=getattr(session, "trace_id", ""),
                error=str(e)[:200], total_run_ms=total_run_ms,
            )
            logger.error(f"[AgentLoop] Loop crashed: {e}", exc_info=True)
            session.status = "error"
            session.error_message = str(e)
            self.session_store.save_session(session)

        return session
