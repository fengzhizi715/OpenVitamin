<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Save, Play, Rocket, Undo2, Redo2, Loader2, ChevronDown } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import NodeLibrary from './editor/NodeLibrary.vue'
import WorkflowCanvas from './editor/WorkflowCanvas.vue'
import NodeConfigPanel from './editor/NodeConfigPanel.vue'
import type { Node } from '@vue-flow/core'
import type { Edge } from '@vue-flow/core'
import type { WorkflowNodeData } from './editor/types'
import { toWorkflowDag, fromWorkflowDag } from './editor/serialization'
import { validateWorkflowNodes, validateWorkflowPreflight } from './editor/validation'
import { getWorkflow, getWorkflowVersion, updateWorkflow, createWorkflowVersion } from '@/services/api'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const workflowId = route.params.id as string

const workflowName = ref('')
const workflowVersion = ref('')
const editorNodes = ref<Node<WorkflowNodeData>[]>([
  {
    id: 'start',
    type: 'workflow',
    position: { x: 80, y: 120 },
    data: { type: 'start', label: 'Start', config: {} },
  },
])
const editorEdges = ref<Edge[]>([])
/** 以 ID 为唯一来源，拖动时仅替换 editorNodes，不丢失选中 */
const selectedNodeId = ref<string | null>(null)
const selectedEdge = ref<Edge | null>(null)
const isDirty = ref(false)

const selectedNode = computed(() =>
  selectedNodeId.value
    ? (editorNodes.value.find((n) => n.id === selectedNodeId.value) as Node<WorkflowNodeData> | undefined) ?? null
    : null
)

type EditorSnapshot = {
  workflowName: string
  nodes: Node<WorkflowNodeData>[]
  edges: Edge[]
}

const HISTORY_LIMIT = 80
const undoStack = ref<EditorSnapshot[]>([])
const redoStack = ref<EditorSnapshot[]>([])
const isApplyingSnapshot = ref(false)
const lastSnapshotSignature = ref('')
const lastSavedSignature = ref('')
const lastBackendDraftSignature = ref('')
let autosaveTimer: number | null = null
const backendDraftSaving = ref(false)
const saveInProgress = ref(false)
const EDIT_DRAFT_KEY = `workflow:edit:${workflowId}:draft`
const validationErrors = ref<Array<{ nodeId: string; nodeLabel?: string; message: string }>>([])
const draftRestorePending = ref<EditorSnapshot | null>(null)

const selectedNodeModelId = computed(() => {
  const c = selectedNode.value?.data?.config
  if (!c || typeof c !== 'object') return ''
  const v = (c as Record<string, unknown>).model_id
  return typeof v === 'string' ? v : ''
})
const selectedNodeModelDisplayName = computed(() => {
  const c = selectedNode.value?.data?.config
  if (!c || typeof c !== 'object') return ''
  const name = (c as Record<string, unknown>).model_display_name
  const id = (c as Record<string, unknown>).model_id
  return (typeof name === 'string' && name) || (typeof id === 'string' ? id : '')
})
const selectedNodeAgentId = computed(() => {
  const c = selectedNode.value?.data?.config
  if (!c || typeof c !== 'object') return ''
  const v = (c as Record<string, unknown>).agent_id
  return typeof v === 'string' ? v : ''
})
const selectedNodeAgentDisplayName = computed(() => {
  const c = selectedNode.value?.data?.config
  if (!c || typeof c !== 'object') return ''
  const name = (c as Record<string, unknown>).agent_display_name
  const id = (c as Record<string, unknown>).agent_id
  return (typeof name === 'string' && name) || (typeof id === 'string' ? id : '')
})


function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value))
}

function captureSnapshot(): EditorSnapshot {
  return {
    workflowName: workflowName.value,
    nodes: clone(editorNodes.value),
    edges: clone(editorEdges.value),
  }
}

function snapshotSignature(snapshot: EditorSnapshot): string {
  return JSON.stringify(snapshot)
}

