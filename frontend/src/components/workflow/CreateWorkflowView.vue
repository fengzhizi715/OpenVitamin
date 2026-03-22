<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, onBeforeRouteLeave } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Save, Play, Rocket, Undo2, Redo2, Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import NodeLibrary from './editor/NodeLibrary.vue'
import WorkflowCanvas from './editor/WorkflowCanvas.vue'
import NodeConfigPanel from './editor/NodeConfigPanel.vue'
import type { Node } from '@vue-flow/core'
import type { Edge } from '@vue-flow/core'
import type { WorkflowNodeData } from './editor/types'
import { validateWorkflowNodes, validateWorkflowPreflight } from './editor/validation'
import { createWorkflow, createWorkflowVersion, runWorkflow as runWorkflowApi, type WorkflowNodePayload, type WorkflowEdgePayload, type WorkflowDagPayload } from '@/services/api'

const router = useRouter()
const { t } = useI18n()

const workflowName = ref('')
const isSaving = ref(false)
const isRunning = ref(false)
const savedWorkflowId = ref<string | null>(null)
const savedVersionId = ref<string | null>(null)
const editorNodes = ref<Node<WorkflowNodeData>[]>([
  {
    id: 'start',
    type: 'workflow',
    position: { x: 80, y: 120 },
    data: { type: 'start', label: 'Start', config: {} },
  },
])
const editorEdges = ref<Edge[]>([])
const selectedNode = ref<Node<WorkflowNodeData> | null>(null)
const selectedEdge = ref<Edge | null>(null)
const isDirty = ref(false)

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
let autosaveTimer: number | null = null
const CREATE_DRAFT_KEY = 'workflow:create:draft'
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

watch(editorNodes, () => {
  const id = selectedNode.value?.id
  if (!id) return
  const fromList = editorNodes.value.find((n) => n.id === id)
  if (fromList && fromList !== selectedNode.value) selectedNode.value = fromList as Node<WorkflowNodeData>
}, { deep: true })

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
  selectedNode.value = null
  selectedEdge.value = null
  isApplyingSnapshot.value = false
}

function saveDraftToLocal() {
  const payload = {
    updated_at: new Date().toISOString(),
    snapshot: captureSnapshot(),
  }
  localStorage.setItem(CREATE_DRAFT_KEY, JSON.stringify(payload))
}

function scheduleAutosave() {
  if (autosaveTimer != null) window.clearTimeout(autosaveTimer)
  autosaveTimer = window.setTimeout(() => {
    saveDraftToLocal()
    autosaveTimer = null
  }, 1200)
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
  const raw = localStorage.getItem(CREATE_DRAFT_KEY)
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
    localStorage.removeItem(CREATE_DRAFT_KEY)
    draftRestorePending.value = null
  }
}
function dismissDraftRestore() {
  localStorage.removeItem(CREATE_DRAFT_KEY)
  draftRestorePending.value = null
}

function goBack() {
  router.push({ name: 'workflow' })
}

function buildDagPayload(): WorkflowDagPayload {
  const nodes: WorkflowNodePayload[] = editorNodes.value.map((n) => ({
    id: n.id,
    type: n.data?.type || 'unknown',
    name: n.data?.label || null,
    description: null,
    config: (n.data?.config as Record<string, any>) || {},
    position: n.position,
  }))
  const edges: WorkflowEdgePayload[] = editorEdges.value.map((e) => ({
    from_node: e.source,
    to_node: e.target,
    condition: null,
    label: (e.label as string) || null,
    source_handle: e.sourceHandle || null,
    target_handle: e.targetHandle || null,
  }))
  return {
    nodes,
    edges,
    entry_node: 'start',
    global_config: {},
  }
}

async function saveWorkflow() {
  if (isSaving.value) return

  const { valid, errors } = validateWorkflowNodes(editorNodes.value)
  if (!valid) {
    validationErrors.value = errors
    return
  }
  validationErrors.value = []

  const name = workflowName.value.trim() || 'Untitled Workflow'
  isSaving.value = true
  
  try {
    // Create workflow if not yet saved
    if (!savedWorkflowId.value) {
      const workflow = await createWorkflow({
        name,
        namespace: 'default',
        description: '',
        tags: [],
      })
      savedWorkflowId.value = workflow.id
    } else {
      // Update workflow name if changed
      // Note: updateWorkflow API exists but we skip for simplicity
    }
    
    // Create a new version with current DAG
    const dag = buildDagPayload()
    const version = await createWorkflowVersion(savedWorkflowId.value, {
      dag,
      description: 'Saved from editor',
    })
    savedVersionId.value = version.version_id
    
    lastSavedSignature.value = snapshotSignature(captureSnapshot())
    recalcDirty()
    localStorage.removeItem(CREATE_DRAFT_KEY)
    
    alert(t('workflow.save_success'))
  } catch (error) {
    console.error('Failed to save workflow:', error)
    alert(t('workflow.save_failed', { message: error instanceof Error ? error.message : t('common.unknown_error') }))
  } finally {
    isSaving.value = false
  }
}

