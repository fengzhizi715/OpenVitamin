<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { 
  Settings,
  BarChart3, 
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Check,
  Zap,
  Database,
  Activity,
  Layers,
  Target
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { 
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

interface OptimizationStatus {
  enabled: boolean
  scheduler_policy: {
    name: string
    version: string
  }
  snapshot: {
    version: string
    node_count: number
    skill_count: number
  }
  config: Record<string, any>
}

interface ImpactReport {
  impact: {
    success_rate_before: number
    success_rate_after: number
    improvement_pct: number
    latency_before_ms: number
    latency_after_ms: number
    latency_reduction_pct: number
    node_count_before: number
    node_count_after: number
    skill_count_before: number
    skill_count_after: number
    version_before: string
    version_after: string
  }
  current_policy: string
  optimization_enabled: boolean
}

// State
const status = ref<OptimizationStatus | null>(null)
const impactReport = ref<ImpactReport | null>(null)
const isLoading = ref(false)
const isRebuilding = ref(false)
const error = ref<string | null>(null)

// Form state
const optimizationEnabled = ref(false)
const selectedPolicy = ref('default')

// Fetch status
const fetchStatus = async () => {
  try {
    const response = await fetch('/api/system/kernel/optimization')
    status.value = await response.json()
    optimizationEnabled.value = status.value?.enabled ?? false
    selectedPolicy.value = status.value?.config?.scheduler_policy ?? 'default'
  } catch (e) {
    console.error('Failed to fetch optimization status:', e)
    error.value = 'Failed to fetch optimization status'
  }
}

// Fetch impact report
const fetchImpactReport = async () => {
  try {
    const response = await fetch('/api/system/kernel/optimization/impact-report')
    impactReport.value = await response.json()
  } catch (e) {
    console.error('Failed to fetch impact report:', e)
  }
}

// Rebuild snapshot
const rebuildSnapshot = async () => {
  isRebuilding.value = true
  try {
    const response = await fetch('/api/system/kernel/optimization/rebuild-snapshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit_instances: 100 })
    })
    const result = await response.json()
    if (result.success) {
      await fetchStatus()
      await fetchImpactReport()
    } else {
      error.value = result.error || 'Failed to rebuild snapshot'
    }
  } catch (e) {
    console.error('Failed to rebuild snapshot:', e)
    error.value = 'Failed to rebuild snapshot'
  } finally {
    isRebuilding.value = false
  }
}

// Update config
const updateConfig = async () => {
  isLoading.value = true
  try {
    const response = await fetch('/api/system/kernel/optimization/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: optimizationEnabled.value,
        scheduler_policy: selectedPolicy.value,
        auto_build_snapshot: true,
        collect_statistics: true
      })
    })
    const result = await response.json()
    if (result.success) {
      await fetchStatus()
      await fetchImpactReport()
    } else {
      error.value = result.error || 'Failed to update config'
    }
  } catch (e) {
    console.error('Failed to update config:', e)
    error.value = 'Failed to update config'
  } finally {
    isLoading.value = false
  }
}

// Toggle optimization
const handleOptimizationToggle = async (val: boolean) => {
  optimizationEnabled.value = val
  await updateConfig()
}

// Policy change
const handlePolicyChange = async (policy: string) => {
  selectedPolicy.value = policy
  if (optimizationEnabled.value) {
    await updateConfig()
  }
}

let pollInterval: any = null

onMounted(async () => {
  await Promise.all([fetchStatus(), fetchImpactReport()])
  // Poll every 30 seconds
  pollInterval = setInterval(() => {
    fetchStatus()
    fetchImpactReport()
  }, 30000)
})

onUnmounted(() => {
  if (pollInterval) {
    clearInterval(pollInterval)
  }
})

// Computed properties for display
const improvementClass = computed(() => {
  const pct = impactReport.value?.impact?.improvement_pct ?? 0
  return pct >= 0 ? 'text-green-500' : 'text-red-500'
})