function recalcDirty() {
  isDirty.value = snapshotSignature(captureSnapshot()) !== lastSavedSignature.value
}

function applySnapshot(snapshot: EditorSnapshot) {
  isApplyingSnapshot.value = true
  workflowName.value = snapshot.workflowName
  editorNodes.value = clone(snapshot.nodes)
  editorEdges.value = clone(snapshot.edges)
  selectedNodeId.value = null
  selectedEdge.value = null
  isApplyingSnapshot.value = false
}

function saveDraftToLocal() {
  const payload = {
    updated_at: new Date().toISOString(),
    snapshot: captureSnapshot(),
  }
  localStorage.setItem(EDIT_DRAFT_KEY, JSON.stringify(payload))
}

/**
 * 已停用：autosave 仅写本地草稿，不创建 version，避免版本膨胀。
 * 保留本函数仅供将来若恢复「服务端草稿」时复用；当前流程不调用。
 */
async function saveDraftToBackend() {
  if (backendDraftSaving.value) return
  const snapshot = captureSnapshot()
  const sig = snapshotSignature(snapshot)
  if (sig === lastBackendDraftSignature.value) return
  backendDraftSaving.value = true
  try {
    await createWorkflowVersion(workflowId, {
      description: `[auto-draft] ${new Date().toISOString()}`,
      dag: {
        nodes: snapshot.nodes.map((n) => ({
          id: n.id,
          type: n.data?.type === 'skill' ? 'tool' : (n.data?.type || 'input'),
          name: n.data?.label || n.id,
          config: (n.data?.config || {}) as Record<string, any>,
          position: n.position,
        })),
        edges: snapshot.edges.map((e) => ({
          from_node: e.source,
          to_node: e.target,
          condition: ((e.data as Record<string, unknown> | undefined)?.condition as string) || null,
          label: typeof e.label === 'string' ? e.label : null,
          source_handle: typeof e.sourceHandle === 'string' ? e.sourceHandle : null,
          target_handle: typeof e.targetHandle === 'string' ? e.targetHandle : null,
        })),
        entry_node: snapshot.nodes[0]?.id || null,
        global_config: {},
      },
    })
    lastBackendDraftSignature.value = sig
  } catch {
    // best effort autosave
  } finally {
    backendDraftSaving.value = false
  }
}

/** 仅本地草稿，不创建 version，避免版本膨胀；仅手动 Save/Publish 创建新 version */
function scheduleAutosave() {
  if (autosaveTimer != null) window.clearTimeout(autosaveTimer)
  autosaveTimer = window.setTimeout(() => {
    saveDraftToLocal()
    autosaveTimer = null
  }, 5000)
}

function markStateChange() {
  if (isApplyingSnapshot.value) return
  validationErrors.value = []
  const current = captureSnapshot()
  const currentSig = snapshotSignature(current)
  if (!lastSnapshotSignature.value) {
    lastSnapshotSignature.value = currentSig
    recalcDirty()
    return
  }
  if (currentSig === lastSnapshotSignature.value) return
  undoStack.value.push(JSON.parse(lastSnapshotSignature.value) as EditorSnapshot)
  if (undoStack.value.length > HISTORY_LIMIT) undoStack.value.shift()
  redoStack.value = []
  lastSnapshotSignature.value = currentSig
  recalcDirty()
  scheduleAutosave()
}

function undo() {
  if (!undoStack.value.length) return
  const prev = undoStack.value.pop()!
  redoStack.value.push(captureSnapshot())
  applySnapshot(prev)
  lastSnapshotSignature.value = snapshotSignature(prev)
  recalcDirty()
}

function redo() {
  if (!redoStack.value.length) return
  const next = redoStack.value.pop()!
  undoStack.value.push(captureSnapshot())
  applySnapshot(next)
  lastSnapshotSignature.value = snapshotSignature(next)
  recalcDirty()
}

