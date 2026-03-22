<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { Check, Circle, Clock, Loader2, XCircle } from 'lucide-vue-next'
import type { WorkflowExecutionRecord } from '@/services/api'
import { normalizeNodeStatus, statusBadgeClass } from './status'
import type { WorkflowUiStatus } from './status'

const props = defineProps<{
  execution: WorkflowExecutionRecord | null
  executionStartTime: number | null
  isRunning: boolean
  loading: boolean
}>()

/** 当前时间戳，运行中时周期性更新以延长 running 节点条 */
const nowMs = ref(Date.now())
let nowTick: number | null = null
watch(
  () => props.isRunning,
  (running) => {
    if (running) {
      nowMs.value = Date.now()
      if (nowTick == null) {
        nowTick = window.setInterval(() => {
          nowMs.value = Date.now()
        }, 500)
      }
    } else {
      if (nowTick != null) {
        window.clearInterval(nowTick)
        nowTick = null
      }
    }
  },
  { immediate: true }
)
onUnmounted(() => {
  if (nowTick != null) {
    window.clearInterval(nowTick)
    nowTick = null
  }
})

type NodeStateItem = WorkflowExecutionRecord['node_states'] extends (infer T)[] | undefined ? T : never

const orderedNodes = computed(() => {
  const list = props.execution?.node_states ?? []
  const start = props.executionStartTime
  if (!start || list.length === 0) return []
  return [...list].sort((a, b) => {
    const aStart = a.started_at ? new Date(a.started_at).getTime() : 0
    const bStart = b.started_at ? new Date(b.started_at).getTime() : 0
    if (aStart !== bStart) return aStart - bStart
    const aEnd = a.finished_at ? new Date(a.finished_at).getTime() : 0
    const bEnd = b.finished_at ? new Date(b.finished_at).getTime() : 0
    return aEnd - bEnd
  })
})

const maxTimeMs = computed(() => {
  const start = props.executionStartTime
  if (!start) return 1000
  let max = 0
  const now = nowMs.value
  for (const n of orderedNodes.value) {
    const s = n.started_at ? new Date(n.started_at).getTime() - start : 0
    let e: number
    if (n.finished_at) {
      e = new Date(n.finished_at).getTime() - start
    } else if (normalizeNodeStatus(n.state) === 'running') {
      e = now - start
    } else {
      e = s
    }
    if (e > max) max = e
  }
  if (props.isRunning && now - start > max) max = now - start
  return Math.max(max, 400)
})

const timeTicks = computed(() => {
  const max = maxTimeMs.value
  const step = max <= 2000 ? 200 : max <= 10000 ? 500 : 1000
  const count = Math.ceil(max / step) + 1
  return Array.from({ length: Math.min(count, 12) }, (_, i) => i * step)
})

function barFor(node: NodeStateItem): { leftPct: number; widthPct: number; status: WorkflowUiStatus } {
  const start = props.executionStartTime
  if (!start) return { leftPct: 0, widthPct: 0, status: 'idle' }
  const status = normalizeNodeStatus(node.state)
  const startMs = node.started_at ? new Date(node.started_at).getTime() - start : 0
  let endMs: number
  if (node.finished_at) {
    endMs = new Date(node.finished_at).getTime() - start
  } else if (status === 'running') {
    endMs = nowMs.value - start
  } else {
    return { leftPct: 0, widthPct: 0, status }
  }
  const max = maxTimeMs.value
  return {
    leftPct: (startMs / max) * 100,
    widthPct: Math.max((endMs - startMs) / max * 100, 2),
    status,
  }
}

function barColor(status: WorkflowUiStatus): string {
  switch (status) {
    case 'succeeded':
      return 'bg-emerald-500'
    case 'running':
      return 'bg-blue-500'
    case 'failed':
    case 'timeout':
      return 'bg-red-500'
    case 'pending':
    case 'queued':
      return 'bg-amber-500/70'
    default:
      return 'bg-muted'
  }
}

function nodeIcon(status: WorkflowUiStatus) {
  switch (status) {
    case 'succeeded':
      return Check
    case 'running':
      return Loader2
    case 'failed':
    case 'timeout':
      return XCircle
    case 'pending':
    case 'queued':
      return Clock
    default:
      return Circle
  }
}
</script>

<template>
  <div v-if="loading" class="flex-1 min-h-[20rem] flex items-center justify-center text-muted-foreground text-sm">
    <Loader2 class="w-5 h-5 animate-spin mr-2" />
    Loading...
  </div>
  <div v-else-if="orderedNodes.length === 0" class="flex-1 min-h-[20rem] flex items-center justify-center text-muted-foreground text-sm">
    No node execution data yet.
  </div>
  <div v-else class="flex flex-col flex-1 min-h-0 overflow-auto">
    <!-- 时间轴刻度 -->
    <div class="flex border-b border-border pb-1 mb-2">
      <div class="w-48 shrink-0 text-xs text-muted-foreground">NODE NAME</div>
      <div class="flex-1 min-w-0 relative flex text-xs text-muted-foreground">
        <template v-for="(t, i) in timeTicks" :key="i">
          <span
            class="absolute transform -translate-x-1/2"
            :style="{ left: `${(t / maxTimeMs) * 100}%` }"
          >
            {{ t >= 1000 ? `${(t / 1000).toFixed(1)}s` : `${t}ms` }}
          </span>
        </template>
      </div>
    </div>
    <!-- 每行：节点名 + 条形 -->
    <div
      v-for="node in orderedNodes"
      :key="node.node_id"
      class="flex items-center gap-2 py-1.5 border-b border-border/50 last:border-0"
    >
      <div class="w-48 shrink-0 flex items-center gap-2 min-w-0">
        <component
          :is="nodeIcon(normalizeNodeStatus(node.state))"
          class="w-4 h-4 shrink-0"
          :class="[
            statusBadgeClass(normalizeNodeStatus(node.state)),
            normalizeNodeStatus(node.state) === 'running' ? 'animate-spin' : '',
          ]"
        />
        <span class="text-sm truncate" :title="node.node_id">{{ node.node_id }}</span>
      </div>
      <div class="flex-1 min-w-0 h-6 relative rounded overflow-hidden bg-muted/30">
        <div
          v-if="barFor(node).widthPct > 0"
          class="absolute inset-y-0 rounded transition-all duration-300"
          :class="barColor(barFor(node).status)"
          :style="{
            left: `${barFor(node).leftPct}%`,
            width: `${barFor(node).widthPct}%`,
          }"
        />
      </div>
    </div>
  </div>
</template>
