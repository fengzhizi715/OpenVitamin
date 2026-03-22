<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  ChevronLeft,
  ChevronRight,
  Sliders,
  Cpu,
  ScanSearch,
  Mic,
  Database,
  FileJson,
  RefreshCw,
  Zap,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  getModelBackupStatus,
  listModelBackups,
  createAllModelBackups,
  createModelBackup,
  deleteModelBackup,
  restoreModelBackup,
  restoreModelBackupBatch,
  getModelBackupRetentionDryRun,
  cleanupModelBackupRetention,
  listModels,
  type ModelBackupRecord,
} from '@/services/api'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const settingsSection = computed(() => route.name as string)
const navCollapsed = ref(false)

const modelBackupStatus = ref<{ last_daily_manifest_date: string | null; daily_manifest_dates: string[] }>({
  last_daily_manifest_date: null,
  daily_manifest_dates: [],
})
const modelBackupList = ref<ModelBackupRecord[]>([])
const modelBackupFilter = ref('')
const modelBackupLoading = ref(false)
const showModelRestoreDialog = ref(false)
const modelRestoreBackupId = ref<string | null>(null)
const modelRestoreConfirmId = ref('')
const showDeleteBackupDialog = ref(false)
const deleteBackupId = ref<string | null>(null)
const deleteBackupLoading = ref(false)
const batchRestoreDate = ref('')
const batchRestoreDryRun = ref(true)
const retentionReport = ref<{ to_delete_count: number; kept_count: number; policy: string; to_delete: { model_id: string; file: string }[] } | null>(null)
const cleanupDryRun = ref(true)

const localModels = ref<{ id: string; name: string }[]>([])
const singleBackupModelId = ref<string>('')
const singleBackupReason = ref('')
const singleBackupLoading = ref(false)

const loadLocalModels = async () => {
  try {
    const res = await listModels()
    const list = (res.data || []).filter((m: { id?: string }) => (m.id || '').startsWith('local:'))
    localModels.value = list.map((m: { id: string; name?: string }) => ({ id: m.id, name: m.name || m.id }))
    if (localModels.value.length && !singleBackupModelId.value) {
      singleBackupModelId.value = localModels.value[0].id
    }
  } catch (e) {
    console.error('Failed to load local models', e)
  }
}

const handleCreateSingleBackup = async () => {
  if (!singleBackupModelId.value) {
    alert(t('settings.model_backup.single_backup_select_placeholder'))
    return
  }
  try {
    singleBackupLoading.value = true
    const result = await createModelBackup(singleBackupModelId.value, singleBackupReason.value || undefined)
    if (result.success && result.backup_id) {
      let msg = t('settings.model_backup.single_backup_success') + ': ' + result.backup_id
      if (result.backup_root && result.storage_path) {
        msg += '\n' + t('settings.model_backup.single_backup_path_hint') + ': ' + result.backup_root + '/model_json/' + result.storage_path
      }
      alert(msg)
      singleBackupReason.value = ''
      await loadModelBackupData()
    } else {
      alert((result.error || 'Backup failed') as string)
    }
  } catch (error) {
    alert((error instanceof Error ? error.message : String(error)) as string)
  } finally {
    singleBackupLoading.value = false
  }
}

const loadModelBackupData = async () => {
  try {
    modelBackupLoading.value = true
    const [status, list] = await Promise.all([
      getModelBackupStatus(),
      listModelBackups(modelBackupFilter.value || undefined, 100),
    ])
    modelBackupStatus.value = status
    modelBackupList.value = list
  } catch (error) {
    console.error('Failed to load model backup data:', error)
  } finally {
    modelBackupLoading.value = false
  }
}

const handleCreateAllModelBackups = async () => {
  try {
    modelBackupLoading.value = true
    const result = await createAllModelBackups('手动全量快照')
    if (result.success) {
      const failed = result.failed?.length ?? 0
      const msg = failed
        ? t('settings.model_backup.alert_create_all_partial', { success: result.success_count, total: result.total, failed })
        : t('settings.model_backup.alert_create_all_success', { success: result.success_count, total: result.total })
      alert(msg)
      await loadModelBackupData()
    }
  } catch (error) {
    alert(t('settings.model_backup.alert_create_all_fail') + ': ' + (error instanceof Error ? error.message : String(error)))
  } finally {
    modelBackupLoading.value = false
  }
}

const handleModelRestore = (backupId: string) => {
  modelRestoreBackupId.value = backupId
  modelRestoreConfirmId.value = ''
  showModelRestoreDialog.value = true
}

