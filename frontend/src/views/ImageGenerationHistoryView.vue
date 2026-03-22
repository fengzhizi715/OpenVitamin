<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  buildImageGenerationDownloadUrl,
  buildImageGenerationThumbnailUrl,
  deleteImageGenerationJob,
  listImageGenerationJobs,
  listModels,
  type ImageGenerationJob,
  type ImageGenerationJobStatus,
  type ModelInfo,
} from '@/services/api'

defineOptions({ name: 'ImageGenerationHistoryView' })

const { t } = useI18n()
const router = useRouter()
const HISTORY_PAGE_SIZE = 12

const models = ref<ModelInfo[]>([])
const history = ref<ImageGenerationJob[]>([])
const historyTotal = ref(0)
const historyHasNextPage = ref(false)
const historyPage = ref(1)
const historyStatusFilter = ref<ImageGenerationJobStatus | ''>('')
const historyModelFilter = ref('')
const historySearch = ref('')
const historySort = ref<'created_at_desc' | 'created_at_asc'>('created_at_desc')
const showHistoryFilters = ref(false)
const viewMode = ref<'cards' | 'table'>('table')
const error = ref('')
const historyImageFallbacks = ref<Record<string, string>>({})
const selectedJobIds = ref<string[]>([])

const totalHistoryPages = computed(() => {
  return Math.max(1, Math.ceil(historyTotal.value / HISTORY_PAGE_SIZE))
})

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

function statusLabel(status?: string | null): string {
  if (!status) return '-'
  return t(`image_generation.status.${status}`)
}

function historyImageSrc(item: ImageGenerationJob): string {
  return (
    historyImageFallbacks.value[item.job_id] ||
    item.result?.thumbnail_url ||
    buildImageGenerationThumbnailUrl(item.job_id)
  )
}

function onHistoryImageError(item: ImageGenerationJob) {
  const fallbackUrl = buildImageGenerationDownloadUrl(item.job_id)
  if (historyImageFallbacks.value[item.job_id] !== fallbackUrl) {
    historyImageFallbacks.value[item.job_id] = fallbackUrl
  }
}

async function fetchModels() {
  try {
    const response = await listModels()
    models.value = response.data.filter((item) => item.model_type === 'image_generation')
  } catch (e: any) {
    error.value = e?.message || t('image_generation.models_error')
  }
}

async function fetchHistory() {
  try {
    const offset = (historyPage.value - 1) * HISTORY_PAGE_SIZE
    const response = await listImageGenerationJobs({
      limit: HISTORY_PAGE_SIZE,
      offset,
      include_result: false,
      status: historyStatusFilter.value,
      model: historyModelFilter.value || undefined,
      q: historySearch.value.trim() || undefined,
      sort: historySort.value,
    })
    const maxPage = Math.max(1, Math.ceil(response.total / HISTORY_PAGE_SIZE))
    if (historyPage.value > maxPage) {
      historyPage.value = maxPage
      return
    }
    historyTotal.value = response.total
    historyHasNextPage.value = response.has_next
    history.value = response.items
    selectedJobIds.value = selectedJobIds.value.filter((id) => history.value.some((item) => item.job_id === id))
  } catch (e: any) {
    history.value = []
    historyTotal.value = 0
    historyHasNextPage.value = false
    error.value = e?.message || t('image_generation.history_error')
  }
}

async function openHistoryJob(jobId: string) {
  await router.push({ name: 'images-job-detail', params: { jobId } })
}

async function deleteHistoryJob(jobId: string) {
  if (!window.confirm(t('image_generation.delete_confirm'))) return
  try {
    await deleteImageGenerationJob(jobId)
    await fetchHistory()
  } catch (e: any) {
    error.value = e?.message || t('image_generation.delete_error')
  }
}

