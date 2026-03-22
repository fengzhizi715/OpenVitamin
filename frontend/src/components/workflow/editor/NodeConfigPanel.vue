<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { X, Settings, Loader2, Trash2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Slider } from '@/components/ui/slider'
import { Textarea } from '@/components/ui/textarea'
import { listModels, listAgents, listTools, type ModelInfo, type AgentDefinition, type ToolInfo } from '@/services/api'
import type { Node, Edge } from '@vue-flow/core'
import type { WorkflowNodeData } from './types'

const { t } = useI18n()

const props = withDefaults(
  defineProps<{
    node: Node<WorkflowNodeData> | null
    selectedNodeId?: string | null
    edge?: Edge | null
    nodes?: Node<WorkflowNodeData>[]
    selectedModelId?: string
    selectedModelDisplayName?: string
    selectedAgentId?: string
    selectedAgentDisplayName?: string
  }>(),
  {
    selectedNodeId: () => null,
    nodes: () => [],
    selectedModelId: () => '',
    selectedModelDisplayName: () => '',
    selectedAgentId: () => '',
    selectedAgentDisplayName: () => '',
  }
)
/** 优先用 selectedNodeId 在 nodes 中查找；找不到时用父组件传入的 node（与 edge 一致，避免 drop 后短暂未同步时配置不显示） */
const resolvedNode = computed(() => {
  const nodes = props.nodes ?? []
  if (props.selectedNodeId) {
    const n = nodes.find((no) => no.id === props.selectedNodeId)
    if (n) return n
    if (props.node?.id === props.selectedNodeId) return props.node
  }
  return props.node ?? null
})
const emit = defineEmits<{
  close: []
  'update:config': [nodeId: string, config: Record<string, unknown>]
  'delete-node': [nodeId: string]
  'update:edge': [edgeId: string, patch: Record<string, unknown>]
  'delete-edge': [edgeId: string]
}>()

const config = () => resolvedNode.value?.data?.config ?? {}

/** Input 节点：input_key 仅允许字符串 */
const inputKeyValidationError = computed(() => {
  if (resolvedNode.value?.data?.type !== 'input') return ''
  const v = (resolvedNode.value?.data?.config as Record<string, unknown>)?.input_key
  if (v === undefined || v === null || v === '') return ''
  return typeof v === 'string' ? '' : t('workflow_editor.input_key_string_only')
})

/** Input 节点：fixed_input 必须是 JSON object（可为空） */
const inputFixedInputValidationError = computed(() => {
  if (resolvedNode.value?.data?.type !== 'input') return ''
  const v = (resolvedNode.value?.data?.config as Record<string, unknown>)?.fixed_input
  if (v === undefined || v === null) return ''
  if (typeof v !== 'object' || Array.isArray(v)) return t('workflow_editor.fixed_input_object_only')
  return ''
})

/** Output 节点：使用 expression 时 output_key 必填 */
const outputKeyValidationError = computed(() => {
  if (resolvedNode.value?.data?.type !== 'output') return ''
  const c = resolvedNode.value?.data?.config as Record<string, unknown> | undefined
  const expr = (c?.expression as string)?.trim?.() ?? ''
  const key = c?.output_key
  const keyStr = key === undefined || key === null ? '' : String(key).trim()
  if (expr === '' || keyStr !== '') return ''
  return t('workflow_editor.output_key_required_with_expression')
})

const selectedModelId = computed(() => {
  const fromNode = (resolvedNode.value?.data?.config as Record<string, unknown> | undefined)?.model_id
  const v = fromNode ?? props.selectedModelId
  return (v != null ? String(v) : '').trim()
})
const selectedAgentId = computed(() => {
  const fromNode = (resolvedNode.value?.data?.config as Record<string, unknown> | undefined)?.agent_id
  const v = fromNode ?? props.selectedAgentId
  return (v != null ? String(v) : '').trim()
})

const llmModels = ref<ModelInfo[]>([])
const loadingModels = ref(false)
const agents = ref<AgentDefinition[]>([])
const loadingAgents = ref(false)
const tools = ref<ToolInfo[]>([])
const loadingTools = ref(false)

const displayModelId = ref('')
const displayAgentId = ref('')

watch(selectedModelId, (v) => { displayModelId.value = v }, { immediate: true })
watch(selectedAgentId, (v) => { displayAgentId.value = v }, { immediate: true })
// When switching back to a node, sync dropdowns from node config after props have settled
watch(
  () => [resolvedNode.value?.id, resolvedNode.value?.data?.config],
  () => {
    nextTick(() => {
      displayModelId.value = selectedModelId.value
      displayAgentId.value = selectedAgentId.value
      syncAgentOutputSchemaRaw()
    })
  },
  { deep: true }
)

