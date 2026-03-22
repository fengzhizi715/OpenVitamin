<script setup lang="ts">
import { markRaw, nextTick, onUnmounted, ref, provide, watch } from 'vue'
import { VueFlow } from '@vue-flow/core'
import { registerWorkflowCanvasSelect } from './canvasSelection'
import type { Node, Edge, NodeChange, EdgeChange } from '@vue-flow/core'
import WorkflowNode from './nodes/WorkflowNode.vue'
import FlowCoordBridge from './FlowCoordBridge.vue'
import type { WorkflowNodeData } from './types'

const props = withDefaults(
  defineProps<{
    nodes?: Node<WorkflowNodeData>[]
    edges?: Edge[]
  }>(),
  { nodes: () => [], edges: () => [] }
)
const FLOW_ID = 'workflow-editor-canvas'

const emit = defineEmits<{
  'update:nodes': [Node<WorkflowNodeData>[]]
  'update:edges': [Edge[]]
  'select-node': [Node<WorkflowNodeData> | null]
  'select-node-by-id': [string]
  'select-edge': [Edge | null]
}>()

function normalizeNodes(list: Node<WorkflowNodeData>[]): Node<WorkflowNodeData>[] {
  return (list ?? []).map((n) => ({
    ...n,
    draggable: (n as any).draggable !== false,
  } as Node<WorkflowNodeData>))
}

const nodesRef = ref<Node<WorkflowNodeData>[]>(normalizeNodes(props.nodes ?? []))
const edgesRef = ref<Edge[]>(props.edges ?? [])

// 若在 onNodesChange 里 emit 后立刻用 props 覆盖 nodesRef，会冲掉 Vue Flow 刚写入的拖动位置；用标志位在“刚 emit”的下一拍用 ref 的 position 做 merge
let justEmittedNodes = false
let justEmittedEdges = false

watch(
  () => props.nodes,
  (v) => {
    const next = v ?? []
    if (justEmittedNodes) {
      const currentPositions = new Map(nodesRef.value.map((n) => [n.id, n.position]))
      nodesRef.value = normalizeNodes(next).map((p) => ({
        ...p,
        position: currentPositions.get(p.id) ?? p.position,
      })) as Node<WorkflowNodeData>[]
      nextTick(() => { justEmittedNodes = false })
    } else {
      nodesRef.value = normalizeNodes(next)
    }
  },
  { immediate: true, deep: true }
)
watch(
  () => props.edges,
  (v) => {
    if (justEmittedEdges) {
      nextTick(() => { justEmittedEdges = false })
    }
    edgesRef.value = v ?? []
  },
  { immediate: true, deep: true }
)

const nodeTypes = { workflow: markRaw(WorkflowNode) }

function inferEditorTypeFromNodeId(nodeId: string): WorkflowNodeData['type'] {
  const m = /^node_([a-z_]+)_\d+$/i.exec(nodeId || '')
  const t = (m?.[1] || '').toLowerCase()
  const allow: WorkflowNodeData['type'][] = [
    'start', 'llm', 'agent', 'embedding', 'prompt_template', 'system_prompt',
    'input', 'output', 'variable', 'condition', 'loop', 'parallel', 'skill',
    'http_request', 'python', 'shell',
  ]
  return (allow.includes(t as WorkflowNodeData['type']) ? (t as WorkflowNodeData['type']) : 'skill')
}

function defaultDataForType(type: WorkflowNodeData['type']): WorkflowNodeData {
  return {
    type,
    label: type === 'llm' ? 'LLM' : type === 'agent' ? 'Agent' : type === 'skill' ? 'Tool' : 'Node',
    subtitle:
      type === 'llm'
        ? 'Select model'
        : type === 'skill'
          ? 'Select tool'
          : type === 'agent'
            ? 'Select agent'
            : undefined,
    config:
      type === 'llm'
        ? { model_id: '' }
        : type === 'skill'
          ? { tool_name: '' }
          : type === 'agent'
            ? { agent_id: '', agent_display_name: '' }
            : {},
  }
}

// Flag to prevent conflict between custom click and VueFlow's selection
let isSelectingViaClick = false
let lastSelectedNodeId: string | null = null
// 刚 drop 到画布的新节点 id，在 selectNodeById 执行前若 onNodesChange 发了 deselect，保留对该节点的选中避免配置一闪而过
let recentlyAddedNodeId: string | null = null
// drop 后短时间内不再把 onNodesChange 的 nodes 同步给父组件，避免第二次 onNodesUpdate 与首次竞争导致配置面板不显示（与 edge 点击不同，node 依赖 editorNodes 中的项）
let dropCooldownUntil = 0
const DROP_COOLDOWN_MS = 220

// 坐标转换由 VueFlow 内部的 FlowCoordBridge 设置，避免在 VueFlow 挂载前调用 useVueFlow 导致白屏
const screenToFlowCoordinateRef = ref<(pos: { x: number; y: number }) => { x: number; y: number }>((pos) => pos)
provide('workflowCanvasSetScreenToFlowCoordinate', (fn: (pos: { x: number; y: number }) => { x: number; y: number }) => {
  screenToFlowCoordinateRef.value = fn
})

function selectNodeById(nodeId: string) {
  if (!nodeId) return
  isSelectingViaClick = true
  const list = nodesRef.value.map((n) => ({ ...n, selected: n.id === nodeId } as Node<WorkflowNodeData>))
  nodesRef.value = list
  emit('update:nodes', list)
  emit('select-node-by-id', nodeId)
  lastSelectedNodeId = nodeId
  emit('select-edge', null)
  setTimeout(() => { isSelectingViaClick = false }, 60)
}

