<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Share, Zap, Box, Bot, Loader2, Sparkles, Cpu, Database, X, Search } from 'lucide-vue-next'
import { listModels, listKnowledgeBases, type ModelInfo } from '@/services/api'

const props = defineProps<{
  modelValue: string
  knowledgeBaseId?: string | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'update:knowledgeBaseId', value: string | null): void
}>()

const models = ref<ModelInfo[]>([])
const loadingModels = ref(false)
const knowledgeBases = ref<Array<{ id: string; name: string; description?: string }>>([])
const loadingKBs = ref(false)
const activeModels = ref<Set<string>>(new Set())
const modelSearchQuery = ref('')
const isModelSelectOpen = ref(false)

// 获取模型列表
const fetchModels = async () => {
  loadingModels.value = true
  try {
    const response = await listModels()
    // 只显示 chat 模型（过滤掉 embedding、asr、perception 等非对话模型）
    const allModels = response.data || []
    const chatTypes = ['llm', 'vlm']
    models.value = allModels.filter((m: ModelInfo) => {
      const mt = (m.model_type || '').toLowerCase()
      if (!mt) return true
      return chatTypes.includes(mt)
    })
    
    // 始终添加 Mock Model（如果不存在）
    const hasMockModel = models.value.some(m => m.id === 'mock' || m.backend === 'mock')
    if (!hasMockModel) {
      models.value.unshift({
        id: 'mock',
        name: 'Mock Model',
        display_name: 'Mock Model (Debug)',
        backend: 'mock',
        supports_stream: true,
        description: 'Mock model for local development and testing'
      })
    }
    
    // 更新活跃模型状态
    activeModels.value = new Set()
    allModels.forEach((m: ModelInfo) => {
      if (m.status === 'active') {
        activeModels.value.add(m.id)
      }
    })
  } catch (error) {
    console.error('Failed to fetch models:', error)
    // 如果API失败，使用默认模型列表（包含 Mock Model）
    models.value = [
      { id: 'mock', name: 'Mock Model', display_name: 'Mock Model (Debug)', backend: 'mock', supports_stream: true },
      { id: 'ollama', name: 'Ollama', display_name: 'Ollama (Local)', backend: 'ollama', supports_stream: true },
      { id: 'gpt-4', name: 'GPT-4 Turbo', display_name: 'GPT-4 Turbo (Cloud)', backend: 'openai', supports_stream: true },
    ]
    activeModels.value = new Set()
  } finally {
    loadingModels.value = false
  }
}

// 获取知识库列表
const fetchKnowledgeBases = async () => {
  loadingKBs.value = true
  try {
    const response = await listKnowledgeBases()
    knowledgeBases.value = response.data || []
  } catch (error) {
    console.error('Failed to fetch knowledge bases:', error)
    knowledgeBases.value = []
  } finally {
    loadingKBs.value = false
  }
}

const onKnowledgeBaseChange = (value: any) => {
  if (typeof value === 'string') {
    emit('update:knowledgeBaseId', value === 'none' ? null : value)
  }
}

const clearKnowledgeBase = () => {
  emit('update:knowledgeBaseId', null)
}

onMounted(() => {
  fetchModels()
  fetchKnowledgeBases()
})

const onModelChange = (value: any) => {
  if (typeof value === 'string') {
    emit('update:modelValue', value)
    modelSearchQuery.value = '' // 选择后清空搜索
  }
}

