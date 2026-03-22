<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Slider } from '@/components/ui/slider'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { X, Activity, Layers, Settings2, ChevronRight, Monitor, Zap, Check, AlertCircle, Globe, Archive } from 'lucide-vue-next'
import { getSystemMetrics, updateModel, createModelBackup } from '@/services/api'

const { t } = useI18n()

const props = withDefaults(
  defineProps<{
    model: any // ModelAsset
    standalone?: boolean
  }>(),
  { standalone: false }
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update'): void
}>()

// UI State
const saving = ref(false)
const saveStatus = ref<'idle' | 'success' | 'error'>('idle')
const showMetadata = ref(false)
const backupLoading = ref(false)

// Default config state
const config = ref({
  displayName: '',
  providerModelId: '',
  contextWindow: [4096],
  temperature: [0.7],
  gpuLayers: 0,
  topP: [0.90],
  systemPrompt: '',
  baseUrl: '',
  apiKey: ''
})

// Telemetry data（推理速度来自 /api/system/metrics 的 inference_speed，无则显示 —）
const telemetry = ref({
  speed: '—',
  vramUsed: 0,
  vramTotal: 0,
  contextUsed: 0,
  contextTotal: props.model?.context_length || 4096,
  latency: '0ms'
})

const handleSave = async () => {
  if (saving.value) return
  
  saving.value = true
  saveStatus.value = 'idle'
  
  try {
    const data: any = {
      context_length: config.value.contextWindow[0],
      description: config.value.systemPrompt,
      base_url: config.value.baseUrl || undefined,
      metadata: {
        ...(props.model.metadata || {}),
        n_gpu_layers: config.value.gpuLayers,
        temperature: config.value.temperature[0],
        top_p: config.value.topP[0],
        api_key: config.value.apiKey || undefined
      }
    }
    
    // 对于云端模型和外部运行时（ollama/lmstudio），允许更新 name 和 provider_model_id
    const isCloudModel = ['openai', 'gemini', 'deepseek', 'kimi', 'ollama', 'lmstudio'].includes(props.model.backend)
    if (isCloudModel) {
      if (config.value.displayName) {
        data.name = config.value.displayName
      }
      if (config.value.providerModelId) {
        data.provider_model_id = config.value.providerModelId
      }
    }
    
    await updateModel(props.model.id, data)
    saveStatus.value = 'success'
    emit('update')
    
    setTimeout(() => {
      saveStatus.value = 'idle'
    }, 3000)
  } catch (error) {
    console.error('Update failed:', error)
    saveStatus.value = 'error'
  } finally {
    saving.value = false
  }
}

const isLocalModel = computed(() => ['local', 'llama.cpp'].includes(props.model?.backend || ''))

const handleBackupModelJson = async () => {
  if (!props.model?.id || backupLoading.value) return
  try {
    backupLoading.value = true
    const result = await createModelBackup(props.model.id)
    if (result.success) {
      saveStatus.value = 'success'
      setTimeout(() => { saveStatus.value = 'idle' }, 2000)
    } else {
      saveStatus.value = 'error'
    }
  } catch (e) {
    console.error('Backup failed', e)
    saveStatus.value = 'error'
  } finally {
    backupLoading.value = false
  }
}

let metricsInterval: any = null
// ... existing onMounted ...

const updateMetrics = async () => {
  try {
    const metrics = await getSystemMetrics()
    telemetry.value.vramUsed = metrics.vram_used
    telemetry.value.vramTotal = metrics.vram_total
    const speed = metrics.inference_speed
    telemetry.value.speed =
      speed != null && typeof speed === 'number' && speed >= 0
        ? `${speed.toFixed(1)} t/s`
        : '—'
  } catch (error) {
    console.error('Failed to fetch metrics:', error)
  }
}

