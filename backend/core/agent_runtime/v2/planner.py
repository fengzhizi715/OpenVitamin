"""
Agent V2 Planner
将用户输入转换为执行计划

通用设计：
- Planner 不硬编码任何业务逻辑
- 由 Agent 的 system_prompt 定义行为
- 支持 Skills 时，由 LLM 决定使用哪个 Skill
"""
from typing import Any, Dict, List, Optional
import re
import uuid
from pathlib import Path

from log import logger, log_structured
from .planner_utils import (
    extract_record_filename,
    extract_shell_command,
    extract_path_from_text,
    extract_workspace_from_text,
    extract_image_from_text,
    strip_injected_workspace_hints,
    keyword_matches,
    match_configured_intent_rules,
    get_replan_direct_skill_config,
    classify_replan_failure,
    extract_filename_from_error,
    extract_command_from_context,
)
from core.agent_runtime.definition import AgentDefinition
from core.types import Message
from .models import (
    Plan,
    Step,
    StepType,
    ExecutorType,
    create_atomic_step,
    create_simple_plan,
)
from .plan_contract_adapter import (
    adapt_contract_to_runtime_plan,
    try_parse_contract_plan,
)


class Planner:
    """
    通用计划生成器
    
    设计原则：
    1. 不硬编码任何意图或技能路由
    2. 由 Agent 的 system_prompt 定义行为
    3. 支持 Skills 时，让 LLM 决定如何调用
    """

    async def create_plan(
        self,
        agent: AgentDefinition,
        user_input: str,
        messages: List[Message],
        context: Optional[Dict[str, Any]] = None
    ) -> Plan:
        """
        创建执行计划
        
        Args:
            agent: Agent 定义（包含 system_prompt 定义行为）
            user_input: 用户输入
            messages: 完整消息历史
            context: 额外上下文（workspace, permissions, user_id 等）
        
        Returns:
            Plan: 可执行的计划
        """
        context = context or {}
        
        log_structured("Planner", "plan_create_start", agent_id=agent.agent_id)
        logger.info(f"[Planner] Creating plan for agent {agent.agent_id}")
        
        # 从 model_params 获取 record_file 配置（优先级高），兼容旧版从 system_prompt 提取
        record_file = None
        if agent.model_params:
            record_file = agent.model_params.get("record_file")
        if not record_file:
            # 兼容旧版：从 system_prompt 中提取
            record_file = extract_record_filename(agent.system_prompt or "")
        
        plan_context = {
            "agent_id": agent.agent_id,
            "model_id": agent.model_id,
            "user_input": user_input,
            "workspace": context.get("workspace", "."),
            "skills": agent.enabled_skills or [],
            "user_id": context.get("user_id", "default"),
            "session_id": context.get("session_id", context.get("user_id", "default")),
            "record_file": record_file,
            "model_params": agent.model_params or {},
        }
        
        # 如果有启用的 Skills，使用 Skill-based 计划
        if agent.enabled_skills:
            plan = await self._create_skill_based_plan(agent, user_input, messages, plan_context)
        else:
            # 纯 LLM 对话
            plan = await self._create_llm_plan(agent, user_input, messages, plan_context)
        
        log_structured("Planner", "plan_created", plan_id=plan.plan_id, step_count=len(plan.steps), goal_preview=(plan.goal or "")[:80])
        logger.info(f"[Planner] Created plan {plan.plan_id} with {len(plan.steps)} steps")
        return plan

    async def _create_skill_based_plan(
        self,
        agent: AgentDefinition,
        user_input: str,
        messages: List[Message],
        context: Dict[str, Any],
    ) -> Plan:
        """
        创建基于技能的计划（支持技能链、单技能执行）
        
        逻辑：
        1. 检测用户意图和匹配的技能
        2. 如果检测到技能链，创建技能链计划
        3. 否则创建单技能执行计划
        """
        from core.skills.registry import SkillRegistry
        
        # 检测意图和技能匹配 - 返回 (skill_id, intent_type) 元组
        skill_match = self._detect_skill_and_intent(user_input, agent.enabled_skills, agent.model_params, messages)
        matched_skill_id, intent_type = skill_match
        
        if not matched_skill_id:
            # Feature creation intent fallback: route to project.analyze when intent rules miss
            if self._is_feature_creation_intent(user_input):
                enabled = set(agent.enabled_skills or [])
                if "builtin_project.analyze" in enabled:
                    matched_skill_id, intent_type = "builtin_project.analyze", "feature_fallback"
                elif "project.analyze" in enabled:
                    matched_skill_id, intent_type = "project.analyze", "feature_fallback"

        if not matched_skill_id and (agent.model_params or {}).get("use_skill_discovery"):
            # 运行时语义发现：在 enabled_skills 白名单内按用户输入做向量检索，取 top1
            logger.info(f"[Planner] Trying semantic discovery for: {user_input[:50]}...")
            discovered_id = await self._discover_skill_semantic(agent, user_input, context)
            if discovered_id:
                matched_skill_id, intent_type = discovered_id, "semantic_discovery"
                logger.info(f"[Planner] Semantic discovery matched skill: {matched_skill_id}")
            else:
                logger.info(f"[Planner] Semantic discovery returned no match")

        if not matched_skill_id:
            # 没有匹配到技能，降级为纯 LLM 计划
            logger.info(f"[Planner] No skill matched, falling back to LLM plan")
            return await self._create_llm_plan(agent, user_input, messages, context)
        
        logger.info(f"[Planner] Matched skill: {matched_skill_id} (intent={intent_type})")
        
        # Check for skill chain configuration in skill_param_extractors
        model_params = agent.model_params or {}
        skill_extractors = model_params.get("skill_param_extractors", {})
        matched_skill_config = skill_extractors.get(matched_skill_id, {})
        chain_skills = matched_skill_config.get("chain", [])
        
        # Only use skill chain for specific patterns (e.g., vision → vlm)
        # Development tasks (analyze → write) need LLM in between, so don't use chain
        is_vision_chain = matched_skill_id in ("builtin_vision.detect_objects", "vision.detect_objects")
        
        if is_vision_chain and chain_skills and isinstance(chain_skills, list):
            # Filter to only available skills
            available_chain = [s for s in chain_skills if s in agent.enabled_skills]
            if available_chain:
                logger.info(f"[Planner] Creating skill chain plan: {matched_skill_id} -> {available_chain}")
                return await self._create_skill_chain_plan(
                    agent, user_input, messages, context,
                    first_skill_id=matched_skill_id,
                    chain_skills=available_chain
                )

        # Feature creation workflow: analyze -> llm(json path+content) -> file.write -> llm summary
        if self._is_feature_creation_intent(user_input):
            feature_plan = await self._create_feature_creation_plan(agent, user_input, messages, context)
            if feature_plan is not None:
                return feature_plan
        
        # Optional: direct skill response mode (skip post-skill LLM), configured per-agent
        direct_response_ids = model_params.get("skill_direct_response_ids", [])
        if not isinstance(direct_response_ids, list):
            direct_response_ids = []
        direct_response_set = {str(s).strip() for s in direct_response_ids if isinstance(s, str) and str(s).strip()}

        # 兼容 builtin_ 前缀差异：例如配置了 project.analyze，实际匹配到 builtin_project.analyze
        if matched_skill_id.startswith("builtin_"):
            direct_response_set.add(matched_skill_id[len("builtin_"):])
        else:
            direct_response_set.add(f"builtin_{matched_skill_id}")
        use_direct_response = matched_skill_id in direct_response_set

        # Default: single skill execution plan with LLM response
        return await self._create_skill_execution_plan(
            agent, user_input, messages, context,
            skill_id=matched_skill_id,
            silent=use_direct_response
        )

    @staticmethod
    def _is_feature_creation_intent(user_input: str) -> bool:
        text = (user_input or "").lower()
        if not text:
            return False
        # 显式“写入/保存到某个文件”优先视为代码创建意图
        explicit_output_file = bool(
            re.search(
                r"(保存到|写入到|输出到|生成到|create|write|save).{0,30}([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]{1,8})",
                text,
                re.IGNORECASE,
            )
        )
        return bool(
            re.search(
                r"(新增|添加|创建|写个?|加个?|增加|做个?|实现).{0,30}(api|接口|service|服务|工具函数|工具方法|util|helper|function)",
                text,
                re.IGNORECASE,
            )
            or re.search(
                r"\b(add|create|implement)\b.{0,30}\b(api|endpoint|service|utility|helper|function)\b",
                text,
                re.IGNORECASE,
            )
            or re.search(
                r"(实现|编写|写|创建|生成).{0,30}(函数|方法|类|脚本|程序|模块|算法|代码)",
                text,
                re.IGNORECASE,
            )
            or explicit_output_file
        )

    @staticmethod
    def _extract_explicit_output_path(user_input: str, project_root: str) -> Optional[str]:
        """
        从用户输入中提取显式指定的输出文件路径（如“保存到 xxx.cpp”）。
        返回相对 project_root 的路径（若可转换），否则返回原始路径。
        """
        text = (user_input or "").strip()
        if not text:
            return None

        m = re.search(
            r"(?:保存到|写入到|输出到|生成到|create|write|save)\s*[:：]?\s*([^\s,，。；;]+?\.[A-Za-z0-9]{1,8})",
            text,
            flags=re.IGNORECASE,
        )
        if not m:
            return None

        raw_path = (m.group(1) or "").strip().strip("\"'`")
        if not raw_path:
            return None

        try:
            p = Path(raw_path).expanduser()
            root = Path(project_root).expanduser().resolve() if project_root else None
            if p.is_absolute() and root is not None:
                try:
                    return str(p.resolve().relative_to(root))
                except Exception:
                    return str(p.resolve())
            return str(p)
        except Exception:
            return raw_path

    async def _create_feature_creation_plan(
        self,
        agent: AgentDefinition,
        user_input: str,
        messages: List[Message],
        context: Dict[str, Any],
    ) -> Optional[Plan]:
        from core.skills.registry import SkillRegistry

        # Ensure registry loaded
        if not SkillRegistry._skills:
            SkillRegistry.load()

        enabled = set(agent.enabled_skills or [])
        analyze_skill_id = "builtin_project.analyze" if "builtin_project.analyze" in enabled else (
            "project.analyze" if "project.analyze" in enabled else None
        )
        write_skill_id = "builtin_file.write" if "builtin_file.write" in enabled else (
            "file.write" if "file.write" in enabled else None
        )
        read_skill_id = "builtin_file.read" if "builtin_file.read" in enabled else (
            "file.read" if "file.read" in enabled else None
        )
        if not analyze_skill_id or not write_skill_id:
            return None

        analyze_skill = SkillRegistry.get(analyze_skill_id)
        if not analyze_skill:
            return None

        plan = Plan(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            goal=f"Create feature for request: {user_input[:60]}",
            context={**(context or {}), "plan_source": "feature_creation_plan"},
        )
        plan.failure_strategy = "stop"

        # Step 1: Analyze project
        analyze_inputs = self._build_skill_inputs_simple(analyze_skill, user_input, context or {}, messages)
        plan.steps.append(
            create_atomic_step(
                executor=ExecutorType.SKILL,
                inputs={"skill_id": analyze_skill_id, "inputs": analyze_inputs},
            )
        )

        # 性能优化：feature_creation 默认走最小关键链路（analyze -> generate -> write -> read）。
        # 可通过 model_params.feature_creation_enable_extra_checks 显式开启额外 LLM 校验步骤。
        model_params = agent.model_params or {}
        enable_extra_checks = bool(model_params.get("feature_creation_enable_extra_checks", False))
        generate_max_tokens = int(
            model_params.get("agent_v2_codegen_max_tokens")
            or model_params.get("feature_creation_generate_max_tokens")
            or 2200
        )
        # 防止异常配置导致极端值
        if generate_max_tokens < 512:
            generate_max_tokens = 512
        if generate_max_tokens > 8192:
            generate_max_tokens = 8192

        # Step 2: Summarize project analysis for user (optional, disabled by default)
        project_root = extract_workspace_from_text(user_input, {"default_keywords": []}) or extract_path_from_text(user_input)
        target_project_root = (
            (analyze_inputs.get("workspace") if isinstance(analyze_inputs, dict) else None)
            or project_root
            or context.get("workspace", ".")
        )
        request_text = user_input or ""
        fallback_output_path = self._extract_explicit_output_path(request_text, str(target_project_root))
        if enable_extra_checks:
            plan.steps.append(
                create_atomic_step(
                    executor=ExecutorType.LLM,
                    inputs={
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "你是项目分析师。必须严格基于项目分析结果（JSON格式）回答，禁止编造或幻觉。\n\n"
                                    "请从项目分析结果中提取以下信息：\n"
                                    "1. 项目主语言：从 output.meta.language 字段读取\n"
                                    "2. 目录结构：从 output.structure.tree 字段读取\n"
                                    "3. 工具函数目录：从 output.structure.layered_guess.utils 数组中查找\n"
                                    "   - 排除包含 venv/site-packages 的路径\n"
                                    "   - 只选择项目内的路径（如 app/utils）\n"
                                    "4. 代码规范：从 output.framework 字段推断\n\n"
                                    "重要：必须使用项目分析结果中的实际数据，不要假设或编造项目类型。"
                                ),
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"用户需求：{user_input}\n"
                                    f"项目根目录：{target_project_root}\n"
                                    "请基于上一步的项目分析结果（JSON格式），解释项目结构和开发建议。"
                                ),
                            },
                        ],
                        "temperature": 0.2,
                        "max_tokens": 600,
                        "_inject_skill_output": True,
                    },
                )
            )

        # Step 3: Generate code as JSON
        codegen_step = create_atomic_step(
            executor=ExecutorType.LLM,
            inputs={
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是代码生成器。必须严格基于项目分析结果生成代码。\n\n"
                            "【第一步：从项目分析结果读取关键信息】\n"
                            "1. 主语言：从 output.meta.language 读取（如 \"python\"）\n"
                            "2. 工具函数目录：从 output.structure.layered_guess.utils 数组中找\n"
                            "   - 排除包含 venv/site-packages 的路径\n"
                            "   - 选择项目内的路径（如 \"app/utils\"）\n"
                            "3. 项目根目录：从 output.meta.repo_root 读取\n\n"
                            "【第二步：确定文件路径】\n"
                            "- path 格式：<工具函数目录>/<文件名>.<扩展名>\n"
                            "- 例如：app/utils/date_utils.py\n"
                            "- 扩展名必须与主语言匹配（python->.py）\n\n"
                            "【输出格式 - 必须严格遵守】\n"
                            "只输出一个 JSON 对象，不要有任何其他内容：\n"
                            "{\n"
                            '  "path": "<文件路径，相对于项目根目录>",\n'
                            '  "content": "<完整的文件内容>"\n'
                            "}\n\n"
                            "【禁止事项】\n"
                            "- 禁止把 JSON 字段名（如 layered_guess.utils）当成文件路径\n"
                            "- 禁止输出 markdown 代码块\n"
                            "- 禁止生成与用户需求无关的代码"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"用户需求：{request_text}\n"
                            f"项目根目录：{target_project_root}\n"
                            "请严格围绕用户需求实现。\n"
                            "1. 从 output.meta.language 读取语言\n"
                            "2. 从 output.structure.layered_guess.utils 数组中找到项目内的 utils 目录（排除 venv）\n"
                            "3. 生成满足用户需求的代码\n"
                            "请生成符合项目规范的代码文件。"
                        ),
                    },
                ],
                "temperature": 0.0,
                "max_tokens": generate_max_tokens,
                "_inject_skill_output": True,
                "_expect_json_output": True,  # Mark for validation
                "_fallback_path": fallback_output_path or "",
            },
        )
        # 当模型未按 JSON 合约返回时，触发一次定向重试，避免整条链路直接失败。
        codegen_step.on_failure_replan = (
            "你上一步没有按要求输出 JSON。请只输出一个 JSON 对象，"
            "且必须包含非空字段 path 与 content，不要输出解释、不要 markdown。"
        )
        plan.steps.append(codegen_step)

        # Step 4: Write file with validation
        write_step = create_atomic_step(
            executor=ExecutorType.SKILL,
            inputs={
                "skill_id": write_skill_id,
                "inputs": {
                    "path": "__from_previous_step_json:path",
                    "content": "__from_previous_step_json:content",
                    "_json_path_base": str(target_project_root),
                },
            },
        )
        # Add validation: if JSON extraction fails, mark step as failed
        write_step.on_failure_replan = (
            "上一步代码生成可能输出了非JSON格式。请重新生成，"
            "严格遵循 JSON 格式：{\"path\":\"...\",\"content\":\"...\"}"
        )
        plan.steps.append(write_step)

        # Step 5: Verify file was created
        if read_skill_id:
            plan.steps.append(
                create_atomic_step(
                    executor=ExecutorType.SKILL,
                    inputs={
                        "skill_id": read_skill_id,
                        "inputs": {
                            "path": "__from_previous_step_json:path",
                            "_json_path_base": str(target_project_root),
                        },
                    },
                )
            )

        # Step 6/7: 额外校验与总结（可选）
        if enable_extra_checks:
            alignment_step = create_atomic_step(
                executor=ExecutorType.LLM,
                inputs={
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是代码交付校验器。请基于用户需求与当前文件内容判断“是否满足需求”。\n"
                                "只输出 JSON：\n"
                                "{\n"
                                '  "aligned": true/false,\n'
                                '  "reason": "<简短原因>"\n'
                                "}\n"
                                "不要输出其他内容。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"用户需求：{request_text}\n"
                                "以下是文件内容（来自上一步 file.read 的结果）。请判断是否满足需求。"
                            ),
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": 200,
                    "_inject_skill_output": True,
                    "_expect_alignment_check": True,
                },
            )
            alignment_step.on_failure_replan = (
                "上一步生成的代码未满足用户需求。请基于项目分析和用户需求重新生成代码，"
                "确保功能语义匹配后再写入文件。"
            )
            plan.steps.append(alignment_step)

            plan.steps.append(
                create_atomic_step(
                    executor=ExecutorType.LLM,
                    inputs={
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "总结交付结果。说明：\n"
                                    "1. 文件创建状态（成功/失败）\n"
                                    "2. 文件路径\n"
                                    "3. 功能说明\n"
                                    "4. 使用建议或下一步"
                                ),
                            },
                            {
                                "role": "user",
                                "content": f"用户需求：{user_input}",
                            },
                        ],
                        "temperature": agent.temperature,
                        "max_tokens": min(int((agent.model_params or {}).get("max_tokens", 1024) or 1024), 1024),
                        "_inject_skill_output": True,
                    },
                )
            )
        return plan

    def _detect_skill_and_intent(
        self,
        user_input: str,
        available_skills: List[str],
        model_params: Optional[Dict[str, Any]] = None,
        messages: Optional[List[Message]] = None,
    ) -> tuple:
        """
        从用户输入中检测需要使用的技能和意图
        
        通用设计：
        - 不硬编码任何业务逻辑关键词
        - 只做简单的技能ID匹配
        - 具体行为由 Agent 的 system_prompt 定义
        """
        user_lower = user_input.lower()
        logger.info(f"[Planner] _detect_skill_and_intent: user_input={user_input[:50]}, available_skills={available_skills}, model_params keys={list((model_params or {}).keys())}")
        
        # 1. 技能ID精确匹配（最优先）
        for skill_id in available_skills:
            if skill_id.lower() in user_lower:
                return skill_id, "explicit"

        # 1.5 Agent 级可配置意图规则（解耦业务场景）
        logger.info(f"[Planner] Checking intent_rules: model_params={model_params}")
        configured_skill = match_configured_intent_rules(
            user_input=user_input,
            user_lower=user_lower,
            available_skills=available_skills,
            model_params=model_params or {},
        )
        if configured_skill:
            logger.info(f"[Planner] Matched configured intent rule: {configured_skill}")
            return configured_skill, "configured_rule"

        recent_job_id = self._extract_job_id_from_text(user_input) or self._extract_job_id_from_messages(messages or [])
        if recent_job_id and self._looks_like_recent_job_followup(user_input):
            job_skill = self._find_enabled_job_tracking_skill(available_skills)
            if job_skill:
                logger.info(f"[Planner] Matched generic recent-job follow-up: {job_skill}")
                return job_skill, "recent_job_followup"

        # 2. 如果没有匹配到任何技能，返回 None
        # Planner 会交给 LLM 来决定行为
        return None, "llm"

    async def _discover_skill_semantic(
        self,
        agent: AgentDefinition,
        user_input: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """
        运行时语义发现：结合向量检索 + LLM 意图识别，
        在 agent.enabled_skills 白名单内选择最合适的技能。
        仅在 model_params.use_skill_discovery=True 时由 _create_skill_based_plan 调用。
        """
        if not (user_input or "").strip():
            logger.debug("[Planner] Semantic discovery: empty user_input")
            return None
        enabled = set(agent.enabled_skills or [])
        if not enabled:
            logger.debug("[Planner] Semantic discovery: no enabled skills")
            return None
        try:
            from core.skills.discovery import get_discovery_engine
            engine = get_discovery_engine()
            
            # 步骤 1: 向量检索获取候选（扩大范围）
            results = engine.search(
                query=user_input.strip(),
                agent_id=agent.agent_id,
                organization_id=context.get("organization_id"),
                top_k=50,
                filters={"enabled_only": True},
            )
            
            # 过滤出 enabled_skills 内的候选
            candidates = [s for s in results if s.id in enabled]
            if not candidates:
                logger.debug("[Planner] Semantic discovery: no candidates in enabled_skills")
                return None
            
            # 步骤 2: 如果只有一个候选，直接返回
            if len(candidates) == 1:
                logger.info(f"[Planner] Semantic discovery: single candidate {candidates[0].id}")
                return candidates[0].id
            
            # 步骤 3: 使用 LLM 选择最合适的 skill
            selected = await self._llm_select_skill(agent, user_input, candidates, context)
            if selected:
                logger.info(f"[Planner] Semantic discovery: LLM selected {selected}")
                return selected
            
            # 降级：返回第一个候选
            logger.info(f"[Planner] Semantic discovery: fallback to first candidate {candidates[0].id}")
            return candidates[0].id
            
        except Exception as e:
            logger.warning(f"[Planner] Semantic discovery failed: {e}", exc_info=True)
            return None
    
    async def _llm_select_skill(
        self,
        agent: AgentDefinition,
        user_input: str,
        candidates: List[Any],
        context: Dict[str, Any],
    ) -> Optional[str]:
        """
        使用 LLM 从候选 skills 中选择最合适的一个。
        返回选中的 skill_id，或 None 表示无法确定。
        """
        try:
            # 构建候选列表描述
            skill_descriptions = []
            for skill in candidates[:10]:  # 最多取前10个
                desc = getattr(skill, 'description', '') or ''
                skill_descriptions.append(f"- {skill.id}: {desc[:100]}")

            image_generation_hint = ""
            
            prompt = f"""根据用户的请求，从以下候选技能中选择最合适的一个。

用户请求: {user_input}

候选技能:
{chr(10).join(skill_descriptions)}
{image_generation_hint}

要求：
1. 只返回技能 ID（如 builtin_web.search），不要有任何解释或思考过程
2. 不要输出任何其他内容
3. 如果无法确定，返回 unknown

技能 ID:"""

            # 调用 LLM（通过 Inference Gateway，避免直接依赖 RuntimeFactory/ModelRegistry）
            from core.models.selector import get_model_selector
            from core.inference import get_inference_client
            from core.types import Message

            selector = get_model_selector()
            model = selector.resolve()  # 获取默认模型
            if not model:
                logger.debug("[Planner] No model available for skill selection")
                return None

            client = get_inference_client()
            response = (await client.generate(
                model=model.id,
                messages=[Message(role="user", content=prompt)],
                temperature=0.1,
                max_tokens=50,
                metadata={
                    "caller": "Planner._llm_select_skill",
                    "agent_id": getattr(agent, "agent_id", ""),
                    "session_id": context.get("session_id", ""),
                    "trace_id": context.get("trace_id", ""),
                },
            )).text
            
            selected_id = response.strip().lower() if isinstance(response, str) else ""
            
            # 清理响应（移除思考标签和 markdown 格式）
            # 移除 <think>...</think> 或类似思考标签
            import re
            selected_id = re.sub(r'<[^>]+>.*?</[^>]+>', '', selected_id, flags=re.DOTALL)
            selected_id = re.sub(r'<[^>]+>', '', selected_id)
            selected_id = selected_id.replace("`", "").replace("**", "").strip()
            
            # 提取最后一行（LLM 可能输出多行解释）
            lines = [l.strip() for l in selected_id.split('\n') if l.strip()]
            if lines:
                selected_id = lines[-1]
            
            # 验证选中的 skill 是否在候选列表中
            if selected_id in candidate_ids:
                return selected_id
            
            logger.debug(f"[Planner] LLM selected invalid skill: {selected_id}")
            return None
            
        except Exception as e:
            logger.warning(f"[Planner] LLM skill selection failed: {e}")
            return None

    def _select_fallback_skill(self, user_input: str, available_skills: List[str]) -> Optional[str]:
        """
        当 Agent 仅具备文件类技能时的兜底选择。
        现在完全依赖 Intent Rules 配置，不再有硬编码的业务逻辑。
        如果用户需要特定的兜底行为，请通过 model_params.intent_rules 配置。
        """
        # 不再自动选择，让 LLM 决定行为
        return None
    
    async def _create_skill_chain_plan(
        self,
        agent: AgentDefinition,
        user_input: str,
        messages: List[Message],
        context: Dict[str, Any],
        first_skill_id: str,
        chain_skills: List[str]
    ) -> Plan:
        """
        创建技能链执行计划
        
        技能链：第一个技能执行完成后，自动执行后续技能
        例如：vision.detect_objects → vlm.generate

        注意：技能链是否启用、链路包含哪些技能由 Agent 的配置驱动（model_params.skill_param_extractors[*].chain）。
        """
        from core.skills.registry import SkillRegistry
        from .models import Plan, create_atomic_step, ExecutorType
        
        # 创建计划
        plan = Plan(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            goal=f"Execute skill chain: {first_skill_id} → {' → '.join(chain_skills)}",
            context=context or {},
        )
        # 技能链默认 fail-fast，避免在错误结果上继续生成误导内容
        plan.failure_strategy = "stop"
        
        # 获取第一个技能的完整对象
        first_skill = SkillRegistry.get(first_skill_id)
        if not first_skill:
            logger.warning(f"[Planner] Skill not found: {first_skill_id}")
            return await self._create_skill_execution_plan(agent, user_input, messages, context, first_skill_id, silent=False)
        
        # 第一个技能：静默执行
        first_inputs = self._build_skill_inputs_simple(
            first_skill,
            user_input,
            context,
            messages,
        )
        first_step = create_atomic_step(
            executor=ExecutorType.SKILL,
            inputs={
                "skill_id": first_skill_id,
                "inputs": first_inputs,
            },
        )
        plan.steps.append(first_step)
        
        # 后续技能：正常执行
        for skill_id in chain_skills:
            skill = SkillRegistry.get(skill_id)
            if not skill:
                logger.warning(f"[Planner] Skill not found in chain: {skill_id}")
                continue
                
            skill_inputs = self._build_skill_inputs_simple(
                skill,
                user_input,
                context,
                messages,
            )
            
            step = create_atomic_step(
                executor=ExecutorType.SKILL,
                inputs={
                    "skill_id": skill_id,
                    "inputs": skill_inputs,
                },
            )
            plan.steps.append(step)

        return plan
    
    async def _create_skill_execution_plan(
        self,
        agent: AgentDefinition,
        user_input: str,
        messages: List[Message],
        context: Dict[str, Any],
        skill_id: str,
        silent: bool = False
    ) -> Plan:
        """
        创建技能执行计划
        
        Args:
            silent: 如果为 True，执行技能后不调用 LLM，由 runtime 直接使用技能输出生成回复
        
        两步流程（默认）：
        1. 执行技能
        2. LLM 根据技能输出生成响应
        
        静默模式（silent=True）：
        1. 仅执行技能
        2. 不追加 LLM 步骤（避免引入额外提示词副作用）
        """
        from core.skills.registry import SkillRegistry
        
        # Ensure skills are loaded
        if not SkillRegistry._skills:
            SkillRegistry.load()
        
        skill = SkillRegistry.get(skill_id)
        if not skill:
            logger.warning(f"[Planner] Skill not found: {skill_id}")
            return await self._create_llm_plan(agent, user_input, messages, context)
        
        # 构建技能输入（简化版：从用户输入提取）
        skill_inputs = self._build_skill_inputs_simple(skill, user_input, context, messages)
        if skill_id in ("builtin_shell.run", "shell.run"):
            command = skill_inputs.get("command")
            if not isinstance(command, str) or not command.strip():
                logger.info(
                    "[Planner] shell.run selected but no executable command extracted; fallback to LLM plan"
                )
                return await self._create_llm_plan(agent, user_input, messages, context)
        
        # 技能执行步骤
        skill_step = create_atomic_step(
            executor=ExecutorType.SKILL,
            inputs={
                "skill_id": skill_id,
                "inputs": skill_inputs,
            },
        )
        # V2.2: 失败后重规划（优先 agent 顶层配置，兼容 model_params）
        if getattr(agent, "on_failure_strategy", None) == "replan":
            skill_step.on_failure_replan = (
                (getattr(agent, "replan_prompt", None) or "").strip()
                or "上一步失败。请根据错误原因重规划并重试，必要时改用其他可用技能。"
            )
        elif agent.model_params.get("enable_replan"):
            skill_step.on_failure_replan = (
                agent.model_params.get("on_failure_replan_instruction")
                or "上一步失败。请根据错误原因重规划并重试，必要时改用其他可用技能。"
            )
        
        steps = [skill_step]
        
        # 如果不是静默模式，添加 LLM 响应步骤
        if not silent:
            llm_step = create_atomic_step(
                executor=ExecutorType.LLM,
                inputs={
                    "messages": [
                        {
                            "role": "system",
                            "content": agent.system_prompt or "你是一个有用的助手。",
                        },
                        {
                            "role": "user",
                            "content": f"用户输入：{user_input}\n\n技能已执行，请根据技能执行结果生成最终回复。",
                        },
                    ],
                    "temperature": agent.temperature,
                    "max_tokens": agent.model_params.get("max_tokens"),
                    "_inject_skill_output": True,  # 注入技能输出
                },
            )
            steps.append(llm_step)
        else:
            # 静默模式：只执行技能步骤
            # 由 runtime 汇总技能输出为最终用户可见回复。
            pass
        
        plan = create_simple_plan(
            goal=f"Execute skill {skill_id}: {user_input[:30]}...",
            steps=steps,
            context=context,
        )
        # Skill 流程默认 fail-fast，避免技能失败后继续输出误导内容
        plan.failure_strategy = "stop"
        
        return plan

    def _build_skill_inputs_simple(
        self,
        skill,
        user_input: str,
        context: Dict[str, Any],
        messages: Optional[List[Message]] = None,
    ) -> Dict[str, Any]:
        """
        简单构建技能输入
        
        通用设计：
        - 不硬编码任何业务逻辑
        - 将 user_input 直接传递给技能
        - 具体如何处理由 Agent 的 system_prompt 定义
        """
        # input_schema 是 JSON Schema 格式，需要从 properties 中获取参数
        schema = skill.input_schema or {}
        params = schema.get("properties", {})  # 获取 properties 下的参数定义
        inputs = {}
        
        user_id = context.get("user_id", "default")
        session_id = context.get("session_id", user_id)
        workspace = context.get("workspace", ".")
        record_file = context.get("record_file")
        
        # 从 model_params 获取参数提取器配置
        model_params = context.get("model_params", {})
        skill_extractors = model_params.get("skill_param_extractors", {})
        
        # 常见参数类型的默认值（通用逻辑，不针对特定业务）
        for param_name in params.keys():
            # Shell 命令参数提取
            if "command" in param_name.lower():
                # 检查是否配置了此 skill 的命令提取器
                extractor = skill_extractors.get(skill.id, {})
                cmd_extractor = extractor.get("command", {})
                if cmd_extractor.get("enabled", True):  # 默认启用
                    cmd = extract_shell_command(user_input, cmd_extractor.get("config"))
                    if cmd:
                        inputs[param_name] = cmd
            elif param_name.lower() in ("working_dir", "cwd"):
                # Shell 运行目录默认绑定当前 workspace
                inputs[param_name] = workspace
            elif param_name.lower() == "path":
                # 检查是否配置了此 skill 的路径提取器
                extractor = skill_extractors.get(skill.id, {})
                path_extractor = extractor.get("path", {})
                if path_extractor.get("enabled", True):  # 默认启用
                    raw_path = extract_path_from_text(user_input, path_extractor.get("config")) or "."
                    # file.write 不接受 "."；未提取到有效路径时使用默认文件名，避免创建文件意图失败
                    if raw_path in ("", ".") and skill.id in ("builtin_file.write", "file.write"):
                        raw_path = path_extractor.get("default") or f"{session_id}_output.txt"
                    inputs[param_name] = raw_path
                else:
                    # 如果禁用，使用配置的默认值或回退到 record_file
                    default_path = path_extractor.get("default") or record_file or f"{session_id}_records.json"
                    inputs[param_name] = default_path
            elif "path" in param_name.lower() or "file" in param_name.lower():
                # 文件路径参数 - 使用可配置的默认值
                # 文件会保存在 workspace 目录下
                extractor = skill_extractors.get(skill.id, {})
                file_extractor = extractor.get("file", {})
                if file_extractor.get("enabled", True):  # 默认启用
                    default_filename = file_extractor.get("default_filename") or f"{session_id}_records.json"
                    file_name = record_file or default_filename
                    file_path = file_name
                    inputs[param_name] = file_path
                else:
                    # 如果禁用，使用配置的默认值或回退到 record_file
                    default_filename = file_extractor.get("default_filename") or record_file or f"{session_id}_records.json"
                    inputs[param_name] = default_filename
            elif "content" in param_name.lower():
                # 内容参数 - 直接使用用户输入；具体如何解析由 Agent 的 system_prompt 或意图规则定义
                inputs[param_name] = user_input
            elif "query" in param_name.lower():
                # 查询参数
                inputs[param_name] = user_input
            elif param_name.lower() == "negative_prompt":
                # 默认不对 negative_prompt 注入用户原始请求，避免把正向提示词错误复制到负向提示词。
                continue
            elif "prompt" in param_name.lower():
                # 提示参数
                base_prompt = strip_injected_workspace_hints(user_input)
                extractor = skill_extractors.get(skill.id, {})
                prompt_extractor = extractor.get("prompt", {}) if isinstance(extractor, dict) else {}
                if isinstance(prompt_extractor, dict):
                    prefix = prompt_extractor.get("prefix")
                    suffix = prompt_extractor.get("suffix")
                    if isinstance(prefix, str) and prefix.strip():
                        base_prompt = prefix.strip() + "\n\n" + base_prompt
                    if isinstance(suffix, str) and suffix.strip():
                        base_prompt = base_prompt + "\n\n" + suffix.strip()
                inputs[param_name] = base_prompt
            elif param_name.lower() == "model_id":
                # 仅对需要继承 Agent 主模型的技能自动填充 model_id。
                # image.generate 的 model_id 默认值应由 Tool 层决定，避免错误复用 Agent 的 LLM model_id。
                if skill.id not in ("builtin_image.generate", "image.generate"):
                    mid = context.get("model_id")
                    if isinstance(mid, str) and mid.strip():
                        inputs[param_name] = mid.strip()
            elif param_name.lower() == "job_id":
                job_id = self._extract_job_id_from_text(user_input)
                if not job_id:
                    job_id = self._extract_job_id_from_messages(messages or [])
                if job_id:
                    inputs[param_name] = job_id
            elif param_name.lower() == "image":
                # 图片参数：提取上传的图片文件名
                # 支持格式：[Files saved to workspace. Image: "xxx.jpg"]
                extractor = skill_extractors.get(skill.id, {})
                image_extractor = extractor.get("image", {})
                if image_extractor.get("enabled", True):  # 默认启用
                    image_path = extract_image_from_text(user_input)
                    if image_path:
                        inputs[param_name] = image_path
            elif param_name.lower() == "workspace":
                # 显式 workspace 参数：优先从用户输入提取路径，未提取到再回退上下文 workspace
                extractor = skill_extractors.get(skill.id, {})
                ws_extractor = extractor.get("workspace", {})
                if ws_extractor.get("enabled", True):
                    explicit_ws = extract_workspace_from_text(
                        user_input,
                        ws_extractor.get("config"),
                    )
                    inputs[param_name] = explicit_ws or workspace
                else:
                    inputs[param_name] = ws_extractor.get("default") or workspace
            elif "workspace" in param_name.lower():
                # 兼容其它命名（如 target_workspace / workspace_path）
                explicit_ws = extract_workspace_from_text(user_input)
                inputs[param_name] = explicit_ws or workspace
            elif param_name.lower() == "detail_level" and skill.id == "builtin_project.analyze":
                extractor = skill_extractors.get(skill.id, {})
                detail_cfg = extractor.get("detail_level", {}) if isinstance(extractor, dict) else {}
                if isinstance(detail_cfg, dict) and not detail_cfg.get("enabled", True):
                    inputs[param_name] = detail_cfg.get("default") or "brief"
                else:
                    inputs[param_name] = (
                        detail_cfg.get("default")
                        if isinstance(detail_cfg, dict) and detail_cfg.get("default")
                        else "detailed"
                    )
            elif param_name.lower() in ("top_n_modules", "top_n_libs", "top_n_risks") and skill.id == "builtin_project.analyze":
                extractor = skill_extractors.get(skill.id, {})
                num_cfg = extractor.get(param_name, {}) if isinstance(extractor, dict) else {}
                default_map = {"top_n_modules": 20, "top_n_libs": 30, "top_n_risks": 15}
                default_val = default_map.get(param_name, 20)
                if isinstance(num_cfg, dict) and num_cfg.get("default") is not None:
                    inputs[param_name] = num_cfg.get("default")
                else:
                    inputs[param_name] = default_val
        
        # 如果没有匹配到任何参数，使用 user_input 作为默认
        if not inputs and params:
            inputs["user_input"] = user_input

        # 对 project.analyze 做兜底：即使 skill schema 未刷新，也默认注入 detailed 参数
        # 避免旧缓存 schema 导致 detail_level/top_n_* 丢失。
        # Feature Creation 需要目录结构来选择正确的文件路径，所以 include_tree=True
        if skill.id == "builtin_project.analyze":
            inputs.setdefault("detail_level", "detailed")
            inputs.setdefault("include_tree", True)  # Feature Creation 需要目录结构
            inputs.setdefault("top_n_modules", 20)
            inputs.setdefault("top_n_libs", 30)
            inputs.setdefault("top_n_risks", 15)
        
        return inputs

    @staticmethod
    def _extract_job_id_from_text(text: str) -> Optional[str]:
        content = (text or "").strip()
        if not content:
            return None
        m = re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", content, re.IGNORECASE)
        if m:
            return m.group(0)
        m2 = re.search(r"job[_ -]?id[:：\s`\"]*([0-9a-f-]{36})", content, re.IGNORECASE)
        if m2:
            return m2.group(1)
        return None

    @classmethod
    def _extract_job_id_from_messages(cls, messages: List[Message]) -> Optional[str]:
        for msg in reversed(messages or []):
            content = getattr(msg, "content", None)
            if not isinstance(content, str):
                continue
            job_id = cls._extract_job_id_from_text(content)
            if job_id:
                return job_id
        return None

    @staticmethod
    def _looks_like_recent_job_followup(user_input: str) -> bool:
        text = (user_input or "").strip().lower()
        if not text:
            return False
        has_reference = any(token in text for token in [
            "当前", "刚才", "刚刚", "这个", "上一", "这轮", "本轮", "recent", "current", "last", "that",
        ])
        has_taskish = any(token in text for token in [
            "任务", "状态", "进度", "结果", "情况", "好了", "完成", "生成", "job", "status", "progress", "result", "done", "finished",
        ])
        return has_reference and has_taskish

    @staticmethod
    def _skill_accepts_param(skill: Any, param_name: str) -> bool:
        schema = getattr(skill, "input_schema", None) or {}
        if not isinstance(schema, dict):
            return False
        props = schema.get("properties", {})
        return isinstance(props, dict) and param_name in props

    def _find_enabled_job_tracking_skill(self, available_skills: List[str]) -> Optional[str]:
        from core.skills.registry import SkillRegistry

        candidates: List[str] = []
        for skill_id in available_skills or []:
            skill = SkillRegistry.get(skill_id)
            if not skill:
                continue
            if self._skill_accepts_param(skill, "job_id"):
                candidates.append(skill_id)

        if len(candidates) == 1:
            return candidates[0]

        preferred = [
            skill_id
            for skill_id in candidates
            if any(marker in skill_id for marker in (".get_", ".status", ".getjob", ".get_job"))
        ]
        if len(preferred) == 1:
            return preferred[0]
        return None

    
    async def _create_llm_plan(
        self,
        agent: AgentDefinition,
        user_input: str,
        messages: List[Message],
        context: Dict[str, Any]
    ) -> Plan:
        """创建纯 LLM 对话计划"""
        # 构建 LLM 消息
        llm_messages = self._build_llm_messages(agent, user_input, messages)
        
        step = create_atomic_step(
            executor=ExecutorType.LLM,
            inputs={
                "messages": [m.model_dump() for m in llm_messages],
                "temperature": agent.temperature,
                "max_tokens": agent.model_params.get("max_tokens"),
            },
        )
        
        return create_simple_plan(
            goal=f"LLM chat with {agent.model_id}",
            steps=[step],
            context=context,
        )

    def _build_llm_messages(
        self,
        agent: AgentDefinition,
        user_input: str,
        messages: List[Message]
    ) -> List[Message]:
        """构建 LLM 消息列表"""
        from core.types import Message
        
        # 添加系统消息
        system_msg = Message(
            role="system",
            content=agent.system_prompt or "You are a helpful assistant."
        )
        
        # 添加历史消息
        all_messages = [system_msg] + list(messages)

        # 避免重复注入同一条用户输入（常见于 session.messages 已包含本轮 user）
        should_append_user = True
        if messages:
            last_msg = messages[-1]
            if last_msg.role == "user":
                last_content = (last_msg.content or "").strip() if isinstance(last_msg.content, str) else str(last_msg.content)
                current_content = (user_input or "").strip()
                if last_content == current_content:
                    should_append_user = False

        if should_append_user:
            user_msg = Message(
                role="user",
                content=user_input
            )
            all_messages.append(user_msg)
        
        return all_messages

    async def create_followup_plan(
        self,
        agent: AgentDefinition,
        execution_context: Dict[str, Any],
        parent_plan_id: Optional[str] = None
    ) -> Plan:
        """
        根据执行上下文生成后续 Plan（用于 REPLAN，V2.2）
        
        Args:
            agent: Agent 定义
            execution_context: 执行上下文（包含 last_failed_step、last_error、replan_instruction 等）
            parent_plan_id: 父 Plan ID
        
        Returns:
            Plan: 新生成的 Plan
        """
        replan_instruction = execution_context.get("replan_instruction", "")
        last_failed_step = execution_context.get("last_failed_step")
        last_error = execution_context.get("last_error")
        current_plan = execution_context.get("current_plan")
        session = execution_context.get("session")

        # V2.3: Check if Plan Contract is enabled
        if agent.plan_contract_enabled:
            logger.info(f"[Planner] Plan Contract enabled, checking sources: {agent.plan_contract_sources}")
            strict_mode = bool(getattr(agent, "plan_contract_strict", False))
            seen_candidate = False
            
            # Try sources in configured priority order
            for source_key in agent.plan_contract_sources:
                candidate = execution_context.get(source_key)
                if candidate is None:
                    logger.debug(f"[Planner] Source '{source_key}' not found in context")
                    continue
                seen_candidate = True
                
                try:
                    contract_plan = try_parse_contract_plan(candidate)
                    if contract_plan is None:
                        logger.debug(f"[Planner] Source '{source_key}' did not parse as valid contract")
                        continue
                    
                    runtime_plan = adapt_contract_to_runtime_plan(
                        contract_plan=contract_plan,
                        context=execution_context,
                        parent_plan_id=parent_plan_id,
                    )
                    logger.info(
                        f"[Planner] Using Plan Contract followup plan from '{source_key}': "
                        f"{runtime_plan.plan_id} (steps={len(runtime_plan.steps)})"
                    )
                    return runtime_plan
                except ValueError as e:
                    logger.error(f"[Planner] Failed to parse contract from '{source_key}': {e}")
                    if strict_mode:
                        raise ValueError(
                            f"Plan Contract strict mode: invalid contract from '{source_key}': {e}"
                        ) from e
                    # Continue to next source or fallback
                except Exception as e:
                    logger.error(f"[Planner] Unexpected error processing contract from '{source_key}': {e}")
                    if strict_mode:
                        raise
                    # Continue to next source or fallback
            
            logger.info("[Planner] No valid Plan Contract found in configured sources, falling back to LLM")
            if strict_mode and seen_candidate:
                raise ValueError("Plan Contract strict mode: no valid contract found in configured sources")
        else:
            logger.debug("[Planner] Plan Contract not enabled, using traditional approach")
        
        # 显式可配置：RePlan 旁路直接创建 skill 计划（默认关闭）
        direct_cfg = get_replan_direct_skill_config(agent)
        if self._should_use_direct_replan_skill(direct_cfg, execution_context):
            direct_plan = self._try_build_direct_replan_skill_plan(
                agent=agent,
                execution_context=execution_context,
                parent_plan_id=parent_plan_id,
                config=direct_cfg,
            )
            if direct_plan is not None:
                logger.info(
                    "[Planner] Using direct replan skill plan (configured)"
                )
                return direct_plan
            fallback = direct_cfg.get("fallback", "planner_replan")
            if fallback == "stop":
                raise ValueError(
                    "replan_direct_skill is enabled but no valid direct skill step could be built"
                )
        
        # 测试/命令失败且具备读+改+测能力时，直接生成「读→LLM 生成 patch→apply_patch→再测」四步计划，避免意图匹配成单步重跑
        if self._is_replan_fix_scenario(agent, execution_context):
            fix_plan = self._build_replan_fix_plan(agent, execution_context, parent_plan_id)
            if fix_plan is not None:
                logger.info("[Planner] Using 4-step replan fix plan (read→LLM patch→apply_patch→run)")
                return fix_plan
        
        # 使用原有逻辑，让 LLM 决定后续计划
        # 构建重规划的用户输入（基于 replan_instruction 和失败上下文）
        user_input = replan_instruction
        if last_error:
            user_input = f"{replan_instruction}\n\n上次执行失败：{last_error}"
        # 若为测试/命令执行失败且 Agent 具备改代码能力，追加明确指令，促使 LLM 生成「读文件→改代码→再测」而非仅重跑
        user_input = self._maybe_append_fix_plan_hint(agent, execution_context, user_input)
        
        # 构建消息历史（从 session 获取，或使用 execution_context 中的 messages）
        messages = []
        if session and hasattr(session, "messages"):
            messages = list(session.messages)
        elif execution_context.get("messages"):
            messages = execution_context.get("messages", [])
        
        # 检测 Feature Creation 意图：使用原始用户输入而非 RePlan 指令
        original_user_input = execution_context.get("user_input", "")
        if self._is_feature_creation_intent(original_user_input):
            feature_plan = await self._create_feature_creation_plan(agent, original_user_input, messages, execution_context)
            if feature_plan is not None:
                logger.info(f"[Planner] RePlan: Detected feature creation intent, using _create_feature_creation_plan")
                feature_plan.parent_plan_id = parent_plan_id
                return feature_plan
        
        # 调用 create_plan 生成新 Plan
        plan = await self.create_plan(
            agent=agent,
            user_input=user_input,
            messages=messages,
            context=execution_context,
        )
        
        # 设置 parent_plan_id
        plan.parent_plan_id = parent_plan_id
        
        logger.info(f"[Planner] Created followup plan {plan.plan_id} (parent: {parent_plan_id})")
        return plan

    def _should_use_direct_replan_skill(
        self,
        config: Dict[str, Any],
        execution_context: Dict[str, Any],
    ) -> bool:
        if not config.get("enabled"):
            return False
        when = [str(x).strip().lower() for x in (config.get("when") or ["any"])]
        if "any" in when:
            return True
        failure_kind = classify_replan_failure(execution_context)
        return failure_kind in set(when)

    def _maybe_append_fix_plan_hint(
        self,
        agent: AgentDefinition,
        execution_context: Dict[str, Any],
        user_input: str,
    ) -> str:
        """
        若为测试/命令执行失败且 Agent 具备读文件与改代码能力，在 user_input 后追加明确指令，
        促使 LLM 生成「读文件 → 改代码 → 再测」的修复计划，而不是只重跑测试。
        """
        last_failed_step = execution_context.get("last_failed_step")
        if last_failed_step is None or not isinstance(getattr(last_failed_step, "inputs", None), dict):
            return user_input
        skill_id = (last_failed_step.inputs or {}).get("skill_id")
        if not isinstance(skill_id, str):
            return user_input
        skill_id = skill_id.strip()
        # 仅对测试/命令类技能失败时追加
        if skill_id not in (
            "builtin_shell.run", "shell.run",
            "builtin_project.test", "project.test",
            "builtin_project.build", "project.build",
        ):
            return user_input
        # 检查是否非零退出或明确失败
        outputs = getattr(last_failed_step, "outputs", None) or {}
        result = outputs.get("result") if isinstance(outputs, dict) else None
        output = result.get("output") if isinstance(result, dict) else None
        exit_code = output.get("exit_code") if isinstance(output, dict) else None
        if not (isinstance(exit_code, int) and exit_code != 0) and not execution_context.get("last_error"):
            return user_input
        # Agent 需具备：读文件 + 改代码 + 执行命令/测试
        enabled = set(agent.enabled_skills or [])
        has_read = "builtin_file.read" in enabled or "file.read" in enabled
        has_patch = (
            "builtin_file.patch" in enabled or "file.patch" in enabled
            or "builtin_file.apply_patch" in enabled or "file.apply_patch" in enabled
        )
        has_run = (
            "builtin_shell.run" in enabled or "shell.run" in enabled
            or "builtin_project.test" in enabled or "project.test" in enabled
        )
        if not (has_read and has_patch and has_run):
            return user_input
        hint = (
            "\n\n【重规划要求】这是测试/命令执行失败后的修复轮次。请按顺序执行："
            " 1) 读取报错涉及的文件（file.read）；"
            " 2) 根据错误信息修改代码（file.patch 或 file.apply_patch）；"
            " 3) 重新运行测试或命令。必须包含修改代码的步骤，不要只重跑测试。"
        )
        return user_input + hint

    def _is_replan_fix_scenario(
        self,
        agent: AgentDefinition,
        execution_context: Dict[str, Any],
    ) -> bool:
        """是否为「测试/命令失败 + 具备读文件与改代码能力」的 replan 修复场景（与 _maybe_append_fix_plan_hint 条件一致）。"""
        last_failed_step = execution_context.get("last_failed_step")
        if last_failed_step is None or not isinstance(getattr(last_failed_step, "inputs", None), dict):
            return False
        skill_id = (last_failed_step.inputs or {}).get("skill_id")
        if not isinstance(skill_id, str):
            return False
        skill_id = skill_id.strip()
        if skill_id not in (
            "builtin_shell.run", "shell.run",
            "builtin_project.test", "project.test",
            "builtin_project.build", "project.build",
        ):
            return False
        outputs = getattr(last_failed_step, "outputs", None) or {}
        result = outputs.get("result") if isinstance(outputs, dict) else None
        output = result.get("output") if isinstance(result, dict) else None
        exit_code = output.get("exit_code") if isinstance(output, dict) else None
        if not (isinstance(exit_code, int) and exit_code != 0) and not execution_context.get("last_error"):
            return False
        enabled = set(agent.enabled_skills or [])
        has_read = "builtin_file.read" in enabled or "file.read" in enabled
        has_patch = (
            "builtin_file.patch" in enabled or "file.patch" in enabled
            or "builtin_file.apply_patch" in enabled or "file.apply_patch" in enabled
        )
        has_run = (
            "builtin_shell.run" in enabled or "shell.run" in enabled
            or "builtin_project.test" in enabled or "project.test" in enabled
        )
        return bool(has_read and has_patch and has_run)

    def _build_replan_fix_plan(
        self,
        agent: AgentDefinition,
        execution_context: Dict[str, Any],
        parent_plan_id: Optional[str],
    ) -> Optional[Plan]:
        """
        构建「读文件 → LLM 生成 patch → apply_patch → 再测」四步计划。
        依赖执行器对 __from_previous_step 的解析，将上一步 LLM 的 response 填入 apply_patch 的 patch 参数。
        """
        from .models import create_atomic_step

        file_to_read = self._extract_replan_target_file(execution_context)
        if not file_to_read:
            logger.info("[Planner] replan_fix_plan skipped: cannot determine target file from failure context")
            return None
        file_to_read = self._resolve_replan_fix_source_file(file_to_read, execution_context)
        test_command = extract_command_from_context(execution_context) or ""
        last_error = str(execution_context.get("last_error") or "")
        failed_step = execution_context.get("last_failed_step")
        failed_output = ""
        if failed_step is not None:
            outputs = getattr(failed_step, "outputs", None) or {}
            result = outputs.get("result") if isinstance(outputs, dict) else None
            output = result.get("output") if isinstance(result, dict) else None
            if isinstance(output, dict):
                stderr = output.get("stderr")
                stdout = output.get("stdout")
                chunks = []
                if isinstance(stderr, str) and stderr.strip():
                    chunks.append(f"[stderr]\\n{stderr[:2000]}")
                if isinstance(stdout, str) and stdout.strip():
                    chunks.append(f"[stdout]\\n{stdout[:2000]}")
                failed_output = "\\n\\n".join(chunks)

        # 确定技能 ID（优先 builtin_ 前缀）
        enabled = set(agent.enabled_skills or [])
        read_skill = "builtin_file.read" if "builtin_file.read" in enabled else "file.read"
        
        # apply_patch 技能：支持多种命名
        if "builtin_file.apply_patch" in enabled:
            apply_patch_skill = "builtin_file.apply_patch"
        elif "file.apply_patch" in enabled:
            apply_patch_skill = "file.apply_patch"
        elif "builtin_file.patch" in enabled:
            apply_patch_skill = "builtin_file.patch"
        elif "file.patch" in enabled:
            apply_patch_skill = "file.patch"
        else:
            logger.info("[Planner] replan_fix_plan skipped: no apply_patch skill found")
            return None
        
        shell_skill = "builtin_shell.run" if "builtin_shell.run" in enabled else "shell.run"

        plan = Plan(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            goal="修复失败的测试（读文件→生成 patch→应用→再测）",
            context={**execution_context, "plan_source": "replan_fix_plan"},
            parent_plan_id=parent_plan_id,
        )
        plan.failure_strategy = "stop"

        # Step 1: 读取相关文件
        plan.steps.append(
            create_atomic_step(
                executor=ExecutorType.SKILL,
                inputs={
                    "skill_id": read_skill,
                    "inputs": {"path": file_to_read},
                },
            )
        )
        # Step 2: LLM 根据文件内容 + 错误信息生成 unified diff（执行器会将 step1 输出注入到用户消息后）
        llm_step = create_atomic_step(
            executor=ExecutorType.LLM,
            inputs={
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是一个代码修复工具。根据错误信息和代码内容生成 unified diff patch。\n\n"
                            "【严格要求】\n"
                            "- 只输出 patch 内容（必须以 --- 开头）\n"
                            "- 不要解释、不要 <think>、不要 markdown 代码块\n"
                            "- 只修改目标文件，不要修改其它文件\n"
                            "- 必须修复导致测试失败的根因\n"
                            "- 尽量最小修改\n\n"
                            "【示例】\n--- a/file.py\n+++ b/file.py\n@@ -1,3 +1,4 @@\n def foo():\n-    pass\n+    return True"
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            f"目标文件：{file_to_read}\n"
                            f"测试命令：{test_command or 'N/A'}\n"
                            f"失败错误：{last_error}\n\n"
                            f"{failed_output}\n\n"
                            "请根据下面的技能执行结果（文件内容）生成 unified diff patch 来修复问题。\n"
                            "【重要】只输出 patch 内容（从 --- 开始），不要有任何其它文字。"
                        ),
                    },
                ],
                "temperature": 0.0,
                "max_tokens": 1200,
                "_expect_unified_diff": True,  # 要求该步输出必须为 unified diff
                "_inject_skill_output": True,
            },
        )
        plan.steps.append(llm_step)
        # Step 3: 应用 patch（patch 内容由执行器从上一步 LLM response 填入）
        patch_inputs = {
            "path": file_to_read,  # 必须提供 path
            "patch": "__from_previous_step",  # 从上一步 LLM response 获取
        }
        plan.steps.append(
            create_atomic_step(
                executor=ExecutorType.SKILL,
                inputs={
                    "_extract_patch": True,  # 标记需要从上一步 LLM 输出提取纯 patch
                    "skill_id": apply_patch_skill,
                    "inputs": patch_inputs,
                },
            )
        )
        # Step 4: 重新运行测试/命令
        if test_command:
            plan.steps.append(
                create_atomic_step(
                    executor=ExecutorType.SKILL,
                    inputs={
                        "skill_id": shell_skill,
                        "inputs": {"command": test_command},
                    },
                )
            )
        return plan

    def _resolve_replan_fix_source_file(
        self,
        file_to_read: str,
        execution_context: Dict[str, Any],
    ) -> str:
        """
        当失败目标是测试文件（如 test_app.py）时，优先尝试定位对应源码文件（如 app.py）。
        避免对测试文件打补丁而不是修复真实业务代码。
        """
        try:
            p = Path(file_to_read).expanduser()
            name = p.name
            stem = p.stem
            suffix = p.suffix or ".py"

            is_py_test_file = (
                suffix == ".py"
                and (name.startswith("test_") or name.endswith("_test.py"))
            )
            if not is_py_test_file:
                return file_to_read

            candidates: List[Path] = []
            if name.startswith("test_"):
                candidates.append(p.with_name(name[len("test_"):]))
            if name.endswith("_test.py"):
                candidates.append(p.with_name(stem[:-5] + ".py"))

            # 基于命令中的 cwd 再尝试一次（兼容相对路径）
            cmd = extract_command_from_context(execution_context) or ""
            m = re.match(r"^\s*cd\s+((?:\"[^\"]+\")|(?:'[^']+')|(?:\S+))\s*&&", cmd, re.DOTALL)
            if m:
                base_dir = Path(m.group(1).strip().strip("\"'")).expanduser().resolve()
                if name.startswith("test_"):
                    candidates.append(base_dir / name[len("test_"):])
                if name.endswith("_test.py"):
                    candidates.append(base_dir / (stem[:-5] + ".py"))

            for c in candidates:
                if c.exists() and c.is_file():
                    resolved = str(c.resolve())
                    logger.info(
                        f"[Planner] replan_fix_plan target switched from test file to source file: "
                        f"{file_to_read} -> {resolved}"
                    )
                    return resolved
        except Exception as e:
            logger.debug(f"[Planner] _resolve_replan_fix_source_file skipped due to error: {e}")
        return file_to_read

    def _extract_replan_target_file(self, execution_context: Dict[str, Any]) -> Optional[str]:
        """
        尝试从失败上下文中提取可读文件路径（优先绝对路径）。
        目标：避免回退到 '.' 导致 file.read 读取失败。
        """
        last_error = str(execution_context.get("last_error") or "")
        # 提前解析命令上下文（若存在 cd /abs/path，可用于把相对文件名补全为绝对路径）
        cmd = extract_command_from_context(execution_context) or ""
        cmd_base_dir: Optional[str] = None
        if cmd:
            m = re.match(r"^\s*cd\s+((?:\"[^\"]+\")|(?:'[^']+')|(?:\S+))\s*&&\s*(.+)$", cmd, re.DOTALL)
            if m:
                cmd_base_dir = m.group(1).strip().strip("\"'")

        def _normalize_with_cmd_base(p: str) -> str:
            pp = (p or "").strip().strip("\"'")
            if not pp:
                return pp
            if pp.startswith("/") or not cmd_base_dir:
                return pp
            return str((Path(cmd_base_dir).expanduser().resolve() / pp))

        # 1) 先看 last_error
        from_error = extract_filename_from_error(last_error)
        if from_error:
            return _normalize_with_cmd_base(from_error)

        # 2) 再看失败步骤 output（stderr/stdout/error）
        failed_step = execution_context.get("last_failed_step")
        if failed_step is not None:
            outputs = getattr(failed_step, "outputs", None) or {}
            result = outputs.get("result") if isinstance(outputs, dict) else None
            output = result.get("output") if isinstance(result, dict) else None
            text_blobs: List[str] = []
            if isinstance(output, dict):
                for key in ("stderr", "stdout", "error"):
                    val = output.get(key)
                    if isinstance(val, str) and val.strip():
                        text_blobs.append(val)
            for txt in text_blobs:
                p = extract_filename_from_error(txt)
                if p:
                    return _normalize_with_cmd_base(p)

        # 3) 最后从命令推断（支持: cd /abs/path && pytest test_xxx.py -v）
        if cmd:
            m = re.match(r"^\s*cd\s+((?:\"[^\"]+\")|(?:'[^']+')|(?:\S+))\s*&&\s*(.+)$", cmd, re.DOTALL)
            base_dir = None
            trailing = cmd
            if m:
                base_dir = m.group(1).strip().strip("\"'")
                trailing = m.group(2).strip()
            target_match = re.search(r"\bpytest\b(?:\s+[^\s-][^\s]*)*\s+([^\s]+\.py)\b", trailing)
            if target_match:
                target = target_match.group(1).strip().strip("\"'")
                if target.startswith("/"):
                    return target
                if base_dir:
                    return str((Path(base_dir).expanduser().resolve() / target))
                return target

        return None

    def _try_build_direct_replan_skill_plan(
        self,
        agent: AgentDefinition,
        execution_context: Dict[str, Any],
        parent_plan_id: Optional[str],
        config: Dict[str, Any],
    ) -> Optional[Plan]:
        from .models import create_atomic_step

        available = set(agent.enabled_skills or [])
        allowed_raw = [s for s in (config.get("allowed_skills") or []) if isinstance(s, str) and s.strip()]
        allowed = set(allowed_raw) if allowed_raw else available

        strategy = str(config.get("strategy") or "retry_failed_skill").strip().lower()
        selected_skill_id: Optional[str] = None
        selected_inputs: Dict[str, Any] = {}

        if strategy == "fixed_skill":
            fixed_skill_id = config.get("fixed_skill_id")
            if isinstance(fixed_skill_id, str):
                selected_skill_id = fixed_skill_id.strip()
            selected_inputs = dict(config.get("fixed_skill_inputs") or {})
            if selected_skill_id in ("builtin_shell.run", "shell.run") and not selected_inputs.get("command"):
                cmd = extract_command_from_context(execution_context)
                if cmd:
                    selected_inputs["command"] = cmd
        else:
            # default strategy: retry_failed_skill
            last_failed_step = execution_context.get("last_failed_step")
            if last_failed_step is not None and isinstance(getattr(last_failed_step, "inputs", None), dict):
                failed_inputs = dict(last_failed_step.inputs)
                sid = failed_inputs.get("skill_id")
                if isinstance(sid, str) and sid.strip():
                    selected_skill_id = sid.strip()
                    selected_inputs = dict(failed_inputs.get("inputs") or {})
                    # shell.run 非 0 退出码通常是业务失败（测试失败），
                    # 直接重跑同一命令价值低，回退到 planner_replan 让 LLM 制定修复计划。
                    if selected_skill_id in ("builtin_shell.run", "shell.run"):
                        failed_outputs = dict(getattr(last_failed_step, "outputs", {}) or {})
                        result = failed_outputs.get("result")
                        output = result.get("output") if isinstance(result, dict) else None
                        exit_code = output.get("exit_code") if isinstance(output, dict) else None
                        if isinstance(exit_code, int) and exit_code != 0:
                            return None

        if not selected_skill_id:
            return None
        if selected_skill_id not in available:
            logger.warning(
                f"[Planner] replan_direct_skill selected skill not enabled: {selected_skill_id}"
            )
            return None
        if selected_skill_id not in allowed:
            logger.warning(
                f"[Planner] replan_direct_skill selected skill not in allowed_skills: {selected_skill_id}"
            )
            return None

        plan = Plan(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            goal=f"Replan direct skill execution: {selected_skill_id}",
            context={
                **execution_context,
                "plan_source": "replan_direct_skill",
                "replan_direct_skill_strategy": strategy,
            },
            parent_plan_id=parent_plan_id,
        )
        plan.failure_strategy = "stop"
        plan.steps.append(
            create_atomic_step(
                executor=ExecutorType.SKILL,
                inputs={
                    "skill_id": selected_skill_id,
                    "inputs": selected_inputs,
                },
            )
        )
        return plan
    
# 全局 Planner 实例
_planner: Optional[Planner] = None


def get_planner() -> Planner:
    """获取 Planner 单例"""
    global _planner
    if _planner is None:
        _planner = Planner()
    return _planner
