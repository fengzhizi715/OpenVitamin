<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeft,
  Check,
  Zap,
  Wrench,
  FileText,
  Copy,
  Play,
  Settings,
  Share2,
  AlertCircle,
  ChevronRight,
  Loader2,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  getAgent,
  getAgentSession,
  getAgentTrace,
  type AgentDefinition,
  type AgentSession,
  type AgentTraceEvent,
} from '@/services/api'
import mermaid from 'mermaid'

const i18n = useI18n()
const { t, locale } = i18n
const route = useRoute()
const router = useRouter()

const agentId = route.params.id as string
const sessionId = computed(() => (route.query.session as string) || '')

const agent = ref<AgentDefinition | null>(null)
const session = ref<AgentSession | null>(null)
const traceEvents = ref<AgentTraceEvent[]>([])
const loading = ref(true)
const selectedStepIndex = ref(0)
const sessionMissing = ref(false)
const activeTab = ref<'timeline' | 'dependencies'>('timeline')
const dagMermaidSvg = ref<string>('')

const fetchData = async () => {
  if (!sessionId.value) return
  try {
    loading.value = true
    sessionMissing.value = false

    // Session 可能因为数据恢复/清理而不存在，但 trace 仍然存在：
    // 这里使用 allSettled，保证“能看 trace 就尽量展示 trace”。
    const [agentRes, sessionRes, traceRes] = await Promise.allSettled([
      getAgent(agentId),
      getAgentSession(sessionId.value),
      getAgentTrace(sessionId.value),
    ])

    agent.value = agentRes.status === 'fulfilled' ? agentRes.value : null

    if (sessionRes.status === 'fulfilled') {
      session.value = sessionRes.value
    } else {
      session.value = null
      const msg = (sessionRes.reason && (sessionRes.reason as any).message) ? String((sessionRes.reason as any).message) : String(sessionRes.reason)
      // api.ts 目前对 404 会抛 `API error: Not Found`，这里做一个宽松判断
      if (msg.includes('Not Found') || msg.includes('404')) {
        sessionMissing.value = true
      }
    }

    if (traceRes.status === 'fulfilled') {
      traceEvents.value = traceRes.value.data || []
    } else {
      traceEvents.value = []
    }

    if (traceEvents.value.length > 0 && selectedStepIndex.value >= traceEvents.value.length) {
      selectedStepIndex.value = 0
    }
  } catch (e) {
    console.error('Failed to load trace:', e)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await fetchData()
  // Initialize DAG after data is loaded if on dependencies tab
  if (activeTab.value === 'dependencies' && traceEvents.value.length > 0) {
    await generateDagDiagram()
  }
})
watch(sessionId, async () => {
  await fetchData()
  // Regenerate DAG when session changes if on dependencies tab
  if (activeTab.value === 'dependencies' && traceEvents.value.length > 0) {
    await generateDagDiagram()
  }
})

// Watch for trace changes to update DAG
watch(traceEvents, async () => {
  if (activeTab.value === 'dependencies' && traceEvents.value.length > 0) {
    await generateDagDiagram()
  }
}, { deep: true })

// Watch for tab changes to regenerate DAG when switching to dependencies tab
watch(activeTab, async () => {
  if (activeTab.value === 'dependencies' && traceEvents.value.length > 0) {
    await generateDagDiagram()
  }
})

const traceIdDisplay = computed(() => {
  void locale.value // depend on locale so i18n updates
  return session.value?.trace_id || session.value?.session_id || sessionId.value || t('agents.trace.n_a')
})
const totalLatencyMs = computed(() =>
  traceEvents.value.reduce((sum, e) => sum + (e.duration_ms ?? 0), 0)
)
const latencyDisplay = computed(() => {
  void locale.value
  const ms = totalLatencyMs.value
  if (ms >= 1000) return t('agents.trace.duration_seconds', { n: (ms / 1000).toFixed(1) })
  return ms ? t('agents.trace.duration_milliseconds', { n: ms }) : t('agents.trace.n_a')
})
const stepsCount = computed(() => traceEvents.value.length)
const statusLabel = computed(() => {
  void locale.value // depend on locale for reactivity
  if (!session.value) return t('agents.trace.n_a')
  const s = session.value?.status
  if (s === 'finished') return t('agents.trace.status_completed')
  if (s === 'error') return t('agents.trace.status_error')
  if (s === 'running') return t('agents.trace.status_running')
  return t('agents.trace.status_idle')
})
const statusBadgeVariant = computed(() => {
  if (!session.value) return 'secondary'
  const s = session.value?.status
  if (s === 'finished') return 'default'
  if (s === 'error') return 'destructive'
  return 'secondary'
})

