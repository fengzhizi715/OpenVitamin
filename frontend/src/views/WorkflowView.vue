<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { 
  Plus, 
  Play, 
  Edit, 
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  Search,
  GitBranch
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { getWorkflowExecutionStatus, listWorkflows, listWorkflowExecutions, type WorkflowRecord } from '@/services/api'
import { normalizeExecutionStatus, statusBadgeClass, type WorkflowUiStatus } from '@/components/workflow/status'

const router = useRouter()
const { t } = useI18n()

interface Workflow {
  id: string
  name: string
  description: string
  status: WorkflowUiStatus
  latestVersion?: string
  lastRun?: string
  lastRunStatus?: WorkflowUiStatus
}

const workflows = ref<Workflow[]>([])

const searchQuery = ref('')
const loading = ref(false)
let refreshTimer: number | null = null

const filteredWorkflows = computed(() => {
  if (!searchQuery.value) return workflows.value
  const query = searchQuery.value.toLowerCase()
  return workflows.value.filter(w => 
    w.name.toLowerCase().includes(query) || 
    w.description.toLowerCase().includes(query)
  )
})

function createWorkflow() {
  router.push({ name: 'workflow-create' })
}

function editWorkflow(id: string) {
  router.push({ name: 'workflow-edit', params: { id } })
}

function runWorkflow(id: string) {
  router.push({ name: 'workflow-run', params: { id } })
}

function viewWorkflow(id: string) {
  router.push({ name: 'workflow-detail', params: { id } })
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'succeeded': return CheckCircle2
    case 'running': return Loader2
    case 'pending':
    case 'queued':
      return Clock
    case 'failed': return XCircle
    default: return Clock
  }
}

function getStatusClass(status: string) {
  return statusBadgeClass(status as WorkflowUiStatus)
}

function isActiveStatus(status: WorkflowUiStatus): boolean {
  return status === 'pending' || status === 'queued' || status === 'running'
}

function toRelativeTime(iso?: string): string {
  if (!iso) return ''
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return iso
  const delta = Math.max(0, Date.now() - ts)
  const mins = Math.floor(delta / 60000)
  if (mins < 1) return t('workflow.time_just_now')
  if (mins < 60) return t('workflow.time_min_ago', { count: mins })
  const hours = Math.floor(mins / 60)
  if (hours < 24) return t('workflow.time_hr_ago', { count: hours })
  const days = Math.floor(hours / 24)
  return t('workflow.time_day_ago', { count: days })
}

async function loadWorkflows() {
  loading.value = true
  try {
    const res = await listWorkflows({ limit: 100, offset: 0 })
    const records = (res.items || []) as WorkflowRecord[]
    const hydrated = await Promise.all(records.map(async (w) => {
      try {
        const ex = await listWorkflowExecutions(w.id, { limit: 1, offset: 0 })
        const latest = ex.items?.[0]
        let latestStatus = normalizeExecutionStatus(latest?.state)
        let latestCreatedAt = latest?.created_at
        if (latest?.execution_id && isActiveStatus(latestStatus)) {
          try {
            const live = await getWorkflowExecutionStatus(w.id, latest.execution_id)
            latestStatus = normalizeExecutionStatus(live.state)
            latestCreatedAt = live.started_at || live.finished_at || latestCreatedAt
          } catch {
            // ignore per-workflow status reconcile errors
          }
        }
        return {
          id: w.id,
          name: w.name,
          description: w.description || '',
          latestVersion: w.latest_version_id || undefined,
          status: latest ? latestStatus : 'idle',
          lastRun: latestCreatedAt ? toRelativeTime(latestCreatedAt) : undefined,
          lastRunStatus: latest ? latestStatus : undefined,
        } as Workflow
      } catch {
        return {
          id: w.id,
          name: w.name,
          description: w.description || '',
          latestVersion: w.latest_version_id || undefined,
          status: 'idle',
        } as Workflow
      }
    }))
    workflows.value = hydrated
  } finally {
    loading.value = false
  }
  scheduleRefresh()
}

