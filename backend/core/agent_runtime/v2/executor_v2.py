"""
Agent V2 PlanBasedExecutor
基于计划的执行器，支持递归执行 sub_plan
"""
from typing import Any, Dict, Optional, Tuple
import json
import re
import time
from pathlib import Path

from log import logger, log_structured
from core.agent_runtime.session import AgentSession
from .models import (
    AgentState,
    ExecutionTrace,
    Plan,
    Step,
    StepLog,
    StepStatus,
    StepType,
    ExecutorType,
)
from .executors import ExecutorFactory
from core.agent_runtime.definition import AgentDefinition

# Replan placeholder safety guardrails
MAX_REPLAN_TEXT_PLACEHOLDER_LEN = 2000
MAX_REPLAN_JSON_PLACEHOLDER_LEN = 4000
ALLOWED_REPLAN_PLACEHOLDERS = {
    # Generic placeholders
    "failed_step_id",
    "failed_step_executor",
    "failed_step_error",
    "failed_step_inputs_json",
    "failed_step_outputs_json",
    "replan_count",
    "replan_limit",
    # Backward-compatible placeholders
    "test_command",
    "exit_code",
    "stdout",
    "stderr",
    "fix_iteration",
    "max_fix_iterations",
}

class PlanBasedExecutor:
    """
    基于计划的执行器
    
    核心特性：
    1. 递归执行：支持 composite 步骤内部的 sub_plan
    2. 状态共享：所有步骤共享同一个 State
    3. 完整追踪：记录每一步的输入输出
    """

    def __init__(self, legacy_executor: Any = None):
        """
        初始化
        
        Args:
            legacy_executor: 传入 v1.5 的 AgentExecutor，用于兼容某些场景
        """
        self.legacy_executor = legacy_executor

    @staticmethod
    def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
        """从 LLM 文本中提取 JSON 对象，容忍 <think> 与 fenced code。"""
        if not isinstance(text, str) or not text.strip():
            return None
        raw = text.strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
        raw = re.sub(r"<think>[\s\S]*$", "", raw, flags=re.IGNORECASE).strip()
        m_block = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw, flags=re.IGNORECASE)
        candidate = m_block.group(1).strip() if m_block else raw
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else None
        except Exception:
            # 从后向前提取最后一个合法 JSON 对象，避免命中前文示例/思考片段
            starts = [idx for idx, ch in enumerate(candidate) if ch == "{"]
            for start in reversed(starts):
                depth = 0
                in_str = False
                esc = False
                for i in range(start, len(candidate)):
                    ch = candidate[i]
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
                            piece = candidate[start:i + 1]
                            try:
                                data = json.loads(piece)
                                if isinstance(data, dict):
                                    return data
                            except Exception:
                                break
            return None

    async def execute_plan(
        self,
        plan: Plan,
        state: AgentState,
        session: AgentSession,
        agent: AgentDefinition,
        workspace: str = ".",
        permissions: Optional[Dict[str, Any]] = None,
        trace: Optional[ExecutionTrace] = None,
        parent_step_id: Optional[str] = None,
        depth: int = 0,
        metrics: Optional[Any] = None,
    ) -> Tuple[Plan, AgentState, ExecutionTrace]:
        """
        执行计划（支持递归）
        
        Args:
            plan: 要执行的计划
            state: Agent 状态（会在执行过程中被修改）
            session: Agent 会话
            agent: Agent 定义
            workspace: 工作目录
            permissions: 权限字典
            trace: 外部传入的 trace（用于递归时共享同一个 trace）
            parent_step_id: 父步骤 ID（用于层级追踪）
            depth: 递归深度（0 表示顶层）
        
        Returns:
            (更新的 Plan, 更新的 State, 执行追踪)
        """
        # 如果传入了 trace，说明是递归调用，共享同一个 trace
        is_recursive = trace is not None
        if not is_recursive:
            trace = ExecutionTrace(plan_id=plan.plan_id)
            trace.push_plan(plan.plan_id)  # V2.2: 将初始 Plan 入栈
            trace.root_plan_id = plan.plan_id  # V2.2: 设置根 Plan
            trace.mark_running()
        
        # V2.3: AI Programming Agent - 最大修复次数限制
        # 初始化 fix_attempt_count（如果尚未设置）
        max_fix_attempts = state.get("max_fix_attempts", 5)
        if state.get("fix_attempt_count") is None:
            state.set_runtime("fix_attempt_count", 0)
            state.set_runtime("max_fix_attempts", max_fix_attempts)
        
        # 获取 trace_id
        trace_id = getattr(session, "trace_id", None) or f"atrace_{id(session)}"
        
        # 构建执行上下文
        from .planner import get_planner
        context = {
            "agent": agent,
            "session": session,
            "workspace": workspace,
            "state": state,
            "permissions": permissions or {},
            "trace_id": trace_id,
            "agent_id": agent.agent_id,
            "legacy_executor": self.legacy_executor,  # 传递 legacy executor 供 LLMExecutor 使用
            "current_plan": plan,  # V2.2: 追踪当前执行的 Plan
            "planner": get_planner(),  # V2.2: Planner 引用，供 REPLAN 使用
            "metrics": metrics,  # 可观测性：性能指标收集
        }
        
        last_skill_output = None  # 保存上一个 skill 的输出
        last_llm_response = None  # 保存上一步 LLM 的 response，供后续 skill 步骤 __from_previous_step 使用
        
        # 执行所有步骤
        for i, step in enumerate(plan.steps):
            # 检查是否需要将上一个 skill 的输出注入到当前 LLM 步骤
            if i > 0 and step.executor == ExecutorType.LLM:
                # 检查两种标记：_template_context 或 _inject_skill_output
                template_context = step.inputs.get("_template_context")
                inject_skill = step.inputs.get("_inject_skill_output")
                if (template_context == "skill_output" or inject_skill) and last_skill_output:
                    # 将 skill 输出注入到 messages 中
                    step.inputs = self._inject_skill_output(step.inputs, last_skill_output)
            
            # 若当前为 skill 步骤且 inputs 中含 __from_previous_step，用上一步 LLM 的 response 替换
            if step.executor == ExecutorType.SKILL and last_llm_response is not None:
                # _extract_patch 标记可能在 step.inputs 内部或 step.input_data 中
                # 需要同时检查两种位置
                extract_patch = False
                
                # 优先检查 step.input_data（Planner 直接创建的 LLM steps）
                if hasattr(step, 'input_data') and isinstance(step.input_data, dict):
                    extract_patch = step.input_data.get("_extract_patch", False)
                
                # 其次检查 step.inputs（某些情况下可能在这里）
                if not extract_patch and isinstance(step.inputs, dict):
                    extract_patch = step.inputs.get("_extract_patch", False)
                
                # 如果需要提取 patch，将标记传递给 _resolve_from_previous_step
                if extract_patch:
                    # 创建一个临时的 inputs 副本，添加 _extract_patch 标记
                    temp_inputs = dict(step.inputs) if isinstance(step.inputs, dict) else {}
                    temp_inputs["_extract_patch"] = True
                    step.inputs = self._resolve_from_previous_step(temp_inputs, last_llm_response)
                else:
                    step.inputs = self._resolve_from_previous_step(step.inputs, last_llm_response)
            
            step = await self._execute_step(step, state, context, trace, parent_step_id=parent_step_id, depth=depth)
            
            # 保存当前步骤的输出（供下一步注入或 __from_previous_step）
            if step.executor == ExecutorType.SKILL:
                last_skill_output = step.outputs
            elif step.executor == ExecutorType.LLM and step.outputs:
                last_llm_response = step.outputs.get("response") if isinstance(step.outputs, dict) else None
                # 若该 LLM 步要求输出 unified diff，则在本步做强校验
                if step.status == StepStatus.COMPLETED and isinstance(step.inputs, dict) and step.inputs.get("_expect_unified_diff"):
                    extracted = self._extract_unified_diff(last_llm_response or "")
                    if not extracted:
                        step.status = StepStatus.FAILED
                        step.error = "LLM did not produce a valid unified diff patch"
                        step.outputs = {"error": step.error, "response": last_llm_response}
                    else:
                        # 将标准化后的 patch 回写，供后续 __from_previous_step 直接使用
                        if isinstance(step.outputs, dict):
                            step.outputs["response"] = extracted
                        last_llm_response = extracted
                # 若该 LLM 步要求需求对齐校验，则强制解析结构化结果
                if step.status == StepStatus.COMPLETED and isinstance(step.inputs, dict) and step.inputs.get("_expect_alignment_check"):
                    payload = self._extract_json_object(last_llm_response or "")
                    aligned = False
                    reason = "alignment check returned invalid JSON"
                    if isinstance(payload, dict):
                        if isinstance(payload.get("aligned"), bool):
                            aligned = payload.get("aligned")
                        elif isinstance(payload.get("status"), str):
                            aligned = payload.get("status", "").strip().lower() in {"pass", "ok", "aligned", "success"}
                        reason_val = payload.get("reason")
                        if isinstance(reason_val, str) and reason_val.strip():
                            reason = reason_val.strip()
                    if not aligned:
                        step.status = StepStatus.FAILED
                        step.error = f"Requirement alignment check failed: {reason}"
                        step.outputs = {"error": step.error, "response": last_llm_response}
            
            # V2.2: 检查失败后是否需要重规划
            if step.status == StepStatus.FAILED:
                # 记录失败信息供后续重规划使用
                context["last_failed_step"] = step
                context["last_error"] = step.error
                context["last_step_outputs"] = step.outputs
                
                # V2.3: 检查并增加修复次数
                fix_attempt_count = state.get("fix_attempt_count", 0) + 1
                max_fix_attempts = state.get("max_fix_attempts", 5)
                
                if fix_attempt_count > max_fix_attempts:
                    logger.warning(f"[PlanBasedExecutor] Max fix attempts ({max_fix_attempts}) exceeded, stopping execution")
                    step.error = f"Maximum fix attempts ({max_fix_attempts}) exceeded. Please review the issue manually."
                    break
                
                state.set_runtime("fix_attempt_count", fix_attempt_count)
                logger.info(f"[PlanBasedExecutor] Fix attempt {fix_attempt_count}/{max_fix_attempts}")
                
                # 检查是否配置了 on_failure_replan
                on_failure = step.on_failure_replan
                if on_failure:
                    if metrics:
                        metrics.replan_count = getattr(metrics, "replan_count", 0) + 1
                    log_structured("PlanBasedExecutor", "replan_triggered", step_id=step.step_id, reason="on_failure_replan")
                    logger.info(f"[PlanBasedExecutor] Step {step.step_id} failed, triggering on_failure_replan")
                    # 替换占位符
                    replan_instruction = self._format_replan_prompt(
                        replan_prompt=on_failure,
                        failed_step=step,
                        agent=agent,
                        state=state
                    )
                    # 创建 REPLAN 步骤并执行
                    from .models import create_replan_step
                    replan_step = create_replan_step(
                        replan_instruction=replan_instruction,
                        executor=ExecutorType.LLM,
                    )
                    replan_step.inputs["_on_failure"] = True
                    # 执行 REPLAN 步骤
                    replan_step = await self._execute_step(
                        replan_step, state, context, trace, 
                        parent_step_id=step.step_id, depth=depth
                    )
                    # REPLAN 步骤也失败，停止执行
                    if replan_step.status == StepStatus.FAILED:
                        logger.warning(f"[PlanBasedExecutor] REPLAN step failed, stopping execution")
                        break
                    # REPLAN 成功：将原失败步骤标记为已恢复，避免最终状态被误判为 failed
                    followup_plan_id = replan_step.outputs.get("followup_plan_id")
                    step.status = StepStatus.COMPLETED
                    step.error = None
                    step.outputs = {
                        **(step.outputs or {}),
                        "recovered_by_replan": True,
                        "replan_followup_plan_id": followup_plan_id,
                    }
                    # REPLAN 成功，继续执行
                    continue
                
                # 默认策略：
                # - 对 skill 步骤：默认 stop（fail-fast），避免在错误结果上继续生成错误结论
                # - 其他步骤：保持原行为 continue
                # V2.2: 失败策略（优先使用 agent 配置）
                failure_strategy = plan.failure_strategy
                if not failure_strategy:
                    # 从 agent 获取 on_failure_strategy 配置
                    agent_failure = getattr(agent, "on_failure_strategy", None)
                    if agent_failure:
                        failure_strategy = agent_failure
                    else:
                        failure_strategy = "stop" if step.executor == ExecutorType.SKILL else "continue"
                
                if failure_strategy == "stop":
                    logger.warning(f"[PlanBasedExecutor] Step {step.step_id} failed, stopping execution")
                    break
                elif failure_strategy == "replan":
                    # 使用 agent 级别的 replan_prompt 创建并执行 REPLAN 步骤（与前端配置一致）
                    from .models import create_replan_step
                    replan_prompt_raw = (
                        (getattr(agent, "replan_prompt", None) or "").strip()
                        or "上一步失败。请根据错误原因重规划并重试，必要时改用其他可用技能。"
                    )
                    # 替换占位符
                    replan_instruction = self._format_replan_prompt(
                        replan_prompt=replan_prompt_raw,
                        failed_step=step,
                        agent=agent,
                        state=state
                    )
                    if metrics:
                        metrics.replan_count = getattr(metrics, "replan_count", 0) + 1
                    log_structured("PlanBasedExecutor", "replan_triggered", step_id=step.step_id, reason="agent_replan")
                    logger.info(f"[PlanBasedExecutor] Step {step.step_id} failed, triggering agent-level replan")
                    replan_step = create_replan_step(replan_instruction=replan_instruction, executor=ExecutorType.LLM)
                    replan_step.inputs["_on_failure"] = True
                    replan_step = await self._execute_step(
                        replan_step, state, context, trace,
                        parent_step_id=step.step_id, depth=depth
                    )
                    if replan_step.status == StepStatus.FAILED:
                        logger.warning(f"[PlanBasedExecutor] REPLAN step failed, stopping execution")
                        break
                    # REPLAN 成功：将原失败步骤标记为已恢复，避免最终状态被误判为 failed
                    followup_plan_id = replan_step.outputs.get("followup_plan_id")
                    step.status = StepStatus.COMPLETED
                    step.error = None
                    step.outputs = {
                        **(step.outputs or {}),
                        "recovered_by_replan": True,
                        "replan_followup_plan_id": followup_plan_id,
                    }
                    continue
                # continue
                logger.info(f"[PlanBasedExecutor] Step {step.step_id} failed, continuing to next step")
        
        # 确定最终状态（仅顶层调用修改 trace.final_status，递归调用不修改）
        if not is_recursive:
            all_completed = all(s.status == StepStatus.COMPLETED for s in plan.steps)
            any_failed = any(s.status == StepStatus.FAILED for s in plan.steps)
            
            if all_completed:
                trace.mark_completed()
            elif any_failed:
                trace.mark_failed()
            else:
                trace.final_status = "running"
            
            if metrics:
                metrics.plan_id = plan.plan_id
                metrics.step_count = len(plan.steps)
                metrics.final_status = trace.final_status
            log_structured(
                "PlanBasedExecutor", "plan_finished",
                plan_id=plan.plan_id, final_status=trace.final_status, step_count=len(plan.steps),
            )
            logger.info(
                f"[PlanBasedExecutor] Plan {plan.plan_id} finished with status: {trace.final_status}"
            )
        else:
            # 递归调用：不修改 trace.final_status，由顶层调用者决定
            logger.debug(
                f"[PlanBasedExecutor] Sub-plan {plan.plan_id} finished (recursive, not updating trace.final_status)"
            )
        
        return plan, state, trace

    def _inject_skill_output(self, inputs: Dict[str, Any], skill_output: Any) -> Dict[str, Any]:
        """
        将 skill 输出注入到 LLM 输入中
        
        通用设计：将 skill 输出作为上下文添加到用户消息中
        
        修复：正确处理失败情况，提取错误信息和工具输出（包括 exit_code, stderr 等）
        """
        import json
        
        def _clip(text: Any, max_len: int = 4000) -> str:
            s = "" if text is None else str(text)
            if len(s) <= max_len:
                return s
            return s[:max_len] + "...(truncated)"
        
        def _filter_output(output_data: Any) -> Any:
            """
            过滤输出数据，移除过大的 base64 字段
            """
            if not isinstance(output_data, dict):
                return output_data
            
            filtered = {}
            for key, value in output_data.items():
                # 跳过 base64 相关的大字段
                if key in ("annotated_image", "image", "base64") and isinstance(value, str) and len(value) > 1000:
                    filtered[key] = f"<{key} (length: {len(value)})>"
                elif isinstance(value, dict):
                    filtered[key] = _filter_output(value)
                elif isinstance(value, list):
                    filtered[key] = [
                        _filter_output(item) if isinstance(item, dict) else item
                        for item in value
                    ]
                else:
                    filtered[key] = value
            return filtered
        
        # 提取 skill 输出内容
        skill_text = ""
        if skill_output and isinstance(skill_output, dict):
            result = skill_output.get("result", {})
            
            # Skill v2 格式兼容：如果没有 result 但有 output，使用 output 作为 result
            if not result and "output" in skill_output:
                result = skill_output
            
            if isinstance(result, dict):
                # 检查是否有错误
                error = result.get("error")
                output_data = result.get("output")
                
                if error:
                    # 失败情况：优先显示错误信息
                    skill_text = f"执行失败：{_clip(error, 2000)}\n"
                    
                    # 如果 output_data 存在（即使失败，tool 也可能返回部分数据，如 exit_code, stdout, stderr），也包含它
                    if output_data:
                        if isinstance(output_data, dict):
                            # 提取关键字段（exit_code, stdout, stderr）
                            exit_code = output_data.get("exit_code")
                            stdout = _clip(output_data.get("stdout", ""), 4000)
                            stderr = _clip(output_data.get("stderr", ""), 4000)
                            
                            details = []
                            if exit_code is not None:
                                details.append(f"退出码: {exit_code}")
                            if stdout:
                                details.append(f"标准输出:\n{stdout}")
                            if stderr:
                                details.append(f"错误输出:\n{stderr}")
                            
                            if details:
                                skill_text += "\n".join(details)
                        else:
                            skill_text += f"输出数据: {json.dumps(output_data, ensure_ascii=False, indent=2)}"
                elif output_data:
                    # 成功情况：正常处理输出
                    # 先过滤掉 base64 等大字段
                    filtered_output = _filter_output(output_data)
                    
                    # 优先使用 summary 字段（通用设计：任何 skill 如果返回格式化的 summary，优先使用）
                    if isinstance(filtered_output, dict) and "summary" in filtered_output:
                        summary_text = filtered_output.get("summary", "")
                        if summary_text and len(str(summary_text)) > 50:
                            # 使用已格式化的 summary
                            skill_text = str(summary_text)
                        else:
                            # summary 太短，使用完整输出
                            skill_text = json.dumps(filtered_output, ensure_ascii=False, indent=2)
                    elif isinstance(filtered_output, str):
                        # 尝试解析 JSON 字符串
                        try:
                            data = json.loads(filtered_output)
                            skill_text = json.dumps(data, ensure_ascii=False, indent=2)
                        except:
                            skill_text = filtered_output
                    elif isinstance(filtered_output, dict):
                        skill_text = json.dumps(filtered_output, ensure_ascii=False, indent=2)
                    else:
                        skill_text = str(filtered_output)
        
        if not skill_text:
            skill_text = "无输出"
        
        # 替换 messages 中的模板变量，或直接添加到用户消息
        inputs = dict(inputs)  # 复制
        messages = inputs.get("messages", [])
        new_messages = []
        
        # 增强：在代码生成步骤中，强制要求 LLM 先复述需求
        is_code_generation = any(
            "代码生成器" in (msg.get("content", "") or "")
            for msg in messages
            if msg.get("role") == "system"
        )
        
        for msg in messages:
            msg = dict(msg)
            content = msg.get("content", "")
            
            # 如果有模板变量，替换它
            if "{{skill_output}}" in content:
                content = content.replace("{{skill_output}}", skill_text)
            elif msg.get("role") == "user":
                # 在用户消息中添加 skill 输出作为上下文
                content = f"{content}\n\n以下是技能执行结果：\n{skill_text}"
            
            # 增强：在代码生成步骤中，在用户需求后添加强制约束
            if is_code_generation and msg.get("role") == "user" and "用户需求：" in content:
                # 提取用户需求部分
                user_req_match = re.search(r"用户需求：([^\n]+)", content)
                if user_req_match:
                    user_req = user_req_match.group(1).strip()
                    content += f"\n\n【强制约束】你必须实现以下具体功能：{user_req}\n禁止假设其他功能，禁止生成示例代码或无关功能。"
            
            msg["content"] = content
            new_messages.append(msg)
        
        inputs["messages"] = new_messages
        
        # 移除模板标记
        inputs.pop("_template_context", None)
        inputs.pop("_inject_skill_output", None)
        
        return inputs

    @staticmethod
    def _extract_unified_diff(text: str) -> Optional[str]:
        """
        从文本中提取 unified diff（以 --- / +++ / @@ 开头的 patch）。
        返回 None 表示未提取到有效 patch。
        """
        if not isinstance(text, str) or not text.strip():
            return None
        raw = text.strip()
        # 先去掉 <think> 包裹内容
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
        # 优先提取 ```diff ... ```
        m_block = re.search(r"```(?:diff)?\s*(--- .+?)```", raw, flags=re.DOTALL | re.IGNORECASE)
        candidate = m_block.group(1).strip() if m_block else raw
        # 从首个 --- 行开始截取
        m_patch = re.search(r"(^--- .+)", candidate, flags=re.DOTALL | re.MULTILINE)
        if not m_patch:
            return None
        patch = m_patch.group(1).strip()
        if not patch.startswith("--- ") or "\n+++ " not in patch or "\n@@ " not in patch:
            return None
        return patch

    @staticmethod
    def _resolve_from_previous_step(inputs: Dict[str, Any], previous_text: str) -> Dict[str, Any]:
        """
        将 skill 步骤 inputs 中值为 __from_previous_step 的项替换为上一步 LLM 的 response 文本。
        用于 replan 修复链中 apply_patch 步骤从上一 LLM 步获取生成的 patch 内容。
        
        增强：自动从 LLM response 中提取纯 patch（去除 <think> 标签和解释文字）
        """
        if previous_text is None:
            previous_text = ""
        if not isinstance(inputs, dict):
            return inputs
        
        # 检查是否需要提取纯 patch
        extract_patch = inputs.get("_extract_patch", False)
        if extract_patch and isinstance(previous_text, str):
            extracted = PlanBasedExecutor._extract_unified_diff(previous_text)
            if extracted:
                logger.info(f"[Executor] Extracted pure patch from LLM response ({len(extracted)} chars)")
                previous_text = extracted
            else:
                logger.warning("[Executor] Failed to extract unified diff from previous LLM output")
                previous_text = ""
        
        def _extract_json_field(text: str, field: str) -> str:
            if not isinstance(text, str) or not text.strip():
                return ""
            raw = text.strip()
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
            raw = re.sub(r"<think>[\s\S]*$", "", raw, flags=re.IGNORECASE).strip()
            # fenced json
            m_block = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw, flags=re.IGNORECASE)
            candidate = m_block.group(1).strip() if m_block else raw
            # try parse whole
            payload = None
            try:
                payload = json.loads(candidate)
            except Exception:
                # fallback: first object-like segment
                m_obj = re.search(r"(\{[\s\S]*\})", candidate)
                if m_obj:
                    try:
                        payload = json.loads(m_obj.group(1))
                    except Exception:
                        payload = None
            if not isinstance(payload, dict):
                return ""
            value = payload.get(field)
            if value is None:
                return ""
            if isinstance(value, str):
                return value
            return json.dumps(value, ensure_ascii=False)

        out = dict(inputs)
        inner = out.get("inputs")
        if isinstance(inner, dict):
            base_hint = inner.get("_json_path_base")
            base_hint = base_hint.strip() if isinstance(base_hint, str) else ""
            new_inner = {}
            for k, v in inner.items():
                if v == "__from_previous_step":
                    new_inner[k] = previous_text if isinstance(previous_text, str) else str(previous_text)
                elif isinstance(v, str) and v.startswith("__from_previous_step_json:"):
                    field = v.split(":", 1)[1].strip()
                    value = _extract_json_field(previous_text, field)
                    if field == "path" and isinstance(value, str):
                        resolved = value.strip()
                        if resolved and base_hint:
                            p = Path(resolved).expanduser()
                            if not p.is_absolute():
                                resolved = str((Path(base_hint).expanduser() / p).resolve())
                        value = resolved
                    new_inner[k] = value
                else:
                    new_inner[k] = v
            # internal control key, should not be forwarded to skills
            new_inner.pop("_json_path_base", None)
            out["inputs"] = new_inner
        
        # 移除提取标记
        out.pop("_extract_patch", None)
        
        return out

    async def _execute_step(
        self,
        step: Step,
        state: AgentState,
        context: Dict[str, Any],
        trace: ExecutionTrace,
        parent_step_id: Optional[str] = None,
        depth: int = 0
    ) -> Step:
        """
        执行单个步骤（支持层级）
        
        处理 atomic 和 composite 两种类型
        
        Args:
            trace: 执行追踪对象
            parent_step_id: 父步骤 ID，用于层级追踪
            depth: 递归深度，0 表示顶层
        """
        step_start = time.perf_counter()
        metrics = context.get("metrics")
        
        # 记录开始日志（包含层级信息）
        start_log = StepLog(
            step_id=step.step_id,
            parent_step_id=parent_step_id,
            depth=depth,
            event_type="start",
            input_data=step.inputs,
        )
        trace.add_log(start_log)
        log_structured(
            "PlanBasedExecutor", "step_start",
            step_id=step.step_id, executor=step.executor.value if hasattr(step.executor, "value") else str(step.executor), depth=depth,
        )
        
        if step.type == StepType.COMPOSITE and step.sub_plan:
            # Composite 步骤：递归执行 sub_plan
            step = await self._execute_composite(step, state, context, trace, parent_step_id=step.step_id, depth=depth + 1)
        elif step.type == StepType.REPLAN:
            # V2.2: REPLAN 步骤：生成新 Plan 并执行
            step = await self._execute_replan(step, state, context, trace, parent_step_id=parent_step_id, depth=depth)
        else:
            # Atomic 步骤：直接执行
            step = await self._execute_atomic(step, state, context)
        
        duration_ms = (time.perf_counter() - step_start) * 1000
        if metrics:
            metrics.step_durations_ms[step.step_id] = duration_ms
        
        # 记录完成日志（包含层级信息与耗时）
        complete_log = StepLog(
            step_id=step.step_id,
            parent_step_id=parent_step_id,
            depth=depth,
            event_type="complete",
            input_data=step.inputs,
            output_data=step.outputs,
            duration_ms=round(duration_ms, 2),
        )
        # 兼容前端：skill 执行步骤添加 skill_call 事件类型
        if step.executor == ExecutorType.SKILL:
            complete_log.event_type = "skill_call"
            # 确保 output_data 包含完整结果
            if step.outputs and "result" in step.outputs:
                complete_log.output_data = step.outputs.get("result", {})
            # 添加 skill_id 便于前端过滤
            skill_id = step.inputs.get("skill_id")
            if skill_id:
                complete_log.tool_id = skill_id
        
        if step.error:
            complete_log.event_type = "error"
            complete_log.output_data = {"error": step.error}
        
        trace.add_log(complete_log)
        log_structured(
            "PlanBasedExecutor", "step_finished",
            step_id=step.step_id, status=step.status.value if hasattr(step.status, "value") else str(step.status),
            duration_ms=round(duration_ms, 2), has_error=bool(step.error),
        )
        
        return step

    async def _execute_atomic(
        self,
        step: Step,
        state: AgentState,
        context: Dict[str, Any]
    ) -> Step:
        """
        执行原子步骤
        
        根据 step.executor 类型选择对应的执行器
        """
        executor_type = step.executor if isinstance(step.executor, ExecutorType) else ExecutorType(step.executor)
        
        try:
            executor = ExecutorFactory.get_executor(executor_type)
            step = await executor.execute(step, state, context)
        except Exception as e:
            logger.error(f"[PlanBasedExecutor] Atomic step {step.step_id} execution error: {e}")
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.outputs = {"error": str(e)}
        
        return step

    async def _execute_composite(
        self,
        step: Step,
        state: AgentState,
        context: Dict[str, Any],
        trace: ExecutionTrace,
        parent_step_id: Optional[str] = None,
        depth: int = 0
    ) -> Step:
        """
        执行组合步骤
        
        递归执行 sub_plan，共享同一个 trace
        
        Args:
            trace: 执行追踪对象（与父计划共享）
            parent_step_id: 父步骤 ID，用于层级追踪
            depth: 递归深度
        """
        if not step.sub_plan:
            step.status = StepStatus.COMPLETED
            step.outputs = {"message": "No sub_plan to execute"}
            return step
        
        step.status = StepStatus.RUNNING
        
        try:
            # 递归执行 sub_plan
            # 注意：共享同一个 trace、state 和 context
            sub_plan, state, trace = await self.execute_plan(
                step.sub_plan,
                state,
                context.get("session"),
                context.get("agent"),
                context.get("workspace", "."),
                permissions=context.get("permissions"),
                trace=trace,  # 共享同一个 trace
                parent_step_id=step.step_id,  # 当前 composite step 作为子计划的父步骤
                depth=depth + 1  # 深度递增
            )
            
            # 更新 sub_plan 引用
            step.sub_plan = sub_plan
            
            # 根据子计划内步骤的状态确定步骤状态（不依赖 trace.final_status，因为递归调用不修改它）
            if not sub_plan.steps:
                step.status = StepStatus.COMPLETED
            else:
                all_completed = all(s.status == StepStatus.COMPLETED for s in sub_plan.steps)
                any_failed = any(s.status == StepStatus.FAILED for s in sub_plan.steps)
                
                if all_completed:
                    step.status = StepStatus.COMPLETED
                elif any_failed:
                    step.status = StepStatus.FAILED
                else:
                    step.status = StepStatus.COMPLETED  # 视为完成
            
            # Phase A: 包含子图日志数量
            all_logs = trace.get_all_logs_with_hierarchy()
            step.outputs = {
                "sub_plan_id": sub_plan.plan_id,
                "sub_plan_status": "completed" if step.status == StepStatus.COMPLETED else "failed",
                "step_logs_count": len(trace.step_logs),
                "total_logs_with_subgraphs": len(all_logs),
                "subgraph_count": len(trace.subgraph_traces),
            }
            
        except Exception as e:
            logger.error(f"[PlanBasedExecutor] Composite step {step.step_id} execution error: {e}")
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.outputs = {"error": str(e)}
        
        return step

    def _format_replan_prompt(
        self,
        replan_prompt: str,
        failed_step: Step,
        agent: AgentDefinition,
        state: AgentState
    ) -> str:
        """
        替换 replan_prompt 中的占位符
        
        通用占位符（推荐）：
        - {failed_step_id}
        - {failed_step_executor}
        - {failed_step_error}
        - {failed_step_inputs_json}
        - {failed_step_outputs_json}
        - {replan_count}
        - {replan_limit}
        
        编程场景兼容占位符（可选）：
        - {test_command}
        - {exit_code}
        - {stdout}
        - {stderr}
        - {fix_iteration} / {max_fix_iterations}  (兼容旧模板，等价于 replan_count / replan_limit)
        
        Args:
            replan_prompt: 包含占位符的 replan prompt 模板
            failed_step: 失败的步骤
            agent: Agent 定义
            state: Agent 状态
        
        Returns:
            替换占位符后的 replan prompt
        """
        def _truncate(value: Any, max_len: int) -> str:
            text = str(value) if value is not None else ""
            if len(text) <= max_len:
                return text
            return text[:max_len] + "...(truncated)"

        # 获取失败步骤的输出和输入
        step_outputs = failed_step.outputs or {}
        step_inputs = failed_step.inputs or {}
        
        # 提取命令（优先从 outputs，其次从 inputs）
        # 对于 shell.run，command 可能在 outputs 中（执行结果）或 inputs 中（原始输入）
        # 注意：skill step 的 inputs 格式为 {"skill_id": "...", "inputs": {"command": "..."}}
        command = (
            step_outputs.get("command") 
            or step_inputs.get("command")
            or (step_inputs.get("inputs") or {}).get("command")
            or ""
        )
        
        # 提取其他字段
        # 对于 skill step，实际数据在 step_outputs["result"]["output"] 中（如果成功）
        # 如果失败，可能在 step_outputs["result"]["error"] 的错误消息中，或 step_outputs["result"]["output"] 中（即使失败也可能有部分数据）
        result = step_outputs.get("result", {})
        tool_output = result.get("output") if isinstance(result, dict) else None
        
        # 优先从 tool_output 中提取
        if isinstance(tool_output, dict):
            exit_code = tool_output.get("exit_code", "")
            stdout = tool_output.get("stdout", "")
            stderr = tool_output.get("stderr", "")
        else:
            # 如果 tool_output 不存在，尝试从 step_outputs 直接获取（向后兼容）
            exit_code = step_outputs.get("exit_code", "")
            stdout = step_outputs.get("stdout", "")
            stderr = step_outputs.get("stderr", "")
            
            # 如果仍然没有，尝试从错误消息中解析 exit_code
            if exit_code == "" and isinstance(result, dict):
                error_msg = result.get("error", "")
                if error_msg and "exit_code=" in error_msg:
                    import re as re_module
                    match = re_module.search(r"exit_code=(\d+)", error_msg)
                    if match:
                        exit_code = match.group(1)
        
        # 更通用的失败错误摘要
        failed_error = (
            failed_step.error
            or (result.get("error") if isinstance(result, dict) else None)
            or step_outputs.get("error")
            or "Step execution failed"
        )
        
        # 获取修复次数
        replan_count = state.runtime_state.get("replan_count", 0) + 1
        replan_limit = getattr(agent, "max_replan_count", 3) or 3
        
        # 准备替换字典
        replacements = {
            # Generic placeholders
            "failed_step_id": _truncate(failed_step.step_id, 256),
            "failed_step_executor": _truncate(
                failed_step.executor.value if hasattr(failed_step.executor, "value") else failed_step.executor,
                256,
            ),
            "failed_step_error": _truncate(failed_error, MAX_REPLAN_TEXT_PLACEHOLDER_LEN),
            "failed_step_inputs_json": _truncate(
                json.dumps(step_inputs, ensure_ascii=False, default=str),
                MAX_REPLAN_JSON_PLACEHOLDER_LEN,
            ),
            "failed_step_outputs_json": _truncate(
                json.dumps(step_outputs, ensure_ascii=False, default=str),
                MAX_REPLAN_JSON_PLACEHOLDER_LEN,
            ),
            "replan_count": replan_count,
            "replan_limit": replan_limit,
            # Backward-compatible placeholders
            "test_command": _truncate(command, MAX_REPLAN_TEXT_PLACEHOLDER_LEN),
            "exit_code": exit_code if exit_code != "" else "N/A",
            "stdout": _truncate(stdout if stdout else "(无输出)", MAX_REPLAN_TEXT_PLACEHOLDER_LEN),
            "stderr": _truncate(stderr if stderr else "(无错误)", MAX_REPLAN_TEXT_PLACEHOLDER_LEN),
            "fix_iteration": replan_count,
            "max_fix_iterations": replan_limit,
        }

        # White-list check for placeholders in template
        template_vars = set(re.findall(r"\{(\w+)\}", replan_prompt or ""))
        unsupported = sorted(v for v in template_vars if v not in ALLOWED_REPLAN_PLACEHOLDERS)
        if unsupported:
            logger.warning(
                f"[PlanBasedExecutor] Unsupported placeholders in replan prompt: {unsupported}"
            )
        
        # 使用安全的替换方式：先检查占位符是否存在，再替换
        # 使用正则表达式匹配 {variable} 格式的占位符
        def replace_placeholder(match):
            var_name = match.group(1)
            return str(replacements.get(var_name, match.group(0)))  # 如果占位符不存在，保持原样
        
        # 替换所有 {variable} 格式的占位符
        formatted = re.sub(r'\{(\w+)\}', replace_placeholder, replan_prompt)
        
        return formatted

    async def _execute_replan(
        self,
        step: Step,
        state: AgentState,
        context: Dict[str, Any],
        trace: ExecutionTrace,
        parent_step_id: Optional[str] = None,
        depth: int = 0
    ) -> Step:
        """
        执行重规划步骤（V2.2）
        
        1. 调用 Planner.create_followup_plan 生成新 Plan
        2. 将新 Plan 入栈（trace.push_plan）
        3. 执行新 Plan（递归调用 execute_plan）
        4. 执行完成后出栈（trace.pop_plan）
        """
        step.status = StepStatus.RUNNING
        pushed_followup_plan = False
        followup_plan_id: Optional[str] = None
        
        try:
            agent = context.get("agent")
            session = context.get("session")
            planner = context.get("planner")
            
            if not planner:
                raise ValueError("Planner not found in context")
            
            # V2.2: 检查重规划次数限制（从 agent 配置获取，默认 3）
            max_replan = getattr(agent, "max_replan_count", 3) or 3
            current_replan_count = state.runtime_state.get("replan_count", 0)
            if current_replan_count >= max_replan:
                logger.warning(f"[PlanBasedExecutor] REPLAN step {step.step_id}: max replan count {max_replan} reached")
                step.status = StepStatus.FAILED
                step.error = f"Maximum replan count ({max_replan}) exceeded"
                step.outputs = {"error": step.error, "replan_count": current_replan_count}
                return step
            # 增加重规划计数
            state.set_runtime("replan_count", current_replan_count + 1)
            
            # 构建重规划上下文
            # 从 context 获取当前 Plan 的 goal 作为 user_input
            current_plan = context.get("current_plan")
            user_input = current_plan.goal if current_plan else ""
            replan_context = {
                **context,
                "replan_instruction": step.replan_instruction,
                "last_failed_step": context.get("last_failed_step"),
                "last_error": context.get("last_error"),
                "current_plan": current_plan,
                "user_input": user_input,  # 添加原始用户输入供意图检测使用
            }
            
            # 调用 Planner 生成后续 Plan
            followup_plan = await planner.create_followup_plan(
                agent=agent,
                execution_context=replan_context,
                parent_plan_id=trace.current_plan_id(),  # 当前 Plan 作为父 Plan（planner 内部会设置 parent_plan_id）
            )
            followup_plan_id = followup_plan.plan_id
            
            # 将新 Plan 入栈
            trace.push_plan(followup_plan.plan_id)
            pushed_followup_plan = True
            # V2.2: 如果没有根 Plan ID，设置当前 Plan 为根
            if trace.root_plan_id is None:
                trace.root_plan_id = followup_plan.plan_id
            
            # 执行新 Plan（递归调用 execute_plan）
            followup_plan, state, trace = await self.execute_plan(
                followup_plan,
                state,
                session,
                agent,
                workspace=context.get("workspace", "."),
                permissions=context.get("permissions"),
                trace=trace,  # 共享同一个 trace
                parent_step_id=step.step_id,  # REPLAN step 作为新 Plan 的父步骤
                depth=depth + 1,
            )
            
            # 执行完成后出栈
            trace.pop_plan()
            
            # 根据新 Plan 的执行结果确定 REPLAN 步骤状态
            # 注意：这里需要检查 followup_plan.steps 的状态，而不是 trace.final_status
            # 因为 trace.final_status 可能被其他 Plan 修改
            if not followup_plan.steps:
                step.status = StepStatus.COMPLETED
            else:
                all_completed = all(s.status == StepStatus.COMPLETED for s in followup_plan.steps)
                any_failed = any(s.status == StepStatus.FAILED for s in followup_plan.steps)
                
                if all_completed:
                    step.status = StepStatus.COMPLETED
                elif any_failed:
                    step.status = StepStatus.FAILED
                else:
                    step.status = StepStatus.COMPLETED  # 视为完成
            
            # Phase A: 包含子图日志数量
            all_logs = trace.get_all_logs_with_hierarchy()
            step.outputs = {
                "followup_plan_id": followup_plan.plan_id,
                "followup_plan_status": "completed" if step.status == StepStatus.COMPLETED else "failed",
                "step_logs_count": len(trace.step_logs),
                "total_logs_with_subgraphs": len(all_logs),
                "subgraph_count": len(trace.subgraph_traces),
            }
            
        except Exception as e:
            logger.error(f"[PlanBasedExecutor] REPLAN step {step.step_id} execution error: {e}")
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.outputs = {"error": str(e)}
            # 仅在当前 REPLAN 已经成功入栈 followup_plan 时才出栈，避免误弹出父/根 plan
            try:
                if pushed_followup_plan and trace.current_plan_id() == followup_plan_id:
                    trace.pop_plan()
            except Exception:
                logger.debug("[PlanBasedExecutor] Failed to pop followup plan from trace stack safely")
        
        return step
