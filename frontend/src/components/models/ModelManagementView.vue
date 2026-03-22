<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { 
  Search, 
  RotateCw, 
  Plus, 
  Settings, 
  Cpu, 
  Bot, 
  Zap, 
  Activity,
  Globe,
  X,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Star,
  ChevronDown,
  ChevronUp,
  Eye,
  Mic,
  ScanSearch,
  Layers,
  Image as ImageIcon
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import ModelConfigSidebar from './ModelConfigSidebar.vue'
import { 
  listModels, 
  scanModels, 
  getSystemConfig, 
  registerModel,
  type SystemConfig 
} from '@/services/api'
import { useNavigation } from '@/composables/useNavigation'

const { activeView } = useNavigation()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()

type ModelAsset = {
  id: string
  name: string
  size?: string
  format: string
  source: string
  status: 'active' | 'detached'
  backend?: string
  runtime?: string
  modelType?: string
  capabilities?: string[]
  tags?: string[]
  quant?: string
  device?: string
  description?: string
  loading?: boolean
}

const models = ref<ModelAsset[]>([])
const loading = ref(false)
const scanning = ref(false)
const searchQuery = ref('')
const systemConfig = ref<SystemConfig | null>(null)
const selectedModelId = ref<string | null>(null)
const expandedModelIds = ref<Set<string>>(new Set())
const navCollapsed = ref(false)

const isExpanded = (id: string) => expandedModelIds.value.has(id)
const toggleExpand = (id: string) => {
  if (expandedModelIds.value.has(id)) expandedModelIds.value.delete(id)
  else expandedModelIds.value.add(id)
}

const selectedModel = computed(() =>
  models.value.find(m => m.id === selectedModelId.value) || null
)

// Sorting and Filtering
const locationFilter = ref<'all' | 'local' | 'cloud'>('all')

// Pagination
const currentPage = ref(1)
const itemsPerPage = ref(12)

const isCloudBackend = (b?: string) => ['openai', 'gemini', 'deepseek', 'kimi', 'ollama', 'lmstudio'].includes((b || '').toLowerCase())

const capabilityFilter = computed(() => route.meta.capability as string | undefined)
const perceptionSubtype = computed(() => route.meta.subtype as string | undefined)

const normalize = (value?: string) => (value || '').toLowerCase()
const containsAny = (haystack: string, keywords: string[]) => keywords.some(k => haystack.includes(k))

const matchesCapability = (model: ModelAsset) => {
  const category = capabilityFilter.value
  if (!category) return true

  const modelType = normalize(model.modelType)
  const capabilities = (model.capabilities || []).map(c => normalize(c))
  const tags = (model.tags || []).map(t => normalize(t))
  const text = [
    model.name,
    model.id,
    model.description,
    model.backend,
    model.runtime,
    ...(model.capabilities || []),
    ...(model.tags || [])
  ]
    .filter(Boolean)
    .map(v => normalize(String(v)))
    .join(' ')

  const hasCapability = (value: string) =>
    modelType === value ||
    capabilities.includes(value) ||
    tags.includes(value) ||
    text.includes(value)

  if (category === 'llm') return hasCapability('llm') || capabilities.includes('chat')
  if (category === 'vlm') return hasCapability('vlm') || capabilities.includes('vision')
  if (category === 'asr') return hasCapability('asr') || containsAny(text, ['speech', 'audio', 'transcribe'])
  if (category === 'embedding') return hasCapability('embedding') || capabilities.includes('embed')
  if (category === 'image_generation') {
    return (
      hasCapability('image_generation') ||
      capabilities.includes('text_to_image') ||
      containsAny(text, ['image generation', 'text_to_image', 'text-to-image', 'diffusion', 'sdxl', 'flux', 'qwen-image'])
    )
  }
  if (category === 'perception') {
    const baseOk = hasCapability('perception') || containsAny(text, ['vision', 'perception'])
    if (!baseOk) return false
    if (!perceptionSubtype.value) return true
    if (perceptionSubtype.value === 'object-detection') {
      return containsAny(text, ['detect', 'detection', 'object', 'bbox', 'yolo'])
    }
    if (perceptionSubtype.value === 'segmentation') {
      return containsAny(text, ['segment', 'segmentation', 'mask'])
    }
    if (perceptionSubtype.value === 'tracking') {
      return containsAny(text, ['track', 'tracking', 'motion'])
    }
  }
  return true
}

const filteredModels = computed(() => {
  let result = [...models.value]
  
  // Search
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(m => 
      m.name.toLowerCase().includes(query) || 
      m.id.toLowerCase().includes(query)
    )
  }

  // Capability Filter
  result = result.filter(matchesCapability)

  // Location Filter (local / cloud)
  if (locationFilter.value !== 'all') {
    if (locationFilter.value === 'cloud') {
      result = result.filter(m => isCloudBackend(m.backend))
    } else if (locationFilter.value === 'local') {
      result = result.filter(m => !isCloudBackend(m.backend))
    }
  }
  
  return result
})

