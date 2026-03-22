<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeft,
  Info,
  Code2,
  ListOrdered,
  Wrench,
  Settings2,
  Play,
  Plus,
  Trash2,
  Save,
  CheckCircle2,
  Globe,
  FileText,
  Code,
  Database,
  Search,
  Network,
  Cpu,
  Clock,
  Type,
  Loader2,
  ChevronDown,
  ChevronRight,
  CheckSquare,
  Square,
} from 'lucide-vue-next'
import type { Component } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Slider } from '@/components/ui/slider'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { createSkill, listTools, type ToolInfo } from '@/services/api'

const { t } = useI18n()
const router = useRouter()

const activeSection = ref('basic-info')

interface SchemaField {
  key: string
  type: string
  description: string
}

const skillName = ref('')
const category = ref('writing')
const description = ref('')
const skillLogic = ref('')
const inputFields = ref<SchemaField[]>([
  { key: 'url', type: 'string', description: '' },
  { key: 'tone', type: 'string', description: '' },
])
const outputFields = ref<SchemaField[]>([
  { key: 'summary', type: 'markdown', description: '' },
])

const categoryToIcon: Record<string, Component> = {
  file: FileText,
  web: Globe,
  python: Code,
  sql: Database,
  http: Network,
  text: Type,
  system: Cpu,
  time: Clock,
}
const toolsFromApi = ref<ToolInfo[]>([])
const loadingTools = ref(true)
const toolSearchQuery = ref('')
const expandedToolCategories = ref<Set<string>>(new Set())

const availableToolsList = computed(() =>
  toolsFromApi.value.map((tool) => {
    const category = tool.ui?.category ?? tool.name.split('.')[0] ?? 'file'
    return {
      id: tool.name,
      name: tool.ui?.display_name ?? tool.name,
      desc: tool.description,
      category,
      icon: categoryToIcon[category] ?? Wrench,
    }
  })
)

const toolsFiltered = computed(() => {
  const q = toolSearchQuery.value.trim().toLowerCase()
  if (!q) return availableToolsList.value
  return availableToolsList.value.filter(
    (t) =>
      t.name.toLowerCase().includes(q) ||
      t.id.toLowerCase().includes(q) ||
      t.desc.toLowerCase().includes(q)
  )
})

interface ToolWithMeta {
  id: string
  name: string
  desc: string
  category: string
  icon: Component
}
const toolsByCategory = computed(() => {
  const map = new Map<string, ToolWithMeta[]>()
  for (const t of toolsFiltered.value) {
    const list = map.get(t.category) ?? []
    list.push(t)
    map.set(t.category, list)
  }
  const order = ['file', 'web', 'http', 'python', 'sql', 'text', 'system', 'time']
  const entries: { category: string; label: string; tools: ToolWithMeta[] }[] = []
  const seen = new Set<string>()
  for (const cat of order) {
    const tools = map.get(cat)
    if (tools?.length) {
      entries.push({ category: cat, label: categoryLabel(cat), tools })
      seen.add(cat)
    }
  }
  for (const [cat, tools] of map) {
    if (!seen.has(cat)) entries.push({ category: cat, label: categoryLabel(cat), tools })
  }
  return entries
})

function categoryLabel(cat: string): string {
  const keyMap: Record<string, string> = {
    file: 'skills.create.tool_cat_file',
    web: 'skills.create.tool_cat_web',
    http: 'skills.create.tool_cat_http',
    python: 'skills.create.tool_cat_python',
    sql: 'skills.create.tool_cat_sql',
    text: 'skills.create.tool_cat_text',
    system: 'skills.create.tool_cat_system',
    time: 'skills.create.tool_cat_time',
  }
  const key = keyMap[cat]
  return key ? t(key) : cat.charAt(0).toUpperCase() + cat.slice(1)
}

const selectedCount = computed(() => selectedToolIds.value.length)