async function deleteSelectedJobs() {
  if (selectedJobIds.value.length === 0) return
  if (!window.confirm(t('image_generation.delete_selected_confirm', { count: selectedJobIds.value.length }))) return
  error.value = ''
  const failures: string[] = []
  for (const jobId of [...selectedJobIds.value]) {
    try {
      await deleteImageGenerationJob(jobId)
    } catch {
      failures.push(jobId)
    }
  }
  selectedJobIds.value = []
  await fetchHistory()
  if (failures.length > 0) {
    error.value = t('image_generation.delete_selected_partial', { failed: failures.length })
  }
}

const allVisibleSelected = computed(() => {
  return history.value.length > 0 && history.value.every((item) => selectedJobIds.value.includes(item.job_id))
})

function toggleSelectAllVisible() {
  if (allVisibleSelected.value) {
    selectedJobIds.value = selectedJobIds.value.filter((id) => !history.value.some((item) => item.job_id === id))
    return
  }
  const merged = new Set(selectedJobIds.value)
  for (const item of history.value) merged.add(item.job_id)
  selectedJobIds.value = Array.from(merged)
}

function toggleJobSelection(jobId: string) {
  if (selectedJobIds.value.includes(jobId)) {
    selectedJobIds.value = selectedJobIds.value.filter((id) => id !== jobId)
  } else {
    selectedJobIds.value = [...selectedJobIds.value, jobId]
  }
}

function prevHistoryPage() {
  if (historyPage.value <= 1) return
  historyPage.value -= 1
}

function nextHistoryPage() {
  if (!historyHasNextPage.value) return
  historyPage.value += 1
}

watch(historyPage, async () => {
  await fetchHistory()
})

watch([historyStatusFilter, historyModelFilter, historySearch, historySort], async () => {
  historyPage.value = 1
  await fetchHistory()
})