// Generate Mermaid DAG diagram from execution trace
const generateDagDiagram = async () => {
  console.log('[DAG] generateDagDiagram called, traceEvents.length:', traceEvents.value.length)
  console.log('[DAG] activeTab:', activeTab.value)
  
  if (traceEvents.value.length === 0) {
    console.log('[DAG] No trace events, skipping')
    dagMermaidSvg.value = ''
    return
  }

  // Build step nodes and dependencies based on execution order
  // Since we don't have explicit depends_on in trace, we infer sequential dependencies
  const steps = traceEvents.value.map((event, index) => ({
    id: `step${index + 1}`,
    name: getStepName(event, index),
    type: event.event_type,
    status: event.event_type === 'error' ? 'failed' : 'completed',
  }))

  console.log('[DAG] Built steps:', steps.map(s => s.name))

  // Build Mermaid graph definition
  let mermaidDef = 'graph TD\n'  // Changed from LR to TD (Top-Down)
  
  // Add styling classes
  mermaidDef += '  classDef completed fill:#dcfce7,stroke:#16a34a,color:#166534\n'
  mermaidDef += '  classDef failed fill:#fee2e2,stroke:#dc2626,color:#991b1b\n'
  mermaidDef += '  classDef running fill:#dbeafe,stroke:#2563eb,color:#1e40af\n'
  mermaidDef += '  classDef default fill:#f3f4f6,stroke:#9ca3af,color:#374151\n'
  // Arrow styling for better visibility
  mermaidDef += '  linkStyle default stroke:#94a3b8,stroke-width:2px\n\n'
  
  // Add nodes
  steps.forEach((step, index) => {
    const nodeId = `S${index + 1}`
    const statusClass = step.status === 'failed' ? 'failed' : 'completed'
    const shortName = step.name.length > 20 ? step.name.substring(0, 20) + '...' : step.name
    mermaidDef += `  ${nodeId}["${index + 1}. ${shortName}"]:::${statusClass}\n`
  })
  
  console.log('[DAG] Nodes added:', steps.map((s, i) => `S${i+1}: ${s.name}`))
  
  // Add edges (sequential dependencies)
  for (let i = 0; i < steps.length - 1; i++) {
    const current = `S${i + 1}`
    const next = `S${i + 2}`
    mermaidDef += `  ${current} --> ${next}\n`
  }

  console.log('[DAG] Edges added:', steps.length > 1 ? `${steps.length - 1} edges` : 'no edges (only 1 step)')
  console.log('[DAG] Full definition:', mermaidDef)

  console.log('[DAG] Mermaid definition generated')

  try {
    // Initialize mermaid with custom config
    mermaid.initialize({
      startOnLoad: false,
      theme: 'base',
      flowchart: {
        curve: 'basis',
        padding: 20,
        nodeSpacing: 30,     // Reduced spacing for vertical layout
        rankSpacing: 50,     // Vertical spacing between ranks
        useMaxWidth: true,   // Use full width
      },
      themeVariables: {
        fontSize: '14px',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      },
    })

    // Render the diagram
    const { svg } = await mermaid.render(`dag-${Date.now()}`, mermaidDef)
    console.log('[DAG] Successfully rendered SVG')
    dagMermaidSvg.value = svg
    
    // After rendering, ensure smooth transitions
    setTimeout(() => {
      const container = document.querySelector('.dag-container')
      if (container) {
        container.style.transition = 'opacity 0.3s ease-in-out'
      }
    }, 0)
  } catch (error) {
    console.error('[DAG] Failed to render diagram:', error)
    dagMermaidSvg.value = `<div class="text-destructive text-sm p-4">Failed to render diagram: ${(error as Error).message}</div>`
  }
}

