import json
import asyncio
import re
from string import Formatter
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.agent_runtime.definition import AgentDefinition, get_agent_registry
from core.agent_runtime.session import AgentSession, get_agent_session_store
from core.agent_runtime.trace import AgentTraceEvent, get_agent_trace_store
from core.agent_runtime.executor import get_agent_executor
from core.agent_runtime.loop import AgentLoop
from core.agent_runtime.rag import get_kb_store
from core.agent_runtime.v2.runtime import AgentRuntime, get_agent_runtime
from core.types import Message
from log import logger
from core.models.registry import get_model_registry
from core.skills.registry import SkillRegistry
from core.tools.sandbox import resolve_in_workspace, WorkspacePathError

router = APIRouter(prefix="/api/agents", tags=["agents"])
session_router = APIRouter(prefix="/api", tags=["agent-sessions"])

# Replan prompt template guardrails
MAX_REPLAN_PROMPT_TEMPLATE_LEN = 8000
ALLOWED_REPLAN_TEMPLATE_PLACEHOLDERS = {
    "failed_step_id",
    "failed_step_executor",
    "failed_step_error",
    "failed_step_inputs_json",
    "failed_step_outputs_json",
    "replan_count",
    "replan_limit",
    # backward-compatible placeholders
    "test_command",
    "exit_code",
    "stdout",
    "stderr",
    "fix_iteration",
    "max_fix_iterations",
}

def _get_user_id(request: Request) -> str:
    uid = (request.headers.get("X-User-Id") or "").strip()
    return uid or "default"

class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Agent name (required)")
    description: str = Field(default="", max_length=500, description="Agent description")
    model_id: str = Field(..., description="Model ID to use for this agent")
    system_prompt: str = Field(default="", description="System prompt for the agent")
    enabled_skills: List[str] = Field(default_factory=list, description="List of Skill IDs (v1.5); Agent only sees these skills")
    tool_ids: List[str] = Field(default_factory=list, description="Deprecated: mapped to builtin_<id> skills when enabled_skills empty")
    rag_ids: List[str] = Field(default_factory=list, description="List of knowledge base IDs for RAG")
    max_steps: int = Field(default=20, ge=1, le=50, description="Maximum steps for agent execution")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Temperature for LLM generation")
    slug: Optional[str] = Field(default=None, max_length=50, description="URL-friendly identifier")
    execution_mode: Optional[str] = Field(default="legacy", description="Execution mode: 'legacy' or 'plan_based'")
    use_execution_kernel: Optional[bool] = Field(default=None, description="Agent-level override for Execution Kernel (None = follow global)")
    # V2.2: RePlan
    max_replan_count: Optional[int] = Field(default=None, ge=0, le=10, description="Max replan attempts (plan_based)")
    on_failure_strategy: Optional[str] = Field(default=None, description="On failure: stop / continue / replan")
    replan_prompt: Optional[str] = Field(default=None, description="Custom replan instruction when strategy is replan")
    response_mode: Optional[str] = Field(default=None, description="Agent response mode: default or direct_tool_result")
    # Model parameters (e.g., intent_rules, skill_param_extractors, use_skill_discovery, etc.)
    model_params: Optional[Dict[str, Any]] = Field(default=None, description="Model parameters: intent_rules, skill_param_extractors, use_skill_discovery (bool, enable semantic skill discovery at runtime), etc.")


def _apply_response_mode(
    model_params: Optional[Dict[str, Any]],
    response_mode: Optional[str],
    enabled_skills: List[str],
) -> Dict[str, Any]:
    params = dict(model_params or {})
    mode = (response_mode or params.get("response_mode") or "default").strip() or "default"
    if mode not in {"default", "direct_tool_result"}:
        raise HTTPException(
            status_code=400,
            detail="response_mode must be one of: default, direct_tool_result",
        )

    params["response_mode"] = mode
    if mode == "direct_tool_result":
        params["skill_direct_response_ids"] = list(enabled_skills or [])
    else:
        params.pop("skill_direct_response_ids", None)
    return params

