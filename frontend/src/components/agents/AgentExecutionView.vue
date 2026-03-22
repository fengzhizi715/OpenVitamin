<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { 
  Search, 
  Bell, 
  Bot, 
  User, 
  RefreshCw, 
  Terminal, 
  Globe, 
  Activity, 
  History, 
  Zap, 
  Coins,
  Send,
  MoreHorizontal,
  FileText,
  Database,
  SearchCode,
  Loader2,
  Code2,
  Plus,
  Trash2,
  Upload,
  Mic,
  Square,
  X,
  Copy,
  Check,
  Wrench,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { renderMarkdown } from '@/utils/markdown'
import EventStreamViewer from './EventStreamViewer.vue'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
import { 
  getAgent, 
  runAgent, 
  runAgentWithFiles,
  getAgentSession, 
  getAgentTrace, 
  listAgentSessions,
  deleteAgentSessionMessage,
  deleteAgentSession,
  listModels,
  asrTranscribe,
  type AgentDefinition, 
  type AgentSession, 
  type AgentTraceEvent,
  type Message,
  type ModelInfo
} from '@/services/api'

const i18n = useI18n()
const { t } = i18n
const route = useRoute()
const router = useRouter()

// Computed i18n values (ensure reactivity for language switching)
const sessionSelectPlaceholder = computed(() => t('agents.execution.session_select'))
const newSessionText = computed(() => t('agents.execution.new_session'))
const emptySessionText = computed(() => t('agents.execution.empty_session'))

const agentId = route.params.id as string
const agent = ref<AgentDefinition | null>(null)
const session = ref<AgentSession | null>(null)
const traces = ref<AgentTraceEvent[]>([])
const userInput = ref('')
const isLoading = ref(true)
const isRunning = ref(false)
const isLoadingSession = ref(false)
const modelInfo = ref<ModelInfo | null>(null)

// File upload state
const fileInputRef = ref<HTMLInputElement | null>(null)
const uploadedFiles = ref<Array<{ file: File; preview?: string }>>([])
const isUploading = ref(false)
const messageAttachments = ref<Record<string, Array<{ name: string; url?: string; kind: 'image' | 'file' }>>>({})

// Voice input (ASR)
const MAX_RECORDING_SECONDS = 120
const isRecording = ref(false)
const asrLoading = ref(false)
const asrError = ref<string | null>(null)
let mediaRecorder: MediaRecorder | null = null
let audioChunks: Blob[] = []
let recordingTimerRef: ReturnType<typeof setTimeout> | null = null

// UI State
const searchLogs = ref('')
const messagesContainerRef = ref<HTMLElement | null>(null)
const copiedMessageIndex = ref<number | null>(null)

// Session persistence & switching
const SESSION_QUERY_KEY = 'session'
const agentLastSessionStorageKey = `ai_platform_agent_last_session:${agentId}`
const sessions = ref<AgentSession[]>([])
const sessionsLoading = ref(false)
const sessionsError = ref<string | null>(null)
const selectedSessionId = ref<string>('') // empty means "no active session yet"

const runtimeLabelForBackend = (backend: string | null | undefined): string => {
  if (!backend) return t('agents.execution.n_a')
  const mapping: Record<string, string> = {
    ollama: t('agents.execution.runtime_ollama'),
    lmstudio: t('agents.execution.runtime_lmstudio'),
    local: t('agents.execution.runtime_local'),
    openai: t('agents.execution.runtime_openai'),
    gemini: t('agents.execution.runtime_gemini'),
    deepseek: t('agents.execution.runtime_deepseek'),
    kimi: t('agents.execution.runtime_kimi'),
    mock: t('agents.execution.runtime_mock'),
  }
  return mapping[backend] || backend
}

const fetchAgentData = async () => {
  try {
    isLoading.value = true
    const [agentData, modelsData] = await Promise.all([
      getAgent(agentId),
      listModels()
    ])
    agent.value = agentData
    
    // Find model info for the agent's model_id
    if (agentData?.model_id) {
      const foundModel = modelsData.data?.find((m: ModelInfo) => m.id === agentData.model_id)
      modelInfo.value = foundModel || null
    }
  } catch (error) {
    console.error('Failed to fetch agent:', error)
  } finally {
    isLoading.value = false
  }
}

const providerDisplay = computed(() => {
  if (!modelInfo.value?.backend) return t('agents.execution.n_a')
  return runtimeLabelForBackend(modelInfo.value.backend)
})

const formatTime = (iso?: string) => {
  if (!iso) return ''
  const d = new Date(iso)
  const hh = d.getHours().toString().padStart(2, '0')
  const mm = d.getMinutes().toString().padStart(2, '0')
  return `${hh}:${mm}`
}

const getSessionPreview = (s: AgentSession) => {
  const last = [...(s.messages || [])].reverse().find(m => m.role !== 'system')
  if (!last?.content) return ''
  return last.content.replace(/\s+/g, ' ').slice(0, 48)
}

const getRouteSessionId = (): string | null => {
  const raw = (route.query as any)?.[SESSION_QUERY_KEY]
  if (typeof raw !== 'string') return null
  const sid = raw.trim()
  return sid ? sid : null
}

const setRouteSessionId = async (sid: string | null) => {
  const nextQuery: Record<string, any> = { ...(route.query as any) }
  if (sid) nextQuery[SESSION_QUERY_KEY] = sid
  else delete nextQuery[SESSION_QUERY_KEY]
  await router.replace({ query: nextQuery })
}

const persistActiveSessionId = async (sid: string | null) => {
  if (sid) localStorage.setItem(agentLastSessionStorageKey, sid)
  else localStorage.removeItem(agentLastSessionStorageKey)
  await setRouteSessionId(sid)
  selectedSessionId.value = sid || ''
}

const fetchSessionsList = async () => {
  try {
    sessionsLoading.value = true
    sessionsError.value = null
    const res = await listAgentSessions({ agent_id: agentId, limit: 30 })
    sessions.value = res.data || []
  } catch (e) {
    sessionsError.value = e instanceof Error ? e.message : String(e)
    sessions.value = []
  } finally {
    sessionsLoading.value = false
  }
}

const loadSession = async (sid: string) => {
  try {
    isLoadingSession.value = true
    const loaded = await getAgentSession(sid)
    session.value = loaded
    await persistActiveSessionId(loaded.session_id)
    await fetchTraces()
  } catch (e) {
    console.error('Failed to load agent session:', e)
    await persistActiveSessionId(null)
    session.value = null
    traces.value = []
  } finally {
    isLoadingSession.value = false
  }
}

const startNewSession = async () => {
  // Clear current view; a new session will be created when user sends next message.
  session.value = null
  traces.value = []
  await persistActiveSessionId(null)
}

const handleDeleteMessage = async (messageIndex: number) => {
  if (!session.value?.session_id) return
  
  try {
    const updated = await deleteAgentSessionMessage(session.value.session_id, messageIndex)
    session.value = updated
    await fetchTraces() // Refresh traces after deletion
  } catch (error) {
    console.error('Failed to delete message:', error)
  }
}

const handleCopyMessage = async (content: string, messageIndex: number) => {
  try {
    // 提取纯文本内容（去除 HTML 标签）
    const tempDiv = document.createElement('div')
    tempDiv.innerHTML = content || ''
    const textContent = tempDiv.textContent || tempDiv.innerText || content
    
    await navigator.clipboard.writeText(textContent)
    copiedMessageIndex.value = messageIndex
    setTimeout(() => {
      copiedMessageIndex.value = null
    }, 2000)
  } catch (err) {
    console.error('Failed to copy:', err)
  }
}

const handleDeleteSession = async (sessionId: string) => {
  if (!sessionId) return
  
  if (!confirm(t('agents.execution.confirm_delete_session'))) {
    return
  }
  
  try {
    await deleteAgentSession(sessionId)
    // If deleted session is current session, clear it
    if (session.value?.session_id === sessionId) {
      session.value = null
      traces.value = []
      await persistActiveSessionId(null)
    }
    // Refresh sessions list
    await fetchSessionsList()
    // If no sessions left or current session was deleted, start new session
    if (sessions.value.length === 0 || session.value === null) {
      await startNewSession()
    }
  } catch (error) {
    console.error('Failed to delete session:', error)
  }
}

const handleSendMessage = async () => {
  if ((!userInput.value.trim() && uploadedFiles.value.length === 0) || isRunning.value) return
  
  // Build message content with file references
  let messageContent = userInput.value.trim()
  
  // Add file information to message if files are uploaded
  if (uploadedFiles.value.length > 0) {
    const fileInfo = uploadedFiles.value.map((item, idx) => {
      return t('agents.execution.file_info', {
        index: idx + 1,
        name: item.file.name,
        size: (item.file.size / 1024).toFixed(2)
      })
    }).join('\n')
    
    if (messageContent) {
      messageContent = `${messageContent}\n\n${fileInfo}`
    } else {
      messageContent = t('agents.execution.process_files', { files: fileInfo })
    }
    
    // Attachments marker for persistence (hidden in UI)
    const attachmentNames = uploadedFiles.value.map((item) => item.file.name).join('|')
    messageContent = `${messageContent}\n\n[Attachments: ${attachmentNames}]`
  }
  
  const userMessage: Message = { role: 'user', content: messageContent }
  const filesToUpload = uploadedFiles.value.map((item) => item.file)
  // 使用消息索引作为 key，避免相同内容的消息覆盖附件
  const messageCount = session.value?.messages?.length || 0
  const attachmentKey = `msg_${messageCount}`
  if (filesToUpload.length > 0) {
    messageAttachments.value[attachmentKey] = filesToUpload.map((file) => {
      const isImage = file.type.startsWith('image/')
      return {
        name: file.name,
        kind: isImage ? 'image' : 'file',
        url: isImage ? URL.createObjectURL(file) : undefined
      }
    })
  }
  userInput.value = ''
  clearFiles()
  
  // 保存当前消息历史
  const previousMessages = session.value?.messages ? [...session.value.messages] : []
  
  // Initialize or update session
  isRunning.value = true
  try {
    // 先添加用户消息到本地 session（立即显示，乐观更新）
    if (session.value) {
      session.value.messages = [...previousMessages, userMessage]
    } else {
      // 如果没有 session，创建一个临时 session 用于显示
      session.value = {
        session_id: '',
        agent_id: agentId,
        user_id: 'default',
        trace_id: '',
        messages: [userMessage],
        step: 0,
        status: 'running',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      }
    }
    
    const res = filesToUpload.length > 0
      ? await runAgentWithFiles(agentId, [userMessage], session.value?.session_id || undefined, filesToUpload)
      : await runAgent(agentId, {
          messages: [userMessage],
          session_id: session.value?.session_id || undefined
        })
    
    // 后端应该返回完整的消息历史（包括所有之前的消息 + 新用户消息 + AI 回复）
    // 直接使用后端返回的 session，因为它包含完整的历史
    if (res && res.messages && res.messages.length > 0) {
      session.value = res
      await persistActiveSessionId(res.session_id)
    } else {
      // 如果后端没有返回消息，保持当前状态（不应该发生，但作为保护）
      console.warn('Backend returned session without messages, keeping current state')
      if (session.value) {
        session.value = {
          ...res,
          messages: session.value.messages
        }
      } else {
        session.value = res
      }
    }
    
    await fetchTraces()
    await fetchSessionsList()
  } catch (error) {
    console.error('Failed to run agent:', error)
    // 如果出错，回滚到之前的状态
    if (session.value) {
      session.value.messages = previousMessages
    }
  } finally {
    isRunning.value = false
  }
}

const fetchTraces = async () => {
  if (!session.value?.session_id) return
  try {
    const res = await getAgentTrace(session.value.session_id)
    traces.value = res.data
  } catch (error) {
    console.error('Failed to fetch traces:', error)
  }
}

// Polling for updates if running
let pollInterval: any = null
watch(() => session.value?.status, (newStatus) => {
  if (newStatus === 'running') {
    if (!pollInterval) {
      pollInterval = setInterval(async () => {
        if (session.value?.session_id) {
          try {
            const updatedSession = await getAgentSession(session.value.session_id)
            // 确保保留所有消息历史
            if (updatedSession && updatedSession.messages) {
              // 如果更新的 session 消息数量少于当前，保留当前的消息（防止丢失）
              if (session.value && session.value.messages && 
                  updatedSession.messages.length < session.value.messages.length) {
                // 合并消息：保留当前消息，但更新其他字段
                session.value = {
                  ...updatedSession,
                  messages: session.value.messages
                }
              } else {
                // 更新的消息数量更多或相等，使用更新的
                session.value = updatedSession
              }
            } else {
              session.value = updatedSession
            }
            await fetchTraces()
          } catch (error) {
            console.error('Failed to poll session:', error)
          }
        }
      }, 2000)
    }
  } else {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }
})

// Switch session from dropdown
watch(selectedSessionId, async (sid) => {
  if (!sid) return
  if (sid === session.value?.session_id) return
  await loadSession(sid)
})

// React to URL changes (back/forward/share links)
watch(() => (route.query as any)?.[SESSION_QUERY_KEY], async (raw) => {
  const sid = typeof raw === 'string' ? raw.trim() : ''
  if (!sid) return
  if (sid === session.value?.session_id) return
  await loadSession(sid)
})

onMounted(async () => {
  await fetchAgentData()
  await fetchSessionsList()

  // Restore session from URL (?session=) or localStorage
  const sid = getRouteSessionId() || localStorage.getItem(agentLastSessionStorageKey)
  if (sid) {
    await loadSession(sid)
  } else {
    // If no explicit session provided, auto-load the most recent session (if any)
    const latest = sessions.value?.[0]?.session_id
    if (latest) {
      await loadSession(latest)
    } else {
      selectedSessionId.value = ''
    }
  }
  await scrollToBottom()
})

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
  Object.values(messageAttachments.value).forEach((items) => {
    items.forEach((it) => {
      if (it.url && it.url.startsWith('blob:')) {
        URL.revokeObjectURL(it.url)
      }
    })
  })
  clearRecordingTimer()
})

