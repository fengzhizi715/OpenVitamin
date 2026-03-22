<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  buildImageGenerationDownloadUrl,
  cancelImageGenerationJob,
  generateImage,
  getImageGenerationJob,
  getLatestImageGenerationWarmup,
  listModels,
  warmupImageGenerationRuntime,
  type ImageGenerationJob,
  type ImageGenerationJobStatus,
  type ImageGenerationWarmupStatus,
  type ModelInfo,
} from '@/services/api'

defineOptions({ name: 'ImageGenerationView' })

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const models = ref<ModelInfo[]>([])
const loadingModels = ref(false)
const submitting = ref(false)
const warmingUp = ref(false)
const error = ref('')
const successMessage = ref('')
const pollTimer = ref<number | null>(null)
const job = ref<ImageGenerationJob | null>(null)
const warmupStatus = ref<ImageGenerationWarmupStatus | null>(null)

const form = ref({
  model: '',
  prompt: '',
  negativePrompt: '',
  width: 512,
  height: 512,
  steps: 4,
  guidance: 4.0,
  seed: 42,
  imageFormat: 'PNG',
})

const presets = [
  { key: 'fast', width: 512, height: 512, steps: 4, guidance: 4.0 },
  { key: 'balanced', width: 768, height: 768, steps: 8, guidance: 4.0 },
  { key: 'quality', width: 1024, height: 1024, steps: 20, guidance: 4.5 },
] as const

const terminalStates: ImageGenerationJobStatus[] = ['succeeded', 'failed', 'cancelled']

const imageUrl = computed(() => {
  const result = job.value?.result
  if (!result) return ''
  if (result.image_base64) {
    return `data:${result.mime_type};base64,${result.image_base64}`
  }
  if (job.value?.job_id) {
    return buildImageGenerationDownloadUrl(job.value.job_id)
  }
  return ''
})

const progressPercent = computed(() => {
  if (!job.value) return null
  if (typeof job.value.progress === 'number') return job.value.progress
  if (job.value.status === 'succeeded') return 100
  return null
})

const isJobActive = computed(() => {
  return job.value?.status === 'queued' || job.value?.status === 'running'
})

const currentJobId = computed(() => {
  return typeof route.params.jobId === 'string'
    ? route.params.jobId
    : typeof route.query.job_id === 'string'
      ? route.query.job_id
      : ''
})

const isDetailRoute = computed(() => route.name === 'images-job-detail')

function isTerminal(status?: string | null): boolean {
  return !!status && terminalStates.includes(status as ImageGenerationJobStatus)
}

function statusLabel(status?: string | null): string {
  if (!status) return '-'
  return t(`image_generation.status.${status}`)
}

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

function formatDurationMs(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '-'
  if (value < 1000) return `${value} ms`
  const seconds = value / 1000
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  const minutes = Math.floor(seconds / 60)
  const remainSeconds = Math.round(seconds % 60)
  return `${minutes}m ${remainSeconds}s`
}

function executionElapsedMs(item: ImageGenerationJob | null): number | null {
  if (!item?.started_at) return null
  const started = new Date(item.started_at).getTime()
  if (Number.isNaN(started)) return null
  const finished = item.finished_at ? new Date(item.finished_at).getTime() : Date.now()
  if (Number.isNaN(finished) || finished < started) return null
  return finished - started
}

function stopPolling() {
  if (pollTimer.value != null) {
    window.clearTimeout(pollTimer.value)
    pollTimer.value = null
  }
}

function clearMessages() {
  error.value = ''
  successMessage.value = ''
}

function applyPreset(key: typeof presets[number]['key']) {
  const preset = presets.find((item) => item.key === key)
  if (!preset) return
  form.value.width = preset.width
  form.value.height = preset.height
  form.value.steps = preset.steps
  form.value.guidance = preset.guidance
}

