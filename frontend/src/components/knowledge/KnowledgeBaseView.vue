<script setup lang="ts">
import { ref, computed, onMounted, Teleport } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { 
  Search, 
  Bell, 
  Plus,
  FileText,
  Layers,
  Database,
  Folder,
  Users,
  File,
  Globe,
  CheckCircle2,
  Loader2,
  AlertCircle,
  LayoutGrid,
  List as ListIcon,
  Filter,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Trash2
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { listKnowledgeBases, listDocuments, listChunks, deleteKnowledgeBase } from '@/services/api'

const router = useRouter()
const { t } = useI18n()

// Knowledge Base data types
interface KnowledgeBase {
  id: string
  name: string
  description?: string
  embedding_model_id: string
  created_at: string
  sourceType?: string
  status?: 'READY' | 'INDEXING' | 'ERROR'
  docs?: number
  chunks?: number
  embeddingModel?: string
  lastIndexed?: string
  icon?: any
}

// Real data
const knowledgeBases = ref<KnowledgeBase[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const deletingKbId = ref<string | null>(null)
const showDeleteDialog = ref(false)
const kbToDelete = ref<KnowledgeBase | null>(null)

// State
const searchQuery = ref('')
const activeTab = ref<'all' | 'internal' | 'customer'>('all')
const viewMode = ref<'list' | 'grid'>('list')
const currentPage = ref(1)
const itemsPerPage = 10

// Statistics (computed from real data)
const totalDocuments = computed(() => {
  return knowledgeBases.value.reduce((sum, kb) => sum + (kb.docs || 0), 0)
})

// 计算今天上传的文档数
const documentsToday = computed(() => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  
  return knowledgeBases.value.reduce((sum, kb) => {
    if (!kb.docs) return sum
    // 这里需要从文档的 created_at 计算，但由于我们没有直接访问所有文档，
    // 我们先简化为 0，待后端提供聚合 API 时再实现
    return sum
  }, 0)
})

const totalChunks = computed(() => {
  return knowledgeBases.value.reduce((sum, kb) => sum + (kb.chunks || 0), 0)
})

// 计算平均 tokens/chunk（基于默认 chunk size 512）
const avgTokensPerChunk = computed(() => {
  // 默认使用 512，这是创建知识库时的默认值
  // 如果需要精确计算，需要后端提供每个 KB 的 chunk_size 配置
  return 512
})

const vectorStorage = ref(0) // TODO: Calculate actual storage size from backend
const storageBackend = ref('SQLite-vec')

// System status
const indexingQueueStatus = ref<'idle' | 'active'>('idle')

// Load knowledge bases
const loadKnowledgeBases = async () => {
  loading.value = true
  error.value = null
  try {
    const response = await listKnowledgeBases()
    const kbs = response.data || []
    
    // Load additional data for each KB
    const enrichedKBs = await Promise.all(
      kbs.map(async (kb: any) => {
        try {
          // Load documents count
          const docsResponse = await listDocuments(kb.id)
          const docs = docsResponse.data || []
          const docsCount = docs.length
          
          // Load chunks count
          const chunksResponse = await listChunks(kb.id, 1) // Just get total
          const chunksCount = chunksResponse.total || 0
          
          // Determine status based on documents
          let status: 'READY' | 'INDEXING' | 'ERROR' = 'READY'
          const hasIndexing = docs.some((d: any) => 
            d.status === 'PARSING' || 
            d.status === 'CHUNKING' || 
            d.status === 'EMBEDDING' ||
            d.status === 'INDEXING'
          )
          const hasError = docs.some((d: any) => 
            d.status === 'FAILED_PARSE' || 
            d.status === 'FAILED_EMBED'
          )
          
          if (hasIndexing) {
            status = 'INDEXING'
          } else if (hasError) {
            status = 'ERROR'
          }
          
          // Map embedding model ID to display name
          const embeddingModel = kb.embedding_model_id || 'Unknown'
          
          // Format last indexed (use most recent document updated_at)
          let lastIndexed = t('common.time.never')
          if (docs.length > 0) {
            const mostRecent = docs.reduce((latest: any, doc: any) => {
              const docDate = new Date(doc.updated_at || doc.created_at)
              const latestDate = latest ? new Date(latest.updated_at || latest.created_at) : new Date(0)
              return docDate > latestDate ? doc : latest
            }, null)
            
            if (mostRecent) {
              const date = new Date(mostRecent.updated_at || mostRecent.created_at)
              const now = new Date()
              const diffMs = now.getTime() - date.getTime()
              const diffMins = Math.floor(diffMs / 60000)
              const diffHours = Math.floor(diffMs / 3600000)
              const diffDays = Math.floor(diffMs / 86400000)
              
              if (diffMins < 1) {
                lastIndexed = t('common.time.just_now')
              } else if (diffMins < 60) {
                lastIndexed = diffMins === 1 ? t('common.time.min_ago', { n: diffMins }) : t('common.time.mins_ago', { n: diffMins })
              } else if (diffHours < 24) {
                lastIndexed = diffHours === 1 ? t('common.time.hour_ago', { n: diffHours }) : t('common.time.hours_ago', { n: diffHours })
              } else if (diffDays < 7) {
                lastIndexed = diffDays === 1 ? t('common.time.day_ago', { n: diffDays }) : t('common.time.days_ago', { n: diffDays })
              } else {
                lastIndexed = date.toLocaleDateString()
              }
            }
          }
          
          // Determine icon based on description or default
          let icon = Folder
          const desc = (kb.description || '').toLowerCase()
          if (desc.includes('wiki') || desc.includes('notion')) {
            icon = Globe
          } else if (desc.includes('pdf') || desc.includes('document')) {
            icon = File
          } else if (desc.includes('team') || desc.includes('project')) {
            icon = Users
          }
          
          return {
            ...kb,
            sourceType: 'LOCAL STORAGE',
            status,
            docs: docsCount,
            chunks: chunksCount,
            embeddingModel,
            lastIndexed,
            icon,
          }
        } catch (err) {
          console.error(`Failed to load data for KB ${kb.id}:`, err)
          return {
            ...kb,
            sourceType: 'LOCAL STORAGE',
            status: 'ERROR' as const,
            docs: 0,
            chunks: 0,
            embeddingModel: kb.embedding_model_id || t('common.time.unknown'),
            lastIndexed: t('common.time.unknown'),
            icon: Folder,
          }
        }
      })
    )
    
    knowledgeBases.value = enrichedKBs
    
    // Update indexing queue status
    const hasIndexing = enrichedKBs.some(kb => kb.status === 'INDEXING')
    indexingQueueStatus.value = hasIndexing ? 'active' : 'idle'
    
  } catch (err) {
    console.error('Failed to load knowledge bases:', err)
    error.value = err instanceof Error ? err.message : 'Failed to load knowledge bases'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadKnowledgeBases()
})

// Filtered knowledge bases
const filteredBases = computed(() => {
  let result = knowledgeBases.value

  // Filter by tab (simplified - all are local storage for now)
  // Keep tab filtering for future use
  if (activeTab.value === 'internal') {
    // For now, show all
  } else if (activeTab.value === 'customer') {
    // For now, show all
  }

  // Filter by search query
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(kb => 
      kb.name.toLowerCase().includes(query) ||
      (kb.description || '').toLowerCase().includes(query) ||
      (kb.embeddingModel || '').toLowerCase().includes(query) ||
      (kb.sourceType || '').toLowerCase().includes(query)
    )
  }

  return result
})

