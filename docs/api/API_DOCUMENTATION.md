# OpenVitamin大模型与智能体应用平台 API 文档

## 目录

1. [概述](#1-概述)
2. [认证](#2-认证)
3. [核心端点](#3-核心端点)
   - [3.1 健康检查](#31-健康检查)
   - [3.2 根端点](#32-根端点)
4. [模型管理](#4-模型管理)
   - [4.1 列出模型](#41-列出模型)
   - [4.2 扫描模型](#42-扫描模型)
   - [4.3 加载模型](#43-加载模型)
   - [4.4 卸载模型](#44-卸载模型)
   - [4.5 模型安全检查](#45-模型安全检查)
   - [4.6 注册云模型](#46-注册云模型)
   - [4.7 更新模型](#47-更新模型)
   - [4.8 模型聊天参数](#48-模型聊天参数)
   - [4.9 模型清单](#49-模型清单)
   - [4.10 浏览模型目录](#410-浏览模型目录)
5. [聊天接口](#5-聊天接口)
   - [5.1 聊天完成](#51-聊天完成)
   - [5.2 视觉语言模型支持](#52-视觉语言模型支持)
   - [5.3 RAG配置](#53-rag配置)
6. [会话管理](#6-会话管理)
   - [6.1 列出会话](#61-列出会话)
   - [6.2 列出消息](#62-列出消息)
   - [6.3 重命名会话](#63-重命名会话)
   - [6.4 删除会话](#64-删除会话)
7. [系统管理](#7-系统管理)
   - [7.1 获取系统配置](#71-获取系统配置)
   - [7.2 更新系统配置](#72-更新系统配置)
   - [7.3 重载引擎](#73-重载引擎)
   - [7.4 浏览目录](#74-浏览目录)
   - [7.5 系统指标](#75-系统指标)
   - [7.6 流式日志](#76-流式日志)
8. [内存管理](#8-内存管理)
   - [8.1 列出记忆](#81-列出记忆)
   - [8.2 删除记忆](#82-删除记忆)
   - [8.3 清空记忆](#83-清空记忆)
9. [知识库](#9-知识库)
   - [9.1 列出知识库](#91-列出知识库)
   - [9.2 创建知识库](#92-创建知识库)
   - [9.3 获取知识库](#93-获取知识库)
   - [9.4 更新知识库](#94-更新知识库)
   - [9.5 删除知识库](#95-删除知识库)
   - [9.6 获取知识库统计](#96-获取知识库统计)
   - [9.7 列出文档](#97-列出文档)
   - [9.8 获取文档](#98-获取文档)
   - [9.9 上传文档](#99-上传文档)
   - [9.10 删除文档](#910-删除文档)
   - [9.11 重新索引文档](#911-重新索引文档)
   - [9.12 列出文档块](#912-列出文档块)
   - [9.13 搜索知识库](#913-搜索知识库)
   - [9.14 列出嵌入模型](#914-列出嵌入模型)
10. [RAG Trace](#10-rag-trace)
    - [10.1 通过消息 ID 获取 Trace](#101-通过消息-id-获取-trace)
    - [10.2 通过 Trace ID 获取 Trace](#102-通过-trace-id-获取-trace)
11. [智能体](#11-智能体)
    - [11.1 列出智能体](#111-列出智能体)
    - [11.2 创建智能体](#112-创建智能体)
    - [11.3 获取智能体](#113-获取智能体)
    - [11.4 更新智能体](#114-更新智能体)
    - [11.5 删除智能体](#115-删除智能体)
    - [11.6 执行智能体](#116-执行智能体)
    - [11.7 执行智能体（带文件上传）](#117-执行智能体带文件上传)
    - [11.8 Agent 会话](#118-agent-会话)
12. [工具](#12-工具)
    - [12.1 列出可用工具](#121-列出可用工具)
    - [12.2 获取工具详情](#122-获取工具详情)
    - [12.3 Web搜索诊断](#123-web搜索诊断)
    - [12.4 Web搜索探测](#124-web搜索探测)
    - [12.5 视觉工具（内置）](#125-视觉工具内置)
13. [技能](#13-技能)
    - [13.1 列出技能](#131-列出技能)
    - [13.2 创建技能](#132-创建技能)
    - [13.3 获取技能](#133-获取技能)
    - [13.4 更新技能](#134-更新技能)
    - [13.5 删除技能](#135-删除技能)
    - [13.6 执行技能](#136-执行技能)
14. [ASR（语音识别）](#14-asr语音识别)
    - [14.1 语音转录](#141-语音转录)
15. [数据库备份](#15-数据库备份)
    - [15.1 数据库状态](#151-数据库状态)
    - [15.2 备份配置](#152-备份配置)
    - [15.3 创建备份](#153-创建备份)
    - [15.4 恢复备份](#154-恢复备份)
    - [15.5 备份历史](#155-备份历史)
    - [15.6 删除备份](#156-删除备份)
16. [VLM（视觉语言模型）](#16-vlm视觉语言模型)
    - [16.1 VLM生成](#161-vlm生成)
17. [Image Generation（文生图）](#17-image-generation文生图)
    - [17.1 提交生成任务](#171-提交生成任务)
    - [17.2 查询任务详情](#172-查询任务详情)
    - [17.3 查询任务列表](#173-查询任务列表)
    - [17.4 取消任务](#174-取消任务)
    - [17.5 删除任务](#175-删除任务)
    - [17.6 下载原图与缩略图](#176-下载原图与缩略图)
    - [17.7 Warmup](#177-warmup)
18. [错误响应](#18-错误响应)
19. [SSE（服务器发送事件）支持](#19-sse服务器发送事件支持)
20. [速率限制](#20-速率限制)
21. [CORS策略](#21-cors策略)
22. [数据持久化](#22-数据持久化)
23. [日志记录](#23-日志记录)
24. [安全考虑](#24-安全考虑)
25. [版本历史](#25-版本历史)

---

## 1. 概述

本文档为 OpenVitamin大模型与智能体应用平台后端 API 的说明。平台通过**统一推理网关**管理 LLM、VLM、Embedding、ASR、**Perception（视觉感知）** 与 **Image Generation（文生图）** 等模型，并提供智能体、技能、知识库、Workflow、备份等能力。内置工具包含 **vision.detect_objects**（YOLO 目标检测）、**vision.segment_objects**（FastSAM 实例分割，彩色 mask+轮廓）；前端不直连模型与工具，所有调用经网关统一出口。

**基础 URL**：`http://localhost:8000`  
**API 版本**：v1

## 2. 认证

大多数端点使用基于头部的认证：
- `X-User-Id`: 用户标识符（如果未提供，默认为"default"）
- `X-Session-Id`: 会话标识符（如果未提供则自动生成）

## 3. 核心端点

### 3.1 健康检查
```
GET /api/health
```
返回平台的健康状态。

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

### 3.2 根端点
```
GET /
```
欢迎消息和平台信息。

**Response:**
```json
{
  "message": "Welcome to OpenVitamin大模型与智能体应用平台",
  "version": "1.0.0"
}
```

## 4. 模型管理

### 4.1 列出模型
```
GET /api/models
Query Parameters:
- model_type (optional): Filter by model type (llm, vlm, embedding, asr, perception, image_generation)
```
列出所有可用模型及其当前状态。`perception` 类型包含目标检测（YOLO）与实例分割（FastSAM）模型；`image_generation` 类型包含 `mlx` 与 `diffusers` 两类文生图模型。

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "local:qwen3-8b",
      "name": "Qwen 3.0 8B",
      "model_type": "llm",
      "backend": "local",
      "status": "active",
      "device": "GPU:0"
    }
  ]
}
```

### 4.2 扫描模型
```
POST /api/models/scan
```
手动扫描不同来源的可用模型（Ollama、LM Studio、本地）。

**Response:**
```json
{
  "success": true,
  "results": {
    "ollama": 2,
    "lmstudio": 1,
    "local": 3
  }
}
```

### 4.3 加载模型
```
POST /api/models/{model_id}/load
```
将特定模型加载到内存中。

**Response:**
```json
{
  "success": true,
  "status": "active",
  "device": "GPU:0"
}
```

### 4.4 卸载模型
```
POST /api/models/{model_id}/unload
```
从内存中卸载特定模型。

**Response:**
```json
{
  "success": true,
  "status": "detached"
}
```

### 4.5 模型安全检查
```
GET /api/models/{model_id}/safety_check
```
加载模型前检查显存安全性。

**Response:**
```json
{
  "is_safe": true,
  "estimated_vram_gb": 8.5,
  "available_vram_gb": 12.0,
  "message": "Safe to load",
  "warning": null
}
```

### 4.6 注册云模型
```
POST /api/models
Body:
{
  "id": "cloud:gpt-4",
  "name": "GPT-4",
  "provider": "openai",
  "provider_model_id": "gpt-4",
  "runtime": "openai",
  "base_url": "https://api.openai.com/v1",
  "api_key": "your-api-key",
  "description": "OpenAI GPT-4 model"
}
```
注册基于云的模型（OpenAI、DeepSeek等）。

**Response:**
```json
{
  "success": true,
  "id": "cloud:gpt-4"
}
```

### 4.7 更新模型
```
PATCH /api/models/{model_id}
Body:
{
  "name": "Updated Model Name",
  "description": "New description"
}
```
更新模型元数据。

### 4.8 模型聊天参数
```
GET /api/models/{model_id}/chat-params
```
获取特定模型的聊天参数。

```
POST /api/models/{model_id}/chat-params
Body: { /* parameter configuration */ }
```
保存模型的聊天参数。

### 4.9 模型清单
```
GET /api/models/{model_id}/manifest
```
获取模型配置清单。

```
PUT /api/models/{model_id}/manifest
Body: { /* manifest configuration */ }
```
更新模型清单配置。

### 4.10 浏览模型目录
```
GET /api/models/{model_id}/browse
Query Parameters:
- dir (optional): Subdirectory to browse
```
列出本地模型的目录内容。

## 5. 聊天接口

### 5.1 聊天完成
```
POST /v1/chat/completions
Headers:
- X-User-Id (optional)
- X-Session-Id (optional)

Body:
{
  "model": "local:qwen3-8b",
  "messages": [
    {
      "role": "user",
      "content": "Hello, how are you?"
    }
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": 1000
}
```

**响应（非流式）：**
```json
{
  "id": "chatcmpl-1234567890",
  "created": 1705123456,
  "model": "local:qwen3-8b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! I'm doing well, thank you for asking. How can I help you today?"
      },
      "finish_reason": "stop"
    }
  ]
}
```

**流式响应：**
使用服务器发送事件(SSE)格式：
```
data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1705123456,"model":"local:qwen3-8b","choices":[{"index":0,"delta":{"content":"Hello"}}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1705123456,"model":"local:qwen3-8b","choices":[{"index":0,"delta":{"content":"!"}}]}

data: [DONE]
```

### 5.2 视觉语言模型支持

VLM模型支持多模态消息：

```json
{
  "model": "local:llava-v1.5-7b",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "What's in this image?"
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD..."
          }
        }
      ]
    }
  ]
}
```

### 5.3 RAG配置

在聊天请求中包含RAG配置：

```json
{
  "model": "local:qwen3-8b",
  "messages": [...],
  "rag": {
    "knowledge_base_id": "kb_1234567890",
    "top_k": 5,
    "min_similarity": 0.7
  }
}
```

## 6. 会话管理
所有会话端点都以`/api/sessions`为前缀。

### 6.1 列出会话

```
GET /api/sessions
Query Parameters:
- limit (default: 50): Maximum number of sessions to return
Headers:
- X-User-Id (optional)
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "sess_1234567890abcdef",
      "title": "New Chat",
      "created_at": "2024-01-13T10:30:00Z",
      "updated_at": "2024-01-13T10:35:00Z",
      "last_model": "local:qwen3-8b"
    }
  ]
}
```

### 6.2 列出消息

```
GET /api/sessions/{session_id}/messages
Query Parameters:
- limit (default: 200): Maximum number of messages to return
Headers:
- X-User-Id (optional)
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "msg_1234567890abcdef",
      "role": "user",
      "content": "Hello!",
      "created_at": "2024-01-13T10:30:00Z",
      "meta": {
        "attachments": [
          {
            "type": "image",
            "url": "data:image/jpeg;base64,..."
          }
        ]
      }
    },
    {
      "id": "msg_0987654321fedcba",
      "role": "assistant",
      "content": "Hi there! How can I help you?",
      "created_at": "2024-01-13T10:30:01Z"
    }
  ]
}
```

### 6.3 重命名会话

```
PATCH /api/sessions/{session_id}
Body:
{
  "title": "New Session Title"
}
Headers:
- X-User-Id (optional)
```

**Response:**
```json
{
  "updated": true,
  "id": "sess_1234567890abcdef",
  "title": "New Session Title"
}
```

### 6.4 删除会话

```
DELETE /api/sessions/{session_id}
Headers:
- X-User-Id (optional)
```

**Response:**
```json
{
  "deleted": true,
  "id": "sess_1234567890abcdef"
}
```

## 7. 系统管理
所有系统端点都以`/api/system`为前缀。

### 7.1 获取系统配置

```
GET /api/system/config
```

**Response:**
```json
{
  "ollama_base_url": "http://localhost:11434",
  "app_name": "OpenVitamin大模型与智能体应用平台",
  "version": "1.0.0",
  "local_model_directory": "/path/to/models",
  "settings": {
    "dataDirectory": "/path/to/models"
  }
}
```

### 7.2 更新系统配置

```
POST /api/system/config
Body: { /* configuration settings */ }
```

**说明：**
- 当前接口已启用配置项白名单与字段级校验。
- 未知 key 或非法值会返回 `400`。
- Runtime 相关配置（如缓存上限、Idle TTL）保存后会在后续请求或下一次自动回收触发时生效，并非强制立即整理当前已加载实例。

### 7.3 重载引擎

```
POST /api/system/engine/reload
```
重载推理引擎。

### 7.4 浏览目录

```
GET /api/system/browse-directory
```
打开系统目录选择器（MacOS/Windows）。

### 7.5 系统指标

```
GET /api/system/metrics
```

**Response:**
```json
{
  "cpu_load": 25.5,
  "ram_used": 8.2,
  "ram_total": 16.0,
  "gpu_usage": 45,
  "vram_used": 6.1,
  "vram_total": 8.0,
  "uptime": "2h 15m 30s",
  "node_version": "v18.17.0",
  "cuda_version": "12.1",
  "active_workers": 8
}
```

### 7.6 流式日志

```
GET /api/system/logs/stream
```
使用服务器发送事件进行实时日志流传输。

## 8. 内存管理
所有内存端点都以`/api/memory`为前缀。

### 8.1 列出记忆

```
GET /api/memory
Query Parameters:
- limit (default: 50): Number of memories to return
- include_deprecated (default: false): Include deprecated memories
Headers:
- X-User-Id (optional)
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "memory_id": "mem_123",
      "user_id": "default",
      "content": "User prefers Python for scripting",
      "confidence": 0.8,
      "tags": ["preference", "programming"],
      "created_at": "2024-01-13T10:30:00Z",
      "updated_at": "2024-01-13T10:30:00Z"
    }
  ]
}
```

### 8.2 删除记忆

```
DELETE /api/memory/{memory_id}
Headers:
- X-User-Id (optional)
```

**Response:**
```json
{
  "deleted": true,
  "id": "mem_123"
}
```

### 8.3 清空记忆

```
POST /api/memory/clear
Headers:
- X-User-Id (optional)
```

**Response:**
```json
{
  "cleared": true,
  "deleted_count": 5
}
```

## 9. 知识库

知识库与文档相关端点：列表/CRUD 以 `/api/knowledge-bases` 为路径；嵌入模型列表为 `GET /api/models/embedding`。

### 9.1 列出知识库

```
GET /api/knowledge-bases
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "kb_1234567890",
      "name": "My Knowledge Base",
      "description": "Personal documents and notes",
      "embedding_model_id": "local:bge-small-en-v1.5",
      "created_at": "2024-01-13T10:30:00Z",
      "updated_at": "2024-01-13T10:30:00Z"
    }
  ]
}
```

### 9.2 创建知识库

```
POST /api/knowledge-bases
Body:
{
  "name": "My Knowledge Base",
  "description": "Personal documents and notes",
  "embedding_model_id": "local:bge-small-en-v1.5"
}
```

**Response:**
```json
{
  "id": "kb_1234567890",
  "name": "My Knowledge Base",
  "description": "Personal documents and notes",
  "embedding_model_id": "local:bge-small-en-v1.5"
}
```

### 9.3 获取知识库

```
GET /api/knowledge-bases/{kb_id}
```

**Response:**
```json
{
  "id": "kb_1234567890",
  "name": "My Knowledge Base",
  "description": "Personal documents and notes",
  "embedding_model_id": "local:bge-small-en-v1.5",
  "disk_size": {
    "total_bytes": 1048576,
    "total_mb": 1.0
  },
  "created_at": "2024-01-13T10:30:00Z",
  "updated_at": "2024-01-13T10:30:00Z"
}
```

### 9.4 更新知识库

```
PATCH /api/knowledge-bases/{kb_id}
Body:
{
  "name": "Updated Name",
  "description": "Updated description"
}
```

### 9.5 删除知识库

```
DELETE /api/knowledge-bases/{kb_id}
```

### 9.6 获取知识库统计

```
GET /api/knowledge-bases/{kb_id}/stats
```

**Response:**
```json
{
  "document_count": 10,
  "chunk_count": 150,
  "total_tokens": 50000
}
```

### 9.7 列出文档

```
GET /api/knowledge-bases/{kb_id}/documents
Query Parameters:
- limit (optional): Maximum number of documents
- offset (optional): Offset for pagination
```

### 9.8 获取文档

```
GET /api/knowledge-bases/{kb_id}/documents/{doc_id}
```

### 9.9 上传文档

```
POST /api/knowledge-bases/{kb_id}/documents
Form Data:
- file: Document file (PDF, TXT, MD, etc.)
- metadata: JSON string (optional)
```

**Response:**
```json
{
  "id": "doc_1234567890",
  "name": "document.pdf",
  "status": "indexing",
  "created_at": "2024-01-13T10:30:00Z"
}
```

### 9.10 删除文档

```
DELETE /api/knowledge-bases/{kb_id}/documents/{doc_id}
```

### 9.11 重新索引文档

```
POST /api/knowledge-bases/{kb_id}/documents/{doc_id}/reindex
```

### 9.12 列出文档块

```
GET /api/knowledge-bases/{kb_id}/chunks
Query Parameters:
- document_id (optional): Filter by document ID
- limit (optional): Maximum number of chunks
- offset (optional): Offset for pagination
```

### 9.13 搜索知识库

```
POST /api/knowledge-bases/{kb_id}/search
Body:
{
  "query": "information retrieval",
  "top_k": 5,
  "score_threshold": 0.7
}
```

**Response:**
```json
{
  "query": "information retrieval",
  "results": [
    {
      "chunk_id": "chunk_123",
      "document_id": "doc_456",
      "content": "Information retrieval is...",
      "score": 0.85,
      "metadata": {}
    }
  ]
}
```

### 9.14 列出嵌入模型

```
GET /api/models/embedding
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "local:bge-small-en-v1.5",
      "name": "BGE Small EN v1.5",
      "model_type": "embedding"
    }
  ]
}
```

## 10. RAG Trace

RAG Trace 用于追踪 RAG 检索过程，端点以 `/api/rag` 为前缀。

### 10.1 通过消息 ID 获取 Trace

```
GET /api/rag/trace/by-message/{message_id}
```
通过聊天消息 ID 查询关联的 RAG 检索 Trace。

**Response:**
```json
{
  "rag_used": true,
  "trace": {
    "trace_id": "trace_123",
    "session_id": "sess_456",
    "message_id": "msg_789",
    "rag_id": "kb_123",
    "rag_type": "naive",
    "query": "user query",
    "embedding_model": "local:bge-small-en-v1.5",
    "vector_store": "sqlite-vec",
    "top_k": 5,
    "chunks": [
      {
        "chunk_id": "chunk_1",
        "content": "retrieved content...",
        "score": 0.85
      }
    ],
    "injected_token_count": 150,
    "created_at": "2024-01-13T10:30:00Z",
    "finalized_at": "2024-01-13T10:30:05Z"
  }
}
```
若该消息未使用 RAG，返回 `{"rag_used": false, "trace": null}`。

### 10.2 通过 Trace ID 获取 Trace

```
GET /api/rag/trace/{trace_id}
```
通过 Trace ID 直接查询单条 RAG Trace（如执行页「查看 Trace」跳转后使用）。响应格式与 10.1 一致。

## 11. 智能体
所有智能体端点都以`/api/agents`为前缀。

### 11.1 列出智能体

```
GET /api/agents
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "agent_id": "agent_12345678",
      "name": "Research Assistant",
      "description": "Helps with research tasks",
      "model_id": "local:qwen3-8b",
      "system_prompt": "You are a helpful research assistant...",
      "enabled_skills": ["builtin_web.search", "builtin_file.read"],
      "tool_ids": ["web.search", "file.read"],
      "rag_ids": ["kb_123"],
      "max_steps": 5,
      "temperature": 0.7
    }
  ]
}
```

### 11.2 创建智能体

```
POST /api/agents
Body:
{
  "name": "Research Assistant",
  "description": "Helps with research tasks",
  "model_id": "local:qwen3-8b",
  "system_prompt": "You are a helpful research assistant...",
  "enabled_skills": ["builtin_web.search", "builtin_file.read"],
  "tool_ids": ["web.search", "file.read"],
  "rag_ids": ["kb_123"],
  "max_steps": 5,
  "temperature": 0.7,
  "slug": "research-assistant",
  "execution_mode": "plan_based",
  "model_params": {
    "intent_rules": [],
    "use_skill_discovery": true
  }
}
```

**说明：**
- `enabled_skills`: Skill ID 列表（内置使用 `builtin_` 前缀）
- `tool_ids`: 兼容字段，若 `enabled_skills` 为空则映射为 `builtin_<tool_id>`
- `rag_ids`: 关联知识库 ID 列表
- `execution_mode`: `"legacy"`（v1.5 循环）或 `"plan_based"`（v2 Plan-Based 执行）
- `model_params`: v2 扩展配置；`intent_rules` 意图规则列表；`use_skill_discovery` 是否启用运行时技能语义发现（仅 plan_based 生效）

**Response:**
```json
{
  "agent_id": "agent_12345678",
  "name": "Research Assistant",
  "description": "Helps with research tasks",
  "model_id": "local:qwen3-8b",
  "system_prompt": "You are a helpful research assistant...",
  "enabled_skills": ["builtin_web.search", "builtin_file.read"],
  "tool_ids": ["web.search", "file.read"],
  "rag_ids": ["kb_123"],
  "max_steps": 5,
  "temperature": 0.7
}
```

### 11.3 获取智能体

```
GET /api/agents/{agent_id}
```

### 11.4 更新智能体

```
PUT /api/agents/{agent_id}
Body:
{
  "name": "Updated Name",
  "description": "Updated description",
  "model_id": "local:qwen3-8b",
  "system_prompt": "Updated prompt...",
  "enabled_skills": ["builtin_web.search"],
  "tool_ids": ["web.search"],
  "rag_ids": [],
  "max_steps": 10,
  "temperature": 0.8,
  "execution_mode": "plan_based",
  "model_params": { "intent_rules": [], "use_skill_discovery": true }
}
```

### 11.5 删除智能体

```
DELETE /api/agents/{agent_id}
```

**Response:**
```json
{
  "status": "ok"
}
```

### 11.6 执行智能体

```
POST /api/agents/{agent_id}/run
Body:
{
  "messages": [
    {
      "role": "user",
      "content": "Research the latest developments in AI"
    }
  ],
  "session_id": "sess_123" (optional)
}
Headers:
- X-User-Id (optional)
```

**Response (流式):**
使用SSE格式返回执行步骤和最终结果。

### 11.7 执行智能体（带文件上传）

```
POST /api/agents/{agent_id}/run/with-files
Form Data:
- messages: JSON string
- files: File[] (optional)
- session_id: string (optional)
Headers:
- X-User-Id (optional)
```

上传的文件会保存到Agent工作目录，路径信息会传递给Agent。

### 11.8 Agent 会话

Agent 会话相关端点以 `/api/agent-sessions` 为前缀，用于管理智能体运行时的会话、工作目录文件与执行追踪。

- `GET /api/agent-sessions` — 列出当前用户的 Agent 会话
- `GET /api/agent-sessions/{session_id}` — 获取指定会话详情
- `GET /api/agent-sessions/{session_id}/files/{filename}` — 读取会话工作目录下的文件
- `PATCH /api/agent-sessions/{session_id}` — 更新会话（如标题等）
- `GET /api/agent-sessions/{session_id}/trace` — 获取会话执行追踪（StepLog 树等）
- `DELETE /api/agent-sessions/{session_id}/messages/{message_index}` — 删除指定消息
- `DELETE /api/agent-sessions/{session_id}` — 删除会话

**请求头**：建议携带 `X-User-Id`、`X-Session-Id` 以区分用户与会话。

## 12. 工具
所有工具端点都以`/api/tools`为前缀。

### 12.1 列出可用工具

```
GET /api/tools
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "name": "web.search",
      "description": "Search the web using DuckDuckGo",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "top_k": {"type": "integer"}
        }
      },
      "output_schema": {
        "type": "array"
      },
      "required_permissions": ["net.web"],
      "ui": null
    }
  ]
}
```

### 12.2 获取工具详情

```
GET /api/tools/{name}
```

**Response:**
```json
{
  "name": "web.search",
  "description": "Search the web using DuckDuckGo",
  "input_schema": {...},
  "output_schema": {...},
  "required_permissions": ["net.web"],
  "ui": null
}
```

### 12.3 Web搜索诊断

```
GET /api/tools/web-search/diagnostic
```
检查web搜索工具的导入状态。

**Response:**
```json
{
  "python": "/path/to/python",
  "duckduckgo_search": "ok"
}
```

### 12.4 Web搜索探测

```
GET /api/tools/web-search/probe
Query Parameters:
- query (default: "test"): Search query
```
直接测试web搜索工具是否工作。

**Response:**
```json
{
  "ok": true,
  "mock": false,
  "tool_net_web_enabled": true,
  "results_count": 3,
  "results": [...],
  "error": null,
  "diagnostic": {...}
}
```

### 12.5 视觉工具（内置）

平台内置两类视觉感知工具，通过 Skill 绑定后由智能体调用；也可通过 `GET /api/tools` 查看完整 schema，或通过 `POST /api/skills/{skill_id}/execute` 间接执行。

| 工具名 | Skill ID | 说明 |
|--------|----------|------|
| **vision.detect_objects** | `builtin_vision.detect_objects` | YOLO 目标检测。输入图片（base64 或工作区路径），输出检测框（label、confidence、bbox）及可选标注图。可选参数：`confidence_threshold`（默认 0.25）、`output_annotated_image`、`backend`（yolov8 / yolov11 / yolov26 / onnx）。 |
| **vision.segment_objects** | `builtin_vision.segment_objects` | FastSAM 实例分割。输入图片，输出实例区域（label、confidence、bbox、可选 mask base64）及可选彩色 mask+轮廓标注图。可选参数：`confidence_threshold`（默认 0.4）、`output_annotated_image`。 |

**通用入参**：
- `image`（必填）：base64 data URL（`data:image/xxx;base64,...`）或相对于 Agent 工作目录的文件路径。

**通用出参**：
- `objects`：数组，每项含 `label`、`confidence`、`bbox`（归一化 [x1,y1,x2,y2]）；segment_objects 还含可选 `mask`（base64 PNG）。
- `image_size`：`[width, height]`。
- `annotated_image`（可选）：标注图 base64 data URL（当 `output_annotated_image=true` 时返回）。

## 13. 技能
所有技能端点都以`/api/skills`为前缀。

### 13.1 列出技能

```
GET /api/skills
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "skill_id": "builtin_web.search",
      "name": "Web Search",
      "description": "Search the web",
      "category": "utilities",
      "type": "tool",
      "enabled": true
    }
  ]
}
```

### 13.2 创建技能

```
POST /api/skills
Body:
{
  "name": "Custom Skill",
  "description": "A custom skill",
  "category": "utilities",
  "type": "prompt",
  "input_schema": {...},
  "definition": {...},
  "enabled": true
}
```

**技能类型 (type):**
- `prompt`: Prompt类型的技能
- `tool`: Tool类型的技能
- `composite`: 组合技能
- `workflow`: 工作流技能

### 13.3 获取技能

```
GET /api/skills/{skill_id}
```

### 13.4 更新技能

```
PUT /api/skills/{skill_id}
Body:
{
  "name": "Updated Name",
  "description": "Updated description",
  "category": "utilities",
  "type": "prompt",
  "input_schema": {...},
  "definition": {...},
  "enabled": true
}
```

**注意：** 内置技能（`builtin_*`）不能更新。

### 13.5 删除技能

```
DELETE /api/skills/{skill_id}
```

**注意：** 内置技能（`builtin_*`）不能删除。

**Response:**
```json
{
  "status": "ok"
}
```

### 13.6 执行技能

```
POST /api/skills/{skill_id}/execute
Body:
{
  "inputs": {
    "query": "test query"
  }
}
```

**Response:**
```json
{
  "type": "tool",
  "output": {...},
  "error": null,
  "prompt": null
}
```

## 14. ASR（语音识别）

所有 ASR 端点用于将音频转录为文本，供聊天等流程使用。

### 14.1 语音转录

```
POST /api/asr/transcribe
Content-Type: multipart/form-data

Form Fields:
- audio: 音频文件（必填，支持 wav/mp3/m4a）
- model_id (optional): ASR 模型 ID，默认 "local:faster-whisper-small"
```

**Response:**
```json
{
  "text": "转录后的完整文本",
  "language": "zh",
  "segments": []
}
```

**说明：** 需先扫描并注册 `model_type=asr` 的模型（如 faster-whisper），数据目录需包含 asr 模型路径。

## 15. 数据库备份

所有备份端点以 `/api/backup` 为前缀。

### 15.1 数据库状态

```
GET /api/backup/status
```

返回当前数据库类型、路径、大小、最近备份时间及备份开关状态。

### 15.2 备份配置

```
GET /api/backup/config
```
获取备份配置（是否启用、频率、保留数量、目录、模式等）。

```
POST /api/backup/config
Body: { "enabled", "frequency", "retention_count", "backup_directory", "auto_delete" }
```
更新备份配置并持久化到系统设置。

### 15.3 创建备份

```
POST /api/backup/create
```
手动创建一次备份。

### 15.4 恢复备份

```
POST /api/backup/restore/{backup_id}
```
从指定备份恢复数据库（需在无其他连接时执行）。

### 15.5 备份历史

```
GET /api/backup/history
```
列出备份记录，支持分页。

### 15.6 删除备份

```
DELETE /api/backup/{backup_id}
```
删除指定备份文件。

### 15.7 浏览备份目录

```
POST /api/backup/browse-directory
Body: { "path": "目录路径" }
```
浏览备份存储目录（用于配置备份路径等）。

## 16. VLM（视觉语言模型）
### 16.1 VLM生成

```
POST /v1/vlm/generate
Content-Type: multipart/form-data

Form Fields:
- request: JSON string of VLMGenerateRequest
- image: Image file (JPEG, PNG, WEBP, GIF)
```

**VLMGenerateRequest JSON:**
```json
{
  "model": "local:llava-v1.5-7b",
  "prompt": "Describe this image in detail",
  "system_prompt": "You are a visual language assistant...",
  "temperature": 0.7,
  "max_tokens": 500
}
```

**Response:**
```json
{
  "model": "local:llava-v1.5-7b",
  "text": "This image shows...",
  "usage": {
    "prompt_tokens": 50,
    "completion_tokens": 200,
    "total_tokens": 250
  }
}
```

**说明：**
- 使用 `multipart/form-data` 格式，而非JSON body
- `request` 字段是JSON字符串，包含模型和提示词参数
- `image` 字段是二进制图像文件
- 支持的图像格式：JPEG, PNG, WEBP, GIF

## 17. Image Generation（文生图）

### 17.1 提交生成任务

```http
POST /api/v1/images/generate
Query Parameters:
- wait (optional, default=true): `true` 同步等待结果；`false` 返回 job 并走异步任务模式
Content-Type: application/json
```

**Body:**
```json
{
  "model": "local:qwen-image-2512-4bit",
  "prompt": "一只戴墨镜的猫，电影感，写实风格",
  "negative_prompt": "blurry, low quality",
  "width": 512,
  "height": 512,
  "num_inference_steps": 4,
  "guidance_scale": 4.0,
  "seed": 42,
  "image_format": "PNG"
}
```

**同步 Response（wait=true）:**
```json
{
  "model": "local:qwen-image-2512-4bit",
  "image_base64": "<base64>",
  "mime_type": "image/png",
  "width": 512,
  "height": 512,
  "seed": 42,
  "latency_ms": 131071,
  "metadata": {
    "pipeline": "qwen-image"
  },
  "output_path": "/abs/path/backend/data/generated_images/<job_id>.png",
  "thumbnail_path": "/abs/path/backend/data/generated_images/<job_id>.thumb.png",
  "download_url": "/api/v1/images/jobs/<job_id>/file",
  "thumbnail_url": "/api/v1/images/jobs/<job_id>/thumbnail"
}
```

**异步 Response（wait=false）:**
```json
{
  "job_id": "ac64ec0b-ccf5-4e1b-9358-3319740a90d9",
  "status": "queued",
  "phase": "queued",
  "created_at": "2026-03-20T00:31:33Z",
  "started_at": null,
  "finished_at": null,
  "queue_position": 0,
  "current_step": null,
  "total_steps": null,
  "progress": null,
  "error": null,
  "result": null
}
```

**说明：**
- 当前支持 `runtime=mlx` 与 `runtime=diffusers` 两类文生图模型。
- 结果会落盘，历史页默认依赖文件与缩略图接口，不建议将大图 base64 作为前端主展示路径。

### 17.2 查询任务详情

```http
GET /api/v1/images/jobs/{job_id}
```

**Response:**
```json
{
  "job_id": "ac64ec0b-ccf5-4e1b-9358-3319740a90d9",
  "status": "succeeded",
  "phase": "completed",
  "created_at": "2026-03-20T00:31:33Z",
  "started_at": "2026-03-20T00:31:35Z",
  "finished_at": "2026-03-20T00:33:46Z",
  "queue_position": null,
  "current_step": 4,
  "total_steps": 4,
  "progress": 100.0,
  "error": null,
  "result": {
    "model": "local:qwen-image-2512-4bit",
    "mime_type": "image/png",
    "width": 512,
    "height": 512,
    "seed": 42,
    "latency_ms": 131071,
    "output_path": "/abs/path/backend/data/generated_images/<job_id>.png",
    "thumbnail_path": "/abs/path/backend/data/generated_images/<job_id>.thumb.png",
    "download_url": "/api/v1/images/jobs/<job_id>/file",
    "thumbnail_url": "/api/v1/images/jobs/<job_id>/thumbnail"
  }
}
```

### 17.3 查询任务列表

```http
GET /api/v1/images/jobs
Query Parameters:
- limit (optional)
- offset (optional)
- status (optional)
- model (optional)
- q (optional): 按 prompt 模糊搜索
- sort (optional): `created_at_desc` | `created_at_asc`
- include_result (optional, default=false)
```

**Response:**
```json
{
  "items": [
    {
      "job_id": "ac64ec0b-ccf5-4e1b-9358-3319740a90d9",
      "status": "succeeded",
      "phase": "completed",
      "created_at": "2026-03-20T00:31:33Z",
      "result": {
        "model": "local:qwen-image-2512-4bit",
        "thumbnail_url": "/api/v1/images/jobs/ac64ec0b-ccf5-4e1b-9358-3319740a90d9/thumbnail"
      }
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0,
  "has_next": false
}
```

### 17.4 取消任务

```http
POST /api/v1/images/jobs/{job_id}/cancel
```

**说明：**
- 对 `queued` 任务会直接取消。
- 对 `running` 任务为 best-effort cancel，通常在 step 边界生效。

### 17.5 删除任务

```http
DELETE /api/v1/images/jobs/{job_id}
```

**说明：**
- `queued/running` 任务不可删除。
- 删除成功时会同步删除历史记录、原图与缩略图文件。

### 17.6 下载原图与缩略图

```http
GET /api/v1/images/jobs/{job_id}/file
GET /api/v1/images/jobs/{job_id}/thumbnail
```

### 17.7 Warmup

```http
POST /api/v1/images/warmup
GET /api/v1/images/warmup/latest
```

**Warmup Body:**
```json
{
  "model": "local:qwen-image-2512-4bit",
  "prompt": "warmup image",
  "width": 256,
  "height": 256,
  "num_inference_steps": 1,
  "guidance_scale": 1.0,
  "seed": 42
}
```

**说明：**
- 用于首次加载前的轻量预热。
- 最近一次 warmup 状态可单独查询。

## 18. 错误响应
标准错误格式：
```json
{
  "detail": "Error message describing what went wrong"
}
```

常见HTTP状态码：
- `200`: Success
- `400`: Bad Request（请求参数错误）
- `404`: Not Found（资源不存在）
- `500`: Internal Server Error（服务器内部错误）
- `503`: Service Unavailable（服务不可用）

## 19. SSE（服务器发送事件）支持
以下端点支持SSE流式响应：
- `/v1/chat/completions` (当 `stream: true`)
- `/api/agents/{agent_id}/run` (智能体执行步骤)
- `/api/system/logs/stream` (系统日志)

SSE格式示例：
```
data: {"step": 1, "action": "thinking", "content": "..."}

data: {"step": 2, "action": "tool_call", "tool": "web.search", "args": {...}}

data: [DONE]
```

## 20. 速率限制
目前未实现速率限制，但可能在未来的版本中添加。

## 21. CORS策略
CORS配置为在开发模式下允许所有来源：
- `allow_origins`: ["*"]
- `allow_credentials`: true
- `allow_methods`: ["*"]
- `allow_headers`: ["*"]
- `expose_headers`: ["X-Session-Id"]

## 22. 数据持久化

平台使用 SQLite 进行数据存储：
- **数据库路径**：`backend/data/platform.db`（或配置指定路径）
- 自动建表与迁移
- ACID 事务

存储内容包括：会话与消息历史、智能体定义、技能定义、知识库与文档、长期记忆、RAG Trace、Agent 会话与执行追踪、Workflow 执行记录、Image Generation job / warmup 历史等。

## 23. 日志记录

API 请求与系统事件记录到：
- **日志目录**：`backend/log/`（或配置指定）
- **格式**：`[TIMESTAMP] LEVEL [COMPONENT] [FILE:LINE] - MESSAGE`，结构化日志为 JSON
- **保留**：30 天

## 24. 安全考虑
- API密钥在数据库中加密存储
- 模型文件在加载前进行验证
- 目录浏览限制在模型目录内
- 所有端点的输入验证
- 文件上传限制在Agent工作目录内
- 工具执行需要明确的权限声明

## 25. 版本历史

- **v1.0.0**：初始版本 — 聊天、模型管理、会话、知识库与 RAG、智能体 v1.5、技能 v1、VLM
- **后续更新**：
  - ASR 语音转录：`POST /api/asr/transcribe`
  - **Image Generation**：`/api/v1/images/*`（generate、jobs、cancel、delete、file、thumbnail、warmup），支持 `mlx` 与 `diffusers` 两类文生图 runtime
  - 数据库备份：`/api/backup/*`（status、config、create、restore、history、delete、browse-directory）
  - Agent 会话：`/api/agent-sessions`（列表、详情、文件、trace、更新、删除会话/消息）
  - 智能体 v2.4：`execution_mode`（legacy / plan_based）、`model_params`（intent_rules、use_skill_discovery）、Skill 语义发现、多 Agent 隔离、Plan Contract、RePlan、执行树与追踪
  - **视觉感知（Perception）**：模型类型 `perception`，支持 YOLO 目标检测与 FastSAM 实例分割；本地模型通过 `perception/` 目录下 `model.json` 注册（见 [LOCAL_MODEL_DEPLOYMENT.md](../local_model/LOCAL_MODEL_DEPLOYMENT.md)）
  - **vision.detect_objects**：内置工具，YOLO 多 backend（yolov8、yolov11、yolov26、onnx）；Skill ID：`builtin_vision.detect_objects`
  - **vision.segment_objects**：内置工具，FastSAM 实例分割，返回彩色 mask+轮廓标注图；Skill ID：`builtin_vision.segment_objects`
  - **Event API（v2.6）**：`/api/events/instance/{id}/*`（事件流、replay、validate、metrics），用于 Execution Kernel 可重建与调试
  - **Kernel 优化（v2.7）**：`/api/system/kernel/optimization`、`/api/system/kernel/optimization/impact-report` 等，优化层配置与效果报告
  - **Workflow Control Plane（v3.0）**：Workflow / Version / Execution 资源模型、运行页节点级状态与日志、Condition / Loop / Output 执行治理

---

本文档随 API 更新而更新，详细变更见 Git 提交历史。
