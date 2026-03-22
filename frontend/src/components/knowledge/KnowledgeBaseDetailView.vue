<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
const { t, locale } = useI18n()
import {
  ChevronLeft,
  Upload,
  RefreshCw,
  CheckCircle2,
  Loader2,
  AlertCircle,
  FileText,
  Layers,
  Settings,
  Search,
  Trash2,
  Edit2,
  Save,
  X,
  Info,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Slider } from '@/components/ui/slider'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getKnowledgeBase, listDocuments, uploadDocument, listChunks, deleteDocument, updateKnowledgeBase, reindexDocument, getKnowledgeBaseStats, searchKnowledgeBase, type SearchResult } from '@/services/api'

const route = useRoute()
const router = useRouter()

const kbId = computed(() => route.params.id as string)

// Knowledge Base Info
const kbInfo = ref<any>(null)
const loading = ref(false)
const editingDescription = ref(false)
const descriptionInput = ref('')
const savingDescription = ref(false)

// Stats
const stats = ref({
  totalChunks: 0,
  totalFiles: 0,
  indexLatency: 0, // ms - will be calculated from backend metrics when available
  diskSize: '0 MB', // Will be calculated from backend when available
})

// Active Tab
const activeTab = ref<'documents' | 'chunks' | 'retrieval' | 'settings'>('documents')

// Documents
const documents = ref<any[]>([])
const uploading = ref(false)
const dragOver = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const uploadError = ref<string | null>(null)
const uploadSuccess = ref<string | null>(null)
const deletingDocId = ref<string | null>(null)
const reindexingDocId = ref<string | null>(null)
const showDeleteConfirm = ref(false)
const docToDelete = ref<any>(null)
let statusPollingTimer: any = null

// Chunks
const chunks = ref<any[]>([])
const chunkSortBy = ref<'sequence' | 'relevance'>('sequence')

// Retrieval Settings
const similarityThreshold = ref([0.82])
const topKResults = ref([5])
const searchType = ref<'dense' | 'hybrid'>('dense')
const searchQuery = ref('')
const searchResults = ref<SearchResult[]>([])
const searching = ref(false)

// Indexing Settings
const chunkSize = ref(512)
const chunkOverlap = ref(15)

// Load knowledge base info
const loadKBInfo = async () => {
  try {
    loading.value = true
    const info = await getKnowledgeBase(kbId.value)
    kbInfo.value = info
    
    // Use new stats API
    try {
      const statsData = await getKnowledgeBaseStats(kbId.value)
      stats.value.totalChunks = statsData.chunk_count
      stats.value.totalFiles = statsData.document_count
      
      // Format disk size
      const totalBytes = statsData.disk_size.total_size
      if (totalBytes < 1024) {
        stats.value.diskSize = `${totalBytes} B`
      } else if (totalBytes < 1024 * 1024) {
        stats.value.diskSize = `${(totalBytes / 1024).toFixed(1)} KB`
      } else {
        stats.value.diskSize = `${(totalBytes / (1024 * 1024)).toFixed(1)} MB`
      }
    } catch (err) {
      console.error('Failed to load stats:', err)
      // Fallback to old method
      const docs = await listDocuments(kbId.value)
      stats.value.totalFiles = docs.data?.length || 0
      const chunksData = await listChunks(kbId.value)
      stats.value.totalChunks = chunksData.total || 0
    }
    
    // Load documents list
    const docs = await listDocuments(kbId.value)
    documents.value = docs.data || []
    
    // Index latency - currently not available from backend
    stats.value.indexLatency = 0
    
    // Start polling if KB is indexing
    const kbStatus = kbInfo.value?.status || 'READY'
    if (kbStatus === 'INDEXING') {
      startStatusPolling()
    } else {
      stopStatusPolling()
    }
  } catch (err) {
    console.error('Failed to load knowledge base:', err)
  } finally {
    loading.value = false
  }
}

// Start polling for status updates
const startStatusPolling = () => {
  if (statusPollingTimer) return
  
  statusPollingTimer = setInterval(async () => {
    try {
      // Reload KB info to get updated status
      const info = await getKnowledgeBase(kbId.value)
      kbInfo.value = info
      
      const docs = await listDocuments(kbId.value)
      documents.value = docs.data || []
      
      // Update chunks count
      const chunksData = await listChunks(kbId.value)
      stats.value.totalChunks = chunksData.total || 0
      
      // Stop polling if KB is not indexing anymore
      const kbStatus = info.status || 'READY'
      if (kbStatus !== 'INDEXING') {
        stopStatusPolling()
      }
    } catch (err) {
      console.error('Failed to poll status:', err)
    }
  }, 2000) // Poll every 2 seconds
}

// Stop polling
const stopStatusPolling = () => {
  if (statusPollingTimer) {
    clearInterval(statusPollingTimer)
    statusPollingTimer = null
  }
}

