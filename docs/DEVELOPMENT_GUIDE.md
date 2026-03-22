# 🔧 开发指南

## 添加新的模型后端

1. 在 `backend/core/agents/` 目录下创建新的 Agent 类
2. 继承 `ModelAgent` 基类并实现必要方法：
   - `chat()`: 非流式聊天完成
   - `stream_chat()`: 流式聊天完成
   - `model_info()`: 返回模型信息
3. 在 `router.py` 中注册新的 Agent

示例：

```
from core.agents.base import ModelAgent
from core.types import ChatCompletionRequest

class MyCustomAgent(ModelAgent):
    async def chat(self, req: ChatCompletionRequest) -> str:
        # 实现非流式调用
        pass
    
    async def stream_chat(self, req: ChatCompletionRequest) -> AsyncIterator[str]:
        # 实现流式调用
        pass
    
    def model_info(self) -> dict:
        return {
            "backend": "my-custom",
            "supports_stream": True
        }
```

## 开发插件

插件系统支持能力扩展，遵循 [AGENTS.md](../AGENTS.md) 规范。

1. **创建插件目录**：在 `backend/core/plugins/builtin/` 下创建新目录
2. **实现插件类**：继承 `Plugin` 基类，实现 `execute` 方法
3. **创建 manifest**：编写 `plugin.json` 定义插件元数据、Schema 和权限
4. **注册插件**：插件会在启动时自动发现并加载

示例插件结构：

```
backend/core/plugins/builtin/my_plugin/
├── plugin.py      # 插件实现
└── plugin.json    # 插件清单
```

插件清单示例 (`plugin.json`)：

```json
{
  "name": "my_plugin",
  "version": "0.1.0",
  "description": "My custom plugin",
  "entry": "core.plugins.builtin.my_plugin.plugin:MyPlugin",
  "type": "capability",
  "stage": "pre",
  "supported_modes": ["chat"],
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"}
    },
    "required": ["query"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "result": {"type": "string"}
    }
  },
  "permissions": ["memory.read"]
}
```

详细规范请参考 [AGENTS.md](../AGENTS.md)。

## 开发智能体 (Agents)

智能体系统遵循 Agent v1.5 规范，支持完整的创建、运行和追踪流程。

1. **创建智能体**：通过 `POST /api/agents` 端点创建智能体
2. **运行智能体**：
   - `POST /api/agents/{agent_id}/run` - 标准运行（JSON 消息）
   - `POST /api/agents/{agent_id}/run/with-files` - 带文件上传（multipart）

智能体数据结构：

```python
from core.agent_runtime.definition import AgentDefinition

agent = AgentDefinition(
    agent_id="agent_xxx",
    name="My Agent",
    description="Agent description",
    model_id="llama3",
    system_prompt="You are a helpful assistant.",
    enabled_skills=["builtin_file.read", "builtin_web.search", "skill_xxx"],  # v1.5: Skill id 列表
    tool_ids=["file.read", "web.search"],  # 兼容字段，从 enabled_skills 推导
    rag_ids=["kb_xxx"],
    max_steps=5,
    temperature=0.7,
    slug="my-agent"  # URL-friendly identifier
)
```

智能体创建验证：
- 模型 ID 存在性校验
- Skill ID 校验（`enabled_skills` 中的每个 skill_id 必须存在）
- 知识库 ID 校验
- RAG 上下文自动注入到 Agent Loop

**Agent v1.5 特点：**
- Agent 仅通过 `enabled_skills` 使用 Skill，不直接接触 Tool
- LLM 输出解析为 `skill_call(skill_id, input)` 或 `tool_call`（映射为 `builtin_<tool>`）
- 支持自然语言工具描述兜底（识别 "Calling skill ..."）

## 开发 Skill

Skill 是 Agent 唯一可见的能力抽象，遵循 Skill v1 规范。

1. **创建 Skill**：通过 `POST /api/skills` 端点创建 Skill
2. **Skill 类型**：
   - `prompt`：纯 Prompt 渲染，无 Tool 绑定（常用于引导型高阶 Skills）
   - `tool`：绑定一个 Tool，通过 `definition.tool_name` 指定
   - `composite`：先渲染 prompt，再调用 tool
   - `workflow`：多 Tool 串行执行，通过 `definition.workflow_steps` 配置

Skill 数据结构：

```python
from core.skills.models import Skill

skill = Skill(
    id="skill_xxx",
    name="My Skill",
    description="Skill description",
    category="utilities",
    type="tool",  # prompt | tool | composite
    input_schema={
        "type": "object",
        "properties": {"param": {"type": "string"}},
        "required": ["param"]
    },
    definition={
        "tool_name": "file.read",  # type=tool 时指定
        "tool_args_mapping": {}    # Skill 输入 key -> Tool 参数 key
    },
    enabled=True
)
```