const goBack = () => router.push('/agents')

const getStepProgress = computed(() => {
  if (!session.value) return 0
  return (session.value.step / (agent.value?.max_steps || 20)) * 100
})

const currentStepDesc = computed(() => {
  if (!session.value || session.value.status === 'idle') return t('agents.execution.waiting_input')
  if (session.value.status === 'running') return t('agents.execution.step_thinking', { step: session.value.step })
  if (session.value.status === 'finished') return t('agents.execution.finished')
  return t('agents.execution.error')
})

// Calculate latency from traces (average of LLM request durations)
const sessionLatency = computed(() => {
  if (!traces.value || traces.value.length === 0) return null
  const llmTraces = traces.value.filter(t => t.event_type === 'llm_request' && t.duration_ms)
  if (llmTraces.length === 0) return null
  const avgMs = llmTraces.reduce((sum, t) => sum + (t.duration_ms || 0), 0) / llmTraces.length
  return Math.round(avgMs)
})

// Format latency display
const latencyDisplay = computed(() => {
  const ms = sessionLatency.value
  if (ms === null) return t('agents.execution.n_a')
  return `${ms}ms`
})

// Calculate tokens (placeholder - would need backend to provide token counts)
const tokensDisplay = computed(() => {
  // For now, show N/A since we don't have token counts from backend
  return t('agents.execution.n_a')
})