const latencyClass = computed(() => {
  const pct = impactReport.value?.impact?.latency_reduction_pct ?? 0
  return pct >= 0 ? 'text-green-500' : 'text-red-500'
})
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <!-- Header -->
    <header class="pt-10 pb-6 px-10 flex items-start justify-between shrink-0">
      <div class="space-y-2">
        <h1 class="text-4xl font-bold tracking-tight">Optimization Dashboard</h1>
        <p class="text-muted-foreground text-lg">V2.7 Optimization Layer Status & Analytics</p>
      </div>
      <div class="flex items-center gap-3 pt-2">
        <Button 
          variant="outline" 
          class="h-11 px-6 rounded-xl gap-2"
          :disabled="isRebuilding"
          @click="rebuildSnapshot"
        >
          <RefreshCw :class="['w-4 h-4', isRebuilding ? 'animate-spin' : '']" />
          Rebuild Snapshot
        </Button>
      </div>
    </header>

    <div class="flex-1 flex overflow-hidden px-10 pb-10 gap-8">
      <!-- Main Content -->
      <main class="flex-1 overflow-y-auto custom-scrollbar pr-4">
        <div class="space-y-10">
          
          <!-- Error Banner -->
          <div v-if="error" class="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-500">
            {{ error }}
            <Button variant="ghost" size="sm" class="ml-2" @click="error = null">Dismiss</Button>
          </div>

          <!-- Optimization Toggle Section -->
          <div class="space-y-4">
            <div class="flex items-center justify-between p-8 rounded-2xl bg-card border border-border shadow-sm">
              <div class="flex items-center gap-6">
                <div class="w-12 h-12 rounded-xl bg-muted flex items-center justify-center border border-border">
                  <Zap class="w-5 h-5 text-yellow-500" />
                </div>
                <div class="space-y-1">
                  <h3 class="text-xl font-bold">Optimization Layer</h3>
                  <p class="text-muted-foreground text-sm">Enable intelligent scheduling based on historical execution data</p>
                </div>
              </div>
              <Switch :checked="optimizationEnabled" @update:checked="handleOptimizationToggle" />
            </div>
          </div>

          <!-- Policy Selection -->
          <section class="space-y-4">
            <h2 class="text-xl font-bold">Scheduler Policy</h2>
            <div class="grid grid-cols-2 gap-4">
              <button 
                @click="handlePolicyChange('default')"
                :class="[
                  'flex items-center gap-4 p-6 rounded-2xl border transition-all text-left',
                  selectedPolicy === 'default' 
                    ? 'bg-accent border-blue-600 shadow-sm' 
                    : 'bg-card border-border hover:bg-accent/50 hover:border-border/80'
                ]"
              >
                <div :class="[
                  'w-12 h-12 rounded-xl flex items-center justify-center border transition-colors',
                  selectedPolicy === 'default' ? 'bg-blue-500/10 border-blue-500/20' : 'bg-muted border-border'
                ]">
                  <Layers :class="['w-6 h-6', selectedPolicy === 'default' ? 'text-blue-500' : 'text-muted-foreground']" />
                </div>
                <div>
                  <div class="font-bold text-lg" :class="selectedPolicy === 'default' ? 'text-foreground' : 'text-muted-foreground'">Default Policy</div>
                  <div class="text-xs text-muted-foreground">Topological order, deterministic scheduling</div>
                </div>
                <div v-if="selectedPolicy === 'default'" class="ml-auto">
                  <div class="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center">
                    <Check class="w-4 h-4 text-white" />
                  </div>
                </div>
              </button>

              <button 
                @click="handlePolicyChange('learned')"
                :class="[
                  'flex items-center gap-4 p-6 rounded-2xl border transition-all text-left',
                  selectedPolicy === 'learned' 
                    ? 'bg-accent border-blue-600 shadow-sm' 
                    : 'bg-card border-border hover:bg-accent/50 hover:border-border/80'
                ]"
              >
                <div :class="[
                  'w-12 h-12 rounded-xl flex items-center justify-center border transition-colors',
                  selectedPolicy === 'learned' ? 'bg-purple-500/10 border-purple-500/20' : 'bg-muted border-border'
                ]">
                  <Target :class="['w-6 h-6', selectedPolicy === 'learned' ? 'text-purple-500' : 'text-muted-foreground']" />
                </div>
                <div>
                  <div class="font-bold text-lg" :class="selectedPolicy === 'learned' ? 'text-foreground' : 'text-muted-foreground'">Learned Policy</div>
                  <div class="text-xs text-muted-foreground">Weight-based priority, optimization-driven</div>
                </div>
                <div v-if="selectedPolicy === 'learned'" class="ml-auto">
                  <div class="w-6 h-6 rounded-full bg-purple-500 flex items-center justify-center">
                    <Check class="w-4 h-4 text-white" />
                  </div>
                </div>
              </button>
            </div>
          </section>

          <!-- Impact Report -->
          <section v-if="impactReport" class="space-y-4">
            <h2 class="text-xl font-bold">Optimization Impact</h2>
            <div class="grid grid-cols-4 gap-4">
              <!-- Success Rate -->
              <div class="p-6 rounded-2xl bg-card border border-border shadow-sm">
                <div class="flex items-center gap-2 mb-3">
                  <TrendingUp class="w-4 h-4 text-green-500" />
                  <span class="text-xs font-bold text-muted-foreground uppercase tracking-wider">Success Rate</span>
                </div>
                <div class="space-y-1">
                  <p :class="['text-2xl font-bold', improvementClass]">
                    {{ (impactReport.impact?.success_rate_after * 100).toFixed(1) }}%
                  </p>
                  <p class="text-xs text-muted-foreground">
                    <span :class="improvementClass">
                      {{ impactReport.impact?.improvement_pct >= 0 ? '+' : '' }}
                      {{ impactReport.impact?.improvement_pct.toFixed(1) }}%
                    </span>
                    vs baseline
                  </p>
                </div>
              </div>

              <!-- Latency -->
              <div class="p-6 rounded-2xl bg-card border border-border shadow-sm">
                <div class="flex items-center gap-2 mb-3">
                  <TrendingDown class="w-4 h-4 text-green-500" />
                  <span class="text-xs font-bold text-muted-foreground uppercase tracking-wider">Avg Latency</span>
                </div>
                <div class="space-y-1">
                  <p :class="['text-2xl font-bold', latencyClass]">
                    {{ impactReport.impact?.latency_after_ms.toFixed(0) }}ms
                  </p>
                  <p class="text-xs text-muted-foreground">
                    <span :class="latencyClass">
                      {{ impactReport.impact?.latency_reduction_pct >= 0 ? '-' : '+' }}
                      {{ Math.abs(impactReport.impact?.latency_reduction_pct).toFixed(1) }}%
                    </span>
                    reduction
                  </p>
                </div>
              </div>

              <!-- Node Count -->
              <div class="p-6 rounded-2xl bg-card border border-border shadow-sm">
                <div class="flex items-center gap-2 mb-3">
                  <Activity class="w-4 h-4 text-blue-500" />
                  <span class="text-xs font-bold text-muted-foreground uppercase tracking-wider">Nodes</span>
                </div>
                <div class="space-y-1">
                  <p class="text-2xl font-bold text-foreground">
                    {{ impactReport.impact?.node_count_after }}
                  </p>
                  <p class="text-xs text-muted-foreground">
                    tracked nodes
                  </p>
                </div>
              </div>

              <!-- Skill Count -->
              <div class="p-6 rounded-2xl bg-card border border-border shadow-sm">
                <div class="flex items-center gap-2 mb-3">
                  <Database class="w-4 h-4 text-purple-500" />
                  <span class="text-xs font-bold text-muted-foreground uppercase tracking-wider">Skills</span>
                </div>
                <div class="space-y-1">
                  <p class="text-2xl font-bold text-foreground">
                    {{ impactReport.impact?.skill_count_after }}
                  </p>
                  <p class="text-xs text-muted-foreground">
                    tracked skills
                  </p>
                </div>
              </div>
            </div>
          </section>

          <!-- Bottom Spacing -->
          <div class="h-24"></div>
        </div>
      </main>

      <!-- Right Sidebar: Status -->
      <aside class="w-[400px] shrink-0 space-y-4">
        <div class="p-8 rounded-2xl bg-card border border-border shadow-sm space-y-8 h-fit">
          <div class="flex items-center gap-3">
            <BarChart3 class="w-5 h-5 text-blue-500" />
            <h2 class="text-xl font-bold">Status</h2>
          </div>

          <!-- Current Policy -->
          <div class="space-y-4 pt-6 border-t border-border">
            <div class="flex items-start gap-4">
              <div class="w-10 h-10 rounded-xl bg-muted flex items-center justify-center border border-border">
                <Settings class="w-5 h-5 text-muted-foreground" />
              </div>
              <div class="space-y-1">
                <p class="text-lg font-bold">{{ status?.scheduler_policy?.name || 'DefaultPolicy' }}</p>
                <p class="text-sm text-muted-foreground">Current Policy</p>
              </div>
            </div>

            <div class="space-y-2">
              <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">Policy Version</p>
              <p class="text-sm font-mono text-foreground break-all">
                {{ status?.scheduler_policy?.version || 'default_1.0.0' }}
              </p>
            </div>

            <div class="space-y-2">
              <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">Snapshot Version</p>
              <p class="text-sm font-mono text-foreground break-all">
                {{ status?.snapshot?.version || 'empty_00000000' }}
              </p>
            </div>
          </div>

          <!-- Snapshot Info -->
          <div class="space-y-4 pt-6 border-t border-border">
            <p class="text-xs font-bold text-muted-foreground uppercase tracking-wider">Snapshot Data</p>
            
            <div class="grid grid-cols-2 gap-4">
              <div class="space-y-1">
                <p class="text-xs text-muted-foreground">Node Weights</p>
                <p class="text-xl font-bold text-foreground">{{ status?.snapshot?.node_count ?? 0 }}</p>
              </div>
              <div class="space-y-1">
                <p class="text-xs text-muted-foreground">Skill Weights</p>
                <p class="text-xl font-bold text-foreground">{{ status?.snapshot?.skill_count ?? 0 }}</p>
              </div>
            </div>
          </div>

          <!-- Optimization Status -->
          <div class="flex items-center justify-between pt-4 border-t border-border">
            <div class="flex items-center gap-3">
              <div :class="[
                'w-8 h-8 rounded-lg flex items-center justify-center',
                status?.enabled ? 'bg-green-500/10' : 'bg-muted'
              ]">
                <Zap :class="['w-4 h-4', status?.enabled ? 'text-green-500' : 'text-muted-foreground']" />
              </div>
              <div>
                <p class="text-sm font-bold">Optimization</p>
                <p class="text-xs text-muted-foreground">
                  {{ status?.enabled ? 'Enabled' : 'Disabled' }}
                </p>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>