function tryRestoreDraft() {
  const raw = localStorage.getItem(EDIT_DRAFT_KEY)
  if (!raw) return
  try {
    const parsed = JSON.parse(raw) as { snapshot?: EditorSnapshot }
    if (!parsed?.snapshot) return
    draftRestorePending.value = parsed.snapshot
  } catch {
    // ignore broken local draft
  }
}
function acceptDraftRestore() {
  if (draftRestorePending.value) {
    applySnapshot(draftRestorePending.value)
    localStorage.removeItem(EDIT_DRAFT_KEY)
    draftRestorePending.value = null
  }
}
function dismissDraftRestore() {
  localStorage.removeItem(EDIT_DRAFT_KEY)
  draftRestorePending.value = null
}

function goBack() {
  router.push({ name: 'workflow-detail', params: { id: workflowId } })
}

async function saveWorkflow() {
  if (saveInProgress.value) return
  const { valid, errors } = validateWorkflowNodes(editorNodes.value)
  if (!valid) {
    validationErrors.value = errors
    return
  }
  validationErrors.value = []
  const snapshot = captureSnapshot()
  saveInProgress.value = true
  try {
    await updateWorkflow(workflowId, { name: (snapshot.workflowName || 'Untitled Workflow').trim() })
    const dag = toWorkflowDag(editorNodes.value, editorEdges.value)
    await createWorkflowVersion(workflowId, {
      description: `Saved at ${new Date().toISOString().slice(0, 19)}`,
      dag,
    })
    lastSavedSignature.value = snapshotSignature(snapshot)
    recalcDirty()
    localStorage.removeItem(EDIT_DRAFT_KEY)
    router.push({ name: 'workflow-detail', params: { id: workflowId } })
  } catch (e) {
    console.error('Save failed:', e)
  } finally {
    saveInProgress.value = false
  }
}

async function runWorkflowSaveAndRun() {
  const { valid, errors } = validateWorkflowNodes(editorNodes.value)
  if (!valid) {
    validationErrors.value = errors
    return
  }
  validationErrors.value = []
  const snapshot = captureSnapshot()
  saveInProgress.value = true
  try {
    await updateWorkflow(workflowId, { name: (snapshot.workflowName || 'Untitled Workflow').trim() })
    const dag = toWorkflowDag(editorNodes.value, editorEdges.value)
    await createWorkflowVersion(workflowId, {
      description: `Saved at ${new Date().toISOString().slice(0, 19)}`,
      dag,
    })
    lastSavedSignature.value = snapshotSignature(snapshot)
    recalcDirty()
    localStorage.removeItem(EDIT_DRAFT_KEY)
    router.push({ name: 'workflow-run', params: { id: workflowId } })
  } catch (e) {
    console.error('Save failed:', e)
  } finally {
    saveInProgress.value = false
  }
}
function runWorkflowPublishedOnly() {
  router.push({ name: 'workflow-run', params: { id: workflowId } })
}

function deployWorkflow() {
  // 能力未闭环，禁用并提示
}

function onUpdateConfig(nodeId: string, config: Record<string, unknown>) {
  const list = [...editorNodes.value]
  const idx = list.findIndex((n) => n.id === nodeId)
  if (idx === -1) return
  const node = list[idx]
  if (!node?.data) return
  const mergedConfigRaw = { ...(node.data.config as Record<string, unknown> || {}), ...config }
  const mergedConfig = Object.fromEntries(
    Object.entries(mergedConfigRaw).filter(([, v]) => v !== undefined)
  ) as Record<string, unknown>
  const nextData = { ...node.data, config: mergedConfig } as WorkflowNodeData
  list[idx] = { ...node, data: nextData }
  editorNodes.value = list
}