const getToolName = (toolId: string) => {
  if (!toolId) return toolId
  
  // For keys with dots like "file.read", vue-i18n interprets them as nested paths
  // So we need to access the messages object directly using bracket notation
  try {
    const currentLocale = i18n.locale.value
    const messages = (i18n as any).messages.value[currentLocale] || (i18n as any).messages.value.en
    const tools = messages?.agents?.tools
    // Access tool name using bracket notation to handle keys with dots
    if (tools && tools[toolId]) {
      return tools[toolId]
    }
  } catch (e) {
    // Fallback to t() function
  }
  
  // Try using t() function with the key
  const key = `agents.tools.${toolId}`
  const translated = t(key)
  
  // If translation returns the key path itself (meaning not found), use fallback
  if (translated === key || translated.includes('agents.tools')) {
    // Fallback: format tool ID nicely (e.g., "file.read" -> "File Read")
    return toolId.split('.').map(part => 
      part.charAt(0).toUpperCase() + part.slice(1)
    ).join(' ')
  }
  
  return translated
}

// Merge messages with tool-call traces so "Calling Tool" blocks appear in conversation order, not all at the bottom
type DisplayItem =
  | { type: 'message'; message: Message; messageIndex: number }
  | { type: 'tool_call'; trace: AgentTraceEvent; resultContent: string | null }
  | { type: 'tool_result'; toolName: string; skillId?: string; summary: Array<{ key: string; value: string }>; rawJson: string; previewUrl?: string; downloadUrl?: string }
  | { type: 'vision_image'; imageUrl: string; traceStep?: number; summary?: string; explanation?: string }

type ParsedToolEnvelope = {
  toolName: string
  skillId?: string
  summary: Array<{ key: string; value: string }>
  rawJson: string
  previewUrl?: string
  downloadUrl?: string
}

const summarizeToolValue = (value: unknown): string => {
  if (value == null) return t('agents.execution.summary_null')
  if (typeof value === 'string') return value.length > 120 ? `${value.slice(0, 117)}...` : value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return t('agents.execution.summary_items', { count: value.length })
  if (typeof value === 'object') return t('agents.execution.summary_fields', { count: Object.keys(value as Record<string, unknown>).length })
  return String(value)
}

const pickNestedRecord = (value: unknown, key: string): Record<string, unknown> | null => {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  const nested = record[key]
  return nested && typeof nested === 'object' ? (nested as Record<string, unknown>) : null
}

const buildToolResultSummary = (payload: Record<string, unknown>): Array<{ key: string; value: string }> => {
  const summary: Array<{ key: string; value: string }> = []
  const seen = new Set<string>()
  const result = pickNestedRecord(payload, 'result')

  const add = (key: string, value: unknown) => {
    if (value == null || seen.has(key)) return
    const rendered = summarizeToolValue(value)
    if (!rendered || rendered === t('agents.execution.summary_null')) return
    summary.push({ key, value: rendered })
    seen.add(key)
  }

  add(t('agents.execution.summary_status'), payload.status)
  add(t('agents.execution.summary_phase'), payload.phase)
  add(t('agents.execution.summary_model'), payload.model ?? payload.model_id ?? result?.model)
  if (result?.width != null && result?.height != null) {
    add(t('agents.execution.summary_size'), `${result.width} × ${result.height}`)
  }
  add(t('agents.execution.summary_latency'), result?.latency_ms != null ? `${result.latency_ms} ms` : payload.latency_ms != null ? `${payload.latency_ms} ms` : null)
  add(t('agents.execution.summary_job_id'), payload.job_id)
  add(t('agents.execution.summary_mode'), payload.mode)

  for (const [key, value] of Object.entries(payload)) {
    if (seen.has(key) || key === 'result') continue
    if (summary.length >= 6) break
    add(key, value)
  }

  return summary
}