class RunAgentRequest(BaseModel):
    messages: List[Message]
    session_id: Optional[str] = None

def _normalize_id_list(items: List[str]) -> List[str]:
    """Normalize user-provided id lists: strip, drop empty, de-duplicate (preserve order)."""
    out: List[str] = []
    seen = set()
    for raw in items or []:
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


# v1.5 compatibility: historical skill id aliases (avoid breaking old agents / old UI payloads)
_SKILL_ID_ALIASES = {
    # old -> new
    "builtin_vision.detect": "builtin_vision.detect_objects",
    # Some older payloads/records used non-builtin ids
    "vision.detect": "builtin_vision.detect_objects",
    "vision.detect_objects": "builtin_vision.detect_objects",
}


def _normalize_skill_ids(skill_ids: List[str]) -> List[str]:
    """Normalize + apply skill id aliases (keep order, de-duplicate)."""
    normalized = _normalize_id_list(skill_ids)
    mapped: List[str] = []
    for s in normalized:
        s2 = _SKILL_ID_ALIASES.get(s, s)

        # Accept both forms:
        # - builtin_<tool_name> (v1.5 Skill id)
        # - <tool_name> (legacy / UI payload / recovered data)
        if not s2.startswith("builtin_"):
            # If it's not a registered skill id, but builtin_<id> exists, promote it.
            if not SkillRegistry.get(s2) and SkillRegistry.get(f"builtin_{s2}"):
                s2 = f"builtin_{s2}"

        mapped.append(s2)
    return _normalize_id_list(mapped)


def _validate_replan_prompt_template(replan_prompt: str) -> Optional[str]:
    """Validate replan prompt template format and placeholder safety."""
    prompt = (replan_prompt or "").strip()
    if not prompt:
        return None
    if len(prompt) > MAX_REPLAN_PROMPT_TEMPLATE_LEN:
        return (
            f"replan_prompt is too long (max {MAX_REPLAN_PROMPT_TEMPLATE_LEN} characters)"
        )
    try:
        for _, field_name, _, _ in Formatter().parse(prompt):
            if field_name is None:
                continue
            if not re.fullmatch(r"\w+", field_name or ""):
                return (
                    f"replan_prompt placeholder '{field_name}' has unsupported format; "
                    "only {word_characters} are allowed"
                )
            if field_name not in ALLOWED_REPLAN_TEMPLATE_PLACEHOLDERS:
                return (
                    f"replan_prompt placeholder '{field_name}' is not allowed; "
                    f"allowed: {sorted(ALLOWED_REPLAN_TEMPLATE_PLACEHOLDERS)}"
                )
    except ValueError as e:
        return f"replan_prompt template format is invalid: {e}"
    return None

@router.get("")
async def list_agents():
    registry = get_agent_registry()
    return {"object": "list", "data": registry.list_agents()}

