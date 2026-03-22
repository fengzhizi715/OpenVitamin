<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { 
  ArrowLeft, 
  Box, 
  Plus, 
  Globe, 
  Code2, 
  Database, 
  FileText,
  Activity,
  Loader2,
  AlertCircle,
  Search,
  ChevronDown,
  ChevronUp,
  CheckSquare,
  Square,
  Clock,
  Wrench,
  Settings
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Slider } from '@/components/ui/slider'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select'
import { updateAgent, getAgent, listModels, listKnowledgeBases, listSkills, type CreateAgentRequest, type SkillRecord } from '@/services/api'

const route = useRoute()
const router = useRouter()
const agentId = route.params.id as string

// Form State
const agentName = ref('')
const agentSlug = ref('')
const agentDescription = ref('')
const selectedModel = ref<string>('')
const selectedKnowledgeBases = ref<string[]>([])
const selectedSkills = ref<string[]>([])
const defaultSystemPrompt = computed(() => t('agents.create.default_system_prompt'))
const systemPrompt = ref(defaultSystemPrompt.value)
const temperature = ref([0.7])
const maxSteps = ref(20)
const executionMode = ref('legacy')
const useExecutionKernel = ref<'inherit' | 'on' | 'off'>('inherit')
const responseMode = ref<'default' | 'direct_tool_result'>('default')

// RePlan 配置 (Plan-Based 模式)
const maxReplanCount = ref(3)
const onFailureStrategy = ref('stop')
const replanPrompt = ref('')
const planContractEnabled = ref(false)
const planContractStrict = ref(false)

// Intent Rules (通用配置：关键词/正则匹配 → Skill)
const intentRules = ref<{keywords: string[], skills: string[], regex?: string}[]>([])
const newIntentRule = ref({ keywords: '', skills: [] as string[], regex: '' })
// 运行时技能语义发现（model_params.use_skill_discovery）
const useSkillDiscovery = ref(false)


// Loading and data states
const loadingAgent = ref(true)
const loadingModels = ref(true)
const loadingKBs = ref(true)
const loadingSkills = ref(true)
const isSubmitting = ref(false)
const submitError = ref<string | null>(null)
const currentAgent = ref<any>(null)  // Store loaded agent data
const availableModels = ref<any[]>([])
const filteredModels = ref<any[]>([])
const availableKnowledgeBases = ref<any[]>([])
const skillsError = ref<string | null>(null)
const availableSkills = ref<SkillRecord[]>([])

// Skills search and filter
const skillSearchQuery = ref('')
const expandedCategories = ref<Set<string>>(new Set(['builtin_file', 'builtin_http', 'builtin_text', 'builtin_time', 'builtin_system']))

const iconComponentByName = (icon?: string | null) => {
  const mapping: Record<string, any> = {
    Globe,
    Code2,
    Database,
    FileText,
    Box,
  }
  return (icon && mapping[icon]) ? mapping[icon] : Box
}

const colorByCategory = (category?: string | null) => {
  const mapping: Record<string, string> = {
    web: 'blue',
    http: 'blue',
    python: 'orange',
    sql: 'violet',
    file: 'blue',
    text: 'green',
    time: 'purple',
    system: 'gray',
  }
  return (category && mapping[category]) ? mapping[category] : 'blue'
}

const skillIconKey = (s: SkillRecord) => {
  if (s.id.startsWith('builtin_')) {
    const name = s.id.replace('builtin_', '').split('.')[0]
    if (name === 'file') return FileText
    if (name === 'web') return Globe
    if (name === 'http') return Globe
    if (name === 'python') return Code2
    if (name === 'sql') return Database
    if (name === 'text') return FileText
    if (name === 'time') return Clock
    if (name === 'system') return Settings
  }
  return Box
}

// Group skills by category
const skillCategoryKey = (s: { id: string; category?: string }): string => {
  if (s.id.startsWith('builtin_')) {
    const name = s.id.replace('builtin_', '').split('.')[0]
    return `builtin_${name}`
  }
  return s.category || 'other'
}

const skillCategoryLabel = (category: string): string => {
  if (category.startsWith('builtin_')) {
    const name = category.replace('builtin_', '')
    const labels: Record<string, string> = {
      file: t('agents.create.skill_category_file'),
      http: t('agents.create.skill_category_http'),
      text: t('agents.create.skill_category_text'),
      time: t('agents.create.skill_category_time'),
      system: t('agents.create.skill_category_system'),
      web: t('agents.create.skill_category_web'),
      python: t('agents.create.skill_category_python'),
      sql: t('agents.create.skill_category_sql')
    }
    return labels[name] || name.charAt(0).toUpperCase() + name.slice(1)
  }
  return category || t('agents.create.skill_category_other')
}

const uiSkills = computed(() => {
  return availableSkills.value.map((s) => ({
    id: s.id,
    name: s.name,
    description: s.description || '',
    type: s.type,
    category: s.category || '',
    icon: skillIconKey(s),
    color: colorByCategory(s.id.startsWith('builtin_') ? s.id.replace('builtin_', '').split('.')[0] : (s.category || '')),
  }))
})

