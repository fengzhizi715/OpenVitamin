<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Edit, Play, Trash2, Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  deleteWorkflowExecution,
  getWorkflow,
  getWorkflowExecution,
  getWorkflowExecutionStatus,
  getWorkflowGovernance,
  setWorkflowGovernance,
  listWorkflowExecutions,
  streamWorkflowExecutionStatus,
  updateWorkflow,
  type WorkflowExecutionRecord,
  type WorkflowRecord,
  type WorkflowGovernanceStatus,
} from '@/services/api'
import { normalizeExecutionStatus, normalizeNodeStatus, parseAgentSchemaError, statusBadgeClass } from './status'

const route = useRoute()
const router = useRouter()
const workflowId = route.params.id as string

const workflow = ref<WorkflowRecord | null>(null)
const executions = ref<WorkflowExecutionRecord[]>([])
const selectedExecution = ref<WorkflowExecutionRecord | null>(null)
const loading = ref(false)
const governance = ref<WorkflowGovernanceStatus | null>(null)
const governanceForm = ref({
  max_queue_size: 200,
  backpressure_strategy: 'wait' as 'wait' | 'reject',
})
const governanceSaving = ref(false)
const workflowNameEdit = ref('')
const workflowNameSaving = ref(false)
const nodeFilter = ref<'all' | 'failed' | 'slow' | 'completed'>('all')
const slowThresholdMs = ref(3000)
const executionTotal = ref(0)
const executionLimit = ref(10)
const executionOffset = ref(0)
const executionLoading = ref(false)
const deletingExecutionId = ref<string | null>(null)
let historyPollTimer: number | null = null
const localTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Local'
let statusStreamStop: (() => void) | null = null

const filteredNodeStates = computed(() => {
  const nodes = selectedExecution.value?.node_states || []
  if (nodeFilter.value === 'all') return nodes
  if (nodeFilter.value === 'failed') return nodes.filter((n) => normalizeNodeStatus(n.state) === 'failed')
  if (nodeFilter.value === 'completed') return nodes.filter((n) => normalizeNodeStatus(n.state) === 'succeeded')
  return nodes.filter((n) => (n.started_at && n.finished_at)
    ? elapsedMs(n.started_at, n.finished_at) >= slowThresholdMs.value
    : false)
})

function goBack() {
  router.push({ name: 'workflow' })
}

function editWorkflow() {
  router.push({ name: 'workflow-edit', params: { id: workflowId } })
}

function runWorkflow() {
  router.push({
    name: 'workflow-run',
    params: { id: workflowId },
    query: {
      auto_start: '1',
      t: String(Date.now()),
    },
  })
}

function openExecutionRun(executionId: string) {
  router.push({
    name: 'workflow-run',
    params: { id: workflowId },
    query: { execution_id: executionId },
  })
}

function openVersions() {
  router.push({ name: 'workflow-versions', params: { id: workflowId } })
}

function elapsedMs(start?: string | null, end?: string | null): number {
  if (!start || !end) return 0
  const s = new Date(start).getTime()
  const e = new Date(end).getTime()
  if (Number.isNaN(s) || Number.isNaN(e)) return 0
  return Math.max(0, e - s)
}