// Paginated models
const paginatedModels = computed(() => {
  const start = (currentPage.value - 1) * itemsPerPage.value
  const end = start + itemsPerPage.value
  return filteredModels.value.slice(start, end)
})

const totalPages = computed(() => Math.ceil(filteredModels.value.length / itemsPerPage.value))

// Get visible page numbers (show max 7 pages around current page)
const visiblePages = computed(() => {
  const pages: number[] = []
  const maxVisible = 7
  const half = Math.floor(maxVisible / 2)
  
  let start = Math.max(1, currentPage.value - half)
  let end = Math.min(totalPages.value, start + maxVisible - 1)
  
  // Adjust start if we're near the end
  if (end - start < maxVisible - 1) {
    start = Math.max(1, end - maxVisible + 1)
  }
  
  for (let i = start; i <= end; i++) {
    pages.push(i)
  }
  
  return pages
})

const hasVisiblePages = computed(() => visiblePages.value.length > 0)
const firstVisiblePage = computed(() => visiblePages.value[0] ?? 1)
const lastVisiblePage = computed(() => visiblePages.value[visiblePages.value.length - 1] ?? 1)

// Reset to page 1 when filters change
watch([searchQuery, locationFilter], () => {
  currentPage.value = 1
})

watch(() => route.fullPath, () => {
  currentPage.value = 1
})

const fetchModels = async () => {
  loading.value = true
  try {
    const [modelsRes, configRes] = await Promise.all([
      listModels(),
      getSystemConfig()
    ])
    
    systemConfig.value = configRes
    
    // Map backend response to ModelAsset interface
    models.value = modelsRes.data.map((m: any) => ({
      ...m,
      id: m.id,
      name: m.name,
      format: m.format || t('models.registry.unknown'),
      source: m.source || t('models.registry.unknown'),
      size: m.size || t('models.registry.unknown'),
      status: m.status || 'detached',
      backend: m.backend,
      runtime: m.runtime || m.backend || t('models.registry.local_runtime'),
      modelType: m.model_type || m.modelType || m.type,
      capabilities: m.capabilities || [],
      tags: m.tags || [],
      quant: m.quantization || t('models.registry.unknown'),
      device: m.device || t('models.registry.cpu'),
      loading: false
    }))
  } catch (error) {
    console.error('Failed to fetch models:', error)
  } finally {
    loading.value = false
  }
}

const handleScan = async () => {
  if (scanning.value) return
  scanning.value = true
  try {
    await scanModels()
    await fetchModels()
  } catch (error) {
    console.error('Scan failed:', error)
  } finally {
    scanning.value = false
  }
}

onMounted(() => {
  fetchModels()
})

// Refresh data when switching to this view
watch(() => activeView.value, (newView) => {
  if (newView === 'models') {
    fetchModels()
  }
})

const handleSettings = (modelId: string) => {
  selectedModelId.value = modelId
}

// Add Cloud Model Dialog
const showAddCloudDialog = ref(false)
const addingCloudModel = ref(false)
const cloudModelForm = ref({
  id: '',
  name: '',
  provider: 'openai',
  provider_model_id: '',
  runtime: 'openai',
  base_url: '',
  api_key: '',
  description: ''
})

const providerOptions = [
  { value: 'openai', label: t('models.provider_labels.openai'), defaultUrl: 'https://api.openai.com/v1', runtime: 'openai' },
  { value: 'gemini', label: t('models.provider_labels.gemini'), defaultUrl: 'https://generativelanguage.googleapis.com/v1beta/openai', runtime: 'gemini' },
  { value: 'deepseek', label: t('models.provider_labels.deepseek'), defaultUrl: 'https://api.deepseek.com', runtime: 'deepseek' },
  { value: 'kimi', label: t('models.provider_labels.kimi'), defaultUrl: 'https://api.moonshot.cn/v1', runtime: 'kimi' },
  { value: 'lmstudio', label: t('models.provider_labels.lmstudio'), defaultUrl: 'http://localhost:1234/v1', runtime: 'lmstudio' },
  { value: 'ollama', label: t('models.provider_labels.ollama'), defaultUrl: 'http://localhost:11434', runtime: 'ollama' },
  { value: 'custom', label: t('models.add_cloud_dialog.custom_provider'), defaultUrl: '', runtime: 'openai' }
]