const isCategoryExpanded = (cat: string) => expandedToolCategories.value.has(cat)
const toggleToolCategory = (cat: string) => {
  const next = new Set(expandedToolCategories.value)
  if (next.has(cat)) next.delete(cat)
  else next.add(cat)
  expandedToolCategories.value = next
}
const selectAllInCategory = (tools: ToolWithMeta[]) => {
  const ids = new Set(selectedToolIds.value)
  tools.forEach((t) => ids.add(t.id))
  selectedToolIds.value = [...ids]
}
const clearInCategory = (tools: ToolWithMeta[]) => {
  const ids = new Set(selectedToolIds.value)
  tools.forEach((t) => ids.delete(t.id))
  selectedToolIds.value = [...ids]
}
const selectAllFiltered = () => {
  toolsFiltered.value.forEach((t) => selectedToolIds.value.push(t.id))
  selectedToolIds.value = [...new Set(selectedToolIds.value)]
}
const clearAllTools = () => {
  selectedToolIds.value = []
}

const selectedToolIds = ref<string[]>([])

const timeoutMs = ref([30000])
const retryAttempts = ref([3])
const temperature = ref([0.7])
const fallbackStrategy = ref('default')

const isSubmitting = ref(false)
const submitError = ref<string | null>(null)

const navItems = [
  { id: 'basic-info', labelKey: 'skills.create.nav_basic', icon: Info },
  { id: 'skill-logic', labelKey: 'skills.create.nav_logic', icon: Code2 },
  { id: 'io-schema', labelKey: 'skills.create.nav_io', icon: ListOrdered },
  { id: 'tools', labelKey: 'skills.create.nav_tools', icon: Wrench },
  { id: 'rules', labelKey: 'skills.create.nav_rules', icon: Settings2 },
]

const estVariables = computed(() => inputFields.value.length + outputFields.value.length)
const estTokens = computed(() => Math.round(skillLogic.value.split(/\s+/).length * 1.3))