function stopRefresh() {
  if (refreshTimer != null) {
    window.clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

function scheduleRefresh() {
  stopRefresh()
  const hasActive = workflows.value.some((w) => isActiveStatus(w.status))
  if (!hasActive) return
  refreshTimer = window.setTimeout(async () => {
    await loadWorkflows()
  }, 3000)
}

onMounted(() => {
  void loadWorkflows()
})

onUnmounted(() => {
  stopRefresh()
})
</script>

<template>
  <div class="flex flex-col h-full bg-background">
    <!-- Header -->
    <div class="flex items-center justify-between px-8 py-6 border-b border-border/50">
      <div class="flex items-center gap-4">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-purple-700 flex items-center justify-center shadow-lg shadow-purple-500/20">
          <GitBranch class="w-5 h-5 text-white" />
        </div>
        <div>
          <h1 class="text-2xl font-bold tracking-tight">{{ t('workflow.title') }}</h1>
          <p class="text-sm text-muted-foreground">{{ t('workflow.subtitle') }}</p>
        </div>
      </div>
      <Button 
        class="gap-2 bg-blue-600 hover:bg-blue-700 text-white"
        @click="createWorkflow"
      >
        <Plus class="w-4 h-4" />
        {{ t('workflow.create') }}
      </Button>
    </div>

    <!-- Search Bar -->
    <div class="px-8 py-4 border-b border-border/50">
      <div class="relative max-w-md">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input
          v-model="searchQuery"
          :placeholder="t('workflow.search_placeholder')"
          class="pl-10"
        />
      </div>
    </div>

    <!-- Workflow Grid -->
    <div class="flex-1 overflow-auto p-8">
      <div v-if="loading" class="mb-4 text-sm text-muted-foreground">{{ t('workflow.loading') }}</div>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <!-- Workflow Cards -->
        <Card 
          v-for="workflow in filteredWorkflows" 
          :key="workflow.id"
          class="group hover:shadow-lg transition-all duration-300 cursor-pointer border-border/50"
          @click="viewWorkflow(workflow.id)"
        >
          <CardHeader class="pb-3">
            <div class="flex items-start justify-between">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-purple-500/20 to-purple-700/20 flex items-center justify-center">
                  <GitBranch class="w-5 h-5 text-purple-500" />
                </div>
                <div>
                  <CardTitle class="text-base font-semibold">{{ workflow.name }}</CardTitle>
                  <Badge 
                    variant="secondary" 
                    :class="getStatusClass(workflow.status)"
                  >
                    <component :is="getStatusIcon(workflow.status)" class="w-3 h-3 mr-1" />
                    {{ workflow.status.toUpperCase() }}
                  </Badge>
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent class="pt-0">
            <CardDescription class="text-sm line-clamp-2 mb-4">
              {{ workflow.description }}
            </CardDescription>
            <div class="text-xs text-muted-foreground mb-3">
              {{ t('workflow.latest_version') }}: {{ workflow.latestVersion || '-' }}
            </div>
            
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2 text-xs text-muted-foreground">
                <Clock class="w-3.5 h-3.5" />
                <span v-if="workflow.lastRun">{{ t('workflow.last_run') }}: {{ workflow.lastRun }}</span>
                <span v-else>{{ t('workflow.never_run') }}</span>
              </div>
              
              <div class="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <Button 
                  variant="ghost" 
                  size="icon" 
                  class="h-8 w-8"
                  @click.stop="editWorkflow(workflow.id)"
                >
                  <Edit class="w-4 h-4" />
                </Button>
                <Button 
                  variant="ghost" 
                  size="icon" 
                  class="h-8 w-8 text-blue-600"
                  @click.stop="runWorkflow(workflow.id)"
                >
                  <Play class="w-4 h-4" />
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- Create New Card (Always show) -->
        <Card 
          class="group hover:shadow-lg transition-all duration-300 cursor-pointer border-dashed border-2 border-border/50 hover:border-purple-500/50"
          @click="createWorkflow"
        >
          <CardContent class="flex flex-col items-center justify-center h-full py-12">
            <div class="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4 group-hover:bg-purple-500/10 transition-colors">
              <Plus class="w-8 h-8 text-muted-foreground group-hover:text-purple-500 transition-colors" />
            </div>
            <h3 class="text-lg font-semibold mb-1">{{ t('workflow.new_pipeline') }}</h3>
            <p class="text-sm text-muted-foreground">{{ t('workflow.new_pipeline_desc') }}</p>
          </CardContent>
        </Card>
      </div>

      <!-- Empty State -->
      <div v-if="workflows.length === 0" class="mt-12 text-center">
        <div class="w-20 h-20 rounded-full bg-muted/50 flex items-center justify-center mx-auto mb-4">
          <GitBranch class="w-10 h-10 text-muted-foreground/50" />
        </div>
        <h3 class="text-lg font-semibold text-foreground mb-2">{{ t('workflow.empty_title') }}</h3>
        <p class="text-sm text-muted-foreground mb-6">{{ t('workflow.empty_desc') }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
