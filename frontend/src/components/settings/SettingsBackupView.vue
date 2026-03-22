<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { 
  Save, 
  Check,
  ChevronLeft,
  ChevronRight,
  Sliders,
  Cpu,
  ScanSearch,
  Mic,
  Database,
  HardDrive,
  Clock,
  CheckCircle2,
  XCircle,
  Download,
  Upload,
  Trash2,
  FolderOpen,
  FileJson,
  Zap,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { 
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  getDatabaseStatus,
  getBackupConfig,
  updateBackupConfig,
  createBackup,
  restoreBackup,
  listBackups,
  deleteBackup,
  browseBackupDirectory,
  type BackupRecord,
} from '@/services/api'

// ============================================
// 扩展预留接口（未来企业版功能）
// ============================================

enum BackupMode {
  LOCAL = 'local',
  LOGICAL_DUMP = 'logical_dump',
  CLOUD = 'cloud'
}

enum DatabaseType {
  SQLITE = 'sqlite',
  POSTGRESQL = 'postgresql',
  MYSQL = 'mysql'
}

interface BackupConfig {
  enabled: boolean
  frequency: 'on_start' | 'daily' | 'weekly' | 'custom'
  retentionCount: number
  autoDelete: boolean
  backupLocation: string
  mode: BackupMode
  databaseType: DatabaseType
}

interface BackupRecord {
  id: string
  date: string
  size: string
  type: 'auto' | 'manual'
  status: 'success' | 'failed' | 'in_progress'
}

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const settingsSection = computed(() => route.name as string)
const navCollapsed = ref(false)

// State
const isSaving = ref(false)
const saveSuccess = ref(false)
const isEditing = ref(false)

// Database Status
const dbType = ref<DatabaseType>(DatabaseType.SQLITE)
const dbPath = ref('')
const dbSize = ref('0 MB')
const lastBackupTime = ref<string | null>(null)
const backupStatus = ref<'enabled' | 'disabled'>('disabled')

// Backup Strategy
const enableAutoBackup = ref(false)
const backupFrequency = ref<'on_start' | 'daily' | 'weekly' | 'custom'>('daily')
const retentionCount = ref(10)
const autoDelete = ref(true)
const backupLocation = ref('~/.local-ai/backups/')

// Backup History
const backupHistory = ref<BackupRecord[]>([])
const loading = ref(false)

// Restore confirmation dialog
const showRestoreDialog = ref(false)
const restoreTargetId = ref<string | null>(null)

const handleSave = async () => {
  isSaving.value = true
  try {
    await updateBackupConfig({
      enabled: enableAutoBackup.value,
      frequency: backupFrequency.value,
      retention_count: retentionCount.value,
      backup_directory: backupLocation.value,
      auto_delete: autoDelete.value,
    })
    
    saveSuccess.value = true
    setTimeout(() => {
      saveSuccess.value = false
    }, 3000)
    isEditing.value = false
    
    // 重新加载配置和状态
    await loadData()
  } catch (error) {
    console.error('Failed to save backup settings:', error)
    alert('保存失败: ' + (error instanceof Error ? error.message : String(error)))
  } finally {
    isSaving.value = false
  }
}

const resetDefaults = () => {
  enableAutoBackup.value = false
  backupFrequency.value = 'daily'
  retentionCount.value = 10
  autoDelete.value = true
  backupLocation.value = '~/.local-ai/backups/'
  isEditing.value = true
}

const handleCreateBackup = async () => {
  try {
    loading.value = true
    const result = await createBackup()
    
    if (result.success) {
      // 重新加载备份历史
      await loadBackupHistory()
      alert('备份创建成功')
    } else {
      alert('备份创建失败')
    }
  } catch (error) {
    console.error('Failed to create backup:', error)
    alert('备份创建失败: ' + (error instanceof Error ? error.message : String(error)))
  } finally {
    loading.value = false
  }
}

const handleRestore = (backupId: string) => {
  restoreTargetId.value = backupId
  showRestoreDialog.value = true
}

const confirmRestore = async () => {
  if (!restoreTargetId.value) return
  
  try {
    loading.value = true
    const result = await restoreBackup(restoreTargetId.value)
    
    if (result.success) {
      alert('备份恢复成功，页面将刷新')
      // 刷新页面以反映恢复后的状态
      window.location.reload()
    } else {
      alert('备份恢复失败: ' + (result.status || 'Unknown error'))
    }
    
    showRestoreDialog.value = false
    restoreTargetId.value = null
  } catch (error) {
    console.error('Failed to restore backup:', error)
    alert('备份恢复失败: ' + (error instanceof Error ? error.message : String(error)))
  } finally {
    loading.value = false
  }
}

const handleDeleteBackup = async (backupId: string) => {
  if (!confirm('确定要删除此备份吗？此操作无法撤销。')) {
    return
  }
  
  try {
    loading.value = true
    const result = await deleteBackup(backupId)
    
    if (result.success) {
      // 重新加载备份历史
      await loadBackupHistory()
    } else {
      alert('删除备份失败')
    }
  } catch (error) {
    console.error('Failed to delete backup:', error)
    alert('删除备份失败: ' + (error instanceof Error ? error.message : String(error)))
  } finally {
    loading.value = false
  }
}

const handleBrowseLocation = async () => {
  try {
    const result = await browseBackupDirectory()
    if (result.path) {
      backupLocation.value = result.path
      isEditing.value = true
    }
  } catch (error) {
    console.error('Failed to browse directory:', error)
    alert('浏览目录失败: ' + (error instanceof Error ? error.message : String(error)))
  }
}

const getStatusColor = (status: string) => {
  switch (status) {
    case 'success':
      return 'bg-green-500/20 text-green-400 border-green-500/30'
    case 'failed':
      return 'bg-red-500/20 text-red-400 border-red-500/30'
    case 'in_progress':
      return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
    default:
      return 'bg-muted/20 text-muted-foreground border-border/30'
  }
}

const getTypeLabel = (type: string) => {
  return type === 'auto' ? t('settings.backup.type_auto') : t('settings.backup.type_manual')
}

const getStatusLabel = (status: string) => {
  switch (status) {
    case 'success':
      return t('settings.backup.status_success')
    case 'failed':
      return t('settings.backup.status_failed')
    case 'in_progress':
      return t('settings.backup.status_in_progress')
    default:
      return status
  }
}

const loadData = async () => {
  try {
    loading.value = true
    
    // 加载数据库状态
    const status = await getDatabaseStatus()
    dbPath.value = status.path
    dbSize.value = status.size
    dbType.value = status.type === 'SQLite' ? DatabaseType.SQLITE : DatabaseType.SQLITE
    lastBackupTime.value = status.last_backup_time
    backupStatus.value = status.backup_status
    
    // 加载备份配置
    const config = await getBackupConfig()
    enableAutoBackup.value = config.enabled
    backupFrequency.value = config.frequency as 'on_start' | 'daily' | 'weekly' | 'custom'
    retentionCount.value = config.retention_count
    autoDelete.value = config.auto_delete
    backupLocation.value = config.backup_directory
    
    // 加载备份历史
    await loadBackupHistory()
  } catch (error) {
    console.error('Failed to load backup data:', error)
  } finally {
    loading.value = false
  }
}

const loadBackupHistory = async () => {
  try {
    const backups = await listBackups()
    backupHistory.value = backups.map(b => ({
      ...b,
      date: new Date(b.date).toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }),
    }))
  } catch (error) {
    console.error('Failed to load backup history:', error)
  }
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <!-- Header -->
    <header class="pt-10 pb-6 px-10 flex items-start justify-between shrink-0">
      <div class="space-y-2">
        <h1 class="text-4xl font-bold tracking-tight">{{ t('settings.backup.title') }}</h1>
        <p class="text-muted-foreground text-lg">{{ t('settings.backup.subtitle') }}</p>
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
          
          <!-- 1️⃣ Database Status Card -->
          <section class="space-y-4">
            <h2 class="text-xl font-bold">{{ t('settings.backup.database_status') }}</h2>
            <div class="p-8 rounded-2xl bg-card border border-border shadow-sm">
              <div class="grid grid-cols-2 gap-6">
                <div class="space-y-1">
                  <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('settings.backup.db_type') }}</p>
                  <p class="text-lg font-medium">{{ dbType === DatabaseType.SQLITE ? 'SQLite' : (dbType === DatabaseType.POSTGRESQL ? 'PostgreSQL' : 'MySQL') }}</p>
                </div>
                <div class="space-y-1">
                  <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('settings.backup.db_size') }}</p>
                  <p class="text-lg font-medium">{{ dbSize }}</p>
                </div>
                <div class="space-y-1 col-span-2">
                  <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('settings.backup.db_path') }}</p>
                  <p class="text-sm font-mono text-muted-foreground break-all">{{ dbPath }}</p>
                </div>
                <div class="space-y-1">
                  <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('settings.backup.last_backup') }}</p>
                  <p class="text-lg font-medium">{{ lastBackupTime || t('settings.backup.never') }}</p>
                </div>
                <div class="space-y-1">
                  <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('settings.backup.backup_status') }}</p>
                  <div class="flex items-center gap-2">
                    <component 
                      :is="backupStatus === 'enabled' ? CheckCircle2 : XCircle" 
                      :class="[
                        'w-5 h-5',
                        backupStatus === 'enabled' ? 'text-green-500' : 'text-muted-foreground'
                      ]"
                    />
                    <p class="text-lg font-medium">
                      {{ backupStatus === 'enabled' ? t('settings.backup.status_enabled') : t('settings.backup.status_disabled') }}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 2️⃣ Backup Strategy Card -->
          <section class="space-y-4">
            <h2 class="text-xl font-bold">{{ t('settings.backup.strategy_title') }}</h2>
            <div class="p-8 rounded-2xl bg-card border border-border shadow-sm space-y-6">
              <!-- Enable Automatic Backup -->
              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <h3 class="text-lg font-semibold">{{ t('settings.backup.enable_auto') }}</h3>
                  <p class="text-sm text-muted-foreground">{{ t('settings.backup.enable_auto_desc') }}</p>
                </div>
                <Switch 
                  :checked="enableAutoBackup" 
                  @update:checked="(val) => { enableAutoBackup = val; isEditing = true }"
                />
              </div>

              <div class="border-t border-border pt-6 space-y-6">
                <!-- Backup Frequency -->
                <div class="space-y-3">
                  <label class="text-sm font-medium text-foreground">{{ t('settings.backup.frequency') }}</label>
                  <Select 
                    v-model="backupFrequency" 
                    @update:modelValue="isEditing = true"
                  >
                    <SelectTrigger class="h-12 bg-background border-border rounded-xl">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="on_start">{{ t('settings.backup.freq_on_start') }}</SelectItem>
                      <SelectItem value="daily">{{ t('settings.backup.freq_daily') }}</SelectItem>
                      <SelectItem value="weekly">{{ t('settings.backup.freq_weekly') }}</SelectItem>
                      <SelectItem value="custom">{{ t('settings.backup.freq_custom') }}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <!-- Retention Policy -->
                <div class="grid grid-cols-2 gap-6">
                  <div class="space-y-3">
                    <label class="text-sm font-medium text-foreground">{{ t('settings.backup.retention_title') }}</label>
                    <div class="flex items-center gap-3">
                      <span class="text-sm text-muted-foreground whitespace-nowrap">{{ t('settings.backup.keep_last') }}</span>
                      <Input 
                        v-model.number="retentionCount"
                        type="number"
                        min="1"
                        class="h-12 bg-background border-border rounded-xl"
                        @update:modelValue="isEditing = true"
                      />
                      <span class="text-sm text-muted-foreground whitespace-nowrap">{{ t('settings.backup.backups') }}</span>
                    </div>
                  </div>
                  <div class="space-y-3">
                    <label class="text-sm font-medium text-foreground">{{ t('settings.backup.auto_delete') }}</label>
                    <div class="flex items-center gap-3 pt-8">
                      <Switch 
                        :checked="autoDelete" 
                        @update:checked="(val) => { autoDelete = val; isEditing = true }"
                      />
                      <span class="text-sm text-muted-foreground">{{ t('settings.backup.auto_delete_desc') }}</span>
                    </div>
                  </div>
                </div>

                <!-- Backup Location -->
                <div class="space-y-3">
                  <label class="text-sm font-medium text-foreground">{{ t('settings.backup.location') }}</label>
                  <div class="flex gap-3">
                    <div class="relative flex-1">
                      <FolderOpen class="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                      <Input 
                        v-model="backupLocation"
                        placeholder="~/.local-ai/backups/"
                        class="pl-12 h-12 bg-background border-border text-foreground rounded-xl"
                        @update:modelValue="isEditing = true"
                      />
                    </div>
                    <Button 
                      variant="outline" 
                      class="h-12 px-6 rounded-xl font-medium"
                      @click="handleBrowseLocation"
                    >
                      {{ t('settings.backup.browse') }}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 3️⃣ Manual Operations Card -->
          <section class="space-y-4">
            <h2 class="text-xl font-bold">{{ t('settings.backup.manual_ops') }}</h2>
            <div class="p-8 rounded-2xl bg-card border border-border shadow-sm">
              <div class="flex items-center gap-4">
                <Button 
                  class="h-12 px-6 rounded-xl font-medium gap-2"
                  @click="handleCreateBackup"
                >
                  <Download class="w-4 h-4" />
                  {{ t('settings.backup.create_now') }}
                </Button>
                <Button 
                  variant="outline"
                  class="h-12 px-6 rounded-xl font-medium gap-2"
                  @click="handleRestore('')"
                >
                  <Upload class="w-4 h-4" />
                  {{ t('settings.backup.restore') }}
                </Button>
              </div>
            </div>
          </section>

          <!-- 4️⃣ Backup History Table -->
          <section class="space-y-4">
            <h2 class="text-xl font-bold">{{ t('settings.backup.history_title') }}</h2>
            <div class="rounded-2xl bg-card border border-border shadow-sm overflow-hidden">
              <div class="overflow-x-auto">
                <table class="w-full">
                  <thead class="bg-muted/30 border-b border-border">
                    <tr>
                      <th class="text-left px-6 py-4 text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                        {{ t('settings.backup.table_date') }}
                      </th>
                      <th class="text-left px-6 py-4 text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                        {{ t('settings.backup.table_size') }}
                      </th>
                      <th class="text-left px-6 py-4 text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                        {{ t('settings.backup.table_type') }}
                      </th>
                      <th class="text-left px-6 py-4 text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                        {{ t('settings.backup.table_status') }}
                      </th>
                      <th class="text-right px-6 py-4 text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                        {{ t('settings.backup.table_actions') }}
                      </th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-border">
                    <tr 
                      v-for="backup in backupHistory" 
                      :key="backup.id"
                      class="hover:bg-muted/20 transition-colors"
                    >
                      <td class="px-6 py-4 text-sm font-medium">
                        <div class="flex items-center gap-2">
                          <Clock class="w-4 h-4 text-muted-foreground" />
                          {{ backup.date }}
                        </div>
                      </td>
                      <td class="px-6 py-4 text-sm text-muted-foreground">
                        <div class="flex items-center gap-2">
                          <HardDrive class="w-4 h-4 text-muted-foreground" />
                          {{ backup.size }}
                        </div>
                      </td>
                      <td class="px-6 py-4">
                        <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-muted/20 text-muted-foreground border border-border/30">
                          {{ getTypeLabel(backup.type) }}
                        </span>
                      </td>
                      <td class="px-6 py-4">
                        <span 
                          :class="[
                            'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border',
                            getStatusColor(backup.status)
                          ]"
                        >
                          {{ getStatusLabel(backup.status) }}
                        </span>
                      </td>
                      <td class="px-6 py-4">
                        <div class="flex items-center justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            class="h-8 px-3 gap-2"
                            :disabled="backup.status === 'in_progress'"
                            @click="handleRestore(backup.id)"
                          >
                            <Upload class="w-3.5 h-3.5" />
                            {{ t('settings.backup.restore') }}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            class="h-8 px-3 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                            :disabled="backup.status === 'in_progress'"
                            @click="handleDeleteBackup(backup.id)"
                          >
                            <Trash2 class="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                    <tr v-if="backupHistory.length === 0">
                      <td colspan="5" class="px-6 py-12 text-center text-muted-foreground">
                        {{ t('settings.backup.no_history') }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <!-- Bottom Spacing -->
          <div class="h-24"></div>
        </div>
      </main>
    </div>

    <!-- Restore Confirmation Dialog -->
    <div 
      v-if="showRestoreDialog"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      @click.self="showRestoreDialog = false"
    >
      <div class="bg-card border border-border rounded-2xl p-6 max-w-md w-full mx-4 shadow-xl">
        <h3 class="text-xl font-bold mb-2">{{ t('settings.backup.restore_confirm_title') }}</h3>
        <p class="text-muted-foreground mb-6">{{ t('settings.backup.restore_confirm_desc') }}</p>
        <div class="flex items-center justify-end gap-3">
          <Button 
            variant="outline" 
            class="rounded-xl"
            @click="showRestoreDialog = false"
          >
            {{ t('settings.backup.cancel') }}
          </Button>
          <Button 
            class="bg-red-600 hover:bg-red-700 text-white rounded-xl"
            @click="confirmRestore"
          >
            {{ t('settings.backup.confirm_restore') }}
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
