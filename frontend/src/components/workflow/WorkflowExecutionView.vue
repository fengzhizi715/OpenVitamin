<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Play, Square, RotateCcw, Loader2, Network, RefreshCw, ListTree, Rows3 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  cancelWorkflowExecution,
  getWorkflow,
  getWorkflowVersion,
  getWorkflowExecution,
  getWorkflowExecutionStatus,
  listWorkflowExecutions,
  reconcileWorkflowExecution,
  runWorkflow,
  streamWorkflowExecutionStatus,
  type WorkflowExecutionStatusRecord,
  type WorkflowExecutionRecord,
  type WorkflowRecord,
} from '@/services/api'
import { normalizeExecutionStatus, normalizeNodeStatus, statusBadgeClass } from './status'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const workflowId = route.params.id as string

const workflow = ref<WorkflowRecord | null>(null)
const currentExecution = ref<WorkflowExecutionRecord | null>(null)
const loading = ref(false)
const logs = ref<string[]>([])
const runError = ref<string | null>(null)
const selectedNodeId = ref<string>('')
const viewMode = ref<'graph' | 'timeline' | 'list' | 'delivery'>('timeline')
/** 调试用：同步等待执行完成（可能超时，仅建议调试时使用） */
const waitForCompletion = ref(false)
let pollTimer: number | null = null
let elapsedTimer: number | null = null
let streamStop: (() => void) | null = null
let pollInFlight = false
let pollTick = 0
let streamTick = 0
let lastAutoReconcileAt = 0
const logContainerRef = ref<HTMLElement | null>(null)
const seenLogKeys = new Set<string>()
const autoStartAttempted = ref(false)
const reconcileInProgress = ref(false)
const nodeMetaMap = ref<Record<string, { name: string; type: string; agentName?: string }>>({})
const runStartInFlight = ref(false)
const currentRunIdempotencyKey = ref<string | null>(null)
let fastPollUntilMs = 0
const elapsedNowMs = ref(Date.now())

function isExecutionActive(exec: WorkflowExecutionRecord | null | undefined): boolean {
  const state = normalizeExecutionStatus(exec?.state)
  if (state === 'running' || state === 'queued') return true
  if (state !== 'pending') return false
  // pending 只在短时间内视为“正在运行”；陈旧 pending 允许用户直接重新启动。
  const created = exec?.created_at ? new Date(exec.created_at).getTime() : NaN
  if (Number.isNaN(created)) return false
  return Date.now() - created <= 15000
}

const isRunning = computed(() => {
  return isExecutionActive(currentExecution.value)
})

const nodeStates = computed<any[]>(() => currentExecution.value?.node_states || [])

/** 以 node_timeline 为单一数据源（有则用，无则回退 node_states），减少多来源状态歧义 */
const nodeTimeline = computed<any[]>(() => {
  const exec = currentExecution.value
  const timeline = exec?.node_timeline
  if (timeline && timeline.length > 0) return timeline
  return nodeStates.value
})

/** Inspector 以 node_timeline 为状态源，与 node_states 合并取 input/output/error，与 Timeline 一致 */
const selectedNode = computed<any | null>(() => {
  if (!selectedNodeId.value) return null
  const fromTimeline = nodeTimeline.value.find((n) => n.node_id === selectedNodeId.value)
  const fromStates = nodeStates.value.find((n) => n.node_id === selectedNodeId.value)
  if (!fromTimeline && !fromStates) return null
  return {
    node_id: selectedNodeId.value,
    state: fromTimeline?.state ?? fromStates?.state ?? 'pending',
    started_at: fromTimeline?.started_at ?? fromStates?.started_at ?? null,
    finished_at: fromTimeline?.finished_at ?? fromStates?.finished_at ?? null,
    retry_count: fromTimeline?.retry_count ?? fromStates?.retry_count ?? 0,
    error_message: fromTimeline?.error_message ?? fromStates?.error_message ?? null,
    input_data: fromStates?.input_data,
    output_data: fromStates?.output_data,
    error_details: fromStates?.error_details,
  }
})

const executionElapsedMs = computed(() => {
  const exec = currentExecution.value
  if (!exec) return 0
  if (typeof exec.duration_ms === 'number' && Number.isFinite(exec.duration_ms) && exec.duration_ms >= 0) {
    return exec.duration_ms
  }
  if (!exec.started_at) return 0
  const start = parseServerTime(exec.started_at)
  const end = exec.finished_at ? parseServerTime(exec.finished_at) : elapsedNowMs.value
  if (Number.isNaN(start) || Number.isNaN(end)) return 0
  return Math.max(0, Math.min(end - start, 24 * 60 * 60 * 1000))
})

const timelineRows = computed(() => {
  const rows = [...nodeTimeline.value]
  const getStart = (n: any) => (n.started_at ? new Date(n.started_at).getTime() : Number.MAX_SAFE_INTEGER)
  rows.sort((a, b) => getStart(a) - getStart(b))
  return rows
})