const handleDeleteBackupClick = (backupId: string) => {
  deleteBackupId.value = backupId
  showDeleteBackupDialog.value = true
}

const confirmDeleteBackup = async () => {
  const bid = deleteBackupId.value
  if (!bid) return
  try {
    deleteBackupLoading.value = true
    const result = await deleteModelBackup(bid)
    if (result.success) {
      showDeleteBackupDialog.value = false
      deleteBackupId.value = null
      await loadModelBackupData()
    } else {
      alert((result.error ?? 'Delete failed') as string)
    }
  } catch (e) {
    alert((e instanceof Error ? e.message : String(e)) as string)
  } finally {
    deleteBackupLoading.value = false
  }
}

const confirmModelRestore = async () => {
  const bid = modelRestoreBackupId.value
  if (!bid) return
  if (modelRestoreConfirmId.value !== bid) {
    alert(t('settings.model_backup.alert_confirm_restore_id'))
    return
  }
  try {
    modelBackupLoading.value = true
    const result = await restoreModelBackup(bid, false)
    if (result.success) {
      alert(t('settings.model_backup.alert_restore_success'))
      showModelRestoreDialog.value = false
      modelRestoreBackupId.value = null
      await loadModelBackupData()
    } else {
      alert(t('settings.model_backup.alert_restore_fail') + ': ' + (result.error ?? ''))
    }
  } catch (error) {
    alert(t('settings.model_backup.alert_restore_fail') + ': ' + (error instanceof Error ? error.message : String(error)))
  } finally {
    modelBackupLoading.value = false
  }
}

const handleBatchRestore = async () => {
  if (!batchRestoreDate.value) {
    alert(t('settings.model_backup.alert_select_date'))
    return
  }
  const targetTs = batchRestoreDate.value + 'T00:00:00Z'
  try {
    modelBackupLoading.value = true
    const result = await restoreModelBackupBatch(targetTs, undefined, batchRestoreDryRun.value)
    if (result.success) {
      const count = result.restored?.length ?? 0
      const failed = result.failed?.length ?? 0
      const msg = batchRestoreDryRun.value
        ? t('settings.model_backup.alert_batch_dry_run', { count })
        : t('settings.model_backup.alert_batch_done', { success: count, failed })
      alert(msg)
      if (!batchRestoreDryRun.value) await loadModelBackupData()
    }
  } catch (error) {
    alert(t('settings.model_backup.alert_batch_fail') + ': ' + (error instanceof Error ? error.message : String(error)))
  } finally {
    modelBackupLoading.value = false
  }
}

const handleRetentionDryRun = async () => {
  try {
    modelBackupLoading.value = true
    const report = await getModelBackupRetentionDryRun(modelBackupFilter.value || undefined)
    retentionReport.value = report
  } catch (error) {
    alert(t('settings.model_backup.alert_retention_fail') + ': ' + (error instanceof Error ? error.message : String(error)))
  } finally {
    modelBackupLoading.value = false
  }
}

const handleCleanupRetention = async () => {
  if (!confirm(cleanupDryRun.value ? t('settings.model_backup.confirm_cleanup_report') : t('settings.model_backup.confirm_cleanup_delete'))) return
  try {
    modelBackupLoading.value = true
    const result = await cleanupModelBackupRetention(cleanupDryRun.value, modelBackupFilter.value || undefined)
    const count = result.to_delete_count ?? 0
    const deleted = result.deleted_count ?? 0
    const errs = result.errors?.length ?? 0
    const msg = cleanupDryRun.value
      ? t('settings.model_backup.alert_cleanup_dry_run', { count })
      : errs > 0
        ? t('settings.model_backup.alert_cleanup_errors', { count: deleted, errors: errs })
        : t('settings.model_backup.alert_cleanup_done', { count: deleted })
    alert(msg)
    if (!cleanupDryRun.value) await loadModelBackupData()
    retentionReport.value = null
  } catch (error) {
    alert(t('settings.model_backup.alert_cleanup_fail') + ': ' + (error instanceof Error ? error.message : String(error)))
  } finally {
    modelBackupLoading.value = false
  }
}

const filteredModelBackupList = computed(() => {
  const list = modelBackupList.value
  const q = (modelBackupFilter.value || '').trim().toLowerCase()
  if (!q) return list
  return list.filter(b => (b.model_id || '').toLowerCase().includes(q))
})

