<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLogs } from '@/composables/useLogs'
import { getSystemMetrics, type SystemMetrics } from '@/services/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { 
  Search, 
  Download, 
  Trash2, 
  Play, 
  Pause,
  RefreshCw,
  AlertCircle,
  FileText,
  Cpu,
  Activity
} from 'lucide-vue-next'

const { t } = useI18n()
const { logs, isStreaming, error, startStreaming, stopStreaming, clearLogs } = useLogs()

// Scroll area ref
const scrollAreaRef = ref<InstanceType<typeof ScrollArea> | null>(null)

// Filters
const searchQuery = ref('')
const levelFilter = ref<'all' | 'INFO' | 'DEBUG' | 'WARN' | 'ERRR'>('all')

// System metrics
const metrics = ref<SystemMetrics | null>(null)
const loadingMetrics = ref(false)

// Filtered logs
const filteredLogs = computed(() => {
  let result = logs.value

  // Level filter
  if (levelFilter.value !== 'all') {
    result = result.filter(log => log.level === levelFilter.value)
  }

  // Search filter
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(log => 
      log.message.toLowerCase().includes(query) ||
      log.tag.toLowerCase().includes(query) ||
      log.level.toLowerCase().includes(query)
    )
  }

  return result
})

// Load system metrics
const loadMetrics = async () => {
  try {
    loadingMetrics.value = true
    metrics.value = await getSystemMetrics()
  } catch (err) {
    console.error('Failed to load metrics:', err)
  } finally {
    loadingMetrics.value = false
  }
}

// Export logs
const exportLogs = (format: 'csv' | 'json') => {
  const data = filteredLogs.value.map(log => ({
    timestamp: log.timestamp,
    level: log.level,
    tag: log.tag,
    message: log.message
  }))

  let content = ''
  let filename = ''
  let mimeType = ''

  if (format === 'csv') {
    content = 'Timestamp,Level,Tag,Message\n'
    content += data.map(log => 
      `"${log.timestamp}","${log.level}","${log.tag}","${log.message.replace(/"/g, '""')}"`
    ).join('\n')
    filename = `logs-${new Date().toISOString().split('T')[0]}.csv`
    mimeType = 'text/csv'
  } else {
    content = JSON.stringify(data, null, 2)
    filename = `logs-${new Date().toISOString().split('T')[0]}.json`
    mimeType = 'application/json'
  }

  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// Format timestamp
const formatTimestamp = (timestamp: string) => {
  try {
    const date = new Date(timestamp)
    return date.toLocaleString()
  } catch {
    return timestamp
  }
}

// Get level badge color
const getLevelColor = (level: string) => {
  switch (level) {
    case 'ERRR':
      return 'bg-red-500/10 text-red-500 border-red-500/20'
    case 'WARN':
      return 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20'
    case 'INFO':
      return 'bg-blue-500/10 text-blue-500 border-blue-500/20'
    case 'DEBUG':
      return 'bg-gray-500/10 text-gray-500 border-gray-500/20'
    default:
      return 'bg-muted text-muted-foreground border-border'
  }
}

// Scroll to bottom function
const scrollToBottom = async () => {
  await nextTick()
  if (!scrollAreaRef.value) return
  
  // Get the root element of ScrollArea component
  const rootEl = (scrollAreaRef.value.$el || scrollAreaRef.value) as HTMLElement
  if (!rootEl) return
  
  // Find the scrollable viewport element
  // reka-ui ScrollAreaViewport typically has a data attribute
  let viewport: HTMLElement | null = null
  
  // Try to find viewport by data attribute (reka-ui convention)
  viewport = rootEl.querySelector('[data-reka-scroll-area-viewport]') as HTMLElement
  
  // Fallback: find scrollable element by checking overflow style
  if (!viewport) {
    const allElements = rootEl.querySelectorAll('*')
    for (const el of Array.from(allElements)) {
      const htmlEl = el as HTMLElement
      const style = window.getComputedStyle(htmlEl)
      if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && 
          htmlEl.scrollHeight > htmlEl.clientHeight) {
        viewport = htmlEl
        break
      }
    }
  }
  
  if (viewport) {
    // Add small delay to ensure DOM is fully rendered
    await new Promise(resolve => setTimeout(resolve, 50))
    viewport.scrollTo({
      top: viewport.scrollHeight,
      behavior: 'auto'
    })
  }
}