const activePresetKey = computed(() => {
  const match = presets.find((preset) =>
    preset.width === form.value.width &&
    preset.height === form.value.height &&
    preset.steps === form.value.steps &&
    preset.guidance === form.value.guidance
  )
  return match?.key || ''
})

async function fetchModels() {
  loadingModels.value = true
  try {
    const response = await listModels()
    models.value = response.data.filter((item) => item.model_type === 'image_generation')
    if (!form.value.model && models.value.length > 0) {
      form.value.model = models.value[0].id
    }
  } catch (e: any) {
    error.value = e?.message || t('image_generation.models_error')
  } finally {
    loadingModels.value = false
  }
}

async function fetchWarmupStatus(model?: string) {
  try {
    warmupStatus.value = await getLatestImageGenerationWarmup(model)
  } catch {
    if (model) {
      try {
        warmupStatus.value = await getLatestImageGenerationWarmup()
        return
      } catch {
      }
    }
    warmupStatus.value = null
  }
}

async function pollJob(jobId: string) {
  try {
    const latest = await getImageGenerationJob(jobId)
    job.value = latest
    if (isTerminal(latest.status)) {
      stopPolling()
      return
    }
  } catch (e: any) {
    error.value = e?.message || t('image_generation.poll_error')
    stopPolling()
    return
  }

  stopPolling()
  pollTimer.value = window.setTimeout(() => {
    void pollJob(jobId)
  }, 2000)
}

async function restoreJobFromRoute() {
  const jobId = currentJobId.value
  if (!jobId) return
  await pollJob(jobId)
}

async function submit() {
  if (!form.value.model || !form.value.prompt.trim()) {
    error.value = t('image_generation.required_error')
    return
  }

  submitting.value = true
  clearMessages()
  stopPolling()
  job.value = null

  try {
    const created = await generateImage(
      {
        model: form.value.model,
        prompt: form.value.prompt.trim(),
        negative_prompt: form.value.negativePrompt.trim() || null,
        width: form.value.width,
        height: form.value.height,
        num_inference_steps: form.value.steps,
        guidance_scale: form.value.guidance,
        seed: form.value.seed,
        image_format: form.value.imageFormat,
      },
      false,
    )

    if (!('job_id' in created)) {
      throw new Error(t('image_generation.sync_response_error'))
    }
    job.value = created
    await router.replace({ name: 'images-job-detail', params: { jobId: created.job_id } })
    await pollJob(created.job_id)
  } catch (e: any) {
    error.value = e?.message || t('image_generation.submit_error')
  } finally {
    submitting.value = false
  }
}

async function cancelCurrentJob() {
  const jobId = job.value?.job_id
  if (!jobId || isTerminal(job.value?.status)) return
  clearMessages()
  try {
    job.value = await cancelImageGenerationJob(jobId)
    await pollJob(jobId)
  } catch (e: any) {
    error.value = e?.message || t('image_generation.cancel_error')
  }
}

async function warmup() {
  if (!form.value.model) {
    error.value = t('image_generation.required_error')
    return
  }
  warmingUp.value = true
  clearMessages()
  try {
    const result = await warmupImageGenerationRuntime({
      model: form.value.model,
      prompt: t('image_generation.warmup_prompt'),
      width: 256,
      height: 256,
      num_inference_steps: 1,
      guidance_scale: 1.0,
      seed: 42,
    })
    successMessage.value = t('image_generation.warmup_done', { ms: result.elapsed_ms })
    await fetchWarmupStatus(form.value.model)
  } catch (e: any) {
    error.value = e?.message || t('image_generation.warmup_error')
  } finally {
    warmingUp.value = false
  }
}

watch(
  () => currentJobId.value,
  async (newJobId, oldJobId) => {
    if (newJobId && newJobId !== oldJobId) {
      await restoreJobFromRoute()
    } else if (!newJobId) {
      stopPolling()
      job.value = null
    }
  },
)

