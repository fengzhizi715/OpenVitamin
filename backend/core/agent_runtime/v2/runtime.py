"""
Agent V2 Runtime
统一的 Agent 运行时入口
支持 legacy 和 plan_based 两种执行模式
"""
import json
import re
import time
import uuid
from typing import Optional

from log import logger, log_structured
from .observability import AgentV2Metrics
from core.agent_runtime.definition import AgentDefinition
from core.agent_runtime.session import AgentSession
from core.agent_runtime.loop import AgentLoop as LegacyAgentLoop
from core.agent_runtime.executor import AgentExecutor
from .models import AgentState, ExecutionMode, Plan, ExecutionTrace
from .executor_v2 import PlanBasedExecutor
from .planner import get_planner


# Feature flag: Use Execution Kernel (new DAG engine) instead of PlanBasedExecutor
# Set to True to enable the new Execution Kernel
USE_EXECUTION_KERNEL = False


class AgentRuntime:
    """
    统一的 Agent 运行时入口
    
    根据 agent.execution_mode 分流：
    - legacy: 使用 v1.5 的 AgentLoop
    - plan_based: 使用 Planner + PlanBasedExecutor/ExecutionKernel
    """

    def __init__(self, executor: AgentExecutor):
        """
        初始化
        
        Args:
            executor: v1.5 的 AgentExecutor 实例
        """
        self.executor = executor
        self.legacy_loop = LegacyAgentLoop(executor)
        self.plan_executor = PlanBasedExecutor(executor)
        self.planner = get_planner()
        
        # Lazy-initialized Execution Kernel adapter
        self._kernel_adapter = None
    
    def _get_kernel_adapter(self):
        """Get or create the Execution Kernel adapter (lazy initialization)"""
        if self._kernel_adapter is None:
            from core.execution.adapters.kernel_adapter import ExecutionKernelAdapter
            self._kernel_adapter = ExecutionKernelAdapter()
        return self._kernel_adapter
    
    def _should_use_kernel(self, agent: AgentDefinition) -> bool:
        """
        Determine whether to use Execution Kernel for this agent.
        
        Priority:
        1. Agent-level override: agent.use_execution_kernel
        2. Global feature flag: USE_EXECUTION_KERNEL
        """
        # Agent-level override takes priority
        agent_override = getattr(agent, "use_execution_kernel", None)
        if agent_override is not None:
            return bool(agent_override)
        # Fall back to global flag
        return USE_EXECUTION_KERNEL

    def _build_permissions(self, agent: AgentDefinition) -> dict:
        """
        根据 agent 的 enabled_skills 构建权限
        
        V2.3: Auto-derive permissions from skill/tool declarations.
        No more hardcoded skill -> permission mappings.
        """
        from core.tools.permissions import build_permissions_for_skills
        
        enabled_skills = agent.enabled_skills or []
        return build_permissions_for_skills(enabled_skills)

    async def run(
        self,
        agent: AgentDefinition,
        session: AgentSession,
        workspace: str = "."
    ) -> AgentSession:
        """
        运行 Agent
        
        Args:
            agent: Agent 定义
            session: Agent 会话
            workspace: 工作目录
        
        Returns:
            更新后的 session
        """
        # 获取执行模式（默认 legacy）
        execution_mode = getattr(agent, "execution_mode", None) or ExecutionMode.LEGACY.value
        
        if execution_mode == ExecutionMode.PLAN_BASED.value:
            return await self._run_plan_based(agent, session, workspace)
        else:
            return await self._run_legacy(agent, session, workspace)

    async def _run_legacy(
        self,
        agent: AgentDefinition,
        session: AgentSession,
        workspace: str
    ) -> AgentSession:
        """
        运行 Legacy 模式（v1.5 兼容）
        """
        logger.info(f"[AgentRuntime] Running legacy mode for agent {agent.agent_id}")
        return await self.legacy_loop.run(session, agent, workspace=workspace)

    async def _run_plan_based(
        self,
        agent: AgentDefinition,
        session: AgentSession,
        workspace: str
    ) -> AgentSession:
        """
        运行 Plan-Based 模式（V2）
        
        流程：
        1. 从 session 中获取最新用户消息
        2. 调用 Planner 生成 Plan
        3. 初始化 State（从 session.state 迁移）
        4. 调用 PlanBasedExecutor.execute_plan
        5. 将结果转换回 session 格式
        """
        logger.info(f"[AgentRuntime] Running plan_based mode for agent {agent.agent_id}")
        run_start = time.perf_counter()
        metrics = AgentV2Metrics(agent_id=agent.agent_id, session_id=session.session_id or "")
        log_structured("Runtime", "run_start", agent_id=agent.agent_id, session_id=session.session_id or "")
        
        # 确保 session 有 trace_id，便于 Trace 页按 session 查询
        if not getattr(session, "trace_id", None):
            session.trace_id = f"atrace_{uuid.uuid4().hex[:16]}"
        
        # 1. 获取最新用户消息
        user_input = ""
        for msg in reversed(session.messages):
            if msg.role == "user":
                user_input = msg.content or ""
                break
        
        if not user_input:
            logger.warning("[AgentRuntime] No user input found")
            session.status = "error"
            session.error_message = "No user input"
            return session
        
        # 构建权限
        permissions = self._build_permissions(agent)

        # 运行前做一次通用资源回收（与具体 Agent/业务解耦）
        try:
            from core.runtimes.factory import get_runtime_factory
            await get_runtime_factory().auto_release_unused_local_runtimes(
                keep_model_ids={str(agent.model_id or "").strip()},
                reason=f"agent_run:{agent.agent_id}",
            )
        except Exception:
            pass
        
        # 获取 user_id
        user_id = getattr(session, "user_id", None) or "default"
        
        # 2. 生成执行计划（若 plan 中有步骤写入 session.state.project_info，会注入到 context）
        plan_context = {
            "workspace": workspace,
            "permissions": permissions,
            "agent_id": agent.agent_id,
            "user_id": user_id,
            "session_id": session.session_id,
        }
        if session.state and isinstance(session.state, dict) and "project_info" in session.state:
            plan_context["project_info"] = session.state.get("project_info")
        plan_creation_start = time.perf_counter()
        plan = await self.planner.create_plan(
            agent=agent,
            user_input=user_input,
            messages=session.messages,
            context=plan_context,
        )
        metrics.plan_creation_ms = round((time.perf_counter() - plan_creation_start) * 1000, 2)
        log_structured("Runtime", "plan_created", plan_id=plan.plan_id, step_count=len(plan.steps), duration_ms=metrics.plan_creation_ms)
        
        # 3. 初始化 State
        state = AgentState(
            agent_id=agent.agent_id,
            persistent_state=session.state or {},
            runtime_state={},
        )
        
        # 4. 执行计划 - 选择执行引擎
        use_kernel = self._should_use_kernel(agent)
        kernel_fallback = False
        
        try:
            if use_kernel:
                # 使用 Execution Kernel (新 DAG 引擎)
                metrics.execution_engine = "kernel"
                log_structured("Runtime", "using_execution_kernel", agent_id=agent.agent_id, plan_id=plan.plan_id)
                try:
                    kernel = self._get_kernel_adapter()
                    plan, state, trace = await kernel.execute_plan(
                        plan=plan,
                        state=state,
                        session=session,
                        agent=agent,
                        messages=session.messages,
                        planner=self.planner,
                        workspace=workspace,
                        permissions=permissions,
                        metrics=metrics,
                        executor=self.executor,
                    )
                except Exception as e:
                    kernel_fallback = True
                    metrics.kernel_fallback = True
                    logger.error(f"[AgentRuntime] Execution Kernel failed, falling back to PlanBasedExecutor: {e}")
                    log_structured("Runtime", "kernel_fallback", agent_id=agent.agent_id, error=str(e)[:200])
                    # Fallback to legacy executor
                    plan, state, trace = await self.plan_executor.execute_plan(
                        plan=plan,
                        state=state,
                        session=session,
                        agent=agent,
                        workspace=workspace,
                        permissions=permissions,
                        metrics=metrics,
                    )
            else:
                # 使用 PlanBasedExecutor (原有执行器)
                metrics.execution_engine = "plan_based"
                plan, state, trace = await self.plan_executor.execute_plan(
                    plan=plan,
                    state=state,
                    session=session,
                    agent=agent,
                    workspace=workspace,
                    permissions=permissions,
                    metrics=metrics,
                )
            
            metrics.total_run_ms = round((time.perf_counter() - run_start) * 1000, 2)
            metrics.final_status = getattr(trace, "final_status", "")
            metrics.step_count = len(plan.steps)
            metrics.replan_count = getattr(state, "runtime_state", {}).get("replan_count", 0)
            
            log_structured("Runtime", "run_finished", plan_id=plan.plan_id, final_status=metrics.final_status, total_run_ms=metrics.total_run_ms, engine=metrics.execution_engine)
            metrics.log_summary()
            
            # 记录聚合统计
            from .observability import get_kernel_stats
            failed_steps = sum(1 for s in plan.steps if s.status == "failed")
            get_kernel_stats().record_run(
                engine=metrics.execution_engine,
                success=metrics.final_status == "completed",
                fallback=kernel_fallback,
                replan_count=metrics.replan_count,
                step_count=metrics.step_count,
                failed_steps=failed_steps,
                duration_ms=metrics.total_run_ms,
            )
            
            # 5. 将结果转换回 session 格式
            session = self._plan_result_to_session(
                session=session,
                plan=plan,
                state=state,
                trace=trace,
            )
            
            # V2.6: 设置 kernel_instance_id（用于前端 Debug UI）
            if metrics.kernel_instance_id:
                session.kernel_instance_id = metrics.kernel_instance_id
            
            # 6. 保存 session 到数据库
            try:
                from core.agent_runtime.session import get_agent_session_store
                session_store = get_agent_session_store()
                session_store.save_session(session)
                logger.info(f"[AgentRuntime] Session {session.session_id} saved successfully")
            except Exception as e:
                logger.warning(f"[AgentRuntime] Failed to save session: {e}")
            
            # 7. 保存 trace 到 trace store
            try:
                from core.agent_runtime.trace import get_agent_trace_store, AgentTraceEvent
                trace_store = get_agent_trace_store()
                
                # Phase A: 展开层级 trace，包括 subgraph_traces
                # 使用 get_all_logs_with_hierarchy() 获取所有层级的 logs
                all_logs = trace.get_all_logs_with_hierarchy()
                
                # 将 V2 ExecutionTrace 转换为 AgentTraceEvent
                for i, log in enumerate(all_logs):
                    try:
                        # 将层级信息存入 input_data（临时方案，后续可扩展 AgentTraceEvent 支持层级字段）
                        input_data_with_hierarchy = dict(log.input_data) if log.input_data else {}
                        if log.parent_step_id is not None:
                            input_data_with_hierarchy["_parent_step_id"] = log.parent_step_id
                        if log.depth is not None:
                            input_data_with_hierarchy["_depth"] = log.depth
                        # V2.5: 首条 trace 写入执行引擎，便于按会话确认是否使用 Execution Kernel
                        if i == 0:
                            input_data_with_hierarchy["_execution_engine"] = metrics.execution_engine
                        
                        # V2.5: 从 input_data 取出 skill_id 写入 tool_id，便于前端 Trace 页按技能名展示（避免两行都显示为 complete）
                        tool_id_from_input = (log.input_data or {}).get("skill_id") if isinstance(log.input_data, dict) else None
                        
                        event = AgentTraceEvent(
                            event_id=f"evt_{trace.plan_id}_{i}",  # 生成唯一 event_id
                            session_id=session.session_id,
                            agent_id=agent.agent_id,
                            trace_id=trace.plan_id,
                            step=i,  # 使用索引作为 step 数字
                            event_type=log.event_type,
                            tool_id=tool_id_from_input,
                            input_data=input_data_with_hierarchy,
                            output_data=log.output_data if isinstance(log.output_data, dict) else {"value": str(log.output_data)},
                            duration_ms=int(round(log.duration_ms)) if log.duration_ms is not None else None,  # 添加耗时
                            created_at=log.timestamp,
                        )
                        trace_store.record_event(event)
                    except Exception as e:
                        logger.warning(f"[AgentRuntime] Skip trace log index={i} due to serialization error: {e}")
                        continue
                # 与 trace store 一致：session.trace_id 指向本次写入的 trace，便于按 session 查 Trace
                session.trace_id = trace.plan_id
                try:
                    from core.agent_runtime.session import get_agent_session_store
                    get_agent_session_store().save_session(session)
                except Exception:
                    pass
                logger.info(f"[AgentRuntime] Trace {trace.plan_id} saved successfully")
            except Exception as e:
                logger.warning(f"[AgentRuntime] Failed to save trace: {e}")
            
        except Exception as e:
            metrics.total_run_ms = round((time.perf_counter() - run_start) * 1000, 2)
            metrics.final_status = "error"
            log_structured("Runtime", "run_failed", plan_id=getattr(plan, "plan_id", ""), error=str(e)[:200], total_run_ms=metrics.total_run_ms)
            metrics.log_summary()
            logger.error(f"[AgentRuntime] Plan execution failed: {e}", exc_info=True)
            session.status = "error"
            session.error_message = str(e)
            # 异常时也保存 session
            try:
                from core.agent_runtime.session import get_agent_session_store
                session_store = get_agent_session_store()
                session_store.save_session(session)
            except Exception:
                pass
        
        return session

    def _plan_result_to_session(
        self,
        session: AgentSession,
        plan: Plan,
        state: AgentState,
        trace: ExecutionTrace
    ) -> AgentSession:
        """
        将 Plan 执行结果转换回 Session 格式
        """
        from core.types import Message
        
        # 更新 session 状态
        if trace.final_status == "completed":
            session.status = "finished"
            session.error_message = None
        elif trace.final_status == "failed":
            session.status = "error"
        else:
            session.status = "finished"
        
        # 更新 session state
        session.state = state.persistent_state

        model_params = (getattr(plan, "context", None) or {}).get("model_params") or {}
        show_intermediate = bool(model_params.get("skill_chain_show_intermediate"))
        image_label = model_params.get("skill_chain_intermediate_image_label", "标注图")

        def _materialize_data_url_image(*, data_url: str) -> Optional[tuple[str, str, str]]:
            """
            将 data:image/... base64 图片落盘到 session.workspace_dir，并返回 (filename, url_path)。
            仅用于“对话展示层”，避免把 base64 直接写回聊天。
            """
            try:
                import base64
                import re
                from pathlib import Path

                s = (data_url or "").strip()
                if not s.startswith("data:image/"):
                    return None
                m = re.match(r"^data:image/([a-zA-Z0-9+.-]+);base64,(.+)$", s, re.DOTALL)
                if not m:
                    return None
                src_ext = (m.group(1) or "png").lower().strip()
                b64 = m.group(2)
                img_bytes = base64.b64decode(b64)

                workspace = getattr(session, "workspace_dir", None) or ""
                if not isinstance(workspace, str) or not workspace.strip():
                    return None
                ws = Path(workspace).resolve()
                ws.mkdir(parents=True, exist_ok=True)

                # 不重编码/不压缩：直接落盘原始 bytes（展示时由前端等比例缩放）
                allowed_ext = {"png", "jpg", "jpeg", "webp", "gif", "bmp"}
                ext = src_ext if src_ext in allowed_ext else "png"
                fname = f"annotated_{uuid.uuid4().hex[:10]}.{ext}"
                out = ws / fname
                out.write_bytes(img_bytes)

                url_path = f"/api/agent-sessions/{session.session_id}/files/{fname}"

                # 生成绝对 URL（前端 Markdown 渲染 img src 时不会走 Vite SPA fallback）
                try:
                    from config.settings import settings
                    host = (getattr(settings, "host", "") or "").strip()
                    port = int(getattr(settings, "port", 8000))
                    if host in ("0.0.0.0", "127.0.0.1", ""):
                        host = "localhost"
                    abs_url = f"http://{host}:{port}{url_path}"
                except Exception:
                    abs_url = url_path

                return fname, url_path, abs_url
            except Exception:
                return None
        
        # 汇总步骤输出，优先展示 LLM 最终回答；若没有 LLM，则回退到技能结果/错误
        def _clean_llm_output(text: str) -> str:
            if not isinstance(text, str) or not text:
                return ""
            # 清理思考内容，但保留最终可展示回答。
            # 兼容两种情况：
            # 1) 完整标签: <think>...</think>
            # 2) 非闭合标签: <think>...
            cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
            cleaned = re.sub(r"<think>[\s\S]*$", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE).strip()
            return cleaned

        llm_output: Optional[str] = None
        skill_output: Optional[str] = None
        vision_annotated_image_url: Optional[str] = None  # For skill chain intermediate image
        last_error: Optional[str] = None
        intermediate_msgs: list[str] = []
        file_mutation_done = False
        plan_source = ""
        if isinstance(getattr(plan, "context", None), dict):
            plan_source = str(plan.context.get("plan_source") or "")
        last_written_path: Optional[str] = None
        last_written_bytes: Optional[int] = None
        last_read_content: Optional[str] = None
        
        logger.info(f"[AgentV2Runtime] Summarizing outputs from {len(plan.steps)} steps")
        for step in plan.steps:
            logger.info(f"[AgentV2Runtime] Step {step.step_id}: executor={step.executor}, status={step.status}, outputs_keys={list(step.outputs.keys()) if step.outputs else 'None'}")
            if step.status == "completed":
                # Skill outputs are collected separately, not from response field
                if step.executor.value == "skill":
                    skill_id = str((step.inputs or {}).get("skill_id", "")).strip() if isinstance(step.inputs, dict) else ""
                    if skill_id in {
                        "builtin_file.write",
                        "file.write",
                        "builtin_file.patch",
                        "file.patch",
                        "builtin_file.apply_patch",
                        "file.apply_patch",
                    }:
                        file_mutation_done = True
                    # 提取 file.write / file.read 的真实输出，供 feature_creation_plan 做确定性回显
                    try:
                        result_raw = step.outputs.get("result", {}) if isinstance(step.outputs, dict) else {}
                        if not result_raw and isinstance(step.outputs, dict) and "output" in step.outputs:
                            result_raw = step.outputs.get("output", {})
                        tool_payload = result_raw.get("output") if isinstance(result_raw, dict) else None
                        actual_output = tool_payload
                        if isinstance(tool_payload, dict) and "output" in tool_payload:
                            actual_output = tool_payload.get("output")

                        if skill_id in {"builtin_file.write", "file.write"} and isinstance(actual_output, dict):
                            p = actual_output.get("path")
                            if isinstance(p, str) and p.strip():
                                last_written_path = p.strip()
                            bw = actual_output.get("bytes_written")
                            if isinstance(bw, int):
                                last_written_bytes = bw
                        if skill_id in {"builtin_file.read", "file.read"}:
                            if isinstance(actual_output, str):
                                last_read_content = actual_output
                            elif isinstance(actual_output, dict):
                                c = actual_output.get("content")
                                if isinstance(c, str):
                                    last_read_content = c
                    except Exception:
                        pass
                    # Collect skill output for later processing
                    summary = self._summarize_skill_step(step.outputs)
                    logger.info(f"[AgentV2Runtime] Step {step.step_id} skill summary: {summary[:100] if summary else 'None'}...")
                    
                    # Special handling for vision.detect_objects - extract annotated image
                    result = step.outputs.get("result", {})
                    # Skill v2 格式兼容：如果 result 为空，尝试根级别的 output
                    if not result and "output" in step.outputs:
                        result = step.outputs.get("output", {})
                    output = result.get("output") if isinstance(result, dict) else None
                    if isinstance(output, dict):
                        annotated_image = output.get("annotated_image")
                        if isinstance(annotated_image, str) and annotated_image.startswith("data:image/"):
                            # Materialize the annotated image
                            materialized = _materialize_data_url_image(data_url=annotated_image)
                            if materialized:
                                fname, url_path, abs_url = materialized
                                vision_annotated_image_url = abs_url
                                logger.info(f"[AgentV2Runtime] Materialized annotated image: {fname} -> {abs_url}")
                    
                    if summary and not show_intermediate:
                        skill_output = summary
                    elif summary and show_intermediate:
                        intermediate_msgs.append(summary)
                # Only LLM responses should be used as the final response
                elif step.executor.value == "llm":
                    output = step.outputs.get("response")
                    logger.info(f"[AgentV2Runtime] Step {step.step_id} LLM response: {output[:100] if output else 'None'}...")
                    if isinstance(output, str) and output.strip():
                        llm_output = _clean_llm_output(output.strip())
            elif step.status == "failed":
                last_error = step.error or "Step execution failed"
                if step.executor.value == "skill":
                    summary = self._summarize_skill_step(step.outputs)
                    if summary:
                        skill_output = summary
        
        # feature_creation_plan：以工具真实结果为准，避免 LLM 总结与实际写入不一致
        if plan_source == "feature_creation_plan":
            model_params = (getattr(plan, "context", None) or {}).get("model_params") or {}
            preview_max_lines_raw = int(
                model_params.get("agent_v2_preview_max_lines")
                or model_params.get("feature_creation_preview_max_lines")
                or 120
            )
            # 通用规则：
            # - 0: 不截断，返回全文
            # - >0: 按行数截断（并做安全上限保护）
            if preview_max_lines_raw == 0:
                preview_max_lines = 0
            else:
                preview_max_lines = preview_max_lines_raw
                if preview_max_lines < 20:
                    preview_max_lines = 20
                if preview_max_lines > 500:
                    preview_max_lines = 500
            lines = ["交付结果："]
            if file_mutation_done and last_written_path:
                lines.append("- 文件创建状态：成功")
                lines.append(f"- 文件路径：{last_written_path}")
                if last_written_bytes is not None:
                    lines.append(f"- 写入字节数：{last_written_bytes}")
            else:
                lines.append("- 文件创建状态：失败（未检测到写入成功）")
            if isinstance(last_read_content, str) and last_read_content.strip():
                lines.append("- 文件内容预览：")
                code_lang = ""
                if isinstance(last_written_path, str):
                    p = last_written_path.lower()
                    if p.endswith(".py"):
                        code_lang = "python"
                    elif p.endswith(".js"):
                        code_lang = "javascript"
                    elif p.endswith(".ts"):
                        code_lang = "typescript"
                    elif p.endswith(".java"):
                        code_lang = "java"
                    elif p.endswith(".go"):
                        code_lang = "go"
                    elif p.endswith(".rs"):
                        code_lang = "rust"
                lines.append(f"```{code_lang}")
                if preview_max_lines == 0:
                    lines.append(last_read_content)
                else:
                    lines.append("\n".join(last_read_content.splitlines()[:preview_max_lines]))
                lines.append("```")
            elif llm_output:
                lines.append("- 说明：")
                lines.append(llm_output)
            session.messages.append(Message(role="assistant", content="\n".join(lines)))
            if session.status == "error" and not session.error_message:
                trace_error = self._extract_error_from_trace(trace)
                session.error_message = trace_error or session.error_message or "Plan execution failed"
            return session

        # Build final response: prioritize LLM output, but include annotated image if available
        logger.info(f"[AgentV2Runtime] Building final response: llm_output={'yes' if llm_output else 'no'}, skill_output={'yes' if skill_output else 'no'}, file_mutation_done={file_mutation_done}")
        
        logger.info(f"[AgentV2Runtime] show_intermediate={show_intermediate}, intermediate_msgs count={len(intermediate_msgs)}")
        
        if vision_annotated_image_url and show_intermediate:
            # For skill chains with vision, combine YOLO results + annotated image + LLM response into one message
            image_msg = f"![{image_label}]({vision_annotated_image_url})"
            
            # Build combined content: YOLO summary + image + LLM output
            combined_parts = []
            if intermediate_msgs:
                combined_parts.extend(intermediate_msgs)
            combined_parts.append(image_msg)
            if llm_output:
                combined_parts.append(llm_output)
            
            session.messages.append(Message(role="assistant", content="\n\n".join(combined_parts)))
        elif vision_annotated_image_url and llm_output:
            # Has image and LLM output but show_intermediate is False
            image_msg = f"![{image_label}]({vision_annotated_image_url})"
            session.messages.append(Message(role="assistant", content=f"{image_msg}\n\n{llm_output}"))
        elif llm_output:
            # 只在 feature_creation_plan 场景下显示文件写入提示
            # 其他智能体（如周报、视觉分析）不需要写入文件
            if not file_mutation_done and plan_source == "feature_creation_plan":
                llm_output = (
                    "说明：本次未检测到写入类技能成功执行（file.write/file.patch），"
                    "以下内容可能仅为建议，尚未实际创建或修改文件。\n\n"
                    f"{llm_output}"
                )
            session.messages.append(
                Message(role="assistant", content=llm_output)
            )
        elif show_intermediate and intermediate_msgs:
            for txt in intermediate_msgs:
                session.messages.append(Message(role="assistant", content=txt))
        elif skill_output:
            session.messages.append(
                Message(role="assistant", content=skill_output)
            )
        elif last_error and skill_output:
            session.messages.append(
                Message(role="assistant", content=skill_output)
            )
            session.error_message = last_error
        elif last_error:
            session.messages.append(
                Message(role="assistant", content=f"Error: {last_error}")
            )
            session.error_message = last_error
        elif session.status == "error":
            # 兜底：若 plan.step 未携带 error，但 trace 已有 error 事件，回填 error_message
            trace_error = self._extract_error_from_trace(trace)
            if trace_error:
                session.error_message = trace_error
            else:
                session.error_message = session.error_message or "Plan execution failed"
        
        return session

    @staticmethod
    def _extract_error_from_trace(trace: ExecutionTrace) -> Optional[str]:
        """从 trace 的 error 事件中提取最后一个可读错误信息。"""
        # Phase A: 使用 get_all_logs_with_hierarchy 包含子图的 error 事件
        all_logs = trace.get_all_logs_with_hierarchy()
        for log in reversed(all_logs):
            if getattr(log, "event_type", None) != "error":
                continue
            output_data = getattr(log, "output_data", None) or {}
            if isinstance(output_data, dict):
                err = output_data.get("error")
                if err:
                    return str(err)
        return None

    @staticmethod
    def _summarize_skill_step(outputs: dict) -> Optional[str]:
        """提取技能步骤可读输出，避免把结构化 payload 直接丢失。"""
        if not isinstance(outputs, dict):
            return str(outputs) if outputs else None
    
        def _summarize_project_analyze(output_data: dict) -> Optional[str]:
            """对 project.analyze 结果做人类可读摘要，避免整包 JSON 回写到对话。"""
            if not isinstance(output_data, dict):
                return None
            meta = output_data.get("meta", {}) if isinstance(output_data.get("meta"), dict) else {}
            framework = output_data.get("framework", {}) if isinstance(output_data.get("framework"), dict) else {}
            tests = output_data.get("tests", {}) if isinstance(output_data.get("tests"), dict) else {}
            risk = output_data.get("risk", {}) if isinstance(output_data.get("risk"), dict) else {}
    
            language = meta.get("language") or "unknown"
            repo_root = meta.get("repo_root") or "N/A"
            file_count = meta.get("file_count")
            size_kb = meta.get("size_kb")
            test_framework = tests.get("framework") or "unknown"
            web_framework = framework.get("web_framework") or "none"
            orm = framework.get("orm") or "none"
            risk_score = risk.get("risk_score", "N/A")
    
            lines = [
                "Project Intelligence 摘要：",
                f"- repo_root: {repo_root}",
                f"- language: {language}",
                f"- files: {file_count if file_count is not None else 'N/A'}",
                f"- size_kb: {size_kb if size_kb is not None else 'N/A'}",
                f"- test_framework: {test_framework}",
                f"- web_framework: {web_framework}",
                f"- orm: {orm}",
                f"- risk_score: {risk_score}",
            ]
            issues = risk.get("issues")
            if isinstance(issues, list) and issues:
                lines.append(f"- top_risk: {issues[0]}")
            return "\n".join(lines)
    
        def _summarize_shell_run(output_data: dict) -> Optional[str]:
            if not isinstance(output_data, dict):
                return None
            exit_code = output_data.get("exit_code")
            stdout = output_data.get("stdout") if isinstance(output_data.get("stdout"), str) else ""
            stderr = output_data.get("stderr") if isinstance(output_data.get("stderr"), str) else ""
            timed_out = bool(output_data.get("timed_out"))
            duration = output_data.get("duration_seconds")
            command = output_data.get("command") if isinstance(output_data.get("command"), str) else ""
    
            lines = [
                "命令执行结果：",
                f"- command: {command}" if command else "- command: N/A",
                f"- exit_code: {exit_code if exit_code is not None else 'N/A'}",
                f"- timed_out: {timed_out}",
                f"- duration_seconds: {duration if duration is not None else 'N/A'}",
            ]
            if exit_code == 0:
                lines.append("- status: success")
            else:
                lines.append("- status: failed")
            if stderr.strip():
                lines.append("- stderr:")
                lines.append(stderr[:1200])
            elif stdout.strip():
                # 成功时默认显示尾部结果，避免整段日志刷屏
                lines.append("- stdout (tail):")
                lines.append(stdout[-1200:])
            return "\n".join(lines)
    
        def _summarize_vision_detect_objects(output_data: dict) -> Optional[str]:
            """对 vision.detect_objects 结果做人类可读摘要，包含标注图提示。"""
            if not isinstance(output_data, dict):
                return None
            
            # 处理嵌套结构：支持 {"objects": [...]} 或 {"output": {"objects": [...]}}
            raw_objects = output_data.get("objects")
            annotated_image = output_data.get("annotated_image")
            
            # 如果当前层级没有 objects，尝试嵌套的 output 字段
            if not isinstance(raw_objects, list) and "output" in output_data:
                nested = output_data.get("output", {})
                if isinstance(nested, dict):
                    raw_objects = nested.get("objects")
                    if not annotated_image:
                        annotated_image = nested.get("annotated_image")
            
            objects = raw_objects if isinstance(raw_objects, list) else None
            has_annotated = isinstance(annotated_image, str) and annotated_image.startswith("data:image/")
                
            if not isinstance(objects, list) or not objects:
                answer = "YOLO 未检测到明显目标。"
                if has_annotated:
                    answer += "（已生成标注图：无框标注。）"
                return answer
                
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
            return "\n".join(parts)

        def _summarize_vision_segment_objects(output_data: dict) -> Optional[str]:
            """对 vision.segment_objects 结果做紧凑摘要，避免 mask/base64 回写。"""
            if not isinstance(output_data, dict):
                return None

            raw_objects = output_data.get("objects")
            annotated_image = output_data.get("annotated_image")
            image_size = output_data.get("image_size")

            if not isinstance(raw_objects, list) and "output" in output_data:
                nested = output_data.get("output", {})
                if isinstance(nested, dict):
                    raw_objects = nested.get("objects")
                    if not annotated_image:
                        annotated_image = nested.get("annotated_image")
                    if not image_size:
                        image_size = nested.get("image_size")

            objects = raw_objects if isinstance(raw_objects, list) else None
            has_annotated = isinstance(annotated_image, str) and annotated_image.startswith("data:image/")
            if not isinstance(objects, list) or not objects:
                answer = "实例分割未检测到明显目标区域。"
                if has_annotated:
                    answer += "（已生成分割标注图。）"
                return answer

            counts: Dict[str, int] = {}
            top_items: List[str] = []
            for o in objects:
                if not isinstance(o, dict):
                    continue
                label = str(o.get("label") or "object")
                counts[label] = counts.get(label, 0) + 1

            try:
                sorted_by_conf = sorted(
                    [o for o in objects if isinstance(o, dict)],
                    key=lambda x: float(x.get("confidence", 0.0)),
                    reverse=True,
                )
                for o in sorted_by_conf[:5]:
                    top_items.append(f"{o.get('label','object')}（{float(o.get('confidence',0.0)):.2f}）")
            except Exception:
                pass

            parts = []
            parts.append(f"实例分割识别到 {len(objects)} 个对象区域。")
            parts.append("按类别计数：" + "，".join([f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]))
            if top_items:
                parts.append("最高置信度示例：" + "，".join(top_items))
            if isinstance(image_size, list) and len(image_size) >= 2:
                parts.append(f"图像尺寸：{image_size[0]}×{image_size[1]}")
            if has_annotated:
                parts.append("已生成分割标注图。")
            return "\n".join(parts)
    
        def _filter_output(output_data: object) -> object:
            """
            过滤输出数据，避免将 base64/dataURL 等超大字段直接写回对话。
            说明：完整 output 仍保留在 Trace，这里仅影响"对话展示层"的回写。
            """
            if isinstance(output_data, dict):
                filtered: dict = {}
                for k, v in output_data.items():
                    # 常见大字段：annotated_image / image / base64
                    if isinstance(v, str):
                        if v.startswith("data:image/"):
                            filtered[k] = f"<{k} (data_url omitted)>"
                            continue
                        if k in ("annotated_image", "image", "base64", "mask", "masks") and len(v) > 256:
                            filtered[k] = f"<{k} (length: {len(v)})>"
                            continue
                    filtered[k] = _filter_output(v)
                return filtered
            if isinstance(output_data, list):
                if len(output_data) > 50:
                    return [_filter_output(x) for x in output_data[:50]] + [f"<omitted {len(output_data) - 50} items>"]
                return [_filter_output(x) for x in output_data]
            return output_data
    
        result = outputs.get("result", {})
        skill_id = outputs.get("skill_id")
        
        # 兼容 Skill v2 格式：如果 result 为空但根级别有 output，直接使用 outputs 作为 result
        if not result and "output" in outputs:
            result = outputs
            
        if isinstance(result, dict):
            output = result.get("output")
            if isinstance(output, str) and output.strip():
                return output.strip()
            if isinstance(output, dict):
                if skill_id == "builtin_project.analyze":
                    # Skill v2 格式兼容：处理嵌套结构 {"type": "tool", "output": {...}}
                    actual_output = output.get("output") if isinstance(output.get("output"), dict) else output
                    summary_text = actual_output.get("summary")
                    if isinstance(summary_text, str) and summary_text.strip():
                        return summary_text.strip()
                    summary = _summarize_project_analyze(actual_output)
                    if summary:
                        return summary
                if skill_id in ("builtin_shell.run", "shell.run"):
                    summary = _summarize_shell_run(output)
                    if summary:
                        return summary
                if skill_id in ("builtin_vision.detect_objects", "vision.detect_objects"):
                    # 视觉分析：返回标注图 + 自然语言描述
                    summary = _summarize_vision_detect_objects(output)
                    if summary:
                        return summary
                if skill_id in ("builtin_vision.segment_objects", "vision.segment_objects"):
                    summary = _summarize_vision_segment_objects(output)
                    if summary:
                        return summary
                # 通用嵌套输出处理：支持 {"output": {"text": "..."}} 或 {"output": {"output": {"text": "..."}}}
                text = output.get("text")
                if not text:
                    # 尝试嵌套结构，最多支持 2 层嵌套
                    nested = output.get("output", {})
                    if isinstance(nested, dict):
                        text = nested.get("text")
                        if not text and isinstance(nested.get("output"), dict):
                            text = nested["output"].get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
            if isinstance(output, (dict, list)) and output:
                return json.dumps(_filter_output(output), ensure_ascii=False)
            if result.get("message"):
                return str(result.get("message"))
    
            # 兜底：兼容不同 skill 返回结构
            compact = {k: v for k, v in result.items() if k != "error" and v not in (None, "", {}, [])}
            if compact:
                return json.dumps(_filter_output(compact), ensure_ascii=False)
            if result.get("error"):
                return f"Error: {result.get('error')}"
            return None
    
        if isinstance(result, str) and result.strip():
            return result.strip()
        return None


# 全局 Runtime 实例
_runtime: Optional[AgentRuntime] = None


def get_agent_runtime(executor: AgentExecutor) -> AgentRuntime:
    """获取 AgentRuntime 单例"""
    global _runtime
    if _runtime is None:
        _runtime = AgentRuntime(executor)
    return _runtime


def get_kernel_adapter():
    """
    V2.7: 获取全局 Kernel Adapter 实例
    
    用于 API 层访问 Execution Kernel 的 Optimization Layer 状态。
    若 Runtime 已存在则按需创建并返回 adapter（无需先执行过 Kernel），
    便于在未跑过任何 Agent 前即可查询/重建优化状态。
    
    Returns:
        ExecutionKernelAdapter 或 None（Runtime 未初始化时）
    """
    global _runtime
    if _runtime is None:
        return None
    return _runtime._get_kernel_adapter()
