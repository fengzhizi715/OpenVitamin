<script setup lang="ts">
import { ref, computed, onMounted, onActivated, onDeactivated } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { 
  Bot, 
  Plus, 
  Search, 
  Code2, 
  FileText, 
  Cpu, 
  HardDrive, 
  Settings2, 
  Activity, 
  History, 
  AlertCircle,
  Terminal,
  FileCode,
  Globe,
  Database,
  SearchCode,
  Binary,
  Trash2
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { getSystemConfig, listAgents, listModels, getAgent, deleteAgent, type ModelInfo, type SystemConfig, type AgentDefinition } from '@/services/api'
import { useSystemMetrics } from '@/composables/useSystemMetrics'

// Loading State
const loading = ref(true)
const agents = ref<any[]>([])
const modelsIndex = ref<Record<string, ModelInfo>>({})
const searchQuery = ref('')
const selectedModelFamily = ref<string>('all')
const selectedStatus = ref<string>('all')
const selectedRag = ref<string>('all')
const selectedTool = ref<string>('all')


// Extract model family from model name or ID
const extractModelFamily = (modelName: string, modelId: string): string => {
  const combined = `${modelName} ${modelId}`.toLowerCase()
  
  // Common model families
  if (combined.includes('llama') || combined.includes('llama2') || combined.includes('llama3')) {
    return 'llama'
  }
  if (combined.includes('mistral')) {
    return 'mistral'
  }
  if (combined.includes('gpt') || combined.includes('openai')) {
    return 'gpt'
  }
  if (combined.includes('claude') || combined.includes('anthropic')) {
    return 'claude'
  }
  if (combined.includes('gemini') || combined.includes('google')) {
    return 'gemini'
  }
  if (combined.includes('qwen')) {
    return 'qwen'
  }
  if (combined.includes('deepseek')) {
    return 'deepseek'
  }
  if (combined.includes('kimi')) {
    return 'kimi'
  }
  
  return 'other'
}

// Get available model families from agents
const availableModelFamilies = computed(() => {
  const families = new Set<string>()
  agents.value.forEach(agent => {
    if (agent.model_family && agent.model_family !== 'other') {
      families.add(agent.model_family)
    }
  })
  return Array.from(families).sort()
})

// Helper function to get localized family name
const getFamilyLabel = (family: string) => {
  const key = `agents.filters.${family}`
  const translated = t(key)
  // If translation key doesn't exist, t() returns the key itself
  if (translated === key) {
    return family.charAt(0).toUpperCase() + family.slice(1)
  }
  return translated
}

// Helper function to get localized tool name (handles keys with dots like "file.read")
const getToolName = (toolId: string) => {
  if (!toolId) return toolId
  
  // For keys with dots like "file.read", vue-i18n interprets them as nested paths
  // So we need to access the messages object directly using bracket notation
  try {
    const currentLocale = i18n.locale.value
    const messages = (i18n as any).messages.value[currentLocale] || (i18n as any).messages.value.en
    const tools = messages?.agents?.tools
    // Access tool name using bracket notation to handle keys with dots
    if (tools && tools[toolId]) {
      return tools[toolId]
    }
  } catch (e) {
    // Fallback to t() function
  }
  
  // Try using t() function with the key
  const key = `agents.tools.${toolId}`
  const translated = t(key)
  
  // If translation returns the key path itself (meaning not found), use fallback
  if (translated === key || translated.includes('agents.tools')) {
    // Fallback: format tool ID nicely (e.g., "file.read" -> "File Read")
    return toolId.split('.').map(part => 
      part.charAt(0).toUpperCase() + part.slice(1)
    ).join(' ')
  }
  
  return translated
}

const fetchAgents = async (showLoading = true) => {
  try {
    if (showLoading) loading.value = true
    const [agentsRes, modelsRes] = await Promise.all([
      listAgents(),
      listModels(),
    ])

    const nextIndex: Record<string, ModelInfo> = {}
    for (const m of (modelsRes.data || [])) nextIndex[m.id] = m
    modelsIndex.value = nextIndex

    const res = agentsRes
    console.log('[AgentsManagementView] Fetched agents:', res)
    // Map backend AgentDefinition to UI-friendly objects
    // Handle case where res.data might be undefined or null
    const agentsList = res?.data || []
    console.log('[AgentsManagementView] Agents list:', agentsList)
    agents.value = agentsList.map((agent: any) => {
      const modelInfo = modelsIndex.value[agent.model_id]
      const runtimeBackend = modelInfo?.backend || null
      const modelName = modelInfo?.name || agent.model_id || ''
      const modelFamily = extractModelFamily(modelName, agent.model_id)
      // v1.5: prefer enabled_skills; fallback to tool_ids as builtin_<id>
      const effectiveSkills: string[] = (agent.enabled_skills && agent.enabled_skills.length > 0)
        ? agent.enabled_skills
        : (agent.tool_ids || []).map((t: string) => `builtin_${t}`)
      const hasWeb = effectiveSkills.some((id: string) => id.includes('web') || id === 'builtin_web.search')
      const hasPython = effectiveSkills.some((id: string) => id.includes('python') || id === 'builtin_python.run')
      // Display list: builtin_* -> tool name, else skill id (for badges & filter)
      const tools = effectiveSkills.map((s: string) => s.startsWith('builtin_') ? s.slice(8) : s)
      return ({
      id: agent.agent_id,
      name: agent.name,
      description: agent.description || '',
      status: 'READY', // Default status
      model: agent.model_id,
      model_family: modelFamily,
      runtime_backend: runtimeBackend,
      runtime_label: runtimeLabelForBackend(runtimeBackend),
      rag_count: agent.rag_ids?.length || 0,
      tools,
      icon: hasWeb ? Globe : (hasPython ? Code2 : Bot),
      color: hasWeb ? 'blue' : (hasPython ? 'orange' : 'indigo')
      })
    })
    console.log('[AgentsManagementView] Mapped agents:', agents.value)
  } catch (error) {
    console.error('[AgentsManagementView] Failed to fetch agents:', error)
    agents.value = []
  } finally {
    if (showLoading) loading.value = false
    console.log('[AgentsManagementView] Loading state:', loading.value, 'Agents count:', agents.value.length)
  }
}

const { metrics } = useSystemMetrics()
const systemConfig = ref<SystemConfig | null>(null)
const wasDeactivated = ref(false)

// Format last heartbeat time
const lastHeartbeat = computed(() => {
  // Use current time as last heartbeat timestamp
  const now = new Date()
  return now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC'
})

onMounted(async () => {
  await fetchAgents()
  try {
    const configData = await getSystemConfig()
    systemConfig.value = configData
  } catch (error) {
    console.error('[AgentsManagementView] Failed to fetch system data:', error)
  }
})

onDeactivated(() => { wasDeactivated.value = true })

// 从创建/编辑页返回时静默刷新列表，保证新数据可见
onActivated(() => {
  if (wasDeactivated.value) {
    wasDeactivated.value = false
    fetchAgents(false)
  }
})

const getStatusColor = (status: string) => {
  switch (status) {
    case 'RUNNING': return 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
    case 'READY': return 'bg-blue-500/10 text-blue-500 border-blue-500/20'
    case 'ERROR': return 'bg-rose-500/10 text-rose-500 border-rose-500/20'
    default: return 'bg-muted text-muted-foreground'
  }
}

const getAgentIconBg = (color: string) => {
  const mapping: Record<string, string> = {
    blue: 'bg-blue-500/10 text-blue-500',
    indigo: 'bg-indigo-500/10 text-indigo-500',
    rose: 'bg-rose-500/10 text-rose-500',
    violet: 'bg-violet-500/10 text-violet-500',
    orange: 'bg-orange-500/10 text-orange-500',
    fuchsia: 'bg-fuchsia-500/10 text-fuchsia-500'
  }
  return mapping[color] || 'bg-muted text-foreground'
}

const router = useRouter()
const i18n = useI18n()
const { t } = i18n

const runtimeLabelForBackend = (backend?: string | null) => {
  const b = (backend || '').toLowerCase()
  const mapping: Record<string, string> = {
    ollama: t('agents.execution.runtime_ollama'),
    lmstudio: t('agents.execution.runtime_lmstudio'),
    local: t('agents.execution.runtime_local'),
    openai: t('agents.execution.runtime_openai'),
    gemini: t('agents.execution.runtime_gemini'),
    deepseek: t('agents.execution.runtime_deepseek'),
    kimi: t('agents.execution.runtime_kimi'),
    mock: t('agents.execution.runtime_mock'),
  }
  return mapping[b] || (backend ? backend : t('agents.unknown'))
}

// Filtered agents based on search query and filters
const filteredAgents = computed(() => {
  let result = agents.value
  
  // Filter by model family
  if (selectedModelFamily.value !== 'all') {
    result = result.filter(agent => agent.model_family === selectedModelFamily.value)
  }
  
  // Filter by status
  if (selectedStatus.value !== 'all') {
    result = result.filter(agent => agent.status?.toLowerCase() === selectedStatus.value.toLowerCase())
  }
  
  // Filter by RAG
  if (selectedRag.value === 'enabled') {
    result = result.filter(agent => agent.rag_count > 0)
  } else if (selectedRag.value === 'disabled') {
    result = result.filter(agent => agent.rag_count === 0)
  }
  
  // Filter by tool
  if (selectedTool.value !== 'all') {
    result = result.filter(agent => agent.tools?.includes(selectedTool.value))
  }
  
  // Filter by search query
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase().trim()
    result = result.filter(agent => {
      // Search in name
      if (agent.name?.toLowerCase().includes(query)) return true
      // Search in description
      if (agent.description?.toLowerCase().includes(query)) return true
      // Search in model ID
      if (agent.model?.toLowerCase().includes(query)) return true
      // Search in runtime label
      if (agent.runtime_label?.toLowerCase().includes(query)) return true
      // Search in tool names
      if (agent.tools?.some((tool: string) => tool.toLowerCase().includes(query))) return true
      return false
    })
  }
  
  return result
})