const absolutizeApiUrl = (value: string): string => {
  if (!value) return value
  if (/^https?:\/\//i.test(value) || value.startsWith('data:')) return value
  if (value.startsWith('/')) return `${API_BASE_URL}${value}`
  return value
}

const findFirstStringByKeys = (value: unknown, keys: string[]): string | undefined => {
  if (!value || typeof value !== 'object') return undefined
  const record = value as Record<string, unknown>
  for (const key of keys) {
    const candidate = record[key]
    if (typeof candidate === 'string' && candidate.trim()) {
      return candidate.trim()
    }
  }
  for (const nested of Object.values(record)) {
    const found = findFirstStringByKeys(nested, keys)
    if (found) return found
  }
  return undefined
}

const extractToolMediaUrls = (payload: Record<string, unknown>): { previewUrl?: string; downloadUrl?: string } => {
  const base64 = findFirstStringByKeys(payload, ['image_base64'])
  const thumbnailUrl = findFirstStringByKeys(payload, ['thumbnail_url', 'thumbnailUrl', 'preview_url', 'previewUrl', 'image_url', 'imageUrl'])
  const downloadUrl = findFirstStringByKeys(payload, ['download_url', 'downloadUrl', 'file_url', 'fileUrl', 'url'])

  const previewUrl = base64
    ? `data:image/png;base64,${base64}`
    : (thumbnailUrl ? absolutizeApiUrl(thumbnailUrl) : (downloadUrl ? absolutizeApiUrl(downloadUrl) : undefined))

  return {
    previewUrl,
    downloadUrl: downloadUrl ? absolutizeApiUrl(downloadUrl) : undefined,
  }
}

const parseDirectToolEnvelope = (content: string): ParsedToolEnvelope | null => {
  if (!content || typeof content !== 'string') return null
  try {
    const parsed = JSON.parse(content)
    if (!parsed || typeof parsed !== 'object' || parsed.type !== 'tool') return null
    const toolName = typeof parsed.tool_name === 'string' ? parsed.tool_name : ''
    const skillId = typeof parsed.skill_id === 'string' ? parsed.skill_id : undefined
    const payload = parsed.output && typeof parsed.output === 'object' ? parsed.output : {}
    const rawJson = JSON.stringify(parsed, null, 2)
    const media = extractToolMediaUrls(payload as Record<string, unknown>)
    return {
      toolName,
      skillId,
      summary: buildToolResultSummary(payload as Record<string, unknown>),
      rawJson,
      previewUrl: media.previewUrl,
      downloadUrl: media.downloadUrl,
    }
  } catch {
    return null
  }
}

const displayItems = computed(() => {
  const messages = session.value?.messages ?? []
  const items: DisplayItem[] = []
  const visionTraces = (traces.value || [])
    .filter(t => (t.event_type === 'tool_call' || t.event_type === 'skill_call') && t.tool_id === 'builtin_vision.detect_objects')
    .map(t => {
      const data = t.output_data as any
      const url = data && typeof data === 'object' ? data.annotated_image : null
      const objects = data && typeof data === 'object' ? data.objects : null
      let summary = undefined as string | undefined
      if (Array.isArray(objects) && objects.length > 0) {
        const counts: Record<string, number> = {}
        for (const o of objects) {
          const label = (o && o.label) ? String(o.label) : 'unknown'
          counts[label] = (counts[label] || 0) + 1
        }
        const parts = Object.entries(counts)
          .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]))
          .map(([k, v]) => `${k}×${v}`)
        summary = `${t('agents.execution.detection_summary_prefix')}：${parts.join('，')}`
      } else if (Array.isArray(objects) && objects.length === 0) {
        summary = `${t('agents.execution.detection_summary_prefix')}：${t('agents.execution.detection_summary_none')}`
      }
      return typeof url === 'string' && url.startsWith('data:image/') ? { url, step: t.step, summary } : null
    })
    .filter(Boolean) as Array<{ url: string; step?: number }>
  const vlmTexts = (traces.value || [])
    .filter(t => (t.event_type === 'tool_call' || t.event_type === 'skill_call') && t.tool_id === 'builtin_vlm.generate')
    .map(t => {
      const data = t.output_data as any
      const text = data && typeof data === 'object' ? data.text : null
      return typeof text === 'string' && text.trim() ? text.trim() : null
    })
    .filter(Boolean) as string[]
  const usedVlmText = new Set<string>()
  let visionIdx = 0
  
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i]
    const content = (msg.content ?? '').trim()

    // Intercept vision tool calls and insert annotated image into conversation
    const isVisionCallMessage =
      msg.role === 'assistant' &&
      (content.includes('Calling skill `builtin_vision.detect_objects`.') ||
        content.includes('Calling tool `vision.detect_objects`.'))
    if (isVisionCallMessage) {
      const nextVision = visionTraces[visionIdx]
      const nextVlmText = vlmTexts[visionIdx]
      if (nextVision?.url) {
        items.push({
          type: 'vision_image',
          imageUrl: nextVision.url,
          traceStep: nextVision.step,
          summary: nextVision.summary,
          explanation: nextVlmText,
        })
        if (nextVlmText) usedVlmText.add(nextVlmText)
      }
      visionIdx += 1
      continue
    }
    
    // Skip all tool-related messages (comprehensive filtering)
    const isToolCallMessage = 
      msg.role === 'tool' ||  // Skip tool role messages entirely
      (msg.role === 'assistant' && (
        content.startsWith('Calling tool `') || 
        content.startsWith('Calling skill `') ||
        content.includes('Calling tool ') ||
        content.includes('Calling skill ')
      )) ||
      (msg.role === 'user' && (
        content.includes('Tool result (untrusted)') ||
        content.includes('Skill result (untrusted)') ||
        content.includes('Tool execution error (untrusted)') ||
        content.includes('Skill execution error (untrusted)') ||
        content.includes('Skill result (untrusted)') ||
        content.includes('Skill result (observation)') ||  // New format
        content.startsWith('Skill result') ||
        content.startsWith('Tool result')
      ));
    
    if (isToolCallMessage) {
      // Skip these messages entirely - don't display them
      continue
    }

    // Skip duplicate assistant message if it's already embedded in vision bubble
    if (msg.role === 'assistant') {
      const trimmed = content.trim()
      if (trimmed && usedVlmText.has(trimmed)) {
        continue
      }
      const directToolEnvelope = parseDirectToolEnvelope(trimmed)
      if (directToolEnvelope) {
        items.push({
          type: 'tool_result',
          toolName: directToolEnvelope.toolName,
          skillId: directToolEnvelope.skillId,
          summary: directToolEnvelope.summary,
          rawJson: directToolEnvelope.rawJson,
          previewUrl: directToolEnvelope.previewUrl,
          downloadUrl: directToolEnvelope.downloadUrl,
        })
        continue
      }
    }
    
    // Only show regular user and assistant messages
    items.push({ type: 'message', message: msg, messageIndex: i })
  }

  // If any vision traces remain (no matching "Calling skill" message), append them at end
  for (; visionIdx < visionTraces.length; visionIdx++) {
    const nextVision = visionTraces[visionIdx]
    const nextVlmText = vlmTexts[visionIdx]
    if (nextVision?.url) {
      items.push({
        type: 'vision_image',
        imageUrl: nextVision.url,
        traceStep: nextVision.step,
        summary: nextVision.summary,
        explanation: nextVlmText,
      })
      if (nextVlmText) usedVlmText.add(nextVlmText)
    }
  }
  
  return items
})

// Check if agent supports file processing (v1.5: enabled_skills or legacy tool_ids)
const supportsFileProcessing = computed(() => {
  const skills = agent.value?.enabled_skills ?? []
  const tools = agent.value?.tool_ids ?? []
  return skills.some((s: string) =>
    s === 'builtin_file.read' || s === 'builtin_file.list' || s === 'builtin_vision.detect_objects'
  ) || tools.some((t: string) => t === 'file.read' || t === 'file.list' || t === 'vision.detect_objects')
})

// v1.5: capability list for sidebar — prefer enabled_skills, fallback to tool_ids
const capabilityDisplayList = computed(() => {
  const skills = agent.value?.enabled_skills ?? []
  const tools = agent.value?.tool_ids ?? []
  if (skills.length > 0) {
    return skills.map((s: string) => s.startsWith('builtin_') ? s.slice(8) : s)
  }
  return tools
})

// Handle file selection
const handleFileSelect = (event: Event) => {
  const input = event.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return
  
  const files = Array.from(input.files)
  files.forEach(file => {
    uploadedFiles.value.push({ file })
  })
  
  // Reset input to allow selecting the same file again
  if (fileInputRef.value) {
    fileInputRef.value.value = ''
  }
}

// Remove uploaded file
const removeFile = (index: number) => {
  uploadedFiles.value.splice(index, 1)
}

// Clear all files
const clearFiles = () => {
  uploadedFiles.value = []
}

const clearRecordingTimer = () => {
  if (recordingTimerRef) {
    clearTimeout(recordingTimerRef)
    recordingTimerRef = null
  }
}