/** Agent output_schema 文本框原始内容，用于校验非法 JSON */
const agentOutputSchemaRaw = ref('')
const agentFixedInputRaw = ref('')
function syncAgentOutputSchemaRaw() {
  if (resolvedNode.value?.data?.type !== 'agent') {
    agentOutputSchemaRaw.value = ''
    return
  }
  const schema = (config() as Record<string, unknown>).output_schema
  if (typeof schema === 'object' && schema !== null) {
    try {
      agentOutputSchemaRaw.value = JSON.stringify(schema, null, 2)
    } catch {
      agentOutputSchemaRaw.value = ''
    }
  } else {
    agentOutputSchemaRaw.value = ''
  }
}
function syncAgentFixedInputRaw() {
  if (resolvedNode.value?.data?.type !== 'agent') {
    agentFixedInputRaw.value = ''
    return
  }
  const fixed = (config() as Record<string, unknown>).fixed_input
  if (typeof fixed === 'object' && fixed !== null) {
    try {
      agentFixedInputRaw.value = JSON.stringify(fixed, null, 2)
    } catch {
      agentFixedInputRaw.value = ''
    }
  } else {
    agentFixedInputRaw.value = ''
  }
}
watch(
  () => [resolvedNode.value?.data?.type, (resolvedNode.value?.data?.config as Record<string, unknown>)?.output_schema],
  () => { syncAgentOutputSchemaRaw() },
  { immediate: true }
)
watch(
  () => [resolvedNode.value?.data?.type, (resolvedNode.value?.data?.config as Record<string, unknown>)?.fixed_input],
  () => { syncAgentFixedInputRaw() },
  { immediate: true }
)
function onAgentOutputSchemaInput(raw: string) {
  agentOutputSchemaRaw.value = raw
  const s = raw?.trim()
  if (!s) {
    updateConfig('output_schema', undefined)
    return
  }
  try {
    const parsed = JSON.parse(s)
    updateConfig('output_schema', parsed)
  } catch {
    // 保持不更新 config，agentConfigErrors 会显示非法 JSON
  }
}
function onAgentFixedInputInput(raw: string) {
  agentFixedInputRaw.value = raw
  const s = raw?.trim()
  if (!s) {
    updateConfig('fixed_input', undefined)
    return
  }
  try {
    const parsed = JSON.parse(s)
    updateConfig('fixed_input', parsed)
  } catch {
    // 保持不更新 config，agentConfigErrors 会显示非法 JSON
  }
}

/** Input 节点 fixed_input 文本框原始内容 */
const inputFixedInputRaw = ref('')
const inputFixedInputParseError = ref('')
function syncInputFixedInputRaw() {
  if (resolvedNode.value?.data?.type !== 'input') {
    inputFixedInputRaw.value = ''
    inputFixedInputParseError.value = ''
    return
  }
  const fixed = (config() as Record<string, unknown>).fixed_input
  if (typeof fixed === 'object' && fixed !== null) {
    try {
      inputFixedInputRaw.value = JSON.stringify(fixed, null, 2)
      inputFixedInputParseError.value = ''
    } catch {
      inputFixedInputRaw.value = ''
      inputFixedInputParseError.value = 'fixed_input JSON 序列化失败，请重新输入'
    }
  } else {
    inputFixedInputRaw.value = ''
    inputFixedInputParseError.value = ''
  }
}
watch(
  () => [resolvedNode.value?.data?.type, (resolvedNode.value?.data?.config as Record<string, unknown>)?.fixed_input],
  () => { syncInputFixedInputRaw() },
  { immediate: true }
)
function onInputFixedInputInput(raw: string) {
  inputFixedInputRaw.value = raw
  const s = raw?.trim()
  if (!s) {
    updateConfig('fixed_input', undefined)
    inputFixedInputParseError.value = ''
    return
  }
  try {
    const parsed = JSON.parse(s)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      inputFixedInputParseError.value = t('workflow_editor.fixed_input_parse_error')
      return
    }
    inputFixedInputParseError.value = ''
    updateConfig('fixed_input', parsed as Record<string, unknown>)
  } catch {
    inputFixedInputParseError.value = 'JSON 格式错误，请检查逗号、引号和大括号'
  }
}

async function loadLlmVlmModels() {
  loadingModels.value = true
  try {
    const res = await listModels()
    const list = res.data ?? []
    llmModels.value = list.filter(
      (m) => m.model_type === 'llm' || m.model_type === 'vlm'
    )
  } catch {
    llmModels.value = []
  } finally {
    loadingModels.value = false
  }
}

async function loadAgents() {
  loadingAgents.value = true
  try {
    const res = await listAgents()
    agents.value = res.data ?? []
  } catch {
    agents.value = []
  } finally {
    loadingAgents.value = false
  }
}

async function loadTools() {
  loadingTools.value = true
  try {
    const res = await listTools()
    tools.value = res.data ?? []
  } catch {
    tools.value = []
  } finally {
    loadingTools.value = false
  }
}

watch(
  () => resolvedNode.value?.data?.type,
  (type) => {
    if (type === 'llm') loadLlmVlmModels()
    if (type === 'agent') loadAgents()
    if (type === 'skill') loadTools()
  },
  { immediate: true }
)
onMounted(() => {
  if (resolvedNode.value?.data?.type === 'llm') loadLlmVlmModels()
  if (resolvedNode.value?.data?.type === 'agent') loadAgents()
  if (resolvedNode.value?.data?.type === 'skill') loadTools()
})

function updateConfig(key: string, value: unknown) {
  if (!resolvedNode.value) return
  const next = { ...config(), [key]: value }
  emit('update:config', resolvedNode.value.id, next)
}

const conditionExprVars = [
  { label: 'Input Query', expr: '${input.query}' },
  { label: 'Workflow Query', expr: '${global.input_data.query}' },
  { label: 'Previous Output', expr: '${prev}' },
  { label: 'Previous Query', expr: '${prev.query}' },
]

function insertConditionExpr(token: string) {
  const current = String((config().condition_expression as string) ?? '').trim()
  const next = current ? `${current} ${token}` : token
  updateConfig('condition_expression', next)
}

function onClose() {
  emit('close')
}