const timelineBounds = computed(() => {
  const rows = timelineRows.value
  if (!rows.length) return { min: 0, max: 1 }
  const starts = rows
    .map((n: any) => (n.started_at ? new Date(n.started_at).getTime() : NaN))
    .filter((v: number) => !Number.isNaN(v))
  const ends = rows
    .map((n: any) => {
      if (n.finished_at) return new Date(n.finished_at).getTime()
      if (n.started_at) return Date.now()
      return NaN
    })
    .filter((v: number) => !Number.isNaN(v))
  const min = starts.length ? Math.min(...starts) : Date.now()
  const max = Math.max(min + 1, ...(ends.length ? ends : [min + 1]))
  return { min, max }
})

/** 与 Timeline 同源：用 node_timeline 统计，避免与列表/Inspector 短时不一致 */
const executionSummary = computed(() => {
  const nodes = nodeTimeline.value
  const completed = nodes.filter((n) => normalizeNodeStatus(n.state) === 'succeeded').length
  const failed = nodes.filter((n) => normalizeNodeStatus(n.state) === 'failed').length
  return { total: nodes.length, completed, failed }
})

const deliveryData = computed(() => {
  const out = currentExecution.value?.output_data
  if (!out || typeof out !== 'object') {
    return {
      finalText: '',
      artifacts: [] as string[],
      payload: out ?? null,
    }
  }
  const obj = out as Record<string, unknown>
  const finalText =
    (typeof obj.final_answer === 'string' && obj.final_answer) ||
    (typeof obj.response === 'string' && obj.response) ||
    (typeof obj.summary === 'string' && obj.summary) ||
    ''

  const artifactCandidates: unknown[] = []
  if (Array.isArray(obj.files_created)) artifactCandidates.push(...obj.files_created)
  if (Array.isArray(obj.output_files)) artifactCandidates.push(...obj.output_files)
  if (Array.isArray(obj.artifacts)) artifactCandidates.push(...obj.artifacts)

  const artifacts = artifactCandidates
    .map((x) => {
      if (typeof x === 'string') return x
      if (x && typeof x === 'object') {
        const p = (x as Record<string, unknown>).path
        return typeof p === 'string' ? p : ''
      }
      return ''
    })
    .filter(Boolean)

  return { finalText, artifacts, payload: obj }
})

function formatExecutionRunError(message: string): string {
  const lower = message.toLowerCase()
  if (
    lower.includes('published') ||
    lower.includes('draft') ||
    (lower.includes('version') && (lower.includes('not allowed') || lower.includes('required')))
  ) {
    return t('workflow_run.require_published')
  }
  return message
}

function goBack() {
  router.push({ name: 'workflow-detail', params: { id: workflowId } })
}