@router.post("")
async def create_agent(req: CreateAgentRequest):
    """Create a new agent with validation"""
    registry = get_agent_registry()
    
    # Validate model_id exists
    model_registry = get_model_registry()
    model = model_registry.get_model(req.model_id)
    if not model:
        # Also check if it's a valid model in any runtime
        available_models = model_registry.list_models()
        model_exists = any(m.id == req.model_id for m in available_models)
        if not model_exists:
            raise HTTPException(
                status_code=400, 
                detail=f"Model '{req.model_id}' not found. Please select a valid model."
            )

    # v1.5: enabled_skills 优先；若无则从 tool_ids 映射为 builtin_<tool_id>
    enabled_skills = _normalize_skill_ids(req.enabled_skills)
    if not enabled_skills and req.tool_ids:
        enabled_skills = _normalize_skill_ids([f"builtin_{t}" for t in _normalize_id_list(req.tool_ids)])
    for skill_id in enabled_skills:
        if not SkillRegistry.get(skill_id):
            raise HTTPException(
                status_code=400,
                detail=f"Skill '{skill_id}' not found. Please select a valid skill."
            )

    # Normalize and validate rag_ids (knowledge bases)
    rag_ids = _normalize_id_list(req.rag_ids)
    if rag_ids:
        kb_store = get_kb_store()
        if not kb_store:
            raise HTTPException(
                status_code=503,
                detail="Knowledge base store is not available. Please try again later."
            )
        for kb_id in rag_ids:
            if not kb_store.get_knowledge_base(kb_id):
                raise HTTPException(
                    status_code=400,
                    detail=f"Knowledge base '{kb_id}' not found. Please select a valid knowledge base."
                )

    failure_strategy = (req.on_failure_strategy or "stop").strip() or "stop"
    if failure_strategy not in {"stop", "continue", "replan"}:
        raise HTTPException(
            status_code=400,
            detail="on_failure_strategy must be one of: stop, continue, replan",
        )
    replan_prompt = (req.replan_prompt or "").strip()
    if failure_strategy == "replan" and not replan_prompt:
        raise HTTPException(
            status_code=400,
            detail="replan_prompt is required when on_failure_strategy is 'replan'",
        )
    replan_validate_error = _validate_replan_prompt_template(replan_prompt)
    if replan_validate_error:
        raise HTTPException(status_code=400, detail=replan_validate_error)
    
    # Generate agent_id
    agent_id = f"agent_{uuid.uuid4().hex[:8]}"
    
    # Create agent definition (v1.5: store enabled_skills; keep tool_ids for backward compat)
    model_params = _apply_response_mode(req.model_params, req.response_mode, enabled_skills)

    agent = AgentDefinition(
        agent_id=agent_id,
        name=req.name.strip(),
        description=req.description.strip(),
        model_id=req.model_id,
        system_prompt=req.system_prompt.strip() if req.system_prompt else "",
        enabled_skills=enabled_skills,
        tool_ids=[s[8:] for s in enabled_skills if s.startswith("builtin_")],
        rag_ids=rag_ids,
        max_steps=req.max_steps,
        temperature=req.temperature,
        slug=req.slug.strip() if req.slug else None,
        execution_mode=req.execution_mode or "legacy",
        use_execution_kernel=req.use_execution_kernel,
        max_replan_count=req.max_replan_count if req.max_replan_count is not None else 3,
        on_failure_strategy=failure_strategy,
        replan_prompt=replan_prompt,
        model_params=model_params,
    )
    
    if registry.create_agent(agent):
        logger.info(f"[Agent API] Agent created successfully: {agent_id} - {req.name}")
        return agent
    raise HTTPException(status_code=500, detail="Failed to create agent")

@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    registry = get_agent_registry()
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent

