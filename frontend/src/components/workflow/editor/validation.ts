/**
 * 工作流编辑器发布/保存前校验：Input/Output 节点配置
 * GAP P1-6：input_key 仅允许字符串；使用 expression 时 output_key 必填
 */
import type { Node } from '@vue-flow/core'
import type { Edge } from '@vue-flow/core'
import type { WorkflowNodeData } from './types'

export interface ValidationError {
  nodeId: string
  nodeLabel?: string
  message: string
}

const DEFAULT_INPUT_KEYS = new Set(['query', 'text', 'prompt', 'message'])

function extractVars(expr: string): string[] {
  const out: string[] = []
  const re = /\$\{([^}]+)\}/g
  let m: RegExpExecArray | null = null
  while ((m = re.exec(expr)) !== null) {
    const token = String(m[1] || '').trim()
    if (token) out.push(token)
  }
  return out
}

export function validateWorkflowNodes(
  nodes: Node<WorkflowNodeData>[]
): { valid: boolean; errors: ValidationError[] } {
  const errors: ValidationError[] = []

  for (const node of nodes) {
    const type = node.data?.type
    const config = (node.data?.config ?? {}) as Record<string, unknown>
    const label = node.data?.label ?? node.id

    if (type === 'input') {
      const inputKey = config.input_key
      if (inputKey !== undefined && inputKey !== null && inputKey !== '') {
        if (typeof inputKey !== 'string') {
          errors.push({
            nodeId: node.id,
            nodeLabel: label,
            message: 'Input 节点：input_key 仅允许字符串',
          })
        }
      }
      const fixedInput = config.fixed_input
      if (fixedInput !== undefined && fixedInput !== null) {
        if (typeof fixedInput !== 'object' || Array.isArray(fixedInput)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: label,
            message: 'Input 节点：fixed_input 须为合法 JSON 对象',
          })
        }
      }
      const schema = config.input_schema
      if (schema !== undefined && schema !== null) {
        if (typeof schema !== 'object' || Array.isArray(schema)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: label,
            message: 'Input 节点：input_schema 须为合法 JSON 对象',
          })
        }
      }
    }

    if (type === 'output') {
      const expression = (config.expression as string)?.trim?.() ?? ''
      const outputKey = config.output_key
      const outputKeyStr =
        outputKey === undefined || outputKey === null ? '' : String(outputKey).trim()

      if (expression !== '' && outputKeyStr === '') {
        errors.push({
          nodeId: node.id,
          nodeLabel: label,
          message: 'Output 节点：使用 expression 时 output_key 必填',
        })
      }
    }
  }

  return {
    valid: errors.length === 0,
    errors,
  }
}

export function validateWorkflowPreflight(
  nodes: Node<WorkflowNodeData>[],
  edges: Edge[],
): { valid: boolean; errors: ValidationError[] } {
  const errors: ValidationError[] = []
  const nodeById = new Map(nodes.map((n) => [n.id, n]))

  const inputFixedInputKeySet = new Set<string>(DEFAULT_INPUT_KEYS)
  let inputQueryDefault: unknown = undefined
  for (const node of nodes) {
    if (node.data?.type !== 'input') continue
    const cfg = (node.data?.config ?? {}) as Record<string, unknown>
    const fixed = cfg.fixed_input
    if (fixed && typeof fixed === 'object' && !Array.isArray(fixed)) {
      for (const k of Object.keys(fixed as Record<string, unknown>)) inputFixedInputKeySet.add(k)
      if (inputQueryDefault === undefined && Object.prototype.hasOwnProperty.call(fixed, 'query')) {
        inputQueryDefault = (fixed as Record<string, unknown>).query
      }
    }
  }

  for (const node of nodes) {
    if (node.data?.type !== 'condition') continue
    const label = node.data?.label ?? node.id
    const cfg = (node.data?.config ?? {}) as Record<string, unknown>
    const expr = String(cfg.condition_expression ?? '').trim()
    if (!expr) {
      errors.push({
        nodeId: node.id,
        nodeLabel: label,
        message: 'Condition 节点：condition_expression 为空，请填写条件表达式',
      })
      continue
    }

    const vars = extractVars(expr)
    for (const v of vars) {
      if (v.startsWith('input.')) {
        const key = v.slice('input.'.length).split('.')[0]
        if (key && !inputFixedInputKeySet.has(key)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: label,
            message: `Condition 变量不存在：\${${v}}。当前 Input 未提供该字段（可用: ${Array.from(inputFixedInputKeySet).join(', ')})`,
          })
        }
      } else if (v.startsWith('nodes.')) {
        const parts = v.split('.')
        const refNodeId = parts[1]
        if (!refNodeId || !nodeById.has(refNodeId)) {
          errors.push({
            nodeId: node.id,
            nodeLabel: label,
            message: `Condition 引用了不存在的节点变量：\${${v}}`,
          })
        }
      }
    }

    if (
      (expr.includes('${input.query}') || expr.includes('${global.input_data.query}')) &&
      (inputQueryDefault === '' || inputQueryDefault === null)
    ) {
      errors.push({
        nodeId: node.id,
        nodeLabel: label,
        message: 'Condition 可能恒为 false：query 默认值为空，请检查 Input.fixed_input.query 或执行入参 input_data.query',
      })
    }
  }

  // 检查 Condition 出边 true/false 是否都存在（编辑器内快速预检）
  for (const node of nodes) {
    if (node.data?.type !== 'condition') continue
    const label = node.data?.label ?? node.id
    const out = edges.filter((e) => e.source === node.id)
    const triggerSet = new Set(out.map((e) => String(e.sourceHandle || e.label || '').toLowerCase()))
    const hasTrue = triggerSet.has('true') || triggerSet.has('condition_true')
    const hasFalse = triggerSet.has('false') || triggerSet.has('condition_false')
    if (!hasTrue || !hasFalse) {
      errors.push({
        nodeId: node.id,
        nodeLabel: label,
        message: 'Condition 分支不完整：需要同时配置 true 与 false 两条出边',
      })
    }
  }

  return { valid: errors.length === 0, errors }
}
