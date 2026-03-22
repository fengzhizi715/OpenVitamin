<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { 
  Database, 
  Cpu, 
  Eye, 
  Image as ImageIcon,
  FolderOpen,
  Check,
  AlertCircle,
  Save,
  RotateCcw,
  Braces,
  ChevronUp,
  File
} from 'lucide-vue-next'
import { getModelManifest, updateModelManifest, browseModelDir, getSystemMetrics, type ModelManifest, type BrowseResult, type SystemMetrics } from '@/services/api'

const { t } = useI18n()

const props = defineProps<{
  model: any // ModelAsset
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved'): void
}>()

// UI State
const activeTab = ref<'basic' | 'capabilities' | 'runtime' | 'vlm' | 'image' | 'json'>('basic')
const saving = ref(false)
const saveStatus = ref<'idle' | 'success' | 'error'>('idle')
const lastSaved = ref<string | null>(null)
const jsonText = ref('')
const jsonError = ref<string | null>(null)

// Browse modal state
const browseOpen = ref(false)
const browsePath = ref('')
const browseDirs = ref<string[]>([])
const browseFiles = ref<string[]>([])
const browseParent = ref<string | null>(null)
const browseModelDirPath = ref('')
const browseRelPath = ref('')
const browseLoading = ref(false)
const browseError = ref<string | null>(null)
const browseTarget = ref<'path' | 'mmproj'>('path')

const metrics = ref<SystemMetrics | null>(null)
const loadMetrics = async () => {
  try {
    metrics.value = await getSystemMetrics()
  } catch {
    metrics.value = null
  }
}

// Form Data
const formData = ref<ModelManifest>({
  model_id: '',
  name: '',
  model_type: 'llm',
  runtime: 'llama.cpp',
  format: 'gguf',
  path: '',
  capabilities: [],
  quantization: '',
  description: '',
  metadata: {}
})

// Computed
const isVlmModel = computed(() => formData.value.model_type === 'vlm')
const isImageGenerationModel = computed(() => formData.value.model_type === 'image_generation')
const isValid = computed(() => {
  if (activeTab.value === 'json') {
    try {
      const parsed = JSON.parse(jsonText.value || '{}')
      return !!(parsed.model_id && parsed.name && parsed.path)
    } catch { return false }
  }
  return formData.value.model_id && formData.value.name && formData.value.path
})

const tabs = computed(() => [
  { id: 'basic', label: t('models.editor.nav_basic'), icon: Database },
  { id: 'capabilities', label: t('models.editor.nav_capabilities'), icon: Cpu },
  { id: 'runtime', label: t('models.editor.nav_runtime'), icon: Cpu },
  ...(isVlmModel.value ? [{ id: 'vlm', label: t('models.editor.nav_vlm'), icon: Eye }] : []),
  ...(isImageGenerationModel.value ? [{ id: 'image', label: t('models.editor.nav_image_generation'), icon: ImageIcon }] : [])
])

// Methods
const loadManifest = async () => {
  try {
    const manifest = await getModelManifest(props.model.id)
    if (manifest) {
      formData.value = { ...formData.value, ...manifest }
      // 确保 path 从 metadata 填充（后端可能用 model_path/path）
      const p = formData.value.path || manifest.metadata?.model_path || manifest.metadata?.path || props.model?.metadata?.path || props.model?.metadata?.model_path
      if (p) formData.value.path = p
      // 确保 capabilities 为数组
      if (!Array.isArray(formData.value.capabilities)) {
        formData.value.capabilities = manifest.capabilities ? [...manifest.capabilities] : []
      }
    }
  } catch (error) {
    console.warn('No manifest found, using defaults')
  }
}