const groupedSkills = computed(() => {
  const groups: Record<string, typeof uiSkills.value> = {}
  const filtered = uiSkills.value.filter(s => {
    if (!skillSearchQuery.value.trim()) return true
    const q = skillSearchQuery.value.toLowerCase()
    return s.name.toLowerCase().includes(q) || 
           s.description.toLowerCase().includes(q) ||
           s.id.toLowerCase().includes(q)
  })
  
  filtered.forEach(skill => {
    const category = skillCategoryKey(skill)
    if (!groups[category]) {
      groups[category] = []
    }
    groups[category].push(skill)
  })
  
  return groups
})

const selectedSkillsCount = computed(() => selectedSkills.value.length)
const totalSkillsCount = computed(() => availableSkills.value.length)

const toggleCategory = (category: string) => {
  if (expandedCategories.value.has(category)) {
    expandedCategories.value.delete(category)
  } else {
    expandedCategories.value.add(category)
  }
}

const selectAllInCategory = (category: string) => {
  const skillsInCategory = groupedSkills.value[category] || []
  skillsInCategory.forEach(skill => {
    if (!selectedSkills.value.includes(skill.id)) {
      selectedSkills.value.push(skill.id)
    }
  })
}

const deselectAllInCategory = (category: string) => {
  const skillsInCategory = groupedSkills.value[category] || []
  skillsInCategory.forEach(skill => {
    const index = selectedSkills.value.indexOf(skill.id)
    if (index > -1) {
      selectedSkills.value.splice(index, 1)
    }
  })
}

const isCategoryAllSelected = (category: string): boolean => {
  const skillsInCategory = groupedSkills.value[category] || []
  return skillsInCategory.length > 0 && skillsInCategory.every(s => selectedSkills.value.includes(s.id))
}

const isCategoryPartiallySelected = (category: string): boolean => {
  const skillsInCategory = groupedSkills.value[category] || []
  const selectedInCategory = skillsInCategory.filter(s => selectedSkills.value.includes(s.id)).length
  return selectedInCategory > 0 && selectedInCategory < skillsInCategory.length
}

const tokenCount = computed(() => {
  return systemPrompt.value.split(/\s+/).length * 1.3
})

const isKBSelected = (kbId: string) => {
  return selectedKnowledgeBases.value.includes(kbId)
}

const toggleKB = (kbId: string) => {
  const index = selectedKnowledgeBases.value.indexOf(kbId)
  if (index > -1) {
    selectedKnowledgeBases.value.splice(index, 1)
  } else {
    selectedKnowledgeBases.value.push(kbId)
  }
}

const isSkillSelected = (skillId: string) => selectedSkills.value.includes(skillId)

const toggleSkill = (skillId: string) => {
  const index = selectedSkills.value.indexOf(skillId)
  if (index > -1) {
    selectedSkills.value.splice(index, 1)
  } else {
    selectedSkills.value.push(skillId)
  }
}

const getToolIconBg = (color: string) => {
  const mapping: Record<string, string> = {
    blue: 'bg-blue-500/10 text-blue-500',
    orange: 'bg-orange-500/10 text-orange-500',
    violet: 'bg-violet-500/10 text-violet-500',
    green: 'bg-green-500/10 text-green-500',
    purple: 'bg-purple-500/10 text-purple-500',
    gray: 'bg-gray-500/10 text-gray-500'
  }
  return mapping[color] || 'bg-muted text-foreground'
}

const normalizeIntentRules = (rules: any): {keywords: string[], skills: string[], regex?: string}[] => {
  if (!Array.isArray(rules)) return []
  return rules.map((r: any) => {
    const keywords = Array.isArray(r?.keywords)
      ? r.keywords.filter((k: any) => typeof k === 'string' && k.trim()).map((k: string) => k.trim())
      : (typeof r?.keywords === 'string'
          ? r.keywords.split(',').map((k: string) => k.trim()).filter((k: string) => k)
          : [])
    const skills = Array.isArray(r?.skills)
      ? r.skills.filter((s: any) => typeof s === 'string' && s.trim()).map((s: string) => s.trim())
      : []
    const regex = typeof r?.regex === 'string' && r.regex.trim() ? r.regex.trim() : undefined
    return { keywords, skills, regex }
  })
}

