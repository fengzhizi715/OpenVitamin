/**
 * Vue Flow 自定义节点可能不在 WorkflowCanvas 的 inject 子树内，provide/inject 会失效。
 * 用模块级回调保证点击节点总能通知画布打开右侧配置。
 */
type SelectById = (nodeId: string) => void
let selectById: SelectById | null = null

export function registerWorkflowCanvasSelect(fn: SelectById | null) {
  selectById = fn
  console.log('[canvasSelection] Registered:', !!fn)
}

export function requestWorkflowNodeSelect(nodeId: string) {
  console.log('[canvasSelection] requestWorkflowNodeSelect:', nodeId, 'handler exists:', !!selectById)
  selectById?.(nodeId)
}
