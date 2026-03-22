<script setup lang="ts">
import { ref, onMounted, onUnmounted, onActivated, onDeactivated, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { 
  WifiOff, 
  Monitor, 
  Sun, 
  Moon, 
  Cpu, 
  BarChart3,
  Save, 
  FolderOpen,
  RefreshCw,
  Check,
  Languages,
  ChevronLeft,
  ChevronRight,
  Sliders,
  Mic,
  ScanSearch,
  Database,
  FileJson,
  Zap,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import { Input } from '@/components/ui/input'
import { 
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { 
  getSystemConfig, 
  updateSystemConfig,
  reloadEngine as reloadEngineApi,
  browseDirectory,
  type SystemConfig 
} from '@/services/api'
import { useSystemMetrics } from '@/composables/useSystemMetrics'

// Settings State
const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const settingsSection = computed(() => route.name as string)
const navCollapsed = ref(false)
const offlineMode = ref(false)
const theme = ref(localStorage.getItem('platform-theme') || (document.documentElement.classList.contains('light') ? 'light' : 'dark'))
const modelLoader = ref('llama.cpp')
const contextWindow = ref([4096])
const gpuLayers = ref(32)
const dataDirectory = ref('~/.local-ai/models/')
const language = ref('en')

// System Monitor State
const { metrics } = useSystemMetrics({ pollInterval: 3000 })
const config = ref<SystemConfig | null>(null)
const engineStatus = ref(t('settings.monitor.status_idle').toUpperCase())
const isSaving = ref(false)
const saveSuccess = ref(false)
const saveError = ref('')
const isEditing = ref(false)
const isInitialLoad = ref(true)

const displayAppName = computed(() => {
  const raw = config.value?.app_name?.trim() || 'OpenVitamin'
  const match = raw.match(/^[A-Za-z0-9._-]+(?:\s+[A-Za-z0-9._-]+)*/)
  return (match?.[0] || raw).trim() || 'OpenVitamin'
})

const fullAppName = computed(() => config.value?.app_name?.trim() || 'OpenVitamin')

let metricsInterval: any = null

const startPolling = () => {
  if (metricsInterval) return
  fetchStatus()
  metricsInterval = setInterval(fetchStatus, 3000)
}

const stopPolling = () => {
  if (metricsInterval) {
    clearInterval(metricsInterval)
    metricsInterval = null
  }
}

const fetchStatus = async (syncSettings = false) => {
  try {
    const c = await getSystemConfig()
    config.value = c
    
    const shouldSync = syncSettings || isInitialLoad.value || !isEditing.value
    
    if (shouldSync && c.settings) {
      if (c.settings.offlineMode !== undefined) offlineMode.value = c.settings.offlineMode
      if (c.settings.theme !== undefined) theme.value = c.settings.theme
      if (c.settings.modelLoader !== undefined) modelLoader.value = c.settings.modelLoader
      if (c.settings.contextWindow !== undefined) contextWindow.value = [c.settings.contextWindow]
      if (c.settings.gpuLayers !== undefined) gpuLayers.value = c.settings.gpuLayers
      if (c.settings.dataDirectory !== undefined) dataDirectory.value = c.settings.dataDirectory
      else if (c.local_model_directory) dataDirectory.value = c.local_model_directory
      if (c.settings.language !== undefined) {
        const loc = c.settings.language === 'zh' || c.settings.language === 'en' ? c.settings.language : 'en'
        language.value = loc
        locale.value = loc
        try { localStorage.setItem('platform-language', loc) } catch (_) {}
      }
    }
    
    if (isInitialLoad.value) {
      isInitialLoad.value = false
    }
  } catch (error) {
    console.error('Failed to fetch system metrics:', error)
  }
}

onMounted(() => {
  startPolling()
})

onActivated(() => {
  startPolling()
})

onDeactivated(() => {
  stopPolling()
})

onUnmounted(() => {
  stopPolling()
})

const handleSave = async (showSuccess = true) => {
  if (showSuccess) isSaving.value = true
  saveError.value = ''
  try {
    await updateSystemConfig({
      offlineMode: offlineMode.value,
      theme: theme.value,
      modelLoader: modelLoader.value,
      contextWindow: contextWindow.value[0],
      gpuLayers: gpuLayers.value,
      dataDirectory: dataDirectory.value,
      language: language.value,
    })
    
    await fetchStatus(true)
    
    if (showSuccess) {
      saveSuccess.value = true
      setTimeout(() => {
        saveSuccess.value = false
      }, 3000)
    }
    isEditing.value = false
  } catch (error) {
    console.error('Failed to save settings:', error)
    saveError.value = error instanceof Error ? error.message : String(error)
  } finally {
    if (showSuccess) isSaving.value = false
  }
}

// 自动保存开关设置
const handleOfflineToggle = (val: boolean) => {
  offlineMode.value = val
  isEditing.value = true
  handleSave(false)
}

const handleThemeChange = (opt: string) => {
  theme.value = opt
  isEditing.value = true
  handleSave(false)
}

const handleLanguageChange = (lang: string) => {
  language.value = lang
  locale.value = lang
  localStorage.setItem('platform-language', lang)
  isEditing.value = true
  handleSave(false)
}

const resetDefaults = () => {
  offlineMode.value = false
  theme.value = 'dark'
  modelLoader.value = 'llama.cpp'
  contextWindow.value = [4096]
  gpuLayers.value = 32
  dataDirectory.value = '~/.local-ai/models/'
  language.value = 'en'
  locale.value = 'en'
  localStorage.setItem('platform-language', 'en')
  isEditing.value = true
}

const reloadEngine = async () => {
  engineStatus.value = t('settings.monitor.status_reloading').toUpperCase() + '...'
  try {
    await reloadEngineApi()
  } catch (error) {
    console.error('Failed to reload engine:', error)
  } finally {
    engineStatus.value = t('settings.monitor.status_idle').toUpperCase()
  }
}

const handleBrowse = async () => {
  try {
    const res = await browseDirectory()
    if (res.path) {
      dataDirectory.value = res.path
      isEditing.value = true
    }
  } catch (error) {
    console.error('Failed to browse directory:', error)
  }
}

// Theme Logic
const applyTheme = (newTheme: string) => {
  const root = window.document.documentElement
  root.classList.remove('light', 'dark')

  if (newTheme === 'system') {
    const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    root.classList.add(systemTheme)
  } else {
    root.classList.add(newTheme)
  }
  
  localStorage.setItem('platform-theme', newTheme)
}

watch(theme, (newTheme) => {
  applyTheme(newTheme)
})
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <!-- Header -->
    <header class="pt-10 pb-6 px-10 flex items-start justify-between shrink-0">
      <div class="space-y-2">
        <h1 class="text-4xl font-bold tracking-tight">General Settings</h1>
        <p class="text-muted-foreground text-lg">{{ t('settings.subtitle') }}</p>
      </div>
      <div class="flex items-center gap-3 pt-2">
        <Button variant="outline" class="h-11 px-6 rounded-xl" @click="resetDefaults">
          {{ t('settings.reset') }}
        </Button>
        <Button 
          class="bg-primary hover:bg-primary/90 text-primary-foreground font-bold h-11 px-6 gap-2 rounded-xl"
          :disabled="isSaving"
          @click="handleSave"
        >
          <component :is="saveSuccess ? Check : Save" class="w-4 h-4" />
          {{ isSaving ? t('settings.saving') : (saveSuccess ? t('settings.saved') : t('settings.save')) }}
        </Button>
      </div>
    </header>

    <div class="flex-1 flex overflow-hidden px-10 pb-10 gap-8">
      <!-- Settings Navigation -->
      <aside
        class="shrink-0 hidden lg:flex flex-col transition-all duration-200"
        :class="navCollapsed ? 'w-16' : 'w-56'"
      >
        <div class="flex items-center justify-between mb-4">
          <div v-if="!navCollapsed" class="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            Settings
          </div>
          <button
            class="h-7 w-7 rounded-lg border border-border/50 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
            @click="navCollapsed = !navCollapsed"
          >
            <ChevronLeft v-if="!navCollapsed" class="w-4 h-4" />
            <ChevronRight v-else class="w-4 h-4" />
          </button>
        </div>
        <div class="space-y-2 flex-1 overflow-y-auto pr-1">
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-general' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/general')"
          >
            <span v-if="!navCollapsed">General</span>
            <span v-else class="flex items-center justify-center">
              <Sliders class="w-4 h-4" />
            </span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-backup' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/backup')"
          >
            <span v-if="!navCollapsed">{{ t('settings.model_backup.nav_database_backup') }}</span>
            <span v-else class="flex items-center justify-center">
              <Database class="w-4 h-4" />
            </span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-model-backup' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/model-backup')"
          >
            <span v-if="!navCollapsed">{{ t('settings.model_backup.nav_model_backup') }}</span>
            <span v-else class="flex items-center justify-center">
              <FileJson class="w-4 h-4" />
            </span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-backend' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/backend')"
          >
            <span v-if="!navCollapsed">Backend</span>
            <span v-else class="flex items-center justify-center">
              <Cpu class="w-4 h-4" />
            </span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-runtime' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/runtime')"
          >
            <span v-if="!navCollapsed">{{ t('settings.runtime.nav') }}</span>
            <span v-else class="flex items-center justify-center">
              <Zap class="w-4 h-4" />
            </span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-object-detection' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/object-detection')"
          >
            <span v-if="!navCollapsed">Object Detection</span>
            <span v-else class="flex items-center justify-center">
              <ScanSearch class="w-4 h-4" />
            </span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-image-generation' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/image-generation')"
          >
            <span v-if="!navCollapsed">{{ t('settings.image_generation.nav') }}</span>
            <span v-else class="flex items-center justify-center">
              <FileJson class="w-4 h-4" />
            </span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-asr' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/asr')"
          >
            <span v-if="!navCollapsed">ASR</span>
            <span v-else class="flex items-center justify-center">
              <Mic class="w-4 h-4" />
            </span>
          </button>
        </div>
      </aside>

      <!-- Main Content Scroll Area -->
      <main class="flex-1 overflow-y-auto custom-scrollbar pr-4">
        <div class="space-y-10">
          <div
            v-if="isEditing"
            class="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100"
          >
            <div class="font-semibold">{{ t('settings.unsaved_changes') }}</div>
            <div class="mt-1">{{ t('settings.unsaved_changes_desc') }}</div>
          </div>
          <div
            v-if="saveError"
            class="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
          >
            <div class="font-semibold">{{ t('settings.save_failed') }}</div>
            <div class="mt-1 break-words">{{ saveError }}</div>
          </div>
          
          <!-- Offline Mode Section -->
          <div class="space-y-4">
            <div class="flex items-center justify-between p-8 rounded-2xl bg-card border border-border shadow-sm">
              <div class="flex items-center gap-6">
                <div class="w-12 h-12 rounded-xl bg-muted flex items-center justify-center border border-border">
                  <WifiOff class="w-5 h-5 text-blue-500" />
                </div>
                <div class="space-y-1">
                  <h3 class="text-xl font-bold">{{ t('settings.offline_mode.title') }}</h3>
                  <p class="text-muted-foreground text-sm">{{ t('settings.offline_mode.description') }}</p>
                </div>
              </div>
              <Switch :checked="offlineMode" @update:checked="handleOfflineToggle" />
            </div>
          </div>

          <!-- Language Section -->
          <section class="space-y-4">
            <h2 class="text-xl font-bold">{{ t('settings.language.title') }}</h2>
            <div class="grid grid-cols-2 gap-4">
              <button 
                v-for="lang in [
                  { id: 'en', label: t('settings.langEn'), sub: 'English' },
                  { id: 'zh', label: t('settings.langZh'), sub: '中文' }
                ]" 
                :key="lang.id"
                @click="handleLanguageChange(lang.id)"
                :class="[
                  'flex items-center gap-4 p-6 rounded-2xl border transition-all text-left',
                  language === lang.id 
                    ? 'bg-accent border-blue-600 shadow-sm' 
                    : 'bg-card border-border hover:bg-accent/50 hover:border-border/80'
                ]"
              >
                <div :class="[
                  'w-12 h-12 rounded-xl flex items-center justify-center border transition-colors',
                  language === lang.id ? 'bg-blue-500/10 border-blue-500/20' : 'bg-muted border-border'
                ]">
                  <Languages :class="[
                    'w-6 h-6',
                    language === lang.id ? 'text-blue-500' : 'text-muted-foreground'
                  ]" />
                </div>
                <div>
                  <div class="font-bold text-lg" :class="language === lang.id ? 'text-foreground' : 'text-muted-foreground'">{{ lang.label }}</div>
                  <div class="text-xs text-muted-foreground">{{ lang.sub }}</div>
                </div>
                <div v-if="language === lang.id" class="ml-auto">
                  <div class="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center">
                    <Check class="w-4 h-4 text-white" />
                  </div>
                </div>
              </button>
            </div>
          </section>

          <!-- Interface Section -->
          <section class="space-y-4">
            <h2 class="text-xl font-bold">{{ t('settings.interface.title') }}</h2>
            <div class="grid grid-cols-3 gap-4">
              <button 
                v-for="opt in ['system', 'light', 'dark']" 
                :key="opt"
                @click="handleThemeChange(opt)"
                :class="[
                  'flex flex-col items-center justify-center gap-3 py-6 px-4 rounded-xl border transition-all font-medium capitalize',
                  theme === opt 
                    ? 'bg-accent border-blue-600 text-accent-foreground shadow-sm' 
                    : 'bg-card border-border text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                ]"
              >
                <component :is="opt === 'system' ? Monitor : (opt === 'light' ? Sun : Moon)" class="w-6 h-6" />
                {{ t(`settings.interface.${opt}`) }}
              </button>
            </div>
          </section>

          <!-- Storage Section -->
          <section class="space-y-4 mt-10">
            <h2 class="text-xl font-bold">{{ t('settings.storage.title') }}</h2>
            <div class="p-8 rounded-2xl bg-card border border-border shadow-sm">
              <div class="space-y-3">
                <label class="text-sm font-medium text-foreground">{{ t('settings.storage.model_dir') }}</label>
                <div class="flex gap-3">
                  <div class="relative flex-1">
                    <FolderOpen class="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <Input 
                      v-model="dataDirectory"
                      placeholder="~/.local-ai/models/"
                      class="pl-12 h-12 bg-background border-border text-foreground rounded-xl"
                      @update:modelValue="isEditing = true"
                    />
                  </div>
                  <Button 
                    variant="outline" 
                    class="h-12 px-6 rounded-xl font-medium"
                    @click="handleBrowse"
                  >
                    {{ t('settings.storage.browse') }}
                  </Button>
                </div>
              </div>
            </div>
          </section>

          <!-- Bottom Spacing -->
          <div class="h-24"></div>
        </div>
      </main>

      <!-- Right Sidebar: System Monitor -->
      <aside class="w-[400px] shrink-0 space-y-4">
        <div class="p-8 rounded-2xl bg-card border border-border shadow-sm space-y-8 h-fit">
          <div class="flex items-center gap-3">
            <BarChart3 class="w-5 h-5 text-blue-500" />
            <h2 class="text-xl font-bold">{{ t('settings.monitor.title') }}</h2>
          </div>

          <!-- Uptime / Version -->
          <div class="grid grid-cols-2 gap-4">
            <div class="space-y-1">
              <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('settings.monitor.uptime') }}</p>
              <p class="text-xl font-medium">{{ metrics?.uptime || '00:00:00' }}</p>
            </div>
            <div class="space-y-1">
              <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('settings.monitor.version') }}</p>
              <p class="text-xl font-medium">v{{ config?.version || '0.1.0' }}</p>
            </div>
          </div>

          <div class="space-y-3 rounded-2xl border border-border bg-background/60 p-4">
            <div class="flex items-start justify-between gap-4">
              <div class="min-w-0">
                <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('settings.monitor.app_name') }}</p>
                <p class="text-lg font-semibold text-foreground truncate">{{ displayAppName }}</p>
                <p v-if="fullAppName !== displayAppName" class="mt-1 text-xs text-muted-foreground break-words">{{ fullAppName }}</p>
              </div>
              <div class="text-right shrink-0">
                <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('settings.monitor.backend_version') }}</p>
                <p class="text-sm font-semibold text-foreground">v{{ config?.version || '0.1.0' }}</p>
              </div>
            </div>
            <div class="flex items-center justify-between gap-4 text-sm">
              <span class="text-muted-foreground">{{ t('settings.monitor.node_version') }}</span>
              <span class="font-medium text-foreground">{{ metrics?.node_version || 'N/A' }}</span>
            </div>
          </div>

          <!-- Hardware -->
          <div class="space-y-6 pt-6 border-t border-border">
            <div class="flex items-start gap-4">
              <div class="w-10 h-10 rounded-xl bg-muted flex items-center justify-center border border-border">
                <Cpu class="w-5 h-5 text-muted-foreground" />
              </div>
              <div class="space-y-1">
                <p class="text-lg font-bold">{{ metrics?.cuda_version === 'MPS (Metal)' ? t('settings.monitor.apple_silicon') : (metrics?.cuda_version?.includes('NVIDIA') ? t('settings.monitor.nvidia_gpu') : (metrics?.cuda_version || 'NVIDIA RTX 4090')) }}</p>
                <p class="text-sm text-muted-foreground">{{ t('settings.monitor.primary_device') }}</p>
              </div>
            </div>

            <!-- VRAM Bar -->
            <div class="space-y-3">
              <div class="flex justify-between items-center text-sm">
                <span class="font-medium text-muted-foreground">{{ t('settings.monitor.vram') }}</span>
                <span class="font-medium text-foreground">{{ metrics?.vram_used || 0 }}GB / {{ metrics?.vram_total || 0 }}GB</span>
              </div>
              <div class="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                <div 
                  class="h-full bg-blue-600 rounded-full transition-all duration-1000"
                  :style="{ width: ((metrics?.vram_used || 0) / (metrics?.vram_total || 1) * 100) + '%' }"
                ></div>
              </div>
            </div>

            <!-- CPU / RAM -->
            <div class="space-y-3">
              <div class="flex justify-between items-center text-sm">
                <span class="font-medium text-muted-foreground">{{ t('settings.monitor.cpu') }}</span>
                <span class="font-medium text-foreground">{{ metrics?.cpu_usage || 0 }}%</span>
              </div>
              <div class="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                <div 
                  class="h-full bg-emerald-600 rounded-full transition-all duration-1000"
                  :style="{ width: (metrics?.cpu_usage || 0) + '%' }"
                ></div>
              </div>
            </div>

            <div class="space-y-3">
              <div class="flex justify-between items-center text-sm">
                <span class="font-medium text-muted-foreground">{{ t('settings.monitor.ram') }}</span>
                <span class="font-medium text-foreground">{{ metrics?.ram_used || 0 }}GB / {{ metrics?.ram_total || 0 }}GB</span>
              </div>
              <div class="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                <div 
                  class="h-full bg-purple-600 rounded-full transition-all duration-1000"
                  :style="{ width: ((metrics?.ram_used || 0) / (metrics?.ram_total || 1) * 100) + '%' }"
                ></div>
              </div>
            </div>

            <!-- Engine Status -->
            <div class="flex items-center justify-between pt-4 border-t border-border">
              <div class="flex items-center gap-3">
                <div class="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
                  <RefreshCw class="w-4 h-4 text-blue-500" />
                </div>
                <div>
                  <p class="text-sm font-bold">{{ t('settings.monitor.engine') }}</p>
                  <p class="text-xs text-muted-foreground">{{ engineStatus }}</p>
                </div>
              </div>
              <Button variant="outline" size="sm" @click="reloadEngine">
                {{ t('settings.monitor.reload') }}
              </Button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>