// Fetch agent data and populate form
const fetchAgentData = async () => {
  try {
    loadingAgent.value = true
    const agent = await getAgent(agentId)
    
    agentName.value = agent.name || ''
    agentSlug.value = agent.slug || ''
    agentDescription.value = agent.description || ''
    selectedModel.value = agent.model_id || ''
    // 若当前 model 不是 LLM/VLM，仍加入列表以便展示（用户可切换为有效模型）
    if (selectedModel.value && !filteredModels.value.some((m: { id: string }) => m.id === selectedModel.value)) {
      const m = availableModels.value.find((x: { id: string }) => x.id === selectedModel.value)
      if (m) filteredModels.value.push(m)
    }
    selectedKnowledgeBases.value = agent.rag_ids || []
    selectedSkills.value = (agent.enabled_skills && agent.enabled_skills.length > 0)
      ? agent.enabled_skills
      : (agent.tool_ids || []).map((t) => `builtin_${t}`)
    
    // Expand categories that contain selected skills
    if (selectedSkills.value.length > 0) {
      selectedSkills.value.forEach(skillId => {
        if (skillId.startsWith('builtin_')) {
          const category = `builtin_${skillId.replace('builtin_', '').split('.')[0]}`
          expandedCategories.value.add(category)
        } else {
          // For custom skills, expand their category if available
          const skill = availableSkills.value.find(s => s.id === skillId)
          if (skill?.category) {
            expandedCategories.value.add(skill.category)
          }
        }
      })
    }
    
    systemPrompt.value = agent.system_prompt || defaultSystemPrompt.value
    temperature.value = [agent.temperature ?? 0.7]
    maxSteps.value = agent.max_steps || 20
    executionMode.value = agent.execution_mode || 'legacy'
    useExecutionKernel.value = agent.use_execution_kernel === true
      ? 'on'
      : agent.use_execution_kernel === false
        ? 'off'
        : 'inherit'
    // RePlan 配置
    maxReplanCount.value = agent.max_replan_count ?? 3
    onFailureStrategy.value = agent.on_failure_strategy || 'stop'
    replanPrompt.value = agent.replan_prompt || ''
    planContractEnabled.value = agent.plan_contract_enabled ?? false
    planContractStrict.value = agent.plan_contract_strict ?? false
    // Intent Rules
    currentAgent.value = agent
    intentRules.value = normalizeIntentRules((agent.model_params || {}).intent_rules)
    useSkillDiscovery.value = (agent.model_params || {}).use_skill_discovery ?? false
    const modelParams = agent.model_params || {}
    const hasDirectResponseSkills = Array.isArray(modelParams.skill_direct_response_ids) && modelParams.skill_direct_response_ids.length > 0
    responseMode.value = modelParams.response_mode === 'direct_tool_result' || hasDirectResponseSkills
      ? 'direct_tool_result'
      : 'default'
  } catch (error) {
    console.error('Failed to fetch agent:', error)
    submitError.value = error instanceof Error ? error.message : 'Failed to load agent'
  } finally {
    loadingAgent.value = false
  }
}

// Fetch available models and knowledge bases
const fetchData = async () => {
  try {
    loadingModels.value = true
    const modelsRes = await listModels()
    availableModels.value = modelsRes.data || []
    
    // 仅保留 LLM 和 VLM（过滤 mock、embedding、asr、perception）
    const chatTypes = ['llm', 'vlm']
    filteredModels.value = availableModels.value.filter(model => {
      const isMock = model.name?.toLowerCase().includes('mock') || model.id?.toLowerCase().includes('mock')
      const mt = (model.model_type || '').toLowerCase()
      const isChatModel = !mt || chatTypes.includes(mt)
      return !isMock && isChatModel
    })
  } catch (error) {
    console.error('Failed to fetch models:', error)
  } finally {
    loadingModels.value = false
  }

  try {
    loadingKBs.value = true
    const kbsRes = await listKnowledgeBases()
    availableKnowledgeBases.value = kbsRes.data || []
  } catch (error) {
    console.error('Failed to fetch knowledge bases:', error)
  } finally {
    loadingKBs.value = false
  }

  try {
    loadingSkills.value = true
    const skillsRes = await listSkills()
    availableSkills.value = skillsRes.data || []
  } catch (error) {
    console.error('Failed to fetch skills:', error)
    skillsError.value = error instanceof Error ? error.message : t('agents.create.load_skills_failed')
  } finally {
    loadingSkills.value = false
  }
}

const handleUpdateAgent = async () => {
  if (!agentName.value.trim()) {
    submitError.value = t('agents.create.err_name_req')
    return
  }

  if (!selectedModel.value) {
    submitError.value = t('agents.create.err_model_req')
    return
  }

  isSubmitting.value = true
  submitError.value = null

  try {
    const data: CreateAgentRequest = {
      name: agentName.value.trim(),
      slug: agentSlug.value.trim() || undefined,
      description: agentDescription.value.trim(),
      model_id: selectedModel.value,
      system_prompt: systemPrompt.value.trim(),
      enabled_skills: selectedSkills.value,
      rag_ids: selectedKnowledgeBases.value,
      max_steps: maxSteps.value,
      temperature: temperature.value[0],
      execution_mode: executionMode.value,
      response_mode: responseMode.value,
      use_execution_kernel: executionMode.value === 'plan_based'
        ? (useExecutionKernel.value === 'inherit' ? null : useExecutionKernel.value === 'on')
        : null,
      // RePlan 配置
      max_replan_count: maxReplanCount.value,
      on_failure_strategy: onFailureStrategy.value,
      replan_prompt: replanPrompt.value,
      plan_contract_enabled: executionMode.value === 'plan_based' ? planContractEnabled.value : false,
      plan_contract_strict: executionMode.value === 'plan_based' ? planContractStrict.value : false,
      plan_contract_sources: executionMode.value === 'plan_based'
        ? ['replan_contract_plan', 'plan_contract', 'followup_plan_contract']
        : undefined,
      // Intent Rules + 语义发现（仅 plan_based 时生效）：深度合并，保留所有现有 model_params 字段
      model_params: {
        ...(currentAgent.value?.model_params || {}),
        intent_rules: normalizeIntentRules(intentRules.value).filter(r => ((r.keywords?.length || 0) > 0 || !!r.regex) && (r.skills?.length || 0) > 0),
        ...(executionMode.value === 'plan_based' ? { use_skill_discovery: useSkillDiscovery.value } : {})
      }
    }

    await updateAgent(agentId, data)
    router.push('/agents')
  } catch (error) {
    console.error('Failed to update agent:', error)
    submitError.value = error instanceof Error ? error.message : t('agents.create.update_failed')
  } finally {
    isSubmitting.value = false
  }
}

