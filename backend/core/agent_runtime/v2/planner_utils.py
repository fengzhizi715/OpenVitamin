"""
Planner Utilities - 静态工具函数

这些函数用于从用户输入中提取结构化信息（路径、命令、图片等）。
所有函数都是纯函数，不依赖 Planner 实例状态。
"""
import re
from typing import Any, Dict, List, Optional


def _sanitize_path_candidate(path: str) -> str:
    """清理自然语言中提取的路径，去除尾随中文标点/配对符号。"""
    if not isinstance(path, str):
        return ""
    p = path.strip().strip("`\"'")
    # 去除常见尾随标点与配对字符
    p = re.sub(r"[，。！？；、,;:)\]）】》>]+$", "", p).strip()
    return p


def extract_record_filename(system_prompt: str) -> Optional[str]:
    """从 system_prompt 中提取约定的 .json 记录文件名（如 weekly_records.json）。"""
    if not system_prompt:
        return None
    m = re.search(r"`([A-Za-z0-9_.-]+\.json)`", system_prompt)
    if m:
        return m.group(1)
    m2 = re.search(r"([A-Za-z0-9_.-]+\.json)", system_prompt)
    if m2:
        return m2.group(1)
    return None


def extract_shell_command(
    user_input: str,
    config: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    从自然语言中提取可执行 shell 命令。
    配置驱动的参数提取器，内部逻辑可通过 config 自定义。
    """
    config = config or {}
    text = (user_input or "").strip()
    if not text:
        return None

    # code block: ```bash ... ``` (始终启用)
    block = re.search(r"```(?:bash|sh|zsh)?\s*\n(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if block:
        cmd = block.group(1).strip()
        if cmd and "{" not in cmd and "}" not in cmd:
            return cmd

    # 从配置获取自定义前缀模式，未配置则使用默认值
    prefix_pattern = config.get("prefix_pattern", r"^\s*(?:运行测试|run test|测试|执行)\s*[:：]\s*(.+)$")
    try:
        m = re.match(prefix_pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            cmd = m.group(1).strip()
            if cmd and "{" not in cmd and "}" not in cmd:
                return cmd
    except re.error:
        pass

    # 从配置获取自定义命令头，未配置则使用默认值
    command_heads = config.get("command_heads", (
        "cd ", "pytest", "python ", "python3 ", "pip ", "npm ", "pnpm ", "yarn ",
        "node ", "go ", "cargo ", "make ", "bash ", "sh ", "uv "
    ))
    if text.startswith(command_heads) and "{" not in text and "}" not in text:
        return text
    return None


def extract_path_from_text(
    user_input: str,
    config: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    从用户输入提取路径（目录或文件名）。
    配置驱动的参数提取器，内部逻辑可通过 config 自定义。
    支持：path:/路径:、./、../、tree、带扩展名的文件名（含「创建 xxx 文件」等表述）。
    """
    config = config or {}
    text = (user_input or "").strip()
    if not text:
        return None

    # 显式 path/路径/目录 指定 (始终启用)
    m = re.search(r"(?:path|路径|目录|folder|dir)\s*[:：]\s*([^\n]+)", text, re.IGNORECASE)
    if m:
        path = _sanitize_path_candidate(m.group(1))
        if path:
            return path

    # 显式「文件: xxx」或「文件名: xxx」
    m_file = re.search(r"(?:文件|文件名|file)\s*[:：]\s*([^\s,，。\n]+)", text, re.IGNORECASE)
    if m_file:
        path = _sanitize_path_candidate(m_file.group(1))
        if path:
            return path

    # 从配置获取 tree 命令模式，未配置则使用默认值
    tree_pattern = config.get("tree_pattern", r"^\s*tree\s+([^\s]+)\s*$")
    try:
        m2 = re.match(tree_pattern, text, re.IGNORECASE)
        if m2:
            return _sanitize_path_candidate(m2.group(1))
    except re.error:
        pass

    # 从配置获取路径 token 模式，未配置则使用默认值
    path_token_pattern = config.get(
        "path_token_pattern",
        r"((?:\./|\../|/)[^\s,;，。；：！？\]\)）】>]+)",
    )
    try:
        m3 = re.search(path_token_pattern, text)
        if m3:
            return _sanitize_path_candidate(m3.group(1))
    except re.error:
        pass

    # 文件名类：创建/写入/保存 xxx.txt 文件、名为 xxx.json、引号内 "xxx.md"
    # 扩展名覆盖文档类 + 常见代码文件，便于编程智能体提取目标文件路径。
    ext_pattern = (
        r"(?:txt|json|md|csv|yaml|yml|log|conf|cfg|ini|xml|html|"
        r"py|js|ts|tsx|jsx|java|kt|kts|go|rs|c|cc|cpp|cxx|h|hpp|"
        r"cs|php|rb|swift|m|mm|scala|sh|bash|zsh|sql|proto|vue)"
    )
    # 创建 test.txt 文件 / 写入 data.json / 保存到 foo.cpp
    m_create = re.search(
        rf"(?:创建|写入|保存|新建|生成|输出|实现)\s*(?:到|为|成|as|to)?\s*[「\"']?([a-zA-Z0-9_./-]+\.{ext_pattern})[」\"']?\s*(?:文件)?",
        text,
        re.IGNORECASE,
    )
    if m_create:
        return _sanitize_path_candidate(m_create.group(1))
    # 名为 test.txt / 文件名 test.txt
    m_named = re.search(rf"(?:名为|文件名)\s*[「\"']?([a-zA-Z0-9_.-]+\.{ext_pattern})[」\"']?", text, re.IGNORECASE)
    if m_named:
        return _sanitize_path_candidate(m_named.group(1))
    # 引号内 "test.txt" 或 'data.json'
    m_quoted = re.search(rf"[「\"']([a-zA-Z0-9_.-]+\.{ext_pattern})[」\"']", text)
    if m_quoted:
        return _sanitize_path_candidate(m_quoted.group(1))
    # 无引号带扩展名（取第一个匹配）
    m_bare = re.search(rf"\b([a-zA-Z0-9_.-]+\.{ext_pattern})\b", text)
    if m_bare:
        return _sanitize_path_candidate(m_bare.group(1))

    # 从配置获取默认路径关键词，未配置则使用默认值
    default_keywords = config.get("default_keywords", ["tree", "项目结构", "目录树", "project structure"])
    if any(k in text.lower() for k in default_keywords):
        return config.get("default_path", ".")

    return None


def extract_workspace_from_text(
    user_input: str,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    从用户输入中提取 workspace 路径。
    仅在识别到显式路径时返回，避免将"项目分析"类自然语言误判为 "."。
    """
    text = (user_input or "").strip()
    if not text:
        return None

    # 优先识别 workspace: /path / 工作区: /path / 项目路径: /path
    m = re.search(
        r"(?:workspace|工作区|项目路径|project\s*path)\s*[:：=]\s*([^\n]+)",
        text,
        re.IGNORECASE,
    )
    if m:
        ws = _sanitize_path_candidate(m.group(1))
        if ws:
            return ws

    cfg = dict(config or {})
    # workspace 提取默认不做关键词回退，避免落到 "."
    cfg.setdefault("default_keywords", [])
    return extract_path_from_text(text, cfg)


def extract_image_from_text(user_input: str) -> Optional[str]:
    """
    从用户输入中提取图片文件名。
    支持格式：
    - [Files saved to workspace. Image: "xxx.jpg"]
    - [Attachments: xxx.jpg]
    - [File 1: xxx.jpg]
    """
    text = user_input or ""
    
    # 格式 1: [Files saved to workspace. Image: "xxx.jpg"]
    m = re.search(r'Image:\s*"([^"]+)"', text)
    if m:
        return m.group(1).strip()
    
    # 格式 2: [Attachments: xxx.jpg]
    m = re.search(r'Attachments:\s*([^\]\n]+)', text)
    if m:
        filename = m.group(1).strip()
        # 去除可能的路径前缀
        return filename.split("/")[-1].split("\\")[-1]
    
    # 格式 3: [File 1: xxx.jpg]
    m = re.search(r'File\s*\d*:\s*([^\(]+)', text)
    if m:
        filename = m.group(1).strip()
        return filename.split("/")[-1].split("\\")[-1]
    
    return None


def strip_injected_workspace_hints(text: str) -> str:
    """
    剥离 API 层注入的 workspace/file hint，避免污染下游技能的 prompt（尤其是 VLM）。

    典型注入格式：
    - [Files saved to workspace. Image: "xxx.jpg" ...]
    - [Files have been saved to the current workspace ...]
    """
    s = (text or "")
    if not s:
        return s
    # 移除整段方括号注入（非贪婪），仅匹配以 "Files saved..." 开头的块
    s = re.sub(r"\n\n\[Files saved to workspace\.[\s\S]*?\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\n\n\[Files have been saved to the current workspace\.[\s\S]*?\]", "", s, flags=re.IGNORECASE)
    return s.strip()


def keyword_matches(user_lower: str, keyword: str) -> bool:
    """
    关键词匹配：
    - 中文/含非 ASCII：子串匹配（适合"测试/目录树"等）
    - 纯英文/数字/下划线/连字符：按词边界匹配，避免 test 命中 tree
    """
    if not isinstance(keyword, str):
        return False
    kw = keyword.strip().lower()
    if not kw:
        return False

    # 含非 ASCII 时保留子串匹配
    if any(ord(ch) > 127 for ch in kw):
        return kw in user_lower

    # 英文词按边界匹配：(?<![a-z0-9_])kw(?![a-z0-9_])
    pattern = rf"(?<![a-z0-9_]){re.escape(kw)}(?![a-z0-9_])"
    return re.search(pattern, user_lower) is not None


def match_configured_intent_rules(
    user_input: str,
    user_lower: str,
    available_skills: List[str],
    model_params: Dict[str, Any],
) -> Optional[str]:
    """
    从 Agent model_params.intent_rules 匹配技能。
    规则结构：
    [
      {"keywords": ["测试", "test"], "skills": ["builtin_shell.run"]},
      {"regex": "\\d{4}-\\d{1,2}-\\d{1,2}", "skills": ["builtin_file.append"]},
      ...
    ]
    
    支持两种匹配方式：
    - keywords: 关键词列表，使用边界感知匹配
    - regex: 正则表达式模式，直接匹配用户输入
    """
    from log import logger
    
    rules = model_params.get("intent_rules")
    if not isinstance(rules, list):
        return None
    
    def _resolve_skill_id(skill_id: Any) -> Optional[str]:
        if not isinstance(skill_id, str):
            return None
        sid = skill_id.strip()
        if not sid:
            return None
        if sid in available_skills:
            return sid
        # 兼容 builtin_ 前缀差异
        if sid.startswith("builtin_"):
            alt = sid[len("builtin_"):]
            if alt in available_skills:
                return alt
        else:
            alt = f"builtin_{sid}"
            if alt in available_skills:
                return alt
        # 兼容版本后缀（例如 xxx@1.0.0）
        for candidate in available_skills:
            if not isinstance(candidate, str):
                continue
            base = candidate.split("@", 1)[0]
            if sid == base:
                return candidate
            if sid.startswith("builtin_") and sid[len("builtin_"):] == base:
                return candidate
            if (not sid.startswith("builtin_")) and f"builtin_{sid}" == base:
                return candidate
        return None

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        
        # 检查 regex 模式匹配
        regex_pattern = rule.get("regex")
        if regex_pattern and isinstance(regex_pattern, str):
            try:
                if re.search(regex_pattern, user_input, re.IGNORECASE):
                    skills = rule.get("skills", [])
                    if isinstance(skills, list):
                        for skill_id in skills:
                            resolved = _resolve_skill_id(skill_id)
                            if resolved:
                                return resolved
            except re.error:
                logger.warning(f"[Planner] Invalid regex pattern: {regex_pattern}")
        
        # 检查 keywords 列表匹配
        keywords = rule.get("keywords", [])
        skills = rule.get("skills", [])
        if not isinstance(keywords, list) or not isinstance(skills, list):
            continue
        if any(
            isinstance(k, str) and keyword_matches(user_lower, k)
            for k in keywords
        ):
            for skill_id in skills:
                resolved = _resolve_skill_id(skill_id)
                if resolved:
                    return resolved
    return None


def get_replan_direct_skill_config(agent) -> Dict[str, Any]:
    """获取 RePlan 直接技能配置"""
    model_params = getattr(agent, "model_params", {}) or {}
    cfg = model_params.get("replan_direct_skill")
    # backward compatibility: old boolean toggle
    if cfg is None:
        legacy_enabled = bool(model_params.get("enable_replan_direct_skill", False))
        cfg = {"enabled": legacy_enabled}
    if not isinstance(cfg, dict):
        return {"enabled": False}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "when": cfg.get("when") if isinstance(cfg.get("when"), list) else ["any"],
        "strategy": str(cfg.get("strategy") or "retry_failed_skill"),
        "fixed_skill_id": cfg.get("fixed_skill_id"),
        "fixed_skill_inputs": cfg.get("fixed_skill_inputs") if isinstance(cfg.get("fixed_skill_inputs"), dict) else {},
        "allowed_skills": cfg.get("allowed_skills") if isinstance(cfg.get("allowed_skills"), list) else [],
        "fallback": str(cfg.get("fallback") or "planner_replan"),
    }


def classify_replan_failure(execution_context: Dict[str, Any]) -> str:
    """分类 RePlan 失败类型"""
    from .models import ExecutorType
    
    step = execution_context.get("last_failed_step")
    last_error = str(execution_context.get("last_error") or "").lower()
    if "timeout" in last_error or "timed out" in last_error:
        return "timeout"
    if step is None:
        return "unknown"
    if getattr(step, "executor", None) == ExecutorType.SKILL:
        return "skill_failed"
    return "step_failed"


def extract_filename_from_error(error: Optional[str]) -> Optional[str]:
    """从错误信息中提取文件名"""
    if not error:
        return None
    
    # 常见测试错误格式：File "xxx.py", line N
    match = re.search(r'File "([^"]+)", line', error)
    if match:
        return match.group(1)
    
    # 或者简单的文件名模式
    match = re.search(r'(\w+\.py)', error)
    if match:
        return match.group(1)
    
    return None


def extract_command_from_context(context: Dict[str, Any]) -> Optional[str]:
    """从上下文中提取测试命令"""
    last_failed_step = context.get("last_failed_step")
    if last_failed_step and last_failed_step.inputs:
        inputs = last_failed_step.inputs
        # shell.run 的输入格式
        if isinstance(inputs, dict):
            cmd_inputs = inputs.get("inputs", {})
            if isinstance(cmd_inputs, dict):
                return cmd_inputs.get("command")
    return None