function onNodesUpdate(incoming: Node<WorkflowNodeData>[]) {
  const current = editorNodes.value
  const merged = current.map((cur) => {
    const inc = incoming.find((i) => i.id === cur.id)
    if (!inc) return cur
    const nextData = inc.data
      ? ({
          ...cur.data,
          ...inc.data,
          config: {
            ...((cur.data?.config as Record<string, unknown>) || {}),
            ...((inc.data?.config as Record<string, unknown>) || {}),
          },
        } as WorkflowNodeData)
      : cur.data
    return {
      ...cur,
      ...inc,
      position: inc.position ?? cur.position,
      data: nextData,
    } as Node<WorkflowNodeData>
  })
  const added = (incoming || []).filter((n) => !current.some((c) => c.id === n.id))
  if (added.length) {
    editorNodes.value = [...merged, ...added]
    selectedEdge.value = null
    const addedId = added[added.length - 1].id
    // 同步设选中，避免与画布 onNodesChange 竞争导致配置面板一闪而过
    selectedNodeId.value = addedId
  } else {
    editorNodes.value = merged
  }
}

function onEdgesUpdate(nextEdges: Edge[]) {
  const prevEdges = editorEdges.value
  editorEdges.value = nextEdges

  // 自动模板：Input -> Condition 连线时，若 Condition 为空则填入可运行默认表达式
  const prevIds = new Set(prevEdges.map((e) => e.id))
  const added = nextEdges.filter((e) => !prevIds.has(e.id))
  for (const edge of added) {
    const src = editorNodes.value.find((n) => n.id === edge.source)
    const tgt = editorNodes.value.find((n) => n.id === edge.target)
    if (src?.data?.type === 'input' && tgt?.data?.type === 'condition') {
      const cfg = (tgt.data?.config || {}) as Record<string, unknown>
      const currentExpr = String(cfg.condition_expression || '').trim()
      if (!currentExpr) {
        onUpdateConfig(tgt.id, {
          ...cfg,
          condition_expression: '${input.query} is not None',
        })
      }
    }
  }
}

function runPreflightCheck() {
  const baseCheck = validateWorkflowNodes(editorNodes.value)
  const preflight = validateWorkflowPreflight(editorNodes.value, editorEdges.value)
  const errors = [...baseCheck.errors, ...preflight.errors]
  validationErrors.value = errors
}

function onSelectNode(node: Node<WorkflowNodeData> | null) {
  selectedNodeId.value = node?.id ?? null
  if (node) selectedEdge.value = null
}

function onSelectNodeById(nodeId: string) {
  if (!editorNodes.value.some((n) => n.id === nodeId)) return
  selectedNodeId.value = nodeId
  selectedEdge.value = null
}

function onSelectEdge(edge: Edge | null) {
  // 仅在选择某条 edge 时清空节点选中；select-edge(null) 只清边，避免 drop 节点后配置被清空（onDrop 里会先 emit select-edge null 再 emit select-node-by-id）
  if (edge != null) selectedNodeId.value = null
  selectedEdge.value = edge
}

function onCloseConfigPanel() {
  selectedNodeId.value = null
  selectedEdge.value = null
}

function onUpdateEdge(edgeId: string, patch: Record<string, unknown>) {
  editorEdges.value = editorEdges.value.map((edge) => {
    if (edge.id !== edgeId) return edge
    return { ...edge, ...patch } as Edge
  })
  selectedEdge.value = editorEdges.value.find((edge) => edge.id === edgeId) || null
}

function removeEdge(edgeId: string) {
  editorEdges.value = editorEdges.value.filter((edge) => edge.id !== edgeId)
  if (selectedEdge.value?.id === edgeId) selectedEdge.value = null
}

function removeNode(nodeId: string) {
  if (nodeId === 'start') return
  editorNodes.value = editorNodes.value.filter((n) => n.id !== nodeId)
  editorEdges.value = editorEdges.value.filter((e) => e.source !== nodeId && e.target !== nodeId)
  if (selectedNodeId.value === nodeId) selectedNodeId.value = null
  if (selectedEdge.value?.source === nodeId || selectedEdge.value?.target === nodeId) selectedEdge.value = null
}