// Pagination
const paginatedBases = computed(() => {
  const start = (currentPage.value - 1) * itemsPerPage
  const end = start + itemsPerPage
  return filteredBases.value.slice(start, end)
})

const totalPages = computed(() => Math.ceil(filteredBases.value.length / itemsPerPage))

// Status badge colors
const getStatusColor = (status: string) => {
  switch (status) {
    case 'READY':
      return 'bg-green-500/20 text-green-400 border-green-500/30'
    case 'INDEXING':
      return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
    case 'ERROR':
      return 'bg-red-500/20 text-red-400 border-red-500/30'
    default:
      return 'bg-muted/20 text-muted-foreground border-border/30'
  }
}

const formatNumber = (num: number) => {
  if (num >= 1000) {
    return (num / 1000).toFixed(1) + 'k'
  }
  return num.toString()
}

// Delete knowledge base
const confirmDelete = (kb: KnowledgeBase, event: Event) => {
  event.stopPropagation()
  kbToDelete.value = kb
  showDeleteDialog.value = true
}

const handleDelete = async () => {
  if (!kbToDelete.value) return
  
  const kbId = kbToDelete.value.id
  deletingKbId.value = kbId
  
  try {
    await deleteKnowledgeBase(kbId)
    // 重新加载列表
    await loadKnowledgeBases()
    showDeleteDialog.value = false
    kbToDelete.value = null
  } catch (err) {
    console.error('Failed to delete knowledge base:', err)
    error.value = err instanceof Error ? err.message : 'Failed to delete knowledge base'
  } finally {
    deletingKbId.value = null
  }
}
</script>