const scrollToSection = (id: string) => {
  activeSection.value = id
  const el = document.getElementById(id)
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const addInputField = () => {
  inputFields.value.push({ key: '', type: 'string', description: '' })
}
const removeInputField = (index: number) => {
  inputFields.value.splice(index, 1)
}
const addOutputField = () => {
  outputFields.value.push({ key: '', type: 'string', description: '' })
}
const removeOutputField = (index: number) => {
  outputFields.value.splice(index, 1)
}

const isToolSelected = (id: string) => selectedToolIds.value.includes(id)
const toggleTool = (id: string) => {
  const i = selectedToolIds.value.indexOf(id)
  if (i >= 0) selectedToolIds.value.splice(i, 1)
  else selectedToolIds.value.push(id)
}

const handleSaveDraft = () => {
  // TODO: persist draft (localStorage or API)
  submitError.value = null
}
function buildInputSchema(): Record<string, unknown> {
  const properties: Record<string, { type: string; description?: string }> = {}
  const required: string[] = []
  for (const f of inputFields.value) {
    if (!f.key.trim()) continue
    properties[f.key.trim()] = { type: f.type || 'string', description: f.description || undefined }
    required.push(f.key.trim())
  }
  return { type: 'object', properties, required }
}

const handleCreateSkill = async () => {
  submitError.value = null
  if (!skillName.value.trim()) {
    submitError.value = t('skills.create.err_name')
    return
  }
  isSubmitting.value = true
  try {
    await createSkill({
      name: skillName.value.trim(),
      description: description.value.trim() || undefined,
      category: category.value || undefined,
      type: 'prompt',
      input_schema: buildInputSchema(),
      definition: { prompt_template: skillLogic.value || '' },
      enabled: true,
    })
    router.push('/skills')
  } catch (e) {
    submitError.value = e instanceof Error ? e.message : t('skills.create.err_create_failed')
  } finally {
    isSubmitting.value = false
  }
}
const handleCancel = () => router.push('/skills')

const dataTypeIds = ['string', 'number', 'boolean', 'markdown', 'json', 'enum'] as const
const dataTypeLabels: Record<(typeof dataTypeIds)[number], string> = {
  string: 'skills.create.type_string',
  number: 'skills.create.type_number',
  boolean: 'skills.create.type_boolean',
  markdown: 'skills.create.type_markdown',
  json: 'skills.create.type_json',
  enum: 'skills.create.type_enum',
}
const dataTypes = computed(() => dataTypeIds.map((id) => ({ id, label: t(dataTypeLabels[id]) })))

function initLocalizedDefaults() {
  if (!skillLogic.value) skillLogic.value = t('skills.create.logic_default')
  if (inputFields.value[0]?.description === '') {
    inputFields.value[0].description = t('skills.create.input_url_desc')
    if (inputFields.value[1]) inputFields.value[1].description = t('skills.create.input_tone_desc')
  }
  if (outputFields.value[0]?.description === '') outputFields.value[0].description = t('skills.create.output_summary_desc')
}
onMounted(async () => {
  initLocalizedDefaults()
  try {
    loadingTools.value = true
    const res = await listTools()
    toolsFromApi.value = res.data ?? []
    const categories = [
      ...new Set(
        (res.data ?? []).map((t) => t.ui?.category ?? t.name.split('.')[0] ?? 'file')
      ),
    ]
    expandedToolCategories.value = new Set(categories)
  } catch (e) {
    console.error('Failed to load tools', e)
    toolsFromApi.value = []
  } finally {
    loadingTools.value = false
  }
})
</script>

<template>
  <div class="flex-1 flex flex-col min-h-0 h-full bg-background text-foreground overflow-hidden">
    <!-- Header -->
    <header class="shrink-0 border-b border-border bg-background px-6 py-3 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button
          @click="handleCancel"
          class="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft class="w-4 h-4" />
          <span class="text-sm font-medium">{{ t('nav.skills') }}</span>
        </button>
        <span class="text-muted-foreground/50">/</span>
        <span class="text-sm font-medium text-foreground">{{ t('skills.create.title') }}</span>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" class="rounded-lg" @click="handleSaveDraft">
          <Save class="w-4 h-4 mr-2" />
          {{ t('skills.create.save_draft') }}
        </Button>
        <Button
          size="sm"
          class="rounded-lg bg-primary text-primary-foreground"
          :disabled="isSubmitting"
          @click="handleCreateSkill"
        >
          <CheckCircle2 class="w-4 h-4 mr-2" />
          {{ t('skills.create.deploy') }}
        </Button>
      </div>
    </header>

    <div class="flex-1 flex min-h-0">
      <!-- Left sidebar nav -->
      <aside class="w-56 shrink-0 border-r border-border bg-muted/30 flex flex-col py-4">
        <div class="px-4 mb-4">
          <h2 class="text-sm font-bold text-foreground">{{ t('skills.create.editor_title') }}</h2>
          <p class="text-xs text-muted-foreground font-mono mt-0.5">v1</p>
        </div>
        <nav class="px-2 space-y-0.5">
          <button
            v-for="item in navItems"
            :key="item.id"
            :class="[
              'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors text-sm',
              activeSection === item.id
                ? 'bg-primary/10 text-primary border border-primary/20 font-semibold'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            ]"
            @click="scrollToSection(item.id)"
          >
            <component :is="item.icon" class="w-4 h-4 shrink-0" />
            <span>{{ t(item.labelKey) }}</span>
            <CheckCircle2 v-if="item.id === 'basic-info' && skillName.trim()" class="w-4 h-4 ml-auto text-green-500" />
          </button>
        </nav>
        <div class="mt-auto px-4 pt-4 border-t border-border">
          <div class="rounded-xl bg-card border border-border p-3 text-xs">
            <p class="font-bold text-muted-foreground uppercase tracking-wider mb-2">{{ t('skills.create.stats') }}</p>
            <div class="flex justify-between mb-1"><span class="text-muted-foreground">{{ t('skills.create.variables') }}</span><span class="font-mono text-primary">{{ estVariables }}</span></div>
            <div class="flex justify-between"><span class="text-muted-foreground">{{ t('skills.create.est_tokens') }}</span><span class="font-mono text-primary">{{ estTokens }}</span></div>
          </div>
        </div>
      </aside>

      <!-- Main content -->
      <main class="flex-1 min-w-0 overflow-y-auto custom-scrollbar p-8 bg-muted/10">
        <div class="max-w-4xl mx-auto space-y-12">
          <div class="border-b border-border pb-6">
            <p class="text-primary font-bold text-xs uppercase tracking-widest mb-2">{{ t('skills.create.config_label') }}</p>
            <h1 class="text-3xl font-bold tracking-tight text-foreground mb-2">{{ t('skills.create.define_title') }}</h1>
            <p class="text-muted-foreground">{{ t('skills.create.define_subtitle') }}</p>
          </div>

          <div v-if="submitError" class="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {{ submitError }}
          </div>

          <!-- 1. Basic Info -->
          <section id="basic-info" class="scroll-mt-8">
            <div class="flex items-center gap-3 mb-4">
              <h3 class="text-xl font-bold text-foreground">{{ t('skills.create.section_basic') }}</h3>
              <div class="flex-1 h-px bg-border" />
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 bg-card rounded-xl border border-border p-6 shadow-sm">
              <div class="space-y-2">
                <label class="text-sm font-semibold text-foreground">{{ t('skills.create.skill_name') }}</label>
                <Input v-model="skillName" :placeholder="t('skills.create.skill_name_placeholder')" class="rounded-lg" />
              </div>
              <div class="space-y-2">
                <label class="text-sm font-semibold text-foreground">{{ t('skills.create.category') }}</label>
                <Select v-model="category">
                  <SelectTrigger class="rounded-lg"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="writing">{{ t('skills.create.cat_writing') }}</SelectItem>
                    <SelectItem value="coding">{{ t('skills.create.cat_coding') }}</SelectItem>
                    <SelectItem value="research">{{ t('skills.create.cat_research') }}</SelectItem>
                    <SelectItem value="automation">{{ t('skills.create.cat_automation') }}</SelectItem>
                    <SelectItem value="data">{{ t('skills.create.cat_data') }}</SelectItem>
                    <SelectItem value="utilities">{{ t('skills.create.cat_utilities') }}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div class="col-span-full space-y-2">
                <label class="text-sm font-semibold text-foreground">{{ t('skills.create.description') }}</label>
                <Textarea v-model="description" :placeholder="t('skills.create.description_placeholder')" class="rounded-lg min-h-[80px]" />
              </div>
            </div>
          </section>

          <!-- 2. Skill Logic -->
          <section id="skill-logic" class="scroll-mt-8">
            <div class="flex items-center gap-3 mb-4">
              <h3 class="text-xl font-bold text-foreground">{{ t('skills.create.section_logic') }}</h3>
              <div class="flex-1 h-px bg-border" />
            </div>
            <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
              <div class="px-4 py-2 border-b border-border bg-muted/50 flex items-center gap-2">
                <span class="text-[10px] font-mono text-muted-foreground uppercase">{{ t('skills.create.monospace_hint') }}</span>
              </div>
              <Textarea
                v-model="skillLogic"
                class="rounded-none border-0 min-h-[240px] font-mono text-sm bg-muted/20 focus-visible:ring-0 resize-none"
                :placeholder="t('skills.create.logic_placeholder')"
              />
              <div class="px-4 py-2 border-t border-border bg-muted/50 text-[10px] text-muted-foreground flex items-center gap-2">
                <Info class="w-3.5 h-3.5 shrink-0" />
                {{ t('skills.create.variable_hint') }}
              </div>
            </div>
          </section>

          <!-- 3. IO Schema -->
          <section id="io-schema" class="scroll-mt-8">
            <div class="flex items-center gap-3 mb-4">
              <h3 class="text-xl font-bold text-foreground">{{ t('skills.create.section_io') }}</h3>
              <div class="flex-1 h-px bg-border" />
            </div>
            <div class="space-y-6">
              <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
                <div class="px-4 py-3 bg-muted/50 border-b border-border flex justify-between items-center">
                  <span class="text-xs font-bold uppercase tracking-wider text-muted-foreground">{{ t('skills.create.input_params') }}</span>
                  <Button variant="ghost" size="sm" class="h-8 text-xs gap-1" @click="addInputField"><Plus class="w-3.5 h-3.5" /> {{ t('skills.create.add_field') }}</Button>
                </div>
                <div class="overflow-x-auto">
                  <table class="w-full text-sm">
                    <thead>
                      <tr class="border-b border-border text-muted-foreground">
                        <th class="px-4 py-3 font-medium text-left">{{ t('skills.create.key_name') }}</th>
                        <th class="px-4 py-3 font-medium text-left">{{ t('skills.create.data_type') }}</th>
                        <th class="px-4 py-3 font-medium text-left">{{ t('skills.create.description') }}</th>
                        <th class="px-4 py-3 w-12" />
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-border">
                      <tr v-for="(f, idx) in inputFields" :key="idx" class="hover:bg-muted/30">
                        <td class="px-4 py-3"><Input v-model="f.key" class="h-8 font-mono text-primary border-0 bg-transparent" :placeholder="t('skills.create.placeholder_key')" /></td>
                        <td class="px-4 py-3">
                          <Select v-model="f.type">
                            <SelectTrigger class="h-8 w-[100px]"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              <SelectItem v-for="dt in dataTypes" :key="dt.id" :value="dt.id">{{ dt.label }}</SelectItem>
                            </SelectContent>
                          </Select>
                        </td>
                        <td class="px-4 py-3"><Input v-model="f.description" class="h-8 border-0 bg-transparent italic text-muted-foreground" :placeholder="t('skills.create.placeholder_desc')" /></td>
                        <td class="px-4 py-3"><Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-red-500" @click="removeInputField(idx)"><Trash2 class="w-4 h-4" /></Button></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
                <div class="px-4 py-3 bg-muted/50 border-b border-border flex justify-between items-center">
                  <span class="text-xs font-bold uppercase tracking-wider text-muted-foreground">{{ t('skills.create.output_def') }}</span>
                  <Button variant="ghost" size="sm" class="h-8 text-xs gap-1" @click="addOutputField"><Plus class="w-3.5 h-3.5" /> {{ t('skills.create.add_field') }}</Button>
                </div>
                <div class="overflow-x-auto">
                  <table class="w-full text-sm">
                    <thead>
                      <tr class="border-b border-border text-muted-foreground">
                        <th class="px-4 py-3 font-medium text-left">{{ t('skills.create.key_name') }}</th>
                        <th class="px-4 py-3 font-medium text-left">{{ t('skills.create.data_type') }}</th>
                        <th class="px-4 py-3 font-medium text-left">{{ t('skills.create.description') }}</th>
                        <th class="px-4 py-3 w-12" />
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-border">
                      <tr v-for="(f, idx) in outputFields" :key="idx" class="hover:bg-muted/30">
                        <td class="px-4 py-3"><Input v-model="f.key" class="h-8 font-mono text-green-600 dark:text-green-400 border-0 bg-transparent" :placeholder="t('skills.create.placeholder_key')" /></td>
                        <td class="px-4 py-3">
                          <Select v-model="f.type">
                            <SelectTrigger class="h-8 w-[100px]"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              <SelectItem v-for="dt in dataTypes" :key="dt.id" :value="dt.id">{{ dt.label }}</SelectItem>
                            </SelectContent>
                          </Select>
                        </td>
                        <td class="px-4 py-3"><Input v-model="f.description" class="h-8 border-0 bg-transparent italic text-muted-foreground" :placeholder="t('skills.create.placeholder_desc')" /></td>
                        <td class="px-4 py-3"><Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-red-500" @click="removeOutputField(idx)"><Trash2 class="w-4 h-4" /></Button></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </section>

          <!-- 4. Tools -->
          <section id="tools" class="scroll-mt-8">
            <div class="flex items-center gap-3 mb-4">
              <h3 class="text-xl font-bold text-foreground">{{ t('skills.create.section_tools') }}</h3>
              <div class="flex-1 h-px bg-border" />
            </div>
            <div v-if="loadingTools" class="flex items-center gap-2 py-8 text-muted-foreground">
              <Loader2 class="w-5 h-5 animate-spin" />
              <span>{{ t('skills.create.tools_loading') }}</span>
            </div>
            <div v-else class="space-y-3">
              <div class="flex flex-wrap items-center gap-2">
                <div class="relative flex-1 min-w-[180px] max-w-sm">
                  <Search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                  <Input
                    v-model="toolSearchQuery"
                    type="text"
                    :placeholder="t('skills.create.tools_search_placeholder')"
                    class="pl-8 h-9 bg-muted/50 border-border"
                  />
                </div>
                <span class="text-sm text-muted-foreground whitespace-nowrap">
                  {{ selectedCount }} {{ t('skills.create.tools_selected') }}
                </span>
                <Button variant="ghost" size="sm" class="h-9 text-muted-foreground" @click="selectAllFiltered">
                  <CheckSquare class="w-4 h-4 mr-1" />
                  {{ t('skills.create.tools_select_all') }}
                </Button>
                <Button variant="ghost" size="sm" class="h-9 text-muted-foreground" @click="clearAllTools">
                  <Square class="w-4 h-4 mr-1" />
                  {{ t('skills.create.tools_clear') }}
                </Button>
              </div>
              <div class="rounded-xl border border-border bg-card overflow-hidden max-h-[min(420px,60vh)] overflow-y-auto custom-scrollbar">
                <template v-for="group in toolsByCategory" :key="group.category">
                  <div class="border-b border-border last:border-b-0">
                    <button
                      type="button"
                      class="w-full flex items-center gap-2 px-4 py-2.5 text-left bg-muted/30 hover:bg-muted/50 transition-colors"
                      @click="toggleToolCategory(group.category)"
                    >
                      <component :is="isCategoryExpanded(group.category) ? ChevronDown : ChevronRight" class="w-4 h-4 shrink-0 text-muted-foreground" />
                      <component :is="categoryToIcon[group.category] ?? Wrench" class="w-4 h-4 shrink-0 text-muted-foreground" />
                      <span class="font-medium text-foreground">{{ group.label }}</span>
                      <span class="text-xs text-muted-foreground">({{ group.tools.length }})</span>
                      <span class="ml-auto text-xs text-muted-foreground">
                        <button type="button" class="hover:text-foreground px-1" @click.stop="selectAllInCategory(group.tools)">{{ t('skills.create.tools_select_all') }}</button>
                        <span class="mx-1">/</span>
                        <button type="button" class="hover:text-foreground px-1" @click.stop="clearInCategory(group.tools)">{{ t('skills.create.tools_clear') }}</button>
                      </span>
                    </button>
                    <div v-show="isCategoryExpanded(group.category)" class="bg-background/50">
                      <div
                        v-for="tool in group.tools"
                        :key="tool.id"
                        :class="[
                          'flex items-center gap-3 px-4 py-2 border-t border-border/50 first:border-t-0 hover:bg-muted/20 transition-colors cursor-pointer',
                          isToolSelected(tool.id) && 'bg-primary/5'
                        ]"
                        @click="toggleTool(tool.id)"
                      >
                        <div :class="['p-1.5 rounded shrink-0', isToolSelected(tool.id) ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground']">
                          <component :is="tool.icon" class="w-4 h-4" />
                        </div>
                        <div class="flex-1 min-w-0 py-0.5">
                          <p class="text-sm font-medium text-foreground truncate">{{ tool.name }}</p>
                          <p class="text-xs text-muted-foreground truncate">{{ tool.desc }}</p>
                        </div>
                        <input
                          type="checkbox"
                          :checked="isToolSelected(tool.id)"
                          class="rounded border-border text-primary focus:ring-primary shrink-0"
                          @click.stop="toggleTool(tool.id)"
                        />
                      </div>
                    </div>
                  </div>
                </template>
                <div v-if="toolsByCategory.length === 0" class="px-4 py-6 text-center text-sm text-muted-foreground">
                  {{ t('skills.create.tools_no_match') }}
                </div>
              </div>
            </div>
          </section>

          <!-- 5. Execution Rules -->
          <section id="rules" class="scroll-mt-8 pb-8">
            <div class="flex items-center gap-3 mb-4">
              <h3 class="text-xl font-bold text-foreground">{{ t('skills.create.section_rules') }}</h3>
              <div class="flex-1 h-px bg-border" />
            </div>
            <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
              <div class="p-4 border-b border-border">
                <div class="flex items-center gap-3 text-foreground font-bold">
                  <Settings2 class="w-5 h-5 text-primary" />
                  {{ t('skills.create.advanced_settings') }}
                </div>
              </div>
              <div class="p-6 grid grid-cols-1 md:grid-cols-2 gap-8">
                <div class="space-y-4">
                  <div class="flex justify-between items-center">
                    <label class="text-sm font-semibold text-foreground">{{ t('skills.create.timeout') }}</label>
                    <span class="text-xs font-mono text-primary bg-primary/10 px-2 py-0.5 rounded">{{ timeoutMs[0] }} ms</span>
                  </div>
                  <Slider v-model="timeoutMs" :min="5000" :max="120000" :step="5000" class="w-full" />
                  <p class="text-[10px] text-muted-foreground">{{ t('skills.create.timeout_hint') }}</p>
                </div>
                <div class="space-y-4">
                  <div class="flex justify-between items-center">
                    <label class="text-sm font-semibold text-foreground">{{ t('skills.create.retry') }}</label>
                    <span class="text-xs font-mono text-primary bg-primary/10 px-2 py-0.5 rounded">{{ retryAttempts[0] }}×</span>
                  </div>
                  <Slider v-model="retryAttempts" :min="0" :max="10" :step="1" class="w-full" />
                  <p class="text-[10px] text-muted-foreground">{{ t('skills.create.retry_hint') }}</p>
                </div>
                <div class="space-y-4">
                  <div class="flex justify-between items-center">
                    <label class="text-sm font-semibold text-foreground">{{ t('skills.create.temperature') }}</label>
                    <span class="text-xs font-mono text-primary bg-primary/10 px-2 py-0.5 rounded">{{ temperature[0].toFixed(1) }}</span>
                  </div>
                  <Slider v-model="temperature" :min="0" :max="1" :step="0.1" class="w-full" />
                  <p class="text-[10px] text-muted-foreground">{{ t('skills.create.temperature_hint') }}</p>
                </div>
                <div class="space-y-4">
                  <label class="text-sm font-semibold text-foreground block">{{ t('skills.create.fallback') }}</label>
                  <Select v-model="fallbackStrategy">
                    <SelectTrigger class="w-full rounded-lg"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">{{ t('skills.create.fallback_default') }}</SelectItem>
                      <SelectItem value="error">{{ t('skills.create.fallback_error') }}</SelectItem>
                      <SelectItem value="backoff">{{ t('skills.create.fallback_backoff') }}</SelectItem>
                    </SelectContent>
                  </Select>
                  <p class="text-[10px] text-muted-foreground">{{ t('skills.create.fallback_hint') }}</p>
                </div>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: hsl(var(--muted-foreground) / 0.2); border-radius: 10px; }
</style>