// Load chunks when chunks tab is active
const loadChunks = async () => {
  try {
    const chunksData = await listChunks(kbId.value, 50)
    chunks.value = chunksData.data || []
  } catch (err) {
    console.error('Failed to load chunks:', err)
    chunks.value = []
  }
}

// Watch activeTab to load chunks when switching to chunks tab
watch(activeTab, (newTab) => {
  if (newTab === 'chunks' && chunks.value.length === 0) {
    loadChunks()
  }
})

onMounted(() => {
  loadKBInfo()
})

// Cleanup on unmount
onUnmounted(() => {
  stopStatusPolling()
})

// File upload handlers
const handleFileSelect = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (files && files.length > 0) {
    await uploadFiles(Array.from(files))
    // Reset file input to allow selecting the same file again
    if (target) {
      target.value = ''
    }
  }
}

const handleDrop = async (event: DragEvent) => {
  event.preventDefault()
  dragOver.value = false
  
  const files = event.dataTransfer?.files
  if (files && files.length > 0) {
    await uploadFiles(Array.from(files))
  }
}

const handleDragOver = (event: DragEvent) => {
  event.preventDefault()
  dragOver.value = true
}

const handleDragLeave = () => {
  dragOver.value = false
}

const uploadFiles = async (files: File[]) => {
  uploading.value = true
  uploadError.value = null
  uploadSuccess.value = null
  
  try {
    // Validate files
    const allowedExtensions = ['.pdf', '.txt', '.md', '.docx']
    const maxSize = 20 * 1024 * 1024 // 20MB
    
    for (const file of files) {
      const ext = '.' + file.name.split('.').pop()?.toLowerCase()
      if (!allowedExtensions.includes(ext)) {
        throw new Error(t('knowledge.detail.messages.err_file_type', { ext }))
      }
      
      if (file.size > maxSize) {
        throw new Error(t('knowledge.detail.messages.err_file_size', { name: file.name }))
      }
    }
    
    // Upload files
    const uploadPromises = files.map(file => uploadDocument(kbId.value, file))
    await Promise.all(uploadPromises)
    
    uploadSuccess.value = t('knowledge.detail.messages.upload_success', { n: files.length })
    
    // Reload KB info immediately to show uploading status
    await loadKBInfo()
    
    // Clear success message after 3 seconds
    setTimeout(() => {
      uploadSuccess.value = null
    }, 3000)
    
  } catch (err) {
    console.error('Failed to upload files:', err)
    uploadError.value = err instanceof Error ? err.message : t('knowledge.detail.messages.err_upload')
    // Clear error after 5 seconds
    setTimeout(() => {
      uploadError.value = null
    }, 5000)
  } finally {
    uploading.value = false
  }
}

// Delete document
const confirmDelete = (doc: any) => {
  docToDelete.value = doc
  showDeleteConfirm.value = true
}

const handleDelete = async () => {
  if (!docToDelete.value) return
  
  const docId = docToDelete.value.id
  deletingDocId.value = docId
  
  try {
    await deleteDocument(kbId.value, docId)
    await loadKBInfo()
    showDeleteConfirm.value = false
    docToDelete.value = null
  } catch (err) {
    console.error('Failed to delete document:', err)
    uploadError.value = err instanceof Error ? err.message : t('knowledge.detail.messages.err_delete')
    setTimeout(() => {
      uploadError.value = null
    }, 5000)
  } finally {
    deletingDocId.value = null
  }
}

// Reindex document
const handleReindex = async (docId: string) => {
  reindexingDocId.value = docId
  
  try {
    await reindexDocument(kbId.value, docId)
      uploadSuccess.value = t('knowledge.detail.messages.reindex_started')
    await loadKBInfo()
    setTimeout(() => {
      uploadSuccess.value = null
    }, 3000)
  } catch (err) {
    console.error('Failed to re-index document:', err)
    uploadError.value = err instanceof Error ? err.message : 'Failed to re-index document'
    setTimeout(() => {
      uploadError.value = null
    }, 5000)
  } finally {
    reindexingDocId.value = null
  }
}