watch(() => cloudModelForm.value.provider, (newProvider) => {
  const option = providerOptions.find(o => o.value === newProvider)
  if (option) {
    cloudModelForm.value.base_url = option.defaultUrl
    cloudModelForm.value.runtime = option.runtime
    // Auto-fill ID and Name if empty
    if (!cloudModelForm.value.id && cloudModelForm.value.provider_model_id) {
       cloudModelForm.value.id = `${newProvider}:${cloudModelForm.value.provider_model_id}`
    }
  }
})

const handleAddCloudModel = async () => {
  addingCloudModel.value = true
  try {
    await registerModel({
      id: cloudModelForm.value.id || `${cloudModelForm.value.provider}:${cloudModelForm.value.provider_model_id}`,
      name: cloudModelForm.value.name || cloudModelForm.value.provider_model_id,
      provider: cloudModelForm.value.provider,
      provider_model_id: cloudModelForm.value.provider_model_id,
      runtime: cloudModelForm.value.runtime,
      base_url: cloudModelForm.value.base_url,
      api_key: cloudModelForm.value.api_key,
      description: cloudModelForm.value.description
    })
    showAddCloudDialog.value = false
    // Reset form
    cloudModelForm.value = {
      id: '',
      name: '',
      provider: 'openai',
      provider_model_id: '',
      runtime: 'openai',
      base_url: '',
      api_key: '',
      description: ''
    }
    await fetchModels()
  } catch (error) {
    console.error('Failed to register cloud model:', error)
    alert(t('models.register_failed') + ': ' + (error instanceof Error ? error.message : String(error)))
  } finally {
    addingCloudModel.value = false
  }
}
</script>

