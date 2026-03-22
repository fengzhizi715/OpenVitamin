"""
配置设置
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""
    app_name: str = "OpenVitamin大模型与智能体应用平台"
    version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    debug: bool = True
    
    # 服务器
    host: str = "0.0.0.0"
    port: int = 8000
    
    # 模型配置
    default_model: str = "llama-3-70b-instruct"
    
    # Ollama 配置
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = ""  # 为空则自动使用本地已下载的第一个模型

    # 数据库配置 (统一合并管理)
    db_path: str = ""  # 为空则使用默认 backend/data/platform.db

    # 文件读取工具：允许的绝对路径根目录（逗号分隔）。在此列表下的绝对路径可被 file.read 读取。
    # 例如："/" 表示允许本机任意目录；"/Users/tony,/data" 表示仅允许这两棵目录。
    # 为空时默认仅允许当前用户主目录。
    file_read_allowed_roots: str = "/"

    # -------------------------
    # Tool permissions (Local-first & Privacy-first)
    # -------------------------
    # HTTP tools: default disabled; enable explicitly for private deployments.
    tool_net_http_enabled: bool = True
    # Optional allowlist (comma-separated). Supports exact host match and suffix match via "*.example.com".
    # Empty means "no host restrictions" when tool_net_http_enabled is True.
    tool_net_http_allowed_hosts: str = ""

    # Web search (DuckDuckGo). Default below; optional override via env TOOL_NET_WEB_ENABLED (no .env required).
    tool_net_web_enabled: bool = True
    # Optional: WEB_SEARCH_SERPER_API_KEY for Google search (Serper). If set, uses Serper instead of DuckDuckGo.
    web_search_serper_api_key: str = ""

    # system.env tool is sensitive (may leak secrets): default disabled.
    tool_system_env_enabled: bool = False
    # Allowlist env var names (comma-separated). Empty means "deny all names" unless tool_system_env_enabled is True and name is explicitly allowed.
    tool_system_env_allowed_names: str = ""
    # Whether system.env may return all variables (very sensitive). Default: False.
    tool_system_env_allow_all: bool = False

    # 模型存储目录
    local_model_directory: str = "~/.local-ai/models/"

    # YOLO 目标检测模型路径（可选，为空则使用 local_model_directory/perception/YOLOv8/yolov8s.pt）
    yolo_model_path: str = ""
    # YOLO 运行设备：cpu / cuda / mps / auto（auto 自动选择 cuda > mps > cpu）
    yolo_device: str = "mps"
    # YOLO 默认 backend：yolov8 / yolov11 / onnx
    yolo_default_backend: str = "yolov8"
    # 文生图默认模型 ID（可选，为空则按运行时可用模型自动选择）
    image_generation_default_model_id: str = ""

    # 本地模型切换时是否自动卸载上一个模型（默认关闭，避免频繁冷启动）
    auto_unload_local_model_on_switch: bool = False
    # 运行时资源回收（通用）
    runtime_auto_release_enabled: bool = True
    # 缓存本地重模型的上限（超出后回收最久未使用模型）
    runtime_max_cached_local_runtimes: int = 1
    # 按模型类型拆分的缓存上限；未配置时回退到 runtime_max_cached_local_runtimes
    runtime_max_cached_local_llm_runtimes: int = 1
    runtime_max_cached_local_vlm_runtimes: int = 1
    runtime_max_cached_local_image_generation_runtimes: int = 1
    # 空闲回收阈值（秒）
    runtime_release_idle_ttl_seconds: int = 300
    # 自动回收最小触发间隔（秒），用于抑制并发尖峰抖动
    runtime_release_min_interval_seconds: int = 5
    # V2.9 按 runtime 类型的并发上限覆盖（JSON 对象，如 {"llama.cpp": 1, "ollama": 4}）。为空则使用代码默认 MODEL_RUNTIME_CONFIG。
    runtime_max_concurrency_overrides: str = ""
    # model.json 备份根目录，为空则使用 backend/data/backups（与 DB 备份目录并列时其下为 model_json/）
    model_json_backup_directory: str = ""
    # model.json 定时全量快照：是否启用、每日执行时间（UTC，如 "02:00" 或 "02:00:00"）
    model_json_backup_daily_enabled: bool = False
    model_json_backup_daily_time: str = "02:00"
    # MPS 内存压力阈值（current/recommended），超阈值触发积极回收
    runtime_mps_pressure_threshold: float = 0.85
    # 系统内存压力阈值（psutil.virtual_memory().percent），超阈值触发积极回收
    # 用于覆盖 llama.cpp 等不计入 torch.mps 统计的内存占用场景。
    runtime_ram_pressure_threshold: float = 85.0
    # 启动时将超过该阈值的 running 会话标记为 error（秒）
    agent_stale_running_session_seconds: int = 1800

    # Workflow wait=true 同步等待超时（秒）
    workflow_wait_timeout_seconds: int = 120
    # Workflow wait=true 允许的最大超时上限（秒）
    workflow_wait_timeout_max_seconds: int = 3600
    # Workflow 执行接口默认等待策略（False=默认异步）
    workflow_execution_wait_default: bool = False
    # 是否允许执行未发布（draft）版本；关闭后仅允许 published 版本执行
    # 生产建议：False。调试环境可通过 debug 覆盖开关放开。
    workflow_allow_draft_execution: bool = False
    # 当 debug=True 且 workflow_allow_draft_execution=False 时，是否允许调试环境自动放开 draft 执行
    workflow_allow_draft_execution_debug_override: bool = True
    # 无已发布版本时回退 draft 的告警最小间隔（秒）
    workflow_draft_fallback_warn_interval_seconds: float = 60.0
    # Workflow 持久化写入重试（SQLite 锁冲突）
    workflow_db_write_retry_attempts: int = 4
    workflow_db_write_retry_base_delay_ms: int = 50
    # Workflow 跨进程并发兜底（基于 DB running 数量的软限制）
    workflow_distributed_running_limit_enabled: bool = True
    workflow_distributed_running_limit_per_workflow: int = 3
    workflow_distributed_running_limit_wait_seconds: float = 15.0
    # 分布式并发兜底等待超时后是否 fail-open 继续执行（True 可避免直接失败）
    workflow_distributed_running_limit_fail_open: bool = True
    # 视为“陈旧 running”并在分布式并发限流时忽略/回收的阈值（秒）
    workflow_distributed_running_stale_seconds: int = 1800
    # 分布式并发限流检查时，是否自动将陈旧 running 回收为 failed
    workflow_distributed_running_auto_reconcile_stale: bool = True
    # Workflow 执行长期 pending 告警（秒）
    workflow_pending_warn_seconds: float = 8.0
    # Workflow 执行 pending 告警重复间隔（秒）
    workflow_pending_warn_interval_seconds: float = 5.0

    # 长期记忆（MVP）
    enable_long_term_memory: bool = False
    memory_inject_mode: str = "recent"  # recent | keyword | vector
    memory_inject_top_k: int = 5

    # 向量检索（sqlite-vec 优先，失败则自动降级 python cosine）
    memory_vector_enabled: bool = True
    memory_embedding_dim: int = 256
    memory_default_confidence: float = 0.6

    # 冲突/合并/衰减（MVP）
    memory_merge_enabled: bool = True
    memory_merge_similarity_threshold: float = 0.92
    memory_conflict_enabled: bool = True
    memory_conflict_similarity_threshold: float = 0.85
    memory_decay_half_life_days: int = 30

    # 结构化 Memory Key Schema（确定性）
    memory_key_schema_enforced: bool = True
    memory_key_schema_allow_unlisted: bool = False

    # 记忆提取器（使用 OpenAI 兼容 chat/completions）
    memory_extractor_enabled: bool = False
    memory_extractor_temperature: float = 0.0
    memory_extractor_top_p: float = 1.0
    memory_extractor_max_tokens: int = 256

    # Chat 持久化策略：
    # - off: 不创建会话/不落库，仅做推理
    # - minimal: 仅在有有效 user_text 且推理成功时落库，避免中间态噪声
    # - full: 完整记录（默认）
    chat_persistence_mode: str = "full"
    # 无 X-Session-Id 时，复用最近活跃会话窗口（分钟）。0 表示不复用。
    chat_session_reuse_window_minutes: int = 15
    # 自动生成会话标题的最大长度
    chat_session_title_max_len: int = 50
    # 幂等键 header（逗号分隔），用于防重写入
    chat_idempotency_headers: str = "Idempotency-Key,X-Request-Id"
    # 强制新会话 header（逗号分隔）；命中后跳过会话复用逻辑
    chat_force_new_session_headers: str = "X-Force-New-Session,X-New-Chat"
    # 输入清洗：剥离上游传输层包装文本（如 sender metadata 包裹）
    chat_input_strip_transport_wrappers: bool = True
    # 输出清洗：剥离推理思维链外显（<think>...</think> / 思维前缀）
    chat_output_strip_reasoning: bool = True
    # Auto 选模是否强制本地优先（存在本地候选时仅在本地中选择）
    model_selector_auto_local_first_strict: bool = True
    # 文生图任务队列：每个模型最多允许 queued+running 的任务数
    image_generation_max_pending_jobs_per_model: int = 4
    
    class Config:
        env_file = ".env"


# 全局配置实例
settings = Settings()
