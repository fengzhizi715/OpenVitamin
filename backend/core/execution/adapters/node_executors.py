"""
Node Executors
Execution Kernel 的节点执行器实现
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, Awaitable
import asyncio
import logging
import json
import re
from pathlib import Path

from execution_kernel.models.graph_definition import NodeDefinition


logger = logging.getLogger(__name__)


class NodeExecutor(ABC):
    """
    节点执行器基类
    
    所有具体执行器（LLM, Skill, Internal）都实现此接口
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """执行器名称"""
        pass
    
    @abstractmethod
    async def execute(
        self,
        node_def: NodeDefinition,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行节点
        
        Args:
            node_def: 节点定义
            input_data: 解析后的输入数据
            context: 执行上下文（包含 agent, session, state 等）
            
        Returns:
            节点输出数据
        """
        pass


class LLMExecutor(NodeExecutor):
    """
    LLM 节点执行器
    
    执行 LLM 推理步骤
    """
    
    def __init__(self, legacy_executor: Any = None):
        """
        Args:
            legacy_executor: 传入 v1.5 的 AgentExecutor，用于兼容
        """
        self.legacy_executor = legacy_executor
    
    @property
    def name(self) -> str:
        return "llm"
    
    async def execute(
        self,
        node_def: NodeDefinition,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行 LLM 步骤
        
        从 node_def.config 中获取 inputs（包含 messages）
        调用 LLM 并返回响应
        """
        config = node_def.config if node_def else {}
        inputs = config.get("inputs", input_data)
        
        # 合并上下文中的数据
        messages = inputs.get("messages", [])
        if inputs.get("_inject_skill_output"):
            graph_context = context.get("_graph_context")
            messages = self._inject_skill_output_into_messages(messages, graph_context)
        
        # 获取 Agent 和模型
        agent = context.get("agent")
        if not agent:
            raise RuntimeError("No agent in context")
        
        # 调用 LLM
        try:
            from core.types import Message
            from core.inference import get_inference_client

            msg_objs = []
            for m in messages:
                if isinstance(m, Message):
                    msg_objs.append(m)
                elif isinstance(m, dict):
                    msg_objs.append(Message(**m))
                else:
                    msg_objs.append(Message(role="user", content=str(m)))

            # V2.8: Use InferenceClient for unified access
            client = get_inference_client()
            model_params = inputs.get("model_params") or {}

            session = context.get("session")
            session_id = getattr(session, "session_id", "") if session is not None else ""
            trace_id = context.get("trace_id", "") or getattr(session, "trace_id", "")

            agent_params = getattr(agent, "model_params", {}) or {}
            max_tokens = inputs.get("max_tokens") or model_params.get("max_tokens") or agent_params.get("max_tokens") or 2048
            stop = inputs.get("stop") or model_params.get("stop")

            response = await client.generate(
                model=agent.model_id,
                messages=msg_objs,
                temperature=inputs.get("temperature", getattr(agent, "temperature", 0.7)),
                max_tokens=int(max_tokens),
                stop=stop,
                metadata={
                    "caller": "NodeExecutor",
                    "node_id": getattr(node_def, "id", "") or "",
                    "agent_id": getattr(agent, "agent_id", "") or "",
                    "session_id": session_id,
                    "trace_id": trace_id,
                },
            )
            content = response.text
            
            # 检查是否需要提取特定格式
            if inputs.get("_expect_unified_diff"):
                from core.agent_runtime.v2.executor_v2 import PlanBasedExecutor
                extracted = PlanBasedExecutor._extract_unified_diff(content)
                if extracted:
                    content = extracted

            # 结构化 JSON 输出约束（通用）：用于后续 __from_previous_step_json 占位符解析
            if inputs.get("_expect_json_output"):
                payload = self._extract_last_json_object(content) or {}
                path_val = payload.get("path") if isinstance(payload, dict) else None
                content_val = payload.get("content") if isinstance(payload, dict) else None

                if (not isinstance(path_val, str) or not path_val.strip()):
                    fallback_path = inputs.get("_fallback_path")
                    if isinstance(fallback_path, str) and fallback_path.strip():
                        path_val = fallback_path.strip()

                if (not isinstance(content_val, str) or not content_val.strip()):
                    content_val = self._recover_content_from_llm_output(content, payload)

                if not isinstance(path_val, str) or not path_val.strip():
                    raise RuntimeError("LLM JSON output missing required field: path")
                if not isinstance(content_val, str) or not content_val.strip():
                    raise RuntimeError("LLM JSON output missing required field: content")
                # 规范化为纯 JSON，降低下游解析歧义
                content = json.dumps(
                    {"path": path_val.strip(), "content": content_val},
                    ensure_ascii=False,
                )
            
            return {"response": content}
            
        except Exception as e:
            logger.error(f"LLM execution failed: {e}")
            raise

    @staticmethod
    def _extract_last_json_object(text: str) -> Optional[Dict[str, Any]]:
        """从文本中提取最后一个合法 JSON 对象（容忍 think/markdown 包裹）。"""
        if not isinstance(text, str) or not text.strip():
            return None
        raw = text.strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
        raw = re.sub(r"<think>[\\s\\S]*$", "", raw, flags=re.IGNORECASE).strip()

        m_block = re.search(r"```(?:json)?\\s*(\\{[\\s\\S]*?\\})\\s*```", raw, flags=re.IGNORECASE)
        if m_block:
            try:
                data = json.loads(m_block.group(1).strip())
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        starts = [idx for idx, ch in enumerate(raw) if ch == "{"]
        for start in reversed(starts):
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(raw)):
                ch = raw[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == "\"":
                        in_str = False
                    continue
                if ch == "\"":
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        piece = raw[start:i + 1]
                        try:
                            data = json.loads(piece)
                            if isinstance(data, dict):
                                return data
                        except Exception:
                            break
        return None

    @staticmethod
    def _recover_content_from_llm_output(text: str, payload: Dict[str, Any]) -> str:
        """
        在模型未严格遵守 JSON 合约时，尽量恢复代码内容，避免整条链路失败。
        优先级：payload 常见字段 > fenced code block > 去除 think 后原文。
        """
        if isinstance(payload, dict):
            for key in ("content", "code", "file_content", "source", "body", "text"):
                val = payload.get(key)
                if isinstance(val, str) and val.strip():
                    return val

        if isinstance(text, str) and text.strip():
            raw = text.strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
            raw = re.sub(r"<think>[\\s\\S]*$", "", raw, flags=re.IGNORECASE).strip()

            m = re.search(r"```(?:[a-zA-Z0-9_+-]*)\\s*([\\s\\S]*?)\\s*```", raw)
            if m:
                code = (m.group(1) or "").strip()
                if code:
                    return code

            return raw
        return ""

    def _inject_skill_output_into_messages(self, messages: Any, graph_context: Any) -> Any:
        """
        通用 skill 输出注入：
        - 从 graph_context.node_outputs 读取最近一个节点输出
        - 追加到最后一条 user 消息
        """
        if not isinstance(messages, list) or not messages:
            return messages

        skill_output_text = "无输出"

        def _clip_text(text: str, max_len: int = 8000) -> str:
            if len(text) <= max_len:
                return text
            return text[:max_len] + f"...(truncated {len(text) - max_len} chars)"

        def _sanitize_for_llm(value: Any, depth: int = 0) -> Any:
            if depth > 6:
                return "<max_depth_reached>"
            if isinstance(value, str):
                s = value.strip()
                if s.startswith("data:image/"):
                    return f"<image_data_url length={len(value)}>"
                if len(value) > 2000:
                    return f"<long_text length={len(value)}>"
                return value
            if isinstance(value, dict):
                out: Dict[str, Any] = {}
                for k, v in value.items():
                    lk = str(k).lower()
                    if lk in {"annotated_image", "image", "base64", "mask", "masks"}:
                        if isinstance(v, str):
                            out[k] = f"<{k} length={len(v)}>"
                        elif isinstance(v, list):
                            out[k] = f"<{k} items={len(v)}>"
                        else:
                            out[k] = f"<{k} omitted>"
                        continue
                    out[k] = _sanitize_for_llm(v, depth + 1)
                return out
            if isinstance(value, list):
                if len(value) > 30:
                    trimmed = value[:30]
                    return [_sanitize_for_llm(x, depth + 1) for x in trimmed] + [f"<omitted {len(value) - 30} items>"]
                return [_sanitize_for_llm(x, depth + 1) for x in value]
            return value

        def _summarize_vision_output(output: Dict[str, Any]) -> Dict[str, Any]:
            objects = output.get("objects", [])
            summarized_objects = []
            if isinstance(objects, list):
                for obj in objects[:30]:
                    if isinstance(obj, dict):
                        summarized_objects.append(
                            {
                                "label": obj.get("label"),
                                "confidence": obj.get("confidence"),
                                "bbox": obj.get("bbox"),
                                "has_mask": bool(obj.get("mask")),
                            }
                        )
                    else:
                        summarized_objects.append(obj)
            labels = []
            if isinstance(objects, list):
                for obj in objects:
                    if isinstance(obj, dict):
                        lb = obj.get("label")
                        if isinstance(lb, str) and lb:
                            labels.append(lb)
            # preserve order, de-dup
            uniq_labels = list(dict.fromkeys(labels))
            return {
                "objects_count": len(objects) if isinstance(objects, list) else 0,
                "labels": uniq_labels[:20],
                "objects_preview": summarized_objects,
                "image_size": output.get("image_size"),
                "has_annotated_image": bool(output.get("annotated_image")),
            }

        try:
            node_outputs = getattr(graph_context, "node_outputs", {}) if graph_context is not None else {}
            if isinstance(node_outputs, dict) and node_outputs:
                latest_output = list(node_outputs.values())[-1]
                if isinstance(latest_output, dict):
                    if isinstance(latest_output.get("output"), dict):
                        payload = latest_output.get("output")
                        if "output" in payload:
                            output = payload.get("output")
                            if isinstance(output, dict) and isinstance(output.get("objects"), list):
                                skill_output_text = json.dumps(
                                    _summarize_vision_output(output),
                                    ensure_ascii=False,
                                )
                            else:
                                skill_output_text = json.dumps(
                                    _sanitize_for_llm(output),
                                    ensure_ascii=False,
                                )
                        else:
                            skill_output_text = json.dumps(
                                _sanitize_for_llm(payload),
                                ensure_ascii=False,
                            )
                    else:
                        skill_output_text = json.dumps(
                            _sanitize_for_llm(latest_output),
                            ensure_ascii=False,
                        )
                else:
                    skill_output_text = _clip_text(str(latest_output))
        except Exception:
            pass
        skill_output_text = _clip_text(skill_output_text, max_len=10000)

        enriched = []
        last_user_idx = None
        for idx, msg in enumerate(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user_idx = idx
            enriched.append(dict(msg) if isinstance(msg, dict) else msg)

        if last_user_idx is None:
            return enriched

        user_msg = enriched[last_user_idx]
        if isinstance(user_msg, dict):
            content = str(user_msg.get("content", ""))
            user_msg["content"] = f"{content}\n\n以下是技能执行结果：\n{skill_output_text}"
            enriched[last_user_idx] = user_msg
        return enriched


class SkillExecutor(NodeExecutor):
    """
    Skill 节点执行器
    
    执行 Skill 工具调用
    """
    
    def __init__(self):
        pass
    
    @property
    def name(self) -> str:
        return "skill"
    
    async def execute(
        self,
        node_def: NodeDefinition,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行 Skill 步骤
        
        从 node_def.config 中获取 skill_id 和 inputs
        调用 SkillExecutor 执行
        """
        config = node_def.config if node_def else {}
        graph_context = context.get("_graph_context")
        
        # 统一兼容输入结构：
        # 1) {"skill_id": "...", "inputs": {...}}
        # 2) {"skill_id": "...", ...skill args...}
        # 3) node_def.config 里直接给 inputs
        raw_inputs = config.get("inputs")
        if raw_inputs is None:
            nested_inputs = input_data.get("inputs") if isinstance(input_data, dict) else None
            raw_inputs = nested_inputs if isinstance(nested_inputs, dict) else input_data
        
        if isinstance(raw_inputs, dict) and isinstance(raw_inputs.get("inputs"), dict):
            inputs = raw_inputs.get("inputs")  # 避免把包裹层传给 schema 校验
        elif isinstance(raw_inputs, dict):
            inputs = {k: v for k, v in raw_inputs.items() if k not in {"skill_id", "_depth"}}
        else:
            inputs = {}
        
        # 解析来自上一步 LLM 的 JSON 占位符（通用，不绑定业务）
        inputs = self._resolve_from_previous_step_markers(inputs, graph_context)

        # skill_id 优先从配置读取，其次从输入读取
        skill_id = config.get("skill_id") or input_data.get("skill_id")
        if not skill_id and isinstance(raw_inputs, dict):
            skill_id = raw_inputs.get("skill_id")
        
        # 调用 Skill 执行
        try:
            from core.skills.executor import SkillExecutor as SkillExec
            from core.skills.contract import SkillExecutionRequest

            # 通用输入防护：避免空内容误写入（如 path 有值但 content 为空导致 0 字节文件）
            sid = str(skill_id or "").strip()
            if sid in {"builtin_file.write", "file.write"}:
                path_val = inputs.get("path")
                content_val = inputs.get("content")
                if not isinstance(path_val, str) or not path_val.strip():
                    raise ValueError("Path is required")
                if not isinstance(content_val, str) or not content_val.strip():
                    raise ValueError("Content is required")
            
            request = SkillExecutionRequest(
                skill_id=skill_id,
                input=inputs,
                trace_id=context.get("trace_id", ""),
                caller_id=context.get("agent_id", ""),
                metadata={
                    "workspace": context.get("workspace", "."),
                    "permissions": context.get("permissions", {}),
                },
            )
            
            response = await SkillExec.execute(request)
            
            return {
                "status": response.status,
                "output": response.output,
                "error": response.error,
                "metrics": response.metrics,
                "skill_id": response.skill_id,
                "version": response.version,
                "trace_id": response.trace_id,
            }
            
        except Exception as e:
            logger.error(f"Skill execution failed: {e}")
            raise

    def _resolve_from_previous_step_markers(self, inputs: Dict[str, Any], graph_context: Any) -> Dict[str, Any]:
        """解析 __from_previous_step / __from_previous_step_json:<field> 占位符。"""
        if not isinstance(inputs, dict):
            return inputs

        def _latest_previous_text() -> str:
            try:
                node_outputs = getattr(graph_context, "node_outputs", {}) if graph_context is not None else {}
                if not isinstance(node_outputs, dict) or not node_outputs:
                    return ""

                def _extract_text(v: Any) -> str:
                    if isinstance(v, dict):
                        if isinstance(v.get("response"), str):
                            return v.get("response") or ""
                        out = v.get("output")
                        if isinstance(out, dict):
                            if isinstance(out.get("text"), str):
                                return out.get("text") or ""
                            return json.dumps(out, ensure_ascii=False)
                        return json.dumps(v, ensure_ascii=False)
                    return str(v)

                # 不依赖 dict 顺序，优先选择“像 JSON 产物”的 LLM 输出（含 path/content 字段）
                candidates = [_extract_text(v) for v in node_outputs.values()]
                if not candidates:
                    return ""

                def _score(t: str) -> tuple[int, int]:
                    s = (t or "").lower()
                    score = 0
                    if "\"path\"" in s or "'path'" in s:
                        score += 4
                    if "\"content\"" in s or "'content'" in s:
                        score += 4
                    if "```json" in s:
                        score += 2
                    if "{" in s and "}" in s:
                        score += 1
                    return score, len(s)

                best = max(candidates, key=_score)
                return best or ""
            except Exception:
                return ""

        def _extract_last_json_object(text: str) -> Optional[Dict[str, Any]]:
            """从模型文本中尽量提取“最后一个”合法 JSON 对象。"""
            if not isinstance(text, str) or not text.strip():
                return None
            raw = text.strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
            raw = re.sub(r"<think>[\\s\\S]*$", "", raw, flags=re.IGNORECASE).strip()

            # 优先 fenced json
            m_block = re.search(r"```(?:json)?\\s*(\\{[\\s\\S]*?\\})\\s*```", raw, flags=re.IGNORECASE)
            if m_block:
                try:
                    data = json.loads(m_block.group(1).strip())
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass

            # 从后向前尝试解析 JSON 对象，避免命中思考中的示例片段
            starts = [idx for idx, ch in enumerate(raw) if ch == "{"]
            for start in reversed(starts):
                depth = 0
                in_str = False
                esc = False
                for i in range(start, len(raw)):
                    ch = raw[i]
                    if in_str:
                        if esc:
                            esc = False
                        elif ch == "\\":
                            esc = True
                        elif ch == "\"":
                            in_str = False
                        continue
                    if ch == "\"":
                        in_str = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = raw[start:i + 1]
                            try:
                                data = json.loads(candidate)
                                if isinstance(data, dict):
                                    return data
                            except Exception:
                                break
            return None

        def _extract_json_field(text: str, field: str) -> str:
            if not isinstance(text, str) or not text.strip():
                return ""
            def _extract_json_quoted_value(raw_text: str, key: str) -> Optional[str]:
                """
                在非严格 JSON 文本中提取 `"key": "..."` 的字符串值，支持转义字符。
                即使外围 JSON 不完整，也可工作（只要该字符串本身闭合）。
                """
                m_key = re.search(rf'["\\\']{re.escape(key)}["\\\']\\s*:\\s*"', raw_text, flags=re.IGNORECASE)
                if not m_key:
                    return None
                start = m_key.end()  # 指向值字符串内容起始
                buf = []
                esc = False
                for i in range(start, len(raw_text)):
                    ch = raw_text[i]
                    if esc:
                        buf.append(ch)
                        esc = False
                        continue
                    if ch == "\\":
                        buf.append(ch)
                        esc = True
                        continue
                    if ch == "\"":
                        token = "".join(buf)
                        try:
                            # 复用 JSON 反转义
                            return json.loads(f'"{token}"')
                        except Exception:
                            return token
                    buf.append(ch)
                return None

            payload = _extract_last_json_object(text)
            value = payload.get(field) if isinstance(payload, dict) else None

            # payload 存在但缺字段，或 payload 解析失败：统一走兜底提取
            if value is None:
                quoted = _extract_json_quoted_value(text, field)
                if isinstance(quoted, str):
                    return quoted.strip()

                # JSON 不完整时的兜底：尝试键值正则提取（常见于 LLM 被 max_tokens 截断）
                m = re.search(
                    rf'["\\\']{re.escape(field)}["\\\']\\s*:\\s*["\\\']([^"\\\']+)',
                    text,
                    flags=re.IGNORECASE,
                )
                if m:
                    return m.group(1).strip()

                # path 专用兜底：若仅提到文件名/相对路径，也尽量提取
                if field == "path":
                    m2 = re.search(
                        r'([A-Za-z0-9_./-]+\.(?:cpp|cc|cxx|c|h|hpp|py|js|ts|tsx|java|go|rs|kt|swift|php|rb|sh|sql|md|txt|json|yaml|yml|vue))',
                        text,
                        flags=re.IGNORECASE,
                    )
                    if m2:
                        return m2.group(1).strip()
                return ""

            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

        prev_text = _latest_previous_text()
        base_hint = inputs.get("_json_path_base")
        base_hint = base_hint.strip() if isinstance(base_hint, str) else ""
        out = {}
        for k, v in inputs.items():
            if k == "_json_path_base":
                continue
            if v == "__from_previous_step":
                out[k] = prev_text
            elif isinstance(v, str) and v.startswith("__from_previous_step_json:"):
                field = v.split(":", 1)[1].strip()
                value = _extract_json_field(prev_text, field)
                if field == "path" and isinstance(value, str):
                    resolved = value.strip()
                    if resolved and base_hint:
                        p = Path(resolved).expanduser()
                        if not p.is_absolute():
                            resolved = str((Path(base_hint).expanduser() / p).resolve())
                    value = resolved
                out[k] = value
            else:
                out[k] = v
        return out


class InternalExecutor(NodeExecutor):
    """
    Internal 节点执行器
    
    执行内部操作（如状态更新、RePlan 等）
    """
    
    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
    
    @property
    def name(self) -> str:
        return "internal"
    
    def register_handler(self, action: str, handler: Callable):
        """注册内部操作处理器"""
        self._handlers[action] = handler
    
    async def execute(
        self,
        node_def: NodeDefinition,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行内部操作
        
        支持的操作：
        - replan: 触发重规划
        - state_update: 更新状态
        """
        config = node_def.config if node_def else {}
        action = config.get("action") or input_data.get("action")
        
        handler = self._handlers.get(action)
        if handler:
            if asyncio.iscoroutinefunction(handler):
                return await handler(input_data, context)
            else:
                return handler(input_data, context)
        
        # 默认处理
        if action == "replan":
            return await self._handle_replan(config, input_data, context)
        elif action == "state_update":
            return await self._handle_state_update(input_data, context)
        
        return {"error": f"Unknown internal action: {action}"}
    
    async def _handle_replan(
        self,
        config: Dict[str, Any],
        input_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """处理重规划"""
        replan_instruction = config.get("replan_instruction") or input_data.get("instruction")
        
        if not replan_instruction:
            return {"error": "No replan instruction provided"}
        
        planner = context.get("planner")
        agent = context.get("agent")
        
        if planner and agent:
            try:
                new_plan = await planner.create_plan(
                    agent=agent,
                    user_input=replan_instruction,
                    messages=[],
                    context=context,
                )
                
                return {
                    "status": "success",
                    "followup_plan_id": new_plan.plan_id,
                    "plan": new_plan.model_dump(),
                }
            except Exception as e:
                logger.error(f"Replan failed: {e}")
                return {"error": str(e), "status": "failed"}
        
        return {"error": "No planner in context", "status": "failed"}
    
    async def _handle_state_update(
        self,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """处理状态更新"""
        state = context.get("state")
        if not state:
            return {"error": "No state in context"}
        
        updates = input_data.get("updates", {})
        for key, value in updates.items():
            state.set_runtime(key, value)
        
        return {"status": "success", "updated_keys": list(updates.keys())}


class NodeExecutorRegistry:
    """
    节点执行器注册表
    
    管理所有可用的执行器
    """
    
    def __init__(self):
        self._executors: Dict[str, NodeExecutor] = {}
    
    def register(self, executor: NodeExecutor):
        """注册执行器"""
        self._executors[executor.name] = executor
        logger.info(f"Registered node executor: {executor.name}")
    
    def get(self, name: str) -> Optional[NodeExecutor]:
        """获取执行器"""
        return self._executors.get(name)
    
    def get_all(self) -> Dict[str, NodeExecutor]:
        """获取所有执行器"""
        return dict(self._executors)


# 全局注册表
_registry: Optional[NodeExecutorRegistry] = None


def get_executor_registry() -> NodeExecutorRegistry:
    """获取全局执行器注册表"""
    global _registry
    if _registry is None:
        _registry = NodeExecutorRegistry()
    return _registry


def init_executors(legacy_executor: Any = None) -> NodeExecutorRegistry:
    """初始化默认执行器"""
    registry = get_executor_registry()
    
    # 注册默认执行器
    registry.register(LLMExecutor(legacy_executor))
    registry.register(SkillExecutor())
    registry.register(InternalExecutor())
    
    return registry