onMounted(() => {
  loadLocalModels()
  loadModelBackupData()
})
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <header class="pt-10 pb-6 px-10 flex items-start justify-between shrink-0">
      <div class="space-y-2">
        <h1 class="text-4xl font-bold tracking-tight">{{ t('settings.model_backup.title') }}</h1>
        <p class="text-muted-foreground text-lg">{{ t('settings.model_backup.subtitle') }}</p>
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
          <!-- 单模型备份 -->
          <section class="space-y-4">
            <h2 class="text-xl font-bold">{{ t('settings.model_backup.single_backup_title') }}</h2>
            <p class="text-sm text-muted-foreground">{{ t('settings.model_backup.single_backup_desc') }}</p>
            <div class="p-6 rounded-2xl bg-card border border-border shadow-sm flex flex-wrap items-end gap-4">
              <Select v-model="singleBackupModelId">
                <SelectTrigger class="w-[280px] h-11 rounded-xl bg-background">
                  <SelectValue :placeholder="t('settings.model_backup.single_backup_select_placeholder')" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem
                    v-for="m in localModels"
                    :key="m.id"
                    :value="m.id"
                  >
                    {{ m.name || m.id }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <Input
                v-model="singleBackupReason"
                :placeholder="t('settings.model_backup.single_backup_reason_placeholder')"
                class="w-[200px] h-11 rounded-xl"
              />
              <Button
                class="h-11 px-6 rounded-xl"
                :disabled="singleBackupLoading || !singleBackupModelId || localModels.length === 0"
                @click="handleCreateSingleBackup"
              >
                {{ singleBackupLoading ? '...' : t('settings.model_backup.single_backup_btn') }}
              </Button>
              <span v-if="localModels.length === 0" class="text-sm text-muted-foreground">{{ t('settings.model_backup.single_backup_no_local') }}</span>
            </div>
          </section>

          <section class="space-y-4">
            <h2 class="text-xl font-bold">{{ t('settings.model_backup.section_title') }}</h2>
            <p class="text-sm text-muted-foreground">{{ t('settings.model_backup.section_desc') }}</p>
            <div class="p-8 rounded-2xl bg-card border border-border shadow-sm space-y-6">
              <div class="flex flex-wrap items-center gap-4">
                <div class="space-y-1">
                  <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('settings.model_backup.last_daily') }}</p>
                  <p class="text-lg font-medium">{{ modelBackupStatus.last_daily_manifest_date || '—' }}</p>
                </div>
                <Button
                  class="h-11 px-6 rounded-xl gap-2"
                  :disabled="modelBackupLoading"
                  @click="handleCreateAllModelBackups"
                >
                  <RefreshCw :class="['w-4 h-4', modelBackupLoading ? 'animate-spin' : '']" />
                  {{ t('settings.model_backup.create_all') }}
                </Button>
                <Input
                  v-model="modelBackupFilter"
                  :placeholder="t('settings.model_backup.filter_placeholder')"
                  class="max-w-xs h-11 rounded-xl"
                  @keyup.enter="loadModelBackupData"
                />
                <Button variant="outline" class="h-11 px-6 rounded-xl" :disabled="modelBackupLoading" @click="loadModelBackupData">
                  {{ t('settings.model_backup.refresh') }}
                </Button>
              </div>
              <div class="overflow-x-auto rounded-xl border border-border">
                <table class="w-full text-sm">
                  <thead class="bg-muted/30 border-b border-border">
                    <tr>
                      <th class="text-left px-4 py-3 font-semibold text-muted-foreground">{{ t('settings.model_backup.col_model_id') }}</th>
                      <th class="text-left px-4 py-3 font-semibold text-muted-foreground">{{ t('settings.model_backup.col_backup_id') }}</th>
                      <th class="text-left px-4 py-3 font-semibold text-muted-foreground">{{ t('settings.model_backup.col_time') }}</th>
                      <th class="text-right px-4 py-3 font-semibold text-muted-foreground">{{ t('settings.model_backup.col_actions') }}</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-border">
                    <tr v-for="b in filteredModelBackupList" :key="b.backup_id + b.timestamp_utc" class="hover:bg-muted/20">
                      <td class="px-4 py-3 font-mono text-muted-foreground">{{ b.model_id }}</td>
                      <td class="px-4 py-3 font-mono text-xs">{{ b.backup_id }}</td>
                      <td class="px-4 py-3 text-muted-foreground">{{ b.timestamp_utc ? new Date(b.timestamp_utc).toLocaleString() : '—' }}</td>
                      <td class="px-4 py-3 text-right space-x-1">
                        <Button variant="ghost" size="sm" class="h-8" @click="handleModelRestore(b.backup_id)">
                          {{ t('settings.model_backup.restore') }}
                        </Button>
                        <Button variant="ghost" size="sm" class="h-8 text-destructive hover:text-destructive" @click="handleDeleteBackupClick(b.backup_id)">
                          {{ t('settings.model_backup.delete') }}
                        </Button>
                      </td>
                    </tr>
                    <tr v-if="filteredModelBackupList.length === 0">
                      <td colspan="4" class="px-4 py-8 text-center text-muted-foreground">{{ t('settings.model_backup.no_records') }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="flex flex-wrap items-end gap-4 pt-4 border-t border-border">
                <div class="space-y-1">
                  <label class="text-sm font-medium">{{ t('settings.model_backup.batch_restore_label') }}</label>
                  <div class="flex gap-2">
                    <Input v-model="batchRestoreDate" type="date" class="h-11 rounded-xl w-48" />
                    <Button variant="outline" size="sm" class="h-11" @click="batchRestoreDryRun = !batchRestoreDryRun">
                      {{ batchRestoreDryRun ? t('settings.model_backup.dry_run_only') : t('settings.model_backup.execute') }}
                    </Button>
                    <Button class="h-11 px-6 rounded-xl" :disabled="modelBackupLoading" @click="handleBatchRestore">
                      {{ t('settings.model_backup.batch_restore_btn') }}
                    </Button>
                  </div>
                </div>
                <div class="flex gap-2">
                  <Button variant="outline" class="h-11 rounded-xl" :disabled="modelBackupLoading" @click="handleRetentionDryRun">
                    {{ t('settings.model_backup.retention_dry_run') }}
                  </Button>
                  <Button variant="outline" class="h-11 rounded-xl" :disabled="modelBackupLoading" @click="handleCleanupRetention">
                    {{ cleanupDryRun ? t('settings.model_backup.cleanup_report_only') : t('settings.model_backup.cleanup_execute') }}
                  </Button>
                </div>
              </div>
              <div v-if="retentionReport" class="rounded-xl border border-border p-4 bg-muted/20 text-sm">
                <p class="font-medium mb-2">{{ t('settings.model_backup.retention_report_title') }}：{{ retentionReport?.policy }}</p>
                <p class="text-muted-foreground">{{ t('settings.model_backup.retention_report_summary', { count: retentionReport?.to_delete_count ?? 0, kept: retentionReport?.kept_count ?? 0 }) }}</p>
              </div>
            </div>
          </section>
          <div class="h-24" />
        </div>
      </main>
    </div>

    <div
      v-if="showModelRestoreDialog"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      @click.self="showModelRestoreDialog = false"
    >
      <div class="bg-card border border-border rounded-2xl p-6 max-w-md w-full mx-4 shadow-xl">
        <h3 class="text-xl font-bold mb-2">{{ t('settings.model_backup.restore_confirm_title') }}</h3>
        <p class="text-muted-foreground mb-2">{{ t('settings.model_backup.restore_confirm_backup') }} <code class="text-xs bg-muted px-1 rounded">{{ modelRestoreBackupId }}</code></p>
        <p class="text-sm text-muted-foreground mb-4">{{ t('settings.model_backup.restore_confirm_prompt') }}</p>
        <Input v-model="modelRestoreConfirmId" :placeholder="t('settings.model_backup.restore_confirm_placeholder')" class="mb-4 rounded-xl font-mono" />
        <div class="flex justify-end gap-3">
          <Button variant="outline" class="rounded-xl" @click="showModelRestoreDialog = false">{{ t('settings.model_backup.cancel') }}</Button>
          <Button class="rounded-xl" @click="confirmModelRestore">{{ t('settings.model_backup.confirm_restore') }}</Button>
        </div>
      </div>
    </div>

    <div
      v-if="showDeleteBackupDialog"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      @click.self="showDeleteBackupDialog = false"
    >
      <div class="bg-card border border-border rounded-2xl p-6 max-w-md w-full mx-4 shadow-xl">
        <h3 class="text-xl font-bold mb-2">{{ t('settings.model_backup.delete_confirm_title') }}</h3>
        <p class="text-muted-foreground mb-4">{{ t('settings.model_backup.delete_confirm_message') }} <code class="text-xs bg-muted px-1 rounded">{{ deleteBackupId }}</code></p>
        <div class="flex justify-end gap-3">
          <Button variant="outline" class="rounded-xl" @click="showDeleteBackupDialog = false; deleteBackupId = null">{{ t('settings.model_backup.cancel') }}</Button>
          <Button variant="destructive" class="rounded-xl" :disabled="deleteBackupLoading" @click="confirmDeleteBackup">{{ deleteBackupLoading ? '...' : t('settings.model_backup.confirm_delete') }}</Button>
        </div>
      </div>
    </div>
  </div>
</template>