function onKeydown(e: KeyboardEvent) {
  const meta = e.metaKey || e.ctrlKey
  if (meta && e.key.toLowerCase() === 'z' && !e.shiftKey) {
    e.preventDefault()
    undo()
    return
  }
  if (meta && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) {
    e.preventDefault()
    redo()
    return
  }
  if ((e.key !== 'Delete' && e.key !== 'Backspace') || !selectedNode.value) return
  // 焦点在输入框/文本框时不要触发删除节点，避免编辑 Default input 等时误删
  const target = e.target as HTMLElement | null
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
  if (selectedNode.value.data?.type === 'start') return
  e.preventDefault()
  removeNode(selectedNode.value.id)
}

watch([workflowName, editorNodes, editorEdges], () => {
  markStateChange()
}, { deep: true })

onBeforeRouteLeave((_to, _from, next) => {
  if (!isDirty.value) {
    next()
    return
  }
  const ok = window.confirm('You have unsaved changes. Leave without saving?')
  next(ok)
})

function onBeforeUnload(e: BeforeUnloadEvent) {
  if (!isDirty.value) return
  e.preventDefault()
  e.returnValue = ''
}

onMounted(async () => {
  try {
    const wf = await getWorkflow(workflowId)
    workflowName.value = wf.name || 'Untitled Workflow'
    workflowVersion.value = wf.latest_version_id ? `v: ${String(wf.latest_version_id).slice(0, 8)}` : ''

    // 优先使用已发布版本，其次 latest 版本；如果都没有，则保持默认起始节点
    const baseVersionId = (wf.published_version_id as string | null) || (wf.latest_version_id as string | null) || null
    if (baseVersionId) {
      try {
        const version = await getWorkflowVersion(workflowId, baseVersionId)
        if (version.dag) {
          const { nodes, edges } = fromWorkflowDag(version.dag)
          editorNodes.value = nodes
          editorEdges.value = edges
        }
      } catch (e) {
        console.error('Failed to load workflow version DAG:', e)
        // 保持默认 start 节点，允许用户继续编辑
      }
    }
  } catch {
    workflowName.value = 'Untitled Workflow'
  }

  // 如果存在本地编辑草稿，让用户选择是否覆盖为草稿快照
  tryRestoreDraft()

  const initialSig = snapshotSignature(captureSnapshot())
  lastSnapshotSignature.value = initialSig
  lastSavedSignature.value = initialSig
  lastBackendDraftSignature.value = initialSig
  recalcDirty()
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('beforeunload', onBeforeUnload)
})
onUnmounted(() => {
  if (autosaveTimer != null) window.clearTimeout(autosaveTimer)
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('beforeunload', onBeforeUnload)
})
</script>

