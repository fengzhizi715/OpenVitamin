<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeft,
  Info,
  Code2,
  ListOrdered,
  Wrench,
  Settings2,
  Save,
  CheckCircle2,
  Plus,
  Trash2,
  Globe,
  FileText,
  Code,
  Database,
} from 'lucide-vue-next'
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
import { getSkill, updateSkill, deleteSkill, type SkillRecord } from '@/services/api'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const skillId = route.params.id as string

const activeSection = ref('basic-info')

interface SchemaField {
  key: string
  type: string
  description: string
}

const loading = ref(true)
const loadError = ref<string | null>(null)
const skill = ref<SkillRecord | null>(null)

const skillName = ref('')
const category = ref('writing')
const description = ref('')
const skillType = ref<'prompt' | 'tool' | 'composite' | 'workflow'>('prompt')
const skillLogic = ref('')
const inputFields = ref<SchemaField[]>([])
const enabled = ref(true)

const timeoutMs = ref([30000])
const retryAttempts = ref([3])
const temperature = ref([0.7])
const fallbackStrategy = ref('default')

const isSubmitting = ref(false)
const submitError = ref<string | null>(null)

const navItems = computed(() => {
  if (loading.value || !skill.value) return []

  const baseItems = [
    { id: 'basic-info', labelKey: 'skills.create.nav_basic', icon: Info },
  ]
  const items = [...baseItems]

  if (skillType.value === 'workflow') {
    items.push({ id: 'workflow-steps', labelKey: 'skills.create.nav_workflow', icon: Code2 })
  } else if (skillType.value !== 'tool') {
    items.push({ id: 'skill-logic', labelKey: 'skills.create.nav_logic', icon: Code2 })
  }

  items.push({ id: 'io-schema', labelKey: 'skills.create.nav_io', icon: ListOrdered })

  if (!isBuiltin.value) {
    items.push({ id: 'rules', labelKey: 'skills.create.nav_rules', icon: Settings2 })
  }

  return items
})

const estVariables = computed(() => inputFields.value.length)
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

function parseInputSchema(schema: Record<string, unknown> | undefined): SchemaField[] {
  if (!schema || typeof schema !== 'object') return []
  const props = (schema as any).properties || {}
  const required = (schema as any).required || []
  const fields: SchemaField[] = []
  for (const [key, value] of Object.entries(props)) {
    if (typeof value === 'object' && value !== null) {
      const v = value as any
      fields.push({
        key,
        type: v.type || 'string',
        description: v.description || '',
      })
    }
  }
  return fields
}

function parseDefinition(definition: Record<string, unknown> | undefined, type: string): string {
  if (!definition || typeof definition !== 'object') return ''
  if (type === 'prompt' || type === 'composite') {
    return (definition as any).prompt_template || ''
  }
  if (type === 'workflow') {
    // For workflow, format workflow steps as JSON
    const steps = (definition as any).workflow_steps || []
    return JSON.stringify(steps, null, 2)
  }
  return ''
}

const loadSkill = async () => {
  loading.value = true
  loadError.value = null
  try {
    const data = await getSkill(skillId)
    skill.value = data
    skillName.value = data.name || ''
    category.value = data.category || 'writing'
    description.value = data.description || ''
    skillType.value = data.type || 'prompt'
    enabled.value = data.enabled ?? true
    skillLogic.value = parseDefinition(data.definition, skillType.value)
    inputFields.value = parseInputSchema(data.input_schema)
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : t('skills.err_load')
  } finally {
    loading.value = false
  }
}

const handleUpdateSkill = async () => {
  submitError.value = null
  if (!skillName.value.trim()) {
    submitError.value = t('skills.create.err_name')
    return
  }
  isSubmitting.value = true
  try {
    const definition: Record<string, unknown> = {}
    if (skillType.value === 'prompt' || skillType.value === 'composite') {
      definition.prompt_template = skillLogic.value || ''
    }
    if (skillType.value === 'tool' || skillType.value === 'composite') {
      // For tool/composite, preserve existing tool_name if any
      if (skill.value?.definition && typeof skill.value.definition === 'object') {
        const existing = skill.value.definition as Record<string, unknown>
        if (existing.tool_name) {
          definition.tool_name = existing.tool_name
        }
        if (existing.tool_args_mapping) {
          definition.tool_args_mapping = existing.tool_args_mapping
        }
      }
    }
    await updateSkill(skillId, {
      name: skillName.value.trim(),
      description: description.value.trim() || undefined,
      category: category.value || undefined,
      type: skillType.value,
      input_schema: buildInputSchema(),
      definition,
      enabled: enabled.value,
    })
    await loadSkill()
    submitError.value = null
  } catch (e) {
    submitError.value = e instanceof Error ? e.message : t('skills.create.err_create_failed')
  } finally {
    isSubmitting.value = false
  }
}

const handleCancel = () => router.push('/skills')

const isBuiltin = computed(() => (skillId || '').startsWith('builtin_'))

const handleDelete = async () => {
  if (!window.confirm(t('skills.delete_confirm', { name: skillName.value || skillId }))) return
  try {
    await deleteSkill(skillId)
    router.push('/skills')
  } catch (e) {
    submitError.value = e instanceof Error ? e.message : t('skills.err_delete')
  }
}

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