function prettyJson(value: unknown): string {
  if (value == null) return 'null'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function formatExecutionTime(value?: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString()
}

async function selectExecution(executionId: string) {
  const detail = await getWorkflowExecution(workflowId, executionId)
  selectedExecution.value = detail
  const idx = executions.value.findIndex((e) => e.execution_id === executionId)
  if (idx >= 0) {
    const prev = executions.value[idx]
    if (prev) {
      executions.value[idx] = {
        ...prev,
        state: detail.state,
        started_at: detail.started_at ?? prev.started_at,
        finished_at: detail.finished_at ?? prev.finished_at,
        duration_ms: detail.duration_ms ?? prev.duration_ms,
        queue_position: detail.queue_position ?? prev.queue_position,
        wait_duration_ms: detail.wait_duration_ms ?? prev.wait_duration_ms,
      }
    }
  }
  const st = normalizeExecutionStatus(detail.state)
  if (st === 'pending' || st === 'queued' || st === 'running') {
    startExecutionStatusStream(executionId)
  } else {
    stopExecutionStatusStream()
  }
}

async function loadExecutionHistory(preferredExecutionId?: string) {
  executionLoading.value = true
  try {
    const list = await listWorkflowExecutions(workflowId, { limit: executionLimit.value, offset: executionOffset.value })
    const items = [...(list.items || [])]
    // 用 status 端点校正活跃执行状态，避免列表上“实际已完成但仍显示 running”。
    await Promise.all(items.map(async (it, idx) => {
      const st = normalizeExecutionStatus(it.state)
      if (st !== 'pending' && st !== 'queued' && st !== 'running') return
      try {
        const s = await getWorkflowExecutionStatus(workflowId, it.execution_id)
        items[idx] = {
          ...it,
          state: s.state,
          started_at: s.started_at ?? it.started_at,
          finished_at: s.finished_at ?? it.finished_at,
          duration_ms: s.duration_ms ?? it.duration_ms,
          queue_position: s.queue_position ?? it.queue_position,
          wait_duration_ms: s.wait_duration_ms ?? it.wait_duration_ms,
        }
      } catch {
        // ignore single item status fetch errors
      }
    }))
    executions.value = items
    executionTotal.value = list.total || 0
    const targetId = preferredExecutionId || selectedExecution.value?.execution_id || executions.value[0]?.execution_id
    if (targetId) {
      const inPage = executions.value.find((e) => e.execution_id === targetId)
      if (inPage) {
        await selectExecution(inPage.execution_id)
      } else if (executions.value[0]?.execution_id) {
        await selectExecution(executions.value[0].execution_id)
      } else {
        selectedExecution.value = null
        stopExecutionStatusStream()
      }
    } else {
      selectedExecution.value = null
      stopExecutionStatusStream()
    }
  } finally {
    executionLoading.value = false
  }
}

function stopHistoryPolling() {
  if (historyPollTimer != null) {
    window.clearTimeout(historyPollTimer)
    historyPollTimer = null
  }
}

function stopExecutionStatusStream() {
  if (statusStreamStop) {
    statusStreamStop()
    statusStreamStop = null
  }
}

function applyExecutionStatusToList(
  executionId: string,
  status: {
    state: string
    started_at?: string | null
    finished_at?: string | null
    duration_ms?: number | null
    queue_position?: number | null
    wait_duration_ms?: number | null
  }
) {
  const idx = executions.value.findIndex((e) => e.execution_id === executionId)
  if (idx < 0) return
  const prev = executions.value[idx]
  if (!prev) return
  executions.value[idx] = {
    ...prev,
    state: status.state,
    started_at: status.started_at ?? prev.started_at,
    finished_at: status.finished_at ?? prev.finished_at,
    duration_ms: status.duration_ms ?? prev.duration_ms,
    queue_position: status.queue_position ?? prev.queue_position,
    wait_duration_ms: status.wait_duration_ms ?? prev.wait_duration_ms,
  }
}

function startExecutionStatusStream(executionId: string) {
  stopExecutionStatusStream()
  statusStreamStop = streamWorkflowExecutionStatus(
    workflowId,
    executionId,
    {
      onStatus: (payload) => {
        applyExecutionStatusToList(executionId, payload)
        if (selectedExecution.value?.execution_id === executionId) {
          selectedExecution.value = {
            ...selectedExecution.value,
            state: payload.state,
            started_at: payload.started_at ?? selectedExecution.value.started_at,
            finished_at: payload.finished_at ?? selectedExecution.value.finished_at,
            duration_ms: payload.duration_ms ?? selectedExecution.value.duration_ms,
            queue_position: payload.queue_position ?? selectedExecution.value.queue_position,
            wait_duration_ms: payload.wait_duration_ms ?? selectedExecution.value.wait_duration_ms,
            node_timeline: payload.node_timeline || selectedExecution.value.node_timeline,
          }
        }
      },
      onTerminal: () => {
        stopExecutionStatusStream()
      },
      onError: () => {
        stopExecutionStatusStream()
      },
    },
    { intervalMs: 1000 }
  )
}

function scheduleHistoryPolling(delayMs = 3000) {
  stopHistoryPolling()
  historyPollTimer = window.setTimeout(async () => {
    const hasActive = executions.value.some((e) => {
      const s = normalizeExecutionStatus(e.state)
      return s === 'pending' || s === 'queued' || s === 'running'
    })
    if (hasActive && !executionLoading.value && !loading.value) {
      await loadExecutionHistory(selectedExecution.value?.execution_id)
    }
    scheduleHistoryPolling(3000)
  }, Math.max(500, delayMs))
}

async function nextExecutionPage() {
  if (executionOffset.value + executionLimit.value >= executionTotal.value) return
  executionOffset.value += executionLimit.value
  await loadExecutionHistory()
}

async function prevExecutionPage() {
  if (executionOffset.value <= 0) return
  executionOffset.value = Math.max(0, executionOffset.value - executionLimit.value)
  await loadExecutionHistory()
}

async function deleteExecutionHistory(executionId: string) {
  if (!window.confirm(`Delete execution ${executionId}?`)) return
  deletingExecutionId.value = executionId
  try {
    await deleteWorkflowExecution(workflowId, executionId)
    if (executionOffset.value >= executionTotal.value - 1) {
      executionOffset.value = Math.max(0, executionOffset.value - executionLimit.value)
    }
    await loadExecutionHistory()
  } finally {
    deletingExecutionId.value = null
  }
}

async function loadGovernance() {
  try {
    const res = await getWorkflowGovernance(workflowId)
    governance.value = res
    const q = res.queue
    if (q) {
      governanceForm.value.max_queue_size = q.max_queue_size ?? 200
      governanceForm.value.backpressure_strategy = (q.backpressure_strategy === 'reject' ? 'reject' : 'wait')
    }
  } catch {
    governance.value = null
  }
}

async function saveWorkflowName() {
  const name = workflowNameEdit.value.trim()
  if (!workflow.value || name === (workflow.value.name ?? '')) return
  workflowNameSaving.value = true
  try {
    workflow.value = await updateWorkflow(workflowId, { name: name || 'Untitled Workflow' })
    workflowNameEdit.value = workflow.value.name ?? ''
  } finally {
    workflowNameSaving.value = false
  }
}

watch(() => workflow.value?.name, (name) => { workflowNameEdit.value = name ?? '' }, { immediate: true })

async function saveGovernance() {
  governanceSaving.value = true
  try {
    const res = await setWorkflowGovernance(workflowId, {
      max_queue_size: governanceForm.value.max_queue_size,
      backpressure_strategy: governanceForm.value.backpressure_strategy,
    })
    governance.value = res
    const q = res.queue
    if (q) {
      governanceForm.value.max_queue_size = q.max_queue_size ?? 200
      governanceForm.value.backpressure_strategy = (q.backpressure_strategy === 'reject' ? 'reject' : 'wait')
    }
  } finally {
    governanceSaving.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const [wf] = await Promise.all([
      getWorkflow(workflowId),
    ])
    workflow.value = wf
    await loadExecutionHistory()
    await loadGovernance()
  } finally {
    loading.value = false
  }
  scheduleHistoryPolling(3000)
})