let metricsInterval: any = null

// Watch for new logs and auto-scroll to bottom
watch(filteredLogs, async () => {
  await scrollToBottom()
}, { deep: true })

onMounted(async () => {
  startStreaming()
  loadMetrics()
  // Refresh metrics every 5 seconds
  metricsInterval = setInterval(loadMetrics, 5000)
  // Scroll to bottom on mount
  await scrollToBottom()
})

onUnmounted(() => {
  stopStreaming()
  if (metricsInterval) {
    clearInterval(metricsInterval)
  }
})
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <!-- Header -->
    <header class="pt-10 pb-6 px-10 flex items-start justify-between shrink-0 border-b border-border/50">
      <div class="space-y-2">
        <h1 class="text-4xl font-bold tracking-tight">{{ t('logs.title') }}</h1>
        <p class="text-muted-foreground text-lg">{{ t('logs.empty_state.waiting') }}</p>
      </div>
      <div class="flex items-center gap-3 pt-2">
        <Button 
          variant="outline" 
          class="h-11 px-6 rounded-xl gap-2"
          @click="isStreaming ? stopStreaming() : startStreaming()"
        >
          <component :is="isStreaming ? Pause : Play" class="w-4 h-4" />
          {{ isStreaming ? t('logs.stream.pause') : t('logs.stream.resume') }}
        </Button>
        <Button 
          variant="outline" 
          class="h-11 px-6 rounded-xl gap-2"
          @click="exportLogs('csv')"
        >
          <Download class="w-4 h-4" />
          {{ t('logs.export.csv') }}
        </Button>
        <Button 
          variant="outline" 
          class="h-11 px-6 rounded-xl gap-2"
          @click="exportLogs('json')"
        >
          <Download class="w-4 h-4" />
          {{ t('logs.export.json') }}
        </Button>
        <Button 
          variant="outline" 
          class="h-11 px-6 rounded-xl gap-2"
          @click="clearLogs"
        >
          <Trash2 class="w-4 h-4" />
          {{ t('logs.clear') }}
        </Button>
      </div>
    </header>

    <div class="flex-1 flex overflow-hidden">
      <!-- Main Content -->
      <main class="flex-1 flex flex-col overflow-hidden px-10 pb-10 pt-6">
        <!-- Filters -->
        <div class="flex items-center gap-4 mb-6 shrink-0">
          <div class="relative flex-1 max-w-md">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input 
              v-model="searchQuery"
              :placeholder="t('logs.search_placeholder')"
              class="pl-10 h-11 rounded-xl"
            />
          </div>
          <div class="flex items-center gap-2">
            <Button
              v-for="level in ['all', 'INFO', 'WARN', 'ERRR', 'DEBUG'] as const"
              :key="level"
              variant="outline"
              size="sm"
              :class="[
                'rounded-lg',
                levelFilter === level ? 'bg-primary text-primary-foreground' : ''
              ]"
              @click="levelFilter = level"
            >
              {{ t(`logs.levels.${level === 'all' ? 'all' : level === 'ERRR' ? 'err' : level.toLowerCase()}`) }}
            </Button>
          </div>
        </div>

        <!-- Error State -->
        <div v-if="error" class="flex-1 flex items-center justify-center">
          <div class="text-center space-y-4">
            <AlertCircle class="w-16 h-16 text-red-500 mx-auto" />
            <h3 class="text-xl font-semibold">{{ t('logs.error_state.title') }}</h3>
            <p class="text-muted-foreground">{{ error }}</p>
            <Button @click="startStreaming()">
              <RefreshCw class="w-4 h-4 mr-2" />
              {{ t('logs.error_state.retry') }}
            </Button>
          </div>
        </div>

        <!-- Empty State -->
        <div v-else-if="filteredLogs.length === 0" class="flex-1 flex items-center justify-center">
          <div class="text-center space-y-4">
            <FileText class="w-16 h-16 text-muted-foreground mx-auto opacity-50" />
            <h3 class="text-xl font-semibold">{{ t('logs.empty_state.title') }}</h3>
            <p class="text-muted-foreground">
              {{ searchQuery || levelFilter !== 'all' ? t('logs.empty_state.no_match') : t('logs.empty_state.waiting') }}
            </p>
          </div>
        </div>

        <!-- Logs Table -->
        <ScrollArea ref="scrollAreaRef" v-else class="flex-1">
          <div class="space-y-1">
            <div
              v-for="log in filteredLogs"
              :key="log.id"
              class="flex items-start gap-4 p-4 rounded-lg hover:bg-muted/50 transition-colors border border-border/50"
            >
              <Badge :class="getLevelColor(log.level)" class="shrink-0">
                {{ log.level }}
              </Badge>
              <div class="flex-1 min-w-0 space-y-1">
                <div class="flex items-center gap-2 text-sm">
                  <span class="text-muted-foreground font-mono text-xs">{{ formatTimestamp(log.timestamp) }}</span>
                  <span class="text-muted-foreground">•</span>
                  <span class="text-muted-foreground font-medium">{{ log.tag }}</span>
                </div>
                <p class="text-sm text-foreground break-words">{{ log.message }}</p>
              </div>
            </div>
          </div>
        </ScrollArea>
      </main>

      <!-- Right Sidebar: Metrics -->
      <aside class="w-80 border-l border-border/50 bg-muted/5 p-6 space-y-6 overflow-auto shrink-0">
        <!-- Hardware Metrics -->
        <div>
          <h3 class="text-sm font-semibold mb-4 flex items-center gap-2">
            <Activity class="w-4 h-4" />
            {{ t('logs.metrics.title') }}
          </h3>
          <div class="space-y-4">
            <div v-if="metrics">
              <div class="flex justify-between items-center text-sm mb-1">
                <span class="text-muted-foreground">{{ t('logs.metrics.cpu') }}</span>
                <span class="font-medium">{{ metrics.cpu_load || 0 }}%</span>
              </div>
              <div class="h-2 bg-muted rounded-full overflow-hidden">
                <div 
                  class="h-full bg-blue-500 rounded-full transition-all"
                  :style="{ width: `${metrics.cpu_load || 0}%` }"
                ></div>
              </div>
            </div>
            <div v-if="metrics">
              <div class="flex justify-between items-center text-sm mb-1">
                <span class="text-muted-foreground">{{ t('logs.metrics.vram') }}</span>
                <span class="font-medium">{{ metrics.vram_used || 0 }}GB / {{ metrics.vram_total || 0 }}GB</span>
              </div>
              <div class="h-2 bg-muted rounded-full overflow-hidden">
                <div 
                  class="h-full bg-purple-500 rounded-full transition-all"
                  :style="{ width: `${((metrics.vram_used || 0) / (metrics.vram_total || 1)) * 100}%` }"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Environment Info -->
        <div>
          <h3 class="text-sm font-semibold mb-4 flex items-center gap-2">
            <Cpu class="w-4 h-4" />
            {{ t('logs.environment.title') }}
          </h3>
          <div class="space-y-2 text-sm">
            <div v-if="metrics" class="flex justify-between">
              <span class="text-muted-foreground">{{ t('logs.environment.node') }}</span>
              <span class="font-medium">{{ metrics.node_version || '-' }}</span>
            </div>
            <div v-if="metrics" class="flex justify-between">
              <span class="text-muted-foreground">{{ t('logs.environment.cuda') }}</span>
              <span class="font-medium">{{ metrics.cuda_version || '-' }}</span>
            </div>
            <div v-if="metrics" class="flex justify-between">
              <span class="text-muted-foreground">{{ t('logs.environment.workers') }}</span>
              <span class="font-medium">{{ metrics.active_workers || 0 }}</span>
            </div>
            <div v-if="metrics" class="flex justify-between">
              <span class="text-muted-foreground">{{ t('logs.environment.uptime') }}</span>
              <span class="font-medium">{{ metrics.uptime || '-' }}</span>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
/* Custom scrollbar */
:deep(.scroll-area-viewport) {
  scrollbar-width: thin;
  scrollbar-color: hsl(var(--border)) transparent;
}

:deep(.scroll-area-viewport)::-webkit-scrollbar {
  width: 6px;
}

:deep(.scroll-area-viewport)::-webkit-scrollbar-track {
  background: transparent;
}

:deep(.scroll-area-viewport)::-webkit-scrollbar-thumb {
  background: hsl(var(--border));
  border-radius: 10px;
}

:deep(.scroll-area-viewport)::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.3);
}
</style>
