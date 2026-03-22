# 本地 AI 推理平台部署指南

本项目是一个集成了 FastAPI 后端网关和 Vue 3 前端界面的本地 AI 推理平台。本文档将指导您如何在本地环境完成部署。

## 1. 环境准备

在开始之前，请确保您的系统中已安装以下软件：

*   **Conda**: 用于管理 Python 虚拟环境（推荐使用 Miniconda 或 Anaconda）。
*   **Node.js**: 建议版本为 v18 或更高。
*   **NPM**: 通常随 Node.js 一起安装。

## 2. 后端部署 (FastAPI)

后端作为推理网关，负责协调模型调用和插件逻辑。

### 2.1 创建并激活环境

打开终端，执行以下命令：

```bash
# 创建虚拟环境 (Python 3.11)
conda create -n ai-inference-platform python=3.11 --yes

# 激活环境
conda activate ai-inference-platform
```

### 2.2 安装依赖

进入项目根目录，安装必要的 Python 包：

```bash
# 确保在项目根目录
cd /path/to/local_ai_inference_platform
pip install -r backend/requirements.txt
```

**主要依赖包括：**
* FastAPI - Web 框架
* jsonschema - JSON Schema 验证（用于插件系统）
* sqlite-vec - 向量数据库支持（**可选**，如果安装失败会自动降级到 Python cosine 相似度计算）
* openai - OpenAI API 客户端
* llama-cpp-python - 本地模型推理
* 其他依赖见 `backend/requirements.txt`

**注意：** `sqlite-vec` 是可选依赖，用于向量搜索功能。如果安装失败，系统会自动降级到 Python 实现的 cosine 相似度计算，不影响基本功能。仅在启用 `memory_vector_enabled=True` 配置时才需要。

### 2.3 运行后端服务

**方式一：使用启动脚本（推荐）**

```bash
# 在项目根目录执行
./run-backend.sh
```

**方式二：手动运行**

```bash
# 进入后端目录
cd backend
conda run -n ai-inference-platform python3 main.py
```

服务默认运行在：`http://localhost:8000`

## 3. 前端部署 (Vue 3 + Vite + Vue Router)

前端采用现代化的技术栈，使用 Vue Router 进行路由管理，提供流畅的单页应用体验。

### 3.1 安装依赖

进入 `frontend` 目录并安装 Node 模块：

```bash
cd frontend
npm install
```

**主要依赖包括：**
* vue@^3.5.24 - Vue 3 框架
* vue-router@^4.6.4 - 路由管理（**新增**）
* @vueuse/core - Vue Composition API 工具库
* radix-vue / reka-ui - UI 组件库
* tailwindcss - CSS 框架
* lucide-vue-next - 图标库

### 3.2 更新依赖

如果项目依赖有更新，执行以下命令：

```bash
cd frontend
npm install
```

这会根据 `package.json` 和 `package-lock.json` 安装或更新所有依赖。

### 3.3 开发环境运行

**方式一：使用启动脚本（推荐）**

```bash
# 在项目根目录执行
./run-frontend.sh
```

**方式二：手动运行**

```bash
cd frontend
npm run dev
```

前端开发服务默认运行在：`http://localhost:5173`

### 3.4 路由说明

前端使用 Vue Router 进行路由管理，支持以下路由：

* `/` — 自动重定向到 `/chat`
* `/chat` — 聊天页面
* `/models` — 模型管理页面
* `/knowledge` — 知识库页面
* `/agents` — 智能体管理页面
* `/logs` — 系统日志页面
* `/settings` — 设置页面（含后端、目标检测、ASR 等子项）

**重要特性：**
* 刷新页面会保持在当前路由，不会跳转到首页
* 支持浏览器前进/后退功能
* 可以分享特定页面的链接

### 3.5 生产环境构建

如果您需要部署到生产环境，可以生成静态资源：

```bash
cd frontend
npm run build
```

构建产物将保存在 `frontend/dist` 目录下。

## 4. 项目结构说明