// Format date
const formatDate = (dateStr: string) => {
  const date = new Date(dateStr)
  return date.toLocaleDateString(locale.value === 'zh' ? 'zh-CN' : 'en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

// Edit description
const startEditDescription = () => {
  descriptionInput.value = kbInfo.value?.description || ''
  editingDescription.value = true
}

const cancelEditDescription = () => {
  editingDescription.value = false
  descriptionInput.value = ''
}

const saveDescription = async () => {
  if (!kbInfo.value) return
  
  savingDescription.value = true
  try {
    const updated = await updateKnowledgeBase(kbId.value, {
      description: descriptionInput.value || undefined,
    })
    kbInfo.value = updated
    editingDescription.value = false
  } catch (err) {
    console.error('Failed to update description:', err)
    uploadError.value = err instanceof Error ? err.message : t('knowledge.detail.messages.err_update_desc')
    setTimeout(() => {
      uploadError.value = null
    }, 5000)
  } finally {
    savingDescription.value = false
  }
}

// Get status badge
const getStatusBadge = (status: string) => {
  switch (status) {
    // 文档状态
    case 'INDEXED':
      return { color: 'bg-green-500/20 text-green-400 border-green-500/30', icon: CheckCircle2 }
    case 'UPLOADED':
    case 'PARSING':
    case 'PARSED':
    case 'CHUNKING':
    case 'CHUNKED':
    case 'EMBEDDING':
      return { color: 'bg-blue-500/20 text-blue-400 border-blue-500/30', icon: Loader2, spinning: true }
    case 'FAILED_PARSE':
    case 'FAILED_EMBED':
      return { color: 'bg-red-500/20 text-red-400 border-red-500/30', icon: AlertCircle }
    // 知识库状态
    case 'READY':
      return { color: 'bg-green-500/20 text-green-400 border-green-500/30', icon: CheckCircle2 }
    case 'INDEXING':
      return { color: 'bg-blue-500/20 text-blue-400 border-blue-500/30', icon: Loader2, spinning: true }
    case 'ERROR':
      return { color: 'bg-red-500/20 text-red-400 border-red-500/30', icon: AlertCircle }
    case 'EMPTY':
      return { color: 'bg-muted/20 text-muted-foreground border-border/30', icon: FileText }
    default:
      return { color: 'bg-muted/20 text-muted-foreground border-border/30', icon: FileText }
  }
}

// Get status display text
const getStatusText = (status: string) => {
  switch (status) {
    case 'READY':
      return t('knowledge.detail.ready')
    case 'INDEXING':
      return t('knowledge.detail.indexing')
    case 'ERROR':
      return t('knowledge.detail.error')
    case 'EMPTY':
      return t('knowledge.detail.empty')
    default:
      return status
  }
}

// Sync Local (refresh data)
const handleSyncLocal = async () => {
  try {
    loading.value = true
    await loadKBInfo()
    uploadSuccess.value = t('knowledge.detail.upload_area.upload_success') || 'Data refreshed successfully'
    setTimeout(() => {
      uploadSuccess.value = null
    }, 3000)
  } catch (err) {
    console.error('Failed to sync:', err)
    uploadError.value = err instanceof Error ? err.message : t('knowledge.detail.messages.err_sync')
    setTimeout(() => {
      uploadError.value = null
    }, 5000)
  } finally {
    loading.value = false
  }
}

// Search knowledge base
const handleSearch = async () => {
  if (!searchQuery.value.trim()) {
    uploadError.value = t('knowledge.detail.search_placeholder')
    setTimeout(() => {
      uploadError.value = null
    }, 3000)
    return
  }
  
  searching.value = true
  searchResults.value = []
  
  try {
    const result = await searchKnowledgeBase(kbId.value, {
      query: searchQuery.value,
      top_k: topKResults.value[0],
      score_threshold: similarityThreshold.value[0],
    })
    searchResults.value = result.data || []
  } catch (err) {
    console.error('Failed to search:', err)
    uploadError.value = err instanceof Error ? err.message : t('knowledge.detail.messages.err_search')
    setTimeout(() => {
      uploadError.value = null
    }, 5000)
  } finally {
    searching.value = false
  }
}

// Re-index entire knowledge base
const reindexingKB = ref(false)
const handleReindexKnowledgeBase = async () => {
  if (!kbInfo.value) return
  
  // Confirm action
  if (!confirm(t('knowledge.detail.reindex_confirm') || 'Are you sure you want to re-index all documents in this knowledge base? This may take a while.')) {
    return
  }
  
  reindexingKB.value = true
  
  try {
    // Get all documents
    const docs = await listDocuments(kbId.value)
    const docList = docs.data || []
    
    if (docList.length === 0) {
      uploadError.value = 'No documents to re-index'
      setTimeout(() => {
        uploadError.value = null
      }, 3000)
      reindexingKB.value = false
      return
    }
    
    // Re-index each document and track results
    const reindexResults = await Promise.allSettled(
      docList.map(doc => reindexDocument(kbId.value, doc.id))
    )
    
    // Count successes and failures
    const successCount = reindexResults.filter(r => r.status === 'fulfilled').length
    const failureCount = reindexResults.filter(r => r.status === 'rejected').length
    
    // Log failures for debugging
    reindexResults.forEach((result, index) => {
      if (result.status === 'rejected') {
        console.error(`Failed to re-index document ${docList[index].id}:`, result.reason)
      }
    })
    
    // Show appropriate message
    if (failureCount === 0) {
      uploadSuccess.value = t('knowledge.detail.messages.reindex_success_all', { n: successCount })
    } else if (successCount === 0) {
      uploadError.value = t('knowledge.detail.messages.reindex_failed_all', { n: failureCount })
    } else {
      uploadSuccess.value = t('knowledge.detail.messages.reindex_partial', { success: successCount, failure: failureCount })
    }
    
    await loadKBInfo()
    
    setTimeout(() => {
      uploadSuccess.value = null
      uploadError.value = null
    }, failureCount > 0 ? 5000 : 3000)
  } catch (err) {
    console.error('Failed to re-index knowledge base:', err)
    uploadError.value = err instanceof Error ? err.message : 'Failed to re-index knowledge base'
    setTimeout(() => {
      uploadError.value = null
    }, 5000)
  } finally {
    reindexingKB.value = false
  }
}
</script>

<template>
  <div class="flex-1 flex flex-col overflow-hidden bg-background">
    <!-- Header -->
    <header class="min-h-14 border-b border-border/50 flex items-start justify-between px-8 py-3 bg-background/50 backdrop-blur-md">
      <div class="flex items-start gap-4 flex-1 min-w-0">
        <Button variant="ghost" size="icon" class="h-9 w-9 mt-0.5 flex-shrink-0" @click="router.push({ name: 'knowledge' })">
          <ChevronLeft class="w-4 h-4" />
        </Button>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <h1 class="text-lg font-semibold break-words min-w-0 flex-1" :title="kbInfo?.name || t('knowledge.detail.loading')">
              {{ kbInfo?.name || t('knowledge.detail.loading') }}
            </h1>
            <Badge 
              v-if="kbInfo" 
              variant="outline" 
              :class="getStatusBadge(kbInfo.status || 'READY').color"
              class="flex-shrink-0"
            >
              <component 
                :is="getStatusBadge(kbInfo.status || 'READY').icon"
                class="w-3 h-3 mr-1"
                :class="getStatusBadge(kbInfo.status || 'READY').spinning ? 'animate-spin' : ''"
              />
              {{ getStatusText(kbInfo.status || 'READY') }}
            </Badge>
          </div>
          <div class="flex items-center gap-4 text-xs text-muted-foreground mt-1 flex-wrap">
            <span>ID: {{ kbInfo?.id || '-' }}</span>
            <span>{{ t('knowledge.detail.created') }}: {{ kbInfo ? formatDate(kbInfo.created_at) : '-' }}</span>
            <span>{{ t('knowledge.detail.disk') }}: {{ stats.diskSize }}</span>
          </div>
          <!-- Description -->
          <div class="mt-2">
            <div v-if="!editingDescription" class="flex items-start gap-2">
              <p class="text-sm text-muted-foreground flex-1 break-words min-w-0">
                {{ kbInfo?.description || t('knowledge.detail.no_description') }}
              </p>
              <Button
                variant="ghost"
                size="icon"
                class="h-6 w-6 flex-shrink-0"
                @click="startEditDescription"
              >
                <Edit2 class="w-3 h-3" />
              </Button>
            </div>
            <div v-else class="flex items-start gap-2">
              <Input
                v-model="descriptionInput"
                :placeholder="t('knowledge.detail.enter_description')"
                class="flex-1 text-sm min-w-0"
                @keyup.enter="saveDescription"
                @keyup.esc="cancelEditDescription"
              />
              <Button
                variant="ghost"
                size="icon"
                class="h-6 w-6 flex-shrink-0"
                @click="saveDescription"
                :disabled="savingDescription"
              >
                <Save v-if="!savingDescription" class="w-3 h-3" />
                <Loader2 v-else class="w-3 h-3 animate-spin" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                class="h-6 w-6 flex-shrink-0"
                @click="cancelEditDescription"
                :disabled="savingDescription"
              >
                <X class="w-3 h-3" />
              </Button>
            </div>
          </div>
        </div>
      </div>

      <div class="flex items-center gap-3 flex-shrink-0 ml-4">
        <Button variant="outline" class="h-9" @click="handleSyncLocal" :disabled="loading">
          <RefreshCw :class="['w-4 h-4 mr-2', loading ? 'animate-spin' : '']" />
          {{ t('knowledge.detail.sync_local') }}
        </Button>
        <Button class="h-9" @click="() => { activeTab = 'documents'; fileInputRef?.click() }" :disabled="uploading">
          <Upload class="w-4 h-4 mr-2" />
          {{ t('knowledge.detail.upload_doc') }}
        </Button>
      </div>
    </header>

    <!-- Stats Cards -->
    <div class="px-8 py-4 border-b border-border/50">
      <div class="grid grid-cols-4 gap-4">
        <div class="p-4 bg-background/50 border border-border/50 rounded-lg">
          <div class="text-xs font-medium text-muted-foreground mb-1">{{ t('knowledge.detail.total_chunks_label') }}</div>
          <div class="text-2xl font-bold">{{ stats.totalChunks.toLocaleString() }}</div>
        </div>
        <div class="p-4 bg-background/50 border border-border/50 rounded-lg">
          <div class="text-xs font-medium text-muted-foreground mb-1">{{ t('knowledge.detail.embedding_model_label') }}</div>
          <div class="text-sm font-semibold">{{ kbInfo?.embedding_model_id || '-' }}</div>
        </div>
        <div class="p-4 bg-background/50 border border-border/50 rounded-lg">
          <div class="text-xs font-medium text-muted-foreground mb-1">{{ t('knowledge.detail.index_latency_label') }}</div>
          <div class="text-2xl font-bold">
            {{ stats.indexLatency > 0 ? `${stats.indexLatency}ms` : '-' }}
          </div>
          <div class="text-xs text-muted-foreground mt-1">{{ t('knowledge.detail.avg_query') }}</div>
        </div>
        <div class="p-4 bg-background/50 border border-border/50 rounded-lg">
          <div class="text-xs font-medium text-muted-foreground mb-1">{{ t('knowledge.detail.total_files_label') }}</div>
          <div class="text-2xl font-bold">{{ stats.totalFiles }}</div>
        </div>
      </div>
    </div>

    <!-- Main Content -->
    <div class="flex-1 flex overflow-hidden">
      <!-- Left Content -->
      <div class="flex-1 flex flex-col overflow-hidden">
        <!-- Tabs -->
        <div class="flex items-center gap-1 px-8 pt-4 border-b border-border/50">
          <button
            v-for="tab in [
              { id: 'documents', label: t('knowledge.detail.tabs.documents'), icon: FileText },
              { id: 'chunks', label: t('knowledge.detail.tabs.chunks'), icon: Layers },
              { id: 'retrieval', label: t('knowledge.detail.tabs.retrieval'), icon: Search },
              { id: 'settings', label: t('knowledge.detail.tabs.settings'), icon: Settings },
            ]"
            :key="tab.id"
            @click="activeTab = tab.id as any"
            class="px-4 py-2 text-sm font-medium transition-colors relative"
            :class="activeTab === tab.id
              ? 'text-primary border-b-2 border-primary'
              : 'text-muted-foreground hover:text-foreground'"
          >
            <component :is="tab.icon" class="w-4 h-4 inline mr-2" />
            {{ tab.label }}
          </button>
        </div>

        <!-- Tab Content -->
        <div class="flex-1 overflow-auto p-8">
          <!-- Documents Tab -->
          <div v-if="activeTab === 'documents'" class="space-y-6">
            <!-- Upload Area -->
            <div
              @drop="handleDrop"
              @dragover="handleDragOver"
              @dragleave="handleDragLeave"
              class="border-2 border-dashed border-border/50 rounded-lg p-12 text-center transition-colors"
              :class="[
                dragOver ? 'border-primary bg-primary/5' : 'hover:border-border',
                uploading ? 'opacity-50 pointer-events-none' : ''
              ]"
            >
              <Upload 
                class="w-12 h-12 mx-auto mb-4 text-muted-foreground"
                :class="uploading ? 'animate-pulse' : ''"
              />
              <p class="text-sm font-medium mb-1">
                {{ uploading ? t('knowledge.detail.upload_area.uploading') : t('knowledge.detail.upload_area.drag_drop') }}
              </p>
              <p class="text-xs text-muted-foreground mb-4">{{ t('knowledge.detail.upload_area.supported') }}</p>
              <input
                ref="fileInputRef"
                type="file"
                multiple
                accept=".pdf,.txt,.md,.docx"
                @change="handleFileSelect"
                class="hidden"
                id="file-upload"
                :disabled="uploading"
              />
              <Button 
                variant="outline" 
                @click="() => fileInputRef?.click()"
                :disabled="uploading"
              >
                <Upload class="w-4 h-4 mr-2" />
                {{ uploading ? t('knowledge.detail.upload_area.uploading') : t('knowledge.detail.upload_area.select_files') }}
              </Button>
              
              <!-- Success Message -->
              <div v-if="uploadSuccess" class="mt-4 p-3 bg-green-500/20 border border-green-500/30 rounded-lg">
                <p class="text-sm text-green-400">{{ uploadSuccess }}</p>
              </div>
              
              <!-- Error Message -->
              <div v-if="uploadError" class="mt-4 p-3 bg-red-500/20 border border-red-500/30 rounded-lg">
                <p class="text-sm text-red-400">{{ uploadError }}</p>
              </div>
            </div>

            <!-- Documents Table -->
            <div class="bg-background/50 border border-border/50 rounded-lg overflow-hidden">
              <table class="w-full">
                <thead>
                  <tr class="border-b border-border/50">
                    <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase">{{ t('knowledge.detail.table.name') }}</th>
                    <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase">{{ t('knowledge.detail.table.status') }}</th>
                    <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase">{{ t('knowledge.detail.table.chunks') }}</th>
                    <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase">{{ t('knowledge.detail.table.date') }}</th>
                    <th class="px-4 py-3 text-left text-xs font-semibold text-muted-foreground uppercase">{{ t('knowledge.detail.table.actions') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="doc in documents"
                    :key="doc.id"
                    class="border-b border-border/30 hover:bg-muted/20 transition-colors"
                  >
                    <td class="px-4 py-3">
                      <div class="flex items-center gap-2">
                        <FileText class="w-4 h-4 text-muted-foreground" />
                        <span class="text-sm font-medium">{{ doc.source }}</span>
                      </div>
                    </td>
                    <td class="px-4 py-3">
                      <Badge
                        variant="outline"
                        class="text-xs"
                        :class="getStatusBadge(doc.status || 'INDEXED').color"
                      >
                        <component
                          :is="getStatusBadge(doc.status || 'INDEXED').icon"
                          class="w-3 h-3 mr-1"
                          :class="getStatusBadge(doc.status || 'INDEXED').spinning ? 'animate-spin' : ''"
                        />
                        {{ t(`common.status.${(doc.status || 'INDEXED').toLowerCase()}`) || doc.status || 'INDEXED' }}
                      </Badge>
                    </td>
                    <td class="px-4 py-3 text-sm">{{ doc.chunks_count || doc.chunks || 0 }}</td>
                    <td class="px-4 py-3 text-sm text-muted-foreground">{{ formatDate(doc.created_at) }}</td>
                    <td class="px-4 py-3">
                      <div class="flex items-center gap-1">
                        <!-- Re-index Button (for INDEXED or FAILED documents) -->
                        <Button
                          v-if="['INDEXED', 'FAILED_PARSE', 'FAILED_EMBED'].includes(doc.status)"
                          variant="ghost"
                          size="icon"
                          class="h-8 w-8"
                          @click.stop="handleReindex(doc.id)"
                          :disabled="reindexingDocId === doc.id"
                          :title="t('knowledge.detail.reindex_doc')"
                        >
                          <RefreshCw
                            :class="[
                              'w-4 h-4 text-muted-foreground hover:text-blue-400 transition-colors',
                              reindexingDocId === doc.id ? 'animate-spin' : ''
                            ]"
                          />
                        </Button>
                        <!-- Delete Button -->
                        <Button 
                          variant="ghost" 
                          size="icon" 
                          class="h-8 w-8"
                          @click.stop="confirmDelete(doc)"
                          :disabled="deletingDocId === doc.id"
                          :title="t('knowledge.detail.delete_doc')"
                        >
                          <Trash2 
                            v-if="deletingDocId === doc.id"
                            class="w-4 h-4 animate-spin text-red-400" 
                          />
                          <Trash2 
                            v-else
                            class="w-4 h-4 text-muted-foreground hover:text-red-400 transition-colors" 
                          />
                        </Button>
                      </div>
                    </td>
                  </tr>
                  <tr v-if="documents.length === 0">
                    <td colspan="5" class="px-4 py-8 text-center text-sm text-muted-foreground">
                      {{ t('knowledge.detail.no_docs') }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Chunks Tab -->
          <div v-if="activeTab === 'chunks'" class="space-y-4">
            <div class="flex items-center justify-between">
              <h2 class="text-lg font-semibold">{{ t('knowledge.detail.recent_chunks') }}</h2>
              <Select v-model="chunkSortBy">
                <SelectTrigger class="w-[140px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="sequence">{{ t('knowledge.detail.sort_sequence') }}</SelectItem>
                  <SelectItem value="relevance">{{ t('knowledge.detail.sort_relevance') }}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div class="space-y-3">
              <div
                v-for="chunk in chunks"
                :key="chunk.chunk_id"
                class="p-4 bg-background/50 border border-border/50 rounded-lg"
              >
                <div class="flex items-start justify-between mb-2">
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-mono text-muted-foreground">#{{ chunk.chunk_id }}</span>
                    <span class="text-xs text-muted-foreground">INDEX: {{ chunk.index || 0 }}</span>
                  </div>
                  <span class="text-xs text-muted-foreground">{{ chunk.document_id }}</span>
                </div>
                <p class="text-sm text-foreground/80">{{ chunk.content }}</p>
              </div>
              <div v-if="chunks.length === 0" class="text-center py-8 text-sm text-muted-foreground">
                {{ t('knowledge.detail.no_chunks') }}
              </div>
            </div>
          </div>

          <!-- Retrieval Tab -->
          <div v-if="activeTab === 'retrieval'" class="max-w-2xl">
            <h2 class="text-lg font-semibold mb-6">{{ t('knowledge.detail.retrieval_testing') }}</h2>
            <div class="space-y-6">
              <div class="p-4 bg-background/50 border border-border/50 rounded-lg">
                <div class="flex items-start gap-2 mb-4 p-2 bg-blue-500/10 border border-blue-500/20 rounded-md">
                  <Info class="w-4 h-4 text-blue-400 flex-shrink-0 mt-0.5" />
                  <div class="text-xs text-blue-300">
                    <p class="font-medium mb-1">{{ t('knowledge.detail.search_tips') }}</p>
                    <ul class="list-disc list-inside space-y-0.5 text-blue-200/80">
                      <li>{{ t('knowledge.detail.tip1') }}</li>
                      <li>{{ t('knowledge.detail.tip2') }}</li>
                      <li>{{ t('knowledge.detail.tip3') }}</li>
                    </ul>
                  </div>
                </div>
                <Input 
                  v-model="searchQuery" 
                  :placeholder="t('knowledge.detail.search_placeholder')" 
                  class="mb-4"
                  @keyup.enter="handleSearch"
                  :disabled="searching"
                />
                <Button class="w-full" @click="handleSearch" :disabled="searching || !searchQuery.trim()">
                  <Search :class="['w-4 h-4 mr-2', searching ? 'animate-spin' : '']" />
                  {{ searching ? t('knowledge.detail.searching') : t('knowledge.detail.search') }}
                </Button>
              </div>
              
              <!-- Success Message -->
              <div v-if="uploadSuccess" class="p-3 bg-green-500/20 border border-green-500/30 rounded-lg">
                <p class="text-sm text-green-400">{{ uploadSuccess }}</p>
              </div>
              
              <!-- Error Message -->
              <div v-if="uploadError" class="p-3 bg-red-500/20 border border-red-500/30 rounded-lg">
                <p class="text-sm text-red-400">{{ uploadError }}</p>
              </div>
              
              <!-- Search Results -->
              <div v-if="searchResults.length > 0" class="space-y-3">
                <h3 class="text-sm font-semibold">{{ t('knowledge.detail.results', { n: searchResults.length }) }}</h3>
                <div
                  v-for="(result, index) in searchResults"
                  :key="index"
                  class="p-4 bg-background/50 border border-border/50 rounded-lg"
                >
                  <div class="flex items-start justify-between mb-2">
                    <span class="text-xs font-mono text-muted-foreground">#{{ index + 1 }}</span>
                    <div class="flex items-center gap-2 text-xs text-muted-foreground">
                      <span>{{ t('knowledge.detail.score') }}: {{ result.score.toFixed(3) }}</span>
                      <span>{{ t('knowledge.detail.distance') }}: {{ result.distance.toFixed(3) }}</span>
                    </div>
                  </div>
                  <p class="text-sm text-foreground/80">{{ result.content }}</p>
                </div>
              </div>
              
              <div v-else-if="!searching && searchResults.length === 0" class="text-sm text-muted-foreground">
                {{ t('knowledge.detail.retrieval_prompt') }}
              </div>
              
              <div v-if="searching" class="text-sm text-muted-foreground text-center py-4">
                <Loader2 class="w-4 h-4 inline animate-spin mr-2" />
                {{ t('knowledge.detail.searching') }}
              </div>
            </div>
          </div>

          <!-- Settings Tab -->
          <div v-if="activeTab === 'settings'" class="max-w-2xl">
            <h2 class="text-lg font-semibold mb-6">{{ t('knowledge.detail.indexing_config') }}</h2>
            <div class="space-y-6">
              <div class="p-4 bg-background/50 border border-border/50 rounded-lg">
                <label class="text-sm font-medium mb-2 block uppercase">{{ t('knowledge.detail.chunk_size_label') }}</label>
                <Input v-model.number="chunkSize" type="number" min="128" max="2048" />
              </div>
              <div class="p-4 bg-background/50 border border-border/50 rounded-lg">
                <label class="text-sm font-medium mb-2 block uppercase">{{ t('knowledge.detail.overlap_label') }}</label>
                <Input v-model.number="chunkOverlap" type="number" min="0" max="50" />
              </div>
              <Button @click="handleReindexKnowledgeBase" :disabled="reindexingKB">
                <RefreshCw :class="['w-4 h-4 mr-2', reindexingKB ? 'animate-spin' : '']" />
                {{ reindexingKB ? t('knowledge.detail.reindexing') : t('knowledge.detail.reindex_kb') }}
              </Button>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Sidebar -->
      <div class="w-80 border-l border-border/50 bg-background/30 p-6 space-y-6 overflow-auto">
        <!-- Retrieval Tuning -->
        <div>
          <h3 class="text-sm font-semibold mb-4">{{ t('knowledge.detail.retrieval_tuning') }}</h3>
          <div class="space-y-4">
            <div>
              <div class="flex items-center justify-between mb-2">
                <label class="text-xs font-medium uppercase">{{ t('knowledge.detail.threshold_label') }}</label>
                <span class="text-xs text-muted-foreground">{{ similarityThreshold[0]?.toFixed(2) || '0.82' }}</span>
              </div>
              <div class="flex items-center gap-2 mb-1">
                <span class="text-xs text-muted-foreground">{{ t('knowledge.detail.strict') }}</span>
                <Slider v-model="similarityThreshold" :min="0" :max="1" :step="0.01" class="flex-1" />
                <span class="text-xs text-muted-foreground">{{ t('knowledge.detail.loose') }}</span>
              </div>
            </div>
            <div>
              <div class="flex items-center justify-between mb-2">
                <label class="text-xs font-medium uppercase">{{ t('knowledge.detail.top_k_label') }}</label>
                <span class="text-xs text-muted-foreground">{{ topKResults[0] }}</span>
              </div>
              <Slider v-model="topKResults" :min="1" :max="20" :step="1" />
            </div>
            <div>
              <div class="flex items-center gap-2 mb-2">
                <label class="text-xs font-medium uppercase">{{ t('knowledge.detail.search_type') }}</label>
                <div class="group relative">
                  <Info class="w-3 h-3 text-muted-foreground cursor-help" />
                  <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-10">
                    <div class="bg-popover text-popover-foreground text-xs rounded-md px-2 py-1.5 shadow-md border border-border max-w-[200px]">
                      {{ t('knowledge.detail.search_type_help') }}
                    </div>
                  </div>
                </div>
              </div>
              <div class="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  class="flex-1"
                  :class="searchType === 'dense' ? 'bg-primary text-primary-foreground' : ''"
                  @click="searchType = 'dense'"
                >
                  {{ t('knowledge.detail.dense') }}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  class="flex-1 opacity-60 cursor-not-allowed"
                  :class="searchType === 'hybrid' ? 'bg-primary/50 text-primary-foreground' : ''"
                  @click="searchType = 'dense'"
                  disabled
                  :title="t('knowledge.detail.hybrid_soon')"
                >
                  {{ t('knowledge.detail.hybrid') }}
                </Button>
              </div>
            </div>
          </div>
        </div>

        <!-- Indexing Config -->
        <div>
          <h3 class="text-sm font-semibold mb-4">{{ t('knowledge.detail.indexing_config') }}</h3>
          <div class="space-y-4">
            <div>
              <label class="text-xs font-medium mb-2 block uppercase">{{ t('knowledge.detail.chunk_size_label') }}</label>
              <Input v-model.number="chunkSize" type="number" min="128" max="2048" />
            </div>
            <div>
              <label class="text-xs font-medium mb-2 block uppercase">{{ t('knowledge.detail.overlap_label') }}</label>
              <Input v-model.number="chunkOverlap" type="number" min="0" max="50" />
            </div>
            <Button class="w-full" @click="handleReindexKnowledgeBase" :disabled="reindexingKB">
              <RefreshCw :class="['w-4 h-4 mr-2', reindexingKB ? 'animate-spin' : '']" />
              {{ reindexingKB ? t('knowledge.detail.reindexing') : t('knowledge.detail.reindex_kb') }}
            </Button>
          </div>
        </div>
      </div>
    </div>

    <!-- Footer -->
    <footer class="h-12 border-t border-border/50 flex items-center justify-between px-8 bg-background/50">
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <div class="w-2 h-2 rounded-full bg-blue-500"></div>
        <span>{{ t('knowledge.detail.local_worker') }}</span>
      </div>
      <div class="text-xs text-muted-foreground">
        v{{ '0.1.0' }} | Running on localhost:8000
      </div>
    </footer>

    <!-- Delete Confirmation Dialog -->
    <Teleport to="body">
      <div
        v-if="showDeleteConfirm"
        class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
        @click.self="showDeleteConfirm = false"
      >
        <div
          class="bg-background border border-border rounded-lg p-6 max-w-md w-full mx-4 shadow-lg"
          @click.stop
        >
          <h3 class="text-lg font-semibold mb-2">{{ t('knowledge.detail.delete_doc_title') }}</h3>
          <p class="text-sm text-muted-foreground mb-4">
            {{ t('knowledge.detail.delete_doc_confirm', { name: docToDelete?.source }) }}
            {{ t('knowledge.detail.delete_doc_warning') }}
          </p>
          <div class="flex justify-end gap-3">
            <Button
              variant="outline"
              @click="showDeleteConfirm = false"
              :disabled="deletingDocId !== null"
            >
              {{ t('knowledge.detail.upload_area.cancel') || t('knowledge.delete_dialog.cancel') }}
            </Button>
            <Button
              variant="destructive"
              @click="handleDelete"
              :disabled="deletingDocId !== null"
            >
              <Trash2 v-if="deletingDocId" class="w-4 h-4 mr-2 animate-spin" />
              <Trash2 v-else class="w-4 h-4 mr-2" />
              {{ deletingDocId ? t('knowledge.detail.deleting') : t('knowledge.delete_dialog.delete') }}
            </Button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
