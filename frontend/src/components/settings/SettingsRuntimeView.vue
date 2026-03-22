<script setup lang="ts">
import { ref, onMounted, onActivated, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  Save,
  Check,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Sliders,
  Database,
  FileJson,
  ScanSearch,
  Mic,
  Zap,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { getSystemConfig, updateSystemConfig, type SystemConfig } from '@/services/api'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const settingsSection = computed(() => route.name as string)
const navCollapsed = ref(false)
const advancedOpen = ref(false)

const autoUnloadLocalModelOnSwitch = ref(false)
const runtimeAutoReleaseEnabled = ref(true)
const runtimeMaxCachedLocalRuntimes = ref(1)
const runtimeMaxCachedLocalLlmRuntimes = ref(1)
const runtimeMaxCachedLocalVlmRuntimes = ref(1)
const runtimeMaxCachedLocalImageGenerationRuntimes = ref(1)
const runtimeReleaseIdleTtlSeconds = ref(300)
const runtimeReleaseMinIntervalSeconds = ref(5)

const config = ref<SystemConfig | null>(null)
const isSaving = ref(false)
const saveSuccess = ref(false)
const saveError = ref('')

function parseBool(value: unknown, defaultVal: boolean): boolean {
  if (value === undefined || value === null) return defaultVal
  if (value === true || value === 1 || value === 'true') return true
  if (value === false || value === 0 || value === 'false') return false
  return defaultVal
}

const loadConfig = async () => {
  try {
    const c = await getSystemConfig()
    config.value = c
    const s = c.settings ?? {}
    autoUnloadLocalModelOnSwitch.value = parseBool(s.autoUnloadLocalModelOnSwitch, false)
    runtimeAutoReleaseEnabled.value = parseBool(s.runtimeAutoReleaseEnabled, true)
    runtimeMaxCachedLocalRuntimes.value = Math.min(16, Math.max(1, Number(s.runtimeMaxCachedLocalRuntimes) || 1))
    runtimeMaxCachedLocalLlmRuntimes.value = Math.min(16, Math.max(1, Number(s.runtimeMaxCachedLocalLlmRuntimes) || runtimeMaxCachedLocalRuntimes.value || 1))
    runtimeMaxCachedLocalVlmRuntimes.value = Math.min(16, Math.max(1, Number(s.runtimeMaxCachedLocalVlmRuntimes) || runtimeMaxCachedLocalRuntimes.value || 1))
    runtimeMaxCachedLocalImageGenerationRuntimes.value = Math.min(16, Math.max(1, Number(s.runtimeMaxCachedLocalImageGenerationRuntimes) || runtimeMaxCachedLocalRuntimes.value || 1))
    runtimeReleaseIdleTtlSeconds.value = Math.min(86400, Math.max(30, Number(s.runtimeReleaseIdleTtlSeconds) || 300))
    runtimeReleaseMinIntervalSeconds.value = Math.min(3600, Math.max(1, Number(s.runtimeReleaseMinIntervalSeconds) || 5))
  } catch (e) {
    console.error('Failed to load system config:', e)
  }
}

onMounted(() => {
  loadConfig()
})

onActivated(() => {
  loadConfig()
})

const handleSave = async () => {
  isSaving.value = true
  saveError.value = ''
  try {
    await updateSystemConfig({
      autoUnloadLocalModelOnSwitch: Boolean(autoUnloadLocalModelOnSwitch.value),
      runtimeAutoReleaseEnabled: Boolean(runtimeAutoReleaseEnabled.value),
      runtimeMaxCachedLocalRuntimes: runtimeMaxCachedLocalRuntimes.value,
      runtimeMaxCachedLocalLlmRuntimes: runtimeMaxCachedLocalLlmRuntimes.value,
      runtimeMaxCachedLocalVlmRuntimes: runtimeMaxCachedLocalVlmRuntimes.value,
      runtimeMaxCachedLocalImageGenerationRuntimes: runtimeMaxCachedLocalImageGenerationRuntimes.value,
      runtimeReleaseIdleTtlSeconds: runtimeReleaseIdleTtlSeconds.value,
      runtimeReleaseMinIntervalSeconds: runtimeReleaseMinIntervalSeconds.value,
    })
    await loadConfig()
    saveSuccess.value = true
    setTimeout(() => { saveSuccess.value = false }, 3000)
  } catch (e) {
    console.error('Failed to save runtime settings:', e)
    saveError.value = e instanceof Error ? e.message : String(e)
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <header class="pt-10 pb-6 px-10 flex items-start justify-between shrink-0">
      <div class="space-y-2">
        <h1 class="text-4xl font-bold tracking-tight">{{ t('settings.runtime.title') }}</h1>
        <p class="text-muted-foreground text-lg">{{ t('settings.runtime.subtitle') }}</p>
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
            <span v-else class="flex items-center justify-center"><Sliders class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-backup' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/backup')"
          >
            <span v-if="!navCollapsed">{{ t('settings.model_backup.nav_database_backup') }}</span>
            <span v-else class="flex items-center justify-center"><Database class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-model-backup' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/model-backup')"
          >
            <span v-if="!navCollapsed">{{ t('settings.model_backup.nav_model_backup') }}</span>
            <span v-else class="flex items-center justify-center"><FileJson class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-backend' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/backend')"
          >
            <span v-if="!navCollapsed">Backend</span>
            <span v-else class="flex items-center justify-center"><Cpu class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-runtime' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/runtime')"
          >
            <span v-if="!navCollapsed">{{ t('settings.runtime.nav') }}</span>
            <span v-else class="flex items-center justify-center"><Zap class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-object-detection' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/object-detection')"
          >
            <span v-if="!navCollapsed">Object Detection</span>
            <span v-else class="flex items-center justify-center"><ScanSearch class="w-4 h-4" /></span>
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
            <span v-else class="flex items-center justify-center"><Mic class="w-4 h-4" /></span>
          </button>
        </div>
      </aside>

      <main class="flex-1 overflow-y-auto custom-scrollbar pr-4">
        <div class="space-y-10">
          <section class="space-y-4">
            <h2 class="text-xl font-bold">{{ t('settings.runtime.title') }}</h2>
            <div class="p-8 rounded-2xl bg-card border border-border shadow-sm space-y-8">
              <div
                v-if="isEditing"
                class="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100"
              >
                <div class="font-semibold">{{ t('settings.unsaved_changes') }}</div>
                <div class="mt-1">{{ t('settings.unsaved_changes_desc') }}</div>
              </div>
              <div class="rounded-2xl border border-border/60 bg-background/40 p-5">
                <p class="text-xs leading-6 text-muted-foreground">
                  {{ t('settings.runtime.effective_timing_note') }}
                </p>
              </div>
              <div
                v-if="saveError"
                class="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
              >
                <div class="font-semibold">{{ t('settings.runtime.save_error_title') }}</div>
                <div class="mt-1 break-words">{{ saveError }}</div>
              </div>
              <div class="flex items-center justify-between gap-4">
                <div class="space-y-1">
                  <label class="text-sm font-medium text-foreground">{{ t('settings.runtime.auto_release_enabled') }}</label>
                  <p class="text-xs text-muted-foreground">{{ t('settings.runtime.auto_release_enabled_desc') }}</p>
                </div>
                <Switch :checked="runtimeAutoReleaseEnabled" @update:checked="(v: boolean) => { runtimeAutoReleaseEnabled = v; isEditing = true }" />
              </div>
              <div class="space-y-3">
                <h3 class="text-sm font-semibold text-foreground">{{ t('settings.runtime.per_type_limits') }}</h3>
                <p class="text-xs text-muted-foreground">{{ t('settings.runtime.per_type_limits_desc') }}</p>
                <div class="grid gap-4 md:grid-cols-3">
                  <div class="space-y-3">
                    <label class="text-sm font-medium text-foreground">{{ t('settings.runtime.max_cached_llm') }}</label>
                    <Input
                      v-model.number="runtimeMaxCachedLocalLlmRuntimes"
                      type="number"
                      min="1"
                      max="16"
                      class="w-full h-12 bg-background border-border text-foreground rounded-xl px-4"
                      @update:modelValue="isEditing = true"
                    />
                    <p class="text-xs text-muted-foreground">{{ t('settings.runtime.max_cached_llm_desc') }}</p>
                  </div>
                  <div class="space-y-3">
                    <label class="text-sm font-medium text-foreground">{{ t('settings.runtime.max_cached_vlm') }}</label>
                    <Input
                      v-model.number="runtimeMaxCachedLocalVlmRuntimes"
                      type="number"
                      min="1"
                      max="16"
                      class="w-full h-12 bg-background border-border text-foreground rounded-xl px-4"
                      @update:modelValue="isEditing = true"
                    />
                    <p class="text-xs text-muted-foreground">{{ t('settings.runtime.max_cached_vlm_desc') }}</p>
                  </div>
                  <div class="space-y-3">
                    <label class="text-sm font-medium text-foreground">{{ t('settings.runtime.max_cached_image_generation') }}</label>
                    <Input
                      v-model.number="runtimeMaxCachedLocalImageGenerationRuntimes"
                      type="number"
                      min="1"
                      max="16"
                      class="w-full h-12 bg-background border-border text-foreground rounded-xl px-4"
                      @update:modelValue="isEditing = true"
                    />
                    <p class="text-xs text-muted-foreground">{{ t('settings.runtime.max_cached_image_generation_desc') }}</p>
                  </div>
                </div>
              </div>
              <div class="space-y-3">
                <label class="text-sm font-medium text-foreground">{{ t('settings.runtime.idle_ttl') }}</label>
                <Input
                  v-model.number="runtimeReleaseIdleTtlSeconds"
                  type="number"
                  min="30"
                  max="86400"
                  class="w-28 h-12 bg-background border-border text-foreground rounded-xl px-4"
                  @update:modelValue="isEditing = true"
                />
                <p class="text-xs text-muted-foreground">{{ t('settings.runtime.idle_ttl_desc') }}</p>
              </div>
              <div class="space-y-3">
                <label class="text-sm font-medium text-foreground">{{ t('settings.runtime.min_interval') }}</label>
                <Input
                  v-model.number="runtimeReleaseMinIntervalSeconds"
                  type="number"
                  min="1"
                  max="3600"
                  class="w-28 h-12 bg-background border-border text-foreground rounded-xl px-4"
                  @update:modelValue="isEditing = true"
                />
                <p class="text-xs text-muted-foreground">{{ t('settings.runtime.min_interval_desc') }}</p>
              </div>
              <div class="rounded-2xl border border-border/60 bg-background/40 p-5">
                <p class="text-xs leading-6 text-muted-foreground">
                  {{ t('settings.runtime.review_note') }}
                </p>
              </div>
              <div class="rounded-2xl border border-border/60 bg-background/40 p-5 space-y-4">
                <button
                  class="w-full flex items-center justify-between text-left"
                  @click="advancedOpen = !advancedOpen"
                >
                  <div class="space-y-1">
                    <h3 class="text-sm font-semibold text-foreground">{{ t('settings.runtime.advanced') }}</h3>
                    <p class="text-xs text-muted-foreground">{{ t('settings.runtime.advanced_desc') }}</p>
                  </div>
                  <ChevronRight class="w-4 h-4 text-muted-foreground transition-transform" :class="advancedOpen ? 'rotate-90' : ''" />
                </button>
                <div v-if="advancedOpen" class="space-y-6 pt-2">
                  <div class="flex items-center justify-between gap-4">
                    <div class="space-y-1">
                      <label class="text-sm font-medium text-foreground">{{ t('settings.runtime.auto_unload') }}</label>
                      <p class="text-xs text-muted-foreground">{{ t('settings.runtime.auto_unload_desc') }}</p>
                    </div>
                    <Switch :checked="autoUnloadLocalModelOnSwitch" @update:checked="(v: boolean) => { autoUnloadLocalModelOnSwitch = v; isEditing = true }" />
                  </div>
                  <div class="space-y-3">
                    <label class="text-sm font-medium text-foreground">{{ t('settings.runtime.max_cached') }}</label>
                    <Input
                      v-model.number="runtimeMaxCachedLocalRuntimes"
                      type="number"
                      min="1"
                      max="16"
                      class="w-32 h-12 bg-background border-border text-foreground rounded-xl px-4"
                      @update:modelValue="isEditing = true"
                    />
                    <p class="text-xs text-muted-foreground">{{ t('settings.runtime.max_cached_desc') }}</p>
                  </div>
                </div>
              </div>
            </div>
          </section>
          <div class="h-24" />
        </div>
      </main>
    </div>
  </div>
</template>