<template>
  <div class="flex flex-col h-full bg-background">
    <!-- Top bar -->
    <div class="flex items-center gap-4 px-6 py-4 border-b border-border/50 shrink-0">
      <Button variant="ghost" size="icon" @click="goBack">
        <ArrowLeft class="w-5 h-5" />
      </Button>
      <div class="flex items-center gap-3 min-w-0 flex-1">
        <input
          v-model="workflowName"
          type="text"
          class="font-semibold text-lg bg-transparent border-b border-transparent hover:border-border focus:border-primary focus:outline-none px-1 py-0.5 min-w-0 max-w-md"
          placeholder="Workflow name"
        />
        <div class="text-sm text-muted-foreground shrink-0">{{ workflowVersion }}</div>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Button variant="outline" size="sm" class="gap-2" :disabled="undoStack.length === 0" @click="undo">
          <Undo2 class="w-4 h-4" />
          Undo
        </Button>
        <Button variant="outline" size="sm" class="gap-2" :disabled="redoStack.length === 0" @click="redo">
          <Redo2 class="w-4 h-4" />
          Redo
        </Button>
        <Button variant="outline" size="sm" class="gap-2" @click="runPreflightCheck">
          检查
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button variant="outline" size="sm" class="gap-2">
              <Play class="w-4 h-4" />
              {{ t('workflow_editor.run') }}
              <ChevronDown class="w-3.5 h-3.5 opacity-60" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem @click="runWorkflowSaveAndRun">保存并运行</DropdownMenuItem>
            <DropdownMenuItem @click="runWorkflowPublishedOnly">运行已发布版本</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button variant="outline" size="sm" class="gap-2" :disabled="saveInProgress" @click="saveWorkflow">
          <Loader2 v-if="saveInProgress" class="w-4 h-4 animate-spin" />
          <Save v-else class="w-4 h-4" />
          {{ saveInProgress ? 'Saving...' : t('workflow_editor.save') }}<span v-if="isDirty && !saveInProgress" class="ml-1 text-amber-500">*</span>
        </Button>
        <Button
          size="sm"
          class="gap-2"
          variant="outline"
          disabled
          title="功能开发中，敬请期待"
        >
          <Rocket class="w-4 h-4 opacity-50" />
          <span class="opacity-70">{{ t('workflow_editor.deploy') }}</span>
        </Button>
      </div>
    </div>

    <!-- 校验错误面板：点击定位节点 -->
    <div v-if="validationErrors.length" class="mx-6 mb-2 rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm">
      <p class="font-medium text-amber-800 dark:text-amber-400 mb-2">保存前校验未通过</p>
      <ul class="space-y-1">
        <li
          v-for="(e, i) in validationErrors"
          :key="i"
          class="cursor-pointer hover:underline text-amber-700 dark:text-amber-300"
          @click="onSelectNodeById(e.nodeId)"
        >
          [{{ e.nodeLabel || e.nodeId }}] {{ e.message }}
        </li>
      </ul>
    </div>

    <!-- 草稿恢复提示条（非阻断） -->
    <div v-if="draftRestorePending" class="mx-6 mb-2 rounded-lg border border-blue-500/50 bg-blue-500/10 px-4 py-2 flex items-center justify-between text-sm">
      <span class="text-blue-800 dark:text-blue-200">检测到未保存草稿</span>
      <div class="flex gap-2">
        <Button variant="outline" size="sm" @click="acceptDraftRestore">恢复</Button>
        <Button variant="ghost" size="sm" @click="dismissDraftRestore">忽略</Button>
      </div>
    </div>

    <!-- Three columns -->
    <div class="flex flex-1 min-h-0">
      <!-- Left: Node Library -->
      <aside class="w-56 shrink-0 flex flex-col border-r border-border/50">
        <NodeLibrary />
      </aside>

      <!-- Center: Canvas -->
      <main class="flex-1 min-w-0 flex flex-col p-4">
        <WorkflowCanvas
          :nodes="editorNodes"
          :edges="editorEdges"
          @update:nodes="onNodesUpdate"
          @update:edges="onEdgesUpdate"
          @select-node="onSelectNode"
          @select-node-by-id="onSelectNodeById"
          @select-edge="onSelectEdge"
        />
      </main>

      <!-- Right: Node Config -->
      <aside class="w-80 shrink-0 flex flex-col border-l border-border/50">
        <NodeConfigPanel
          :node="selectedNode"
          :selected-node-id="selectedNodeId"
          :edge="selectedEdge"
          :nodes="editorNodes"
          :selected-model-id="selectedNodeModelId"
          :selected-model-display-name="selectedNodeModelDisplayName"
          :selected-agent-id="selectedNodeAgentId"
          :selected-agent-display-name="selectedNodeAgentDisplayName"
          @close="onCloseConfigPanel"
          @update:config="onUpdateConfig"
          @delete-node="removeNode"
          @update:edge="onUpdateEdge"
          @delete-edge="removeEdge"
        />
      </aside>
    </div>
  </div>
</template>
