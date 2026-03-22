<script setup lang="ts">
import { ref, onMounted, onUnmounted, onActivated, onDeactivated, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Save, Check, ChevronLeft, ChevronRight, Sliders, Cpu, ScanSearch, Mic, Database, FileJson, Zap } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
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
  listModels,
  type SystemConfig,
} from '@/services/api'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const settingsSection = computed(() => route.name as string)
const navCollapsed = ref(false)

const defaultModelId = ref('__auto__')
const imageModels = ref<Array<{ id: string; name: string }>>([])
const config = ref<SystemConfig | null>(null)
const isSaving = ref(false)
const saveSuccess = ref(false)
const saveError = ref('')
const isEditing = ref(false)
const isInitialLoad = ref(true)

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

const loadModels = async () => {
  try {
    const res = await listModels()
    const data = Array.isArray(res?.data) ? res.data.filter((m: any) => (m.model_type || '').toLowerCase() === 'image_generation') : []
    imageModels.value = data.map((m: any) => ({ id: m.id, name: m.name || m.id }))
  } catch (error) {
    console.error('Failed to load image generation models:', error)
    imageModels.value = []
  }
}

const fetchStatus = async (syncSettings = false) => {
  try {
    const c = await getSystemConfig()
    config.value = c
    const shouldSync = syncSettings || isInitialLoad.value || !isEditing.value
    if (shouldSync && c.settings) {
      const stored = c.settings.imageGenerationDefaultModelId
      defaultModelId.value = typeof stored === 'string' && stored.trim() ? stored : '__auto__'
    }
    if (isInitialLoad.value) {
      isInitialLoad.value = false
    }
  } catch (error) {
    console.error('Failed to fetch system config:', error)
  }
}