onUnmounted(() => {
  stopExecutionStatusStream()
  stopHistoryPolling()
})
</script>

<template>
  <div class="flex flex-col h-full bg-background">
    <div class="flex items-center gap-4 px-8 py-6 border-b border-border/50">
      <Button variant="ghost" size="icon" @click="goBack">
        <ArrowLeft class="w-5 h-5" />
      </Button>
      <div class="flex-1">
        <div class="flex items-center gap-3">
          <h1 class="text-2xl font-bold tracking-tight">{{ workflow?.name || 'Workflow Detail' }}</h1>
          <Badge variant="secondary">{{ workflow?.lifecycle_state || 'draft' }}</Badge>
        </div>
        <p class="text-sm text-muted-foreground">ID: {{ workflowId }}</p>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" class="gap-2" @click="openVersions">
          Versions
        </Button>
        <Button variant="outline" class="gap-2" @click="editWorkflow">
          <Edit class="w-4 h-4" />
          Edit
        </Button>
        <Button variant="destructive" class="gap-2">
          <Trash2 class="w-4 h-4" />
          Delete
        </Button>
        <Button class="gap-2 bg-blue-600 hover:bg-blue-700" @click="runWorkflow">
          <Play class="w-4 h-4" />
          Run
        </Button>
      </div>
    </div>

    <div class="flex-1 overflow-auto p-8">
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Workflow Information</CardTitle>
            </CardHeader>
            <CardContent class="space-y-3">
              <div>
                <label class="text-sm font-medium text-muted-foreground">Name</label>
                <div class="flex items-center gap-2 mt-1">
                  <Input
                    v-model="workflowNameEdit"
                    class="flex-1 text-base"
                    placeholder="Workflow name"
                    :disabled="workflowNameSaving"
                    @blur="saveWorkflowName"
                    @keydown.enter.prevent="saveWorkflowName"
                  />
                  <span v-if="workflowNameSaving" class="text-xs text-muted-foreground">Saving...</span>
                </div>
              </div>
              <div>
                <label class="text-sm font-medium text-muted-foreground">Description</label>
                <p class="text-base">{{ workflow?.description || '-' }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-muted-foreground">Status</label>
                <Badge variant="secondary">{{ workflow?.lifecycle_state || 'draft' }}</Badge>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle class="flex items-center justify-between">
                <span>Latest Node Results</span>
                <select v-model="nodeFilter" class="h-8 rounded-md border border-input bg-background px-2 text-xs">
                  <option value="all">All</option>
                  <option value="failed">Failed</option>
                  <option value="slow">Slow</option>
                  <option value="completed">Completed</option>
                </select>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div v-if="loading" class="h-40 flex items-center justify-center text-muted-foreground text-sm">
                <Loader2 class="w-4 h-4 animate-spin mr-2" />
                Loading...
              </div>
              <div v-else-if="!selectedExecution || filteredNodeStates.length === 0" class="h-40 flex items-center justify-center text-muted-foreground text-sm">
                No node-level results yet.
              </div>
              <div v-else class="space-y-3 max-h-[32rem] overflow-auto pr-1">
                <div v-for="ns in filteredNodeStates" :key="ns.node_id" class="rounded-lg border border-border/60 p-3">
                  <div class="flex items-center justify-between mb-2">
                    <span class="text-sm font-medium">{{ ns.node_id }}</span>
                    <div class="flex items-center gap-2">
                      <Badge variant="secondary" :class="statusBadgeClass(normalizeNodeStatus(ns.state))">
                        {{ normalizeNodeStatus(ns.state) }}
                      </Badge>
                      <span class="text-xs text-muted-foreground">{{ elapsedMs(ns.started_at, ns.finished_at) }} ms</span>
                    </div>
                  </div>
                  <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                    <div class="rounded border border-border/50 bg-muted/20 p-2">
                      <div class="mb-1 text-muted-foreground">input</div>
                      <pre class="whitespace-pre-wrap break-words">{{ prettyJson(ns.input_data) }}</pre>
                    </div>
                    <div class="rounded border border-border/50 bg-muted/20 p-2">
                      <div class="mb-1 text-muted-foreground">output</div>
                      <pre class="whitespace-pre-wrap break-words">{{ prettyJson(ns.output_data) }}</pre>
                    </div>
                  </div>
                  <template v-if="ns.error_message">
                    <div v-if="parseAgentSchemaError(ns.error_message)" class="mt-2 rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
                      <p class="font-medium text-amber-700 dark:text-amber-400">Output schema 校验失败（调试）</p>
                      <p class="mt-1 text-amber-600 dark:text-amber-500">{{ parseAgentSchemaError(ns.error_message)?.detail }}</p>
                    </div>
                    <div v-else class="mt-2 rounded border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-400">{{ ns.error_message }}</div>
                  </template>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div class="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle class="flex items-center justify-between">
                <span>Execution History</span>
                <span class="text-xs text-muted-foreground">
                  {{ executionTotal === 0 ? '0-0' : `${executionOffset + 1}-${Math.min(executionOffset + executions.length, executionTotal)}` }}/{{ executionTotal }}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div v-if="executionLoading" class="text-sm text-muted-foreground flex items-center gap-2">
                <Loader2 class="w-4 h-4 animate-spin" />
                Loading history...
              </div>
              <div v-else-if="executions.length === 0" class="text-sm text-muted-foreground">No executions.</div>
              <div v-else class="space-y-2">
                <button
                  v-for="exec in executions"
                  :key="exec.execution_id"
                  class="w-full text-left rounded-lg border border-border/60 p-3 hover:bg-muted/20"
                  :class="selectedExecution?.execution_id === exec.execution_id ? 'bg-muted/30 border-blue-500/40' : ''"
                  @click="selectExecution(exec.execution_id)"
                >
                  <div class="flex items-center justify-between">
                    <span class="text-xs truncate">{{ exec.execution_id }}</span>
                    <div class="flex items-center gap-2">
                      <Badge variant="secondary" :class="statusBadgeClass(normalizeExecutionStatus(exec.state))">{{ normalizeExecutionStatus(exec.state) }}</Badge>
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-6 px-2 text-xs"
                        @click.stop="openExecutionRun(exec.execution_id)"
                      >
                        Open
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-6 px-2 text-xs text-red-400 hover:text-red-300"
                        :disabled="deletingExecutionId === exec.execution_id"
                        @click.stop="deleteExecutionHistory(exec.execution_id)"
                      >
                        <Loader2 v-if="deletingExecutionId === exec.execution_id" class="w-3 h-3 animate-spin" />
                        <span v-else>Delete</span>
                      </Button>
                    </div>
                  </div>
                  <div class="text-xs text-muted-foreground mt-1" :title="exec.created_at || ''">
                    {{ formatExecutionTime(exec.created_at) }}
                  </div>
                </button>
              </div>
              <div class="mt-2 text-[11px] text-muted-foreground">Timezone: {{ localTimeZone }}</div>
              <div class="mt-3 flex items-center justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  :disabled="executionOffset <= 0 || executionLoading"
                  @click="prevExecutionPage"
                >
                  Prev
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  :disabled="executionOffset + executionLimit >= executionTotal || executionLoading"
                  @click="nextExecutionPage"
                >
                  Next
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Selected Output</CardTitle>
            </CardHeader>
            <CardContent>
              <pre class="h-56 overflow-auto rounded border border-border/60 bg-muted/20 p-3 text-xs whitespace-pre-wrap break-words">{{ prettyJson(selectedExecution?.output_data) }}</pre>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Execution Governance</CardTitle>
            </CardHeader>
            <CardContent class="space-y-3">
              <div class="space-y-2">
                <label class="text-sm font-medium">Max queue size</label>
                <Input
                  v-model.number="governanceForm.max_queue_size"
                  type="number"
                  min="1"
                  max="10000"
                  class="h-9"
                />
              </div>
              <div class="space-y-2">
                <label class="text-sm font-medium">Backpressure</label>
                <select
                  v-model="governanceForm.backpressure_strategy"
                  class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
                >
                  <option value="wait">Wait (queue)</option>
                  <option value="reject">Reject when full</option>
                </select>
              </div>
              <div v-if="governance?.queue" class="text-xs text-muted-foreground">
                Queued: {{ governance.queue.queued_executions ?? 0 }} / {{ governance.queue.max_queue_size ?? '-' }}
              </div>
              <Button
                size="sm"
                class="w-full"
                :disabled="governanceSaving"
                @click="saveGovernance"
              >
                <Loader2 v-if="governanceSaving" class="w-4 h-4 animate-spin mr-2" />
                Save governance
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  </div>
</template>
