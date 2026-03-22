import { ref, watch } from 'vue'
import { getModelChatParams, saveModelChatParams } from '@/services/api'

const STORAGE_KEY = 'ai_platform_parameters'

export interface Parameters {
  temperature: number
  top_p: number
  maxTokens: number
  contextWindow: number
  systemPrompt: string
  useSystemPrompt: boolean
  maxHistoryMessages: number
}

const MAX_TOKENS_MIN = 256
const MAX_TOKENS_MAX = 8192

const defaults: Parameters = {
  temperature: 0.7,
  top_p: 0.9,
  maxTokens: 4096,
  contextWindow: 16384,
  systemPrompt: 'You are a helpful AI assistant.',
  useSystemPrompt: true,
  maxHistoryMessages: 10
}

function clampMaxTokens(value: number): number {
  return Math.min(MAX_TOKENS_MAX, Math.max(MAX_TOKENS_MIN, value))
}

function loadParameters(): Parameters {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (!saved) return defaults
  try {
    const loaded = { ...defaults, ...JSON.parse(saved) }
    loaded.maxTokens = clampMaxTokens(loaded.maxTokens)
    return loaded
  } catch (e) {
    return defaults
  }
}

const savedParams = loadParameters()

// Singleton state
const temperature = ref(savedParams.temperature)
const top_p = ref(savedParams.top_p)
const maxTokens = ref(savedParams.maxTokens)
const contextWindow = ref(savedParams.contextWindow)
const systemPrompt = ref(savedParams.systemPrompt)
const useSystemPrompt = ref(savedParams.useSystemPrompt)
const maxHistoryMessages = ref(savedParams.maxHistoryMessages)

let activeModelId: string | null = null
let isSyncing = false

/**
 * 从后端加载模型特定参数
 */
async function syncFromModel(modelId: string) {
  if (!modelId || modelId === 'auto') return
  
  activeModelId = modelId
  isSyncing = true
  
  try {
    const res = await getModelChatParams(modelId)
    if (res.success && res.data && Object.keys(res.data).length > 0) {
      const p = res.data as Partial<Parameters>
      if (typeof p.temperature === 'number') temperature.value = p.temperature
      if (typeof p.top_p === 'number') top_p.value = p.top_p
      if (typeof p.maxTokens === 'number') maxTokens.value = clampMaxTokens(p.maxTokens)
      if (typeof p.systemPrompt === 'string') systemPrompt.value = p.systemPrompt
      if (typeof p.useSystemPrompt === 'boolean') useSystemPrompt.value = p.useSystemPrompt
      if (typeof p.maxHistoryMessages === 'number') maxHistoryMessages.value = p.maxHistoryMessages
      // contextWindow 通常是模型固有的，不从这里覆盖，除非有特殊需求
    } else {
      // 如果没有模型特定配置，使用全局/默认值
      // 这里可以选择保持当前值，或者重置回全局 defaults
    }
  } catch (e) {
    console.error('Failed to sync parameters from model:', e)
  } finally {
    isSyncing = false
  }
}

/**
 * 保存到后端
 */
async function syncToModel() {
  if (!activeModelId || activeModelId === 'auto' || isSyncing) return
  
  const toSave: Partial<Parameters> = {
    temperature: temperature.value,
    top_p: top_p.value,
    maxTokens: maxTokens.value,
    systemPrompt: systemPrompt.value,
    useSystemPrompt: useSystemPrompt.value,
    maxHistoryMessages: maxHistoryMessages.value
  }

  try {
    await saveModelChatParams(activeModelId, toSave)
  } catch (e) {
    console.error('Failed to sync parameters to model:', e)
  }
}

// 持久化监听 (本地 localStorage 仍然保留作为全局兜底)
watch(
  [temperature, top_p, maxTokens, contextWindow, systemPrompt, useSystemPrompt, maxHistoryMessages],
  () => {
    const toSave: Parameters = {
      temperature: temperature.value,
      top_p: top_p.value,
      maxTokens: maxTokens.value,
      contextWindow: contextWindow.value,
      systemPrompt: systemPrompt.value,
      useSystemPrompt: useSystemPrompt.value,
      maxHistoryMessages: maxHistoryMessages.value
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave))
    
    // 如果有活动模型，也同步到模型配置
    if (!isSyncing) {
      syncToModel()
    }
  },
  { deep: true }
)

export function useParameters() {
  return {
    temperature,
    top_p,
    maxTokens,
    contextWindow,
    systemPrompt,
    useSystemPrompt,
    maxHistoryMessages,
    syncFromModel
  }
}