const toggleVoiceInput = async () => {
  if (asrLoading.value || isRunning.value) return

  if (isRecording.value) {
    clearRecordingTimer()
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop()
    }
    return
  }

  try {
    asrError.value = null
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm'
    mediaRecorder = new MediaRecorder(stream)
    audioChunks = []

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data)
    }

    mediaRecorder.onstop = async () => {
      clearRecordingTimer()
      stream.getTracks().forEach((t) => t.stop())
      if (audioChunks.length === 0) {
        isRecording.value = false
        return
      }
      const blob = new Blob(audioChunks, { type: mimeType })
      isRecording.value = false
      asrLoading.value = true
      try {
        const result = await asrTranscribe(blob)
        const text = (result.text || '').trim()
        if (text) {
          userInput.value = userInput.value ? `${userInput.value}\n${text}` : text
        }
      } catch (err) {
        asrError.value = err instanceof Error ? err.message : String(err)
      } finally {
        asrLoading.value = false
      }
    }

    mediaRecorder.start()
    isRecording.value = true

    recordingTimerRef = setTimeout(() => {
      if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop()
      }
    }, MAX_RECORDING_SECONDS * 1000)
  } catch (err) {
    asrError.value = err instanceof Error ? err.message : String(err)
    if (err instanceof Error && err.name === 'NotAllowedError') {
      asrError.value = t('chat.voice_permission_denied')
    }
  }
}

const stripWorkspaceHints = (content: string) => {
  if (!content) return content
  // Remove per-file header lines like "[File 1: ...]"
  const lines = content.split('\n')
  const filtered = lines.filter(line => !/^\s*\[File\s+\d+:/i.test(line))
  const withoutFileHeader = filtered.join('\n')
  // Remove attachment marker line
  const withoutAttachmentMarker = withoutFileHeader
    .split('\n')
    .filter(line => !/^\s*\[Attachments:\s*/i.test(line))
    .join('\n')
  // Remove appended workspace/tool hints to keep user message clean
  const idx = withoutAttachmentMarker.indexOf('\n\n[Files ')
  if (idx === -1) return withoutAttachmentMarker.trim()
  return withoutAttachmentMarker.slice(0, idx).trim()
}

const renderMessageContent = (content: string, role?: string) => {
  const cleaned = role === 'user' ? stripWorkspaceHints(content) : content
  return renderMarkdown(cleaned)
}

const parseAttachmentNames = (content: string) => {
  const m = content.match(/\[Attachments:\s*([^\]]+)\]/i)
  if (!m) return []
  return m[1]
    .split('|')
    .map((s) => s.trim())
    .filter(Boolean)
}

const buildFileUrl = (filename: string) => {
  const sid = session.value?.session_id
  if (!sid) return ''
  return `${API_BASE_URL}/api/agent-sessions/${encodeURIComponent(sid)}/files/${encodeURIComponent(filename)}`
}

const getMessageAttachments = (content: string, role?: string, messageIndex?: number) => {
  if (role !== 'user') return []
  // 使用消息索引作为 key
  const key = messageIndex !== undefined ? `msg_${messageIndex}` : stripWorkspaceHints(content)
  const local = messageAttachments.value[key]
  if (local && local.length > 0) return local
  const names = parseAttachmentNames(content)
  if (names.length === 0) return []
  return names.map((name) => {
    const lower = name.toLowerCase()
    const isImage = /\.(png|jpe?g|gif|webp|bmp)$/i.test(lower)
    return {
      name,
      kind: isImage ? 'image' : 'file',
      url: isImage ? buildFileUrl(name) : undefined
    }
  })
}

const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainerRef.value) {
    messagesContainerRef.value.scrollTo({
      top: messagesContainerRef.value.scrollHeight,
      behavior: 'smooth'
    })
  }
}

// Watch for new messages and auto-scroll
watch(() => session.value?.messages?.length, async () => {
  await scrollToBottom()
})