const canDeleteNode = () => resolvedNode.value != null && resolvedNode.value.data?.type !== 'start'
const canDeleteEdge = () => props.edge != null

function onDeleteNode() {
  if (!resolvedNode.value || resolvedNode.value.data?.type === 'start') return
  emit('delete-node', resolvedNode.value.id)
}

function onDeleteEdge() {
  if (!props.edge) return
  emit('delete-edge', currentEdgeId.value)
}

function modelDisplayName(m: ModelInfo) {
  return m.display_name || m.name || m.id
}

function agentDisplayName(a: AgentDefinition) {
  return a.name || a.agent_id
}

const selectedTool = computed(() => {
  const name = String((config().tool_name as string) ?? (config().tool_id as string) ?? '')
  if (!name) return null
  return tools.value.find((tool) => tool.name === name) ?? null
})

const currentNodeId = computed(() => resolvedNode.value?.id ?? '')
const currentEdgeId = computed(() => props.edge?.id ?? '')
const currentEdgeData = computed<Record<string, unknown>>(() => ((props.edge?.data as Record<string, unknown>) || {}))

const edgeSourceNodeType = computed(() => {
  const sourceId = props.edge?.source
  if (!sourceId) return ''
  return props.nodes?.find((n) => n.id === sourceId)?.data?.type || ''
})

const edgeTriggerOptions = computed<Array<{ value: string; label: string }>>(() => {
  if (edgeSourceNodeType.value === 'condition') {
    return [
      { value: 'true', label: 'condition_true' },
      { value: 'false', label: 'condition_false' },
    ]
  }
  if (edgeSourceNodeType.value === 'loop') {
    return [
      { value: 'continue', label: 'loop_continue' },
      { value: 'exit', label: 'loop_exit' },
    ]
  }
  return [
    { value: 'success', label: 'success' },
    { value: 'failure', label: 'failure' },
    { value: 'always', label: 'always' },
  ]
})

const edgeTriggerValue = computed(() => {
  const label = String(props.edge?.label || '').trim()
  if (label) return label
  const handle = String(props.edge?.sourceHandle || '').trim()
  if (handle && ['true', 'false', 'continue', 'exit'].includes(handle)) return handle
  return edgeTriggerOptions.value[0]?.value || 'success'
})

const edgeValidationError = computed(() => {
  if (!props.edge) return ''
  const trigger = edgeTriggerValue.value
  if (edgeSourceNodeType.value === 'condition' && !['true', 'false'].includes(trigger)) {
    return t('workflow_editor.condition_edge_trigger_error')
  }
  if (edgeSourceNodeType.value === 'loop' && !['continue', 'exit'].includes(trigger)) {
    return 'Loop node edges must use loop_continue or loop_exit trigger.'
  }
  if (
    edgeSourceNodeType.value !== 'condition' &&
    edgeSourceNodeType.value !== 'loop' &&
    ['true', 'false', 'continue', 'exit'].includes(trigger)
  ) {
    return 'This trigger is only valid for condition/loop source nodes.'
  }
  return ''
})

function updateEdgeTrigger(value: string) {
  const specialHandle = ['true', 'false', 'continue', 'exit'].includes(value) ? value : null
  emit('update:edge', currentEdgeId.value, {
    label: value,
    sourceHandle: specialHandle,
  })
}

/** Agent 节点配置校验（编辑器内表单校验） */
const agentConfigErrors = computed(() => {
  if (resolvedNode.value?.data?.type !== 'agent') return []
  const c = config() as Record<string, unknown>
  const errs: string[] = []
  const aid = (c.agent_id as string)?.trim()
  if (!aid) errs.push('请选择要调用的 Agent（必填）')
  const timeout = c.timeout
  if (timeout !== undefined && timeout !== null && timeout !== '') {
    const n = Number(timeout)
    if (Number.isNaN(n) || n < 0) errs.push('Timeout 须为非负整数（秒）')
  }
  const maxSteps = c.max_steps
  if (maxSteps !== undefined && maxSteps !== null && maxSteps !== '') {
    const n = Number(maxSteps)
    if (Number.isNaN(n) || n < 1 || n > 50) errs.push(t('workflow_editor.agent_max_steps_error'))
  }
  if (agentOutputSchemaRaw.value.trim()) {
    try {
      const parsed = JSON.parse(agentOutputSchemaRaw.value)
      if (typeof parsed !== 'object' || parsed === null) errs.push(t('workflow_editor.output_schema_object_only'))
      else if (parsed.type !== undefined && parsed.type !== 'object') errs.push(t('workflow_editor.output_schema_object_suggestion'))
    } catch {
      errs.push(t('workflow_editor.output_schema_valid_json'))
    }
  }
  if (agentFixedInputRaw.value.trim()) {
    try {
      const parsed = JSON.parse(agentFixedInputRaw.value)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        errs.push(t('workflow_editor.default_input_object_only'))
      }
    } catch {
      errs.push(t('workflow_editor.default_input_valid_json'))
    }
  }
  return errs
})

const toolInputSchema = computed<Record<string, any>>(() => {
  return (selectedTool.value?.input_schema as Record<string, any>) || {}
})

const toolSchemaProperties = computed<[string, Record<string, any>][]>(() => {
  const props = toolInputSchema.value?.properties
  if (!props || typeof props !== 'object') return []
  return Object.entries(props as Record<string, Record<string, any>>)
})

function currentToolInputs(): Record<string, unknown> {
  return ((config().inputs as Record<string, unknown>) || {})
}