@router.put("/{agent_id}")
async def update_agent(agent_id: str, req: CreateAgentRequest):
    registry = get_agent_registry()
    
    # 获取现有 agent，用于合并 model_params
    existing_agent = registry.get_agent(agent_id)
    if not existing_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    enabled_skills = _normalize_skill_ids(req.enabled_skills)
    if not enabled_skills and req.tool_ids:
        enabled_skills = _normalize_skill_ids([f"builtin_{t}" for t in _normalize_id_list(req.tool_ids)])
    for skill_id in enabled_skills:
        if not SkillRegistry.get(skill_id):
            raise HTTPException(status_code=400, detail=f"Skill '{skill_id}' not found.")
    
    # 深度合并 model_params：保留原有字段，只更新请求中提供的字段
    if req.model_params is not None and req.model_params:
        # 请求中有 model_params，深度合并（保留原有字段）
        existing_params = existing_agent.model_params or {}
        model_params = {**existing_params, **req.model_params}
    else:
        # 请求中没有 model_params，保留原有的
        model_params = existing_agent.model_params or {}
    model_params = _apply_response_mode(model_params, req.response_mode, enabled_skills)

    failure_strategy = (req.on_failure_strategy or "stop").strip() or "stop"
    if failure_strategy not in {"stop", "continue", "replan"}:
        raise HTTPException(
            status_code=400,
            detail="on_failure_strategy must be one of: stop, continue, replan",
        )
    replan_prompt = (req.replan_prompt or "").strip()
    if failure_strategy == "replan" and not replan_prompt:
        raise HTTPException(
            status_code=400,
            detail="replan_prompt is required when on_failure_strategy is 'replan'",
        )
    replan_validate_error = _validate_replan_prompt_template(replan_prompt)
    if replan_validate_error:
        raise HTTPException(status_code=400, detail=replan_validate_error)
    
    agent = AgentDefinition(
        agent_id=agent_id,
        name=req.name,
        description=req.description,
        model_id=req.model_id,
        system_prompt=req.system_prompt,
        enabled_skills=enabled_skills,
        tool_ids=[s[8:] for s in enabled_skills if s.startswith("builtin_")],
        rag_ids=req.rag_ids,
        max_steps=req.max_steps,
        temperature=req.temperature,
        execution_mode=req.execution_mode or "legacy",
        use_execution_kernel=req.use_execution_kernel,
        max_replan_count=req.max_replan_count if req.max_replan_count is not None else 3,
        on_failure_strategy=failure_strategy,
        replan_prompt=replan_prompt,
        model_params=model_params,
    )
    if registry.update_agent(agent):
        return agent
    raise HTTPException(status_code=500, detail="Failed to update agent")

@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    registry = get_agent_registry()
    if registry.delete_agent(agent_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Agent not found")

def _get_agent_workspaces_root() -> Path:
    """Return data/agent_workspaces directory for session file uploads."""
    root = Path(__file__).resolve().parents[1] / "data"
    root.mkdir(parents=True, exist_ok=True)
    workspaces = root / "agent_workspaces"
    workspaces.mkdir(parents=True, exist_ok=True)
    return workspaces


def _normalize_filename(name: str) -> str:
    """NFC 归一化，避免 macOS NFD 与 LLM 传的 NFC 不一致导致找不到文件。"""
    import unicodedata
    return unicodedata.normalize("NFC", name)


def _resolve_agent_runtime_workspace(agent: AgentDefinition, session_id: str) -> str:
    """
    Resolve runtime workspace for an agent session.
    - Default: per-session workspace (data/agent_workspaces/{session_id})
    - Optional override: agent.model_params.workspace_root (absolute or relative)
    """
    session_workspace = (_get_agent_workspaces_root() / session_id).resolve()
    session_workspace.mkdir(parents=True, exist_ok=True)

    model_params = getattr(agent, "model_params", {}) or {}
    custom_root = model_params.get("workspace_root")
    if not custom_root:
        return str(session_workspace)

    try:
        candidate = Path(str(custom_root)).expanduser()
        if not candidate.is_absolute():
            # Relative path is resolved against project backend dir for predictability
            candidate = (Path(__file__).resolve().parents[1] / candidate).resolve()
        if candidate.exists() and candidate.is_dir():
            logger.info(f"[Agent API] Using agent workspace_root override: {candidate}")
            return str(candidate)
        logger.warning(
            f"[Agent API] Invalid workspace_root '{custom_root}' for agent={agent.agent_id}, fallback to session workspace"
        )
    except Exception as e:
        logger.warning(
            f"[Agent API] Failed to resolve workspace_root '{custom_root}' for agent={agent.agent_id}: {e}"
        )
    return str(session_workspace)


async def _save_uploaded_files(session_id: str, files: List[UploadFile]) -> Path:
    """Save uploaded files to session workspace; return workspace absolute path."""
    workspaces_root = _get_agent_workspaces_root()
    workspace_dir = workspaces_root / session_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for f in files or []:
        if not f.filename or f.filename.strip() == "":
            continue
        # 使用 basename + NFC 归一化，避免路径穿越及 macOS 文件名编码差异
        raw_name = Path(f.filename).name
        safe_name = _normalize_filename(raw_name)
        dest = workspace_dir / safe_name
        content = await f.read()
        dest.write_bytes(content)
    return workspace_dir.resolve()


@router.post("/{agent_id}/run")
async def run_agent(agent_id: str, req: RunAgentRequest):
    registry = get_agent_registry()
    session_store = get_agent_session_store()
    executor = get_agent_executor()
    
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # 获取或创建会话
    session_id = req.session_id or f"asess_{uuid.uuid4().hex[:12]}"
    session = session_store.get_session(session_id)
    
    if not session:
        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            messages=req.messages,
            status="idle"
        )
    else:
        # 如果是已有会话，追加新消息
        session.messages.extend(req.messages)
        session.status = "idle"
        session.step = 0 # 重置步数以开始新一轮 Loop

    # 默认使用会话 workspace；支持 Agent 级 workspace_root 覆盖（编程类 Agent 常用）
    workspace = _resolve_agent_runtime_workspace(agent, session_id)
    session.workspace_dir = workspace
    # 进入执行态，便于前端轮询感知（即便请求较慢）
    session.status = "running"
    session.error_message = None
    session_store.save_session(session)

    try:
        runtime = get_agent_runtime(executor)
        result_session = await runtime.run(agent, session, workspace=workspace)
        return result_session
    except asyncio.CancelledError:
        # Request cancelled/timed out by client/proxy: avoid leaving session in running forever.
        session.status = "error"
        session.error_message = "Request cancelled or timed out"
        session_store.save_session(session)
        logger.warning(
            f"[Agent API] run cancelled session_id={session_id} agent_id={agent_id}"
        )
        raise
    except Exception as e:
        # 避免会话卡在 idle 且前端无反馈
        session.status = "error"
        session.error_message = str(e)
        session_store.save_session(session)
        logger.exception(f"[Agent API] run failed session_id={session_id} agent_id={agent_id}: {e}")
        raise