const handleCreateAgent = () => {
  router.push('/agents/create')
}

const handleRunAgent = (agentId: string) => {
  router.push(`/agents/${agentId}/run`)
}

const handleEditAgent = (agentId: string) => {
  router.push(`/agents/${agentId}/edit`)
}

const deletingId = ref<string | null>(null)
const handleDeleteAgent = async (agentId: string, agentName: string) => {
  if (!window.confirm(t('agents.delete_confirm', { name: agentName }))) {
    return
  }
  deletingId.value = agentId
  try {
    await deleteAgent(agentId)
    agents.value = agents.value.filter((a) => a.id !== agentId)
  } catch (error) {
    console.error('Failed to delete agent:', error)
    alert(error instanceof Error ? error.message : t('agents.delete_failed'))
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <!-- Header -->
    <header class="pt-8 pb-6 px-8 flex items-start justify-between shrink-0 border-b border-border">
      <div class="space-y-1">
        <h1 class="text-3xl font-bold tracking-tight text-foreground">{{ t('agents.title') }}</h1>
        <p class="text-muted-foreground/80">{{ t('agents.subtitle') }}</p>
      </div>
      <div class="flex items-center gap-4">
        <div class="relative w-80">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input 
            v-model="searchQuery"
            :placeholder="t('agents.search_placeholder')" 
            class="pl-10 h-10 bg-muted border-border focus:border-blue-500/50 transition-all rounded-lg text-sm"
          />
        </div>
        <Button @click="handleCreateAgent" class="bg-blue-600 hover:bg-blue-700 text-white font-bold h-10 px-4 gap-2 rounded-lg shadow-lg shadow-blue-500/20">
          <Plus class="w-4 h-4" />
          {{ t('agents.create_button') }}
        </Button>
      </div>
    </header>

    <!-- Filters -->
    <div v-if="!loading && agents.length > 0" class="px-8 pb-6 flex items-center gap-3 shrink-0 border-b border-border">
      <Select v-model="selectedModelFamily">
        <SelectTrigger class="w-[160px] h-9 bg-muted border-border rounded-md text-xs">
          <span class="text-muted-foreground mr-1">{{ t('agents.filters.model_family') }}:</span>
          <SelectValue :placeholder="t('agents.filters.all')" />
        </SelectTrigger>
        <SelectContent class="bg-card border-border">
          <SelectItem value="all">{{ t('agents.filters.all') }}</SelectItem>
          <SelectItem 
            v-for="family in availableModelFamilies" 
            :key="family" 
            :value="family"
          >
            {{ getFamilyLabel(family) }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="selectedStatus">
        <SelectTrigger class="w-[130px] h-9 bg-muted border-border rounded-md text-xs">
          <span class="text-muted-foreground mr-1">{{ t('agents.filters.status') }}:</span>
          <SelectValue :placeholder="t('agents.filters.all')" />
        </SelectTrigger>
        <SelectContent class="bg-card border-border">
          <SelectItem value="all">{{ t('agents.filters.all') }}</SelectItem>
          <SelectItem value="running">{{ t('agents.filters.running') }}</SelectItem>
          <SelectItem value="ready">{{ t('agents.filters.ready') }}</SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="selectedRag">
        <SelectTrigger class="w-[140px] h-9 bg-muted border-border rounded-md text-xs">
          <span class="text-muted-foreground mr-1">{{ t('agents.filters.rag') }}:</span>
          <SelectValue :placeholder="t('agents.filters.all')" />
        </SelectTrigger>
        <SelectContent class="bg-card border-border">
          <SelectItem value="all">{{ t('agents.filters.all') }}</SelectItem>
          <SelectItem value="enabled">{{ t('agents.filters.enabled') }}</SelectItem>
          <SelectItem value="disabled">{{ t('agents.filters.disabled') }}</SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="selectedTool">
        <SelectTrigger class="w-[120px] h-9 bg-muted border-border rounded-md text-xs">
          <span class="text-muted-foreground mr-1">{{ t('agents.filters.tools') }}:</span>
          <SelectValue :placeholder="t('agents.filters.all')" />
        </SelectTrigger>
        <SelectContent class="bg-card border-border">
          <SelectItem value="all">{{ t('agents.filters.all') }}</SelectItem>
          <SelectItem value="terminal">{{ t('agents.filters.terminal') }}</SelectItem>
        </SelectContent>
      </Select>

      <button 
        @click="selectedModelFamily = 'all'; selectedStatus = 'all'; selectedRag = 'all'; selectedTool = 'all'; searchQuery = ''"
        class="text-xs font-medium text-muted-foreground/60 hover:text-foreground transition-colors ml-2"
      >
        {{ t('agents.filters.clear_all') }}
      </button>
    </div>

    <!-- Agent Grid -->
    <div v-if="!loading && filteredAgents.length > 0" class="flex-1 min-h-0 overflow-y-auto px-8 pb-8 custom-scrollbar">
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div 
          v-for="agent in filteredAgents" 
          :key="agent.id"
          class="bg-card border border-border rounded-2xl p-6 flex flex-col gap-5 hover:border-border transition-all group"
        >
          <!-- Card Header -->
          <div class="flex items-start justify-between">
            <div class="flex items-center gap-4">
              <div :class="['w-12 h-12 rounded-xl flex items-center justify-center shrink-0 shadow-inner cursor-pointer hover:scale-105 transition-transform', getAgentIconBg(agent.color)]" @click="handleRunAgent(agent.id)">
                <component :is="agent.icon" class="w-6 h-6" />
              </div>
              <div>
                <h3 class="text-xl font-bold text-foreground group-hover:text-blue-500 transition-colors cursor-pointer" @click="handleRunAgent(agent.id)">{{ agent.name }}</h3>
              </div>
            </div>
            <Badge :class="['px-2.5 py-0.5 rounded-full text-[10px] font-black tracking-widest border', getStatusColor(agent.status)]">
              {{ agent.status === 'RUNNING' ? t('agents.status.running') : (agent.status === 'READY' ? t('agents.status.ready') : t('agents.status.error')) }}
            </Badge>
          </div>

          <!-- Description -->
          <p class="text-muted-foreground/90 text-[13px] leading-relaxed line-clamp-2">
            {{ agent.description }}
          </p>

          <!-- Error Message (if any) -->
          <div v-if="agent.error" class="bg-rose-500/10 border border-rose-500/20 rounded-lg p-3 flex items-start gap-3">
            <AlertCircle class="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
            <p class="text-[11px] font-bold text-rose-500/90 leading-tight">{{ agent.error }}</p>
          </div>

          <!-- Meta Info -->
          <div class="space-y-3">
            <div class="flex items-center gap-3 text-[11px] text-muted-foreground/70 font-medium">
              <Binary class="w-3.5 h-3.5" />
              <span>{{ agent.model }} <span class="mx-1.5 opacity-30">•</span> {{ agent.runtime_label }}</span>
            </div>
            <div class="flex items-center gap-3 text-[11px] text-muted-foreground/70 font-medium">
              <Database class="w-3.5 h-3.5" />
              <span>{{ t('agents.card.rag') }}: <span class="text-muted-foreground">{{ agent.rag_count > 0 ? `${agent.rag_count} ${t('agents.card.sources')}` : t('agents.card.disabled') }}</span></span>
            </div>
          </div>

          <!-- Tools -->
          <div class="flex flex-wrap gap-2">
            <div 
              v-for="tool in agent.tools" 
              :key="tool"
              class="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-muted border border-border text-[10px] font-bold text-muted-foreground hover:bg-muted/80 hover:text-foreground transition-all cursor-default"
            >
              <Globe v-if="tool === 'web-search' || tool === 'web.search'" class="w-3 h-3" />
              <Code2 v-else-if="tool === 'python-interpreter' || tool === 'python.run'" class="w-3 h-3" />
              <Database v-else-if="tool === 'sql-engine' || tool === 'sql.query'" class="w-3 h-3" />
              <FileText v-else-if="tool === 'file.read' || tool === 'file.list' || tool === 'content-gen'" class="w-3 h-3" />
              <Terminal v-else-if="tool === 'terminal'" class="w-3 h-3" />
              <FileCode v-else-if="tool === 'fs-access'" class="w-3 h-3" />
              <SearchCode v-else-if="tool === 'audit' || tool === 'scanner'" class="w-3 h-3" />
              <Activity v-else-if="tool === 'metrics'" class="w-3 h-3" />
              {{ getToolName(tool) }}
            </div>
          </div>

          <!-- Card Footer -->
          <div class="mt-auto pt-4 border-t border-border flex items-center justify-between">
            <div class="flex items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                class="h-8 rounded-lg bg-muted border-border text-muted-foreground hover:text-foreground hover:bg-muted/80"
                @click="handleRunAgent(agent.id)"
              >
                {{ t('agents.card.run') }}
              </Button>
            </div>
            <div class="flex items-center gap-1">
              <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted" @click="handleRunAgent(agent.id)">
                <History v-if="agent.status === 'ERROR'" class="w-4 h-4" />
                <Activity v-else class="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted" @click="handleEditAgent(agent.id)" :title="t('agents.card.edit')">
                <Settings2 class="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-red-500 hover:bg-red-500/10" :title="t('agents.card.delete')" :disabled="deletingId === agent.id" @click.stop="handleDeleteAgent(agent.id, agent.name)">
                <Trash2 class="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- No Search Results -->
    <div v-if="!loading && agents.length > 0 && filteredAgents.length === 0" class="flex-1 min-h-0 flex flex-col items-center justify-center p-8 text-center">
      <div class="w-24 h-24 rounded-full bg-muted border border-border flex items-center justify-center mb-6 shadow-2xl">
        <Search class="w-12 h-12 text-blue-500/50" />
      </div>
      <h2 class="text-2xl font-bold text-foreground mb-2">{{ t('agents.search_no_results') }}</h2>
      <p class="text-muted-foreground/80 max-w-md mb-8 leading-relaxed">
        {{ t('agents.search_no_results_desc', { query: searchQuery }) }}
      </p>
      <Button @click="searchQuery = ''" variant="outline" class="border-border text-muted-foreground hover:text-foreground hover:bg-muted">
        {{ t('agents.search_clear') }}
      </Button>
    </div>

    <!-- Empty State -->
    <div v-if="!loading && agents.length === 0" class="flex-1 min-h-0 flex flex-col items-center justify-center p-8 text-center">
      <div class="w-24 h-24 rounded-full bg-muted border border-border flex items-center justify-center mb-6 shadow-2xl">
        <Bot class="w-12 h-12 text-blue-500/50" />
      </div>
      <h2 class="text-2xl font-bold text-foreground mb-2">{{ t('agents.empty_state.title') }}</h2>
      <p class="text-muted-foreground/80 max-w-md mb-8 leading-relaxed">
        {{ t('agents.empty_state.subtitle') }}
      </p>
      <Button @click="handleCreateAgent" class="bg-blue-600 hover:bg-blue-700 text-white font-bold h-12 px-8 gap-2 rounded-xl shadow-lg shadow-blue-500/20 transition-all hover:scale-105 active:scale-95">
        <Plus class="w-5 h-5" />
        {{ t('agents.empty_state.create_first') }}
      </Button>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="flex-1 min-h-0 flex items-center justify-center">
      <div class="flex flex-col items-center gap-4">
        <div class="w-10 h-10 border-2 border-blue-600/20 border-t-blue-600 rounded-full animate-spin"></div>
        <p class="text-xs font-black tracking-widest uppercase text-muted-foreground/60 animate-pulse">{{ t('agents.loading') }}</p>
      </div>
    </div>

    <!-- Page Footer (System Info) -->
    <footer class="h-12 border-t border-border bg-muted px-8 flex items-center justify-between shrink-0 text-[10px] font-bold tracking-tight uppercase">
      <div class="flex items-center gap-6">
        <div class="flex items-center gap-2">
          <div class="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]"></div>
          <span class="text-muted-foreground/60">{{ t('agents.footer.local_engine') }}: <span class="text-foreground ml-1">{{ systemConfig?.version || t('agents.not_available') }}</span></span>
        </div>
        <div class="flex items-center gap-2">
          <HardDrive class="w-3.5 h-3.5 text-muted-foreground/40" />
          <span class="text-muted-foreground/60">{{ t('agents.footer.vram_usage') }}: <span class="text-foreground ml-1">{{ t('agents.footer.gb_format', { n: metrics?.vram_used?.toFixed(1) || '0' }) }} / {{ t('agents.footer.gb_format', { n: metrics?.vram_total?.toFixed(1) || '0' }) }}</span></span>
        </div>
        <div class="flex items-center gap-2">
          <Cpu class="w-3.5 h-3.5 text-muted-foreground/40" />
          <span class="text-muted-foreground/60">{{ t('agents.footer.cpu_load') }}: <span class="text-foreground ml-1">{{ Math.round(metrics?.cpu_load || 0) }}%</span></span>
        </div>
      </div>
      <div class="text-muted-foreground/40">
        {{ t('agents.footer.last_heartbeat') }}: {{ lastHeartbeat }}
      </div>
    </footer>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 5px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.25);
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.1);
}
</style>