<template>
  <div class="flex-1 flex overflow-hidden bg-background">
    <!-- Main Content -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Header -->
      <header class="h-16 border-b border-border/60 flex items-center justify-between px-8 bg-background/90 backdrop-blur">
        <div class="flex items-center gap-4">
          <div class="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
            <span class="tracking-wide uppercase">{{ t('models.registry.breadcrumb_registry') }}</span>
            <span class="opacity-40">/</span>
            <span class="text-foreground">{{ t('models.registry.breadcrumb_models') }}</span>
          </div>
          <div class="hidden md:flex items-center gap-2 text-[10px] font-mono text-emerald-500/80">
            <div class="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]"></div>
            {{ systemConfig?.ollama_base_url || 'localhost:11434' }}
          </div>
        </div>

        <div class="flex items-center gap-3">
          <div class="relative">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input 
              v-model="searchQuery"
              :placeholder="t('models.registry.filter_placeholder')" 
              class="w-[260px] pl-10 h-10 bg-muted/20 border-border/50 focus:bg-muted/30 transition-all rounded-xl text-sm"
            />
          </div>
          <Button 
            class="h-10 px-4 rounded-xl bg-blue-600 hover:bg-blue-700 text-white flex items-center gap-2"
            @click="showAddCloudDialog = true"
          >
            <Plus class="w-4 h-4" />
            {{ t('models.registry.cloud_model') }}
          </Button>
          <Button 
            variant="outline" 
            size="icon" 
            class="h-10 w-10 border-border/50 bg-muted/10 hover:bg-muted/20"
            :disabled="scanning"
            @click="handleScan"
          >
            <RotateCw class="w-4 h-4" :class="{ 'animate-spin': scanning }" />
          </Button>
          
        </div>
      </header>

      <ScrollArea class="flex-1">
        <div class="px-6 py-8 w-full">
          <div class="flex gap-6">
            <!-- Capability Navigation -->
            <aside
              class="shrink-0 hidden lg:block transition-all duration-200"
              :class="navCollapsed ? 'w-16' : 'w-56'"
            >
              <div class="flex items-center justify-between mb-4">
                <div v-if="!navCollapsed" class="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                  {{ t('models.registry.capability_nav') }}
                </div>
                <button
                  class="h-7 w-7 rounded-lg border border-border/50 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
                  @click="navCollapsed = !navCollapsed"
                >
                  <ChevronLeft v-if="!navCollapsed" class="w-4 h-4" />
                  <ChevronRight v-else class="w-4 h-4" />
                </button>
              </div>
              <div class="space-y-2">
                <button
                  class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
                  :class="capabilityFilter === 'llm' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
                  @click="router.push('/models/llm')"
                >
                  <span v-if="!navCollapsed">{{ t('models.registry.nav_llm') }}</span>
                  <span v-else class="flex items-center justify-center">
                    <Cpu class="w-4 h-4" />
                  </span>
                </button>
                <button
                  class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
                  :class="capabilityFilter === 'vlm' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
                  @click="router.push('/models/vlm')"
                >
                  <span v-if="!navCollapsed">{{ t('models.registry.nav_vlm') }}</span>
                  <span v-else class="flex items-center justify-center">
                    <Eye class="w-4 h-4" />
                  </span>
                </button>
                <button
                  class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
                  :class="capabilityFilter === 'asr' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
                  @click="router.push('/models/asr')"
                >
                  <span v-if="!navCollapsed">{{ t('models.registry.nav_asr') }}</span>
                  <span v-else class="flex items-center justify-center">
                    <Mic class="w-4 h-4" />
                  </span>
                </button>
                <div class="space-y-1">
                  <button
                    class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
                    :class="capabilityFilter === 'perception' && !perceptionSubtype ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
                    @click="router.push('/models/perception')"
                  >
                    <span v-if="!navCollapsed">{{ t('models.registry.nav_perception') }}</span>
                    <span v-else class="flex items-center justify-center">
                      <ScanSearch class="w-4 h-4" />
                    </span>
                  </button>
                  <div v-if="!navCollapsed" class="ml-3 space-y-1">
                    <button
                      class="w-full text-left text-xs font-medium px-3 py-2 rounded-lg transition-colors"
                      :class="capabilityFilter === 'perception' && perceptionSubtype === 'object-detection' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40 text-muted-foreground'"
                      @click="router.push('/models/perception/object-detection')"
                    >
                      {{ t('models.registry.object_detection') }}
                    </button>
                    <button
                      class="w-full text-left text-xs font-medium px-3 py-2 rounded-lg transition-colors"
                      :class="capabilityFilter === 'perception' && perceptionSubtype === 'segmentation' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40 text-muted-foreground'"
                      @click="router.push('/models/perception/segmentation')"
                    >
                      {{ t('models.registry.segmentation') }}
                    </button>
                    <button
                      class="w-full text-left text-xs font-medium px-3 py-2 rounded-lg transition-colors"
                      :class="capabilityFilter === 'perception' && perceptionSubtype === 'tracking' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40 text-muted-foreground'"
                      @click="router.push('/models/perception/tracking')"
                    >
                      {{ t('models.registry.tracking') }}
                    </button>
                  </div>
                </div>
                <button
                  class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
                  :class="capabilityFilter === 'image_generation' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
                  @click="router.push('/models/image-generation')"
                >
                  <span v-if="!navCollapsed">{{ t('models.registry.nav_image_generation') }}</span>
                  <span v-else class="flex items-center justify-center">
                    <ImageIcon class="w-4 h-4" />
                  </span>
                </button>
                <button
                  class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
                  :class="capabilityFilter === 'embedding' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
                  @click="router.push('/models/embedding')"
                >
                  <span v-if="!navCollapsed">{{ t('models.registry.nav_embedding') }}</span>
                  <span v-else class="flex items-center justify-center">
                    <Layers class="w-4 h-4" />
                  </span>
                </button>
              </div>
            </aside>

            <!-- Main Panel -->
            <div class="flex-1 space-y-8">
              <!-- Page Title -->
              <div class="flex flex-col lg:flex-row lg:items-end justify-between gap-6">
                <div class="space-y-2">
                  <h1 class="text-3xl font-black tracking-tight text-foreground">{{ t('models.registry.model_registry') }}</h1>
                  <p class="text-sm text-muted-foreground/70 font-medium">{{ t('models.registry.model_registry_desc') }}</p>
                </div>
                <div class="flex items-center gap-2 bg-muted/20 p-1 rounded-xl border border-border/40">
                  <button
                    class="h-8 px-4 text-xs font-semibold rounded-lg transition-colors"
                    :class="locationFilter === 'all' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
                    @click="locationFilter = 'all'"
                  >
                    {{ t('models.registry.location_all') }}
                  </button>
                  <button
                    class="h-8 px-4 text-xs font-semibold rounded-lg transition-colors"
                    :class="locationFilter === 'local' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
                    @click="locationFilter = 'local'"
                  >
                    {{ t('models.registry.location_local') }}
                  </button>
                  <button
                    class="h-8 px-4 text-xs font-semibold rounded-lg transition-colors"
                    :class="locationFilter === 'cloud' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
                    @click="locationFilter = 'cloud'"
                  >
                    {{ t('models.registry.location_cloud') }}
                  </button>
                </div>
              </div>

              <!-- List -->
              <div v-if="paginatedModels.length > 0" class="rounded-2xl border border-border/60 bg-muted/10 overflow-hidden shadow-sm">
                <div class="grid grid-cols-12 gap-4 px-5 py-3 text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70 border-b border-border/50">
                  <div class="col-span-1"></div>
                  <div class="col-span-4">{{ t('models.registry.table_model_name') }}</div>
                  <div class="col-span-2">{{ t('models.registry.table_provider') }}</div>
                  <div class="col-span-2">{{ t('models.registry.table_runtime') }}</div>
                  <div class="col-span-2">{{ t('models.registry.table_status') }}</div>
                  <div class="col-span-1 text-right">{{ t('models.registry.table_default') }}</div>
                </div>

                <div v-for="model in paginatedModels" :key="model.id" class="border-b border-border/40 last:border-b-0">
                  <div class="grid grid-cols-12 gap-4 px-5 py-4 items-center">
                    <button
                      class="col-span-1 h-8 w-8 rounded-lg flex items-center justify-center hover:bg-muted/40 transition-colors"
                      @click="toggleExpand(model.id)"
                    >
                      <ChevronDown v-if="!isExpanded(model.id)" class="w-4 h-4 text-muted-foreground" />
                      <ChevronUp v-else class="w-4 h-4 text-muted-foreground" />
                    </button>

                    <div class="col-span-4">
                      <div class="text-sm font-semibold text-foreground">{{ model.name }}</div>
                      <div class="text-[11px] text-muted-foreground font-mono">{{ model.id }}</div>
                      <div class="mt-1 text-[11px] text-muted-foreground">
                        {{ model.modelType || '-' }}
                        <span v-if="model.capabilities?.length"> · {{ model.capabilities.join(', ') }}</span>
                      </div>
                    </div>

                    <div class="col-span-2">
                      <Badge variant="outline" class="text-[10px] font-semibold">
                        {{ isCloudBackend(model.backend) ? t('models.registry.badge_cloud') : t('models.registry.badge_local') }}
                      </Badge>
                      <div class="text-[11px] text-muted-foreground mt-1">{{ (model.backend || t('models.registry.local_runtime')).toUpperCase() }}</div>
                    </div>

                    <div class="col-span-2">
                      <div class="text-sm font-medium">{{ model.runtime || t('models.registry.local_runtime') }}</div>
                      <div class="text-[11px] text-muted-foreground">{{ model.device || t('models.registry.cpu') }}</div>
                    </div>

                    <div class="col-span-2">
                      <div class="flex items-center gap-2 text-sm font-medium">
                        <span
                          class="w-2 h-2 rounded-full"
                          :class="model.status === 'active' ? 'bg-emerald-500' : 'bg-slate-400'"
                        ></span>
                        {{ model.status === 'active' ? t('models.registry.status_active') : t('models.registry.status_ready') }}
                      </div>
                      <div class="text-[11px] text-muted-foreground">{{ model.size || t('models.registry.unknown') }}</div>
                    </div>

                    <div class="col-span-1 flex justify-end">
                      <Star class="w-4 h-4 text-muted-foreground/60" />
                    </div>
                  </div>

                  <div v-if="isExpanded(model.id)" class="border-t border-border/50 bg-muted/5">
                    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 p-6">
                      <div class="space-y-4">
                        <div class="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">{{ t('models.registry.page_capability_info') }}</div>
                        <div class="rounded-xl border border-border/60 bg-background/60 p-4">
                          <div class="text-xs font-semibold text-foreground mb-3">{{ t('models.registry.page_model_metadata') }}</div>
                          <div class="grid grid-cols-2 gap-3 text-xs text-muted-foreground">
                            <div>{{ t('models.registry.label_model_type') }}: <span class="text-foreground">{{ model.modelType || '-' }}</span></div>
                            <div>{{ t('models.registry.label_format') }}: <span class="text-foreground">{{ model.format }}</span></div>
                            <div>{{ t('models.registry.label_quant') }}: <span class="text-foreground">{{ model.quant }}</span></div>
                            <div>{{ t('models.registry.label_source') }}: <span class="text-foreground">{{ model.source }}</span></div>
                            <div>{{ t('models.registry.label_size') }}: <span class="text-foreground">{{ model.size }}</span></div>
                          </div>
                        </div>
                        <div class="rounded-xl border border-border/60 bg-background/60 p-4">
                          <div class="text-xs font-semibold text-foreground mb-2">{{ t('models.registry.page_description') }}</div>
                          <div class="text-sm text-muted-foreground">
                            {{ model.description || t('models.registry.page_no_description') }}
                          </div>
                        </div>
                      </div>

                      <div class="space-y-4">
                        <div class="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">{{ t('models.registry.page_runtime_binding') }}</div>
                        <div class="rounded-xl border border-border/60 bg-background/60 p-4">
                          <div class="text-xs font-semibold text-foreground mb-3">{{ t('models.registry.page_runtime_details') }}</div>
                          <div class="grid grid-cols-2 gap-3 text-xs text-muted-foreground">
                            <div>{{ t('models.registry.label_backend') }}: <span class="text-foreground">{{ model.backend || t('models.registry.local_runtime') }}</span></div>
                            <div>{{ t('models.registry.label_runtime') }}: <span class="text-foreground">{{ model.runtime || t('models.registry.local_runtime') }}</span></div>
                            <div>{{ t('models.registry.label_device') }}: <span class="text-foreground">{{ model.device || t('models.registry.cpu') }}</span></div>
                            <div>{{ t('models.registry.label_id') }}: <span class="text-foreground">{{ model.id }}</span></div>
                          </div>
                        </div>
                        <div class="flex items-center gap-2">
                          <Button
                            v-if="!isCloudBackend(model.backend)"
                            variant="outline"
                            size="sm"
                            class="h-9"
                            @click="router.push(`/models/${model.id}/config`)"
                          >
                            {{ t('models.registry.open_config') }}
                          </Button>
                          <Button variant="outline" size="sm" class="h-9" @click="handleSettings(model.id)">
                            {{ t('models.registry.configure') }}
                          </Button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Empty State -->
              <div v-else-if="!loading" class="flex flex-col items-center justify-center py-20 space-y-4 border-2 border-dashed border-border/20 rounded-3xl">
                <div class="w-16 h-16 rounded-full bg-muted/30 flex items-center justify-center">
                  <Bot class="w-8 h-8 text-muted-foreground/40" />
                </div>
                <div class="text-center">
                  <h3 class="text-lg font-bold">{{ t('models.no_models') }}</h3>
                  <p class="text-sm text-muted-foreground">{{ t('models.no_models_desc') }}</p>
                </div>
                <Button variant="outline" class="mt-4" @click="handleScan">
                  {{ t('models.scan_button') }}
                </Button>
              </div>

              <!-- Pagination -->
              <div v-if="filteredModels.length > 0" class="mt-8 pt-6 border-t border-border/50 flex items-center justify-between">
                <div class="text-sm text-muted-foreground">
                  {{ t('models.pagination.showing', { 
                    start: (currentPage - 1) * itemsPerPage + 1, 
                    end: Math.min(currentPage * itemsPerPage, filteredModels.length),
                    total: filteredModels.length 
                  }) }}
                  <span class="ml-2 text-xs text-muted-foreground/70">{{ t('models.pagination.page_of', { current: currentPage, total: totalPages || 1 }) }}</span>
                </div>
                <div class="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-9 w-9 p-0"
                    :disabled="currentPage === 1"
                    @click="currentPage--"
                  >
                    <ChevronLeft class="w-4 h-4" />
                  </Button>
                  <div class="flex items-center gap-1">
                    <!-- First page -->
                    <button
                      v-if="hasVisiblePages && firstVisiblePage > 1"
                      @click="currentPage = 1"
                      class="h-9 min-w-9 px-2 text-sm rounded-lg transition-colors font-medium bg-muted/30 text-muted-foreground hover:bg-muted/50"
                    >
                      1
                    </button>
                    <span v-if="hasVisiblePages && firstVisiblePage > 2" class="px-2 text-muted-foreground">...</span>
                    
                    <!-- Visible pages -->
                    <button
                      v-for="page in visiblePages"
                      :key="page"
                      @click="currentPage = page"
                      class="h-9 min-w-9 px-2 text-sm rounded-lg transition-colors font-medium"
                      :class="currentPage === page 
                        ? 'bg-primary text-primary-foreground' 
                        : 'bg-muted/30 text-muted-foreground hover:bg-muted/50'"
                    >
                      {{ page }}
                    </button>
                    
                    <!-- Last page -->
                    <span v-if="hasVisiblePages && lastVisiblePage < totalPages - 1" class="px-2 text-muted-foreground">...</span>
                    <button
                      v-if="hasVisiblePages && lastVisiblePage < totalPages"
                      @click="currentPage = totalPages"
                      class="h-9 min-w-9 px-2 text-sm rounded-lg transition-colors font-medium bg-muted/30 text-muted-foreground hover:bg-muted/50"
                    >
                      {{ totalPages }}
                    </button>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-9 w-9 p-0"
                    :disabled="currentPage === totalPages"
                    @click="currentPage++"
                  >
                    <ChevronRight class="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </ScrollArea>
    </div>

    <!-- Config Sidebar (non-local: runtime config; local: runtime config) -->
    <transition
      enter-active-class="transition-transform duration-300 ease-out"
      enter-from-class="translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transition-transform duration-200 ease-in"
      leave-from-class="translate-x-0"
      leave-to-class="translate-x-full"
    >
      <ModelConfigSidebar
        v-if="selectedModel"
        :model="selectedModel"
        @close="selectedModelId = null"
        @update="fetchModels"
      />
    </transition>

    <!-- Add Cloud Model Dialog -->
    <Teleport to="body">
      <div v-if="showAddCloudDialog" class="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
        <div class="bg-background border border-border rounded-2xl shadow-2xl max-w-2xl w-full overflow-hidden flex flex-col h-[90vh] max-h-[90vh]">
          <div class="flex-shrink-0 p-6 border-b border-border/50 flex items-center justify-between bg-muted/5">
            <div class="flex items-center gap-4">
              <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 shadow-inner">
                <Globe class="w-6 h-6" />
              </div>
              <div>
                <h3 class="text-xl font-black tracking-tight text-foreground">{{ t('models.add_cloud_dialog.title') }}</h3>
                <p class="text-xs text-muted-foreground font-medium">{{ t('models.add_cloud_dialog.subtitle') }}</p>
              </div>
            </div>
            <Button variant="ghost" size="icon" class="rounded-full hover:bg-muted" @click="showAddCloudDialog = false">
              <X class="w-5 h-5" />
            </Button>
          </div>

          <ScrollArea class="flex-1 min-h-0">
            <div class="p-8 space-y-8">
              <!-- Section 1: Provider Selection -->
              <div class="space-y-4">
                <div class="flex items-center gap-2">
                  <div class="w-1 h-4 bg-blue-500 rounded-full"></div>
                  <label class="text-xs font-black tracking-widest text-foreground uppercase">{{ t('models.add_cloud_dialog.step1') }}</label>
                </div>
                
                <div class="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <button 
                    v-for="opt in providerOptions" 
                    :key="opt.value"
                    type="button"
                    :class="[
                      'flex flex-col items-center justify-center p-4 rounded-xl border-2 transition-all gap-2 text-center group',
                      cloudModelForm.provider === opt.value 
                        ? 'border-blue-500 bg-blue-500/5 shadow-sm' 
                        : 'border-border/50 bg-muted/20 hover:border-border hover:bg-muted/40'
                    ]"
                    @click="cloudModelForm.provider = opt.value"
                  >
                    <div :class="[
                      'w-10 h-10 rounded-lg flex items-center justify-center mb-1 transition-colors',
                      cloudModelForm.provider === opt.value ? 'bg-blue-500 text-white' : 'bg-muted-foreground/10 text-muted-foreground group-hover:bg-muted-foreground/20'
                    ]">
                      <Bot v-if="opt.value === 'openai'" class="w-6 h-6" />
                      <Zap v-else-if="opt.value === 'gemini'" class="w-6 h-6" />
                      <Activity v-else-if="opt.value === 'deepseek'" class="w-6 h-6" />
                      <Cpu v-else-if="opt.value === 'kimi'" class="w-6 h-6" />
                      <Zap v-else-if="opt.value === 'lmstudio'" class="w-6 h-6" />
                      <Cpu v-else-if="opt.value === 'ollama'" class="w-6 h-6" />
                      <Plus v-else class="w-6 h-6" />
                    </div>
                    <span class="text-xs font-bold tracking-tight">{{ opt.label }}</span>
                  </button>
                </div>
              </div>

              <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                <!-- Section 2: Model Identity -->
                <div class="space-y-6">
                  <div class="flex items-center gap-2">
                    <div class="w-1 h-4 bg-emerald-500 rounded-full"></div>
                    <label class="text-xs font-black tracking-widest text-foreground uppercase">{{ t('models.add_cloud_dialog.step2') }}</label>
                  </div>

                  <div class="space-y-4">
                    <div class="space-y-2">
                      <div class="flex items-center justify-between">
                        <label class="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">{{ t('models.add_cloud_dialog.provider_model_id') }}</label>
                        <Badge variant="outline" class="text-[8px] font-black h-4 px-1 opacity-50">{{ t('models.add_cloud_dialog.required') }}</Badge>
                      </div>
                      <Input 
                        v-model="cloudModelForm.provider_model_id" 
                        :placeholder="t('models.add_cloud_dialog.provider_model_id_example')" 
                        class="h-11 bg-muted/20 border-border/40 focus:ring-1 focus:ring-blue-500 transition-all rounded-xl" 
                      />
                      <p class="text-[9px] text-muted-foreground px-1">{{ t('models.add_cloud_dialog.provider_model_id_desc') }}</p>
                    </div>

                    <div class="space-y-2">
                      <label class="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">{{ t('models.add_cloud_dialog.display_name') }}</label>
                      <Input 
                        v-model="cloudModelForm.name" 
                        :placeholder="t('models.add_cloud_dialog.display_name_placeholder')" 
                        class="h-11 bg-muted/20 border-border/40 focus:ring-1 focus:ring-blue-500 transition-all rounded-xl" 
                      />
                    </div>

                    <div class="space-y-2">
                      <label class="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">{{ t('models.add_cloud_dialog.system_id') }}</label>
                      <Input 
                        v-model="cloudModelForm.id" 
                        :placeholder="t('models.add_cloud_dialog.system_id_example')" 
                        class="h-11 bg-muted/20 border-border/40 font-mono text-xs focus:ring-1 focus:ring-blue-500 transition-all rounded-xl" 
                      />
                    </div>
                  </div>
                </div>

                <!-- Section 3: Connection Settings -->
                <div class="space-y-6">
                  <div class="flex items-center gap-2">
                    <div class="w-1 h-4 bg-amber-500 rounded-full"></div>
                    <label class="text-xs font-black tracking-widest text-foreground uppercase">{{ t('models.add_cloud_dialog.step3') }}</label>
                  </div>

                  <div class="space-y-4">
                    <div class="space-y-2">
                      <label class="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">{{ t('models.config.base_url') }}</label>
                      <Input 
                        v-model="cloudModelForm.base_url" 
                        placeholder="https://api.openai.com/v1" 
                        class="h-11 bg-muted/20 border-border/40 font-mono text-xs focus:ring-1 focus:ring-blue-500 transition-all rounded-xl" 
                      />
                    </div>

                    <div class="space-y-2">
                      <div class="flex items-center justify-between">
                        <label class="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">{{ t('models.add_cloud_dialog.api_key') }}</label>
                        <Badge v-if="!['lmstudio', 'ollama'].includes(cloudModelForm.provider)" variant="outline" class="text-[8px] font-black h-4 px-1 opacity-50">{{ t('models.add_cloud_dialog.required') }}</Badge>
                        <Badge v-else variant="outline" class="text-[8px] font-black h-4 px-1 opacity-50">{{ t('models.add_cloud_dialog.optional') }}</Badge>
                      </div>
                      <Input 
                        v-model="cloudModelForm.api_key" 
                        type="password" 
                        :placeholder="t('models.config.api_key_placeholder')" 
                        class="h-11 bg-muted/20 border-border/40 font-mono text-xs focus:ring-1 focus:ring-blue-500 transition-all rounded-xl" 
                      />
                      <p class="text-[9px] text-muted-foreground px-1 flex items-center gap-1">
                        <Activity class="w-2 h-2" />
                        {{ t('models.add_cloud_dialog.storage_secure') }}
                      </p>
                    </div>

                    <div class="space-y-2 pt-2">
                      <label class="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">{{ t('models.add_cloud_dialog.description') }}</label>
                      <textarea 
                        v-model="cloudModelForm.description"
                        rows="2"
                        :placeholder="t('models.add_cloud_dialog.description_placeholder')"
                        class="w-full p-3 rounded-xl bg-muted/20 border border-border/40 text-sm focus:ring-1 focus:ring-blue-500 focus:outline-none transition-all resize-none"
                      ></textarea>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </ScrollArea>

          <div class="flex-shrink-0 p-6 border-t border-border/50 bg-muted/5 flex items-center justify-between">
            <div class="flex flex-col">
              <span class="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">{{ t('models.add_cloud_dialog.ready_to_connect') }}</span>
              <span class="text-xs font-medium text-foreground">{{ cloudModelForm.provider_model_id || t('models.add_cloud_dialog.waiting_input') }}</span>
            </div>
            <div class="flex items-center gap-3">
              <Button variant="ghost" class="rounded-xl px-6 font-bold" @click="showAddCloudDialog = false">{{ t('models.add_cloud_dialog.cancel') }}</Button>
              <Button 
                class="h-12 px-10 font-black tracking-tight bg-blue-600 hover:bg-blue-700 text-white rounded-xl shadow-lg shadow-blue-500/20 active:scale-95 transition-all" 
                :disabled="addingCloudModel || !cloudModelForm.provider_model_id || (!['lmstudio', 'ollama'].includes(cloudModelForm.provider) && !cloudModelForm.api_key)"
                @click="handleAddCloudModel"
              >
                <Loader2 v-if="addingCloudModel" class="w-4 h-4 mr-2 animate-spin" />
                {{ t('models.add_cloud_dialog.register') }}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