onMounted(async () => {
  await loadModels()
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

const handleSave = async () => {
  isSaving.value = true
  saveError.value = ''
  try {
    await updateSystemConfig({
      imageGenerationDefaultModelId: defaultModelId.value === '__auto__' ? '' : defaultModelId.value,
    })
    await fetchStatus(true)
    saveSuccess.value = true
    setTimeout(() => {
      saveSuccess.value = false
    }, 3000)
    isEditing.value = false
  } catch (error) {
    console.error('Failed to save settings:', error)
    saveError.value = error instanceof Error ? error.message : String(error)
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <header class="pt-10 pb-6 px-10 flex items-start justify-between shrink-0">
      <div class="space-y-2">
        <h1 class="text-4xl font-bold tracking-tight">{{ t('settings.image_generation.title') }}</h1>
        <p class="text-muted-foreground text-lg">{{ t('settings.subtitle') }}</p>
      </div>
      <div class="flex items-center gap-3 pt-2">
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
      <aside class="shrink-0 hidden lg:flex flex-col transition-all duration-200" :class="navCollapsed ? 'w-16' : 'w-56'">
        <div class="flex items-center justify-between mb-4">
          <div v-if="!navCollapsed" class="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">{{ t('settings.title') }}</div>
          <button
            class="h-7 w-7 rounded-lg border border-border/50 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
            @click="navCollapsed = !navCollapsed"
          >
            <ChevronLeft v-if="!navCollapsed" class="w-4 h-4" />
            <ChevronRight v-else class="w-4 h-4" />
          </button>
        </div>
        <div class="space-y-2 flex-1 overflow-y-auto pr-1">
          <button class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors" :class="settingsSection === 'settings-general' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'" @click="router.push('/settings/general')">
            <span v-if="!navCollapsed">{{ t('settings.general_nav') }}</span>
            <span v-else class="flex items-center justify-center"><Sliders class="w-4 h-4" /></span>
          </button>
          <button class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors" :class="settingsSection === 'settings-backup' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'" @click="router.push('/settings/backup')">
            <span v-if="!navCollapsed">{{ t('settings.model_backup.nav_database_backup') }}</span>
            <span v-else class="flex items-center justify-center"><Database class="w-4 h-4" /></span>
          </button>
          <button class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors" :class="settingsSection === 'settings-model-backup' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'" @click="router.push('/settings/model-backup')">
            <span v-if="!navCollapsed">{{ t('settings.model_backup.nav_model_backup') }}</span>
            <span v-else class="flex items-center justify-center"><FileJson class="w-4 h-4" /></span>
          </button>
          <button class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors" :class="settingsSection === 'settings-backend' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'" @click="router.push('/settings/backend')">
            <span v-if="!navCollapsed">{{ t('settings.backend_nav') }}</span>
            <span v-else class="flex items-center justify-center"><Cpu class="w-4 h-4" /></span>
          </button>
          <button class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors" :class="settingsSection === 'settings-runtime' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'" @click="router.push('/settings/runtime')">
            <span v-if="!navCollapsed">{{ t('settings.runtime.nav') }}</span>
            <span v-else class="flex items-center justify-center"><Zap class="w-4 h-4" /></span>
          </button>
          <button class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors" :class="settingsSection === 'settings-object-detection' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'" @click="router.push('/settings/object-detection')">
            <span v-if="!navCollapsed">{{ t('settings.object_detection_nav') }}</span>
            <span v-else class="flex items-center justify-center"><ScanSearch class="w-4 h-4" /></span>
          </button>
          <button class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors" :class="settingsSection === 'settings-image-generation' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'" @click="router.push('/settings/image-generation')">
            <span v-if="!navCollapsed">{{ t('settings.image_generation.nav') }}</span>
            <span v-else class="flex items-center justify-center"><FileJson class="w-4 h-4" /></span>
          </button>
          <button class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors" :class="settingsSection === 'settings-asr' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'" @click="router.push('/settings/asr')">
            <span v-if="!navCollapsed">{{ t('settings.asr_nav') }}</span>
            <span v-else class="flex items-center justify-center"><Mic class="w-4 h-4" /></span>
          </button>
        </div>
      </aside>

      <div class="flex-1 overflow-y-auto custom-scrollbar pr-4">
        <div class="space-y-10">
          <div v-if="isEditing" class="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
            <div class="font-semibold">{{ t('settings.unsaved_changes') }}</div>
            <div class="mt-1">{{ t('settings.unsaved_changes_desc') }}</div>
          </div>
          <div v-if="saveError" class="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            <div class="font-semibold">{{ t('settings.save_failed') }}</div>
            <div class="mt-1 break-words">{{ saveError }}</div>
          </div>

          <section class="space-y-4 mb-10">
            <h2 class="text-xl font-bold">{{ t('settings.image_generation.title') }}</h2>
            <div class="p-8 rounded-2xl bg-card border border-border shadow-sm space-y-6">
              <div class="flex items-center gap-3 pb-4 border-b border-border">
                <FileJson class="w-5 h-5 text-muted-foreground" />
                <p class="text-sm text-muted-foreground">{{ t('settings.image_generation.desc') }}</p>
              </div>
              <div class="space-y-3">
                <label class="text-sm font-medium text-foreground">{{ t('settings.image_generation.default_model') }}</label>
                <Select v-model="defaultModelId" @update:modelValue="isEditing = true">
                  <SelectTrigger class="h-12 bg-background border-border text-foreground rounded-xl px-4">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent class="bg-popover border-border text-popover-foreground">
                    <SelectItem value="__auto__">{{ t('settings.image_generation.auto_model') }}</SelectItem>
                    <SelectItem v-for="m in imageModels" :key="m.id" :value="m.id">
                      {{ m.name }} ({{ m.id }})
                    </SelectItem>
                  </SelectContent>
                </Select>
                <p class="text-xs text-muted-foreground">{{ t('settings.image_generation.default_model_hint') }}</p>
              </div>
            </div>
          </section>

          <div class="h-24"></div>
        </div>
      </div>
    </div>
  </div>
</template>
