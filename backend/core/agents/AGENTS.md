# AGENTS.md — Model Agents Governance

> **模块级规范文档**
>
> 本文件定义 `core/agents/` 模块中 **Model Agent（模型代理）** 的设计原则、
> 接口契约与行为约束。
>
> 本模块是 **推理网关（Inference Gateway）中的模型适配层**，
> 负责对接不同模型后端，但不包含任何业务或智能逻辑。

---

## 1. 模块定位（Module Purpose）

`core/agents` 是 **模型适配层（Model Adapter Layer）**，其职责是：

- 对不同推理后端进行统一封装  
  （API / Ollama / vLLM / llama.cpp 等）
- 提供一致的：
  - 非流式推理接口
  - 流式（Streaming）推理接口
- 向上层推理网关暴露 **最小、稳定、可扩展** 的接口

> **重要澄清**
>
> 本模块中的 *Model Agent*：
>
> - ✅ 是 Adapter / Driver
> - ❌ 不是 Autonomous Agent
> - ❌ 不是 Planner / Reasoner

---

## 2. 设计边界（Strict Boundaries）

### 2.1 Model Agent 必须做的事 ✅

1. 接收统一的 `ChatCompletionRequest`
2. 调用具体模型后端
3. 转换模型输出为：
   - 完整文本（non-stream）
   - Token / Chunk 流（streaming）
4. （可选）暴露模型能力元信息（`model_info`）

---

### 2.2 Model Agent 严禁做的事 ❌

- ❌ 修改或重写 Prompt
- ❌ 注入隐藏的 system prompt
- ❌ 决策或覆盖参数策略
- ❌ 实现插件、RAG、Tool Calling
- ❌ 处理 HTTP / SSE / Web 相关逻辑
- ❌ 感知 UI 或前端状态

> **任何“智能决策”行为，都不应存在于本模块中。**

---

## 3. Agent 接口规范（Interface Contract）

所有 Model Agent **必须实现** 统一抽象接口：

```python
class ModelAgent(ABC):

    async def chat(req: ChatCompletionRequest) -> str:
        """非流式：返回完整的 assistant 文本（纯文本，无格式）"""

    async def stream_chat(req: ChatCompletionRequest) -> AsyncIterator[str]:
        """流式：逐 token/chunk 输出字符串（无 SSE/JSON 包装）"""

    def model_info(self) -> dict:
        """返回模型能力描述（用于 Models API）"""
```

### 3.1 接口语义说明

`chat(req)`
* 返回 完整的 assistant 文本
* 不包含：
  * SSE
  * JSON chunk
  * role / message 封装

`stream_chat(req)`
* 只允许返回字符串
* 每次 yield 表示一个 token / chunk
* ❌ 不允许返回：  
  * JSON
  * SSE 格式
  * Message 对象

`model_info()`
* 返回模型元信息（dict）
* 用于：
  * Models 页面
  * Debug / Inspect
* ❌ 不参与推理流程

## 4. Streaming 行为规范（非常重要）
### 4.1 Streaming 的唯一输出单位

* Streaming 输出 必须是字符串
* 表示：
  * token
  * 子词
  * 文本片段

### 4.2 Streaming 生命周期
```
stream_chat():
    yield token
    yield token
    yield token
    return
```

说明：
* [DONE] 信号由 Gateway 层统一处理
* Model Agent 不感知：
  * HTTP 连接
  * SSE 协议
  * 客户端状态

## 5. 参数处理规范
Model Agent 只能透传参数，不得自行修改：

* temperature
* top_p
* max_tokens

如果某后端不支持参数：

* ✅ 可以忽略
* ✅ 可以降级
* ❌ 不得偷偷替换或补默认值

## 6. 后端差异处理原则
不同模型后端能力不一致时：
* 在 Agent 内部做 最小必要适配
* 不得向上暴露后端私有字段
* 不得污染统一接口

示例

| 后端        | Streaming 来源    |
| --------- | --------------- |
| Ollama    | message → token |
| OpenAI    | delta.content   |
| llama.cpp | stdout chunk    |


## 7. Router 与 Agent 的关系
* Model Agent 不负责路由
* Model Router 决定：
  * 使用哪个 Agent 
  * Agent 的实例生命周期

> Agent 是 被动执行者，不是调度者。

## 8. 错误处理原则
* Agent 内部异常：
  * 向上抛出标准 Exception

* ❌ 不得：
  * 捕获后打印并吞掉
  * 返回半截内容而不标记错误
  * 错误格式与响应方式由 Gateway 层统一处理。

## 9. 可扩展性约束
新增 Model Agent 时，必须：
* 继承 ModelAgent
* 遵循 streaming 语义
* 不引入副作用（线程 / IO 泄漏）
* 补充最小文档说明

## 10. 设计哲学（Design Philosophy）
Model Agent 是"翻译官"，不是"决策者"

它的职责是： 统一请求 → 后端协议 → 统一输出

而不是思考： "应该怎么回答用户？"

---

## 11. 现有实现清单

当前 `core/agents/` 中的所有实现：

| 类名 | 文件 | 路由前缀 | 用途 | 状态 |
|------|------|---------|------|------|
| MockModelAgent | mock_agent.py | "mock" | 开发调试、前后端并行 | ✅ 生产就绪 |
| OllamaAgent | ollama_agent.py | "ollama:" | 本地推理（Ollama） | ✅ 生产就绪 |
| OpenAIAgent | openai_agent.py | 其他 | 云端推理（OpenAI）| ✅ 生产就绪 |

---

## 12. 扩展新 Agent 的 3 步法则

1. **继承 ModelAgent**
   ```python
   class MyAgent(ModelAgent):
       async def chat(self, req) -> str: ...
       async def stream_chat(self, req) -> AsyncIterator[str]: ...
       def model_info(self) -> dict: ...
   ```

2. **在 router.py 中注册**
   ```python
   def get_agent(self, model_id: str) -> ModelAgent:
       if model_id.startswith("mybackend:"):
           return self.myagent
   ```

3. **完成！** 无需改动其他代码