// 根据模型ID获取显示信息
const modelDisplay = computed(() => {
  if (props.modelValue === 'auto') {
    return {
      name: t('chat.header.auto_select'),
      icon: Sparkles,
      details: t('chat.header.best_available')
    }
  }

  const currentModel = models.value.find(m => m.id === props.modelValue)
  if (currentModel) {
    const detailsMap: Record<string, string> = {
      mock: t('chat.header.debug_mode'), lmstudio: t('chat.header.local_inference'),
      ollama: t('chat.header.local_inference'), openai: t('chat.header.cloud_api'),
      gemini: t('chat.header.cloud_api'), deepseek: t('chat.header.cloud_api'),
      kimi: t('chat.header.cloud_api'), local: t('chat.header.local_runtime'),
      'llama.cpp': t('chat.header.local_inference'), openai_compatible: t('chat.header.local_inference'),
    }
    return {
      name: currentModel.display_name || currentModel.name,
      icon: getModelIcon(currentModel.backend),
      details: detailsMap[currentModel.backend] || t('chat.header.unknown')
    }
  }
  
  // 默认映射（兼容旧代码）
  const mapping: Record<string, { name: string; icon: any; details: string }> = {
    'lmstudio': { name: 'LM Studio', icon: Zap, details: t('chat.header.local_inference') },
    'ollama': { name: 'Ollama', icon: Bot, details: t('chat.header.local_inference') },
    'gpt-4': { name: 'GPT-4 Turbo', icon: Zap, details: t('chat.header.cloud_api') },
    'gpt-3.5-turbo': { name: 'GPT-3.5 Turbo', icon: Zap, details: t('chat.header.cloud_api') },
  }
  
  return mapping[props.modelValue] || { 
    name: props.modelValue, 
    icon: Bot, 
    details: t('chat.header.unknown_model') 
  }
})

const MODEL_ICONS: Record<string, any> = {
  mock: Box, lmstudio: Zap, ollama: Bot, openai: Zap, gemini: Sparkles,
  deepseek: Zap, kimi: Sparkles, local: Cpu, 'llama.cpp': Cpu, openai_compatible: Zap,
}
const MODEL_COLORS: Record<string, string> = {
  mock: 'text-orange-500', lmstudio: 'text-blue-500', ollama: 'text-emerald-500',
  openai: 'text-purple-500', gemini: 'text-blue-400', deepseek: 'text-sky-500',
  kimi: 'text-green-500', local: 'text-rose-500', 'llama.cpp': 'text-amber-500', openai_compatible: 'text-violet-500',
}
const getModelIcon = (backend: string) => MODEL_ICONS[backend] || Bot
const getModelBadgeColor = (backend: string) => MODEL_COLORS[backend] || 'text-muted-foreground'

// 过滤模型（根据搜索查询）
const filteredModels = computed(() => {
  if (!modelSearchQuery.value.trim()) {
    return models.value
  }
  
  const query = modelSearchQuery.value.toLowerCase()
  return models.value.filter((m: ModelInfo) => {
    const name = (m.display_name || m.name || '').toLowerCase()
    const desc = (m.description || '').toLowerCase()
    const backend = (m.backend || '').toLowerCase()
    return name.includes(query) || desc.includes(query) || backend.includes(query)
  })
})

// 按类型分组模型，顺序：本地优先 -> 云端 -> 调试
const orderedModelGroups = computed(() => {
  const filtered = filteredModels.value
  const local = filtered.filter((m: ModelInfo) => {
    const b = m.backend ?? 'local'
    return ['lmstudio', 'ollama', 'local', 'llama.cpp', 'openai_compatible'].includes(b)
  })
  const cloud = filtered.filter((m: ModelInfo) => {
    const b = m.backend ?? 'local'
    return ['openai', 'gemini', 'deepseek', 'kimi'].includes(b)
  })
  const debug = filtered.filter((m: ModelInfo) => (m.backend ?? 'local') === 'mock')
  return [
    { key: 'local', label: `💻 ${t('chat.header.group_local')}`, models: local },
    { key: 'cloud', label: `☁️ ${t('chat.header.group_cloud')}`, models: cloud },
    { key: 'debug', label: `🐛 ${t('chat.header.group_debug')}`, models: debug },
  ].filter(g => g.models.length > 0)
})
</script>

