/**
 * API 服务层
 * 封装所有后端 API 调用
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const STORAGE_USER_ID_KEY = 'ai_platform_user_id'
const STORAGE_SESSION_ID_KEY = 'ai_platform_session_id'
let forceNewSessionOnce = false

export function getUserId(): string {
  return localStorage.getItem(STORAGE_USER_ID_KEY) || 'default'
}

export function setUserId(userId: string): void {
  localStorage.setItem(STORAGE_USER_ID_KEY, userId || 'default')
}

export function getSessionId(): string | null {
  return localStorage.getItem(STORAGE_SESSION_ID_KEY)
}

export function setSessionId(sessionId: string | null): void {
  if (!sessionId) {
    localStorage.removeItem(STORAGE_SESSION_ID_KEY)
    return
  }
  localStorage.setItem(STORAGE_SESSION_ID_KEY, sessionId)
}

export function requestNewSessionOnNextChat(): void {
  forceNewSessionOnce = true
}

// Model Manifest Types
export interface ModelManifest {
  model_id: string
  name: string
  model_type: 'llm' | 'vlm' | 'embedding' | 'image_generation'
  runtime: string
  format: string
  path: string
  capabilities: string[]
  quantization: string
  description: string
  metadata: Record<string, any>
}

// Model Manifest APIs
export async function getModelManifest(modelId: string): Promise<ModelManifest | null> {
  try {
    const encodedId = encodeURIComponent(modelId)
    const response = await apiFetch(`${API_BASE_URL}/api/models/${encodedId}/manifest`)
    if (!response.ok) return null
    return await response.json()
  } catch (error) {
    console.error('Failed to fetch model manifest:', error)
    return null
  }
}

export async function updateModelManifest(modelId: string, manifest: ModelManifest): Promise<void> {
  const encodedId = encodeURIComponent(modelId)
  const response = await apiFetch(`${API_BASE_URL}/api/models/${encodedId}/manifest`, {
    method: 'PUT',
    body: JSON.stringify(manifest)
  })
  if (!response.ok) {
    throw new Error(`Failed to update model manifest: ${response.status}`)
  }
}

export interface BrowseResult {
  path: string
  dirs: string[]
  files: string[]
  parent: string | null
  model_dir: string
}

export async function browseModelDir(modelId: string, dir = ''): Promise<BrowseResult> {
  const encodedId = encodeURIComponent(modelId)
  const url = dir
    ? `${API_BASE_URL}/api/models/${encodedId}/browse?dir=${encodeURIComponent(dir)}`
    : `${API_BASE_URL}/api/models/${encodedId}/browse`
  const response = await apiFetch(url)
  if (!response.ok) {
    const err = (await response.json().catch(() => ({}))) as { error?: string }
    throw new Error(err.error ?? `Browse failed: ${response.status}`)
  }
  return response.json()
}

function captureSessionIdFromResponse(response: Response): void {
  const sid = response.headers.get('X-Session-Id')
  if (sid) setSessionId(sid)
}

async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {})
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  // 统一注入 user/session header
  headers.set('X-User-Id', getUserId())
  const sid = getSessionId()
  if (sid) headers.set('X-Session-Id', sid)

  const response = await fetch(input, { ...init, headers, signal: init.signal })
  captureSessionIdFromResponse(response)
  return response
}

export interface Message {
  role: 'system' | 'user' | 'assistant'
  content: string | Array<{
    type: 'text' | 'image_url'
    text?: string
    image_url?: {
      url: string
    }
  }>
}

export interface RAGConfig {
  knowledge_base_id: string
  top_k?: number
  score_threshold?: number
}

export interface ChatRequest {
  model: string
  messages: Message[]
  temperature?: number
  top_p?: number
  max_tokens?: number
  stream?: boolean
  system_prompt?: string
  max_history_messages?: number
  rag?: RAGConfig
  signal?: AbortSignal
}

export interface Choice {
  index: number
  message: Message
  finish_reason: 'stop' | 'length' | 'content_filter'
}

export interface Usage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface ChatResponse {
  id: string
  object: string
  created: number
  model: string
  choices: Choice[]
  usage: Usage
}

export interface DeltaContent {
  content?: string
}

export interface StreamChoice {
  index: number
  delta: DeltaContent
}

export interface ChatStreamResponse {
  id: string
  object: string
  created: number
  model: string
  choices: StreamChoice[]
}

// VLM Interfaces
export interface VLMMessage {
  role: 'system' | 'user' | 'assistant'
  content: string | Array<{
    type: 'text' | 'image_url'
    text?: string
    image_url?: {
      url: string
    }
  }>
}

export interface VLMGenerateRequest {
  model: string
  messages: VLMMessage[]
  temperature?: number
  top_p?: number
  max_tokens?: number
  stream?: boolean
  signal?: AbortSignal
}

export interface VLMGenerateResponse {
  id: string
  object: string
  created: number
  model: string
  choices: Choice[]
  usage: Usage
}

export interface VLMStreamResponse {
  id: string
  object: string
  created: number
  model: string
  choices: StreamChoice[]
}

export interface ModelInfo {
  id: string
  name: string
  display_name: string
  backend: string
  supports_stream: boolean
  supports_functions?: boolean
  description?: string
  device?: string
  base_url?: string
  status?: 'active' | 'detached'
  quantization?: string
  size?: string
  format?: string
  source?: string
  model_type?: 'llm' | 'embedding' | 'vlm' | 'image_generation' | string
}

export interface ModelsResponse {
  object: string
  data: ModelInfo[]
}

/**
 * 获取可用模型列表
 */
export async function listModels(): Promise<ModelsResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/models`, { method: 'GET' })

  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`)
  }

  return response.json()
}

/**
 * 手动扫描模型
 */
