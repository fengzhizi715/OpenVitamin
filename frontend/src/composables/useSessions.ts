import { computed, ref, watch } from 'vue'
import {
  deleteSession,
  getSessionId,
  listSessionMessages,
  listSessions,
  renameSession,
  requestNewSessionOnNextChat,
  setSessionId,
  type Session,
  type SessionMessage,
} from '@/services/api'

export interface ChatMessageForUI {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  modelName?: string
  loading?: boolean
  meta?: Record<string, unknown> | null
  params?: {
    temperature: number
    top_p: number
    max_tokens: number
    system_prompt?: string
  }
  attachments?: Array<{
    type: 'image'
    url: string
  }>
}

// module-singleton state（在多组件间共享）
const sessions = ref<Session[]>([])
const activeSessionId = ref<string | null>(getSessionId())
const sessionsLoading = ref(false)
const sessionsError = ref<string | null>(null)

function parseTimestamp(ts: string): number {
  const t = Date.parse(ts)
  return Number.isFinite(t) ? t : Date.now()
}

function normalizeMessageContent(content: unknown): string {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content
    .filter((item: any) => item?.type === 'text' && typeof item.text === 'string')
    .map((item: any) => item.text as string)
    .join('\n')
    .trim()
}

function extractAttachmentsFromContent(content: unknown): Array<{type: 'image', url: string}> {
  if (!Array.isArray(content)) return []
  return content
    .filter((item: any) => item?.type === 'image_url' && typeof item.image_url?.url === 'string')
    .map((item: any) => ({
      type: 'image' as const,
      url: item.image_url!.url,
    }))
}

function mapMessagesToUI(messages: SessionMessage[]): ChatMessageForUI[] {
  return messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map((m) => {
      // 显式断言 meta 的类型
      const meta = m.meta as any;
      
      // 从 meta 中提取附件信息
      let attachments: Array<{type: 'image', url: string}> | undefined;
      if (meta?.attachments) {
        attachments = meta.attachments.map((att: any) => ({
          type: att.type,
          url: att.url
        }));
      }
      // 兼容旧/多模态历史：附件可能在 content 数组里
      const rawContent: unknown = (m as any).content
      if (!attachments || attachments.length === 0) {
        const fromContent = extractAttachmentsFromContent(rawContent)
        if (fromContent.length > 0) attachments = fromContent
      }
      
      return {
        id: m.id,
        role: m.role as 'user' | 'assistant',
        content: normalizeMessageContent(rawContent),
        timestamp: parseTimestamp(m.created_at),
        modelName: m.model ?? undefined,
        loading: false,
        meta: (m.meta as any) ?? null,
        params: meta?.params,
        attachments
      };
    })
}

export function useSessions() {
  const currentSession = computed(() => sessions.value.find((s) => s.id === activeSessionId.value) || null)

  async function refreshSessions(limit: number = 50) {
    sessionsLoading.value = true
    sessionsError.value = null
    try {
      const res = await listSessions(limit)
      sessions.value = res.data || []
    } catch (e) {
      sessionsError.value = e instanceof Error ? e.message : String(e)
    } finally {
      sessionsLoading.value = false
    }
  }

  async function selectSession(sessionId: string) {
    setSessionId(sessionId)
    activeSessionId.value = sessionId
  }

  function newChat() {
    // 清空 session，让后端在下一次 chat 请求中自动创建
    requestNewSessionOnNextChat()
    setSessionId(null)
    activeSessionId.value = null
  }

  async function loadActiveSessionMessages(limit: number = 200): Promise<ChatMessageForUI[]> {
    const sid = activeSessionId.value
    if (!sid) return []
    const res = await listSessionMessages(sid, limit)
    return mapMessagesToUI(res.data || [])
  }

  async function removeSession(sessionId: string) {
    await deleteSession(sessionId)
    if (activeSessionId.value === sessionId) {
      newChat()
    }
    await refreshSessions()
  }

  async function updateSessionTitle(sessionId: string, title: string) {
    await renameSession(sessionId, title)
    // Update local session list
    const session = sessions.value.find((s) => s.id === sessionId)
    if (session) {
      session.title = title
    }
  }

  // 如果 apiFetch 捕获到了新的 session id（后端自动创建），同步到 activeSessionId
  watch(
    () => getSessionId(),
    (sid) => {
      if (sid && sid !== activeSessionId.value) {
        activeSessionId.value = sid
      }
    }
  )

  return {
    sessions,
    activeSessionId,
    currentSession,
    sessionsLoading,
    sessionsError,
    refreshSessions,
    selectSession,
    newChat,
    loadActiveSessionMessages,
    removeSession,
    updateSessionTitle,
  }
}

