export type WorkflowUiStatus =
  | 'idle'
  | 'pending'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timeout'

export function normalizeExecutionStatus(state?: string | null): WorkflowUiStatus {
  const s = String(state || '').toLowerCase()
  if (s === 'completed' || s === 'success' || s === 'succeeded') return 'succeeded'
  if (s === 'failed' || s === 'error') return 'failed'
  if (s === 'pending') return 'pending'
  if (s === 'queued') return 'queued'
  if (s === 'running') return 'running'
  if (s === 'cancelled' || s === 'canceled') return 'cancelled'
  if (s === 'timeout' || s === 'timed_out') return 'timeout'
  return 'idle'
}

export function normalizeNodeStatus(state?: string | null): WorkflowUiStatus {
  const s = String(state || '').toLowerCase()
  if (s === 'completed' || s === 'success' || s === 'succeeded') return 'succeeded'
  if (s === 'failed' || s === 'error') return 'failed'
  if (s === 'running' || s === 'in_progress' || s === 'in-progress' || s === 'executing' || s === 'processing') return 'running'
  if (s === 'pending') return 'pending'
  if (s === 'queued') return 'queued'
  if (s === 'skipped') return 'idle'
  if (s === 'cancelled' || s === 'canceled') return 'cancelled'
  if (s === 'timeout' || s === 'timed_out') return 'timeout'
  return 'idle'
}

/** 解析节点错误中的 Agent 输出 schema 校验错误，用于调试展示 */
export function parseAgentSchemaError(message?: string | null): { isSchemaError: boolean; detail: string } | null {
  const m = String(message || '').trim()
  const prefix = 'AGENT_NODE_OUTPUT_SCHEMA_ERROR:'
  if (!m.includes(prefix)) return null
  const detail = m.replace(new RegExp(`^.*${prefix}\\s*`), '').trim()
  return { isSchemaError: true, detail: detail || m }
}

export function statusBadgeClass(status: WorkflowUiStatus): string {
  switch (status) {
    case 'succeeded':
      return 'text-emerald-500 bg-emerald-500/10'
    case 'running':
      return 'text-blue-500 bg-blue-500/10 animate-pulse'
    case 'pending':
    case 'queued':
      return 'text-amber-500 bg-amber-500/10'
    case 'failed':
    case 'timeout':
      return 'text-red-500 bg-red-500/10'
    case 'cancelled':
      return 'text-zinc-400 bg-zinc-500/10'
    default:
      return 'text-muted-foreground bg-muted'
  }
}