// Watch for message content changes (for streaming updates)
watch(() => {
  const lastMsg = session.value?.messages?.[session.value.messages.length - 1]
  return lastMsg ? lastMsg.content : ''
}, async () => {
  await scrollToBottom()
})
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden font-sans">
    <!-- Top Header -->
    <header class="h-16 border-b border-border bg-muted px-6 flex items-center justify-between shrink-0 shadow-sm z-10">
      <div class="flex items-center gap-4">
        <div class="flex items-center gap-2 text-muted-foreground text-sm">
          <button @click="goBack" class="hover:text-blue-500 transition-colors flex items-center gap-1">
            <span class="font-medium">{{ t('nav.agents') }}</span>
          </button>
          <span class="text-muted-foreground/60">/</span>
          <span class="font-semibold text-foreground">{{ agent?.name || t('agents.execution.loading') }}</span>
        </div>
      </div>
      
      <div class="flex items-center gap-6">
        <div class="flex items-center gap-3">
          <Select v-model="selectedSessionId" :disabled="sessionsLoading">
            <SelectTrigger class="w-[300px] h-10 bg-card border border-border rounded-xl text-sm">
              <SelectValue :placeholder="sessionSelectPlaceholder" />
            </SelectTrigger>
            <SelectContent class="max-h-[320px]">
              <SelectItem v-if="sessionsLoading" value="__loading" disabled>
                {{ t('agents.execution.sessions_loading') }}
              </SelectItem>
              <template v-else>
                <SelectItem v-if="sessions.length === 0" value="__empty" disabled>
                  {{ t('agents.execution.sessions_empty') }}
                </SelectItem>
                <template v-else>
                  <SelectItem
                    v-for="s in sessions"
                    :key="s.session_id"
                    :value="s.session_id"
                    class="cursor-pointer group/item"
                  >
                    <div class="flex items-center justify-between w-full gap-2">
                      <div class="flex flex-col gap-0.5 flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-xs text-muted-foreground">{{ formatTime(s.updated_at) }}</span>
                          <span class="text-xs font-medium text-foreground/90 truncate">{{ s.session_id }}</span>
                        </div>
                        <div class="text-[11px] text-muted-foreground truncate max-w-[200px]">
                          {{ getSessionPreview(s) }}
                        </div>
                      </div>
                      <button
                        @click.stop="handleDeleteSession(s.session_id)"
                        class="opacity-0 group-hover/item:opacity-100 transition-opacity p-1 rounded hover:bg-muted text-muted-foreground hover:text-red-400 shrink-0"
                        :title="t('agents.execution.delete_session')"
                      >
                        <Trash2 class="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </SelectItem>
                </template>
              </template>
            </SelectContent>
          </Select>

          <Button
            variant="outline"
            class="h-10 rounded-xl bg-card border-border text-muted-foreground hover:text-foreground hover:bg-muted gap-2"
            @click="startNewSession"
            type="button"
          >
            <Plus class="w-4 h-4" />
            {{ newSessionText }}
          </Button>
        </div>

        <div class="relative w-72">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input 
            v-model="searchLogs"
            :placeholder="t('agents.execution.search_logs')" 
            class="pl-10 h-10 bg-card border-border focus-visible:ring-1 focus-visible:ring-blue-500 rounded-xl text-sm"
          />
        </div>
        <Button class="bg-blue-600 hover:bg-blue-700 text-white font-bold h-10 px-6 rounded-xl shadow-lg shadow-blue-500/20">
          {{ t('agents.execution.deploy') }}
        </Button>
        <button class="p-2 text-muted-foreground hover:text-foreground transition-colors relative">
          <Bell class="w-5 h-5" />
          <span class="absolute top-2 right-2 w-2 h-2 bg-rose-500 rounded-full border-2 border-muted"></span>
        </button>
      </div>
    </header>

    <div class="flex-1 flex overflow-hidden">
      <!-- Main Chat Area -->
      <main class="flex-1 flex flex-col bg-background overflow-hidden border-r border-border">
        <!-- Messages List -->
        <div 
          ref="messagesContainerRef"
          class="flex-1 overflow-y-auto p-8 custom-scrollbar"
        >
          <div v-if="isLoading || isLoadingSession" class="flex items-center justify-center h-full">
            <Loader2 class="w-8 h-8 animate-spin text-blue-500" />
          </div>
          
          <template v-else>
            <div v-if="!session" class="flex items-center justify-center h-full text-sm text-muted-foreground">
              {{ emptySessionText }}
            </div>

            <template v-else>
            <!-- Messages only (all tool calls hidden from user view) -->
            <template v-for="(item, idx) in displayItems" :key="`msg-${idx}`">
              <!-- Message bubble -->
              <div 
                v-if="item.type === 'message'"
                :class="['flex gap-4 group mb-6', item.message.role === 'user' ? 'justify-end' : 'justify-start']"
              >
                <div 
                  :class="[
                    'w-8 h-8 rounded-full flex items-center justify-center shrink-0',
                    item.message.role === 'user' ? 'bg-orange-500 text-white' : 'bg-blue-600 text-white'
                  ]"
                >
                  <User v-if="item.message.role === 'user'" class="w-4 h-4" />
                  <Bot v-else class="w-4 h-4" />
                </div>
                <div :class="['flex-1 max-w-[85%]', item.message.role === 'user' ? 'flex justify-end' : '']">
                  <div :class="['space-y-2', item.message.role === 'user' ? 'items-end' : 'items-start']">
                    <div class="flex items-center gap-2 text-xs text-muted-foreground">
                      <span class="font-medium capitalize">
                        {{ item.message.role === 'user' ? t('agents.execution.you') : (agent?.name || t('agents.execution.agent')) }}
                      </span>
                    </div>
                    <div 
                      :class="[
                        'rounded-2xl px-4 py-3 text-sm leading-relaxed relative group/msg border shadow-sm break-words min-w-[60px] max-w-full',
                        item.message.role === 'user' 
                          ? 'bg-orange-500/10 text-orange-900 dark:text-orange-100 border-orange-500/30 shadow-orange-500/5' 
                          : 'bg-card text-foreground/90 border-border/50'
                      ]"
                    >
                      <div class="absolute top-2 right-2 opacity-0 group-hover/msg:opacity-100 transition-opacity flex gap-1 z-10 bg-background/80 backdrop-blur-sm rounded-lg p-1">
                        <button
                          @click="handleCopyMessage(item.message.content || '', item.messageIndex)"
                          class="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                          :title="copiedMessageIndex === item.messageIndex ? t('chat.message.copied') : t('chat.message.copy')"
                        >
                          <Check v-if="copiedMessageIndex === item.messageIndex" class="w-3.5 h-3.5 text-green-500" />
                          <Copy v-else class="w-3.5 h-3.5" />
                        </button>
                        <button
                          v-if="session?.session_id && !isRunning"
                          @click="handleDeleteMessage(item.messageIndex)"
                          class="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-red-400 transition-colors"
                          :title="t('agents.execution.delete_message')"
                        >
                          <Trash2 class="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <div 
                        class="prose prose-sm dark:prose-invert max-w-none prose-p:leading-relaxed prose-pre:p-0 prose-pre:bg-transparent prose-code:text-blue-400 prose-code:bg-blue-500/10 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none pt-10"
                        v-html="renderMessageContent(item.message.content, item.message.role)"
                      ></div>
                      <div v-if="getMessageAttachments(item.message.content, item.message.role, item.messageIndex).length > 0" class="mt-3 flex flex-wrap gap-2">
                        <template v-for="(att, aidx) in getMessageAttachments(item.message.content, item.message.role, item.messageIndex)" :key="`att-${idx}-${aidx}`">
                          <div v-if="att.kind === 'image' && att.url" class="rounded-lg border border-border/50 bg-muted/40 p-2">
                            <img :src="att.url" :alt="att.name" class="max-w-[240px] max-h-40 object-contain rounded-md" />
                            <div class="mt-1 text-[10px] text-muted-foreground truncate max-w-[240px]">{{ att.name }}</div>
                          </div>
                          <div v-else class="rounded-lg border border-border/50 bg-muted/40 px-3 py-2 text-[11px] text-foreground/80">
                            {{ att.name }}
                          </div>
                        </template>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div
                v-else-if="item.type === 'tool_result'"
                class="flex gap-4 group mb-6 justify-start"
              >
                <div class="w-8 h-8 rounded-full flex items-center justify-center shrink-0 bg-blue-600 text-white">
                  <Wrench class="w-4 h-4" />
                </div>
                <div class="flex-1 max-w-[85%]">
                  <div class="space-y-2 items-start">
                    <div class="flex items-center gap-2 text-xs text-muted-foreground">
                      <span class="font-medium capitalize">{{ agent?.name || t('agents.execution.agent') }}</span>
                      <span class="text-[10px] text-muted-foreground/70">{{ t('agents.execution.tool_result') }}</span>
                    </div>
                    <div class="rounded-2xl px-4 py-3 text-sm leading-relaxed border shadow-sm bg-card text-foreground/90 border-border/50">
                      <div class="flex items-center gap-2 mb-3">
                        <Badge variant="secondary" class="text-[10px] font-medium">
                          {{ getToolName(item.toolName || item.skillId || 'tool') }}
                        </Badge>
                      </div>
                      <div v-if="item.previewUrl" class="mb-4">
                        <img :src="item.previewUrl" :alt="t('agents.execution.tool_preview_alt')" class="max-w-full max-h-96 object-contain rounded-lg border border-border/50 bg-muted/20" />
                        <div v-if="item.downloadUrl" class="mt-2">
                          <a
                            :href="item.downloadUrl"
                            target="_blank"
                            rel="noopener noreferrer"
                            class="text-xs text-blue-500 hover:text-blue-400 underline underline-offset-2"
                          >
                            {{ t('agents.execution.open_generated_asset') }}
                          </a>
                        </div>
                      </div>
                      <div v-if="item.summary.length > 0" class="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div v-for="entry in item.summary" :key="entry.key" class="rounded-lg border border-border/50 bg-muted/30 px-3 py-2">
                          <div class="text-[10px] uppercase tracking-wide text-muted-foreground">{{ entry.key }}</div>
                          <div class="mt-1 text-sm text-foreground break-all">{{ entry.value }}</div>
                        </div>
                      </div>
                      <details class="mt-4">
                        <summary class="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                          {{ t('agents.execution.view_raw_json') }}
                        </summary>
                        <pre class="mt-2 rounded-lg border border-border/50 bg-muted/40 p-3 text-xs overflow-x-auto whitespace-pre-wrap break-all">{{ item.rawJson }}</pre>
                      </details>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Vision annotated image bubble -->
              <div 
                v-else-if="item.type === 'vision_image'"
                class="flex gap-4 group mb-6 justify-start"
              >
                <div class="w-8 h-8 rounded-full flex items-center justify-center shrink-0 bg-blue-600 text-white">
                  <Bot class="w-4 h-4" />
                </div>
                <div class="flex-1 max-w-[85%]">
                  <div class="space-y-2 items-start">
                    <div class="flex items-center gap-2 text-xs text-muted-foreground">
                      <span class="font-medium capitalize">
                        {{ agent?.name || t('agents.execution.agent') }}
                      </span>
                      <span class="text-[10px] text-muted-foreground/70">{{ t('agents.execution.vision_annotated_image') }}</span>
                    </div>
                    <div class="rounded-2xl px-4 py-3 text-sm leading-relaxed border shadow-sm bg-card text-foreground/90 border-border/50">
                      <img :src="item.imageUrl" :alt="t('agents.execution.vision_preview_alt')" class="max-w-full max-h-96 object-contain rounded-lg" />
                      <div v-if="item.summary" class="mt-3 text-xs text-muted-foreground">
                        {{ item.summary }}
                      </div>
                      <div v-if="item.explanation" class="mt-2 text-sm text-foreground/90">
                        {{ item.explanation }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>

            <!-- Thinking Indicator -->
            <div v-if="isRunning" class="flex gap-4 ml-14 animate-pulse">
              <div class="flex items-center gap-3 text-muted-foreground text-sm font-medium">
                <MoreHorizontal class="w-5 h-5" />
                <span>{{ t('agents.execution.thinking') }}</span>
              </div>
            </div>
            </template>
          </template>
        </div>

        <!-- Input Bar -->
        <div class="p-6 bg-muted border-t border-border shadow-sm">
          <div class="max-w-4xl mx-auto space-y-3">
            <!-- File Preview (if files uploaded) -->
            <div v-if="uploadedFiles.length > 0" class="flex flex-wrap gap-2 pb-2">
              <div 
                v-for="(item, idx) in uploadedFiles" 
                :key="idx"
                class="group/file flex items-center gap-2 px-3 py-2 rounded-xl bg-card border border-border/50 hover:border-blue-500/50 text-xs text-foreground transition-all shadow-sm hover:shadow-md"
              >
                <FileText class="w-4 h-4 text-blue-500 shrink-0" />
                <span class="font-medium truncate max-w-[200px]">{{ item.file.name }}</span>
                <span class="text-muted-foreground shrink-0 text-[10px]">{{ t('agents.execution.file_size', { size: (item.file.size / 1024).toFixed(2) }) }}</span>
                <button
                  @click="removeFile(idx)"
                  class="ml-1 p-1 rounded-md hover:bg-red-500/10 text-muted-foreground hover:text-red-500 transition-colors shrink-0 opacity-0 group-hover/file:opacity-100"
                  :title="t('agents.execution.remove_file')"
                >
                  <X class="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
            
            <!-- Input with file upload button -->
            <div class="relative flex items-center gap-2">
              <Input 
                v-model="userInput"
                :placeholder="t('agents.execution.input_placeholder')" 
                class="h-14 pl-6 pr-24 bg-card border-border focus-visible:ring-blue-500 rounded-2xl text-base shadow-inner text-foreground flex-1"
                :disabled="isRunning"
              />
              
              <!-- File Upload Button (only show if agent supports file processing) -->
              <input
                v-if="supportsFileProcessing"
                ref="fileInputRef"
                type="file"
                multiple
                class="hidden"
                @change="handleFileSelect"
                :disabled="isRunning"
              />
              
              <Button
                v-if="supportsFileProcessing"
                @click="fileInputRef?.click()"
                :disabled="isRunning"
                variant="ghost"
                size="icon"
                class="absolute right-14 top-1/2 -translate-y-1/2 w-10 h-10 rounded-xl text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-all"
                :title="t('agents.execution.upload_file')"
              >
                <Upload class="w-5 h-5" />
              </Button>

              <Button
                @click="toggleVoiceInput"
                :disabled="isRunning || asrLoading"
                variant="ghost"
                size="icon"
                class="absolute right-24 top-1/2 -translate-y-1/2 w-10 h-10 rounded-xl text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-all"
                :title="isRecording ? t('chat.voice_stop') : asrLoading ? t('chat.voice_transcribing') : t('chat.voice_start')"
              >
                <Square v-if="isRecording" class="w-5 h-5 text-red-500" />
                <Mic v-else class="w-5 h-5" />
              </Button>
              
              <Button 
                @click="handleSendMessage"
                :disabled="isRunning || (!userInput.trim() && uploadedFiles.length === 0)"
                size="icon" 
                class="absolute right-2 top-1/2 -translate-y-1/2 w-10 h-10 rounded-xl bg-blue-600 hover:bg-blue-700 text-white shadow-lg shadow-blue-500/20 transition-all hover:scale-105 active:scale-95"
              >
                <Send class="w-5 h-5" />
              </Button>
            </div>
            <div v-if="asrError" class="text-xs text-destructive mt-2">
              {{ asrError }}
            </div>
            <div v-else-if="asrLoading" class="text-xs text-muted-foreground mt-2">
              {{ t('chat.voice_transcribing') }}
            </div>
          </div>
        </div>
      </main>

      <!-- Right Sidebar -->
      <aside class="w-80 bg-muted/50 flex flex-col overflow-y-auto custom-scrollbar border-l border-border/50 z-10">
        <div class="p-6 space-y-8">
          <!-- Execution Progress -->
          <section class="space-y-4 p-4 rounded-xl bg-card/50 border border-border/30">
            <div class="flex items-center justify-between">
              <h3 class="text-[11px] font-black text-muted-foreground uppercase tracking-[0.2em]">{{ t('agents.execution.progress') }}</h3>
              <span class="text-xs font-bold text-blue-500">{{ session?.step || 0 }}/{{ agent?.max_steps || 20 }}</span>
            </div>
            <div class="h-2 w-full bg-muted-foreground/10 rounded-full overflow-hidden shadow-inner">
              <div class="h-full bg-gradient-to-r from-blue-500 to-blue-600 transition-all duration-500 ease-out shadow-sm" :style="{ width: `${getStepProgress}%` }"></div>
            </div>
            <p class="text-xs text-muted-foreground leading-relaxed font-medium">
              {{ t('agents.execution.current_step') }}: <span class="text-foreground font-semibold">{{ currentStepDesc }}</span>
            </p>
            <Button
              variant="outline"
              class="w-full h-10 rounded-xl bg-card border-border/50 text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-all gap-2 text-xs font-bold shadow-sm hover:shadow-md"
              :disabled="!session?.session_id"
              @click="router.push({ name: 'agents-trace', params: { id: agentId }, query: { session: session?.session_id } })"
            >
              <History class="w-4 h-4" />
              {{ t('agents.execution.view_trace') }}
            </Button>
          </section>

          <!-- Model Configuration -->
          <section class="space-y-4 p-4 rounded-xl bg-card/50 border border-border/30">
            <h3 class="text-[11px] font-black text-muted-foreground uppercase tracking-[0.2em]">{{ t('agents.execution.model_config') }}</h3>
            <div class="space-y-2">
              <div class="flex items-center justify-between p-3 rounded-lg hover:bg-muted/50 transition-colors border border-transparent hover:border-border/30">
                <span class="text-xs text-muted-foreground font-medium">{{ t('agents.execution.provider') }}</span>
                <span class="text-xs font-bold text-foreground">{{ providerDisplay }}</span>
              </div>
              <div class="flex items-center justify-between p-3 rounded-lg hover:bg-muted/50 transition-colors border border-transparent hover:border-border/30">
                <span class="text-xs text-muted-foreground font-medium">{{ t('agents.execution.model') }}</span>
                <span class="text-xs font-bold text-foreground truncate max-w-[150px]" :title="agent?.model_id">{{ agent?.model_id || t('agents.execution.n_a') }}</span>
              </div>
              <div class="flex items-center justify-between p-3 rounded-lg hover:bg-muted/50 transition-colors border border-transparent hover:border-border/30">
                <span class="text-xs text-muted-foreground font-medium">{{ t('agents.execution.quant') }}</span>
                <Badge variant="secondary" class="bg-muted/50 text-foreground text-[10px] font-black px-2 py-0.5 border-none">{{ t('agents.execution.n_a') }}</Badge>
              </div>
            </div>
          </section>

          <!-- RAG Sources -->
          <section class="space-y-4 p-4 rounded-xl bg-card/50 border border-border/30">
            <h3 class="text-[11px] font-black text-muted-foreground uppercase tracking-[0.2em]">{{ t('agents.execution.rag_sources') }}</h3>
            <div class="flex flex-wrap gap-2">
              <div v-for="rag in agent?.rag_ids" :key="rag" 
                   class="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-[10px] font-bold text-emerald-600 dark:text-emerald-400 shadow-sm hover:bg-emerald-500/20 hover:border-emerald-500/50 transition-all cursor-default">
                <FileText class="w-3.5 h-3.5" />
                <span class="truncate max-w-[120px]">{{ rag }}</span>
              </div>
              <div v-if="!agent?.rag_ids?.length" class="text-xs text-muted-foreground/70 italic font-medium px-2 py-1">{{ t('agents.execution.no_rag_enabled') }}</div>
            </div>
          </section>

          <!-- Capabilities -->
          <section class="space-y-4 p-4 rounded-xl bg-card/50 border border-border/30">
            <h3 class="text-[11px] font-black text-muted-foreground uppercase tracking-[0.2em]">{{ t('agents.execution.capabilities') }}</h3>
            <div class="space-y-3">
              <div v-for="tool in capabilityDisplayList" :key="tool" class="flex items-center gap-3 group p-2 rounded-lg hover:bg-muted/30 transition-colors">
                <div class="w-8 h-8 rounded-lg bg-card border border-border/50 flex items-center justify-center text-muted-foreground group-hover:bg-blue-500/10 group-hover:text-blue-500 group-hover:border-blue-500/30 transition-all shadow-sm">
                  <Globe v-if="tool === 'web-search' || tool === 'web.search'" class="w-4 h-4" />
                  <Code2 v-else-if="tool === 'python-interpreter' || tool === 'python.run'" class="w-4 h-4" />
                  <Database v-else-if="tool === 'sql-engine' || tool === 'sql.query'" class="w-4 h-4" />
                  <FileText v-else-if="tool === 'file.read' || tool === 'file.list' || tool === 'content-gen'" class="w-4 h-4" />
                  <Terminal v-else-if="tool === 'terminal'" class="w-4 h-4" />
                  <SearchCode v-else-if="tool === 'audit' || tool === 'scanner'" class="w-4 h-4" />
                  <Activity v-else-if="tool === 'metrics'" class="w-4 h-4" />
                  <Wrench v-else class="w-4 h-4" />
                </div>
                <span class="text-xs font-semibold text-muted-foreground group-hover:text-foreground transition-colors">{{ getToolName(tool) }}</span>
              </div>
            </div>
          </section>

          <!-- Debug Event Stream -->
          <section class="space-y-2 rounded-xl bg-card/50 border border-border/30 overflow-hidden">
            <EventStreamViewer :kernel-instance-id="session?.kernel_instance_id" />
          </section>
        </div>
      </aside>
    </div>

    <!-- Footer -->
    <footer class="h-10 border-t border-border bg-muted px-6 flex items-center justify-between shrink-0 text-[10px] font-bold tracking-tight uppercase shadow-sm z-10">
      <div class="flex items-center gap-6">
        <div class="flex items-center gap-2">
          <div class="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]"></div>
          <span class="text-muted-foreground font-black">{{ t('agents.execution.status.active') }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-muted-foreground/60">{{ t('agents.execution.status.session') }}:</span>
          <span class="text-foreground font-black">{{ session?.session_id || t('agents.execution.n_a') }}</span>
        </div>
      </div>
      <div class="flex items-center gap-6">
        <div class="flex items-center gap-2">
          <Zap class="w-3.5 h-3.5 text-blue-500" />
          <span class="text-muted-foreground">{{ t('agents.execution.status.latency') }}: <span class="text-foreground ml-1">{{ latencyDisplay }}</span></span>
        </div>
        <div class="flex items-center gap-2">
          <Coins class="w-3.5 h-3.5 text-blue-500" />
          <span class="text-muted-foreground">{{ t('agents.execution.status.tokens') }}: <span class="text-foreground ml-1">{{ tokensDisplay }}</span></span>
        </div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 5px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.25);
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.4);
}