watch(
  () => form.value.model,
  async (model) => {
    if (model) {
      await fetchWarmupStatus(model)
    }
  },
)

onMounted(async () => {
  await fetchModels()
  await Promise.allSettled([
    fetchWarmupStatus(form.value.model || undefined),
  ])
  if (currentJobId.value) {
    await restoreJobFromRoute()
  } else {
    job.value = null
  }
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-background text-foreground">
    <div class="border-b border-border/50 px-6 py-4">
      <div class="flex items-center justify-between gap-4">
        <div>
          <h1 class="text-xl font-semibold">{{ t('image_generation.title') }}</h1>
          <p class="mt-1 text-sm text-muted-foreground">
            {{ t('image_generation.subtitle') }}
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="!isDetailRoute"
            class="rounded-xl border border-border/60 px-4 py-2 text-sm font-medium hover:bg-accent"
            @click="router.push({ name: 'images-history' })"
          >
            {{ t('image_generation.view_history') }}
          </button>
          <button
            v-if="isDetailRoute"
            class="rounded-xl border border-border/60 px-4 py-2 text-sm font-medium hover:bg-accent"
            @click="router.push({ name: 'images' })"
          >
            {{ t('image_generation.back_to_list') }}
          </button>
        </div>
      </div>
    </div>

    <div
      class="mx-auto grid min-h-0 w-full max-w-[1440px] flex-1 items-start gap-6 overflow-auto p-6"
      :class="isDetailRoute ? 'grid-cols-1' : 'grid-cols-1 xl:grid-cols-[420px_minmax(0,1fr)]'"
    >
      <section v-if="!isDetailRoute" class="rounded-2xl border border-border/60 bg-card/50 p-5">
        <div class="space-y-4">
          <label class="block">
            <span class="mb-2 block text-sm font-medium">{{ t('image_generation.model') }}</span>
            <select
              v-model="form.model"
              class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none"
              :disabled="loadingModels || submitting || warmingUp"
            >
              <option value="" disabled>{{ t('image_generation.model') }}</option>
              <option v-for="model in models" :key="model.id" :value="model.id">
                {{ model.display_name || model.name || model.id }}
              </option>
            </select>
          </label>

          <div>
            <div class="mb-2 block text-sm font-medium">{{ t('image_generation.presets') }}</div>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="preset in presets"
                :key="preset.key"
                class="rounded-full border px-3 py-1.5 text-xs font-medium"
                :class="activePresetKey === preset.key ? 'border-primary bg-primary/15 text-primary' : 'border-border/60 hover:bg-accent'"
                @click="applyPreset(preset.key)"
              >
                {{ t(`image_generation.preset_${preset.key}`) }}
              </button>
            </div>
          </div>

          <label class="block">
            <span class="mb-2 block text-sm font-medium">{{ t('image_generation.prompt') }}</span>
            <textarea
              v-model="form.prompt"
              rows="5"
              class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none"
              :placeholder="t('image_generation.prompt_placeholder')"
            />
          </label>

          <label class="block">
            <span class="mb-2 block text-sm font-medium">{{ t('image_generation.negative_prompt') }}</span>
            <textarea
              v-model="form.negativePrompt"
              rows="3"
              class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none"
              :placeholder="t('image_generation.negative_prompt_placeholder')"
            />
          </label>

          <div class="grid grid-cols-2 gap-3">
            <label class="block">
              <span class="mb-2 block text-sm font-medium">{{ t('image_generation.width') }}</span>
              <input v-model.number="form.width" type="number" class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none" />
            </label>
            <label class="block">
              <span class="mb-2 block text-sm font-medium">{{ t('image_generation.height') }}</span>
              <input v-model.number="form.height" type="number" class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none" />
            </label>
            <label class="block">
              <span class="mb-2 block text-sm font-medium">{{ t('image_generation.steps') }}</span>
              <input v-model.number="form.steps" type="number" class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none" />
            </label>
            <label class="block">
              <span class="mb-2 block text-sm font-medium">{{ t('image_generation.guidance') }}</span>
              <input v-model.number="form.guidance" type="number" step="0.1" class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none" />
            </label>
            <label class="block">
              <span class="mb-2 block text-sm font-medium">{{ t('image_generation.seed') }}</span>
              <input v-model.number="form.seed" type="number" class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none" />
            </label>
            <label class="block">
              <span class="mb-2 block text-sm font-medium">{{ t('image_generation.format') }}</span>
              <select v-model="form.imageFormat" class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none">
                <option value="PNG">{{ t('image_generation.format_png') }}</option>
                <option value="JPEG">{{ t('image_generation.format_jpeg') }}</option>
                <option value="WEBP">{{ t('image_generation.format_webp') }}</option>
              </select>
            </label>
          </div>

          <div v-if="error" class="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {{ error }}
          </div>
          <div v-if="successMessage" class="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            {{ successMessage }}
          </div>

          <div class="flex flex-wrap gap-3">
            <button
              class="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="submitting || loadingModels || warmingUp"
              @click="submit"
            >
              {{ submitting ? t('image_generation.submitting') : t('image_generation.start_job') }}
            </button>
            <button
              class="rounded-xl border border-border/60 px-4 py-2 text-sm font-medium text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!job || isTerminal(job.status)"
              @click="cancelCurrentJob"
            >
              {{ t('image_generation.cancel_job') }}
            </button>
            <button
              class="rounded-xl border border-border/60 px-4 py-2 text-sm font-medium text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!form.model || warmingUp || submitting"
              @click="warmup"
            >
              {{ warmingUp ? t('image_generation.warming_up') : t('image_generation.warmup') }}
            </button>
          </div>

          <div class="rounded-2xl border border-border/60 bg-background/40 p-4">
            <div>
              <h2 class="text-sm font-semibold">{{ t('image_generation.warmup_status') }}</h2>
              <p class="mt-1 text-xs text-muted-foreground">
                {{ warmupStatus ? t('image_generation.warmup_done', { ms: warmupStatus.elapsed_ms }) : t('image_generation.warmup_none') }}
              </p>
            </div>
            <div v-if="warmupStatus" class="mt-3 space-y-1 text-xs text-muted-foreground">
              <div>{{ t('image_generation.warmup_model') }}: {{ warmupStatus.model }}</div>
              <div>{{ t('image_generation.warmup_last') }}: {{ warmupStatus.started_at }}</div>
              <div>{{ t('image_generation.status_label') }}: {{ statusLabel(warmupStatus.status) }}</div>
              <div class="break-all">{{ warmupStatus.output_path || '-' }}</div>
            </div>
          </div>
        </div>
      </section>

      <section class="min-h-0 self-start rounded-2xl border border-border/60 bg-card/50 p-5">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-lg font-semibold">{{ t('image_generation.job_status') }}</h2>
            <p class="mt-1 text-sm text-muted-foreground">{{ t('image_generation.job_status_desc') }}</p>
          </div>
          <div
            v-if="job"
            class="rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-wide"
            :class="{
              'border-amber-500/40 text-amber-300': job.status === 'queued',
              'border-blue-500/40 text-blue-300': job.status === 'running',
              'border-emerald-500/40 text-emerald-300': job.status === 'succeeded',
              'border-red-500/40 text-red-300': job.status === 'failed',
              'border-slate-500/40 text-slate-300': job.status === 'cancelled',
            }"
          >
            <span class="inline-flex items-center gap-2">
              <span
                v-if="isJobActive"
                class="inline-block h-2 w-2 rounded-full bg-current animate-pulse"
              />
              {{ statusLabel(job.status) }}
            </span>
          </div>
        </div>

          <div v-if="job" class="mt-5 space-y-4">
            <div class="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
              <div class="space-y-3">
                <div class="rounded-xl border border-border/50 bg-background/60 p-4">
                  <div class="text-xs uppercase tracking-wide text-muted-foreground">{{ t('image_generation.execution_summary') }}</div>
                  <div class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                    <div>
                      <div class="text-xs text-muted-foreground">{{ t('image_generation.job_id') }}</div>
                      <div class="mt-1 break-all text-sm">{{ job.job_id }}</div>
                    </div>
                    <div>
                      <div class="text-xs text-muted-foreground">{{ t('image_generation.phase') }}</div>
                      <div class="mt-1 text-sm">{{ job.phase || '-' }}</div>
                    </div>
                    <div>
                      <div class="text-xs text-muted-foreground">{{ t('image_generation.result_model') }}</div>
                      <div class="mt-1 break-all text-sm">{{ job.model }}</div>
                    </div>
                    <div>
                      <div class="text-xs text-muted-foreground">{{ t('image_generation.elapsed') }}</div>
                      <div class="mt-1 text-sm">{{ formatDurationMs(executionElapsedMs(job)) }}</div>
                    </div>
                  </div>
                </div>

                <div class="rounded-xl border border-border/50 bg-background/60 p-4">
                  <div class="text-xs uppercase tracking-wide text-muted-foreground">{{ t('image_generation.request_summary') }}</div>
                  <div class="mt-3">
                    <div class="text-xs text-muted-foreground">{{ t('image_generation.result_prompt') }}</div>
                    <div class="mt-1 whitespace-pre-wrap text-sm leading-6">{{ job.prompt }}</div>
                  </div>
                </div>
              </div>

              <div class="space-y-3">
                <div class="rounded-xl border border-border/50 bg-background/60 p-4">
                  <div class="text-xs uppercase tracking-wide text-muted-foreground">{{ t('image_generation.execution_timing') }}</div>
                  <div class="mt-3 space-y-3 text-sm">
                    <div>
                      <div class="text-xs text-muted-foreground">{{ t('image_generation.created_at') }}</div>
                      <div class="mt-1">{{ formatDateTime(job.created_at) }}</div>
                    </div>
                    <div>
                      <div class="text-xs text-muted-foreground">{{ t('image_generation.started_at') }}</div>
                      <div class="mt-1">{{ formatDateTime(job.started_at) }}</div>
                    </div>
                    <div>
                      <div class="text-xs text-muted-foreground">{{ t('image_generation.finished_at') }}</div>
                      <div class="mt-1">{{ formatDateTime(job.finished_at) }}</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="job.status === 'queued' || job.status === 'running'" class="rounded-xl border border-border/50 bg-background/60 p-3">
              <div class="flex items-center justify-between text-xs text-muted-foreground">
                <span>{{ t('image_generation.phase') }}: {{ job.phase || '-' }}</span>
                <span v-if="job.status === 'queued' && job.queue_position">#{{ job.queue_position }}</span>
                <span v-else-if="job.current_step && job.total_steps">{{ job.current_step }}/{{ job.total_steps }}</span>
              </div>
              <div class="mt-2 h-2 overflow-hidden rounded-full bg-muted/40">
                <div
                  class="h-full bg-blue-500 transition-all duration-300"
                  :style="{ width: `${progressPercent ?? (job.status === 'queued' ? 5 : 10)}%` }"
                />
              </div>
              <div class="mt-2 text-xs text-muted-foreground">
                {{ progressPercent != null ? `${progressPercent}%` : '-' }}
              </div>
            </div>

          <div v-if="job.error" class="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
            {{ job.error }}
          </div>

          <div v-if="job.result || isJobActive" class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div class="rounded-2xl border border-border/50 bg-background/60 p-4">
              <div class="relative h-[60vh] min-h-[360px] max-h-[640px] overflow-hidden rounded-xl">
                <div v-if="imageUrl" class="flex h-full w-full items-center justify-center bg-background/40">
                  <img :src="imageUrl" :alt="t('image_generation.preview_alt')" class="h-full w-full object-contain" />
                </div>
                <div v-else class="flex h-full items-center justify-center rounded-xl border border-dashed border-border/50 text-sm text-muted-foreground">
                  {{ isJobActive ? t('image_generation.generating_placeholder') : t('image_generation.preview_empty') }}
                </div>

                <div
                  v-if="isJobActive"
                  class="absolute inset-0 flex flex-col items-center justify-center rounded-xl bg-background/75 backdrop-blur-sm"
                >
                  <div class="h-10 w-10 rounded-full border-2 border-primary/20 border-t-primary animate-spin" />
                  <div class="mt-4 text-sm font-medium">
                    {{ job?.status === 'queued' ? t('image_generation.loading_queued') : t('image_generation.loading_generating') }}
                  </div>
                  <div class="mt-1 text-xs text-muted-foreground">
                    {{ job?.phase || '-' }}
                  </div>
                  <div v-if="progressPercent != null" class="mt-3 w-full max-w-xs px-6">
                    <div class="h-2 overflow-hidden rounded-full bg-muted/40">
                      <div class="h-full bg-primary transition-all duration-300" :style="{ width: `${progressPercent}%` }" />
                    </div>
                    <div class="mt-2 text-center text-xs text-muted-foreground">{{ progressPercent }}%</div>
                  </div>
                </div>
              </div>
            </div>

            <div class="space-y-3 xl:sticky xl:top-4 self-start">
              <div class="rounded-xl border border-border/50 bg-background/60 p-3">
                <div class="text-xs uppercase tracking-wide text-muted-foreground">{{ t('image_generation.result_card') }}</div>
                <div class="mt-2 space-y-2 text-sm">
                  <div>
                    <div class="text-xs text-muted-foreground">{{ t('image_generation.result_model') }}</div>
                    <div class="mt-1 break-all">{{ job.model }}</div>
                  </div>
                  <div>
                    <div class="text-xs text-muted-foreground">{{ t('image_generation.result_prompt') }}</div>
                    <div class="mt-1 line-clamp-4">{{ job.prompt }}</div>
                  </div>
                </div>
              </div>
              <div class="rounded-xl border border-border/50 bg-background/60 p-3">
                <div class="text-xs uppercase tracking-wide text-muted-foreground">{{ t('image_generation.output') }}</div>
                <div v-if="job.result" class="mt-2 space-y-2 text-sm">
                  <div>{{ t('image_generation.dimensions_value', { width: job.result.width, height: job.result.height }) }}</div>
                  <div>{{ t('image_generation.latency_ms', { value: job.result.latency_ms ?? '-' }) }}</div>
                  <div>{{ t('image_generation.seed_value', { value: job.result.seed ?? '-' }) }}</div>
                </div>
                <div v-else class="mt-2 text-sm text-muted-foreground">
                  {{ job?.status === 'queued' ? t('image_generation.loading_queued') : t('image_generation.loading_generating') }}
                </div>
              </div>

              <div class="rounded-xl border border-border/50 bg-background/60 p-3">
                <div class="text-xs uppercase tracking-wide text-muted-foreground">{{ t('image_generation.stored_file') }}</div>
                <div class="mt-2 break-all text-xs text-muted-foreground">
                  {{ job.result?.output_path || '-' }}
                </div>
                <a
                  v-if="job.job_id && job.result?.output_path"
                  class="mt-3 inline-flex rounded-lg border border-border/60 px-3 py-2 text-sm hover:bg-accent"
                  :href="buildImageGenerationDownloadUrl(job.job_id)"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {{ t('image_generation.download_file') }}
                </a>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="mt-5 flex h-[320px] items-center justify-center rounded-2xl border border-dashed border-border/50 text-sm text-muted-foreground">
          {{ t('image_generation.no_job') }}
        </div>
      </section>
    </div>
  </div>
</template>
