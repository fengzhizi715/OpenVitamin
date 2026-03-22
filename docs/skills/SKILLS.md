# 系统内置 Skills 简述

本文档简述当前平台包含的 **Skills**（技能）：可被 Agent 启用的能力单元，用于工作流节点或对话中的工具调用。

---

## 1. 概念说明

- **Skill**：平台级能力资产，与具体 LLM 无关；Agent 通过 `enabled_skills` 配置可见的 Skill 列表。
- **类型**：
  - **prompt**：引导式技能，通过 prompt 指导 Agent 按步骤调用底层 Tool（如 `builtin_file.read`、`builtin_web.search`）。
  - **tool**：对单个 Tool 的薄封装，参数映射后直接调用。
  - **built-in image tool**：图片生成相关能力通过 Built-in Skill 暴露给 Agent，如 `builtin_image.generate`、`builtin_image.get_job`。
- **注册**：内置 Skill 在服务启动时由 `register_builtin_composite_skills()` 注册到 SkillRegistry，并持久化到 Skill Store。

---

## 2. 内置 Skills 列表

| ID | 名称 | 分类 | 类型 | 简述 |
|----|------|------|------|------|
| `builtin_research.summarize` | Research & Summarize | research | prompt | 联网检索并总结：使用 `builtin_web.search`、`builtin_text.split`/`truncate` 等，输出摘要与来源。 |
| `builtin_document.analyze` | Read & Analyze Documents | document | prompt | 读取并分析本地文档（PDF/MD/TXT）：`builtin_file.read` + 文本切分，输出结构化摘要、要点、问题与标签。 |
| `builtin_data.analyze` | Analyze Data with Python | analysis | prompt | 用 Python 做数据分析：通过 `builtin_file.read`、`builtin_python.run`、`builtin_file.write` 完成读取、分析、结果写出。 |
| `builtin_api.operator` | Call External API | api | tool | 调用外部 HTTP API：封装 `http.request`，支持 method、url、headers、body、auth、timeout 等。 |
| `builtin_kb.query` | Query Knowledge Base | rag | prompt | 知识库查询（RAG）：与 Agent 层 RAG 配合，引导提出清晰问题并基于检索上下文作答。 |
| `builtin_code.assistant` | Code Assistant | code | prompt | 读/写/重构代码：`builtin_file.read`、`builtin_text.diff`、`builtin_file.write`，按步骤完成查看、改稿、展示 diff、落盘。 |
| `builtin_project.tree` | Project Tree | file | tool | 生成项目目录树：封装 `file.tree`，支持 path、max_depth、include_hidden。 |
| `builtin_project.detect` | Detect Project | project | tool | 检测项目类型（Python/Node/Rust/Go/Java 等）并推断 test_command、build_command；封装 `project.detect`。 |
| `builtin_project.analyze` | Analyze Project | project | tool | 项目智能分析（V2.3）：封装 `project.analyze`，输出元信息、目录结构、模块与导入导出、入口、测试结构、依赖、框架与构建信息、风险概览等。 |
| `builtin_image.list_models` | List Image Models | image | tool | 列出当前可用的文生图模型与默认参数，封装 `image.list_models`。 |
| `builtin_image.generate` | Generate Image | image | tool | 提交图片生成任务，支持 prompt、negative_prompt、尺寸、steps、guidance、seed，并可自动选择默认文生图模型。 |
| `builtin_image.get_job` | Get Image Job | image | tool | 查询图片生成任务状态、phase、结果下载地址与缩略图。 |
| `builtin_image.cancel_job` | Cancel Image Job | image | tool | 取消运行中或排队中的图片生成任务。 |

---

## 3. 内置 Tools 列表

Tools 是底层能力单元，可被 Skill 或工作流中的 Tool 节点直接调用；每个 Tool 有唯一 `name`（如 `file.read`）、描述与输入/输出 schema，并声明所需权限。