/* Markdown content styling */
:deep(.prose) {
  color: inherit;
}

:deep(.prose pre) {
  background: hsl(var(--muted)) !important;
  border: 1px solid hsl(var(--border));
  border-radius: 0.5rem;
  padding: 1rem;
  overflow-x: auto;
}

:deep(.prose code) {
  background: hsl(var(--primary) / 0.15) !important;
  color: hsl(var(--primary));
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
  font-size: 0.875em;
}

:deep(.prose pre code) {
  background: transparent !important;
  color: inherit !important;
  padding: 0;
}

:deep(.prose h1, .prose h2, .prose h3, .prose h4, .prose h5, .prose h6) {
  color: inherit;
  margin-top: 1.5em;
  margin-bottom: 0.5em;
}

:deep(.prose p) {
  margin-top: 0.75em;
  margin-bottom: 0.75em;
}

:deep(.prose ul, .prose ol) {
  margin-top: 0.75em;
  margin-bottom: 0.75em;
  padding-left: 1.5em;
}

:deep(.prose a) {
  color: hsl(217 91% 60%);
  text-decoration: underline;
}

:deep(.prose a:hover) {
  color: hsl(217 91% 65%);
}

:deep(.prose blockquote) {
  border-left: 4px solid hsl(var(--border));
  padding-left: 1em;
  margin-left: 0;
  color: hsl(var(--muted-foreground));
}
/* Agent run: scale images proportionally (no re-encode) */
::deep(.prose img) {
  max-width: 384px;
  height: auto;
  display: block;
}
</style>
