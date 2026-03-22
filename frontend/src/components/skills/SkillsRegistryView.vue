<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Search,
  Plus,
  Globe,
  FileText,
  Languages,
  Code2,
  ChevronLeft,
  ChevronRight,
  Wrench,
  Trash2,
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
import { listSkills, deleteSkill, type SkillRecord } from '@/services/api'

const { t } = useI18n()

const allSkills = ref<SkillRecord[]>([])
const loading = ref(true)
const loadError = ref<string | null>(null)

onMounted(async () => {
  loading.value = true
  loadError.value = null
  try {
    const res = await listSkills()
    allSkills.value = res.data || []
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : t('skills.err_load_list')
    allSkills.value = []
  } finally {
    loading.value = false
  }
})

const searchQuery = ref('')
const filterType = ref('all')
const filterStatus = ref('all')
const currentPage = ref(1)
const pageSize = 10

const filteredSkills = computed(() => {
  let list = allSkills.value
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.description && s.description.toLowerCase().includes(q)) ||
        (s.category && s.category.toLowerCase().includes(q)) ||
        (s.type && s.type.toLowerCase().includes(q))
    )
  }
  return list
})

const totalCount = computed(() => filteredSkills.value.length)
const paginatedSkills = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredSkills.value.slice(start, start + pageSize)
})
const totalPages = computed(() => Math.max(1, Math.ceil(totalCount.value / pageSize)))
const rangeStart = computed(() => (currentPage.value - 1) * pageSize + 1)
const rangeEnd = computed(() =>
  Math.min(currentPage.value * pageSize, totalCount.value)
)

const getSkillIcon = (skill: SkillRecord) => {
  if (skill.type === 'tool') return Wrench
  if (skill.type === 'composite') return Code2
  return FileText
}

const router = useRouter()
const handleCreateSkill = () => {
  router.push({ name: 'skills-create' })
}

const goToSkillDetail = (skillId: string) => {
  router.push({ name: 'skill-detail', params: { id: skillId } })
}

const handleDeleteSkill = async (skill: SkillRecord, e: Event) => {
  e.stopPropagation()
  if (!window.confirm(t('skills.delete_confirm', { name: skill.name || skill.id }))) return
  try {
    await deleteSkill(skill.id)
    const res = await listSkills()
    allSkills.value = res.data || []
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : t('skills.err_delete')
  }
}

const isBuiltin = (id: string) => (id || '').startsWith('builtin_')

const goPrev = () => {
  if (currentPage.value > 1) currentPage.value--
}
const goNext = () => {
  if (currentPage.value < totalPages.value) currentPage.value++
}
</script>