function getToolName(toolId: string): string {
  void locale.value
  if (!toolId) return toolId
  // v1.5: trace stores skill_id in tool_id; builtin_<name> -> lookup by tool name
  const lookupId = toolId.startsWith('builtin_') ? toolId.slice(8) : toolId

  // For keys with dots like "file.read", vue-i18n interprets them as nested paths
  // So we need to access the messages object directly using bracket notation
  try {
    const currentLocale = i18n.locale.value
    const messages = (i18n as any).messages.value[currentLocale] || (i18n as any).messages.value.en
    const tools = messages?.agents?.tools
    // Access tool name using bracket notation to handle keys with dots
    if (tools && tools[lookupId]) {
      return tools[lookupId]
    }
  } catch (e) {
    // Fallback to t() function
  }
  
  // Try using t() function with the key
  const key = `agents.tools.${lookupId}`
  const translated = t(key)
  
  // If translation returns the key path itself (meaning not found), use fallback
  if (translated === key || translated.includes('agents.tools')) {
    // Fallback: format tool ID nicely (e.g., "file.read" -> "File Read")
    return lookupId.split('.').map(part => 
      part.charAt(0).toUpperCase() + part.slice(1)
    ).join(' ')
  }
  
  return translated
}

function getStepTypeLabel(event: AgentTraceEvent): string {
  void locale.value // depend on locale for reactivity
  if (event.event_type === 'tool_call' || event.event_type === 'skill_call') return t('agents.trace.step_type_tool')
  // V2/Kernel 使用 event_type "complete"，若有 skill_id 则按工具步骤展示
  if (event.event_type === 'complete' && (event.tool_id || (event.input_data && typeof event.input_data === 'object' && (event.input_data as Record<string, unknown>).skill_id))) {
    return t('agents.trace.step_type_tool')
  }
  if (event.event_type === 'llm_request') return t('agents.trace.step_type_llm')
  if (event.event_type === 'error') return t('agents.trace.step_type_error')
  if (event.event_type === 'final_answer') return t('agents.trace.step_type_llm')
  return event.event_type ? t('agents.trace.step_type_step') : t('agents.trace.step_type_step')
}

function getStepName(event: AgentTraceEvent, index: number): string {
  void locale.value // depend on locale for reactivity
  // tool_id 可能来自顶层，或 V2/Kernel trace 在 input_data.skill_id
  const skillOrToolId = event.tool_id ?? (event.input_data && typeof event.input_data === 'object' && (event.input_data as Record<string, unknown>).skill_id as string | undefined)
  if ((event.event_type === 'tool_call' || event.event_type === 'skill_call' || event.event_type === 'complete') && skillOrToolId) {
    return getToolName(skillOrToolId)
  }
  if (event.event_type === 'llm_request') return index === 0 ? t('agents.trace.step_planning') : t('agents.trace.step_synthesis')
  if (event.event_type === 'error') return t('agents.trace.step_error')
  if (event.event_type === 'final_answer') return t('agents.trace.step_synthesis')
  if (skillOrToolId) return getToolName(skillOrToolId)
  return event.event_type || t('agents.trace.step_index', { n: index + 1 })
}

function getStepDuration(event: AgentTraceEvent): string {
  void locale.value // depend on locale for reactivity
  const ms = event.duration_ms
  if (ms == null) return t('agents.trace.n_a')
  if (ms >= 1000) return t('agents.trace.duration_seconds', { n: (ms / 1000).toFixed(1) })
  return t('agents.trace.duration_milliseconds', { n: ms })
}

function isStepCompleted(event: AgentTraceEvent): boolean {
  return event.event_type !== 'error' && (event.output_data != null || event.event_type === 'final_answer')
}

const selectedEvent = computed(() =>
  traceEvents.value[selectedStepIndex.value] ?? null
)

const selectedStepStatus = computed(() => {
  void locale.value
  const e = selectedEvent.value
  if (!e) return t('agents.trace.n_a')
  if (e.event_type === 'error') return t('agents.trace.detail_error')
  return t('agents.trace.detail_success')
})

const endpointDisplay = computed(() => {
  void locale.value
  const e = selectedEvent.value
  if (!e?.input_data) return t('agents.trace.n_a')
  const d = e.input_data
  if (typeof d === 'object' && d?.url) return d.url
  if (typeof d === 'object' && d?.endpoint) return d.endpoint
  return t('agents.trace.n_a')
})