onMounted(async () => {
  await Promise.allSettled([fetchModels(), fetchHistory()])
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-background text-foreground">
    <div class="border-b border-border/50 px-6 py-4">
      <div class="mx-auto flex w-full max-w-[1440px] items-center justify-between gap-4">
        <div>
          <h1 class="text-xl font-semibold">{{ t('image_generation.history') }}</h1>
          <p class="mt-1 text-sm text-muted-foreground">
            {{ t('image_generation.history_desc', { total: historyTotal }) }}
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button
            class="rounded-xl border border-border/60 px-4 py-2 text-sm font-medium hover:bg-accent"
            @click="router.push({ name: 'images' })"
          >
            {{ t('image_generation.back_to_workspace') }}
          </button>
          <button class="rounded-xl border border-border/60 px-4 py-2 text-sm font-medium hover:bg-accent" @click="fetchHistory">
            {{ t('image_generation.history_refresh') }}
          </button>
        </div>
      </div>
    </div>

    <div class="mx-auto w-full max-w-[1440px] flex-1 overflow-auto p-6">
      <div v-if="error" class="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
        {{ error }}
      </div>

      <div class="rounded-2xl border border-border/60 bg-card/50 p-5">
        <div class="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div class="flex flex-wrap items-center gap-2">
            <button
              class="h-10 rounded-lg border border-border/60 px-3 py-1 text-xs hover:bg-accent"
              @click="showHistoryFilters = !showHistoryFilters"
            >
              {{ showHistoryFilters ? t('image_generation.history_hide_filters') : t('image_generation.history_show_filters') }}
            </button>
            <button
              class="h-10 rounded-lg border border-border/60 px-3 py-1 text-xs hover:bg-accent"
              :class="viewMode === 'table' ? 'bg-accent' : ''"
              @click="viewMode = 'table'"
            >
              {{ t('image_generation.history_view_table') }}
            </button>
            <button
              class="h-10 rounded-lg border border-border/60 px-3 py-1 text-xs hover:bg-accent"
              :class="viewMode === 'cards' ? 'bg-accent' : ''"
              @click="viewMode = 'cards'"
            >
              {{ t('image_generation.history_view_cards') }}
            </button>
            <button
              class="h-10 rounded-lg border border-border/60 px-3 py-1 text-xs hover:bg-accent disabled:opacity-50"
              :disabled="selectedJobIds.length === 0"
              @click="deleteSelectedJobs"
            >
              {{ t('image_generation.history_delete_selected', { count: selectedJobIds.length }) }}
            </button>
          </div>
        </div>

        <div v-if="showHistoryFilters" class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-[180px_240px_minmax(220px,1fr)_180px]">
          <label class="block">
            <span class="mb-2 block text-xs font-medium text-muted-foreground">{{ t('image_generation.history_filter_status') }}</span>
            <select v-model="historyStatusFilter" class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none">
              <option value="">{{ t('image_generation.history_filter_all') }}</option>
              <option value="queued">{{ t('image_generation.status.queued') }}</option>
              <option value="running">{{ t('image_generation.status.running') }}</option>
              <option value="succeeded">{{ t('image_generation.status.succeeded') }}</option>
              <option value="failed">{{ t('image_generation.status.failed') }}</option>
              <option value="cancelled">{{ t('image_generation.status.cancelled') }}</option>
            </select>
          </label>
          <label class="block">
            <span class="mb-2 block text-xs font-medium text-muted-foreground">{{ t('image_generation.history_filter_model') }}</span>
            <select v-model="historyModelFilter" class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none">
              <option value="">{{ t('image_generation.history_filter_all') }}</option>
              <option v-for="model in models" :key="model.id" :value="model.id">
                {{ model.display_name || model.name || model.id }}
              </option>
            </select>
          </label>
          <label class="block">
            <span class="mb-2 block text-xs font-medium text-muted-foreground">{{ t('image_generation.history_search_prompt') }}</span>
            <input
              v-model="historySearch"
              type="text"
              class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none"
              :placeholder="t('image_generation.history_search_placeholder')"
            />
          </label>
          <label class="block">
            <span class="mb-2 block text-xs font-medium text-muted-foreground">{{ t('image_generation.history_sort') }}</span>
            <select v-model="historySort" class="w-full rounded-xl border border-border/60 bg-background px-3 py-2 text-sm outline-none">
              <option value="created_at_desc">{{ t('image_generation.history_sort_latest') }}</option>
              <option value="created_at_asc">{{ t('image_generation.history_sort_oldest') }}</option>
            </select>
          </label>
        </div>

        <div v-if="history.length === 0" class="mt-4 text-sm text-muted-foreground">
          {{ t('image_generation.history_empty') }}
        </div>
        <div v-else-if="viewMode === 'cards'" class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
          <div
            v-for="item in history"
            :key="item.job_id"
            class="rounded-xl border border-border/50 bg-background/70 p-4"
          >
            <div class="mb-3 flex items-center justify-between">
              <label class="inline-flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  :checked="selectedJobIds.includes(item.job_id)"
                  @change="toggleJobSelection(item.job_id)"
                />
                {{ t('image_generation.history_select') }}
              </label>
            </div>
            <div class="flex items-start gap-3">
              <img
                v-if="item.status === 'succeeded'"
                :src="historyImageSrc(item)"
                :alt="t('image_generation.thumbnail_alt')"
                class="h-16 w-16 shrink-0 rounded-lg border border-border/50 object-cover"
                @error="onHistoryImageError(item)"
              />
              <div class="min-w-0 flex-1">
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="truncate text-sm font-medium">{{ item.prompt }}</div>
                    <div class="mt-1 truncate text-xs text-muted-foreground">{{ item.job_id }}</div>
                  </div>
                  <div class="shrink-0 rounded-full border px-2 py-1 text-[11px] uppercase tracking-wide">
                    {{ statusLabel(item.status) }}
                  </div>
                </div>
                <div class="mt-2 text-xs text-muted-foreground">
                  <div>{{ item.model }}</div>
                  <div>{{ formatDateTime(item.created_at) }}</div>
                </div>
              </div>
            </div>
            <div class="mt-4 flex gap-2">
              <button class="rounded-lg border border-border/60 px-2 py-1 text-xs hover:bg-accent" @click.stop="openHistoryJob(item.job_id)">
                {{ t('image_generation.history_open') }}
              </button>
              <button class="rounded-lg border border-border/60 px-2 py-1 text-xs hover:bg-accent" @click.stop="deleteHistoryJob(item.job_id)">
                {{ t('image_generation.history_delete') }}
              </button>
            </div>
          </div>
        </div>
        <div v-else class="mt-4 overflow-hidden rounded-xl border border-border/50">
          <div class="grid grid-cols-[44px_88px_minmax(0,1.2fr)_180px_180px_140px_160px] border-b border-border/50 bg-background/80 px-3 py-2 text-xs font-medium text-muted-foreground">
            <div class="flex items-center justify-center">
              <input type="checkbox" :checked="allVisibleSelected" @change="toggleSelectAllVisible" />
            </div>
            <div>{{ t('image_generation.history_table_preview') }}</div>
            <div>{{ t('image_generation.result_prompt') }}</div>
            <div>{{ t('image_generation.result_model') }}</div>
            <div>{{ t('image_generation.created_at') }}</div>
            <div>{{ t('image_generation.status_label') }}</div>
            <div>{{ t('image_generation.history_actions') }}</div>
          </div>
          <div
            v-for="item in history"
            :key="item.job_id"
            class="grid grid-cols-[44px_88px_minmax(0,1.2fr)_180px_180px_140px_160px] items-center border-b border-border/30 bg-background/60 px-3 py-3 text-sm last:border-b-0"
          >
            <div class="flex items-center justify-center">
              <input type="checkbox" :checked="selectedJobIds.includes(item.job_id)" @change="toggleJobSelection(item.job_id)" />
            </div>
            <div>
              <img
                v-if="item.status === 'succeeded'"
                :src="historyImageSrc(item)"
                :alt="t('image_generation.thumbnail_alt')"
                class="h-14 w-14 rounded-lg border border-border/50 object-cover"
                @error="onHistoryImageError(item)"
              />
            </div>
            <div class="min-w-0">
              <div class="truncate font-medium">{{ item.prompt }}</div>
              <div class="mt-1 truncate text-xs text-muted-foreground">{{ item.job_id }}</div>
            </div>
            <div class="truncate text-xs text-muted-foreground">{{ item.model }}</div>
            <div class="text-xs text-muted-foreground">{{ formatDateTime(item.created_at) }}</div>
            <div>
              <span class="rounded-full border px-2 py-1 text-[11px] uppercase tracking-wide">{{ statusLabel(item.status) }}</span>
            </div>
            <div class="flex gap-2">
              <button class="rounded-lg border border-border/60 px-2 py-1 text-xs hover:bg-accent" @click.stop="openHistoryJob(item.job_id)">
                {{ t('image_generation.history_open') }}
              </button>
              <button class="rounded-lg border border-border/60 px-2 py-1 text-xs hover:bg-accent" @click.stop="deleteHistoryJob(item.job_id)">
                {{ t('image_generation.history_delete') }}
              </button>
            </div>
          </div>
        </div>

        <div class="mt-4 flex items-center justify-between">
          <button class="rounded-lg border border-border/60 px-3 py-1 text-xs hover:bg-accent disabled:opacity-50" :disabled="historyPage <= 1" @click="prevHistoryPage">
            {{ t('image_generation.history_prev') }}
          </button>
          <div class="text-xs text-muted-foreground">
            {{ t('image_generation.history_page', { page: historyPage, totalPages: totalHistoryPages, total: historyTotal }) }}
          </div>
          <button class="rounded-lg border border-border/60 px-3 py-1 text-xs hover:bg-accent disabled:opacity-50" :disabled="!historyHasNextPage" @click="nextHistoryPage">
            {{ t('image_generation.history_next') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
