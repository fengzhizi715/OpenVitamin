<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Activity,
  Play,
  Check,
  XCircle,
  Clock,
  ChevronRight,
  Loader2,
  AlertCircle,
  RefreshCw,
  Layers,
  Zap,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  getInstanceEvents,
  replayInstanceState,
  getInstanceMetrics,
  validateEventStream,
  type ExecutionEvent,
  type RebuiltGraphState,
  type ExecutionMetrics,
  type EventValidation,
} from '@/services/api'

const props = defineProps<{
  kernelInstanceId: string | null | undefined
}>()

const i18n = useI18n()
const { t } = i18n

// State
const events = ref<ExecutionEvent[]>([])
const metrics = ref<ExecutionMetrics | null>(null)
const validation = ref<EventValidation | null>(null)
const rebuiltState = ref<RebuiltGraphState | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const selectedSequence = ref<number | null>(null)
const expandedNodes = ref<Set<string>>(new Set())

// Computed
const hasInstanceId = computed(() => !!props.kernelInstanceId)

const nodeStates = computed(() => rebuiltState.value?.nodes || {})

// Format helpers
const formatTimestamp = (ts: number) => {
  const d = new Date(ts)
  return d.toLocaleTimeString()
}

const formatEventType = (eventType: string) => {
  const labels: Record<string, string> = {
    graph_started: 'Graph Started',
    graph_completed: 'Graph Completed',
    graph_failed: 'Graph Failed',
    graph_cancelled: 'Graph Cancelled',
    node_scheduled: 'Node Scheduled',
    node_started: 'Node Started',
    node_succeeded: 'Node Succeeded',
    node_failed: 'Node Failed',
    node_retry_scheduled: 'Retry Scheduled',
    node_skipped: 'Node Skipped',
    node_timeout: 'Node Timeout',
    scheduler_decision: 'Scheduler Decision',
    state_transition: 'State Transition',
    context_updated: 'Context Updated',
    patch_applied: 'Patch Applied',
    patch_failed: 'Patch Failed',
    crash_recovery_started: 'Recovery Started',
    crash_recovery_completed: 'Recovery Completed',
  }
  return labels[eventType] || eventType
}

const getEventIcon = (eventType: string) => {
  if (eventType.includes('succeeded') || eventType.includes('completed')) return Check
  if (eventType.includes('failed') || eventType.includes('error')) return XCircle
  if (eventType.includes('started')) return Play
  if (eventType.includes('scheduled')) return Clock
  return Activity
}

const getEventColor = (eventType: string) => {
  if (eventType.includes('succeeded') || eventType.includes('completed')) return 'text-emerald-500 bg-emerald-500/10'
  if (eventType.includes('failed') || eventType.includes('error')) return 'text-red-500 bg-red-500/10'
  if (eventType.includes('started')) return 'text-blue-500 bg-blue-500/10'
  if (eventType.includes('scheduled')) return 'text-amber-500 bg-amber-500/10'
  return 'text-muted-foreground bg-muted'
}

const formatNodeState = (state: string) => {
  const labels: Record<string, string> = {
    pending: 'Pending',
    running: 'Running',
    succeeded: 'Succeeded',
    failed: 'Failed',
    skipped: 'Skipped',
  }
  return labels[state] || state
}

const getNodeStateColor = (state: string) => {
  const colors: Record<string, string> = {
    pending: 'bg-gray-100 text-gray-600',
    running: 'bg-blue-100 text-blue-600',
    succeeded: 'bg-emerald-100 text-emerald-600',
    failed: 'bg-red-100 text-red-600',
    skipped: 'bg-amber-100 text-amber-600',
  }
  return colors[state] || 'bg-muted text-muted-foreground'
}