const methodDisplay = computed(() => {
  void locale.value
  const e = selectedEvent.value
  if (!e?.input_data) return t('agents.trace.n_a')
  const d = e.input_data
  if (typeof d === 'object' && d?.method) return String(d.method).toUpperCase()
  return t('agents.trace.n_a')
})

const inputJsonStr = computed(() => {
  const e = selectedEvent.value
  if (!e?.input_data) return '{}'
  try {
    return typeof e.input_data === 'string' ? e.input_data : JSON.stringify(e.input_data, null, 2)
  } catch {
    return '{}'
  }
})

const outputJsonStr = computed(() => {
  const e = selectedEvent.value
  if (e?.output_data === undefined) return '{}'
  try {
    const data = e.output_data
    if (typeof data === 'object' && data?.annotated_image) {
      const { annotated_image, ...rest } = data as Record<string, unknown>
      return JSON.stringify({ ...rest, annotated_image: '(base64 image, see below)' }, null, 2)
    }
    return typeof data === 'string' ? data : JSON.stringify(data ?? {}, null, 2)
  } catch {
    return '{}'
  }
})

const annotatedImageUrl = computed(() => {
  const e = selectedEvent.value
  if (!e?.output_data || typeof e.output_data !== 'object') return null
  const data = e.output_data as Record<string, unknown>
  const url = data?.annotated_image
  return typeof url === 'string' && url.startsWith('data:image/') ? url : null
})

const errorMessage = computed(() => {
  const e = selectedEvent.value
  if (e?.event_type !== 'error') return null
  if (e?.output_data && typeof e.output_data === 'string') return e.output_data
  if (e?.output_data && typeof e.output_data === 'object') return JSON.stringify(e.output_data)
  return e?.input_data ? String(e.input_data) : null
})

function goBack() {
  router.push({ name: 'agents-run', params: { id: agentId }, query: { session: sessionId.value } })
}

function goToRun() {
  router.push({ name: 'agents-run', params: { id: agentId }, query: { session: sessionId.value } })
}

async function copyTraceId() {
  try {
    await navigator.clipboard.writeText(traceIdDisplay.value)
    // could toast "Copied"
  } catch (_) {}
}

async function copyStepJson() {
  const e = selectedEvent.value
  if (!e) return
  try {
    const payload = { input: e.input_data, output: e.output_data }
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
  } catch (_) {}
}

async function copyInputJson() {
  try {
    await navigator.clipboard.writeText(inputJsonStr.value)
  } catch (_) {}
}

async function copyOutputJson() {
  try {
    await navigator.clipboard.writeText(outputJsonStr.value)
  } catch (_) {}
}