function prettyJson(value: unknown): string {
  if (value == null) return 'null'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function parseServerTime(v: string | null | undefined): number {
  if (!v) return NaN
  const s = String(v).trim()
  // 后端常返回无时区 ISO（UTC 语义），前端补 Z 按 UTC 解析，避免 +8h 偏移。
  const normalized = /([zZ]|[+-]\d{2}:\d{2})$/.test(s) ? s : `${s}Z`
  const ts = new Date(normalized).getTime()
  return Number.isNaN(ts) ? new Date(s).getTime() : ts
}

function displayNodeName(nodeId: string): string {
  const meta = nodeMetaMap.value[nodeId]
  if (meta?.type === 'agent' && meta?.agentName) return meta.agentName
  if (meta?.name) return meta.name
  if (nodeId === 'start') return t('workflow_run.start_node')
  if (nodeId === 'end') return t('workflow_run.end_node')
  return nodeId
}

function displayNodeSubtitle(nodeId: string): string {
  const meta = nodeMetaMap.value[nodeId]
  if (meta?.type) return `${meta.type} · ${nodeId}`
  return nodeId
}

/** List/Inspector 的 output 仍从 node_states 取（事件流无 payload），状态与 Timeline 同源 */
function getNodeOutputData(nodeId: string): unknown {
  const n = nodeStates.value.find((x) => x.node_id === nodeId)
  return n?.output_data
}

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function formatLocalLogTime(rawTs?: string | null): string {
  const baseMs = rawTs ? parseServerTime(rawTs) : Date.now()
  const d = new Date(Number.isNaN(baseMs) ? Date.now() : baseMs)
  const pad = (n: number, len = 2) => String(n).padStart(len, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}

function pushLog(line: string, dedupeKey?: string) {
  const key = dedupeKey || line
  if (seenLogKeys.has(key)) return
  seenLogKeys.add(key)
  logs.value.push(line)
  if (logs.value.length > 300) logs.value = logs.value.slice(-300)
  void nextTick(() => {
    const el = logContainerRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function nodeLogSignature(n: any): string {
  return `${normalizeNodeStatus(n?.state)}|${intOrZero(n?.retry_count)}|${String(n?.error_message || '')}`
}

function intOrZero(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0
}

function appendExecutionLogDiff(prevExec: WorkflowExecutionRecord | null, nextExec: WorkflowExecutionRecord, source: string) {
  const prevState = normalizeExecutionStatus(prevExec?.state)
  const nextState = normalizeExecutionStatus(nextExec?.state)
  if (!prevExec || prevState !== nextState) {
    const ts = formatLocalLogTime(nextExec.finished_at || nextExec.started_at || nextExec.created_at)
    const line = `[${ts}] Execution ${nextExec.execution_id}: ${nextState.toUpperCase()}`
    pushLog(line, `exec|${nextExec.execution_id}|${nextState}|${source}`)
  }

  const prevNodes = (prevExec?.node_timeline?.length ? prevExec.node_timeline : prevExec?.node_states) || []
  const nextNodes = (nextExec.node_timeline?.length ? nextExec.node_timeline : nextExec.node_states) || []
  const prevMap = new Map<string, string>()
  for (const n of prevNodes) {
    prevMap.set(n.node_id, nodeLogSignature(n))
  }
  for (const n of nextNodes) {
    const currSig = nodeLogSignature(n)
    if (prevMap.get(n.node_id) === currSig) continue
    const state = normalizeNodeStatus(n.state)
    const retry = intOrZero((n as any).retry_count)
    const retrySuffix = retry > 0 ? ` retry=${retry}` : ''
    const errSuffix = n.error_message ? ` (${n.error_message})` : ''
    const ts = formatLocalLogTime((n as any).finished_at || (n as any).started_at || nextExec.started_at || nextExec.created_at)
    const line = `[${ts}] Node "${n.node_id}": ${state}${retrySuffix}${errSuffix}`
    pushLog(line, `node|${nextExec.execution_id}|${n.node_id}|${currSig}|${source}`)
  }
}

function isTerminalState(state: string): boolean {
  return ['succeeded', 'failed', 'cancelled', 'timeout'].includes(normalizeExecutionStatus(state))
}

function ensureSelectedNode() {
  if (!selectedNodeId.value && nodeStates.value.length > 0) {
    selectedNodeId.value = nodeStates.value[0].node_id
  }
  if (selectedNodeId.value && !nodeStates.value.some((n) => n.node_id === selectedNodeId.value)) {
    selectedNodeId.value = nodeStates.value[0]?.node_id || ''
  }
}

function timelineTrackStyle(node: any) {
  const { min, max } = timelineBounds.value
  const span = Math.max(1, max - min)
  const hasTiming = !!(node.started_at || node.finished_at)
  const start = node.started_at ? new Date(node.started_at).getTime() : min
  const end = node.finished_at ? new Date(node.finished_at).getTime() : (node.started_at ? Date.now() : min)
  if (!hasTiming) {
    return {
      left: '0%',
      width: '0%',
      opacity: '0',
    }
  }
  const left = ((start - min) / span) * 100
  const width = Math.max(2, ((Math.max(start + 1, end) - start) / span) * 100)
  return {
    left: `${Math.min(98, Math.max(0, left))}%`,
    width: `${Math.min(100, Math.max(2, width))}%`,
  }
}

function nodeTrackClass(state: string) {
  const s = normalizeNodeStatus(state)
  if (s === 'succeeded') return 'bg-emerald-500/35 border-emerald-400/80'
  if (s === 'failed') return 'bg-red-500/35 border-red-400/90'
  if (s === 'running' || s === 'pending' || s === 'queued') return 'bg-blue-500/35 border-blue-400/90'
  return 'bg-slate-600/30 border-slate-400/60'
}

function nodeTrackAnimClass(state: string) {
  const s = normalizeNodeStatus(state)
  if (s === 'running' || s === 'pending' || s === 'queued') return 'timeline-track-running'
  return ''
}

function isNodeRunning(n: { state?: string | null; started_at?: string | null; finished_at?: string | null }) {
  const s = normalizeNodeStatus(n.state || '')
  if (!isExecutionActive(currentExecution.value)) return false
  if (s === 'running') return true
  if (s === 'succeeded' || s === 'failed' || s === 'cancelled' || s === 'timeout' || s === 'idle') return false
  // 兼容状态回填顺序差异：仅在执行整体仍 active 时，把“已开始未结束”的 pending/queued 视作运行中
  return Boolean((s === 'pending' || s === 'queued') && n.started_at && !n.finished_at)
}

async function loadWorkflowMeta() {
  workflow.value = await getWorkflow(workflowId)
  const baseVersionId = workflow.value?.published_version_id || workflow.value?.latest_version_id
  if (!baseVersionId) {
    nodeMetaMap.value = {}
    return
  }
  try {
    const version = await getWorkflowVersion(workflowId, baseVersionId)
    const map: Record<string, { name: string; type: string; agentName?: string }> = {}
    for (const n of version?.dag?.nodes || []) {
      const cfg = (n.config || {}) as Record<string, unknown>
      const nodeId = String(n.id || '').trim()
      if (!nodeId) continue
      const agentName =
        n.type === 'agent'
          ? (String(cfg.agent_display_name || cfg.agent_id || '').trim() || undefined)
          : undefined
      map[nodeId] = { name: n.name || nodeId, type: n.type || 'node' }
      if (agentName) map[nodeId].agentName = agentName
    }
    nodeMetaMap.value = map
  } catch {
    nodeMetaMap.value = {}
  }
}

async function loadLatestExecution() {
  const res = await listWorkflowExecutions(workflowId, { limit: 10, offset: 0 })
  const latest = (res.items || [])[0]
  if (!latest) return
  const full = await getWorkflowExecution(workflowId, latest.execution_id)
  appendExecutionLogDiff(currentExecution.value, full, 'load_latest')
  currentExecution.value = full
  ensureSelectedNode()
}

async function loadExecutionById(executionId: string) {
  const full = await getWorkflowExecution(workflowId, executionId)
  appendExecutionLogDiff(currentExecution.value, full, 'load_by_id')
  currentExecution.value = full
  ensureSelectedNode()
}

async function refreshCurrentExecution() {
  if (!currentExecution.value?.execution_id) return
  const executionId = currentExecution.value.execution_id
  const prev = currentExecution.value
  const status = await getWorkflowExecutionStatus(workflowId, executionId)
  await applyExecutionStatusPayload(status, 'poll_status')
  const merged = currentExecution.value || prev

  // 若节点已出现终态失败，但 execution 总状态仍是 active，主动触发一次 reconcile 读取，减少前端状态滞后。
  const activeExec = ['pending', 'queued', 'running'].includes(normalizeExecutionStatus(merged.state))
  const hasTerminalFailedNode = (merged.node_timeline || []).some((n: any) => {
    const s = normalizeNodeStatus(n?.state)
    return s === 'failed' || s === 'timeout' || s === 'cancelled'
  })
  const now = Date.now()
  if (activeExec && hasTerminalFailedNode && now - lastAutoReconcileAt > 1500) {
    lastAutoReconcileAt = now
    try {
      const reconciled = await getWorkflowExecution(workflowId, executionId, { reconcile: true })
      appendExecutionLogDiff(currentExecution.value, reconciled, 'auto_reconcile')
      currentExecution.value = reconciled
      ensureSelectedNode()
    } catch {
      // ignore reconcile read errors; regular polling will continue
    }
  }

  pollTick += 1
  // 低频拉全量详情，保持 inspector/output_data 与轻量状态同步
  if (pollTick % 5 === 0 || isTerminalState(status.state)) {
    const latest = await getWorkflowExecution(workflowId, executionId)
    appendExecutionLogDiff(currentExecution.value, latest, 'poll_detail')
    currentExecution.value = latest
    ensureSelectedNode()
  }
}

function stopPolling() {
  if (pollTimer != null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function stopStatusStream() {
  if (streamStop) {
    streamStop()
    streamStop = null
  }
}

function nextPollDelayMs(): number {
  if (Date.now() < fastPollUntilMs) return 500
  const state = normalizeExecutionStatus(currentExecution.value?.state)
  let base = 2000
  if (state === 'running') base = 1200
  else if (state === 'queued' || state === 'pending') base = 2500
  else return 0
  if (document.hidden) base = Math.min(8000, base * 3)
  return base
}

function schedulePolling(delayMs: number) {
  if (pollTimer != null) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(async () => {
    if (pollInFlight) {
      schedulePolling(nextPollDelayMs() || 2500)
      return
    }
    pollInFlight = true
    try {
      await refreshCurrentExecution()
    } catch {
      schedulePolling(3000)
      return
    } finally {
      pollInFlight = false
    }
    const next = nextPollDelayMs()
    if (next > 0) {
      schedulePolling(next)
    } else {
      stopPolling()
    }
  }, Math.max(0, delayMs))
}

function ensurePolling() {
  if (pollTimer != null) return
  const delay = nextPollDelayMs()
  if (delay <= 0) return
  schedulePolling(0)
}

async function applyExecutionStatusPayload(status: WorkflowExecutionStatusRecord, source: string) {
  const prev = currentExecution.value
  if (!prev || prev.execution_id !== status.execution_id) return
  const merged = {
    ...prev,
    state: status.state,
    started_at: status.started_at ?? prev.started_at,
    finished_at: status.finished_at ?? prev.finished_at,
    duration_ms: status.duration_ms ?? prev.duration_ms,
    queue_position: status.queue_position ?? prev.queue_position,
    wait_duration_ms: status.wait_duration_ms ?? prev.wait_duration_ms,
    node_timeline: status.node_timeline || [],
  }
  appendExecutionLogDiff(prev, merged, source)
  currentExecution.value = merged
  ensureSelectedNode()
}

function startStatusStream(executionId: string) {
  stopStatusStream()
  streamTick = 0
  streamStop = streamWorkflowExecutionStatus(
    workflowId,
    executionId,
    {
      onStatus: (payload) => {
        void applyExecutionStatusPayload(payload, 'sse_status')
        streamTick += 1
        if (streamTick % 8 === 0) {
          void (async () => {
            try {
              const latest = await getWorkflowExecution(workflowId, executionId)
              appendExecutionLogDiff(currentExecution.value, latest, 'sse_detail')
              currentExecution.value = latest
              ensureSelectedNode()
            } catch {
              // ignore periodic full-detail sync errors
            }
          })()
        }
      },
      onTerminal: () => {
        stopStatusStream()
        stopPolling()
        void (async () => {
          try {
            const latest = await getWorkflowExecution(workflowId, executionId)
            appendExecutionLogDiff(currentExecution.value, latest, 'sse_terminal')
            currentExecution.value = latest
            ensureSelectedNode()
          } catch {
            // ignore terminal full-sync errors
          }
        })()
      },
      onError: () => {
        stopStatusStream()
        ensurePolling()
      },
    },
    { intervalMs: 900 }
  )
}

async function startExecution() {
  if (runStartInFlight.value || loading.value) return
  runError.value = null
  loading.value = true
  runStartInFlight.value = true
  pollTick = 0
  fastPollUntilMs = Date.now() + 2000
  try {
    currentRunIdempotencyKey.value =
      currentRunIdempotencyKey.value ||
      (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `wf-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`)
    const exec = await runWorkflow(workflowId, {}, waitForCompletion.value, currentRunIdempotencyKey.value)
    // 以 runWorkflow 返回的 execution_id 为唯一真源，避免并发场景绑定到错误的 run。
    const full = await getWorkflowExecution(workflowId, exec.execution_id)
    appendExecutionLogDiff(currentExecution.value, full, 'start')
    currentExecution.value = full
    // 将 URL 绑定到本次 execution，避免页面刷新后回到旧运行上下文。
    void router.replace({
      name: 'workflow-run',
      params: { id: workflowId },
      query: { execution_id: full.execution_id },
    })
    ensureSelectedNode()
    stopPolling()
    startStatusStream(full.execution_id)
    ensurePolling()
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    runError.value = formatExecutionRunError(msg)
  } finally {
    currentRunIdempotencyKey.value = null
    runStartInFlight.value = false
    loading.value = false
  }
}

async function stopExecution() {
  if (!currentExecution.value?.execution_id) return
  runError.value = null
  loading.value = true
  try {
    const updated = await cancelWorkflowExecution(workflowId, currentExecution.value.execution_id)
    appendExecutionLogDiff(currentExecution.value, updated, 'stop')
    currentExecution.value = updated
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e)
    throw e
  } finally {
    loading.value = false
  }
}

async function restartExecution() {
  logs.value = []
  seenLogKeys.clear()
  if (isRunning.value) {
    try {
      await stopExecution()
    } catch (e) {
      // cancel 失败不阻断新的 run 请求（例如旧 execution 已失效或状态不一致）。
      runError.value = e instanceof Error ? e.message : String(e)
    }
  }
  await startExecution()
}

async function doReconcile() {
  const exec = currentExecution.value
  if (!exec?.execution_id) return
  reconcileInProgress.value = true
  runError.value = null
  try {
    const updated = await reconcileWorkflowExecution(workflowId, exec.execution_id)
    appendExecutionLogDiff(currentExecution.value, updated, 'reconcile')
    currentExecution.value = updated
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e)
  } finally {
    reconcileInProgress.value = false
  }
}

onMounted(async () => {
  elapsedTimer = window.setInterval(() => {
    elapsedNowMs.value = Date.now()
  }, 1000)

  loading.value = true
  const requestedExecutionId = String(route.query.execution_id || route.query.executionId || '').trim()
  const autoStartRequested =
    String(route.query.auto_start || route.query.autorun || '').trim() === '1'
  try {
    await loadWorkflowMeta()
    if (requestedExecutionId) {
      await loadExecutionById(requestedExecutionId)
      try {
        await refreshCurrentExecution()
      } catch {
        // ignore first status refresh error; polling will recover
      }
    } else {
      await loadLatestExecution()
    }
    if (currentExecution.value?.execution_id && isExecutionActive(currentExecution.value)) {
      startStatusStream(currentExecution.value.execution_id)
      ensurePolling()
    }
  } finally {
    loading.value = false
  }

  // 从详情页点击 Run 进入时，显式触发一次新运行。
  if (autoStartRequested && !autoStartAttempted.value) {
    autoStartAttempted.value = true
    await startExecution()
    return
  }

  // 兼容：直接进入 Run 页且当前没有活跃执行时，自动触发一次运行。
  if (!requestedExecutionId && !autoStartAttempted.value && !isExecutionActive(currentExecution.value)) {
    autoStartAttempted.value = true
    await startExecution()
  }
})

onUnmounted(() => {
  if (elapsedTimer != null) {
    window.clearInterval(elapsedTimer)
    elapsedTimer = null
  }
  stopStatusStream()
  stopPolling()
})
</script>

<template>
  <div class="workflow-exec-root h-full flex flex-col text-slate-100">
    <header class="exec-topbar border-b border-slate-800/80 px-4 py-3">
      <div class="flex items-center gap-3">
        <Button type="button" variant="ghost" size="icon" class="text-slate-200 hover:text-white" @click="goBack">
          <ArrowLeft class="w-5 h-5" />
        </Button>
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <h1 class="text-lg font-semibold truncate">{{ workflow?.name || t('workflow_run.title_default') }}</h1>
            <Badge variant="secondary" :class="statusBadgeClass(normalizeExecutionStatus(currentExecution?.state))">
              {{ normalizeExecutionStatus(currentExecution?.state).toUpperCase() }}
            </Badge>
          </div>
          <div class="text-xs text-slate-400 mt-0.5">
            {{ t('workflow_run.run_id') }}: {{ currentExecution?.execution_id || '-' }}
          </div>
        </div>
        <div class="ml-auto flex items-center gap-2">
          <div class="inline-flex rounded-lg border border-slate-700 bg-slate-900/70 p-1">
              <button class="exec-tab" :class="viewMode === 'graph' ? 'exec-tab-active' : ''" @click="viewMode = 'graph'">
                <Network class="w-3.5 h-3.5 mr-1" /> {{ t('workflow_run.graph') }}
              </button>
              <button class="exec-tab" :class="viewMode === 'timeline' ? 'exec-tab-active' : ''" @click="viewMode = 'timeline'">
                <Rows3 class="w-3.5 h-3.5 mr-1" /> {{ t('workflow_run.timeline') }}
              </button>
              <button class="exec-tab" :class="viewMode === 'list' ? 'exec-tab-active' : ''" @click="viewMode = 'list'">
                <ListTree class="w-3.5 h-3.5 mr-1" /> {{ t('workflow_run.list') }}
              </button>
              <button class="exec-tab" :class="viewMode === 'delivery' ? 'exec-tab-active' : ''" @click="viewMode = 'delivery'">
                {{ t('workflow_run.delivery') }}
              </button>
            </div>
            <div class="px-3 py-1 rounded-lg border border-slate-700 bg-slate-900/70 text-xs">
            <div class="text-slate-400">{{ t('workflow_run.elapsed') }}</div>
            <div class="font-semibold">{{ formatElapsed(executionElapsedMs) }}</div>
          </div>
          <label v-if="!isRunning" class="inline-flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" v-model="waitForCompletion" class="h-3.5 w-3.5 rounded border-slate-600" />
            <span>{{ t('workflow_run.debug_wait') }}</span>
          </label>
          <Button type="button" v-if="!isRunning" class="gap-2 bg-blue-600 hover:bg-blue-700" :disabled="loading" @click="startExecution">
            <Play class="w-4 h-4" /> {{ t('workflow_run.start') }}
          </Button>
          <Button type="button" v-else variant="destructive" class="gap-2" :disabled="loading" @click="stopExecution">
            <Square class="w-4 h-4" /> {{ t('workflow_run.stop') }}
          </Button>
          <Button type="button" variant="outline" class="gap-2 border-slate-700 bg-slate-900/60" :disabled="loading" @click="restartExecution">
            <RotateCcw class="w-4 h-4" /> {{ t('workflow_run.rerun') }}
          </Button>
          <Button
            type="button"
            variant="outline"
            class="gap-2 border-slate-700 bg-slate-900/60"
            :disabled="loading || reconcileInProgress"
            :title="t('workflow_run.reconcile_tooltip')"
            @click="doReconcile"
          >
            <Loader2 v-if="reconcileInProgress" class="w-4 h-4 animate-spin" />
            <RefreshCw v-else class="w-4 h-4" />
            <span>{{ t('workflow_run.reconcile') }}</span>
          </Button>
        </div>
      </div>
      <div v-if="waitForCompletion" class="mt-3 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
        {{ t('workflow_run.wait_hint') }}
      </div>
      <div v-if="runError" class="mt-3 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
        {{ runError }}
      </div>
    </header>

    <main class="flex-1 min-h-0 grid grid-cols-[260px_1fr_320px]">
      <aside class="border-r border-slate-800/80 min-h-0">
        <div class="px-3 py-2 text-xs uppercase tracking-wide text-slate-400 border-b border-slate-800/80">{{ t('workflow_run.node_name') }}</div>
        <div class="overflow-auto h-[calc(100vh-270px)] px-2 py-2">
          <div
            v-if="viewMode === 'timeline'"
            class="h-[28px] border-b border-slate-800/60"
            aria-hidden="true"
          />
          <button
            v-for="n in timelineRows"
            :key="n.node_id"
            class="w-full h-12 text-left px-2 text-sm border-b border-slate-800/60 hover:bg-slate-800/70 flex items-center"
            :class="selectedNodeId === n.node_id ? 'bg-blue-600/20' : ''"
            @click="selectedNodeId = n.node_id"
          >
            <div class="flex items-center justify-between gap-2 min-w-0 w-full">
              <div class="min-w-0">
                <div class="truncate inline-flex items-center gap-1.5">
                  <Loader2
                    v-if="isNodeRunning(n)"
                    class="w-4 h-4 shrink-0 animate-spin text-blue-300"
                  />
                  <span>{{ displayNodeName(n.node_id) }}</span>
                </div>
                <div class="truncate text-[11px] text-slate-500">{{ displayNodeSubtitle(n.node_id) }}</div>
              </div>
              <span class="w-2 h-2 rounded-full" :class="nodeTrackClass(n.state)" />
            </div>
          </button>
          <div v-if="!timelineRows.length" class="text-xs text-slate-500 px-2 py-3">
            <Loader2 v-if="loading" class="w-4 h-4 animate-spin inline-block mr-2" />
            {{ t('workflow_run.no_nodes') }}
          </div>
        </div>
      </aside>

      <section class="min-h-0 border-r border-slate-800/80">
        <div class="px-3 py-2 text-xs uppercase tracking-wide text-slate-400 border-b border-slate-800/80">
          {{ viewMode.toUpperCase() }}
        </div>

        <div v-if="viewMode === 'timeline'" class="h-[calc(100vh-270px)] overflow-auto">
          <div class="relative min-w-[760px]">
            <div class="grid grid-cols-6 text-[11px] text-slate-500 border-b border-slate-800/80">
              <div v-for="mark in [0, 20, 40, 60, 80, 100]" :key="mark" class="px-2 py-1 border-r border-slate-800/60">{{ mark }}%</div>
            </div>
            <div v-for="n in timelineRows" :key="`row-${n.node_id}`" class="relative h-12 border-b border-slate-800/60">
              <div class="absolute inset-y-0 left-0 right-0 grid grid-cols-6 pointer-events-none">
                <div v-for="m in 6" :key="m" class="border-r border-slate-800/40" />
              </div>
              <div
                class="absolute top-2 h-8 rounded border shadow-sm"
                :class="[nodeTrackClass(n.state), nodeTrackAnimClass(n.state)]"
                :style="timelineTrackStyle(n)"
              />
            </div>
          </div>
        </div>

        <div v-else-if="viewMode === 'list'" class="h-[calc(100vh-270px)] overflow-auto p-3 space-y-2">
          <div v-for="n in timelineRows" :key="`list-${n.node_id}`" class="rounded border border-slate-800 bg-slate-900/60 p-3 text-xs">
            <div class="flex items-center justify-between">
              <span class="font-medium">{{ n.node_id }}</span>
              <Badge variant="secondary" :class="statusBadgeClass(normalizeNodeStatus(n.state))">{{ normalizeNodeStatus(n.state) }}</Badge>
            </div>
            <div class="mt-2 text-slate-400">retry: {{ n.retry_count || 0 }}</div>
            <pre class="mt-2 rounded bg-slate-950/60 p-2 overflow-auto text-[11px]">{{ prettyJson(getNodeOutputData(n.node_id)) }}</pre>
          </div>
        </div>

        <div v-else-if="viewMode === 'delivery'" class="h-[calc(100vh-270px)] overflow-auto p-4 space-y-3">
          <div class="rounded border border-slate-800 bg-slate-900/60 p-3 text-xs">
            <div class="text-slate-400 mb-1">{{ t('workflow_run.delivery_summary') }}</div>
            <div class="grid grid-cols-2 gap-2 text-slate-200">
              <div class="flex justify-between"><span>{{ t('workflow_run.state') }}</span><span>{{ normalizeExecutionStatus(currentExecution?.state) }}</span></div>
              <div class="flex justify-between"><span>{{ t('workflow_run.elapsed') }}</span><span>{{ formatElapsed(executionElapsedMs) }}</span></div>
              <div class="flex justify-between"><span>{{ t('workflow_run.nodes') }}</span><span>{{ executionSummary.completed }}/{{ executionSummary.total }}</span></div>
              <div class="flex justify-between"><span>{{ t('workflow_run.failed') }}</span><span>{{ executionSummary.failed }}</span></div>
            </div>
          </div>
          <div class="rounded border border-slate-800 bg-slate-900/60 p-3 text-xs">
            <div class="text-slate-400 mb-1">{{ t('workflow_run.final_output') }}</div>
            <pre class="rounded bg-slate-950/60 p-2 overflow-auto whitespace-pre-wrap">{{ deliveryData.finalText || t('workflow_run.no_final_output') }}</pre>
          </div>
          <div class="rounded border border-slate-800 bg-slate-900/60 p-3 text-xs">
            <div class="text-slate-400 mb-1">{{ t('workflow_run.artifacts') }}</div>
            <ul v-if="deliveryData.artifacts.length" class="space-y-1">
              <li v-for="(a, idx) in deliveryData.artifacts" :key="`artifact-${idx}`" class="rounded bg-slate-950/60 px-2 py-1 font-mono">{{ a }}</li>
            </ul>
            <div v-else class="text-slate-500">{{ t('workflow_run.no_artifacts') }}</div>
          </div>
          <div class="rounded border border-slate-800 bg-slate-900/60 p-3 text-xs">
            <div class="text-slate-400 mb-1">{{ t('workflow_run.raw_output') }}</div>
            <pre class="rounded bg-slate-950/60 p-2 overflow-auto">{{ prettyJson(deliveryData.payload) }}</pre>
          </div>
        </div>

        <div v-else class="h-[calc(100vh-270px)] overflow-auto p-4 text-sm text-slate-400">
          {{ t('workflow_run.graph_placeholder') }}
        </div>
      </section>

      <aside class="min-h-0">
        <div class="px-3 py-2 text-xs uppercase tracking-wide text-slate-400 border-b border-slate-800/80">Node Inspector</div>
        <div class="h-[calc(100vh-270px)] overflow-auto p-3 space-y-3">
          <div v-if="selectedNode" class="rounded border border-slate-800 bg-slate-900/60 p-3">
            <div class="text-sm font-semibold">{{ selectedNode.node_id }}</div>
            <div class="text-xs text-slate-400 mt-1">{{ normalizeNodeStatus(selectedNode.state) }}</div>
          </div>

          <div class="rounded border border-slate-800 bg-slate-900/60 p-3 text-xs">
            <div class="text-slate-400 mb-1">{{ t('workflow_run.performance') }}</div>
            <div class="flex justify-between"><span>{{ t('workflow_run.queue_pos') }}</span><span>{{ currentExecution?.queue_position ?? '-' }}</span></div>
            <div class="flex justify-between"><span>{{ t('workflow_run.wait_ms') }}</span><span>{{ currentExecution?.wait_duration_ms ?? '-' }}</span></div>
            <div class="flex justify-between"><span>{{ t('workflow_run.nodes') }}</span><span>{{ executionSummary.completed }}/{{ executionSummary.total }}</span></div>
            <div class="flex justify-between"><span>{{ t('workflow_run.failed') }}</span><span>{{ executionSummary.failed }}</span></div>
          </div>

          <div class="rounded border border-slate-800 bg-slate-900/60 p-3 text-xs">
            <div class="text-slate-400 mb-1">{{ t('workflow_run.input') }}</div>
            <pre class="rounded bg-slate-950/60 p-2 overflow-auto">{{ prettyJson(selectedNode?.input_data) }}</pre>
          </div>

          <div class="rounded border border-slate-800 bg-slate-900/60 p-3 text-xs">
            <div class="text-slate-400 mb-1">{{ t('workflow_run.output') }}</div>
            <pre class="rounded bg-slate-950/60 p-2 overflow-auto">{{ prettyJson(selectedNode?.output_data) }}</pre>
          </div>

          <div v-if="selectedNode?.error_message" class="rounded border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-300">
            <div class="mb-1">{{ t('workflow_run.error') }}</div>
            <div>{{ selectedNode.error_message }}</div>
            <pre v-if="selectedNode.error_details" class="mt-2 rounded bg-red-950/40 p-2 overflow-auto">{{ prettyJson(selectedNode.error_details) }}</pre>
          </div>
        </div>
      </aside>
    </main>

    <footer class="border-t border-slate-800/80 h-40 bg-slate-950/80">
      <div class="px-3 py-2 text-xs uppercase tracking-wide text-slate-400 border-b border-slate-800/80">{{ t('workflow_run.execution_logs') }}</div>
      <div ref="logContainerRef" class="h-[calc(100%-33px)] overflow-auto px-3 py-2 text-xs font-mono space-y-1 text-slate-300">
        <div v-for="(line, idx) in logs" :key="idx">{{ line }}</div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.workflow-exec-root {
  background:
    radial-gradient(1200px 600px at 20% -20%, rgba(37, 99, 235, 0.25), transparent 60%),
    radial-gradient(900px 500px at 90% -10%, rgba(16, 185, 129, 0.12), transparent 60%),
    #050b18;
}

.exec-topbar {
  background: rgba(3, 10, 24, 0.88);
  backdrop-filter: blur(8px);
}

.exec-tab {
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  color: rgb(148 163 184);
  padding: 6px 10px;
  border-radius: 8px;
}

.exec-tab:hover {
  color: rgb(226 232 240);
  background: rgba(30, 41, 59, 0.6);
}

.exec-tab-active {
  color: #fff;
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.95), rgba(29, 78, 216, 0.95));
}

.timeline-track-running {
  background-image: linear-gradient(
    110deg,
    rgba(59, 130, 246, 0.18) 0%,
    rgba(125, 211, 252, 0.35) 45%,
    rgba(59, 130, 246, 0.18) 100%
  );
  background-size: 220% 100%;
  animation: timelineShimmer 1.6s linear infinite;
}

@keyframes timelineShimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -20% 0;
  }
}
</style>