function updateToolInputField(key: string, value: unknown) {
  const nextInputs = { ...currentToolInputs(), [key]: value }
  emit('update:config', currentNodeId.value, { ...config(), inputs: nextInputs })
}

function readToolInputField(key: string, schema: Record<string, any>): string | number {
  const value = currentToolInputs()[key]
  if (value == null) {
    if (schema.default != null) return schema.default
    return schema.type === 'number' || schema.type === 'integer' ? 0 : ''
  }
  if (typeof value === 'number') return value
  if (typeof value === 'boolean') return value ? 1 : 0
  return String(value)
}

function parseToolInputValue(raw: string, schema: Record<string, any>): unknown {
  if (schema.type === 'integer') {
    const parsed = parseInt(raw, 10)
    return Number.isNaN(parsed) ? schema.default ?? 0 : parsed
  }
  if (schema.type === 'number') {
    const parsed = parseFloat(raw)
    return Number.isNaN(parsed) ? schema.default ?? 0 : parsed
  }
  if (schema.type === 'boolean') {
    return raw === 'true'
  }
  return raw
}
</script>

<template>
  <div class="flex flex-col h-full bg-card border-l border-border/50 overflow-hidden">
    <div class="flex items-center justify-between px-4 py-3 border-b border-border/50 shrink-0">
      <div class="flex items-center gap-2">
        <Settings class="w-4 h-4 text-muted-foreground" />
        <h2 class="text-sm font-semibold text-foreground">
          {{ resolvedNode ? t('workflow_editor.node_config_title', { name: resolvedNode.data?.label }) : edge ? t('workflow_editor.edge_config_title', { id: currentEdgeId }) : t('workflow_editor.node_config_empty') }}
        </h2>
      </div>
      <Button variant="ghost" size="icon" class="h-8 w-8" @click="onClose">
        <X class="w-4 h-4" />
      </Button>
    </div>
    <div v-if="!resolvedNode && !edge" class="flex-1 flex items-center justify-center text-muted-foreground text-sm px-4">
      {{ t('workflow_editor.node_config_select') }}
    </div>
    <div v-else class="flex-1 overflow-y-auto p-4 space-y-5 flex flex-col">
      <template v-if="edge && !resolvedNode">
        <div class="space-y-2">
          <label class="text-sm font-medium leading-none">{{ t('workflow_editor.edge_trigger') }}</label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="option in edgeTriggerOptions"
              :key="option.value"
              type="button"
              class="px-2.5 py-1.5 rounded-md border text-xs transition-colors"
              :class="edgeTriggerValue === option.value ? 'bg-blue-600 text-white border-blue-600' : 'bg-background text-foreground border-input hover:bg-muted/40'"
              @click="updateEdgeTrigger(option.value)"
            >
              {{ option.label }}
            </button>
          </div>
          <p v-if="edgeValidationError" class="text-xs text-red-500">
            {{ edgeValidationError }}
          </p>
        </div>
        <div class="space-y-2">
          <label class="text-sm font-medium leading-none">{{ t('workflow_editor.edge_condition') }}</label>
          <Input
            :model-value="(currentEdgeData.condition as string) ?? ''"
            :placeholder="t('workflow_editor.edge_condition_placeholder')"
            @update:model-value="(value) => emit('update:edge', currentEdgeId, { data: { ...currentEdgeData, condition: value } })"
          />
          <p class="text-xs text-muted-foreground">{{ t('workflow_editor.edge_condition_hint') }}</p>
        </div>
      </template>

      <!-- Start：仅说明，无配置项，避免误走 skill 等分支 -->
      <template v-else-if="resolvedNode && resolvedNode.data?.type === 'start'">
        <p class="text-sm text-muted-foreground">{{ t('workflow_editor.node_config_no_options') }}</p>
      </template>

      <!-- LLM：Basic / Runtime 分组折叠，仅 Basic 默认展开 -->
      <template v-else-if="resolvedNode && resolvedNode.data?.type === 'llm'">
        <details class="config-section border rounded-lg border-border/60 bg-muted/20" open>
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_basic') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
        <div class="space-y-2">
          <label class="text-sm font-medium leading-none">{{ t('workflow_editor.llm_model_name') }}</label>
          <select
            v-model="displayModelId"
            class="flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="loadingModels"
            @change="(e: Event) => {
              const v = (e.target as HTMLSelectElement).value
              const m = llmModels.find((x) => x.id === v)
              const patch: Record<string, unknown> = {
                model_id: v || undefined,
                model_display_name: m ? modelDisplayName(m) : '',
                // 归一化：切换模型时清理 legacy 字段
                model: undefined,
              }
              emit('update:config', currentNodeId, { ...config(), ...patch })
            }"
          >
            <option value="">{{ t('workflow_editor.llm_model_placeholder') }}</option>
            <option
              v-for="m in llmModels"
              :key="m.id"
              :value="m.id"
            >
              {{ modelDisplayName(m) }}{{ m.backend ? ` (${m.backend})` : '' }}
            </option>
          </select>
          <p v-if="loadingModels" class="text-xs text-muted-foreground flex items-center gap-1">
            <Loader2 class="w-3 h-3 animate-spin" />
            {{ t('workflow_editor.llm_models_loading') }}
          </p>
          <p v-else-if="llmModels.length === 0" class="text-xs text-muted-foreground">
            {{ t('workflow_editor.llm_models_empty') }}
          </p>
        </div>
        <div class="space-y-2">
          <label class="text-sm font-medium leading-none">{{ t('workflow_editor.llm_temperature') }}: {{ (config().temperature as number) ?? 0.7 }}</label>
          <Slider
            :model-value="[(config().temperature as number) ?? 0.7]"
            :min="0"
            :max="2"
            :step="0.1"
            @update:model-value="(v: number[] | undefined) => updateConfig('temperature', v?.[0] ?? 0.7)"
          />
          <p class="text-xs text-muted-foreground">0.0 ({{ t('workflow_editor.precise') }}) — 2.0 ({{ t('workflow_editor.creative') }})</p>
        </div>
        <div class="space-y-2">
          <label class="text-sm font-medium leading-none">{{ t('workflow_editor.llm_top_p') }}</label>
          <Input
            type="number"
            step="0.1"
            :model-value="(config().top_p as number) ?? 0.9"
            @update:model-value="updateConfig('top_p', parseFloat($event as string) || 0.9)"
          />
        </div>
        <div class="space-y-2">
          <label class="text-sm font-medium leading-none">{{ t('workflow_editor.llm_max_tokens') }}</label>
          <Input
            type="number"
            :model-value="(config().max_tokens as number) ?? 2048"
            @update:model-value="updateConfig('max_tokens', parseInt($event as string, 10) || 2048)"
          />
        </div>
          </div>
        </details>
        <details class="config-section border rounded-lg border-border/60 bg-muted/20 mt-2">
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_runtime') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
        <div class="space-y-2">
          <label class="text-sm font-medium leading-none">{{ t('workflow_editor.input_variables') }}</label>
          <p class="text-xs text-muted-foreground">{{ t('workflow_editor.input_variables_hint') }}</p>
        </div>
        <div class="space-y-2">
          <label class="text-sm font-medium leading-none">{{ t('workflow_editor.output_mapping') }}</label>
          <p class="text-xs text-muted-foreground">{{ t('workflow_editor.output_mapping_example') }}</p>
        </div>
        <Button variant="outline" size="sm" class="w-full">
          {{ t('workflow_editor.preview_prompt') }}
        </Button>
          </div>
        </details>
      </template>

      <!-- Agent：Basic / Runtime / Schema 分组折叠，仅 Basic 默认展开 -->
      <template v-else-if="resolvedNode && resolvedNode.data?.type === 'agent'">
        <div class="space-y-3">
          <div v-if="agentConfigErrors.length" class="rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400 space-y-1">
            <p class="font-medium">{{ t('workflow_editor.config_validation') }}</p>
            <ul class="list-disc list-inside">
              <li v-for="(msg, i) in agentConfigErrors" :key="i">{{ msg }}</li>
            </ul>
          </div>
          <details class="config-section border rounded-lg border-border/60 bg-muted/20" open>
            <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
              <span>{{ t('workflow_editor.section_basic') }}</span>
              <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
            </summary>
            <div class="px-3 pb-3 pt-0 space-y-2">
          <div class="space-y-2">
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.agent_select') }} <span class="text-destructive">*</span></label>
            <select
              v-model="displayAgentId"
              class="flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="loadingAgents"
              @change="(e: Event) => {
                const v = (e.target as HTMLSelectElement).value
                const a = agents.find((x) => x.agent_id === v)
                const patch: Record<string, unknown> = { agent_id: v, agent_display_name: a ? agentDisplayName(a) : '' }
                emit('update:config', currentNodeId, { ...config(), ...patch })
              }"
            >
              <option value="">{{ t('workflow_editor.agent_placeholder') }}</option>
              <option
                v-for="a in agents"
                :key="a.agent_id"
                :value="a.agent_id"
              >
                {{ agentDisplayName(a) }}
              </option>
            </select>
            <p v-if="loadingAgents" class="text-xs text-muted-foreground flex items-center gap-1">
              <Loader2 class="w-3 h-3 animate-spin" />
              {{ t('workflow_editor.agent_loading') }}
            </p>
            <p v-else-if="agents.length === 0" class="text-xs text-muted-foreground">
              {{ t('workflow_editor.agent_empty') }}
            </p>
          </div>
            </div>
          </details>
          <details class="config-section border rounded-lg border-border/60 bg-muted/20 mt-2">
            <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
              <span>{{ t('workflow_editor.section_runtime') }}</span>
              <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
            </summary>
            <div class="px-3 pb-3 pt-0 space-y-3">
            <div class="space-y-2">
              <label class="text-xs font-medium">{{ t('workflow_editor.agent_timeout_seconds') }}</label>
              <Input
                :model-value="String((config().timeout as number) ?? (config().agent_timeout_seconds as number) ?? '')"
                type="number"
                min="0"
                step="1"
                :placeholder="t('workflow_editor.default_placeholder')"
                class="h-9"
                @update:model-value="(v) => {
                  if ((v as string) === '') {
                    emit('update:config', currentNodeId, { ...config(), timeout: undefined, agent_timeout_seconds: undefined })
                    return
                  }
                  const n = Number(v)
                  if (!Number.isNaN(n) && n >= 0) {
                    emit('update:config', currentNodeId, { ...config(), timeout: n, agent_timeout_seconds: undefined })
                  }
                }"
              />
            </div>
            <div class="space-y-2">
              <label class="text-xs font-medium">{{ t('workflow_editor.agent_max_steps') }}</label>
              <Input
                :model-value="String((config().max_steps as number) ?? '')"
                type="number"
                min="1"
                step="1"
                :placeholder="t('workflow_editor.default_placeholder')"
                class="h-9"
                @update:model-value="(v) => {
                  if ((v as string) === '') { updateConfig('max_steps', undefined); return }
                  const n = Number(v)
                  if (!Number.isNaN(n) && n >= 1 && n <= 50) updateConfig('max_steps', n)
                }"
              />
            </div>
            <div class="space-y-2">
              <label class="text-xs font-medium">{{ t('workflow_editor.agent_model_override') }}</label>
              <Input
                :model-value="(config().model_override as string) ?? ''"
                :placeholder="t('workflow_editor.agent_model_override_placeholder')"
                class="h-9"
                @update:model-value="(v) => updateConfig('model_override', (v as string)?.trim() || undefined)"
              />
            </div>
            <div class="space-y-2">
              <label class="text-xs font-medium">{{ t('workflow_editor.agent_pass_context_keys') }}</label>
              <Input
                :model-value="Array.isArray(config().pass_context_keys) ? (config().pass_context_keys as string[]).join(', ') : (config().pass_context_keys as string) ?? ''"
                :placeholder="t('workflow_editor.agent_pass_context_keys_placeholder')"
                class="h-9"
                @update:model-value="(v) => {
                  const s = (v as string)?.trim()
                  updateConfig('pass_context_keys', s ? s.split(',').map((k) => k.trim()).filter(Boolean) : undefined)
                }"
              />
            </div>
            <div class="space-y-2">
              <label class="text-xs font-medium">{{ t('workflow_editor.agent_fixed_input') }}</label>
              <Textarea
                :model-value="agentFixedInputRaw"
              :placeholder="t('workflow_editor.agent_fixed_input_placeholder')"
                rows="4"
                class="text-xs font-mono"
                @update:model-value="onAgentFixedInputInput"
              />
              <p class="text-xs text-muted-foreground">{{ t('workflow_editor.agent_fixed_input_hint') }}</p>
            </div>
            </div>
          </details>
          <details class="config-section border rounded-lg border-border/60 bg-muted/20 mt-2">
            <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
              <span>{{ t('workflow_editor.section_schema') }}</span>
              <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
            </summary>
            <div class="px-3 pb-3 pt-0 space-y-2">
            <div class="space-y-2">
              <label class="text-xs font-medium">{{ t('workflow_editor.agent_output_schema') }}</label>
              <Textarea
                :model-value="agentOutputSchemaRaw"
                :placeholder="t('workflow_editor.schema_placeholder')"
                rows="4"
                class="text-xs font-mono"
                @update:model-value="onAgentOutputSchemaInput"
              />
              <p class="text-xs text-muted-foreground">{{ t('workflow_editor.agent_output_schema_hint') }}</p>
            </div>
            </div>
          </details>
        </div>
      </template>

      <!-- Prompt Template：Basic 分组 -->
      <template v-else-if="resolvedNode && resolvedNode.data?.type === 'prompt_template'">
        <details class="config-section border rounded-lg border-border/60 bg-muted/20" open>
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_basic') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.prompt_template') }}</label>
            <Textarea
              :model-value="(config().template as string) ?? ''"
              :placeholder="t('workflow_editor.prompt_template_placeholder')"
              rows="8"
              @update:model-value="updateConfig('template', $event)"
            />
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.prompt_role') }}</label>
            <Input
              :model-value="(config().role as string) ?? 'user'"
              :placeholder="t('workflow_editor.prompt_role_placeholder')"
              @update:model-value="updateConfig('role', $event)"
            />
          </div>
        </details>
      </template>

      <!-- Skill：Basic / Schema·Inputs 分组折叠，仅 Basic 默认展开 -->
      <template v-else-if="resolvedNode && resolvedNode.data?.type === 'skill'">
        <details class="config-section border rounded-lg border-border/60 bg-muted/20" open>
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_basic') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
          <label class="text-sm font-medium leading-none">{{ t('workflow_editor.skill_tool') }}</label>
          <select
            class="flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
            :disabled="loadingTools"
            :value="(config().tool_name as string) ?? (config().tool_id as string) ?? ''"
            @change="(e: Event) => {
              const v = (e.target as HTMLSelectElement).value
              const tool = tools.find((x) => x.name === v)
              emit('update:config', currentNodeId, {
                ...config(),
                tool_name: v,
                tool_id: v,
                tool_display_name: tool?.ui?.display_name || tool?.name || v,
              })
            }"
          >
            <option value="">{{ t('workflow_editor.skill_tool_placeholder') }}</option>
            <option v-for="tool in tools" :key="tool.name" :value="tool.name">
              {{ tool.ui?.display_name || tool.name }}
            </option>
          </select>
          </div>
        </details>
        <details class="config-section border rounded-lg border-border/60 bg-muted/20 mt-2">
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_schema_inputs') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0">
        <template v-if="toolSchemaProperties.length > 0">
          <div class="space-y-3">
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.skill_tool_inputs') }}</label>
            <div
              v-for="[fieldName, schema] in toolSchemaProperties"
              :key="fieldName"
              class="space-y-2"
            >
              <label class="text-xs font-medium text-muted-foreground">
                {{ fieldName }}
                <span v-if="Array.isArray(toolInputSchema.required) && toolInputSchema.required.includes(fieldName)" class="text-destructive">*</span>
              </label>
              <select
                v-if="Array.isArray(schema.enum)"
                class="flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
                :value="String(currentToolInputs()[fieldName] ?? schema.default ?? '')"
                @change="(e: Event) => updateToolInputField(fieldName, parseToolInputValue((e.target as HTMLSelectElement).value, schema))"
              >
                <option v-for="option in schema.enum" :key="String(option)" :value="String(option)">
                  {{ String(option) }}
                </option>
              </select>
              <Textarea
                v-else-if="schema.type === 'object' || schema.type === 'array'"
                :model-value="JSON.stringify((currentToolInputs()[fieldName] ?? schema.default ?? (schema.type === 'array' ? [] : {})), null, 2)"
                rows="4"
                @update:model-value="(value) => {
                  try {
                    updateToolInputField(fieldName, JSON.parse(String(value || (schema.type === 'array' ? '[]' : '{}'))))
                  } catch {
                    // ignore invalid JSON until valid
                  }
                }"
              />
              <div v-else-if="schema.type === 'boolean'" class="flex items-center gap-2">
                <input
                  type="checkbox"
                  class="h-4 w-4"
                  :checked="Boolean(currentToolInputs()[fieldName] ?? schema.default ?? false)"
                  @change="(e: Event) => updateToolInputField(fieldName, (e.target as HTMLInputElement).checked)"
                />
                <span class="text-sm">{{ schema.description || t('workflow_editor.enabled') }}</span>
              </div>
              <Input
                v-else
                :type="schema.type === 'number' || schema.type === 'integer' ? 'number' : 'text'"
                :model-value="readToolInputField(fieldName, schema)"
                :placeholder="schema.description || fieldName"
                @update:model-value="(value) => updateToolInputField(fieldName, parseToolInputValue(String(value ?? ''), schema))"
              />
              <p v-if="schema.description" class="text-xs text-muted-foreground">{{ schema.description }}</p>
            </div>
          </div>
        </template>
        <div v-else class="space-y-2">
          <label class="text-sm font-medium leading-none">{{ t('workflow_editor.skill_tool_inputs_json') }}</label>
          <Textarea
            :model-value="JSON.stringify((config().inputs as Record<string, unknown>) ?? {}, null, 2)"
            rows="8"
            :placeholder="t('workflow_editor.skill_tool_inputs_json_placeholder')"
            @update:model-value="(value) => {
              try {
                updateConfig('inputs', JSON.parse(String(value || '{}')))
              } catch {
                // keep textarea editable; persist only valid JSON
              }
            }"
          />
        </div>
          </div>
        </details>
      </template>

      <!-- Shell：Basic 分组 -->
      <template v-else-if="resolvedNode && resolvedNode.data?.type === 'shell'">
        <details class="config-section border rounded-lg border-border/60 bg-muted/20" open>
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_basic') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.shell_command') }}</label>
            <Textarea
              :model-value="(config().command as string) ?? ''"
              :placeholder="t('workflow_editor.shell_command_placeholder')"
              rows="8"
              @update:model-value="updateConfig('command', $event)"
            />
          </div>
        </details>
      </template>

      <!-- Condition：Basic 分组 -->
      <template v-else-if="resolvedNode && resolvedNode.data?.type === 'condition'">
        <details class="config-section border rounded-lg border-border/60 bg-muted/20" open>
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_basic') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.condition_expression') }}</label>
            <Input
              :model-value="(config().condition_expression as string) ?? ''"
              :placeholder="t('workflow_editor.condition_expression_placeholder')"
              @update:model-value="updateConfig('condition_expression', $event)"
            />
            <div class="flex flex-wrap gap-2">
              <Button
                v-for="item in conditionExprVars"
                :key="item.label"
                type="button"
                variant="outline"
                size="sm"
                class="h-7 px-2 text-[11px]"
                @click="insertConditionExpr(item.expr)"
              >
                {{ item.label }}
              </Button>
            </div>
            <p class="text-xs text-muted-foreground">
              {{ t('workflow_editor.condition_expression_hint') }}
            </p>
          </div>
        </details>
      </template>

      <!-- Loop：Basic / Runtime 分组折叠 -->
      <template v-else-if="resolvedNode && resolvedNode.data?.type === 'loop'">
        <details class="config-section border rounded-lg border-border/60 bg-muted/20" open>
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_basic') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.loop_type') }}</label>
            <select
              class="flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
              :value="(config().loop_type as string) ?? 'condition'"
              @change="(e: Event) => updateConfig('loop_type', (e.target as HTMLSelectElement).value)"
            >
              <option value="condition">{{ t('workflow_editor.loop_type_condition') }}</option>
              <option value="fixed">{{ t('workflow_editor.loop_type_fixed') }}</option>
            </select>
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.condition_expression') }}</label>
            <Input
              :model-value="(config().condition_expression as string) ?? ''"
              :placeholder="t('workflow_editor.loop_condition_placeholder')"
              @update:model-value="updateConfig('condition_expression', $event)"
            />
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.loop_max_iterations') }}</label>
            <Input
              type="number"
              :model-value="(config().max_iterations as number) ?? 5"
              @update:model-value="updateConfig('max_iterations', parseInt(String($event), 10) || 5)"
            />
          </div>
        </details>
        <details class="config-section border rounded-lg border-border/60 bg-muted/20 mt-2">
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_runtime') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.loop_timeout_seconds') }}</label>
            <Input
              type="number"
              :model-value="(config().timeout_seconds as number) ?? 300"
              @update:model-value="updateConfig('timeout_seconds', parseInt(String($event), 10) || 300)"
            />
            <div class="flex items-center gap-2">
              <input
                type="checkbox"
                class="h-4 w-4"
                :checked="Boolean((config().audit_log as boolean) ?? true)"
                @change="(e: Event) => updateConfig('audit_log', (e.target as HTMLInputElement).checked)"
              />
              <span class="text-sm">{{ t('workflow_editor.loop_enable_audit_log') }}</span>
            </div>
            <p class="text-xs text-muted-foreground">
              {{ t('workflow_editor.loop_runtime_hint') }}
            </p>
          </div>
        </details>
      </template>

      <!-- Input：Basic / Schema 分组折叠 -->
      <template v-else-if="resolvedNode && resolvedNode.data?.type === 'input'">
        <details class="config-section border rounded-lg border-border/60 bg-muted/20" open>
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_basic') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.input_key_optional') }}</label>
            <Input
              :model-value="(config().input_key as string) ?? ''"
              :placeholder="t('workflow_editor.input_key_placeholder')"
              @update:model-value="updateConfig('input_key', ($event as string)?.trim() || undefined)"
            />
            <p v-if="inputKeyValidationError" class="text-xs text-destructive">{{ inputKeyValidationError }}</p>
            <p class="text-xs text-muted-foreground">
              留空表示整个 <code>input_data</code> 作为工作流输入；否则从 <code>input_data[input_key]</code> 读取。
            </p>
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.input_fixed_input') }}</label>
            <Textarea
              :model-value="inputFixedInputRaw"
              :placeholder="t('workflow_editor.input_fixed_input_placeholder')"
              rows="3"
              class="text-xs font-mono"
              @update:model-value="onInputFixedInputInput"
            />
            <p v-if="inputFixedInputParseError" class="text-xs text-destructive">{{ inputFixedInputParseError }}</p>
            <p v-else-if="inputFixedInputValidationError" class="text-xs text-destructive">{{ inputFixedInputValidationError }}</p>
            <p class="text-xs text-muted-foreground">
              与工作流入参合并，用于补默认值；执行时 <code>fixed_input</code> 先于 <code>input_data</code> 合并。
            </p>
          </div>
        </details>
        <details class="config-section border rounded-lg border-border/60 bg-muted/20 mt-2">
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
              <span>{{ t('workflow_editor.section_schema') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.input_schema') }}</label>
            <Textarea
              :model-value="typeof config().input_schema === 'object' && config().input_schema != null ? JSON.stringify(config().input_schema as Record<string, unknown>, null, 2) : ''"
              :placeholder="t('workflow_editor.schema_placeholder')"
              rows="4"
              class="text-xs font-mono"
              @update:model-value="(value) => {
                const s = (value as string)?.trim()
                if (!s) { updateConfig('input_schema', undefined); return }
                try {
                  updateConfig('input_schema', JSON.parse(s))
                } catch {
                  // 非法 JSON 不更新 config，保留原值
                }
              }"
            />
            <p class="text-xs text-muted-foreground">
              {{ t('workflow_editor.input_schema_hint') }}
            </p>
          </div>
        </details>
      </template>

      <!-- Output：Basic 分组 -->
      <template v-else-if="resolvedNode && resolvedNode.data?.type === 'output'">
        <details class="config-section border rounded-lg border-border/60 bg-muted/20" open>
          <summary class="config-section-summary px-3 py-2 text-sm font-medium cursor-pointer list-none flex items-center justify-between hover:bg-muted/40 rounded-t-lg [&::-webkit-details-marker]:hidden">
            <span>{{ t('workflow_editor.section_basic') }}</span>
            <span class="config-section-chevron text-muted-foreground transition-transform duration-200 select-none">▼</span>
          </summary>
          <div class="px-3 pb-3 pt-0 space-y-2">
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.output_key') }}</label>
            <Input
              :model-value="(config().output_key as string) ?? 'result'"
              :placeholder="t('workflow_editor.output_key_placeholder')"
              @update:model-value="updateConfig('output_key', ($event as string) || 'result')"
            />
            <p v-if="outputKeyValidationError" class="text-xs text-destructive">{{ outputKeyValidationError }}</p>
            <p class="text-xs text-muted-foreground">
              将该节点输出写入到 <code>execution.output_data[output_key]</code>。
            </p>
            <label class="text-sm font-medium leading-none">{{ t('workflow_editor.output_expression') }}</label>
            <Input
              :model-value="(config().expression as string) ?? ''"
              placeholder="${nodes.llm_1.output} 或 ${input.text}"
              @update:model-value="updateConfig('expression', ($event as string)?.trim() || undefined)"
            />
            <p class="text-xs text-muted-foreground">
              使用执行上下文表达式从前序节点或输入中选择最终输出；留空则使用节点默认输出。
            </p>
          </div>
        </details>
      </template>

      <!-- Start / other -->
      <template v-else>
        <p class="text-sm text-muted-foreground">{{ t('workflow_editor.node_config_no_options') }}</p>
      </template>

      <!-- Delete node (all types except Start) -->
      <div v-if="canDeleteNode() || canDeleteEdge()" class="mt-auto pt-4 border-t border-border/50">
        <Button
          variant="outline"
          size="sm"
          class="w-full text-destructive hover:bg-destructive/10 hover:text-destructive"
          @click="canDeleteNode() ? onDeleteNode() : onDeleteEdge()"
        >
          <Trash2 class="w-4 h-4 mr-2" />
          {{ canDeleteNode() ? t('workflow_editor.delete_node') : 'Delete edge' }}
        </Button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.config-section[open] .config-section-chevron {
  transform: rotate(180deg);
}
</style>