const handleSave = async () => {
  if (activeTab.value === 'json') {
    if (!syncFormFromJson()) return
  }
  if (saving.value || !isValid.value) return
  
  saving.value = true
  saveStatus.value = 'idle'
  
  try {
    await updateModelManifest(props.model.id, formData.value)
    saveStatus.value = 'success'
    lastSaved.value = new Date().toLocaleTimeString()
    emit('saved')
    
    setTimeout(() => {
      saveStatus.value = 'idle'
    }, 3000)
  } catch (error) {
    console.error('Save failed:', error)
    saveStatus.value = 'error'
  } finally {
    saving.value = false
  }
}

const syncJsonFromForm = () => {
  try {
    jsonText.value = JSON.stringify(formData.value, null, 2)
    jsonError.value = null
  } catch (e) {
    jsonError.value = e instanceof Error ? e.message : t('models.editor.invalid_json')
  }
}

const syncFormFromJson = (): boolean => {
  try {
    const parsed = JSON.parse(jsonText.value) as ModelManifest
    const merged = { ...formData.value, ...parsed }
    if (!merged.metadata || typeof merged.metadata !== 'object') {
      merged.metadata = { ...formData.value.metadata }
    }
    formData.value = merged
    jsonError.value = null
    return true
  } catch (e) {
    jsonError.value = e instanceof Error ? e.message : t('models.editor.invalid_json')
    return false
  }
}

const handleReset = () => {
  loadManifest()
  if (activeTab.value === 'json') syncJsonFromForm()
}

const toggleCapability = (cap: string, checked: boolean) => {
  const arr = [...(formData.value.capabilities || [])]
  const idx = arr.indexOf(cap)
  if (checked && idx < 0) arr.push(cap)
  else if (!checked && idx >= 0) arr.splice(idx, 1)
  formData.value.capabilities = arr.sort()
}

const removeCapability = (cap: string) => {
  formData.value.capabilities = (formData.value.capabilities || []).filter(c => c !== cap)
}

const openBrowse = async (target: 'path' | 'mmproj' = 'path') => {
  browseTarget.value = target
  browseOpen.value = true
  browseError.value = null
  browseRelPath.value = ''
  await loadBrowse('')
}

const loadBrowse = async (relPath: string) => {
  browseLoading.value = true
  browseError.value = null
  try {
    const res = await browseModelDir(props.model.id, relPath)
    browsePath.value = res.path
    browseDirs.value = res.dirs
    browseFiles.value = res.files
    browseParent.value = res.parent
    browseModelDirPath.value = res.model_dir
    browseRelPath.value = relPath
  } catch (e) {
    browseError.value = e instanceof Error ? e.message : t('models.editor.browse_failed')
  } finally {
    browseLoading.value = false
  }
}

const browseNavigate = (dir: string) => {
  const newRel = browseRelPath.value ? browseRelPath.value + '/' + dir : dir
  loadBrowse(newRel)
}

const browseUp = () => {
  const parts = browseRelPath.value.split('/').filter(Boolean)
  parts.pop()
  loadBrowse(parts.join('/'))
}

const selectPath = (fullPath: string) => {
  if (browseTarget.value === 'mmproj') {
    if (!formData.value.metadata) formData.value.metadata = {}
    formData.value.metadata.mmproj_path = fullPath
  } else {
    formData.value.path = fullPath
  }
  browseOpen.value = false
}

const closeBrowse = () => {
  browseOpen.value = false
}

onMounted(() => {
  loadManifest()
  loadMetrics()
})

watch(activeTab, (tab) => {
  if (tab === 'json') syncJsonFromForm()
})
</script>