onMounted(() => {
  loadSkill()
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
        <Button
          v-if="!isBuiltin"
          variant="outline"
          size="sm"
          class="text-destructive hover:text-destructive hover:bg-destructive/10"
          @click="handleDelete"
        >
          <Trash2 class="w-4 h-4 mr-1" />
          {{ t('skills.delete_skill') }}
        </Button>
        <span class="text-muted-foreground/50">/</span>
        <span class="text-sm font-medium text-foreground">{{ skillName || skillId }}</span>
      </div>
      <div class="flex items-center gap-2">
        <Button
          v-if="!isBuiltin"
          size="sm"
          class="rounded-lg bg-primary text-primary-foreground"
          :disabled="isSubmitting || loading"
          @click="handleUpdateSkill"
        >
          <CheckCircle2 class="w-4 h-4 mr-2" />
          {{ t('skills.create.deploy') }}
        </Button>
        <span v-else class="text-xs text-muted-foreground italic">{{ t('skills.create.builtin_readonly') }}</span>
      </div>
    </header>

    <div v-if="loading" class="flex-1 flex items-center justify-center">
      <div class="text-muted-foreground">{{ t('skills.create.loading_skill') }}</div>
    </div>
    <div v-else-if="loadError" class="flex-1 flex items-center justify-center">
      <div class="rounded-2xl border border-red-500/30 bg-red-500/10 px-6 py-4 text-sm text-red-600 dark:text-red-400">
        {{ loadError }}
      </div>
    </div>
    <div v-else class="flex-1 flex min-h-0">
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
            <CheckCircle2 v-if="activeSection === item.id" class="w-4 h-4 ml-auto text-green-500" />
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
            <h1 class="text-3xl font-bold tracking-tight text-foreground mb-2">{{ skillName || t('skills.create.edit_title') }}</h1>
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
              <div class="space-y-2">
                <label class="text-sm font-semibold text-foreground">{{ t('common.type') }}</label>
                <Select v-model="skillType" :disabled="skill?.id?.startsWith('builtin_')">
                  <SelectTrigger class="rounded-lg"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="prompt">{{ t('skills.type_prompt') }}</SelectItem>
                    <SelectItem value="tool">{{ t('skills.type_tool') }}</SelectItem>
                    <SelectItem value="composite">{{ t('skills.type_composite') }}</SelectItem>
                    <SelectItem value="workflow">{{ t('skills.type_workflow') }}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div class="space-y-2">
                <label class="text-sm font-semibold text-foreground">{{ t('common.status_label') }}</label>
                <div class="flex items-center gap-2">
                  <input
                    type="checkbox"
                    v-model="enabled"
                    class="rounded border-border text-primary focus:ring-primary"
                  />
                  <span class="text-sm">{{ enabled ? t('common.enabled') : t('common.disabled') }}</span>
                </div>
              </div>
              <div class="col-span-full space-y-2">
                <label class="text-sm font-semibold text-foreground">{{ t('skills.create.description') }}</label>
                <Textarea v-model="description" :placeholder="t('skills.create.description_placeholder')" class="rounded-lg min-h-[80px]" />
              </div>
            </div>
          </section>

          <!-- 2. Skill Logic / Workflow Steps (hidden for tool type) -->
          <section 
            v-if="skillType !== 'tool'"
            :id="skillType === 'workflow' ? 'workflow-steps' : 'skill-logic'" 
            class="scroll-mt-8"
          >
            <div class="flex items-center gap-3 mb-4">
              <h3 class="text-xl font-bold text-foreground">
                {{ skillType === 'workflow' ? t('skills.create.section_workflow') : t('skills.create.section_logic') }}
              </h3>
              <div class="flex-1 h-px bg-border" />
            </div>
            <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
              <div class="px-4 py-2 border-b border-border bg-muted/50 flex items-center gap-2">
                <span class="text-[10px] font-mono text-muted-foreground uppercase">
                  {{ skillType === 'workflow' ? t('skills.create.workflow_steps_hint') : t('skills.create.monospace_hint') }}
                </span>
              </div>
              <Textarea
                v-model="skillLogic"
                :disabled="isBuiltin"
                class="rounded-none border-0 min-h-[240px] font-mono text-sm bg-muted/20 focus-visible:ring-0 resize-none"
                :placeholder="skillType === 'workflow' ? t('skills.create.workflow_placeholder') : t('skills.create.logic_placeholder')"
              />
              <div class="px-4 py-2 border-t border-border bg-muted/50 text-[10px] text-muted-foreground flex items-center gap-2">
                <Info class="w-3.5 h-3.5 shrink-0" />
                <span v-if="isBuiltin" class="text-amber-500">{{ t('skills.create.builtin_readonly') }}</span>
                <span v-else-if="skillType === 'workflow'">{{ t('skills.create.workflow_steps_desc') }}</span>
                <span v-else>{{ t('skills.create.variable_hint') }}</span>
              </div>
            </div>
          </section>

          <!-- 3. IO Schema -->
          <section id="io-schema" class="scroll-mt-8">
            <div class="flex items-center gap-3 mb-4">
              <h3 class="text-xl font-bold text-foreground">{{ t('skills.create.section_io') }}</h3>
              <div class="flex-1 h-px bg-border" />
            </div>
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
          </section>

          <!-- 4. Execution Rules -->
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