<template>
  <div class="flex-1 flex flex-col overflow-hidden bg-background">
    <!-- Top Navigation Bar -->
    <header class="h-14 border-b border-border/50 flex items-center justify-between px-8 bg-background/50 backdrop-blur-md">
      <div class="flex-1 max-w-md">
        <div class="relative">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            v-model="searchQuery"
            :placeholder="t('knowledge.search_placeholder')"
            class="pl-9 h-9 bg-background/50 border-border/40 text-sm"
          />
        </div>
      </div>
    
      <div class="flex items-center gap-4">
        <Button variant="ghost" size="icon" class="h-9 w-9">
          <Bell class="w-4 h-4" />
        </Button>
        <Button class="h-9 px-4" @click="$router.push({ name: 'knowledge-create' })">
          <Plus class="w-4 h-4 mr-2" />
          {{ t('knowledge.new_kb') }}
        </Button>
      </div>
    </header>
    
    <!-- Main Content -->
    <div class="flex-1 overflow-auto">
      <div class="max-w-7xl mx-auto px-8 py-6">
        <!-- Header Section -->
        <div class="flex items-start justify-between mb-6">
          <div>
            <h1 class="text-3xl font-bold mb-2">{{ t('knowledge.title') }}</h1>
            <p class="text-sm text-muted-foreground">
              {{ t('knowledge.subtitle') }}
            </p>
          </div>

          <!-- System Status Cards -->
          <div class="flex items-center gap-3">
            <div class="px-3 py-2 bg-background/50 border border-border/50 rounded-lg flex items-center gap-2">
              <div class="w-2 h-2 rounded-full bg-green-500"></div>
              <span class="text-xs font-medium">{{ t('knowledge.engine_active') }}</span>
            </div>
            <div class="px-3 py-2 bg-background/50 border border-border/50 rounded-lg flex items-center gap-2">
              <RefreshCw 
                class="w-3 h-3 text-muted-foreground" 
                :class="indexingQueueStatus === 'active' ? 'animate-spin' : ''"
              />
              <span class="text-xs font-medium">
                {{ t('knowledge.indexing_queue') }}: {{ indexingQueueStatus === 'active' ? t('knowledge.active') : t('knowledge.idle') }}
              </span>
              <span class="text-xs text-muted-foreground">
                {{ indexingQueueStatus === 'active' ? t('knowledge.processing') : t('knowledge.ready_tasks') }}
              </span>
            </div>
          </div>
        </div>

        <!-- Statistics Cards -->
        <div class="grid grid-cols-3 gap-4 mb-6">
          <!-- Total Documents -->
          <div class="p-4 bg-background/50 border border-border/50 rounded-lg">
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-2">
                <FileText class="w-4 h-4 text-muted-foreground" />
                <span class="text-xs font-medium text-muted-foreground">{{ t('knowledge.stats.total_docs') }}</span>
              </div>
            </div>
            <div class="flex items-baseline gap-2">
              <span class="text-2xl font-bold">{{ formatNumber(totalDocuments) }}</span>
              <span v-if="documentsToday > 0" class="text-xs text-green-400">+{{ documentsToday }} {{ t('knowledge.stats.today') }}</span>
            </div>
          </div>

          <!-- Total Chunks -->
          <div class="p-4 bg-background/50 border border-border/50 rounded-lg">
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-2">
                <Layers class="w-4 h-4 text-muted-foreground" />
                <span class="text-xs font-medium text-muted-foreground">{{ t('knowledge.stats.total_chunks') }}</span>
              </div>
            </div>
            <div class="flex items-baseline gap-2">
              <span class="text-2xl font-bold">{{ formatNumber(totalChunks) }}</span>
            </div>
            <div v-if="totalChunks > 0" class="text-xs text-muted-foreground mt-1">{{ t('knowledge.stats.avg_tokens', { n: avgTokensPerChunk }) }}</div>
          </div>

          <!-- Vector Storage -->
          <div class="p-4 bg-background/50 border border-border/50 rounded-lg">
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-2">
                <Database class="w-4 h-4 text-muted-foreground" />
                <span class="text-xs font-medium text-muted-foreground">{{ t('knowledge.stats.vector_storage') }}</span>
              </div>
            </div>
            <div class="flex items-baseline gap-2">
              <span class="text-2xl font-bold">{{ vectorStorage }} GB</span>
            </div>
            <div class="text-xs text-muted-foreground mt-1">{{ storageBackend }}</div>
          </div>
        </div>

        <!-- Filters and Controls -->
        <div class="flex items-center justify-between mb-4">
          <div class="flex items-center gap-1">
            <button
              v-for="tab in [
                { id: 'all', label: t('knowledge.tabs.all') },
                { id: 'internal', label: t('knowledge.tabs.internal') },
                { id: 'customer', label: t('knowledge.tabs.customer') }
              ]"
              :key="tab.id"
              @click="activeTab = tab.id as any"
              class="px-3 py-1.5 text-xs font-semibold rounded transition-colors"
              :class="activeTab === tab.id 
                ? 'bg-primary text-primary-foreground' 
                : 'bg-muted/30 text-muted-foreground hover:bg-muted/50'"
            >
              {{ tab.label }}
            </button>
          </div>

          <div class="flex items-center gap-2">
            <Button variant="ghost" size="sm" class="h-8">
              <Filter class="w-4 h-4 mr-2" />
              {{ t('knowledge.filter') }}
            </Button>
            <div class="flex items-center gap-1 p-1 bg-muted/30 rounded">
              <Button
                variant="ghost"
                size="sm"
                class="h-7 w-7 p-0"
                :class="viewMode === 'list' ? 'bg-background' : ''"
                @click="viewMode = 'list'"
              >
                <ListIcon class="w-4 h-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                class="h-7 w-7 p-0"
                :class="viewMode === 'grid' ? 'bg-background' : ''"
                @click="viewMode = 'grid'"
              >
                <LayoutGrid class="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>

        <!-- Loading State -->
        <div v-if="loading" class="text-center py-12 text-muted-foreground">
          <Loader2 class="w-8 h-8 mx-auto mb-2 animate-spin" />
          <p>{{ t('knowledge.loading') }}</p>
        </div>

        <!-- Error State -->
        <div v-else-if="error" class="text-center py-12">
          <AlertCircle class="w-8 h-8 mx-auto mb-2 text-red-400" />
          <p class="text-red-400">{{ error }}</p>
          <Button variant="outline" class="mt-4" @click="loadKnowledgeBases">
            <RefreshCw class="w-4 h-4 mr-2" />
            {{ t('knowledge.retry') }}
          </Button>
        </div>

        <!-- Knowledge Base Table -->
        <div v-else class="bg-background/50 border border-border/50 rounded-lg overflow-hidden">
          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-border/50">
                  <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    {{ t('knowledge.table.name') }}
                  </th>
                  <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    {{ t('knowledge.table.status') }}
                  </th>
                  <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    {{ t('knowledge.table.docs') }}
                  </th>
                  <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    {{ t('knowledge.table.chunks') }}
                  </th>
                  <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    {{ t('knowledge.table.model') }}
                  </th>
                  <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    {{ t('knowledge.table.last_indexed') }}
                  </th>
                  <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    {{ t('knowledge.table.actions') }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-if="paginatedBases.length === 0"
                  class="border-b border-border/30"
                >
                  <td colspan="7" class="px-4 py-12 text-center text-muted-foreground">
                    <Folder class="w-12 h-12 mx-auto mb-2 opacity-50" />
                    <p>{{ t('knowledge.no_kbs') }}</p>
                    <Button variant="outline" class="mt-4" @click="$router.push({ name: 'knowledge-create' })">
                      <Plus class="w-4 h-4 mr-2" />
                      {{ t('knowledge.create_kb') }}
                    </Button>
                  </td>
                </tr>
                <tr
                  v-for="kb in paginatedBases"
                  :key="kb.id"
                  class="border-b border-border/30 hover:bg-muted/20 transition-colors cursor-pointer"
                  @click="router.push({ name: 'knowledge-detail', params: { id: kb.id } })"
                >
                  <td class="px-4 py-3">
                    <div class="flex items-center gap-3">
                      <component :is="kb.icon || Folder" class="w-5 h-5 text-muted-foreground" />
                      <div>
                        <div class="font-medium text-sm">{{ kb.name }}</div>
                        <div class="text-xs text-muted-foreground">{{ kb.sourceType || 'LOCAL STORAGE' }}</div>
                      </div>
                    </div>
                  </td>
                  <td class="px-4 py-3">
                    <Badge 
                      variant="outline" 
                      class="text-xs"
                      :class="getStatusColor(kb.status || 'READY')"
                    >
                      <component 
                        :is="kb.status === 'READY' ? CheckCircle2 : kb.status === 'INDEXING' ? Loader2 : AlertCircle"
                        class="w-3 h-3 mr-1"
                        :class="kb.status === 'INDEXING' ? 'animate-spin' : ''"
                      />
                      {{ kb.status === 'READY' ? t('common.status.ready') : (kb.status === 'INDEXING' ? t('common.status.indexing') : t('common.status.error')) }}
                    </Badge>
                  </td>
                  <td class="px-4 py-3 text-sm">{{ (kb.docs || 0).toLocaleString() }}</td>
                  <td class="px-4 py-3 text-sm">{{ (kb.chunks || 0).toLocaleString() }}</td>
                  <td class="px-4 py-3">
                    <span class="text-sm text-blue-400">
                      {{ kb.embeddingModel || kb.embedding_model_id || 'Unknown' }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-sm text-muted-foreground">{{ kb.lastIndexed || 'Never' }}</td>
                  <td class="px-4 py-3" @click.stop>
                    <div class="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-8"
                        @click="router.push({ name: 'knowledge-detail', params: { id: kb.id } })"
                      >
                        {{ t('knowledge.table.view') }}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-8 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                        :disabled="deletingKbId === kb.id"
                        @click="confirmDelete(kb, $event)"
                      >
                        <Trash2 
                          v-if="deletingKbId !== kb.id"
                          class="w-4 h-4" 
                        />
                        <Loader2 
                          v-else
                          class="w-4 h-4 animate-spin" 
                        />
                      </Button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Footer / Pagination -->
          <div class="px-4 py-3 border-t border-border/50 flex items-center justify-between">
            <div class="text-xs text-muted-foreground">
              {{ t('knowledge.pagination.showing', { count: paginatedBases.length, total: filteredBases.length }) }}
            </div>
            <div class="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                class="h-8 w-8 p-0"
                :disabled="currentPage === 1"
                @click="currentPage--"
              >
                <ChevronLeft class="w-4 h-4" />
              </Button>
              <div class="flex items-center gap-1">
                <button
                  v-for="page in totalPages"
                  :key="page"
                  @click="currentPage = page"
                  class="h-8 w-8 text-xs rounded transition-colors"
                  :class="currentPage === page 
                    ? 'bg-primary text-primary-foreground' 
                    : 'bg-muted/30 text-muted-foreground hover:bg-muted/50'"
                >
                  {{ page }}
                </button>
              </div>
              <Button
                variant="ghost"
                size="sm"
                class="h-8 w-8 p-0"
                :disabled="currentPage === totalPages"
                @click="currentPage++"
              >
                <ChevronRight class="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Dialog -->
    <Teleport to="body">
      <div
        v-if="showDeleteDialog"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="showDeleteDialog = false"
      >
        <div class="bg-background border border-border rounded-lg shadow-lg p-6 max-w-md w-full mx-4">
          <h3 class="text-lg font-semibold mb-2">{{ t('knowledge.delete_dialog.title') }}</h3>
          <p class="text-sm text-muted-foreground mb-4">
            {{ t('knowledge.delete_dialog.confirm', { name: kbToDelete?.name }) }}
            {{ t('knowledge.delete_dialog.warning') }}
          </p>
          <div class="flex items-center justify-end gap-2">
            <Button
              variant="outline"
              size="sm"
              @click="showDeleteDialog = false"
              :disabled="deletingKbId !== null"
            >
              {{ t('knowledge.delete_dialog.cancel') }}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              @click="handleDelete"
              :disabled="deletingKbId !== null"
            >
              <Loader2 v-if="deletingKbId !== null" class="w-4 h-4 mr-2 animate-spin" />
              <Trash2 v-else class="w-4 h-4 mr-2" />
              {{ t('knowledge.delete_dialog.delete') }}
            </Button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* Additional styles if needed */
</style>