// Actions
const fetchData = async () => {
  if (!props.kernelInstanceId) {
    events.value = []
    metrics.value = null
    validation.value = null
    rebuiltState.value = null
    return
  }

  loading.value = true
  error.value = null

  try {
    const [eventsRes, metricsRes, validationRes, stateRes] = await Promise.all([
      getInstanceEvents(props.kernelInstanceId),
      getInstanceMetrics(props.kernelInstanceId).catch(() => null),
      validateEventStream(props.kernelInstanceId).catch(() => null),
      replayInstanceState(props.kernelInstanceId).catch(() => null),
    ])

    events.value = eventsRes.events || []
    metrics.value = metricsRes
    validation.value = validationRes
    rebuiltState.value = stateRes

    // Select first event by default
    if (events.value.length > 0 && selectedSequence.value === null) {
      const firstEvent = events.value[0]
      if (firstEvent) selectedSequence.value = firstEvent.sequence
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    console.error('Failed to fetch event stream:', e)
  } finally {
    loading.value = false
  }
}

const replayToSequence = async (sequence: number) => {
  if (!props.kernelInstanceId) return

  try {
    rebuiltState.value = await replayInstanceState(props.kernelInstanceId, sequence)
    selectedSequence.value = sequence
  } catch (e) {
    console.error('Failed to replay to sequence:', e)
  }
}

const toggleNodeExpand = (nodeId: string) => {
  if (expandedNodes.value.has(nodeId)) {
    expandedNodes.value.delete(nodeId)
  } else {
    expandedNodes.value.add(nodeId)
  }
}

// Watch for kernelInstanceId changes
watch(() => props.kernelInstanceId, (newId) => {
  if (newId) {
    fetchData()
  } else {
    events.value = []
    metrics.value = null
    validation.value = null
    rebuiltState.value = null
    selectedSequence.value = null
  }
}, { immediate: true })

onMounted(() => {
  if (props.kernelInstanceId) {
    fetchData()
  }
})
</script>

<template>
  <div class="flex flex-col h-full bg-background border border-border rounded-xl overflow-hidden">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30">
      <div class="flex items-center gap-2">
        <Layers class="w-4 h-4 text-primary" />
        <span class="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          {{ t('agents.debug.event_stream') }}
        </span>
        <Badge v-if="validation" :variant="validation.valid ? 'default' : 'destructive'" class="text-[10px]">
          {{ validation.valid ? t('agents.debug.valid') : t('agents.debug.invalid') }}
        </Badge>
      </div>
      <Button
        variant="ghost"
        size="icon"
        class="w-7 h-7"
        @click="fetchData"
        :disabled="loading || !hasInstanceId"
      >
        <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
      </Button>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-hidden flex flex-col">
      <template v-if="!hasInstanceId">
        <div class="flex-1 flex items-center justify-center p-4 text-center">
          <div class="space-y-2">
            <AlertCircle class="w-8 h-8 mx-auto text-muted-foreground/50" />
            <p class="text-xs text-muted-foreground">{{ t('agents.debug.no_kernel_instance') }}</p>
          </div>
        </div>
      </template>

      <template v-else-if="loading">
        <div class="flex-1 flex items-center justify-center">
          <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
        </div>
      </template>

      <template v-else-if="error">
        <div class="flex-1 flex items-center justify-center p-4 text-center">
          <div class="space-y-2">
            <XCircle class="w-8 h-8 mx-auto text-red-500" />
            <p class="text-xs text-red-500">{{ error }}</p>
          </div>
        </div>
      </template>

      <template v-else-if="events.length === 0">
        <div class="flex-1 flex items-center justify-center p-4 text-center">
          <p class="text-xs text-muted-foreground">{{ t('agents.debug.no_events') }}</p>
        </div>
      </template>

      <template v-else>
        <!-- Metrics Bar -->
        <div v-if="metrics" class="grid grid-cols-4 gap-2 px-3 py-2 border-b border-border bg-muted/20 text-center">
          <div>
            <div class="text-[10px] text-muted-foreground uppercase">{{ t('agents.debug.events') }}</div>
            <div class="text-sm font-bold text-foreground">{{ metrics.total_events }}</div>
          </div>
          <div>
            <div class="text-[10px] text-muted-foreground uppercase">{{ t('agents.debug.success_rate') }}</div>
            <div class="text-sm font-bold" :class="metrics.node_success_rate >= 0.8 ? 'text-emerald-500' : 'text-amber-500'">
              {{ (metrics.node_success_rate * 100).toFixed(0) }}%
            </div>
          </div>
          <div>
            <div class="text-[10px] text-muted-foreground uppercase">{{ t('agents.debug.duration') }}</div>
            <div class="text-sm font-bold text-foreground">{{ (metrics.total_execution_duration_ms / 1000).toFixed(2) }}s</div>
          </div>
          <div>
            <div class="text-[10px] text-muted-foreground uppercase">{{ t('agents.debug.nodes') }}</div>
            <div class="text-sm font-bold text-foreground">{{ metrics.completed_nodes }}/{{ metrics.completed_nodes + metrics.failed_nodes }}</div>
          </div>
        </div>

        <!-- Event List -->
        <div class="flex-1 overflow-y-auto custom-scrollbar">
          <div class="divide-y divide-border/50">
            <button
              v-for="event in events"
              :key="event.event_id"
              @click="replayToSequence(event.sequence)"
              :class="[
                'w-full flex items-center gap-3 px-3 py-2 text-left transition-all',
                selectedSequence === event.sequence
                  ? 'bg-primary/5 border-l-2 border-primary'
                  : 'hover:bg-muted/50 border-l-2 border-transparent',
              ]"
            >
              <div
                :class="[
                  'w-6 h-6 rounded-lg flex items-center justify-center shrink-0',
                  getEventColor(event.event_type),
                ]"
              >
                <component :is="getEventIcon(event.event_type)" class="w-3 h-3" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="text-xs font-medium text-foreground truncate">
                  {{ formatEventType(event.event_type) }}
                </div>
                <div class="text-[10px] text-muted-foreground">
                  #{{ event.sequence }} • {{ formatTimestamp(event.timestamp) }}
                </div>
              </div>
              <ChevronRight
                v-if="selectedSequence === event.sequence"
                class="w-4 h-4 text-primary shrink-0"
              />
            </button>
          </div>
        </div>

        <!-- Rebuilt State Panel -->
        <div v-if="rebuiltState && Object.keys(nodeStates).length > 0" class="border-t border-border bg-muted/20 max-h-48 overflow-y-auto">
          <div class="px-3 py-2 border-b border-border/50">
            <div class="flex items-center gap-2">
              <Zap class="w-3.5 h-3.5 text-amber-500" />
              <span class="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                {{ t('agents.debug.state_at_step', { n: rebuiltState.last_sequence }) }}
              </span>
            </div>
          </div>
          <div class="divide-y divide-border/30">
            <button
              v-for="(node, nodeId) in nodeStates"
              :key="nodeId"
              @click="toggleNodeExpand(nodeId)"
              class="w-full px-3 py-2 flex items-center gap-2 hover:bg-muted/30 transition-colors"
            >
              <div
                :class="[
                  'w-5 h-5 rounded text-[10px] font-bold flex items-center justify-center',
                  getNodeStateColor(node.state),
                ]"
              >
                {{ nodeId.charAt(0).toUpperCase() }}
              </div>
              <div class="flex-1 min-w-0">
                <div class="text-xs font-medium text-foreground truncate">{{ nodeId }}</div>
                <div class="text-[10px] text-muted-foreground">
                  {{ formatNodeState(node.state) }}
                  <span v-if="node.retry_count > 0" class="text-amber-500">
                    • {{ node.retry_count }} {{ t('agents.debug.retries') }}
                  </span>
                </div>
              </div>
              <ChevronRight
                :class="[
                  'w-3.5 h-3.5 text-muted-foreground transition-transform',
                  expandedNodes.has(nodeId) ? 'rotate-90' : '',
                ]"
              />
            </button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.2);
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.4);
}
</style>