export async function scanModels(): Promise<{ success: boolean; results: Record<string, number> }> {
  const response = await apiFetch(`${API_BASE_URL}/api/models/scan`, { method: 'POST' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 手动注册模型（云端 API）
 */
export async function registerModel(data: {
  id: string
  name: string
  provider: string
  provider_model_id: string
  runtime: string
  base_url?: string
  api_key?: string
  description?: string
}): Promise<{ success: boolean; id: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/models`, {
    method: 'POST',
    body: JSON.stringify(data)
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}


/**
 * 检查模型加载安全性
 */
export async function checkModelSafety(model_id: string): Promise<{ 
  is_safe: boolean; 
  estimated_vram_gb: number; 
  available_vram_gb: number;
  message: string;
  warning: string | null;
}> {
  const response = await apiFetch(`${API_BASE_URL}/api/models/${model_id}/safety_check`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 获取模型的聊天参数
 */
export async function getModelChatParams(modelId: string): Promise<{ success: boolean; data: any }> {
  const response = await apiFetch(`${API_BASE_URL}/api/models/${modelId}/chat-params`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 保存模型的聊天参数
 */
export async function saveModelChatParams(modelId: string, params: any): Promise<{ success: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/api/models/${modelId}/chat-params`, { 
    method: 'POST',
    body: JSON.stringify(params)
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}


/**
 * 更新模型信息
 */
export async function updateModel(modelId: string, data: any): Promise<{ success: boolean; data: any }> {
  const response = await apiFetch(`${API_BASE_URL}/api/models/${modelId}`, { 
    method: 'PATCH',
    body: JSON.stringify(data)
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 非流式聊天完成
 */
export async function chatCompletion(req: ChatRequest): Promise<ChatResponse> {
  const { signal, ...body } = req
  const headers: Record<string, string> = {}
  if (forceNewSessionOnce) {
    headers['X-Force-New-Session'] = '1'
    forceNewSessionOnce = false
  }
  const response = await apiFetch(`${API_BASE_URL}/v1/chat/completions`, {
    method: 'POST',
    body: JSON.stringify({
      ...body,
      stream: false,
    }),
    headers,
    signal
  })

  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`)
  }

  return response.json()
}

// ----------------------------
// VLM API (multipart)
// ----------------------------

export interface VlmGenerateRequest {
  model: string
  prompt: string
  temperature?: number
  max_tokens?: number
}

export interface VlmGenerateResponse {
  model: string
  text: string
  usage?: Record<string, unknown> | null
}

// ----------------------------
// ASR API (语音识别)
// ----------------------------

export interface ASRTranscribeResponse {
  text: string
  language: string
  segments: Array<{ start: number; end: number; text: string }>
}

export async function asrTranscribe(
  audio: Blob | File,
  modelId: string = 'local:faster-whisper-small',
  options: { signal?: AbortSignal } = {}
): Promise<ASRTranscribeResponse> {
  const form = new FormData()
  const file = audio instanceof File ? audio : new File([audio], 'audio.webm', { type: audio.type })
  form.append('audio', file)
  form.append('model_id', modelId)

  const headers: Record<string, string> = {
    'X-User-Id': getUserId(),
  }
  const sid = getSessionId()
  if (sid) headers['X-Session-Id'] = sid

  const response = await fetch(`${API_BASE_URL}/api/asr/transcribe`, {
    method: 'POST',
    body: form,
    headers,
    signal: options.signal,
  })
  captureSessionIdFromResponse(response)

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(err.detail || `ASR error: ${response.statusText}`)
  }
  return response.json()
}

// ----------------------------
// VLM API (multipart)
// ----------------------------

export async function vlmGenerate(
  req: VlmGenerateRequest,
  image: File,
  options: { signal?: AbortSignal } = {}
): Promise<VlmGenerateResponse> {
  const form = new FormData()
  form.append('request', JSON.stringify(req))
  form.append('image', image)

  const headers: Record<string, string> = {
    'X-User-Id': getUserId(),
  }
  const sid = getSessionId()
  if (sid) headers['X-Session-Id'] = sid

  const response = await fetch(`${API_BASE_URL}/v1/vlm/generate`, {
    method: 'POST',
    body: form,
    headers,
    signal: options.signal,
  })
  captureSessionIdFromResponse(response)

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(err.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * 流式聊天完成（SSE）
 * @param req 请求参数
 * @param onChunk 每个 chunk 到达时的回调
 * @param onDone 流完成时的回调
 */
export async function streamChatCompletion(
  req: ChatRequest,
  onChunk: (chunk: ChatStreamResponse) => void,
  onDone?: () => void,
  onError?: (error: Error) => void
): Promise<void> {
  const { signal, ...body } = req
  try {
    const headers: Record<string, string> = {}
    if (forceNewSessionOnce) {
      headers['X-Force-New-Session'] = '1'
      forceNewSessionOnce = false
    }
    const response = await apiFetch(`${API_BASE_URL}/v1/chat/completions`, {
      method: 'POST',
      body: JSON.stringify({
        ...body,
        stream: true,
      }),
      headers,
      signal
    })

    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('Response body is not readable')
    }

    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        // 检查 signal 是否已被取消
        if (signal?.aborted) {
          reader.cancel() // 主动取消 reader
          throw new DOMException('Request aborted', 'AbortError')
        }
        
        const { done, value } = await reader.read()

        if (done) {
          // 彻底完成，处理最后的 buffer
          if (buffer.trim()) {
            const hasDone = parseSSEBuffer(buffer, onChunk, onDone)
            if (!hasDone) onDone?.()
          } else {
            onDone?.()
          }
          break
        }

        buffer += decoder.decode(value, { stream: true })
        
        // SSE 规范：消息以 \n\n 分隔
        let boundary = buffer.lastIndexOf('\n\n')
        if (boundary !== -1) {
          const completePart = buffer.substring(0, boundary)
          buffer = buffer.substring(boundary + 2)
          
          if (parseSSEBuffer(completePart, onChunk, onDone)) {
            return // 收到 [DONE]
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  } catch (error) {
    // 如果是 abort 错误，不要调用 onError（避免重复处理）
    if (error instanceof DOMException && error.name === 'AbortError') {
      return // 静默退出
    }
    onError?.(error instanceof Error ? error : new Error(String(error)))
  }
}

// ----------------------------
// Sessions API（历史列表/消息加载）
// ----------------------------

export interface Session {
  id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
  last_model?: string | null
  deleted_at?: string | null
}

export interface SessionMessage {
  id: string
  session_id: string
  role: 'system' | 'user' | 'assistant'
  content: string
  created_at: string
  model?: string | null
  meta?: Record<string, unknown> | null
}

// ----------------------------
// RAG Trace API
// ----------------------------

export interface RAGTraceChunk {
  doc_id?: string | null
  doc_name?: string | null
  chunk_id?: string | null
  score: number
  content: string
  content_tokens?: number | null
  rank: number
}

export interface RAGTrace {
  id: string
  session_id: string
  message_id: string
  rag_id: string
  rag_type: string
  query: string
  embedding_model: string
  vector_store: string
  top_k: number
  retrieved_count: number
  score_threshold?: number | null
  injected_token_count?: number | null
  finalized: boolean
  created_at: string
  chunks: RAGTraceChunk[]
}

export interface RAGTraceResponse {
  rag_used: boolean
  trace?: RAGTrace | null
}

export async function getRagTraceByMessage(messageId: string): Promise<RAGTraceResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/rag/trace/by-message/${encodeURIComponent(messageId)}`, {
    method: 'GET',
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function getRagTraceById(traceId: string): Promise<RAGTraceResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/rag/trace/${encodeURIComponent(traceId)}`, {
    method: 'GET',
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function listSessions(limit: number = 50): Promise<{ object: string; data: Session[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/sessions?limit=${limit}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function listSessionMessages(
  sessionId: string,
  limit: number = 200
): Promise<{ object: string; data: SessionMessage[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/sessions/${sessionId}/messages?limit=${limit}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function renameSession(sessionId: string, title: string): Promise<{ updated: boolean; id: string; title: string }> {
  const params = new URLSearchParams({ title })
  const response = await apiFetch(`${API_BASE_URL}/api/sessions/${sessionId}?${params.toString()}`, { method: 'PATCH' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function deleteSession(sessionId: string): Promise<{ deleted: boolean; id: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/sessions/${sessionId}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

// ----------------------------
// System & Logs API
// ----------------------------

export interface SystemMetrics {
  cpu_load: number
  ram_used: number
  ram_total: number
  gpu_usage: number
  vram_used: number
  vram_total: number
  /** 推理速度（tokens/s），后端可选返回；无则前端显示占位 */
  inference_speed?: number | null
  uptime: string
  node_version: string
  cuda_version: string
  active_workers: number
}

export interface LogEntry {
  timestamp: string
  level: 'INFO' | 'DEBUG' | 'WARN' | 'ERRR'
  tag: string
  message: string
}

export interface SystemConfig {
  ollama_base_url: string
  app_name: string
  version: string
  local_model_directory: string
  settings?: Record<string, any>
}

export async function getSystemMetrics(): Promise<SystemMetrics> {
  const response = await apiFetch(`${API_BASE_URL}/api/system/metrics`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

// ----------------------------
// Workflows API
// ----------------------------

export interface WorkflowNodePayload {
  id: string
  type: string
  name?: string | null
  description?: string | null
  config: Record<string, any>
  position?: { x: number; y: number } | null
}

export interface WorkflowEdgePayload {
  from_node: string
  to_node: string
  condition?: string | null
  label?: string | null
  source_handle?: string | null
  target_handle?: string | null
}

export interface WorkflowDagPayload {
  nodes: WorkflowNodePayload[]
  edges: WorkflowEdgePayload[]
  entry_node?: string | null
  global_config?: Record<string, any>
}

export interface WorkflowRecord {
  id: string
  namespace: string
  name: string
  description?: string | null
  lifecycle_state: string
  latest_version_id?: string | null
  published_version_id?: string | null
  owner_id: string
  tags: string[]
  created_at: string
  updated_at: string
}

export interface WorkflowVersionRecord {
  version_id: string
  workflow_id: string
  version_number: string
  state: string
  description?: string | null
  created_by?: string | null
  published_by?: string | null
  created_at: string
  published_at?: string | null
  dag?: WorkflowDagPayload
  checksum?: string
}

export interface WorkflowExecutionRecord {
  execution_id: string
  workflow_id: string
  version_id: string
  state: string
  graph_instance_id?: string | null
  input_data: Record<string, any>
  output_data?: Record<string, any> | null
  global_context?: Record<string, any>
  trigger_type?: string
  triggered_by?: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  duration_ms?: number | null
  queue_position?: number | null
  queued_at?: string | null
  wait_duration_ms?: number | null
  error_message?: string | null
  error_details?: Record<string, any> | null
  node_states?: Array<{
    node_id: string
    state: string
    input_data: Record<string, any>
    output_data: Record<string, any>
    error_message?: string | null
    error_details?: Record<string, any> | null
    started_at?: string | null
    finished_at?: string | null
    retry_count?: number
  }>
  /** 与 node_states 同源，用于 Timeline 单一数据源，减少多来源歧义 */
  node_timeline?: Array<{
    node_id: string
    state: string
    started_at?: string | null
    finished_at?: string | null
    duration_ms?: number | null
    retry_count?: number
    error_message?: string | null
  }>
}

export interface WorkflowExecutionStatusRecord {
  execution_id: string
  workflow_id: string
  version_id: string
  state: string
  started_at?: string | null
  finished_at?: string | null
  duration_ms?: number | null
  queue_position?: number | null
  wait_duration_ms?: number | null
  node_timeline?: Array<{
    node_id: string
    state: string
    started_at?: string | null
    finished_at?: string | null
    duration_ms?: number | null
    retry_count?: number
    error_message?: string | null
  }>
}

export async function listWorkflows(params: {
  namespace?: string
  lifecycle_state?: string
  limit?: number
  offset?: number
} = {}): Promise<{ items: WorkflowRecord[]; total: number; limit: number; offset: number }> {
  const usp = new URLSearchParams()
  if (params.namespace) usp.set('namespace', params.namespace)
  if (params.lifecycle_state) usp.set('lifecycle_state', params.lifecycle_state)
  if (typeof params.limit === 'number') usp.set('limit', String(params.limit))
  if (typeof params.offset === 'number') usp.set('offset', String(params.offset))
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows${usp.toString() ? `?${usp.toString()}` : ''}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function createWorkflow(data: {
  namespace?: string
  name: string
  description?: string
  tags?: string[]
  metadata?: Record<string, any>
}): Promise<WorkflowRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function getWorkflow(workflowId: string): Promise<WorkflowRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function updateWorkflow(workflowId: string, data: {
  name?: string
  description?: string
  tags?: string[]
  metadata?: Record<string, any>
  lifecycle_state?: string
}): Promise<WorkflowRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function createWorkflowVersion(
  workflowId: string,
  data: { dag: WorkflowDagPayload; version_number?: string; description?: string }
): Promise<WorkflowVersionRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/versions`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function listWorkflowVersions(
  workflowId: string,
  params: { state?: string; limit?: number; offset?: number } = {}
): Promise<{ items: WorkflowVersionRecord[]; total: number; limit: number; offset: number }> {
  const usp = new URLSearchParams()
  if (params.state) usp.set('state', params.state)
  if (typeof params.limit === 'number') usp.set('limit', String(params.limit))
  if (typeof params.offset === 'number') usp.set('offset', String(params.offset))
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/versions${usp.toString() ? `?${usp.toString()}` : ''}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function getWorkflowVersion(workflowId: string, versionId: string): Promise<WorkflowVersionRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/versions/${versionId}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function publishWorkflowVersion(workflowId: string, versionId: string): Promise<WorkflowVersionRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/versions/${versionId}/publish`, {
    method: 'POST',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function diffWorkflowVersions(
  workflowId: string,
  fromVersionId: string,
  toVersionId: string
): Promise<{
  workflow_id: string
  from_version_id: string
  to_version_id: string
  summary: {
    node_added: number
    node_removed: number
    node_changed: number
    edge_added: number
    edge_removed: number
  }
  nodes: { added: string[]; removed: string[]; changed: string[] }
  edges: { added: string[]; removed: string[] }
}> {
  const usp = new URLSearchParams()
  usp.set('from_version_id', fromVersionId)
  usp.set('to_version_id', toVersionId)
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/versions/compare?${usp.toString()}`, {
    method: 'GET',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function rollbackWorkflowVersion(
  workflowId: string,
  versionId: string,
  data: { publish?: boolean; description?: string } = {}
): Promise<WorkflowVersionRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/versions/${versionId}/rollback`, {
    method: 'POST',
    body: JSON.stringify({
      publish: data.publish ?? true,
      description: data.description ?? '',
    }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function runWorkflow(
  workflowId: string,
  data: { version_id?: string; input_data?: Record<string, any>; global_context?: Record<string, any>; trigger_type?: string },
  wait = false,
  idempotencyKey?: string
): Promise<WorkflowExecutionRecord> {
  const key =
    (idempotencyKey && idempotencyKey.trim()) ||
    (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `wf-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`)
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/executions?wait=${wait ? 'true' : 'false'}`, {
    method: 'POST',
    headers: {
      'Idempotency-Key': key,
      'X-Request-Id': key,
    },
    body: JSON.stringify({
      workflow_id: workflowId,
      version_id: data.version_id,
      input_data: data.input_data || {},
      global_context: data.global_context || {},
      trigger_type: data.trigger_type || 'manual',
    }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function listWorkflowExecutions(
  workflowId: string,
  params: { state?: string; limit?: number; offset?: number } = {}
): Promise<{ items: WorkflowExecutionRecord[]; total: number; limit: number; offset: number }> {
  const usp = new URLSearchParams()
  if (params.state) usp.set('state', params.state)
  if (typeof params.limit === 'number') usp.set('limit', String(params.limit))
  if (typeof params.offset === 'number') usp.set('offset', String(params.offset))
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/executions${usp.toString() ? `?${usp.toString()}` : ''}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function getWorkflowExecution(
  workflowId: string,
  executionId: string,
  opts: { reconcile?: boolean } = {}
): Promise<WorkflowExecutionRecord> {
  const usp = new URLSearchParams()
  if (opts.reconcile) usp.set('reconcile', 'true')
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/workflows/${workflowId}/executions/${executionId}${usp.toString() ? `?${usp.toString()}` : ''}`,
    { method: 'GET' }
  )
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function getWorkflowExecutionStatus(
  workflowId: string,
  executionId: string
): Promise<WorkflowExecutionStatusRecord> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/workflows/${workflowId}/executions/${executionId}/status`,
    { method: 'GET' }
  )
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export type WorkflowExecutionStatusStreamMessage =
  | { type: 'status'; payload: WorkflowExecutionStatusRecord }
  | { type: 'heartbeat'; at?: string }
  | { type: 'terminal'; state?: string }
  | { type: 'error'; message?: string }

export function streamWorkflowExecutionStatus(
  workflowId: string,
  executionId: string,
  handlers: {
    onStatus: (payload: WorkflowExecutionStatusRecord) => void
    onTerminal?: (state?: string) => void
    onError?: (error: Error) => void
  },
  options?: { intervalMs?: number }
): () => void {
  const intervalMs = Math.max(300, Math.min(5000, Math.floor(options?.intervalMs || 900)))
  const url = `${API_BASE_URL}/api/v1/workflows/${workflowId}/executions/${executionId}/stream?interval_ms=${intervalMs}`
  const eventSource = new EventSource(url)

  eventSource.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data) as WorkflowExecutionStatusStreamMessage
      if (!msg || typeof msg !== 'object') return
      if (msg.type === 'status' && msg.payload) {
        handlers.onStatus(msg.payload)
        return
      }
      if (msg.type === 'terminal') {
        handlers.onTerminal?.(msg.state)
        return
      }
      if (msg.type === 'error') {
        handlers.onError?.(new Error(msg.message || 'workflow status stream error'))
      }
    } catch (e) {
      handlers.onError?.(new Error(`workflow status stream parse error: ${String(e)}`))
    }
  }

  eventSource.onerror = () => {
    handlers.onError?.(new Error('workflow status stream connection error'))
    eventSource.close()
  }

  return () => {
    eventSource.close()
  }
}

export async function cancelWorkflowExecution(workflowId: string, executionId: string): Promise<WorkflowExecutionRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/executions/${executionId}/cancel`, {
    method: 'POST',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function deleteWorkflowExecution(workflowId: string, executionId: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/executions/${executionId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
}

/** 手动对账：将 kernel 终态写回 DB，用于异常场景恢复 */
export async function reconcileWorkflowExecution(
  workflowId: string,
  executionId: string
): Promise<WorkflowExecutionRecord> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/workflows/${workflowId}/executions/${executionId}/reconcile`,
    { method: 'POST' }
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/** Workflow 执行治理状态（队列/背压/并发） */
export interface WorkflowGovernanceStatus {
  quota?: Record<string, unknown>
  concurrency?: { active_slots?: number }
  queue?: {
    queued_executions?: number
    max_queue_size?: number
    backpressure_strategy?: 'wait' | 'reject'
  }
}

export async function getWorkflowGovernance(workflowId: string): Promise<WorkflowGovernanceStatus> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/governance`, { method: 'GET' })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function setWorkflowGovernance(
  workflowId: string,
  config: { max_queue_size?: number; backpressure_strategy?: 'wait' | 'reject' }
): Promise<WorkflowGovernanceStatus> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/workflows/${workflowId}/governance`, {
    method: 'PUT',
    body: JSON.stringify(config),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

// ----------------------------
// Agents API
// ----------------------------

export interface AgentDefinition {
  agent_id: string
  name: string
  description: string
  model_id: string
  system_prompt: string
  /** v1.5: Skill ids the agent can call (only these are visible to the agent) */
  enabled_skills?: string[]
  /** Legacy: tool names; backend derives from enabled_skills when all are builtin_ */
  tool_ids: string[]
  rag_ids: string[]
  max_steps: number
  temperature: number
  slug?: string | null
  execution_mode?: string
  use_execution_kernel?: boolean | null
  plan_contract_enabled?: boolean
  plan_contract_strict?: boolean
  plan_contract_sources?: string[]
  max_replan_count?: number
  on_failure_strategy?: string
  replan_prompt?: string
  model_params?: Record<string, any>
}

export interface CreateAgentRequest {
  name: string
  description?: string
  model_id: string
  system_prompt?: string
  /** v1.5: Skill ids; if empty, backend maps tool_ids to builtin_<id> */
  enabled_skills?: string[]
  tool_ids?: string[]
  rag_ids?: string[]
  max_steps?: number
  temperature?: number
  slug?: string | null
  /** V2: Execution mode - "legacy" or "plan_based" */
  execution_mode?: string
  /** V2.5: Agent-level Execution Kernel override. null/undefined = follow global */
  use_execution_kernel?: boolean | null
  /** V2.2: Max replan count */
  max_replan_count?: number
  /** V2.2: On failure strategy - stop/continue/replan */
  on_failure_strategy?: string
  /** V2.2: Custom replan prompt */
  replan_prompt?: string
  /** Agent response mode */
  response_mode?: 'default' | 'direct_tool_result'
  /** V2.3: Enable Plan Contract ingestion in RePlan */
  plan_contract_enabled?: boolean
  /** V2.3: Strict mode: invalid contract fails fast (no fallback) */
  plan_contract_strict?: boolean
  /** V2.3: Contract source keys in priority order */
  plan_contract_sources?: string[]
  /** Model parameters (e.g., intent_rules, skill_param_extractors, etc.) */
  model_params?: Record<string, any>
}

export interface RunAgentRequest {
  messages: Message[]
  session_id?: string
}

export interface AgentSession {
  session_id: string
  agent_id: string
  user_id: string
  trace_id: string
  messages: Message[]
  step: number
  status: 'running' | 'finished' | 'error' | 'idle'
  error_message?: string | null
  /** V2.6: Execution Kernel instance ID for event stream replay/debug */
  kernel_instance_id?: string | null
  created_at: string
  updated_at: string
}

export interface AgentTraceEvent {
  trace_id?: string | null
  event_id: string
  session_id: string
  step: number
  event_type: string
  agent_id?: string | null
  model_id?: string | null
  tool_id?: string | null
  input_data?: any
  output_data?: any
  duration_ms?: number | null
  created_at: string
}

export async function createAgent(data: CreateAgentRequest): Promise<AgentDefinition> {
  const response = await apiFetch(`${API_BASE_URL}/api/agents`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * 获取智能体详情
 */
export async function getAgent(agentId: string): Promise<AgentDefinition> {
  const response = await apiFetch(`${API_BASE_URL}/api/agents/${agentId}`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 更新智能体
 */
export async function updateAgent(agentId: string, data: CreateAgentRequest): Promise<AgentDefinition> {
  const response = await apiFetch(`${API_BASE_URL}/api/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * 删除智能体
 */
export async function deleteAgent(agentId: string): Promise<{ status: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/agents/${agentId}`, { method: 'DELETE' })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * 运行智能体
 */
export async function runAgent(agentId: string, data: RunAgentRequest): Promise<AgentSession> {
  const response = await apiFetch(`${API_BASE_URL}/api/agents/${agentId}/run`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 运行智能体（带上传文件）。文件会保存到会话工作目录，file.read 可读取。
 */
export async function runAgentWithFiles(
  agentId: string,
  messages: Message[],
  sessionId: string | undefined,
  files: File[]
): Promise<AgentSession> {
  const form = new FormData()
  form.append('messages', JSON.stringify(messages))
  form.append('session_id', sessionId ?? '')
  files.forEach((file) => form.append('files', file))
  const headers: Record<string, string> = {
    'X-User-Id': getUserId(),
  }
  const sid = getSessionId()
  if (sid) headers['X-Session-Id'] = sid
  const response = await fetch(`${API_BASE_URL}/api/agents/${agentId}/run/with-files`, {
    method: 'POST',
    body: form,
    headers,
    // 不设置 Content-Type，让浏览器自动设置 multipart/form-data; boundary=...
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(err.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * 获取智能体会话状态
 */
export async function getAgentSession(sessionId: string): Promise<AgentSession> {
  const response = await apiFetch(`${API_BASE_URL}/api/agent-sessions/${sessionId}`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 获取智能体运行追踪
 */
export async function getAgentTrace(sessionId: string): Promise<{ object: string; data: AgentTraceEvent[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/agent-sessions/${sessionId}/trace`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 删除智能体会话中的消息
 */
export async function deleteAgentSessionMessage(sessionId: string, messageIndex: number): Promise<AgentSession> {
  const response = await apiFetch(`${API_BASE_URL}/api/agent-sessions/${sessionId}/messages/${messageIndex}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 删除整个智能体会话
 */
export async function deleteAgentSession(sessionId: string): Promise<{ deleted: boolean; session_id: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/agent-sessions/${sessionId}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 更新智能体会话（用于删除消息等操作）
 */
export async function updateAgentSession(
  sessionId: string,
  data: { messages?: Message[]; status?: string }
): Promise<AgentSession> {
  const response = await apiFetch(`${API_BASE_URL}/api/agent-sessions/${sessionId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 列出智能体会话（可选按 agent_id 过滤）
 */
export async function listAgentSessions(
  params: { agent_id?: string; limit?: number } = {}
): Promise<{ object: string; data: AgentSession[] }> {
  const usp = new URLSearchParams()
  if (params.agent_id) usp.set('agent_id', params.agent_id)
  if (typeof params.limit === 'number') usp.set('limit', String(params.limit))
  const qs = usp.toString()
  const response = await apiFetch(`${API_BASE_URL}/api/agent-sessions${qs ? `?${qs}` : ''}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 列出所有智能体
 */
export async function listAgents(): Promise<{ object: string; data: AgentDefinition[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/agents`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export interface ToolInfo {
  name: string
  description: string
  input_schema: any
  output_schema: any
  required_permissions: string[]
  ui?: {
    display_name?: string
    icon?: string | null
    category?: string | null
    permissions_hint?: any
  } | null
}

export async function listTools(): Promise<{ object: string; data: ToolInfo[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/tools`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * Skills API (v1)
 */
export interface SkillRecord {
  id: string
  name: string
  description: string
  category: string
  type: 'prompt' | 'tool' | 'composite'
  definition: Record<string, unknown>
  input_schema: Record<string, unknown>
  enabled: boolean
  created_at: string | null
  updated_at: string | null
}

export interface CreateSkillRequest {
  name: string
  description?: string
  category?: string
  type?: 'prompt' | 'tool' | 'composite'
  input_schema?: Record<string, unknown>
  definition?: Record<string, unknown>
  enabled?: boolean
}

export async function listSkills(): Promise<{ object: string; data: SkillRecord[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/skills`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function getSkill(skillId: string): Promise<SkillRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/skills/${encodeURIComponent(skillId)}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export interface UpdateSkillRequest {
  name?: string
  description?: string
  category?: string
  type?: 'prompt' | 'tool' | 'composite'
  input_schema?: Record<string, unknown>
  definition?: Record<string, unknown>
  enabled?: boolean
}

export async function createSkill(body: CreateSkillRequest): Promise<SkillRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/skills`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function updateSkill(skillId: string, body: UpdateSkillRequest): Promise<SkillRecord> {
  const response = await apiFetch(`${API_BASE_URL}/api/skills/${encodeURIComponent(skillId)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function deleteSkill(skillId: string): Promise<{ status: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/skills/${encodeURIComponent(skillId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(err.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function executeSkill(skillId: string, inputs: Record<string, unknown>): Promise<{ type: string; output?: unknown; error?: string; prompt?: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/skills/${encodeURIComponent(skillId)}/execute`, {
    method: 'POST',
    body: JSON.stringify({ inputs }),
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function getSystemConfig(): Promise<SystemConfig> {
  const response = await apiFetch(`${API_BASE_URL}/api/system/config`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function updateSystemConfig(config: Record<string, any>): Promise<{ success: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/api/system/config`, { 
    method: 'POST',
    body: JSON.stringify(config)
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }))
    const detail = err?.detail
    const firstValidationError = Array.isArray(detail?.errors) ? detail.errors[0] : null
    const validationMessage =
      firstValidationError && typeof firstValidationError?.msg === 'string'
        ? `${firstValidationError.msg}${Array.isArray(firstValidationError?.loc) ? ` (${firstValidationError.loc.join('.')})` : ''}`
        : null
    const message =
      typeof detail === 'string'
        ? detail
        : validationMessage
          ? validationMessage
        : typeof detail?.message === 'string'
          ? detail.message
          : response.statusText
    throw new Error(message)
  }
  return response.json()
}

export async function reloadEngine(): Promise<{ success: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/api/system/engine/reload`, { method: 'POST' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function browseDirectory(): Promise<{ path: string | null }> {
  const response = await apiFetch(`${API_BASE_URL}/api/system/browse-directory`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * Backup API
 */

export interface DatabaseStatusResponse {
  type: string
  path: string
  size: string
  size_bytes: number
  last_backup_time: string | null
  backup_status: 'enabled' | 'disabled'
}

export interface BackupConfigResponse {
  enabled: boolean
  frequency: 'on_start' | 'daily' | 'weekly' | 'manual'
  retention_count: number
  backup_directory: string
  auto_delete: boolean
  mode: string
  database_type: string
}

export interface BackupConfigRequest {
  enabled: boolean
  frequency: 'on_start' | 'daily' | 'weekly' | 'custom'
  retention_count: number
  backup_directory: string
  auto_delete: boolean
}

export interface BackupRecord {
  id: string
  date: string
  size: string
  size_bytes: number
  type: 'auto' | 'manual'
  status: 'success' | 'failed' | 'in_progress'
  error_message?: string | null
}

export interface CreateBackupResponse {
  success: boolean
  backup_id: string
  backup_path: string
  size: number
  size_mb: number
  duration_seconds: number
}

export interface RestoreBackupResponse {
  success: boolean
  status: string
  duration_seconds: number
}

export async function getDatabaseStatus(): Promise<DatabaseStatusResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/backup/status`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function getBackupConfig(): Promise<BackupConfigResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/backup/config`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function updateBackupConfig(config: BackupConfigRequest): Promise<{ success: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/api/backup/config`, {
    method: 'POST',
    body: JSON.stringify(config)
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function createBackup(): Promise<CreateBackupResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/backup/create`, { method: 'POST' })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function restoreBackup(backupId: string): Promise<RestoreBackupResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/backup/restore/${backupId}`, { method: 'POST' })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function listBackups(): Promise<BackupRecord[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/backup/history`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function deleteBackup(backupId: string): Promise<{ success: boolean }> {
  const response = await apiFetch(`${API_BASE_URL}/api/backup/${backupId}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function browseBackupDirectory(): Promise<{ path: string | null }> {
  const response = await apiFetch(`${API_BASE_URL}/api/backup/browse-directory`, { method: 'POST' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * Model.json 备份 API（阶段 2）
 */
export interface ModelBackupStatus {
  last_daily_manifest_date: string | null
  daily_manifest_dates: string[]
}

export interface ModelBackupRecord {
  backup_id: string
  model_id: string
  file: string
  sha256?: string
  timestamp_utc: string
  action: string
  reason?: string
  source?: string
}

export async function getModelBackupStatus(): Promise<ModelBackupStatus> {
  const response = await apiFetch(`${API_BASE_URL}/api/model-backups/status`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function listModelBackups(modelId?: string, limit = 50): Promise<ModelBackupRecord[]> {
  const params = new URLSearchParams()
  if (modelId) params.set('model_id', modelId)
  params.set('limit', String(limit))
  const response = await apiFetch(`${API_BASE_URL}/api/model-backups?${params}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function createModelBackup(modelId: string, reason?: string): Promise<{
  success: boolean
  backup_id?: string
  storage_path?: string
  backup_root?: string
  error?: string
}> {
  const response = await apiFetch(`${API_BASE_URL}/api/model-backups/create`, {
    method: 'POST',
    body: JSON.stringify({ model_id: modelId, reason: reason ?? '' })
  })
  const data = await response.json()
  if (!response.ok) {
    const msg = Array.isArray(data.detail) ? data.detail.join(' ') : (data.detail ?? 'Create model backup failed')
    throw new Error(typeof msg === 'string' ? msg : 'Create model backup failed')
  }
  return data
}

export async function createAllModelBackups(reason?: string): Promise<{ success: boolean; total: number; success_count: number; created: unknown[]; failed: { model_id: string; error: string }[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/model-backups/create-all`, {
    method: 'POST',
    body: JSON.stringify({ reason: reason ?? 'Manual full snapshot' })
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function deleteModelBackup(backupId: string): Promise<{ success: boolean; backup_id?: string; deleted_file?: string; error?: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/model-backups/delete`, {
    method: 'POST',
    body: JSON.stringify({ backup_id: backupId })
  })
  const data = await response.json()
  if (!response.ok) throw new Error(Array.isArray(data.detail) ? data.detail.join(' ') : (data.detail ?? 'Delete failed'))
  return data
}

export async function restoreModelBackup(backupId: string, dryRun = false): Promise<{ success: boolean; model_id?: string; error?: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/model-backups/restore`, {
    method: 'POST',
    body: JSON.stringify({ backup_id: backupId, dry_run: dryRun })
  })
  const data = await response.json()
  if (!response.ok) throw new Error(Array.isArray(data.detail) ? data.detail.join(', ') : (data.detail ?? 'Restore failed'))
  return data
}

export async function restoreModelBackupBatch(
  targetTimestampUtc: string,
  modelIds?: string[],
  dryRun = false
): Promise<{ success: boolean; restored: { model_id: string; backup_id: string }[]; failed: { model_id: string; error: string }[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/model-backups/restore-batch`, {
    method: 'POST',
    body: JSON.stringify({ target_timestamp_utc: targetTimestampUtc, model_ids: modelIds ?? null, dry_run: dryRun })
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail ?? 'Batch restore failed')
  return data
}

export async function getModelBackupRetentionDryRun(modelId?: string): Promise<{
  to_delete: { model_id: string; file: string; timestamp_utc: string; backup_id?: string }[]
  to_delete_count: number
  kept_count: number
  policy: string
}> {
  const params = modelId ? `?model_id=${encodeURIComponent(modelId)}` : ''
  const response = await apiFetch(`${API_BASE_URL}/api/model-backups/retention-dry-run${params}`, { method: 'GET' })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

export async function cleanupModelBackupRetention(dryRun: boolean, modelId?: string): Promise<{
  dry_run?: boolean
  deleted_count?: number
  errors?: { model_id: string; file: string; error: string }[]
  to_delete_count: number
}> {
  const response = await apiFetch(`${API_BASE_URL}/api/model-backups/cleanup`, {
    method: 'POST',
    body: JSON.stringify({ dry_run: dryRun, model_id: modelId ?? null })
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * Knowledge Base API
 */

export interface CreateKnowledgeBaseRequest {
  name: string
  description?: string
  embedding_model_id: string
  chunk_size?: number
  chunk_overlap?: number
}

export interface KnowledgeBaseDiskSize {
  raw_files_size: number
  vector_table_size: number
  metadata_size: number
  total_size: number
}

export interface KnowledgeBase {
  id: string
  name: string
  description?: string
  embedding_model_id: string
  status?: string
  created_at: string
  disk_size?: KnowledgeBaseDiskSize
}

/**
 * 创建知识库
 */
export async function createKnowledgeBase(data: CreateKnowledgeBaseRequest): Promise<string> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  const result = await response.json()
  return result.id
}

/**
 * 列出所有知识库
 */
export async function listKnowledgeBases(): Promise<{ object: string; data: KnowledgeBase[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 获取知识库信息
 */
export async function getKnowledgeBase(kbId: string): Promise<KnowledgeBase> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 更新知识库信息
 */
export interface UpdateKnowledgeBaseRequest {
  name?: string
  description?: string
}

export async function updateKnowledgeBase(
  kbId: string,
  data: UpdateKnowledgeBaseRequest
): Promise<KnowledgeBase> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * 删除知识库
 */
export async function deleteKnowledgeBase(kbId: string): Promise<{ deleted: boolean; id: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}`, {
    method: 'DELETE',
  })
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 列出所有 embedding 模型
 */
export async function listEmbeddingModels(): Promise<Array<{ id: string; name: string; embedding_dim: number }>> {
  const response = await apiFetch(`${API_BASE_URL}/api/models/embedding`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  const result = await response.json()
  return result.data || []
}

/**
 * 列出知识库下的所有文档
 */
export async function listDocuments(kbId: string): Promise<{ object: string; data: any[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/documents`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 获取文档详细信息
 */
export async function getDocument(kbId: string, docId: string): Promise<any> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/documents/${docId}`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 上传文档到知识库
 */
export async function uploadDocument(kbId: string, file: File): Promise<{ id: string }> {
  const formData = new FormData()
  formData.append('file', file)
  
  const headers = new Headers()
  headers.set('X-User-Id', getUserId())
  const sid = getSessionId()
  if (sid) headers.set('X-Session-Id', sid)
  // Don't set Content-Type header - let browser set it with boundary for FormData
  
  const response = await fetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/documents`, {
    method: 'POST',
    headers,
    body: formData,
  })
  
  if (!response.ok) {
    let errorMessage = `API error: ${response.statusText}`
    try {
      const error = await response.json()
      errorMessage = error.detail || error.message || errorMessage
    } catch {
      // If response is not JSON, use status text
    }
    throw new Error(errorMessage)
  }
  
  return response.json()
}

/**
 * 删除文档
 */
export async function deleteDocument(kbId: string, docId: string): Promise<{ deleted: boolean; id: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/documents/${docId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * 重新索引文档
 */
export async function reindexDocument(kbId: string, docId: string): Promise<{ id: string; status: string; message: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/documents/${docId}/reindex`, {
    method: 'POST',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * 获取知识库统计信息
 */
export interface KnowledgeBaseStats {
  knowledge_base_id: string
  document_count: number
  document_status_breakdown: Record<string, number>
  chunk_count: number
  vector_count: number
  disk_size: KnowledgeBaseDiskSize
  embedding_model_id: string
}

export async function getKnowledgeBaseStats(kbId: string): Promise<KnowledgeBaseStats> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/stats`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 列出知识库下的所有 chunks
 */
export async function listChunks(kbId: string, limit: number = 50): Promise<{ object: string; data: any[]; total: number }> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/chunks?limit=${limit}`)
  if (!response.ok) throw new Error(`API error: ${response.statusText}`)
  return response.json()
}

/**
 * 搜索知识库
 */
export interface SearchKnowledgeBaseRequest {
  query: string
  top_k?: number
  score_threshold?: number
}

export interface SearchResult {
  content: string
  distance: number
  score: number
}

export async function searchKnowledgeBase(
  kbId: string,
  req: SearchKnowledgeBaseRequest
): Promise<{ object: string; data: SearchResult[] }> {
  const response = await apiFetch(`${API_BASE_URL}/api/knowledge-bases/${kbId}/search`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export function streamLogs(
  onLog: (entry: LogEntry) => void,
  onError?: (error: Error) => void
): () => void {
  const eventSource = new EventSource(`${API_BASE_URL}/api/system/logs/stream`)

  eventSource.onmessage = (event) => {
    try {
      const entry = JSON.parse(event.data) as LogEntry
      onLog(entry)
    } catch (e) {
      console.error('Failed to parse log entry:', e)
    }
  }

  eventSource.onerror = (_err) => {
    // EventSource 连接错误时触发
    // 注意：onerror 会在连接关闭时也触发，需要区分
    if (eventSource.readyState === EventSource.CLOSED) {
      onError?.(new Error('Log stream connection closed'))
    } else {
      onError?.(new Error('Log stream connection error'))
    }
    eventSource.close()
  }

  return () => {
    eventSource.close()
  }
}

/**
 * 解析 buffer 中的所有 SSE 消息
 * @returns 是否包含 [DONE] 信号
 */
function parseSSEBuffer(
  buffer: string, 
  onChunk: (chunk: ChatStreamResponse) => void, 
  onDone?: () => void
): boolean {
  const lines = buffer.split('\n')
  let foundDone = false

  for (const line of lines) {
    const trimmedLine = line.trim()
    if (!trimmedLine || !trimmedLine.startsWith('data: ')) continue

    const data = trimmedLine.slice(6)

    if (data === '[DONE]') {
      onDone?.()
      foundDone = true
      continue
    }

    try {
      const chunk = JSON.parse(data) as ChatStreamResponse
      onChunk(chunk)
    } catch (e) {
      // 忽略部分解析失败，可能是截断了
      console.warn('SSE Parse error:', e, data)
    }
  }
  return foundDone
}

// =========================================
// V2.6: Event & Replay API Types
// =========================================

export interface ExecutionEvent {
  event_id: string
  instance_id: string
  sequence: number
  event_type: string
  timestamp: number
  payload: Record<string, any>
  schema_version: number
}

export interface EventListResponse {
  instance_id: string
  total: number
  events: ExecutionEvent[]
}

export interface RebuiltNodeState {
  node_id: string
  state: string
  input_data: Record<string, any>
  output_data: Record<string, any>
  retry_count: number
  error_message: string | null
  error_type: string | null
  started_at: string | null
  finished_at: string | null
}

export interface RebuiltGraphState {
  instance_id: string
  graph_id: string
  state: string
  nodes: Record<string, RebuiltNodeState>
  context: Record<string, any>
  event_count: number
  last_sequence: number
}

export interface EventValidation {
  valid: boolean
  event_count: number
  node_count: number
  errors: string[]
  first_sequence: number | null
  last_sequence: number | null
}

export interface ExecutionMetrics {
  instance_id: string
  total_events: number
  node_success_rate: number
  avg_node_duration_ms: number
  total_retry_count: number
  total_execution_duration_ms: number
  completed_nodes: number
  failed_nodes: number
  details: Record<string, any>
}

/**
 * Get event stream for an instance
 */
export async function getInstanceEvents(
  instanceId: string,
  startSequence = 1,
  endSequence?: number
): Promise<EventListResponse> {
  const params = new URLSearchParams({ start_sequence: String(startSequence) })
  if (endSequence) params.append('end_sequence', String(endSequence))
  const response = await apiFetch(`${API_BASE_URL}/api/events/instance/${instanceId}?${params}`)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Get event type breakdown for an instance
 */
export async function getEventTypeBreakdown(instanceId: string): Promise<{
  instance_id: string
  total_events: number
  breakdown: Record<string, number>
}> {
  const response = await apiFetch(`${API_BASE_URL}/api/events/instance/${instanceId}/event-types`)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Replay instance state from events
 */
export async function replayInstanceState(
  instanceId: string,
  targetSequence?: number
): Promise<RebuiltGraphState> {
  const params = targetSequence ? `?target_sequence=${targetSequence}` : ''
  const response = await apiFetch(`${API_BASE_URL}/api/events/instance/${instanceId}/replay${params}`)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Validate event stream integrity
 */
export async function validateEventStream(instanceId: string): Promise<EventValidation> {
  const response = await apiFetch(`${API_BASE_URL}/api/events/instance/${instanceId}/validate`)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Get execution metrics for an instance
 */
export async function getInstanceMetrics(instanceId: string): Promise<ExecutionMetrics> {
  const response = await apiFetch(`${API_BASE_URL}/api/events/instance/${instanceId}/metrics`)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export interface ImageGenerationRequest {
  model: string
  prompt: string
  negative_prompt?: string | null
  width?: number | null
  height?: number | null
  num_inference_steps?: number | null
  guidance_scale?: number | null
  seed?: number | null
  image_format?: string
}

export interface ImageGenerationResponse {
  model: string
  mime_type: string
  width: number
  height: number
  seed?: number | null
  latency_ms?: number | null
  image_base64: string
  output_path?: string | null
  download_url?: string | null
  thumbnail_path?: string | null
  thumbnail_url?: string | null
  metadata: Record<string, any>
}

export type ImageGenerationJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface ImageGenerationJob {
  job_id: string
  status: ImageGenerationJobStatus
  model: string
  prompt: string
  phase?: string | null
  error?: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  queue_position?: number | null
  current_step?: number | null
  total_steps?: number | null
  progress?: number | null
  result?: ImageGenerationResponse | null
}

export interface ImageGenerationJobListResponse {
  items: ImageGenerationJob[]
  total: number
  limit: number
  offset: number
  has_next: boolean
}

export interface ImageGenerationWarmupStatus {
  warmup_id: string
  model: string
  status: string
  started_at?: string | null
  finished_at?: string | null
  elapsed_ms?: number | null
  output_path?: string | null
  width?: number | null
  height?: number | null
  error?: string | null
}

export async function generateImage(
  payload: ImageGenerationRequest,
  wait = true,
): Promise<ImageGenerationResponse | ImageGenerationJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/images/generate?wait=${wait ? 'true' : 'false'}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function getImageGenerationJob(jobId: string): Promise<ImageGenerationJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/images/jobs/${jobId}`, {
    method: 'GET',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function cancelImageGenerationJob(jobId: string): Promise<ImageGenerationJob> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/images/jobs/${jobId}/cancel`, {
    method: 'POST',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function deleteImageGenerationJob(jobId: string): Promise<{ ok: boolean; job_id: string }> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/images/jobs/${jobId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export function buildImageGenerationDownloadUrl(jobId: string): string {
  return `${API_BASE_URL}/api/v1/images/jobs/${jobId}/file`
}

export function buildImageGenerationThumbnailUrl(jobId: string): string {
  return `${API_BASE_URL}/api/v1/images/jobs/${jobId}/thumbnail`
}

export async function listImageGenerationJobs(params?: {
  limit?: number
  offset?: number
  status?: ImageGenerationJobStatus | ''
  model?: string
  q?: string
  sort?: 'created_at_desc' | 'created_at_asc'
  include_result?: boolean
}): Promise<ImageGenerationJobListResponse> {
  const usp = new URLSearchParams()
  if (params?.limit != null) usp.set('limit', String(params.limit))
  if (params?.offset != null) usp.set('offset', String(params.offset))
  if (params?.status) usp.set('status', params.status)
  if (params?.model) usp.set('model', params.model)
  if (params?.q) usp.set('q', params.q)
  if (params?.sort) usp.set('sort', params.sort)
  if (params?.include_result != null) usp.set('include_result', String(params.include_result))
  const response = await apiFetch(`${API_BASE_URL}/api/v1/images/jobs${usp.toString() ? `?${usp.toString()}` : ''}`, {
    method: 'GET',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function warmupImageGenerationRuntime(payload: {
  model: string
  prompt?: string
  width?: number
  height?: number
  num_inference_steps?: number
  guidance_scale?: number
  seed?: number
}): Promise<{
  ok: boolean
  warmup_id?: string
  model: string
  started_at: string
  elapsed_ms: number
  output_path?: string | null
  width: number
  height: number
}> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/images/warmup`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}

export async function getLatestImageGenerationWarmup(model?: string): Promise<ImageGenerationWarmupStatus> {
  const usp = new URLSearchParams()
  if (model) usp.set('model', model)
  const response = await apiFetch(`${API_BASE_URL}/api/v1/images/warmup/latest${usp.toString() ? `?${usp.toString()}` : ''}`, {
    method: 'GET',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `API error: ${response.statusText}`)
  }
  return response.json()
}