async function runWorkflow() {
  if (isRunning.value) return

  const { valid, errors } = validateWorkflowNodes(editorNodes.value)
  if (!valid) {
    validationErrors.value = errors
    return
  }
  validationErrors.value = []

  // Save first if not saved
  if (!savedWorkflowId.value || isDirty.value) {
    const shouldSave = window.confirm(t('workflow.confirm_save_before_run'))
    if (!shouldSave) return
    
    await saveWorkflow()
    if (!savedWorkflowId.value) return // Save failed
  }
  
  isRunning.value = true
  
  try {
    const execution = await runWorkflowApi(
      savedWorkflowId.value!,
      {
        version_id: savedVersionId.value || undefined,
        input_data: {},
        global_context: {},
        trigger_type: 'manual',
      },
      false
    )
    
    alert(t('workflow.run_started', { executionId: execution.execution_id }))
    // Optionally navigate to execution detail page
    // router.push({ name: 'workflow-execution', params: { id: execution.execution_id } })
  } catch (error) {
    console.error('Failed to run workflow:', error)
    const msg = error instanceof Error ? error.message : String(error)
    const lower = msg.toLowerCase()
    const friendly =
      lower.includes('published') ||
      lower.includes('draft') ||
      (lower.includes('version') && (lower.includes('not allowed') || lower.includes('required')))
        ? t('workflow.run_requires_published')
        : msg
    alert(t('workflow.run_failed', { message: friendly }))
  } finally {
    isRunning.value = false
  }
}

function deployWorkflow() {
  // TODO: deploy action (after create)
  alert(t('workflow.deploy_coming_soon'))
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
  if (selectedNode.value?.id === nodeId) {
    selectedNode.value = list[idx] as Node<WorkflowNodeData>
  }
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
  if (added.length) editorNodes.value = [...merged, ...added]
  else editorNodes.value = merged
  const id = selectedNode.value?.id
  if (id) {
    const fromList = editorNodes.value.find((n) => n.id === id)
    if (fromList) selectedNode.value = fromList
  }
}

function onEdgesUpdate(nextEdges: Edge[]) {
  const prevEdges = editorEdges.value
  editorEdges.value = nextEdges

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
  validationErrors.value = [...baseCheck.errors, ...preflight.errors]
}

function onSelectNode(node: Node<WorkflowNodeData> | null) {
  console.log("[CreateWorkflowView] onSelectNode:", node?.id)
  if (!node) {
    selectedNode.value = null
    return
  }
  selectedEdge.value = null
  const fromList = editorNodes.value.find((n) => n.id === node.id)
  selectedNode.value = (fromList ?? node) as Node<WorkflowNodeData>
}

function onSelectNodeById(nodeId: string) {
  console.log("[CreateWorkflowView] onSelectNodeById:", nodeId, "editorNodes count:", editorNodes.value.length)
  const fromList = editorNodes.value.find((n) => n.id === nodeId)
  if (!fromList) return
  
  // Clear edge selection first
  selectedEdge.value = null
  
  // Direct assignment - Vue should detect this
  selectedNode.value = fromList as Node<WorkflowNodeData>
}

function onSelectEdge(edge: Edge | null) {
  selectedNode.value = null
  selectedEdge.value = edge
}

function onCloseConfigPanel() {
  selectedNode.value = null
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
  if (selectedNode.value?.id === nodeId) selectedNode.value = null
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

onMounted(() => {
  tryRestoreDraft()
  const initialSig = snapshotSignature(captureSnapshot())
  lastSnapshotSignature.value = initialSig
  lastSavedSignature.value = initialSig
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
        <Input
          v-model="workflowName"
          placeholder="Workflow name..."
          class="max-w-xs font-semibold"
        />
        <span class="text-sm text-muted-foreground shrink-0">New workflow</span>
      </div>
      <div class="flex items-center gap-2">
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
        <Button variant="outline" size="sm" class="gap-2" :disabled="isRunning" @click="runWorkflow">
          <Loader2 v-if="isRunning" class="w-4 h-4 animate-spin" />
          <Play v-else class="w-4 h-4" />
          {{ t('workflow_editor.run') }}
        </Button>
        <Button variant="outline" size="sm" class="gap-2" :disabled="isSaving" @click="saveWorkflow">
          <Loader2 v-if="isSaving" class="w-4 h-4 animate-spin" />
          <Save v-else class="w-4 h-4" />
          {{ t('workflow_editor.save') }}<span v-if="isDirty" class="ml-1 text-amber-500">*</span>
        </Button>
        <Button size="sm" class="gap-2" variant="outline" disabled title="功能开发中，敬请期待">
          <Rocket class="w-4 h-4 opacity-50" />
          <span class="opacity-70">{{ t('workflow_editor.deploy') }}</span>
        </Button>
      </div>
    </div>

    <!-- 校验错误面板：点击定位节点 -->
    <div v-if="validationErrors.length" class="mx-6 mb-2 rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm">
      <p class="font-medium text-amber-800 dark:text-amber-400 mb-2">校验未通过</p>
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

    <!-- Three columns: Node Library | Canvas | Node Config -->
    <div class="flex flex-1 min-h-0">
      <aside class="w-56 shrink-0 flex flex-col border-r border-border/50">
        <NodeLibrary />
      </aside>
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
      <aside class="w-80 shrink-0 flex flex-col border-l border-border/50">
        <NodeConfigPanel
          :node="selectedNode"
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