const TRACE_VERSION = 'V1.0.4'
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden font-sans">
    <!-- Header -->
    <header class="h-16 border-b border-border bg-muted px-6 flex items-center justify-between shrink-0 z-10">
      <div class="flex items-center gap-4">
        <button
          @click="goBack"
          class="p-2 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
          :title="t('agents.trace.back_to_run')"
        >
          <ArrowLeft class="w-5 h-5" />
        </button>
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
            <FileText class="w-4 h-4 text-primary" />
          </div>
          <div>
            <h1 class="text-lg font-bold text-foreground">{{ agent?.name || t('agents.trace.loading') }}</h1>
            <p class="text-xs text-muted-foreground">
              {{ t('agents.trace.trace_id') }}: <span class="font-mono text-foreground/90">{{ traceIdDisplay }}</span>
            </p>
          </div>
          <Badge :variant="statusBadgeVariant" class="text-[10px] font-black tracking-widest">
            {{ statusLabel }}
          </Badge>
        </div>
      </div>
      <div class="flex items-center gap-4">
        <span class="text-[10px] font-bold uppercase text-muted-foreground">
          {{ t('agents.trace.latency') }} <span class="text-foreground ml-1">{{ latencyDisplay }}</span>
        </span>
        <span class="text-[10px] font-bold uppercase text-muted-foreground">
          {{ t('agents.trace.steps') }} <span class="text-foreground ml-1">{{ stepsCount }}/{{ stepsCount }}</span>
        </span>
        <Button size="sm" class="gap-2 bg-blue-600 hover:bg-blue-700 text-white font-bold" @click="goToRun">
          <Play class="w-4 h-4" />
          {{ t('agents.trace.re_run') }}
        </Button>
        <button
          class="p-2 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
          :title="t('agents.trace.settings')"
        >
          <Settings class="w-5 h-5" />
        </button>
      </div>
    </header>

    <div class="flex-1 flex min-h-0">
      <!-- Left: Execution Timeline -->
      <aside class="w-72 border-r border-border bg-muted/30 flex flex-col shrink-0 overflow-hidden">
        <div class="p-4 border-b border-border">
          <h2 class="text-[11px] font-black text-muted-foreground uppercase tracking-[0.2em]">
            {{ t('agents.trace.execution_timeline') }}
          </h2>
        </div>
        <!-- Tab Switcher -->
        <div class="flex border-b border-border">
          <button
            @click="activeTab = 'timeline'"
            :class="[
              'flex-1 py-2 text-xs font-bold transition-colors',
              activeTab === 'timeline'
                ? 'bg-primary/10 text-primary border-b-2 border-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
            ]"
          >
            📋 {{ t('agents.trace.timeline') }}
          </button>
          <button
            @click="activeTab = 'dependencies'"
            :class="[
              'flex-1 py-2 text-xs font-bold transition-colors',
              activeTab === 'dependencies'
                ? 'bg-primary/10 text-primary border-b-2 border-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
            ]"
          >
            🔗 {{ t('agents.trace.dependencies') }}
          </button>
        </div>
        <div class="flex-1 overflow-y-auto p-2 space-y-1" v-show="activeTab === 'timeline'">
          <template v-if="loading">
            <div class="flex items-center justify-center py-12">
              <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          </template>
          <template v-else-if="traceEvents.length === 0">
            <p class="text-sm text-muted-foreground text-center py-8">{{ t('agents.trace.no_steps') }}</p>
          </template>
          <template v-else>
            <button
              v-for="(event, idx) in traceEvents"
              :key="event.event_id"
              @click="selectedStepIndex = idx"
              :class="[
                'w-full flex items-center gap-3 p-3 rounded-xl text-left transition-all border',
                selectedStepIndex === idx
                  ? 'bg-primary/10 border-primary/30 text-foreground'
                  : 'border-transparent hover:bg-muted/80 text-muted-foreground hover:text-foreground',
              ]"
            >
              <div
                :class="[
                  'w-8 h-8 rounded-lg flex items-center justify-center shrink-0',
                  selectedStepIndex === idx ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground',
                ]"
              >
                <Check v-if="isStepCompleted(event)" class="w-4 h-4 text-emerald-500" />
                <Zap v-else-if="selectedStepIndex === idx" class="w-4 h-4" />
                <Wrench v-else-if="event.event_type === 'tool_call' || event.event_type === 'skill_call'" class="w-4 h-4" />
                <FileText v-else class="w-4 h-4" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="text-xs font-bold text-foreground truncate">
                  {{ idx + 1 }}. {{ getStepName(event, idx) }}
                </div>
                <div class="text-[10px] text-muted-foreground mt-0.5">
                  {{ getStepTypeLabel(event) }}{{ t('agents.trace.duration_sep') }}{{ getStepDuration(event) }}
                </div>
              </div>
              <ChevronRight
                v-if="selectedStepIndex === idx"
                class="w-4 h-4 text-primary shrink-0"
              />
            </button>
          </template>
        </div>
        
        <!-- Dependencies View (DAG) -->
        <div class="flex-1 overflow-y-auto p-4" v-show="activeTab === 'dependencies'">
          <template v-if="loading">
            <div class="flex items-center justify-center py-12">
              <Loader2 class="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          </template>
          <template v-else-if="traceEvents.length === 0">
            <p class="text-sm text-muted-foreground text-center py-8">{{ t('agents.trace.no_dependencies') }}</p>
          </template>
          <template v-else>
            <div class="text-xs font-bold text-muted-foreground mb-2">
              {{ t('agents.trace.dag_description') }}
            </div>
            <div 
              v-html="dagMermaidSvg" 
              class="dag-container"
              style="min-height: 200px;"
            ></div>
            <div class="mt-4 space-y-2">
              <div class="flex items-center gap-2 text-xs">
                <div class="w-3 h-3 rounded bg-emerald-100 border border-emerald-500"></div>
                <span class="text-muted-foreground">{{ t('agents.trace.legend_completed') }}</span>
              </div>
              <div class="flex items-center gap-2 text-xs">
                <div class="w-3 h-3 rounded bg-red-100 border border-red-500"></div>
                <span class="text-muted-foreground">{{ t('agents.trace.legend_failed') }}</span>
              </div>
              <div class="flex items-center gap-2 text-xs">
                <svg width="20" height="8" class="text-foreground">
                  <line x1="0" y1="4" x2="20" y2="4" stroke="currentColor" stroke-width="2"/>
                  <polygon points="20,4 15,2 15,6" fill="currentColor"/>
                </svg>
                <span class="text-muted-foreground">{{ t('agents.trace.legend_depends_on') }}</span>
              </div>
            </div>
          </template>
        </div>
        <div class="p-3 border-t border-border">
          <Button variant="outline" size="sm" class="w-full gap-2" @click="copyTraceId">
            <Copy class="w-3.5 h-3.5" />
            {{ t('agents.trace.copy_trace_id') }}
          </Button>
        </div>
      </aside>

      <!-- Main: Step detail -->
      <main class="flex-1 flex flex-col min-w-0 overflow-y-auto bg-background">
        <template v-if="loading">
          <div class="flex items-center justify-center flex-1">
            <Loader2 class="w-8 h-8 animate-spin text-muted-foreground" />
          </div>
        </template>
        <template v-else-if="!selectedEvent">
          <div class="flex flex-col items-center justify-center flex-1 text-center p-8">
            <p class="text-muted-foreground">{{ t('agents.trace.select_step') }}</p>
          </div>
        </template>
        <template v-else>
          <div class="p-8 space-y-8">
            <!-- Step header -->
            <div class="flex items-start justify-between gap-4">
              <div>
                <h2 class="text-2xl font-bold text-foreground">{{ getStepName(selectedEvent, selectedStepIndex) }}</h2>
                <p class="text-sm text-muted-foreground mt-1">
                  {{ getStepTypeLabel(selectedEvent) }}{{ t('agents.trace.duration_sep') }}{{ getStepDuration(selectedEvent) }}
                </p>
              </div>
              <Button variant="outline" size="sm" class="gap-2 shrink-0" @click="copyStepJson">
                <Copy class="w-3.5 h-3.5" />
                {{ t('agents.trace.copy_json') }}
              </Button>
            </div>

            <!-- Overview cards -->
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div class="rounded-xl border border-border bg-card p-4">
                <div class="text-[10px] font-black text-muted-foreground uppercase tracking-wider mb-2">
                  {{ t('agents.trace.status') }}
                </div>
                <div class="flex items-center gap-2">
                  <Check
                    v-if="selectedEvent.event_type !== 'error'"
                    class="w-5 h-5 text-emerald-500 shrink-0"
                  />
                  <AlertCircle v-else class="w-5 h-5 text-destructive shrink-0" />
                  <span class="font-bold text-foreground">{{ selectedStepStatus }}</span>
                </div>
              </div>
              <div class="rounded-xl border border-border bg-card p-4">
                <div class="text-[10px] font-black text-muted-foreground uppercase tracking-wider mb-2">
                  {{ t('agents.trace.endpoint') }}
                </div>
                <span class="text-sm font-mono text-foreground break-all">{{ endpointDisplay }}</span>
              </div>
              <div class="rounded-xl border border-border bg-card p-4">
                <div class="text-[10px] font-black text-muted-foreground uppercase tracking-wider mb-2">
                  {{ t('agents.trace.method') }}
                </div>
                <span class="text-sm font-mono text-foreground">{{ methodDisplay }}</span>
              </div>
            </div>

            <!-- JSON Input -->
            <section class="space-y-2">
              <h3 class="text-xs font-black text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                <ChevronRight class="w-3.5 h-3.5 rotate-[-90deg]" />
                {{ t('agents.trace.json_input') }}
              </h3>
              <div class="relative rounded-xl border border-border bg-muted/50 p-4 font-mono text-xs overflow-x-auto">
                <pre class="whitespace-pre-wrap break-words text-foreground">{{ inputJsonStr }}</pre>
                <button
                  class="absolute top-2 right-2 p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground"
                  :title="t('agents.trace.copy_input')"
                  @click="copyInputJson"
                >
                  <Copy class="w-3.5 h-3.5" />
                </button>
              </div>
            </section>

            <!-- Annotated Image (vision.detect_objects) -->
            <section v-if="annotatedImageUrl" class="space-y-2">
              <h3 class="text-xs font-black text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                <ChevronRight class="w-3.5 h-3.5" />
                标注图
              </h3>
              <div class="rounded-xl border border-border bg-muted/50 p-4 flex justify-center">
                <img :src="annotatedImageUrl" alt="Annotated detection" class="max-w-full max-h-96 object-contain rounded-lg" />
              </div>
            </section>

            <!-- JSON Output -->
            <section class="space-y-2">
              <h3 class="text-xs font-black text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                <ChevronRight class="w-3.5 h-3.5" />
                {{ t('agents.trace.json_output') }}
              </h3>
              <div class="relative rounded-xl border border-border bg-muted/50 p-4 font-mono text-xs overflow-x-auto">
                <pre class="whitespace-pre-wrap break-words text-foreground">{{ outputJsonStr }}</pre>
                <button
                  class="absolute top-2 right-2 p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground"
                  :title="t('agents.trace.copy_output')"
                  @click="copyOutputJson"
                >
                  <Copy class="w-3.5 h-3.5" />
                </button>
              </div>
            </section>

            <!-- Error reference (when step is error) -->
            <section v-if="errorMessage" class="space-y-2">
              <h3 class="text-xs font-black text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                <AlertCircle class="w-3.5 h-3.5" />
                {{ t('agents.trace.error_reference') }}
              </h3>
              <div class="rounded-xl border border-destructive/30 bg-destructive/10 p-4">
                <p class="font-bold text-destructive">{{ errorMessage }}</p>
                <p class="text-xs text-muted-foreground mt-2">{{ t('agents.trace.error_reference_hint') }}</p>
              </div>
            </section>
          </div>
        </template>
      </main>
    </div>

    <!-- Footer -->
    <footer class="h-12 border-t border-border bg-muted px-6 flex items-center justify-between shrink-0 text-[10px] font-bold tracking-tight uppercase">
      <span class="text-muted-foreground">{{ t('agents.trace.version', { v: TRACE_VERSION }) }}</span>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" class="gap-2 h-8 text-[10px] font-bold">
          <Share2 class="w-3.5 h-3.5" />
          {{ t('agents.trace.export_trace') }}
        </Button>
        <Button variant="outline" size="sm" class="gap-2 h-8 text-[10px] font-bold">
          <AlertCircle class="w-3.5 h-3.5" />
          {{ t('agents.trace.report_issue') }}
        </Button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.dag-container {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  min-height: 300px;
  padding: 20px;
}

.dag-container :deep(svg) {
  max-width: 100%;
  height: auto;
  max-height: 500px;  /* Reduced for better vertical fit */
}

/* 禁用节点的悬停和点击效果，但保持可见 */
.dag-container :deep(.node),
.dag-container :deep(.node > *) {
  cursor: default !important;
  pointer-events: none !important;
}

/* 移除所有过渡动画，避免抖动 */
.dag-container :deep(.node),
.dag-container :deep(.node *),
.dag-container :deep(.edgePath),
.dag-container :deep(.edgePath *) {
  transition: none !important;
}

/* 确保悬停时不产生任何变化 */
.dag-container :deep(.node:hover) {
  transform: none !important;
  opacity: 1 !important;
}

.dag-container :deep(.edgePath),
.dag-container :deep(.edgePath *) {
  stroke-width: 2px;
  pointer-events: none !important;
}

/* 禁用 Mermaid 的默认交互样式 */
.dag-container :deep(.clickable),
.dag-container :deep(.cluster),
.dag-container :deep(.flowchart-link) {
  pointer-events: none !important;
  cursor: default !important;
}
</style>