<template>
  <header class="h-14 border-b border-border/50 flex items-center justify-between px-6 bg-background shadow-sm sticky top-0 z-10 dark:shadow-none">
    <!-- Left: Model Selector -->
    <div class="flex items-center gap-3">
      <!-- Active Indicator Dot -->
      <div class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
      
      <!-- Model Selector -->
      <Select :model-value="modelValue" @update:model-value="onModelChange" :disabled="loadingModels" @open-change="isModelSelectOpen = $event">
        <SelectTrigger class="w-[300px] h-9 bg-muted/20 border border-border/50 font-medium rounded-xl hover:bg-muted/30 transition-all">
          <div class="flex items-center gap-2 w-full">
            <component :is="modelDisplay.icon" class="w-4 h-4 text-muted-foreground shrink-0" />
            <SelectValue :placeholder="t('chat.header.select_model')" class="flex-1">
              <span class="text-sm">{{ modelDisplay.name }}</span>
            </SelectValue>
            <span class="text-xs text-muted-foreground shrink-0">{{ modelDisplay.details }}</span>
          </div>
        </SelectTrigger>
        <SelectContent class="max-h-[80vh] w-[400px] p-0 model-select-content">
          <!-- Search Bar -->
          <div class="sticky top-0 z-10 bg-popover border-b border-border/50 p-2 shrink-0">
            <div class="relative">
              <Search class="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input 
                v-model="modelSearchQuery"
                :placeholder="t('chat.header.search_models')"
                class="pl-8 h-9 text-sm"
                @click.stop
                @keydown.stop
              />
            </div>
          </div>

          <!-- Model List (scrollable via SelectViewport) -->
          <div class="p-1 model-select-list">
              <!-- Auto Selection -->
              <SelectItem value="auto" class="cursor-pointer border-b border-border/50 mb-1">
                <div class="flex items-center gap-2 w-full py-0.5">
                  <Sparkles class="w-4 h-4 shrink-0 text-emerald-500" />
                  <div class="flex-1 flex flex-col min-w-0">
                    <span class="text-sm font-semibold truncate">{{ t('chat.header.automatic') }}</span>
                    <span class="text-xs text-muted-foreground truncate">{{ t('chat.header.auto_desc') }}</span>
                  </div>
                </div>
              </SelectItem>

              <!-- Model Groups: 本地 -> 云端 -> 调试 -->
              <template v-for="(group, gIdx) in orderedModelGroups" :key="group.key">
                <div class="py-1">
                  <div class="px-2 py-1 text-[10px] font-black tracking-widest text-muted-foreground/60 uppercase">{{ group.label }}</div>
                  <SelectItem 
                    v-for="model in group.models" 
                    :key="model.id" 
                    :value="model.id"
                    class="cursor-pointer py-1.5"
                  >
                    <div class="flex items-center gap-2 w-full">
                      <div class="relative">
                        <component 
                          :is="getModelIcon(model.backend)" 
                          :class="['w-4 h-4 shrink-0', getModelBadgeColor(model.backend)]" 
                        />
                        <div v-if="activeModels.has(model.id)" class="absolute -top-1 -right-1 w-2 h-2 bg-emerald-500 rounded-full"></div>
                      </div>
                      <div class="flex-1 flex flex-col min-w-0">
                        <span class="text-sm font-medium truncate">{{ model.display_name || model.name }}</span>
                        <span class="text-xs text-muted-foreground truncate">{{ model.description || model.backend }}</span>
                      </div>
                      <div class="flex items-center gap-1 shrink-0">
                        <Badge v-if="model.supports_stream" variant="secondary" class="h-4 px-1 text-[9px] bg-emerald-500/10 text-emerald-500 border-none">
                          {{ t('chat.header.stream') }}
                        </Badge>
                        <Badge v-if="activeModels.has(model.id)" variant="secondary" class="h-4 px-1 text-[9px] bg-blue-500/10 text-blue-500 border-none">
                          {{ t('chat.header.active') }}
                        </Badge>
                      </div>
                    </div>
                  </SelectItem>
                </div>
                <div v-if="gIdx < orderedModelGroups.length - 1" class="h-px bg-border/20 mx-2 my-1"></div>
              </template>

              <!-- No Results -->
              <div v-if="!loadingModels && filteredModels.length === 0 && modelSearchQuery.trim()" class="px-4 py-8 text-center text-sm text-muted-foreground">
                {{ t('chat.header.no_models_found') }}
              </div>

              <!-- Loading State -->
              <div v-if="loadingModels" class="px-4 py-4 text-sm text-muted-foreground flex items-center justify-center gap-2">
                <Loader2 class="w-4 h-4 animate-spin" />
                {{ t('chat.header.loading_models') }}
              </div>
            </div>
        </SelectContent>
      </Select>

      <!-- Knowledge Base Selector -->
      <Select 
        :model-value="knowledgeBaseId || 'none'" 
        @update:model-value="onKnowledgeBaseChange" 
        :disabled="loadingKBs"
      >
        <SelectTrigger class="w-[250px] h-9 bg-muted/20 border border-border/50 font-medium rounded-xl hover:bg-muted/30 transition-all">
          <div class="flex items-center gap-2 w-full">
            <Database class="w-4 h-4 text-muted-foreground shrink-0" />
            <SelectValue :placeholder="t('chat.header.kb_placeholder')" class="flex-1">
              <span class="text-sm">
                {{ knowledgeBaseId ? (knowledgeBases.find(kb => kb.id === knowledgeBaseId)?.name || t('chat.header.unknown')) : t('chat.header.no_kb') }}
              </span>
            </SelectValue>
            <button
              v-if="knowledgeBaseId"
              type="button"
              class="h-5 w-5 mr-1 flex items-center justify-center rounded hover:bg-destructive/10 hover:text-destructive transition-colors"
              @click.stop="clearKnowledgeBase"
            >
              <X class="w-3 h-3" />
            </button>
          </div>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none" class="cursor-pointer border-b border-border/50 mb-1">
            <div class="flex items-center gap-2 w-full py-0.5">
              <Database class="w-4 h-4 shrink-0 text-muted-foreground" />
              <div class="flex-1 flex flex-col min-w-0">
                <span class="text-sm font-semibold truncate">{{ t('chat.header.no_kb') }}</span>
                <span class="text-xs text-muted-foreground truncate">{{ t('chat.header.no_rag') }}</span>
              </div>
            </div>
          </SelectItem>

          <SelectItem 
            v-for="kb in knowledgeBases" 
            :key="kb.id" 
            :value="kb.id"
            class="cursor-pointer"
          >
            <div class="flex items-center gap-2 w-full">
              <Database class="w-4 h-4 shrink-0 text-blue-400" />
              <div class="flex-1 flex flex-col min-w-0">
                <span class="text-sm font-medium truncate">{{ kb.name }}</span>
                <span class="text-xs text-muted-foreground truncate">{{ kb.description || t('nav.knowledge') }}</span>
              </div>
            </div>
          </SelectItem>
          <div v-if="loadingKBs" class="px-2 py-1.5 text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 class="w-4 h-4 animate-spin" />
            {{ t('chat.header.loading_kbs') }}
          </div>
          <div v-if="!loadingKBs && knowledgeBases.length === 0" class="px-2 py-1.5 text-sm text-muted-foreground">
            {{ t('chat.header.no_kbs') }}
          </div>
        </SelectContent>
      </Select>
    </div>

    <!-- Right: Actions -->
    <div class="flex items-center gap-2">
      <Button 
        variant="ghost" 
        size="sm" 
        class="h-8 px-3 text-xs text-muted-foreground hover:text-foreground"
        @click="fetchModels"
      >
        {{ t('chat.header.refresh') }}
      </Button>
      <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-foreground">
        <Share class="w-4 h-4" />
      </Button>
    </div>
  </header>
</template>

<!-- 模型下拉 teleport 到 body，需全局选择器使底部模型可滚动可见 -->
<style>
.model-select-content {
  display: flex !important;
  flex-direction: column !important;
  max-height: 80vh !important;
}
.model-select-content [data-reka-select-viewport] {
  height: auto !important;
  max-height: calc(80vh - 60px) !important;
  min-height: 120px !important;
  overflow-y: auto !important;
  overflow-x: hidden !important;
  flex: 1 1 auto !important;
}
</style>