// 必须在 setup 同步注册：子节点可能在 onMounted 之前就可交互；onMounted 过晚会导致 inject/回调未就绪
registerWorkflowCanvasSelect(selectNodeById)
onUnmounted(() => registerWorkflowCanvasSelect(null))

function onNodesChange(changes: NodeChange[]) {
  const inDropCooldown = Date.now() < dropCooldownUntil
  if (!inDropCooldown) {
    justEmittedNodes = true
    emit('update:nodes', nodesRef.value)
  }
  let hasSelectChange = false
  let draggingNodeId: string | null = null
  for (const change of changes) {
    if (change.type === 'position') {
      const dragging = (change as any).dragging
      if (dragging) draggingNodeId = (change as any).id ?? null
      continue
    }
    if (change.type === 'select') {
      hasSelectChange = true
      continue
    }
  }
  if (hasSelectChange) {
    if (isSelectingViaClick) return
    const current = nodesRef.value
    const selected = current.find((n) => (n as any).selected) as Node<WorkflowNodeData> | undefined
    if (selected) {
      emit('select-node-by-id', selected.id)
      lastSelectedNodeId = selected.id
    } else if (draggingNodeId) {
      emit('select-node-by-id', draggingNodeId)
      lastSelectedNodeId = draggingNodeId
    } else if (lastSelectedNodeId && current.some((n) => n.id === lastSelectedNodeId)) {
      emit('select-node-by-id', lastSelectedNodeId)
    } else if (recentlyAddedNodeId && current.some((n) => n.id === recentlyAddedNodeId)) {
      // 刚 drop 的新节点尚未被 selectNodeById 标记 selected，避免被清空导致配置面板一闪而过
      emit('select-node-by-id', recentlyAddedNodeId)
      lastSelectedNodeId = recentlyAddedNodeId
    } else {
      emit('select-node', null)
      lastSelectedNodeId = null
    }
    emit('select-edge', null)
  }
}

function onPaneClick(evt: MouseEvent) {
  const el = evt.target as HTMLElement
  if (el.closest('.vue-flow__node')) return
  if (nodesRef.value.some((n) => Boolean((n as any).dragging))) return
  nodesRef.value = nodesRef.value.map((n) => ({ ...n, selected: false } as Node<WorkflowNodeData>))
  emit('update:nodes', nodesRef.value)
  emit('select-node', null)
  lastSelectedNodeId = null
  emit('select-edge', null)
}

function onEdgesChange(changes: EdgeChange[]) {
  justEmittedEdges = true
  emit('update:edges', edgesRef.value)
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  const raw = e.dataTransfer?.getData('application/vnd.workflow-node')
  if (!raw) return
  try {
    const { type, label } = JSON.parse(raw) as { type: string; label: string }
    const pos = screenToFlowCoordinateRef.value({ x: e.clientX, y: e.clientY })
    const id = `node_${type}_${Date.now()}`
    const newNode: Node<WorkflowNodeData> = {
      id,
      type: 'workflow',
      position: pos,
      selected: true,
      data: { ...defaultDataForType(type as WorkflowNodeData['type']), label },
    }
    recentlyAddedNodeId = id
    lastSelectedNodeId = id
    dropCooldownUntil = Date.now() + DROP_COOLDOWN_MS
    const othersDeselected = nodesRef.value.map((n) => ({ ...n, selected: false } as Node<WorkflowNodeData>))
    nodesRef.value = [...othersDeselected, newNode]
    emit('update:nodes', nodesRef.value)
    emit('select-edge', null)
    emit('select-node-by-id', id)
    // 延迟再同步画布 selected 态并清除“刚添加”标记；cooldown 内 onNodesChange 不再 emit update:nodes，避免父组件二次 onNodesUpdate 冲掉配置
    setTimeout(() => {
      selectNodeById(id)
      recentlyAddedNodeId = null
    }, 50)
  } catch (_) {
    // ignore
  }
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
}

function onNodeClick({ node }: { node: Node<WorkflowNodeData> }) {
  selectNodeById(node.id)
}

function onEdgeClick({ edge }: { edge: Edge }) {
  const selected = (props.edges ?? []).find((e) => e.id === edge.id) ?? edge
  emit('select-edge', selected as Edge)
  emit('select-node', null)
}

function onConnect(connection: { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }) {
  const id = `e-${connection.source}-${connection.target}-${Date.now()}`
  const label = connection.sourceHandle && ['true', 'false', 'continue', 'exit'].includes(connection.sourceHandle)
    ? connection.sourceHandle
    : undefined
  const newEdge: Edge = {
    id,
    source: connection.source,
    target: connection.target,
    ...(label && { label }),
    ...(connection.sourceHandle != null && { sourceHandle: connection.sourceHandle }),
    ...(connection.targetHandle != null && { targetHandle: connection.targetHandle }),
  }
  edgesRef.value = [...edgesRef.value, newEdge]
  emit('update:edges', edgesRef.value)
}
</script>

<template>
  <div class="workflow-canvas-wrap h-full w-full relative">
    <!-- v-model 与 Vue Flow 双向绑定，拖动由库内部更新 nodesRef，onNodesChange 只做同步与选中逻辑 -->
    <VueFlow
      :id="FLOW_ID"
      v-model:nodes="nodesRef"
      v-model:edges="edgesRef"
      :node-types="nodeTypes"
      :nodes-draggable="true"
      :connectable="true"
      class="rounded-lg bg-muted/20"
      @drop="onDrop"
      @dragover="onDragOver"
      @connect="onConnect"
      @node-click="onNodeClick"
      @pane-click="onPaneClick"
      @edge-click="onEdgeClick"
      @nodes-change="onNodesChange"
      @edges-change="onEdgesChange"
    >
      <FlowCoordBridge />
    </VueFlow>
  </div>
</template>