| 分类 | Tool 名称 | 简述 |
|------|-----------|------|
| **file** | `file.read` | 读取文件内容，支持工作区相对路径或配置的绝对根路径。 |
| | `file.list` | 列出目录下的文件，限定在工作区目录。 |
| | `file.write` | 写入文件，不存在则创建，存在则覆盖。 |
| | `file.append` | 向文件追加内容，不存在则创建。 |
| | `file.delete` | 删除文件（仅文件，不删目录）。 |
| | `file.patch` | 使用 unified diff 格式打补丁，应用前会备份。 |
| | `file.apply_patch` | 对工作区文件应用 unified diff，有行数/路径等安全限制。 |
| | `file.search` | 在文件中按模式（含正则、glob）搜索，可输出行号。 |
| | `file.tree` | 生成目录树，可指定深度。 |
| **python** | `python.run` | 在沙箱中执行 Python 代码，返回 stdout/stderr/exit_code。 |
| **web** | `web.search` | 联网搜索（需配置搜索后端）。 |
| **sql** | `sql.query` | 执行 SQL 查询（需配置数据源与权限）。 |
| **http** | `http.get` | 发送 HTTP GET 请求。 |
| | `http.post` | 发送 HTTP POST 请求。 |
| | `http.request` | 通用 HTTP 请求，支持 method、url、headers、body 等。 |
| **text** | `text.split` | 按分隔符或长度切分文本。 |
| | `text.truncate` | 截断文本到指定长度。 |
| | `text.regex_extract` | 用正则从文本中提取内容。 |
| | `text.diff` | 计算两段文本的 diff。 |
| **time** | `time.now` | 获取当前时间。 |
| | `time.format` | 时间格式化。 |
| | `time.sleep` | 休眠指定秒数。 |
| **system** | `system.cpu` | 获取 CPU 使用情况。 |
| | `system.memory` | 获取内存使用情况。 |
| | `system.disk` | 获取磁盘使用情况。 |
| | `system.env` | 读取环境变量。 |
| **vision** | `vision.detect_objects` | 使用 YOLO 检测图像中的物体，可输出标注图。 |
| | `vision.segment_objects` | 使用 FastSAM 做实例分割，可输出 mask 与标注图。 |
| **vlm** | `vlm.generate` | 根据图像 + 文本 prompt 用 VLM 生成文本。 |
| **image** | `image.list_models` | 列出可用文生图模型与默认参数。 |
| | `image.generate` | 提交图片生成任务，支持 prompt、negative_prompt、尺寸、steps、guidance、seed。 |
| | `image.get_job` | 查询图片任务状态、phase、结果、下载地址与缩略图。 |
| | `image.cancel_job` | 取消图片生成任务。 |
| **shell** | `shell.run` | 执行 shell 命令，返回 stdout、stderr、exit_code；需 `shell.run` 权限。 |
| **project** | `project.detect` | 从工作区根目录检测项目类型并推断 test/build 命令。 |
| | `project.scan` | 扫描工作区得到项目类型、test/build 命令、git 等，产出 project_context。 |
| | `project.test` | 执行项目测试（依赖 project_context，通常先调 project.scan）。 |
| | `project.build` | 执行项目构建。 |
| | `project.analyze` | 项目智能分析：元信息、目录结构、模块与导入、入口、测试与依赖、风险概览等。 |

---

## 4. 分类与用途速览

- **research**：检索与总结，适合调研类任务。
- **document**：本地文档读取与结构化分析。
- **analysis**：数据 + Python 分析流水线。
- **api**：对外 HTTP 调用。
- **rag**：知识库问答，依赖 Agent 的 RAG 配置。
- **image**：图片生成与图片任务状态管理。
- **code**：代码阅读、修改与 diff。
- **file**：文件/目录结构查看（目录树）。
- **project**：项目类型检测、项目级分析，便于在改代码前理解工程结构。

---

## 5. 使用方式

- **Agent 配置**：在 Agent 的 `enabled_skills` 中填入上述 Skill ID，该 Agent 在对话或工作流中即可按需调用对应能力。图片型 Agent 可启用 `builtin_image.*`，配合 `intent_rules` 或语义发现路由到文生图能力。
- **工作流**：工作流中的 Skill 节点通过 `tool_id` / `tool_name` 绑定到已注册的 Tool；部分能力由上述 composite Skill 通过多步 Tool 调用实现。
- **扩展**：除内置 Skill 外，可通过 Skill API 注册自定义 Skill（名称、描述、类型、definition、input_schema 等），注册后同样可被 Agent 与工作流使用。

---

## 6. 相关代码位置

- 内置 Skill 定义与注册：`backend/core/plugins/builtin/skills/__init__.py`
- Skill 模型与注册表：`backend/core/skills/models.py`、`backend/core/skills/registry.py`
- Skill 执行：`backend/core/skills/executor.py`、`backend/core/skills/service.py`
- 内置 Tool 注册：`backend/core/plugins/builtin/tools/__init__.py`（file / python / web / sql / http / text / time / system / vision / vlm / image / shell / project 等子目录）
- Tool 基类与注册表：`backend/core/tools/base.py`、`backend/core/tools/registry.py`
- Vision/VLM/Image 工具实现：`backend/core/tools/yolo/`、`backend/core/tools/vlm/`、`backend/core/tools/image/`
