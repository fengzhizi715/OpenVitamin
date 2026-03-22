/**
 * Workflow Editor 节点库项与画布节点数据类型
 */

export type EditorNodeType =
  | 'start'
  | 'llm'
  | 'agent'
  | 'embedding'
  | 'prompt_template'
  | 'system_prompt'
  | 'input'
  | 'output'
  | 'variable'
  | 'condition'
  | 'loop'
  | 'parallel'
  | 'skill'
  | 'http_request'
  | 'python'
  | 'shell'

export type NodeCategory = 'ai' | 'prompt' | 'data' | 'logic' | 'tool'

export interface NodeLibraryItem {
  type: EditorNodeType
  label: string
  icon: string
  category: NodeCategory
  disabled?: boolean
  disabledReason?: string
}

export interface WorkflowNodeData {
  type: EditorNodeType
  label: string
  subtitle?: string
  /** 与后端 WorkflowNode.config 对应 */
  config: Record<string, unknown>
}

export const NODE_LIBRARY: NodeLibraryItem[] = [
  // AI
  { type: 'llm', label: 'LLM', icon: 'brain', category: 'ai' },
  { type: 'agent', label: 'Agent', icon: 'user', category: 'ai' },
  { type: 'embedding', label: 'Embedding', icon: 'layers', category: 'ai', disabled: true, disabledReason: 'Coming soon' },
  // Prompt
  { type: 'prompt_template', label: 'Prompt Template', icon: 'file-text', category: 'prompt' },
  { type: 'system_prompt', label: 'System Prompt', icon: 'message-square', category: 'prompt', disabled: true, disabledReason: 'Use Prompt Template for now' },
  // Data
  { type: 'input', label: 'Input', icon: 'log-in', category: 'data' },
  { type: 'output', label: 'Output', icon: 'log-out', category: 'data' },
  { type: 'variable', label: 'Variable', icon: 'variable', category: 'data', disabled: true, disabledReason: 'Coming soon' },
  // Logic
  { type: 'condition', label: 'Condition', icon: 'git-branch', category: 'logic' },
  { type: 'loop', label: 'Loop', icon: 'repeat', category: 'logic' },
  { type: 'parallel', label: 'Parallel', icon: 'copy', category: 'logic', disabled: true, disabledReason: 'Coming soon' },
  // Tool
  { type: 'skill', label: 'Skill', icon: 'sparkles', category: 'tool' },
  { type: 'http_request', label: 'HTTP Request', icon: 'globe', category: 'tool', disabled: true, disabledReason: 'Coming soon' },
  { type: 'python', label: 'Python', icon: 'code', category: 'tool', disabled: true, disabledReason: 'Coming soon' },
  { type: 'shell', label: 'Shell', icon: 'terminal', category: 'tool' },
]

export const NODE_CATEGORY_LABELS: Record<NodeCategory, string> = {
  ai: 'AI',
  prompt: 'Prompt',
  data: 'Data',
  logic: 'Logic',
  tool: 'Tool',
}