**Built-in Skills 自动注册：**
- 启动时，ToolRegistry 中的每个 Tool 会自动注册为 Built-in Skill（id=`builtin_<tool.name>`）
  - 内置高阶 Skills（复合能力）也会自动注册：
  - `builtin_research.summarize`：研究型（web.search + 引导总结）
  - `builtin_vision.detect` / `builtin_vision.detect_objects`：视觉目标检测（YOLO）
  - `builtin_document.analyze`：文档型（file.read + 文本处理）
  - `builtin_data.analyze`：数据分析型（python.run + 引导分析）
  - `builtin_api.operator`：API 操作型（http.request 封装）
  - `builtin_kb.query`：知识库查询型（RAG 语义接口）
  - `builtin_code.assistant`：代码助手型（file.read/write + diff）
- Agent 通过 `enabled_skills = ["builtin_file.read", "builtin_research.summarize", ...]` 使用
- Built-in Skills 不可编辑/删除，保持系统一致性

## 开发工具 (Tools)

工具是执行层原子能力，**仅通过 SkillExecutor 被 Agent 间接调用**，遵循 [Tools v1](../AGENTS.md) 规范。

1. **实现工具类**：在 `backend/core/plugins/builtin/tools/` 的相应类别下创建工具
2. **继承基类**：继承 `core.tools.base.Tool`，定义 `name`, `description`, `input_schema`
3. **实现 run 方法**：编写异步执行逻辑，使用 `ToolContext` 获取上下文（workspace、permissions 等）
4. **注册工具**：在对应类别的 `plugin.py` 中调用 `ToolRegistry.register()`

示例工具实现：

```python
from core.tools.base import Tool
from core.tools.context import ToolContext
from core.tools.result import ToolResult

class MyTool(Tool):
    @property
    def name(self) -> str:
        return "my_group.my_tool"

    @property
    def description(self) -> str:
        return "Does something useful"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"param": {"type": "string"}},
            "required": ["param"]
        }

    async def run(self, input_data: dict, ctx: ToolContext) -> ToolResult:
        # ctx.workspace 为会话工作目录（上传文件时设置）
        # ctx.permissions 为权限字典
        # 执行逻辑
        return ToolResult(success=True, data="Done")
```

**注意**：
- Tool 不感知 Agent/Skill，仅接收业务参数与 ToolContext
- 启动时会自动生成对应的 Built-in Skill（id=`builtin_<tool.name>`）
- HTTP Tools 和 system.env 默认禁用，需显式开启权限（Local-first 原则）
- Tool 通过 `ToolContext.workspace` 访问会话工作目录（文件上传时设置）

## 配置说明

后端配置位于 `backend/config/settings.py`，可通过环境变量覆盖：

- `HOST`: 服务主机地址（默认：0.0.0.0）
- `PORT`: 服务端口（默认：8000）
- `DEBUG`: 调试模式（默认：True）
- `MEMORY_VECTOR_ENABLED`: 是否启用向量搜索（默认：True）
- `MEMORY_EMBEDDING_DIM`: 向量维度（默认：256）
- `FILE_READ_ALLOWED_ROOTS`: 文件读取工具允许的绝对路径根目录，逗号分隔（如 `/` 表示允许任意目录，`/Users/tony,/data` 表示仅允许特定目录），默认值为 `/`（允许所有目录）
- `TOOL_NET_HTTP_ENABLED`: 是否启用 HTTP Tools（默认：False，Local-first 原则）
- `TOOL_NET_HTTP_ALLOWED_HOSTS`: HTTP Tools 允许的主机列表，逗号分隔，支持 `*.example.com` 后缀匹配
- `TOOL_SYSTEM_ENV_ENABLED`: 是否启用 system.env Tool（默认：False，防止泄露密钥）
- `TOOL_SYSTEM_ENV_ALLOWED_NAMES`: system.env 允许的环境变量名列表，逗号分隔
- `TOOL_SYSTEM_ENV_ALLOW_ALL`: 是否允许 system.env 返回所有环境变量（默认：False）

**资源管理相关配置**：
- 程序关闭时通过 FastAPI lifespan 机制进行可靠清理
- 支持 SIGINT、SIGTERM、SIGHUP 信号处理，涵盖 Ctrl+C、kill 命令和终端关闭场景
- 脚本层进程组管理确保子进程树完全终止
- Llama.cpp 模型实例自动跟踪与显式资源释放
- Embedding Runtime (ONNX) 显式关闭机制
- 前端页面卸载事件监听

前端配置位于 `frontend/.env`：

- `VITE_API_URL`: 后端 API 地址（默认：http://localhost:8000）

**聊天界面行为**：
- Enter 键仅用于换行，不触发消息发送
- 必须点击发送按钮或使用快捷键发送消息
- 防止意外提交未完成的消息

## 向量搜索配置

系统支持基于 `sqlite-vec` 的向量搜索功能，用于记忆检索和知识库查询。

**检查向量配置**：
```
cd backend
conda run -n ai-inference-platform python3 scripts/check_vector_config.py
```

**安装 sqlite-vec**（可选，如果安装失败会自动降级到 Python cosine 相似度计算）：
```bash
conda activate ai-inference-platform
pip install sqlite-vec
```

注意：`sqlite-vec` 是可选依赖，仅在启用 `memory_vector_enabled=True` 时需要。如果未安装，系统会自动使用 Python 实现的 cosine 相似度计算，功能不受影响但性能可能略低。