@router.post("/{agent_id}/run/with-files")
async def run_agent_with_files(
    agent_id: str,
    messages: str = Form(..., description="JSON array of Message objects"),
    session_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[]),
):
    """Run agent with uploaded files. Files are saved to session workspace so file.read can access them."""
    registry = get_agent_registry()
    session_store = get_agent_session_store()
    executor = get_agent_executor()
    
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    try:
        messages_list = json.loads(messages)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid messages JSON: {e}")
    
    if not isinstance(messages_list, list):
        raise HTTPException(status_code=400, detail="messages must be a JSON array")
    
    # 转为 Message 对象，避免 session.messages 里混入 dict 导致 loop 中 model_dump 报错
    messages_objs = [Message(**m) if isinstance(m, dict) else m for m in messages_list]
    
    session_id = session_id or f"asess_{uuid.uuid4().hex[:12]}"
    # 带文件上传场景固定使用会话 workspace，保证上传文件可读
    workspace_dir = _get_agent_workspaces_root() / session_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir_str = str(workspace_dir.resolve())
    saved_names: List[str] = []
    logger.info(f"[Agent API] run/with-files received files count={len(files)} session_id={session_id}")
    if files:
        workspace_path = await _save_uploaded_files(session_id, files)
        workspace_dir_str = str(workspace_path)
        saved_names = [_normalize_filename(Path(f.filename).name) for f in files if f.filename and f.filename.strip()]
        logger.info(f"[Agent API] Saved {len(files)} file(s) to workspace {workspace_dir_str} names={saved_names}")
        if saved_names:
            first_path = workspace_path / saved_names[0]
            logger.info(f"[Agent API] verify first file exists={first_path.is_file()} path={first_path} dir_list={list(workspace_path.iterdir())}")
        # 在最后一条用户消息后追加提示：文件在工作目录，支持 file.read / vision.detect_objects
        if messages_objs and saved_names:
            last = messages_objs[-1]
            first_file = saved_names[0]
            # 检测是否为图像文件，便于给 vision 分析场景更明确的指引
            img_ext = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
            is_image = any(Path(n).suffix.lower() in img_ext for n in saved_names)
            if is_image:
                # 根据 Agent 启用的 skills 动态生成 hint
                enabled_skills = agent.enabled_skills or []
                has_vision = "builtin_vision.detect_objects" in enabled_skills
                has_vlm = "builtin_vlm.generate" in enabled_skills
                execution_mode = (getattr(agent, "execution_mode", None) or "legacy").strip().lower()
                
                if has_vision:
                    # Agent 启用了 vision.detect_objects，提供该 skill 的示例
                    if execution_mode == "plan_based":
                        # Plan-based 模式不依赖 LLM 输出 JSON skill_call，避免把“JSON-only”指令注入用户消息污染后续 prompt。
                        hint = (
                            f"\n\n[Files saved to workspace. Image: \"{first_file}\". "
                            f"You can reference the image by filename \"{first_file}\" when needed. "
                            f"Do NOT ask user for paths.]"
                        )
                    else:
                        hint = (
                            f"\n\n[Files saved to workspace. Image: \"{first_file}\". "
                            f"Call vision.detect_objects with {{\"image\": \"{first_file}\"}} to analyze. "
                            f"Respond ONLY in JSON, e.g. {{\"type\": \"skill_call\", \"skill_id\": \"builtin_vision.detect_objects\", \"input\": {{\"image\": \"{first_file}\"}}}}. "
                            f"Do NOT ask user for paths.]"
                        )
                elif has_vlm:
                    # Agent 只启用了 VLM，提供 VLM 的示例
                    if execution_mode == "plan_based":
                        hint = (
                            f"\n\n[Files saved to workspace. Image: \"{first_file}\". "
                            f"Use the image filename \"{first_file}\" as reference when needed. "
                            f"Do NOT ask user for paths.]"
                        )
                    else:
                        hint = (
                            f"\n\n[Files saved to workspace. Image: \"{first_file}\". "
                            f"You MUST call builtin_vlm.generate skill to analyze this image and get the actual text/content from the image. "
                            f"Do NOT use the image filename (e.g. \"{first_file}\") as the recognized text. "
                            f"Use {{\"type\": \"skill_call\", \"skill_id\": \"builtin_vlm.generate\", \"input\": {{\"image\": \"{first_file}\", \"prompt\": \"<user's question>\"}}}}. "
                            f"Do NOT ask user for paths. Do NOT provide final answer without calling the skill first.]"
                        )
                else:
                    # Agent 没有启用任何图像相关的 skill，只提供通用提示
                    hint = (
                        f"\n\n[Files saved to workspace. Image: \"{first_file}\". "
                        f"Use the image path \"{first_file}\" when needed. "
                        f"Do NOT ask user for paths.]"
                    )
            else:
                hint = (
                    "\n\n[Files have been saved to the current workspace. "
                    "When using file.read, use the **relative path** (filename only), e.g. path=\""
                    + first_file
                    + "\". Do NOT use absolute paths.]"
                )
            if len(saved_names) > 1 and not is_image:
                hint = (
                    "\n\n[Files have been saved to the current workspace: "
                    + ", ".join(f'"{n}"' for n in saved_names)
                    + ". When using file.read, use the **relative path** (filename only), e.g. path=\""
                    + first_file
                    + "\". Do NOT use absolute paths.]"
                )
            messages_objs[-1] = Message(role=last.role, content=last.content + hint)
    
    session = session_store.get_session(session_id)
    if not session:
        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            messages=messages_objs,
            status="idle"
        )
    else:
        session.messages.extend(messages_objs)
        session.status = "idle"
        session.step = 0

    # Track last uploaded files for deterministic image selection
    if saved_names:
        state = session.state or {}
        state["last_uploaded_images"] = saved_names
        state["last_uploaded_image"] = saved_names[0]
        session.state = state
    
    session.workspace_dir = workspace_dir_str
    # 在进入 loop 前持久化 session（含 workspace_dir），便于同会话后续请求使用正确工作目录
    session.status = "running"
    session.error_message = None
    session_store.save_session(session)

    try:
        runtime = get_agent_runtime(executor)
        result_session = await runtime.run(agent, session, workspace=workspace_dir_str)
        return result_session
    except asyncio.CancelledError:
        # Request cancelled/timed out by client/proxy: avoid leaving session in running forever.
        session.status = "error"
        session.error_message = "Request cancelled or timed out"
        session_store.save_session(session)
        logger.warning(
            f"[Agent API] run/with-files cancelled session_id={session_id} agent_id={agent_id}"
        )
        raise
    except Exception as e:
        # 避免会话卡在 idle 且前端无反馈
        session.status = "error"
        session.error_message = str(e)
        session_store.save_session(session)
        logger.exception(f"[Agent API] run/with-files failed session_id={session_id} agent_id={agent_id}: {e}")
        raise