<template>
  <div class="flex-1 flex flex-col min-h-0 h-full bg-background text-foreground overflow-hidden">
    <!-- Header -->
    <header class="shrink-0 border-b border-border bg-background/95 px-8 pt-8 pb-6">
      <div class="flex items-start justify-between gap-4">
        <div class="space-y-1">
          <h1 class="text-3xl font-bold tracking-tight text-foreground">
            {{ t('skills.title') }}
          </h1>
          <p class="text-sm text-muted-foreground/90">
            {{ t('skills.subtitle') }}
          </p>
        </div>
        <Button
          class="shrink-0 bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 rounded-xl shadow-lg shadow-primary/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
          @click="handleCreateSkill"
        >
          <Plus class="w-4 h-4 mr-2" />
          {{ t('skills.create_skill') }}
        </Button>
      </div>

      <!-- Search & Filters -->
      <div class="mt-6 flex flex-wrap items-center gap-3">
        <div class="relative flex-1 min-w-[220px] max-w-md">
          <Search
            class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none"
          />
          <Input
            v-model="searchQuery"
            :placeholder="t('skills.search_placeholder')"
            class="pl-10 h-10 bg-muted/50 border-border rounded-xl text-sm focus-visible:ring-primary/50 focus-visible:border-primary/50 transition-all"
          />
        </div>
        <Select v-model="filterType">
          <SelectTrigger
            class="w-[130px] h-10 bg-muted/50 border-border rounded-xl text-xs"
          >
            <SelectValue :placeholder="t('skills.filter_type')" />
          </SelectTrigger>
          <SelectContent class="bg-card border-border">
            <SelectItem value="all">{{ t('common.all') }}</SelectItem>
          </SelectContent>
        </Select>
        <Select v-model="filterStatus">
          <SelectTrigger
            class="w-[130px] h-10 bg-muted/50 border-border rounded-xl text-xs"
          >
            <SelectValue :placeholder="t('skills.filter_status')" />
          </SelectTrigger>
          <SelectContent class="bg-card border-border">
            <SelectItem value="all">{{ t('common.all') }}</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </header>

    <!-- Table area: fills remaining height -->
    <div class="flex-1 min-h-0 flex flex-col overflow-hidden">
      <div class="flex-1 min-h-0 overflow-auto px-8 py-6 custom-scrollbar">
        <div v-if="loading" class="flex items-center justify-center py-24 text-muted-foreground">
          {{ t('common.loading') }}
        </div>
        <div v-else-if="loadError" class="rounded-2xl border border-red-500/30 bg-red-500/10 px-6 py-4 text-sm text-red-600 dark:text-red-400">
          {{ loadError }}
        </div>
        <div
          v-else
          class="rounded-2xl border border-border bg-card overflow-hidden shadow-sm min-h-full"
        >
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="border-b border-border bg-muted/40">
                <th
                  class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                >
                  {{ t('skills.col_name') }}
                </th>
                <th
                  class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                >
                  {{ t('skills.col_description') }}
                </th>
                <th
                  class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                >
                  {{ t('common.category') }}
                </th>
                <th
                  class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                >
                  {{ t('common.type') }}
                </th>
                <th
                  class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                >
                  {{ t('common.status_label') }}
                </th>
                <th class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground w-20">
                  {{ t('common.actions') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="skill in paginatedSkills"
                :key="skill.id"
                class="border-b border-border/50 hover:bg-muted/25 transition-colors last:border-b-0 cursor-pointer"
                @click="goToSkillDetail(skill.id)"
              >
                <td class="px-5 py-4">
                  <div class="flex items-center gap-3">
                    <div
                      class="w-10 h-10 rounded-xl bg-muted/80 border border-border flex items-center justify-center shrink-0 text-muted-foreground"
                    >
                      <component
                        :is="getSkillIcon(skill)"
                        class="w-5 h-5"
                      />
                    </div>
                    <span class="font-semibold text-foreground">{{ skill.name }}</span>
                  </div>
                </td>
                <td class="px-5 py-4 max-w-[300px]">
                  <span class="text-sm text-muted-foreground line-clamp-2 leading-relaxed">
                    {{ skill.description || '—' }}
                  </span>
                </td>
                <td class="px-5 py-4">
                  <span class="text-sm text-muted-foreground">{{ skill.category || '—' }}</span>
                </td>
                <td class="px-5 py-4">
                  <span class="text-xs font-mono px-2 py-1 rounded-lg bg-muted border border-border">{{ skill.type && $te('skills.type_' + skill.type) ? t('skills.type_' + skill.type) : (skill.type || '—') }}</span>
                </td>
                <td class="px-5 py-4">
                  <span
                    :class="[
                      'text-xs font-medium px-2 py-1 rounded-lg',
                      skill.enabled ? 'bg-green-500/10 text-green-600 dark:text-green-400 border border-green-500/20' : 'bg-muted text-muted-foreground border border-border'
                    ]"
                  >
                    {{ skill.enabled ? t('common.enabled') : t('common.disabled') }}
                  </span>
                </td>
                <td class="px-5 py-4" @click.stop>
                  <Button
                    v-if="!isBuiltin(skill.id)"
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8 text-muted-foreground hover:text-destructive"
                    :title="t('skills.delete_skill')"
                    @click="handleDeleteSkill(skill, $event)"
                  >
                    <Trash2 class="w-4 h-4" />
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Empty (only when not loading and no error) -->
        <div
          v-if="!loading && !loadError && filteredSkills.length === 0"
          class="flex flex-col items-center justify-center py-24 text-center"
        >
          <div
            class="w-20 h-20 rounded-2xl bg-muted border border-border flex items-center justify-center mb-5"
          >
            <Search class="w-10 h-10 text-muted-foreground/50" />
          </div>
          <p class="text-base font-semibold text-foreground">{{ t('common.no_results') }}</p>
          <p class="text-sm text-muted-foreground mt-1">{{ t('common.no_results_hint') }}</p>
        </div>
      </div>

      <!-- Pagination -->
      <footer
        class="shrink-0 border-t border-border bg-muted/30 px-8 py-3.5 flex items-center justify-between"
      >
        <p class="text-xs font-medium text-muted-foreground">
          {{ t('skills.pagination_show', { start: rangeStart, end: rangeEnd, total: totalCount }) }}
        </p>
        <div class="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            class="h-9 rounded-xl border-border text-muted-foreground hover:text-foreground hover:bg-muted/80"
            :disabled="currentPage <= 1"
            @click="goPrev"
          >
            <ChevronLeft class="w-4 h-4 mr-1" />
            {{ t('common.prev') }}
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="h-9 rounded-xl border-border text-muted-foreground hover:text-foreground hover:bg-muted/80"
            :disabled="currentPage >= totalPages"
            @click="goNext"
          >
            {{ t('common.next') }}
            <ChevronRight class="w-4 h-4 ml-1" />
          </Button>
        </div>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.2);
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.35);
}
</style>
