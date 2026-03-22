# 将本平台配置为 OpenClaw 推理后端

本平台（V2.8 Inference Gateway）对外提供 **OpenAI 兼容** 的 Chat Completions API，可作为 [OpenClaw](https://www.getopenclaw.ai/) 的推理后端使用。本文说明如何在 OpenClaw 中配置并指向本平台。

---

## 1. 前置条件

- **本平台** 已启动，例如：`http://localhost:8000`（或你实际部署的地址）。
- **OpenClaw** 已安装，配置文件位于 `~/.openclaw/openclaw.json`（或项目内 `openclaw.config.json`）。
- 本平台至少有一个可用的 **LLM 模型**（在 `GET /api/models` 中可见）。

---

## 2. 获取本平台的模型 ID

在本平台后端运行的前提下，查询可用模型：

```bash
curl -s http://localhost:8000/api/models | jq '.data[].id'
```

或只查 LLM：`curl -s "http://localhost:8000/api/models?model_type=llm" | jq '.data[].id'`。

记下你要给 OpenClaw 使用的 `model_id`（必须 **与本平台返回的 id 完全一致**，大小写/斜杠/冒号都要一致）。

常见示例（以你平台实际返回为准）：
- `local:qwen3-8b`
- `local:llama-3.2-1b`

下文以 `YOUR_MODEL_ID` 表示。

---

## 3. 在 OpenClaw 中新增自定义 Provider

在 `~/.openclaw/openclaw.json` 的 `models.providers` 中增加一个自定义 provider，指向本平台。

### 3.1 最小配置示例

```json5
{
  "models": {
    "mode": "merge",
    "providers": {
      "local-ai": {
        "baseUrl": "http://localhost:8000/v1",
        "api": "openai-completions",
        "models": [
          {
            "id": "YOUR_MODEL_ID",
            "name": "Local LLM",
            "contextWindow": 8192,
            "maxTokens": 4096
          }
        ]
      }
    }
  }
}
```

说明：

- **provider 名称**：示例用 `local-ai`，可改为任意合法 id（如 `platform`、`gateway`）。
- **baseUrl**：本平台 Chat 接口为 `POST /v1/chat/completions`，因此 baseUrl 填 **`http://localhost:8000/v1`**（若本平台跑在其它主机/端口，替换为实际地址；不要填 `/api`）。
- **api**：OpenClaw 的 provider 类型字段。本文以 `openai-completions` 为例（OpenAI Chat Completions 兼容）。若 OpenClaw 版本提示该值不支持，请以 OpenClaw 官方文档/示例中的 `api` 枚举为准。
- **models**：至少列出一个模型；`id` 必须与本平台 `GET /api/models` 返回的 `id` **完全一致**；`contextWindow` / `maxTokens` 建议按模型能力填写，避免 OpenClaw 请求超过模型实际限制（最终仍以模型/运行时限制为准）。
- **输入能力声明要与后端一致**：如果该模型在本平台是文本模型（例如 `runtime=mlx` + `model_type=llm`），建议在 OpenClaw 的该模型配置里将 `input` 设为 `["text"]`（或不写），不要声明 `image`，避免上游发送图像导致请求失败。
- 本平台本地部署通常**不要求 API Key**，故未写 `apiKey`；若你启用了鉴权，可增加 `"apiKey": "${LOCAL_AI_API_KEY}"` 并在 `~/.openclaw/.env` 中配置。

### 3.2 多模型示例

若本平台有多个模型，在 `models` 数组中逐项列出即可：

```json5
"local-ai": {
  "baseUrl": "http://localhost:8000/v1",
  "api": "openai-completions",
  "models": [
    { "id": "local:qwen3-8b", "name": "Qwen3 8B (Local)", "contextWindow": 32768, "maxTokens": 4096 },
    { "id": "local:llama-3.2-1b", "name": "Llama 3.2 1B (Local)", "contextWindow": 128000, "maxTokens": 8192 }
  ]
}
```

---

## 4. 将 OpenClaw 默认模型设为本平台

在 `agents.defaults.model` 中把 primary 设为本平台上的模型，格式为 **`{provider_id}/{model_id}`**：

```json5
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "local-ai/YOUR_MODEL_ID"
      }
    }
  }
}
```

例如（推荐完整写法）：`"primary": "local-ai/local:qwen3-8b"`。若配置了多个模型，可再设置 `fallbacks`：

```json5
"model": {
  "primary": "local-ai/local:qwen3-8b",
  "fallbacks": ["local-ai/local:llama-3.2-1b"]
}
```

> 优先级提示（非常重要）：如果你在 `agents.list[]` 里给某个 agent（如 `main`）显式设置了 `model`，它会覆盖 `agents.defaults.model.primary`。  
> 也就是说，修改 defaults 后若不生效，请检查是否存在 `agents.list[].model` 的覆盖配置。

---

## 5. 完整示例（合并上述配置）

```json5
{
  "models": {
    "mode": "merge",
    "providers": {
      "local-ai": {
        "baseUrl": "http://localhost:8000/v1",
        "api": "openai-completions",
        "models": [
          {
            "id": "local:qwen3-8b",
            "name": "Qwen3 8B (Local)",
            "contextWindow": 32768,
            "maxTokens": 4096
          }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "local-ai/local:qwen3-8b"
      }
    }
  }
}
```

保存后可用 `openclaw doctor` 做一次配置校验；再启动 Gateway（如 `openclaw gateway run`）或通过 Telegram/Discord 等渠道发消息，即会使用本平台做推理。

---

## 6. 会话行为（重要，避免“新对话被合并”）

本平台支持 OpenAI 兼容接口，但会话由后端管理。若不理解该行为，常见现象是：在 OpenClaw 里“新开对话”，后端仍复用到旧会话。

### 6.1 默认会话行为

- 若请求包含 `X-Session-Id`，后端优先使用该会话。
- 若未携带 `X-Session-Id`，后端会按配置尝试复用最近活跃会话（时间窗）：
  - `chat_session_reuse_window_minutes`（默认 `15` 分钟）。
- 若希望“本次一定新会话”，可在该请求携带任一 Header：
  - `X-Force-New-Session: 1`
  - `X-New-Chat: 1`

上述 Header 是通用机制，不绑定任何具体客户端产品名。

### 6.2 建议配置（作为 OpenClaw 后端）

- 如果希望 OpenClaw 每次“新建对话”都绝不复用旧会话：
  1. 客户端在“新建对话后的首条请求”带 `X-Force-New-Session: 1`；
  2. 或将 `chat_session_reuse_window_minutes=0`（不自动复用，但可能产生更多碎片会话）。

### 6.3 幂等与持久化策略（可选）

- `chat_idempotency_headers`：默认 `Idempotency-Key,X-Request-Id`，用于重试去重写入。
- `chat_persistence_mode`：
  - `full`：完整记录；
  - `minimal`：仅成功回合落库（推荐外部网关场景）；
  - `off`：仅推理不落库。

---

## 7. 可选：API Key 与鉴权

若本平台日后启用 API Key 或 Bearer 鉴权：

1. 在 `~/.openclaw/.env` 中配置变量，例如：`LOCAL_AI_API_KEY=your-secret`。
2. 在 provider 中增加：`"apiKey": "${LOCAL_AI_API_KEY}"`。

若本平台使用自定义 Header（例如 `X-API-Key`），可查阅 OpenClaw 文档中的 `models.providers.*.headers` 与 `authHeader` 进行配置。

---

## 8. 与本平台 API 的对应关系

| OpenClaw 行为           | 本平台接口 / 说明                          |
|-------------------------|--------------------------------------------|
| 调用 primary/fallback 模型 | `POST /v1/chat/completions`，`model` 为上述 `model_id` |
| 流式输出                | 本平台支持 `stream: true`，OpenClaw 会按 SSE 消费 |
| 模型列表                | 由你在 `models.providers["local-ai"].models` 中维护，或从 `GET /api/models` 抄写 |

本平台不实现 OpenClaw 的「模型发现」接口，因此需要在 OpenClaw 配置里**显式列出**要使用的模型（如上 `models` 数组）。

---

## 9. 跨域（CORS）与局域网部署

当 OpenClaw 部署在局域网内**另一台机器**上、请求本平台 API 时，涉及两点：**是否受 CORS 限制**、**本平台是否可被外机访问**。

### 9.1 谁在调用：决定有没有 CORS

- **OpenClaw Gateway（后端进程）** 在机器 B 上向本平台（机器 A）发 **HTTP 请求**：这是**服务端对服务端**的调用，不经过浏览器，**不会触发 CORS**。只要网络通、baseUrl 配对即可。
- **只有**当「浏览器里的页面」（例如某个 Web 前端的 JS）**直接**请求本平台 API 时，浏览器才会做同源检查，此时才需要本平台的 CORS 配置允许该页面的 origin。

因此：**OpenClaw 跑在另一台机器上、由 Gateway 调本平台** → 无跨域问题，只需保证网络可达和 baseUrl 正确。

额外注意（VLM 场景）：

- 本平台当前 Chat 网关默认拒绝 `http://` / `https://` 的 `image_url`，要求使用 `data:image/...`（base64 data URL）输入图像。
- 如果 OpenClaw 某些通道/插件把图片以远程 URL 透传给后端，可能报 400（而不是 CORS 问题）。
- 这类场景建议先走纯文本模型，或在客户端侧将图片转换为 data URL 再转发。

### 9.2 本平台当前 CORS 配置

本平台当前 `main.py` 配置为：

- `allow_origins=["*"]`
- `allow_credentials=True`
- `allow_methods=["*"]`
- `allow_headers=["*"]`

说明：

- 对“OpenClaw Gateway（服务端） -> 本平台（服务端）”调用，CORS 不生效。
- 对“浏览器直连本平台”调用，才受 CORS 影响。
- 若你需要浏览器携带凭证（cookies/authorization）访问，建议将 `allow_origins` 改为**显式白名单**，不要继续使用 `"*"`。

### 9.3 局域网访问：本平台需监听所有网卡

若 OpenClaw 在**其他机器**上访问本平台，本平台必须监听 `0.0.0.0`，而不能只监听 `127.0.0.1`：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

否则外机无法连上。

### 9.4 OpenClaw 的 baseUrl 必须用本平台在局域网中的地址

在 OpenClaw 所在机器上，`baseUrl` 要填**本平台所在机器**的 LAN 地址，例如：

- 本平台在 `192.168.1.100`：`"baseUrl": "http://192.168.1.100:8000/v1"`
- 或本机有主机名：`"baseUrl": "http://ai-server.local:8000/v1"`

不要填 `http://localhost:8000/v1`（那只会指向 OpenClaw 本机）。

### 9.5 防火墙与安全

- 本平台所在机器的**防火墙 / 安全组**需放行入站 **8000**（或你实际端口）。
- 仅内网使用时，可继续不配 API Key；若本平台会暴露到公网，建议启用鉴权并限制 `allow_origins`。

---

## 10. 故障排查

- **连接失败**：确认本平台已启动且 `baseUrl` 的 host/port 正确；若 OpenClaw 在 Docker 内而本平台在宿主机，使用 `host.docker.internal` 或宿主机 IP，勿用 `localhost`。**跨机访问**时 baseUrl 必须用本平台的 LAN IP 或主机名，且本平台需 `--host 0.0.0.0`，防火墙放行端口。
- **跨机仍连不上**：在本平台机器上确认 `curl -s http://127.0.0.1:8000/api/models` 有响应；在 OpenClaw 机器上执行 `curl -s http://<本平台IP>:8000/api/models` 能通即可排除网络/防火墙问题。
- **模型不存在 / 400**：确认 `models[].id` 与本平台 `GET /api/models` 返回的 `id` 完全一致（区分大小写、斜杠等）。
- **明明新开对话却被合并**：检查是否发送了 `X-Force-New-Session: 1`（或 `X-New-Chat: 1`）；若客户端无法加 Header，可将 `chat_session_reuse_window_minutes=0`。
- **浏览器里请求被 CORS 拦**：仅当浏览器中的页面直连本平台 API 时才会出现；当前本平台 `allow_origins=["*"]`，一般可通。若仍报 CORS，检查本平台返回的 `Access-Control-Allow-Origin` 与请求的 Origin。
- **OpenClaw 报错**：运行 `openclaw doctor` 检查配置；查看 OpenClaw 日志中请求的 URL 与 body，确认与本平台 `POST /v1/chat/completions` 的请求格式一致。