@session_router.get("/agent-sessions")
async def list_agent_sessions(request: Request, agent_id: Optional[str] = None, limit: int = 50):
    user_id = _get_user_id(request)
    session_store = get_agent_session_store()
    sessions = session_store.list_sessions(user_id=user_id, limit=limit, agent_id=agent_id)
    return {"object": "list", "data": sessions}

@session_router.get("/agent-sessions/{session_id}")
async def get_agent_session(session_id: str):
    session_store = get_agent_session_store()
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@session_router.get("/agent-sessions/{session_id}/files/{filename}")
async def get_agent_session_file(session_id: str, filename: str):
    """Serve a file from the agent session workspace."""
    session_store = get_agent_session_store()
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    workspace = getattr(session, "workspace_dir", None)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        resolved = resolve_in_workspace(workspace=workspace, path=filename, allowed_absolute_roots=None)
    except WorkspacePathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(resolved))

class UpdateAgentSessionRequest(BaseModel):
    messages: Optional[List[Message]] = None
    status: Optional[str] = None

@session_router.patch("/agent-sessions/{session_id}")
async def update_agent_session(session_id: str, req: UpdateAgentSessionRequest):
    session_store = get_agent_session_store()
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if req.messages is not None:
        session.messages = req.messages
    if req.status is not None:
        session.status = req.status
    
    if session_store.save_session(session):
        return session
    raise HTTPException(status_code=500, detail="Failed to update session")

@session_router.get("/agent-sessions/{session_id}/trace")
async def get_agent_trace(session_id: str):
    trace_store = get_agent_trace_store()
    traces = trace_store.get_session_traces(session_id)
    # 将Pydantic模型转换为字典，确保可以正确序列化为JSON
    return {"object": "list", "data": [trace.model_dump() for trace in traces]}

@session_router.delete("/agent-sessions/{session_id}/messages/{message_index}")
async def delete_agent_session_message(session_id: str, message_index: int):
    """Delete a message from agent session by index"""
    session_store = get_agent_session_store()
    success = session_store.delete_message(session_id, message_index)
    if not success:
        raise HTTPException(status_code=404, detail="Session or message not found")
    # Return updated session
    updated_session = session_store.get_session(session_id)
    if not updated_session:
        raise HTTPException(status_code=404, detail="Session not found after deletion")
    return updated_session

@session_router.delete("/agent-sessions/{session_id}")
async def delete_agent_session(request: Request, session_id: str):
    """Delete an entire agent session"""
    user_id = _get_user_id(request)
    session_store = get_agent_session_store()
    success = session_store.delete_session(session_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True, "session_id": session_id}