onMounted(() => {
  updateMetrics()
  // 每 3 秒更新一次
  metricsInterval = setInterval(updateMetrics, 3000)
  
  // 初始化配置
  if (props.model) {
    config.value.displayName = props.model.name || ''
    config.value.providerModelId = props.model.provider_model_id || ''
    config.value.contextWindow = [props.model.context_length || 4096]
    config.value.systemPrompt = props.model.description || ''
    config.value.gpuLayers = props.model.metadata?.n_gpu_layers || 0
    config.value.baseUrl = props.model.base_url || ''
    config.value.apiKey = props.model.metadata?.api_key || ''
    config.value.temperature = [props.model.metadata?.temperature || 0.7]
    config.value.topP = [props.model.metadata?.top_p || 0.9]
  }
})

onUnmounted(() => {
  if (metricsInterval) clearInterval(metricsInterval)
})
</script>

<template>
  <div
    class="h-full flex flex-col bg-background overflow-hidden"
    :class="standalone ? 'w-full max-w-2xl mx-auto' : 'border-l border-border/50 shadow-2xl w-[400px]'"
  >
    <!-- Header -->
    <div class="p-6 border-b border-border/30 flex items-start justify-between">
      <div class="space-y-1.5">
        <h2 class="text-xl font-bold tracking-tight text-foreground">{{ model.name }}</h2>
        <div class="flex items-center gap-1.5 text-xs text-emerald-500 font-medium">
          <div class="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]"></div>
          {{ t('models.config.active_runtime', { backend: model.backend || t('models.provider_labels.ollama') }) }}
        </div>
      </div>
      <Button variant="ghost" size="icon" class="h-8 w-8 -mt-1 -mr-1 text-muted-foreground hover:text-foreground hover:bg-muted/50" @click="emit('close')">
        <X class="w-4 h-4" />
      </Button>
    </div>

    <ScrollArea class="flex-1">
      <div class="p-6 space-y-8 pb-10">
        <!-- Runtime Telemetry -->
        <section class="space-y-4">
          <div class="flex items-center justify-between">
            <h3 class="text-[10px] font-bold tracking-[0.2em] text-muted-foreground/60 uppercase">{{ t('models.config.telemetry') }}</h3>
            <Badge variant="outline" class="text-[10px] font-mono border-primary/20 bg-primary/5 text-primary">
              {{ telemetry.speed }}
            </Badge>
          </div>
          
          <div class="space-y-4">
            <!-- VRAM Bar -->
            <div class="space-y-2">
              <div class="flex items-center justify-between text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
                <span>{{ t('models.config.vram_utilization') }}</span>
                <span class="font-mono text-foreground">{{ telemetry.vramUsed }} <span class="text-muted-foreground/50">/</span> {{ telemetry.vramTotal }} GB</span>
              </div>
              <div class="h-1.5 w-full bg-muted/40 rounded-full overflow-hidden">
                <div 
                  class="h-full bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.3)]" 
                  :style="{ width: (telemetry.vramUsed / telemetry.vramTotal * 100) + '%' }"
                ></div>
              </div>
            </div>

            <!-- Context & Latency Grid -->
            <div class="grid grid-cols-2 gap-3">
              <div class="bg-muted/30 border border-border/20 rounded-xl p-4 space-y-1.5">
                <span class="text-[10px] font-bold tracking-widest text-muted-foreground/50 uppercase">{{ t('models.config.context') }}</span>
                <div class="text-lg font-bold tracking-tight">
                  {{ telemetry.contextUsed }}<span class="text-xs text-muted-foreground/40 font-medium">/{{ telemetry.contextTotal / 1000 }}k</span>
                </div>
              </div>
              <div class="bg-muted/30 border border-border/20 rounded-xl p-4 space-y-1.5">
                <span class="text-[10px] font-bold tracking-widest text-muted-foreground/50 uppercase">{{ t('models.config.latency') }}</span>
                <div class="text-lg font-bold tracking-tight">{{ telemetry.latency }}</div>
              </div>
            </div>
          </div>
        </section>

        <Separator class="bg-border/30" />

        <!-- Runtime Configuration -->
        <section class="space-y-6">
          <h3 class="text-[10px] font-bold tracking-[0.2em] text-primary uppercase">{{ t('models.config.runtime_config') }}</h3>
          
          <!-- Context Window -->
          <div class="space-y-4">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <Activity class="w-4 h-4 text-muted-foreground/60" />
                <span class="text-xs font-bold tracking-wide text-foreground/80 uppercase">{{ t('models.config.context_window') }}</span>
              </div>
              <Badge variant="secondary" class="h-5 px-1.5 text-[10px] font-mono bg-muted/50 border-none">{{ config.contextWindow[0] ?? 0 }}</Badge>
            </div>
            <Slider 
              v-model="config.contextWindow" 
              :max="32768" 
              :step="512" 
              class="[&_[role=slider]]:bg-primary [&_[role=slider]]:border-primary"
            />
          </div>

          <!-- Temperature -->
          <div class="space-y-4">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <Zap class="w-4 h-4 text-muted-foreground/60" />
                <span class="text-xs font-bold tracking-wide text-foreground/80 uppercase">{{ t('models.config.temperature') }}</span>
              </div>
              <Badge variant="secondary" class="h-5 px-1.5 text-[10px] font-mono bg-muted/50 border-none">{{ (config.temperature[0] ?? 0.7).toFixed(2) }}</Badge>
            </div>
            <Slider 
              v-model="config.temperature" 
              :max="1" 
              :step="0.01"
              class="[&_[role=slider]]:bg-primary"
            />
          </div>

          <!-- GPU Layers (Only for local runtimes like llama.cpp/local) -->
          <div v-if="['local', 'llama.cpp'].includes(model.backend)" class="space-y-4">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <Layers class="w-4 h-4 text-muted-foreground/60" />
                <span class="text-xs font-bold tracking-wide text-foreground/80 uppercase">{{ t('models.config.gpu_layers') }}</span>
              </div>
              <div class="flex items-center border border-border/50 rounded-lg bg-muted/30 h-7">
                <button class="px-2 text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-l-lg transition-colors border-r border-border/30 h-full" @click="config.gpuLayers > 0 && config.gpuLayers--">-</button>
                <span class="px-3 text-xs font-mono font-bold">{{ config.gpuLayers }}</span>
                <button class="px-2 text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-r-lg transition-colors border-l border-border/30 h-full" @click="config.gpuLayers++">+</button>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              class="w-full h-9 gap-2 text-xs"
              :disabled="backupLoading"
              @click="handleBackupModelJson"
            >
              <Archive class="w-3.5 h-3.5" />
              {{ backupLoading ? t('models.config.loading_short') : t('settings.model_backup.backup_btn_in_model') }}
            </Button>
          </div>

          <!-- Sampler Params -->
          <div class="space-y-4">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <Settings2 class="w-4 h-4 text-muted-foreground/60" />
                <span class="text-xs font-bold tracking-wide text-foreground/80 uppercase text-muted-foreground/70">{{ t('models.config.sampler_params') }}</span>
              </div>
              <Badge variant="secondary" class="h-5 px-1.5 text-[10px] font-mono bg-muted/50 border-none">{{ (config.topP[0] ?? 0.9).toFixed(2) }}</Badge>
            </div>
            <Slider 
              v-model="config.topP" 
              :max="1" 
              :step="0.01"
              class="[&_[role=slider]]:bg-primary"
            />
          </div>

          <!-- System Prompt / Description -->
          <div class="space-y-3">
            <div class="flex items-center gap-2">
              <Monitor class="w-4 h-4 text-muted-foreground/60" />
              <span class="text-xs font-bold tracking-wide text-foreground/80 uppercase text-muted-foreground/70">{{ t('models.config.system_prompt') }}</span>
            </div>
            <Textarea 
              v-model="config.systemPrompt" 
              class="min-h-[120px] bg-muted/20 border-border/30 focus-visible:ring-primary/30 text-xs leading-relaxed resize-none p-4 rounded-xl"
              :placeholder="t('models.config.system_prompt_placeholder')"
            />
          </div>

          <!-- Cloud/API Specific Config (Only for Cloud API models and external runtimes) -->
          <div v-if="['openai', 'gemini', 'deepseek', 'kimi', 'ollama', 'lmstudio'].includes(model.backend)" class="space-y-4 pt-4 border-t border-border/20">
            <div class="space-y-3">
              <div class="flex items-center gap-2">
                <Monitor class="w-4 h-4 text-muted-foreground/60" />
                <span class="text-xs font-bold tracking-wide text-foreground/80 uppercase text-muted-foreground/70">{{ t('models.config.display_name') }}</span>
              </div>
              <Input 
                v-model="config.displayName" 
                class="bg-muted/20 border-border/30 text-xs h-9 px-3 rounded-lg"
                :placeholder="t('models.config.display_name_placeholder')"
              />
            </div>
            
            <div class="space-y-3">
              <div class="flex items-center gap-2">
                <Activity class="w-4 h-4 text-muted-foreground/60" />
                <span class="text-xs font-bold tracking-wide text-foreground/80 uppercase text-muted-foreground/70">{{ t('models.config.provider_model_id') }}</span>
              </div>
              <Input 
                v-model="config.providerModelId" 
                class="bg-muted/20 border-border/30 text-xs font-mono h-9 px-3 rounded-lg"
                :placeholder="t('models.config.provider_model_id_example')"
              />
            </div>
            
            <div class="space-y-3">
              <div class="flex items-center gap-2">
                <Globe class="w-4 h-4 text-muted-foreground/60" />
                <span class="text-xs font-bold tracking-wide text-foreground/80 uppercase text-muted-foreground/70">{{ t('models.config.base_url') }}</span>
              </div>
              <Input 
                v-model="config.baseUrl" 
                class="bg-muted/20 border-border/30 text-xs font-mono h-9 px-3 rounded-lg"
                :placeholder="t('models.config.base_url_placeholder')"
              />
            </div>
            
            <div class="space-y-3">
              <div class="flex items-center gap-2">
                <Zap class="w-4 h-4 text-muted-foreground/60" />
                <span class="text-xs font-bold tracking-wide text-foreground/80 uppercase text-muted-foreground/70">{{ t('models.config.api_key') }}</span>
              </div>
              <Input 
                v-model="config.apiKey" 
                type="password"
                class="bg-muted/20 border-border/30 text-xs font-mono h-9 px-3 rounded-lg"
                :placeholder="t('models.config.api_key_placeholder')"
              />
            </div>
          </div>
        </section>

        <!-- Update Action -->
        <div class="space-y-3">
          <Button 
            class="w-full h-12 font-bold tracking-wide transition-all"
            :class="[
              saveStatus === 'success' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-blue-600 hover:bg-blue-700',
              { 'opacity-80 cursor-not-allowed': saving }
            ]"
            :disabled="saving"
            @click="handleSave"
          >
            <div v-if="saving" class="flex items-center gap-2">
              <Zap class="w-4 h-4 animate-spin" />
              {{ t('models.config.saving') }}
            </div>
            <div v-else-if="saveStatus === 'success'" class="flex items-center gap-2">
              <Check class="w-4 h-4" />
              {{ t('models.config.success') }}
            </div>
            <div v-else-if="saveStatus === 'error'" class="flex items-center gap-2">
              <AlertCircle class="w-4 h-4" />
              {{ t('models.config.error') }}
            </div>
            <span v-else>{{ t('models.config.save') }}</span>
          </Button>
          
          <p v-if="saveStatus === 'success'" class="text-[10px] text-center text-emerald-500 font-bold tracking-wider animate-in fade-in duration-500">
            {{ t('models.config.success_msg') }}
          </p>
        </div>
      </div>
    </ScrollArea>

    <!-- Footer link -->
    <div class="p-4 border-t border-border/30 bg-muted/10">
      <button 
        class="flex items-center justify-between w-full text-[10px] font-bold tracking-widest text-muted-foreground/60 uppercase hover:text-foreground transition-colors group"
        @click="showMetadata = !showMetadata"
      >
        <span>{{ t('models.config.metadata') }}</span>
        <ChevronRight class="w-3 h-3 transition-transform" :class="{ 'rotate-90': showMetadata }" />
      </button>
      
      <div v-if="showMetadata" class="mt-4 animate-in slide-in-from-bottom-2 duration-300">
        <pre class="p-4 bg-black/40 rounded-xl text-[10px] font-mono text-muted-foreground overflow-auto max-h-[300px] border border-white/5">{{ JSON.stringify(model, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>