```text
local_ai_inference_platform/
├── backend/                    # Python FastAPI 后端
│   ├── api/                    # HTTP 接口（chat、agents、skills、knowledge、backup、asr、vlm 等）
│   ├── config/                 # 应用配置（settings）
│   ├── core/                   # 核心业务逻辑
│   │   ├── agent_runtime/      # Agent 运行时（loop、v2/plan_based、trace）
│   │   ├── agents/             # 模型代理与路由
│   │   ├── backup/             # 数据库备份
│   │   ├── data/               # ORM、向量检索、数据库连接
│   │   ├── knowledge/          # 知识库
│   │   ├── memory/             # 长期记忆
│   │   ├── models/             # 模型注册与 Scanner
│   │   ├── plan_contract/      # Plan Contract 校验
│   │   ├── plugins/            # 插件与内置工具/技能
│   │   ├── project_intelligence/ # 项目分析
│   │   ├── rag/                # RAG 追踪存储
│   │   ├── runtimes/           # 推理运行时（LLM/VLM/Embedding/ASR/Perception）
│   │   ├── skills/             # Skill 能力与发现
│   │   ├── system/             # 系统设置存储
│   │   └── tools/              # 工具抽象与 YOLO 等
│   ├── data/                   # 持久化数据（platform.db、knowledge_bases、agent_workspaces）
│   ├── log/                    # 结构化日志模块
│   ├── middleware/             # 请求中间件（如 user_context）
│   ├── main.py                 # 应用入口
│   └── requirements.txt       # Python 依赖
├── frontend/                   # Vue 3 前端
│   ├── src/
│   │   ├── components/         # Vue 组件
│   │   ├── composables/        # Composition API
│   │   ├── router/             # 路由配置
│   │   ├── services/           # API 服务
│   │   ├── views/              # 页面视图
│   │   └── main.ts             # 应用入口
│   ├── public/                 # 静态资源
│   └── package.json            # Node 依赖
├── docs/                       # 文档（含 API、部署、架构等）
├── AGENTS.md                   # 智能体与插件开发规范
├── run-backend.sh              # 后端启动脚本
└── run-frontend.sh             # 前端启动脚本
```

## 5. 快速启动

项目提供了便捷的启动脚本，可以快速启动前后端服务：

```bash
# 启动后端（需要先创建并激活 conda 环境）
./run-backend.sh

# 启动前端（会自动检查并安装依赖）
./run-frontend.sh

# 或者使用 run-all.sh（如果存在）
./run-all.sh
```

## 6. 常见问题 (FAQ)

### 6.1 端口冲突

* **后端端口 8000 被占用**：修改 `backend/main.py` 中的 `uvicorn.run()` 参数
* **前端端口 5173 被占用**：修改 `frontend/vite.config.ts` 中的 `server.port` 配置

### 6.2 依赖安装问题

**前端依赖更新后无法运行：**
```bash
cd frontend
# 删除 node_modules 和 lock 文件，重新安装
rm -rf node_modules package-lock.json
npm install
```

**后端依赖安装失败：**
```bash
# 确保 conda 环境已激活
conda activate ai-inference-platform
# 使用国内镜像源（可选）
pip install -r backend/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 6.3 路由相关问题

* **刷新页面跳转到首页**：已修复，现在刷新会保持在当前页面
* **浏览器前进/后退不工作**：确保使用 Vue Router 的导航方法，不要直接修改 URL

### 6.4 跨域问题 (CORS)

开发环境下前端会自动代理请求，如需修改请检查：
* 后端的 CORS 中间件配置（`backend/main.py`）
* 前端的 Vite 代理配置（`frontend/vite.config.ts`）

### 6.5 Conda 环境问题

如果遇到 `conda activate` 错误：
```bash
# 初始化 conda（首次使用）
conda init

# 或者使用 conda run 直接运行（无需激活）
conda run -n ai-inference-platform python3 backend/main.py
```

---
*文档最后更新日期：2026年2月*