const handleCancel = () => {
  router.push('/agents')
}

onMounted(async () => {
  // Load skills first, then agent data (so we can expand categories based on selected skills)
  await fetchData()
  await fetchAgentData()
})
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <!-- Header -->
    <header class="pt-8 pb-6 px-8 flex items-start justify-between shrink-0 border-b border-border">
      <div class="space-y-1">
        <div class="flex items-center gap-4">
          <button @click="handleCancel" class="p-2 hover:bg-muted rounded-lg transition-colors">
            <ArrowLeft class="w-5 h-5 text-muted-foreground hover:text-foreground" />
          </button>
          <div>
            <h1 class="text-3xl font-bold tracking-tight text-foreground">{{ t('agents.create.title') }}</h1>
            <p class="text-muted-foreground/80 mt-1">{{ t('agents.create.subtitle') }}</p>
          </div>
        </div>
      </div>
    </header>

    <!-- Error Message -->
    <div v-if="submitError" class="mx-8 mt-6 bg-rose-500/10 border border-rose-500/20 rounded-lg p-4 flex items-start gap-3">
      <AlertCircle class="w-5 h-5 text-rose-500 shrink-0 mt-0.5" />
      <p class="text-sm font-bold text-rose-500/90">{{ submitError }}</p>
    </div>

    <!-- Main Content -->
    <div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
      <div class="max-w-4xl mx-auto px-8 py-8">
        <!-- Same form structure as CreateAgentView -->
        <!-- 01. Basic Information -->
        <section class="space-y-6 mb-12">
          <h2 class="text-sm font-black text-blue-500 tracking-widest uppercase flex items-center gap-2">
            <FileText class="w-4 h-4" />
            {{ t('agents.create.section_basic') }}
          </h2>
          <div class="space-y-4">
            <div>
              <label class="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2 block">{{ t('agents.create.name_label') }}</label>
              <Input 
                v-model="agentName"
                :placeholder="t('agents.create.name_placeholder')"
                class="h-12 bg-background border-border focus:border-blue-500/50 rounded-lg"
              />
            </div>
            <div>
              <label class="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2 block">{{ t('agents.create.slug_label') }}</label>
              <Input 
                v-model="agentSlug"
                :placeholder="t('agents.create.slug_placeholder')"
                class="h-12 bg-background border-border focus:border-blue-500/50 rounded-lg"
              />
            </div>
            <div>
              <label class="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2 block">{{ t('agents.create.desc_label') }}</label>
              <Textarea 
                v-model="agentDescription"
                :placeholder="t('agents.create.desc_placeholder')"
                class="min-h-24 bg-background border-border focus:border-blue-500/50 rounded-lg resize-none"
              />
            </div>
          </div>
        </section>

        <!-- 02. Model Selection -->
        <section class="space-y-6 mb-12">
          <h2 class="text-sm font-black text-blue-500 tracking-widest uppercase flex items-center gap-2">
            <Box class="w-4 h-4" />
            {{ t('agents.create.section_model') }}
          </h2>
          <div v-if="loadingModels" class="flex items-center justify-center py-12">
            <Loader2 class="w-6 h-6 animate-spin text-blue-500" />
          </div>
          <div v-else>
            <Select v-model="selectedModel">
              <SelectTrigger class="h-12 bg-background border-border focus:border-blue-500/50 rounded-lg">
                <SelectValue :placeholder="t('models.select_placeholder')" />
              </SelectTrigger>
              <SelectContent class="bg-card border-border max-h-80 overflow-y-auto">
                <SelectItem 
                  v-for="model in filteredModels" 
                  :key="model.id" 
                  :value="model.id"
                >
                  <div class="flex items-center gap-3">
                    <div class="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center shrink-0">
                      <Box class="w-4 h-4 text-blue-500" />
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="text-sm font-medium text-foreground truncate">
                        {{ model.display_name || model.name }}
                      </div>
                      <div class="text-xs text-muted-foreground/70">
                        {{ model.backend }}<span v-if="model.context_length"> • {{ model.context_length }} tokens</span>
                      </div>
                    </div>
                    <Badge v-if="model.status === 'active'" class="px-2 py-0.5 rounded-full text-[9px] font-black tracking-widest bg-emerald-500/10 text-emerald-500 border-emerald-500/20">
                      {{ model.status?.toUpperCase() }}
                    </Badge>
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </section>

        <!-- 03. Knowledge Bases (RAG) -->
        <section class="space-y-6 mb-12">
          <h2 class="text-sm font-black text-blue-500 tracking-widest uppercase flex items-center gap-2">
            <Database class="w-4 h-4" />
            {{ t('agents.create.section_kb') }}
          </h2>
          <div v-if="loadingKBs" class="flex items-center justify-center py-12">
            <Loader2 class="w-6 h-6 animate-spin text-blue-500" />
          </div>
          <div v-else class="flex flex-wrap gap-3">
            <button
              v-for="kb in availableKnowledgeBases"
              :key="kb.id"
              @click="toggleKB(kb.id)"
              :class="[
                'flex items-center gap-2 px-4 py-2 rounded-lg border transition-all',
                isKBSelected(kb.id)
                  ? 'bg-blue-500/20 border-blue-500/50 text-blue-400'
                  : 'bg-background border-border text-muted-foreground hover:border-border hover:text-foreground'
              ]"
            >
              <Database class="w-4 h-4" />
              <span class="text-sm font-medium">{{ kb.name }}</span>
            </button>
            <div v-if="availableKnowledgeBases.length === 0" class="text-sm text-muted-foreground">
              {{ t('agents.create.no_kbs') }}
            </div>
          </div>
        </section>

        <!-- 04. Skills (v1.5) -->
        <section class="space-y-6 mb-12">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-black text-blue-500 tracking-widest uppercase flex items-center gap-2">
              <Activity class="w-4 h-4" />
              {{ t('agents.create.section_skills') }}
            </h2>
            <div class="text-xs font-bold text-muted-foreground">
              {{ selectedSkillsCount }} / {{ totalSkillsCount }} {{ t('agents.create.skills_selected') }}
            </div>
          </div>
          <div v-if="loadingSkills" class="flex items-center justify-center py-12">
            <Loader2 class="w-6 h-6 animate-spin text-blue-500" />
          </div>
          <div v-else-if="skillsError" class="bg-rose-500/10 border border-rose-500/20 rounded-lg p-4 text-sm text-rose-500">
            {{ skillsError }}
          </div>
          <div v-else-if="availableSkills.length === 0" class="text-sm text-muted-foreground">
            {{ t('agents.create.no_skills') }}
          </div>
          <template v-else>
            <!-- Search Bar -->
            <div class="relative">
              <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
              <Input
                v-model="skillSearchQuery"
                :placeholder="t('agents.create.search_skills') || 'Search skills...'"
                class="pl-10 h-10 bg-background border-border focus:border-blue-500/50 rounded-lg"
              />
            </div>

            <!-- Grouped Skills -->
            <div class="space-y-3 max-h-[600px] overflow-y-auto custom-scrollbar">
              <div
                v-for="(skills, category) in groupedSkills"
                :key="category"
                class="space-y-2"
              >
                <!-- Category Header -->
                <div
                  @click="toggleCategory(category)"
                  class="flex items-center justify-between p-3 bg-muted/50 rounded-lg cursor-pointer hover:bg-muted transition-colors"
                >
                  <div class="flex items-center gap-3 flex-1">
                    <button
                      @click.stop="isCategoryAllSelected(category) ? deselectAllInCategory(category) : selectAllInCategory(category)"
                      class="p-1 hover:bg-background rounded transition-colors"
                    >
                      <CheckSquare
                        v-if="isCategoryAllSelected(category)"
                        class="w-4 h-4 text-blue-500"
                      />
                      <Square
                        v-else-if="isCategoryPartiallySelected(category)"
                        class="w-4 h-4 text-blue-500/50"
                      />
                      <Square
                        v-else
                        class="w-4 h-4 text-muted-foreground"
                      />
                    </button>
                    <span class="text-sm font-bold text-foreground">{{ skillCategoryLabel(category) }}</span>
                    <Badge variant="outline" class="text-[10px] px-2 py-0">
                      {{ skills.length }}
                    </Badge>
                  </div>
                  <component
                    :is="expandedCategories.has(category) ? ChevronUp : ChevronDown"
                    class="w-4 h-4 text-muted-foreground"
                  />
                </div>

                <!-- Skills in Category -->
                <div
                  v-if="expandedCategories.has(category)"
                  class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 pl-4"
                >
                  <div
                    v-for="skill in skills"
                    :key="skill.id"
                    @click="toggleSkill(skill.id)"
                    :class="[
                      'bg-background border rounded-xl p-4 cursor-pointer transition-all hover:shadow-md',
                      isSkillSelected(skill.id)
                        ? 'border-blue-500 shadow-[0_0_20px_rgba(59,130,246,0.15)]'
                        : 'border-border hover:border-blue-500/30'
                    ]"
                  >
                    <div class="flex items-start justify-between mb-3">
                      <div :class="['w-10 h-10 rounded-lg flex items-center justify-center shrink-0', getToolIconBg(skill.color)]">
                        <component :is="skill.icon" class="w-5 h-5" />
                      </div>
                      <div
                        v-if="isSkillSelected(skill.id)"
                        class="w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center shrink-0"
                      >
                        <svg class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
                        </svg>
                      </div>
                    </div>
                    <h3 class="text-sm font-bold text-foreground mb-1 line-clamp-1">{{ skill.name }}</h3>
                    <p class="text-xs text-muted-foreground/70 leading-relaxed line-clamp-2 mb-2">{{ skill.description }}</p>
                    <div class="flex items-center gap-2">
                      <Badge v-if="skill.type" variant="outline" class="text-[10px] px-1.5 py-0 font-mono">
                        {{ skill.type }}
                      </Badge>
                      <Badge v-if="skill.id.startsWith('builtin_')" variant="outline" class="text-[10px] px-1.5 py-0 text-blue-500 border-blue-500/30">
                        {{ t('agents.create.builtin_badge') }}
                      </Badge>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </section>

        <!-- 05. System Prompt -->
        <section class="space-y-6 mb-12">
          <h2 class="text-sm font-black text-blue-500 tracking-widest uppercase flex items-center gap-2">
            <FileText class="w-4 h-4" />
            {{ t('agents.create.section_prompt') }}
          </h2>
          <div class="space-y-3">
            <Textarea 
              v-model="systemPrompt"
              :placeholder="t('agents.create.default_system_prompt')"
              class="min-h-32 bg-background border-border focus:border-blue-500/50 rounded-lg resize-none font-mono text-sm"
            />
            <div class="flex items-center justify-between text-xs text-muted-foreground">
              <span>{{ t('agents.create.tokens', { n: Math.round(tokenCount) }) }}</span>
            </div>
          </div>
        </section>

        <!-- 06. Execution Settings -->
        <section class="space-y-6 mb-12">
          <h2 class="text-sm font-black text-blue-500 tracking-widest uppercase flex items-center gap-2">
            <Activity class="w-4 h-4" />
            {{ t('agents.create.section_exec') }}
          </h2>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div class="space-y-4">
              <label class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('agents.create.temp_label') }}</label>
              <Slider 
                v-model="temperature"
                :min="0"
                :max="2"
                :step="0.1"
                class="py-2"
              />
              <div class="flex justify-between text-[10px] font-bold text-muted-foreground/50 uppercase tracking-wider">
                <span>{{ t('agents.create.temp_precise') }}</span>
                <span>{{ t('agents.create.temp_balanced') }}</span>
                <span>{{ t('agents.create.temp_creative') }}</span>
              </div>
            </div>
            <div class="space-y-3">
              <label class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('agents.create.steps_label') }}</label>
              <Input 
                v-model="maxSteps"
                type="number"
                class="h-12 bg-background border-border focus:border-blue-500/50 rounded-lg text-2xl font-bold text-center"
              />
              <p class="text-[10px] text-muted-foreground/60 leading-tight">{{ t('agents.create.steps_desc') }}</p>
            </div>
          </div>
          <!-- Execution Mode -->
          <div class="pt-4 mt-4 border-t border-border">
            <label class="text-xs font-bold text-muted-foreground uppercase tracking-wider">{{ t('agents.create.execution_mode_label') }}</label>
            <div class="mt-2 flex gap-3">
              <button
                type="button"
                class="flex-1 p-3 rounded-lg border transition-all"
                :class="executionMode === 'legacy' ? 'border-blue-500 bg-blue-500/10' : 'border-border hover:border-muted-foreground/30'"
                @click="executionMode = 'legacy'"
              >
                <div class="text-xs font-semibold" :class="executionMode === 'legacy' ? 'text-blue-500' : 'text-foreground'">{{ t('agents.create.execution_mode_legacy') }}</div>
                <p class="text-[10px] text-muted-foreground/60 mt-1">{{ t('agents.create.execution_mode_legacy_desc') }}</p>
              </button>
              <button
                type="button"
                class="flex-1 p-3 rounded-lg border transition-all"
                :class="executionMode === 'plan_based' ? 'border-purple-500 bg-purple-500/10' : 'border-border hover:border-muted-foreground/30'"
                @click="executionMode = 'plan_based'"
              >
                <div class="text-xs font-semibold" :class="executionMode === 'plan_based' ? 'text-purple-500' : 'text-foreground'">{{ t('agents.create.execution_mode_plan_based') }}</div>
                <p class="text-[10px] text-muted-foreground/60 mt-1">{{ t('agents.create.execution_mode_plan_based_desc') }}</p>
              </button>
            </div>

            <!-- Kernel Override -->
            <div class="mt-4 space-y-2">
              <label class="text-xs text-muted-foreground">{{ t('agents.create.execution_kernel_override_label') }}</label>
              <select
                v-model="useExecutionKernel"
                :disabled="executionMode !== 'plan_based'"
                class="w-full px-3 py-2 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-2 focus:ring-purple-500/50 disabled:opacity-50"
              >
                <option value="inherit">{{ t('agents.create.follow_global') }}</option>
                <option value="on">{{ t('agents.create.force_on') }}</option>
                <option value="off">{{ t('agents.create.force_off') }}</option>
              </select>
              <p class="text-[10px] text-muted-foreground/60">
                {{ t('agents.create.execution_kernel_override_desc') }}
              </p>
            </div>

            <div class="mt-4 space-y-2">
              <label class="text-xs text-muted-foreground">{{ t('agents.create.response_mode_label') }}</label>
              <Select v-model="responseMode">
                <SelectTrigger class="w-full">
                  <SelectValue :placeholder="t('agents.create.response_mode_label')" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">{{ t('agents.create.response_mode_default') }}</SelectItem>
                  <SelectItem value="direct_tool_result">{{ t('agents.create.response_mode_direct') }}</SelectItem>
                </SelectContent>
              </Select>
              <p class="text-[10px] text-muted-foreground/60">
                {{ t('agents.create.response_mode_desc') }}
              </p>
            </div>

            <!-- RePlan Configuration (Plan-Based 模式) -->
            <div v-if="executionMode === 'plan_based'" class="mt-4 p-4 rounded-lg border border-purple-500/30 bg-purple-500/5 space-y-4">
              <div class="text-xs font-semibold text-purple-500 mb-3">{{ t('agents.create.replan_config') }}</div>

              <!-- Plan Contract -->
              <div class="space-y-3">
                <label class="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
                  <input
                    v-model="planContractEnabled"
                    type="checkbox"
                    class="h-4 w-4 rounded border-border bg-background text-purple-500 focus:ring-purple-500/50"
                  />
                  {{ t('agents.create.enable_plan_contract') }}
                </label>
                <label
                  class="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none"
                  :class="!planContractEnabled ? 'opacity-50' : ''"
                >
                  <input
                    v-model="planContractStrict"
                    type="checkbox"
                    :disabled="!planContractEnabled"
                    class="h-4 w-4 rounded border-border bg-background text-purple-500 focus:ring-purple-500/50 disabled:opacity-50"
                  />
                  {{ t('agents.create.plan_contract_strict') }}
                </label>
                <p class="text-[10px] text-muted-foreground/60">
                  {{ t('agents.create.plan_contract_sources') }}
                </p>
              </div>
              
              <!-- Max RePlan Count -->
              <div class="space-y-2">
                <label class="text-xs text-muted-foreground">{{ t('agents.create.max_replan_count') }}</label>
                <input
                  v-model.number="maxReplanCount"
                  type="number"
                  min="0"
                  max="10"
                  class="w-full px-3 py-2 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-2 focus:ring-purple-500/50"
                />
                <p class="text-[10px] text-muted-foreground/60">{{ t('agents.create.max_replan_count_desc') }}</p>
              </div>

              <!-- On Failure Strategy -->
              <div class="space-y-2">
                <label class="text-xs text-muted-foreground">{{ t('agents.create.on_failure_strategy') }}</label>
                <select
                  v-model="onFailureStrategy"
                  class="w-full px-3 py-2 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-2 focus:ring-purple-500/50"
                >
                  <option value="stop">{{ t('agents.create.failure_strategy_stop') }}</option>
                  <option value="continue">{{ t('agents.create.failure_strategy_continue') }}</option>
                  <option value="replan">{{ t('agents.create.failure_strategy_replan') }}</option>
                </select>
              </div>

              <!-- RePlan Prompt -->
              <div class="space-y-2">
                <label class="text-xs text-muted-foreground">{{ t('agents.create.replan_prompt_label') }}</label>
                <textarea
                  v-model="replanPrompt"
                  rows="3"
                  :placeholder="t('agents.create.replan_prompt_placeholder')"
                  class="w-full px-3 py-2 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-2 focus:ring-purple-500/50"
                ></textarea>
                <p class="text-[10px] text-muted-foreground/60">{{ t('agents.create.replan_prompt_desc') }}</p>
              </div>
            </div>

            <!-- Intent Rules Configuration (通用配置) -->
            <div 
              class="mt-4 p-4 rounded-lg border space-y-3"
              :class="executionMode === 'legacy' 
                ? 'border-blue-500/30 bg-blue-500/10' 
                : 'border-purple-500/30 bg-purple-500/10'"
            >
              <div 
                class="text-xs font-semibold mb-2"
                :class="executionMode === 'legacy' ? 'text-blue-500' : 'text-purple-500'"
              >
                {{ t('agents.create.intent_rules') }}
              </div>
              <!-- 运行时技能语义发现（仅 Plan-Based V2.4） -->
              <template v-if="executionMode === 'plan_based'">
                <label class="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
                  <input
                    v-model="useSkillDiscovery"
                    type="checkbox"
                    class="h-4 w-4 rounded border-border bg-background text-purple-500 focus:ring-2 focus:ring-purple-500/50"
                  />
                  <span>{{ t('agents.create.use_skill_discovery') }}</span>
                </label>
                <p class="text-[10px] text-muted-foreground/60 -mt-1">
                  {{ t('agents.create.use_skill_discovery_desc') }}
                </p>
              </template>
              <p class="text-[10px] text-muted-foreground/60">
                {{ t('agents.create.intent_rules_desc') }}
              </p>
              
              <!-- Existing Rules -->
              <div v-for="(rule, index) in intentRules" :key="index" class="flex items-center gap-2 p-2 rounded bg-background/50">
                <div class="flex-1 text-xs">
                  <span v-if="rule.regex" class="text-muted-foreground">{{ t('agents.create.regex_label') }}:</span>
                  <span v-else class="text-muted-foreground">{{ t('agents.create.keywords_label') }}:</span> 
                  <span class="font-mono">{{ rule.regex || rule.keywords.join(', ') }}</span>
                </div>
                <div class="flex-1 text-xs">
                  <span class="text-muted-foreground">{{ t('agents.create.skills_label') }}:</span> {{ rule.skills.join(', ') }}
                </div>
                <button
                  type="button"
                  @click="intentRules.splice(index, 1)"
                  class="text-red-500 hover:text-red-600"
                >
                  ✕
                </button>
              </div>

              <!-- Add New Rule -->
              <div class="space-y-2">
                <!-- Regex input -->
                <input
                  v-model="newIntentRule.regex"
                  :placeholder="t('agents.create.regex_placeholder')"
                  :class="[
                    'w-full px-3 py-2 text-xs rounded-lg border border-border bg-background font-mono focus:outline-none focus:ring-2',
                    executionMode === 'legacy' ? 'focus:ring-blue-500/50' : 'focus:ring-purple-500/50'
                  ]"
                />
                <p class="text-[10px] text-muted-foreground/60">{{ t('agents.create.regex_desc') }}</p>
                <!-- Keywords input -->
                <input
                  v-model="newIntentRule.keywords"
                  :placeholder="t('agents.create.keywords_placeholder')"
                  :class="[
                    'w-full px-3 py-2 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-2',
                    executionMode === 'legacy' ? 'focus:ring-blue-500/50' : 'focus:ring-purple-500/50'
                  ]"
                />
                <div class="flex gap-2">
                  <select
                    v-model="newIntentRule.skills"
                    multiple
                    :class="[
                      'flex-1 px-3 py-2 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-2',
                      executionMode === 'legacy' ? 'focus:ring-blue-500/50' : 'focus:ring-purple-500/50'
                    ]"
                  >
                    <option v-for="skill in availableSkills" :key="skill.id" :value="skill.id">
                      {{ skill.id }}
                    </option>
                  </select>
                  <button
                    type="button"
                    @click="if ((newIntentRule.keywords || newIntentRule.regex) && newIntentRule.skills.length) { intentRules.push({ keywords: newIntentRule.keywords.split(',').map(k => k.trim()).filter(k => k), skills: newIntentRule.skills, regex: newIntentRule.regex || undefined }); newIntentRule.keywords = ''; newIntentRule.skills = []; newIntentRule.regex = ''; }"
                    :disabled="(!newIntentRule.keywords && !newIntentRule.regex) || newIntentRule.skills.length === 0"
                    :class="[
                      'px-3 py-2 text-xs rounded-lg text-white disabled:opacity-50',
                      executionMode === 'legacy' 
                        ? 'bg-blue-500 hover:bg-blue-600' 
                        : 'bg-purple-500 hover:bg-purple-600'
                    ]"
                  >
                    Add
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Bottom Spacing -->
        <div class="h-24"></div>
      </div>
    </div>

    <!-- Fixed Footer -->
    <footer class="h-16 border-t border-border bg-muted px-8 flex items-center justify-between shrink-0">
      <div class="flex items-center gap-6 text-[10px] font-bold tracking-tight uppercase">
        <div class="flex items-center gap-2">
          <div class="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]"></div>
          <span class="text-muted-foreground/60">{{ t('agents.footer.local_engine') }}: <span class="text-foreground ml-1">{{ t('agents.create.status_active') }}</span></span>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <Button @click="handleCancel" variant="outline" class="h-10 px-6 rounded-lg border-border text-muted-foreground hover:text-foreground hover:bg-muted">
          {{ t('agents.create.cancel') }}
        </Button>
        <Button @click="handleUpdateAgent" :disabled="isSubmitting || loadingAgent || loadingModels || loadingKBs || loadingSkills" class="h-10 px-6 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold shadow-lg shadow-blue-500/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2">
          <Loader2 v-if="isSubmitting" class="w-4 h-4 animate-spin" />
          {{ isSubmitting ? t('chat.message.loading') : t('agents.edit.update') }}
        </Button>
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
