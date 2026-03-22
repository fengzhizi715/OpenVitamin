# LLM 推理参数配置指南（平台一致版）

本文档只描述当前本平台可稳定生效的推理参数，避免“文档可配、实际不生效”。

---

## 1. 适用范围

- 主要接口：`POST /v1/chat/completions`
- 主要请求模型：`ChatCompletionRequest`
- 稳定参数：`temperature`、`top_p`、`max_tokens`、`stream`

> 说明：其他常见参数（如 `stop`、`top_k`、`min_p`、`seed`、`response_format`、`frequency_penalty`、`presence_penalty`、`repetition_penalty`）在当前 Chat 主路径不作为稳定承诺能力，见 §6。

---

## 2. 当前可生效参数

### 2.1 Temperature（温度）

- 范围：`0.0 ~ 2.0`
- 含义：控制随机性；越低越稳定，越高越发散。

建议：
- `0.0 ~ 0.2`：代码、结构化提取、事实问答
- `0.3 ~ 0.7`：通用助手
- `0.8 ~ 1.0`：创意写作（不建议长期 > 1.0）

### 2.2 Top P（核采样）

- 范围：`0.0 ~ 1.0`
- 含义：从累计概率达到 P 的候选集合中采样。

建议：
- `0.4 ~ 0.7`：偏稳
- `0.8 ~ 1.0`：偏灵活

### 2.3 Max Tokens（最大生成长度）

- 范围：`1 ~ 8192`（当前请求模型上限）
- 含义：输出 token 上限，不是目标长度。

建议：
- 简短问答：`128 ~ 512`
- 一般任务：`512 ~ 2048`
- 长回答/大纲：`2048 ~ 4096`
- 仅在确实需要时拉高到 `8192`

### 2.4 Stream（流式）

- 类型：`true/false`
- 含义：是否以 SSE 方式流式返回。

建议：
- 交互对话：`true`
- 批处理与离线任务：`false`

## 3. 运行时差异（重要）

### 3.1 LLM（llama.cpp / openai-compatible / mlx）

通常可稳定使用：
- `temperature`
- `top_p`
- `max_tokens`
- `stream`

### 3.2 Torch VLM（图文）

当前主路径稳定参数为：
- `temperature`
- `max_tokens`

不建议在 VLM 场景依赖：
- `top_p`
- `stop`
- `frequency_penalty`
- `presence_penalty`

### 3.3 MLX（当前实现）

- 当前 `MLXRuntime` 为文本 LLM 路径。
- 仅处理文本消息，不支持当前平台内的图像输入 VLM 流程。

---

## 4. 场景化推荐（仅用可生效参数）

### 4.1 代码生成

按任务复杂度分层建议 `max_tokens`：

- 小片段 / 单函数：`1200 ~ 2500`
- 单文件较复杂实现：`3000 ~ 5000`
- 多文件思路展开 / 大模块草稿：`5000 ~ 8192`（上限）

如果经常出现“代码被截断”，优先把 `max_tokens` 提到 `4096` 或 `6000`，并配合 `stream=true`。

```json
{
  "temperature": 0.1,
  "top_p": 0.5,
  "max_tokens": 4000,
  "stream": true
}
```

### 4.2 技术问答 / RAG 问答

```json
{
  "temperature": 0.2,
  "top_p": 0.7,
  "max_tokens": 1200,
  "stream": true
}
```

### 4.3 通用助手

```json
{
  "temperature": 0.6,
  "top_p": 0.9,
  "max_tokens": 1000,
  "stream": true
}
```

### 4.4 创意写作

```json
{
  "temperature": 0.9,
  "top_p": 0.95,
  "max_tokens": 3000,
  "stream": true
}
```

### 4.5 结构化抽取

```json
{
  "temperature": 0.0,
  "top_p": 0.5,
  "max_tokens": 1000,
  "stream": false
}
```

---

## 5. 调优建议

### 5.1 输出太短

- 增加 `max_tokens`
- 检查 `stop` 是否过早命中

### 5.2 输出太发散

- 降低 `temperature`（每次 0.1）
- 降低 `top_p`（每次 0.1）

### 5.3 输出重复

- 先尝试小幅提高 `temperature`
- 同时降低 `top_p`（避免过于单一候选）
- 检查提示词是否要求模型机械重复格式

### 5.4 延迟过高

- 降低 `max_tokens`
- 使用 `stream=true`
- 控制上下文长度（历史消息、RAG 注入内容）

---

## 6. 当前不建议作为“平台参数”使用的字段

以下字段在业界常见，但当前平台 `/v1/chat/completions` 主路径不作为稳定承诺能力：

- `stop`
- `top_k`
- `min_p`
- `seed`
- `response_format`
- `frequency_penalty`
- `presence_penalty`
- `repetition_penalty`

如果你在特定后端做了定制扩展，请以该后端实现为准，并在文档中单独注明“仅对某 runtime 生效”。

补充说明：
- Inference Gateway 内部链路已经支持 `stop` 字段。
- 但当前对外 `/v1/chat/completions` 主请求模型 `ChatCompletionRequest` 尚未正式暴露 `stop`，因此本文档不把它列为平台稳定参数。

---

## 7. API 调用示例

### Python（OpenAI Compatible）

```python
response = client.chat.completions.create(
    model="qwen3-8b",
    messages=[{"role": "user", "content": "写一个快速排序函数"}],
    temperature=0.1,
    top_p=0.5,
    max_tokens=4000,
    stream=False,
)
```

### cURL

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-8b",
    "messages": [{"role": "user", "content": "写一个快速排序函数"}],
    "temperature": 0.1,
    "top_p": 0.5,
    "max_tokens": 4000,
    "stream": false
  }'
```