<template>
  <div class="h-full flex-1 flex bg-background overflow-hidden min-w-0">
    <!-- Sidebar -->
    <div class="w-64 border-r border-border/30 bg-muted/5 flex flex-col">
      <!-- Header -->
      <div class="p-4 border-b border-border/30">
        <div class="flex items-center gap-3 min-w-0">
          <div class="p-2 bg-primary/10 rounded-lg shrink-0">
            <Database class="w-5 h-5 text-primary" />
          </div>
          <div class="min-w-0">
            <h2 class="text-sm font-bold tracking-tight truncate">{{ model?.name || model?.id || t('models.editor.title') }}</h2>
            <p class="text-xs text-muted-foreground">{{ t('models.editor.model_json') }}</p>
          </div>
        </div>
      </div>

      <!-- Navigation -->
      <nav class="flex-1 p-4 space-y-1">
        <div class="mb-4">
          <h3 class="text-[10px] font-bold tracking-widest text-muted-foreground/60 uppercase mb-2">
            {{ t('models.editor.section_configuration') }}
          </h3>
          <div class="space-y-1">
            <button
              v-for="tab in tabs"
              :key="tab.id"
              @click="activeTab = tab.id as any"
              class="w-full flex items-center gap-3 px-3 py-2.5 text-sm rounded-lg transition-all"
              :class="[
                activeTab === tab.id
                  ? 'bg-blue-500 text-white shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
              ]"
            >
              <component :is="tab.icon" class="w-4 h-4" />
              {{ tab.label }}
            </button>
          </div>
        </div>
        <div class="mt-6">
          <h3 class="text-[10px] font-bold tracking-widest text-muted-foreground/60 uppercase mb-2">
            {{ t('models.editor.section_source_control') }}
          </h3>
          <div class="space-y-1">
            <button
              @click="activeTab = 'json'"
              class="w-full flex items-center gap-3 px-3 py-2.5 text-sm rounded-lg transition-all"
              :class="[
                activeTab === 'json'
                  ? 'bg-blue-500 text-white shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
              ]"
            >
              <Braces class="w-4 h-4" />
              {{ t('models.editor.nav_json') }}
            </button>
          </div>
        </div>
      </nav>

      <!-- Status -->
      <div class="p-4 border-t border-border/30">
        <div class="flex items-center justify-between text-[10px]">
          <span class="font-bold text-muted-foreground/60 uppercase">{{ t('models.editor.vram') }}</span>
          <span class="font-mono text-foreground">{{ metrics ? `${(metrics.vram_used ?? 0).toFixed(1)} / ${(metrics.vram_total ?? 0).toFixed(1)} GB` : '—' }}</span>
        </div>
        <div class="mt-2 h-1.5 w-full bg-muted/40 rounded-full overflow-hidden">
          <div 
            class="h-full bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.3)] transition-all"
            :style="{ width: metrics && metrics.vram_total > 0 ? `${Math.min(100, (metrics.vram_used / metrics.vram_total) * 100)}%` : '0%' }"
          ></div>
        </div>
      </div>
    </div>

    <!-- Main Content -->
    <div class="flex-1 flex flex-col">
      <!-- Tab Content -->
      <ScrollArea class="flex-1">
        <div class="p-8">
          <!-- Basic Info Tab -->
          <div v-if="activeTab === 'basic'">
            <h3 class="text-lg font-black tracking-tight mb-6">{{ t('models.editor.basic_information') }}</h3>
            
            <div class="space-y-6">
              <!-- Model ID -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.model_id') }}
                </label>
                <div class="relative">
                  <Input
                    v-model="formData.model_id"
                    class="h-11 bg-muted/20 border-border/40 font-mono text-sm pr-10"
                    readonly
                  />
                  <div class="absolute right-3 top-1/2 -translate-y-1/2">
                    <div class="w-2 h-2 rounded-full bg-blue-500"></div>
                  </div>
                </div>
              </div>

              <!-- Display Name -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.display_name') }}
                </label>
                <Input
                  v-model="formData.name"
                  class="h-11 bg-muted/20 border-border/40 text-sm"
                  :placeholder="t('models.editor.display_name_placeholder')"
                />
              </div>

              <!-- Model Type -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.model_type') }}
                </label>
                <div class="grid grid-cols-3 gap-2">
                  <button
                    @click="formData.model_type = 'llm'"
                    class="p-4 rounded-lg border transition-all text-left"
                    :class="[
                      formData.model_type === 'llm'
                        ? 'border-blue-500 bg-blue-500/5 text-blue-500'
                        : 'border-border/50 bg-muted/20 hover:bg-muted/40'
                    ]"
                  >
                    <div class="text-xs font-bold">{{ t('models.editor.model_type_llm') }}</div>
                  </button>
                  <button
                    @click="formData.model_type = 'vlm'"
                    class="p-4 rounded-lg border transition-all text-left"
                    :class="[
                      formData.model_type === 'vlm'
                        ? 'border-blue-500 bg-blue-500/5 text-blue-500'
                        : 'border-border/50 bg-muted/20 hover:bg-muted/40'
                    ]"
                  >
                    <div class="text-xs font-bold">{{ t('models.editor.model_type_vlm') }}</div>
                  </button>
                  <button
                    @click="formData.model_type = 'image_generation'"
                    class="p-4 rounded-lg border transition-all text-left"
                    :class="[
                      formData.model_type === 'image_generation'
                        ? 'border-blue-500 bg-blue-500/5 text-blue-500'
                        : 'border-border/50 bg-muted/20 hover:bg-muted/40'
                    ]"
                  >
                    <div class="text-xs font-bold">{{ t('models.editor.model_type_image_generation') }}</div>
                  </button>
                </div>
              </div>

              <!-- Runtime -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.runtime') }}
                </label>
                <select
                  v-model="formData.runtime"
                  class="w-full h-11 bg-muted/20 border border-border/40 rounded-lg px-3 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="llama.cpp">llama.cpp</option>
                  <option value="torch">Torch</option>
                  <option value="mlx">MLX</option>
                  <option value="diffusers">Diffusers</option>
                  <option value="ollama">Ollama</option>
                  <option value="vllm">vLLM</option>
                </select>
              </div>

              <!-- Model Path -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.model_path') }}
                </label>
                <div class="flex gap-2">
                  <div class="relative flex-1">
                    <Input
                      v-model="formData.path"
                      class="h-11 bg-muted/20 border-border/40 text-sm pr-10"
                      :placeholder="t('models.editor.model_path_placeholder')"
                    />
                    <Check class="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-emerald-500" />
                  </div>
                  <Button
                    variant="outline"
                    class="h-11 px-4 border-border/40 hover:bg-muted/20"
                    @click="openBrowse('path')"
                  >
                    <FolderOpen class="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </div>
          </div>

          <!-- Capabilities Tab -->
          <div v-else-if="activeTab === 'capabilities'">
            <h3 class="text-lg font-black tracking-tight mb-6">{{ t('models.editor.capabilities') }}</h3>
            <p class="text-sm text-muted-foreground mb-6">{{ t('models.editor.capabilities_desc') }}</p>
            <div class="space-y-4">
              <div class="flex flex-wrap gap-4">
                <label class="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    :checked="formData.capabilities.includes('chat')"
                    class="rounded border-border/50"
                    @change="(e) => toggleCapability('chat', (e.target as HTMLInputElement).checked)"
                  />
                  <span class="text-sm font-medium">chat</span>
                  <span class="text-xs text-muted-foreground">{{ t('models.editor.capability_chat_desc') }}</span>
                </label>
                <label class="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    :checked="formData.capabilities.includes('vision')"
                    class="rounded border-border/50"
                    @change="(e) => toggleCapability('vision', (e.target as HTMLInputElement).checked)"
                  />
                  <span class="text-sm font-medium">vision</span>
                  <span class="text-xs text-muted-foreground">{{ t('models.editor.capability_vision_desc') }}</span>
                </label>
                <label class="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    :checked="formData.capabilities.includes('embedding')"
                    class="rounded border-border/50"
                    @change="(e) => toggleCapability('embedding', (e.target as HTMLInputElement).checked)"
                  />
                  <span class="text-sm font-medium">embedding</span>
                  <span class="text-xs text-muted-foreground">{{ t('models.editor.capability_embedding_desc') }}</span>
                </label>
                <label class="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    :checked="formData.capabilities.includes('object_detection')"
                    class="rounded border-border/50"
                    @change="(e) => toggleCapability('object_detection', (e.target as HTMLInputElement).checked)"
                  />
                  <span class="text-sm font-medium">object_detection</span>
                  <span class="text-xs text-muted-foreground">{{ t('models.editor.capability_object_detection_desc') }}</span>
                </label>
                <label class="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    :checked="formData.capabilities.includes('text_to_image')"
                    class="rounded border-border/50"
                    @change="(e) => toggleCapability('text_to_image', (e.target as HTMLInputElement).checked)"
                  />
                  <span class="text-sm font-medium">text_to_image</span>
                  <span class="text-xs text-muted-foreground">{{ t('models.editor.capability_text_to_image_desc') }}</span>
                </label>
              </div>
              <div v-if="formData.capabilities.length" class="flex flex-wrap gap-2 mt-4">
                <span
                  v-for="cap in formData.capabilities"
                  :key="cap"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-primary/10 text-primary text-xs font-medium"
                >
                  {{ cap }}
                  <button type="button" class="hover:text-destructive" @click="removeCapability(cap)">×</button>
                </span>
              </div>
            </div>
          </div>

          <!-- Runtime Tab -->
          <div v-else-if="activeTab === 'runtime'">
            <h3 class="text-lg font-black tracking-tight mb-6">{{ t('models.editor.runtime_title', { runtime: formData.runtime }) }}</h3>
            
            <div class="space-y-6">
              <!-- Context Length -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.context_length') }}
                </label>
                <Input
                  v-model.number="formData.metadata.n_ctx"
                  type="number"
                  class="h-11 bg-muted/20 border-border/40 text-sm"
                  placeholder="8192"
                />
                <p class="text-xs text-muted-foreground">{{ t('models.editor.context_length_desc') }}</p>
              </div>

              <!-- GPU Layers -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.gpu_layers') }}
                </label>
                <Input
                  v-model.number="formData.metadata.n_gpu_layers"
                  type="number"
                  class="h-11 bg-muted/20 border-border/40 text-sm"
                  placeholder="32"
                />
                <p class="text-xs text-muted-foreground">{{ t('models.editor.gpu_layers_desc') }}</p>
              </div>

              <!-- Threads -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.threads') }}
                </label>
                <Input
                  v-model.number="formData.metadata.n_threads"
                  type="number"
                  class="h-11 bg-muted/20 border-border/40 text-sm"
                  placeholder="8"
                />
                <p class="text-xs text-muted-foreground">{{ t('models.editor.threads_desc') }}</p>
              </div>
            </div>
          </div>

          <!-- VLM Config Tab -->
          <div v-else-if="activeTab === 'vlm'">
            <h3 class="text-lg font-black tracking-tight mb-6">{{ t('models.editor.vlm_configuration') }}</h3>
            
            <div class="space-y-6">
              <!-- VLM Family -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.vlm_family') }}
                </label>
                <select
                  v-model="formData.metadata.vlm_family"
                  class="w-full h-11 bg-muted/20 border border-border/40 rounded-lg px-3 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="llava-1.5">llava-1.5</option>
                  <option value="llava-1.6">llava-1.6</option>
                  <option value="bakllava">bakllava</option>
                </select>
              </div>

              <!-- Projector Status -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.projector_status') }}
                </label>
                <div class="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-lg flex items-center justify-between">
                  <div class="flex items-center gap-2">
                    <Check class="w-4 h-4 text-emerald-500" />
                    <span class="text-sm">{{ t('models.editor.projector_found') }}</span>
                  </div>
                  <div class="px-2 py-1 bg-blue-500/20 text-blue-500 text-xs font-bold rounded-full">
                    {{ t('models.editor.multimodal_active') }}
                  </div>
                </div>
              </div>

              <!-- Projector Path -->
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.projector_path') }}
                </label>
                <div class="flex gap-2">
                  <Input
                    v-model="formData.metadata.mmproj_path"
                    class="h-11 bg-muted/20 border-border/40 text-sm flex-1"
                    :placeholder="t('models.editor.projector_path_placeholder')"
                  />
                  <Button
                    variant="outline"
                    class="h-11 px-4 border-border/40 hover:bg-muted/20"
                    @click="openBrowse('mmproj')"
                  >
                    <FolderOpen class="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </div>
          </div>

          <!-- Image Generation Config Tab -->
          <div v-else-if="activeTab === 'image'">
            <h3 class="text-lg font-black tracking-tight mb-6">{{ t('models.editor.image_generation_configuration') }}</h3>

            <div class="space-y-6">
              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.pipeline') }}
                </label>
                <Input
                  v-model="formData.metadata.pipeline"
                  class="h-11 bg-muted/20 border-border/40 text-sm"
                  :placeholder="t('models.editor.pipeline_placeholder')"
                />
              </div>

              <div class="grid grid-cols-2 gap-4">
                <div class="space-y-2">
                  <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                    {{ t('models.editor.default_width') }}
                  </label>
                  <Input
                    v-model.number="formData.metadata.default_width"
                    type="number"
                    class="h-11 bg-muted/20 border-border/40 text-sm"
                    placeholder="1024"
                  />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                    {{ t('models.editor.default_height') }}
                  </label>
                  <Input
                    v-model.number="formData.metadata.default_height"
                    type="number"
                    class="h-11 bg-muted/20 border-border/40 text-sm"
                    placeholder="1024"
                  />
                </div>
              </div>

              <div class="grid grid-cols-2 gap-4">
                <div class="space-y-2">
                  <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                    {{ t('models.editor.default_steps') }}
                  </label>
                  <Input
                    v-model.number="formData.metadata.default_num_inference_steps"
                    type="number"
                    class="h-11 bg-muted/20 border-border/40 text-sm"
                    placeholder="20"
                  />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                    {{ t('models.editor.guidance_scale') }}
                  </label>
                  <Input
                    v-model.number="formData.metadata.default_guidance_scale"
                    type="number"
                    step="0.1"
                    class="h-11 bg-muted/20 border-border/40 text-sm"
                    placeholder="4.0"
                  />
                </div>
              </div>

              <div class="space-y-2">
                <label class="text-xs font-bold tracking-widest text-muted-foreground uppercase">
                  {{ t('models.editor.scheduler') }}
                </label>
                <Input
                  v-model="formData.metadata.scheduler"
                  class="h-11 bg-muted/20 border-border/40 text-sm"
                  :placeholder="t('models.editor.scheduler_placeholder')"
                />
              </div>

              <label class="flex items-center gap-3 cursor-pointer">
                <input
                  v-model="formData.metadata.negative_prompt_supported"
                  type="checkbox"
                  class="rounded border-border/50"
                />
                <span class="text-sm font-medium">negative_prompt_supported</span>
                <span class="text-xs text-muted-foreground">{{ t('models.editor.negative_prompt_supported_desc') }}</span>
              </label>
            </div>
          </div>

          <!-- {{ t('models.editor.nav_json') }} Tab -->
          <div v-else-if="activeTab === 'json'">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-lg font-black tracking-tight">{{ t('models.editor.synchronized_model_json') }}</h3>
              <button
                type="button"
                class="text-xs text-primary hover:underline"
                @click="syncJsonFromForm"
              >
                {{ t('models.editor.format_document') }}
              </button>
            </div>
            <div class="space-y-2">
              <textarea
                v-model="jsonText"
                class="w-full min-h-[calc(100vh-240px)] p-4 font-mono text-sm bg-muted/20 border border-border/40 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
                spellcheck="false"
                placeholder="{}"
              />
              <p v-if="jsonError" class="text-xs text-destructive">{{ jsonError }}</p>
            </div>
          </div>
        </div>
      </ScrollArea>

      <!-- Footer -->
      <div class="p-6 border-t border-border/30 bg-muted/5">
        <div class="flex items-center justify-between">
          <!-- Validation Status -->
          <div class="flex items-center gap-2">
            <div class="flex items-center gap-2">
              <Check 
                v-if="isValid" 
                class="w-4 h-4 text-emerald-500" 
              />
              <AlertCircle 
                v-else 
                class="w-4 h-4 text-amber-500" 
              />
              <span 
                class="text-sm font-bold"
                :class="isValid ? 'text-emerald-500' : 'text-amber-500'"
              >
                {{ isValid ? t('models.editor.config_valid') : t('models.editor.config_invalid') }}
              </span>
            </div>
            <span v-if="lastSaved" class="text-xs text-muted-foreground">
              {{ t('models.editor.last_saved', { time: lastSaved }) }}
            </span>
          </div>

          <!-- Action Buttons -->
          <div class="flex items-center gap-3">
            <Button
              variant="ghost"
              class="h-9 px-4 font-bold text-muted-foreground hover:text-foreground"
              @click="handleReset"
            >
              <RotateCcw class="w-4 h-4 mr-2" />
              {{ t('models.editor.reset') }}
            </Button>
            <Button
              class="h-9 px-6 font-bold bg-blue-600 hover:bg-blue-700 text-white"
              :disabled="saving || !isValid"
              @click="handleSave"
            >
              <Save v-if="!saving" class="w-4 h-4 mr-2" />
              <div v-else class="flex items-center gap-2">
                <div class="w-2 h-2 rounded-full bg-current animate-pulse"></div>
                {{ t('models.editor.saving') }}
              </div>
              {{ t('models.editor.save_changes') }}
            </Button>
          </div>
        </div>
      </div>
    </div>

  </div>

    <!-- Browse Path Modal -->
    <Teleport to="body">
      <div v-if="browseOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="closeBrowse">
        <div class="bg-background border border-border rounded-xl shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col m-4" @click.stop>
          <div class="p-4 border-b border-border flex items-center justify-between shrink-0">
            <h3 class="font-semibold">{{ browseTarget === 'mmproj' ? t('models.editor.select_projector_path') : t('models.editor.select_model_path') }}</h3>
            <Button variant="ghost" size="icon" @click="closeBrowse">×</Button>
          </div>
          <div class="p-4 border-b border-border/50 text-sm text-muted-foreground truncate shrink-0">
            {{ browsePath || (browseLoading ? t('models.editor.loading') : '') }}
          </div>
          <div v-if="browseError" class="px-4 py-2 text-destructive text-sm">{{ browseError }}</div>
          <div class="flex-1 overflow-auto p-4 space-y-4 min-h-0">
            <div v-if="browseLoading" class="flex items-center justify-center py-12 text-muted-foreground">{{ t('models.editor.loading') }}</div>
            <template v-else>
              <div v-if="browseParent !== null" class="flex items-center gap-2 cursor-pointer hover:bg-muted/50 rounded-lg p-2" @click="browseUp">
                <ChevronUp class="w-4 h-4" />
                <span>..</span>
              </div>
              <div v-if="browseDirs.length" class="space-y-1">
                <div
                  v-for="d in browseDirs"
                  :key="'dir-' + d"
                  class="flex items-center gap-2 cursor-pointer hover:bg-muted/50 rounded-lg p-2"
                  @click="browseNavigate(d)"
                >
                  <FolderOpen class="w-4 h-4 text-amber-500" />
                  <span>{{ d }}/</span>
                </div>
              </div>
              <div v-if="browseFiles.length" class="space-y-1">
                <div
                  v-for="f in browseFiles"
                  :key="'file-' + f"
                  class="flex items-center gap-2 cursor-pointer hover:bg-muted/50 rounded-lg p-2"
                  @click="selectPath(browsePath + '/' + f)"
                >
                  <File class="w-4 h-4 text-muted-foreground" />
                  <span>{{ f }}</span>
                </div>
              </div>
              <div v-if="!browseLoading && !browseDirs.length && !browseFiles.length" class="text-muted-foreground text-sm py-4">{{ t('models.editor.empty_directory') }}</div>
            </template>
          </div>
        </div>
      </div>
    </Teleport>
</template>
