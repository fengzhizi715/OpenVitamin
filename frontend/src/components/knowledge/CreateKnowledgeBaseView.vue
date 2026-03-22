<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { ArrowRight, ChevronLeft } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { createKnowledgeBase, listEmbeddingModels } from '@/services/api'

const router = useRouter()

// Form data
const formData = ref({
  name: '',
  description: '',
  embeddingModelId: '',
  chunkSize: 512,
  chunkOverlap: 50,
})

// Options
const embeddingModels = ref<Array<{ id: string; name: string }>>([])
const vectorStoreTypes = [
  { value: 'sqlite-vec', label: 'SQLite-vec (Local Persistent)' }
]

const loading = ref(false)
const error = ref<string | null>(null)

// Load embedding models
onMounted(async () => {
  try {
    const models = await listEmbeddingModels()
    embeddingModels.value = models.map((m: any) => ({
      id: m.id,
      name: `${m.name} (${t('knowledge.create.local_suffix')})`
    }))
    // Set default if available
    if (embeddingModels.value.length > 0 && !formData.value.embeddingModelId) {
      formData.value.embeddingModelId = embeddingModels.value[0]!.id
    }
  } catch (err) {
    console.error('Failed to load embedding models:', err)
    error.value = t('knowledge.create.err_emb_models')
  }
})

// Adjust chunk size
const adjustChunkSize = (delta: number) => {
  const newValue = formData.value.chunkSize + delta
  if (newValue >= 128 && newValue <= 2048) {
    formData.value.chunkSize = newValue
  }
}

// Adjust chunk overlap
const adjustChunkOverlap = (delta: number) => {
  const newValue = formData.value.chunkOverlap + delta
  if (newValue >= 0 && newValue <= formData.value.chunkSize) {
    formData.value.chunkOverlap = newValue
  }
}

// Submit form
const handleSubmit = async () => {
  if (!formData.value.name.trim()) {
    error.value = t('knowledge.create.err_name_req')
    return
  }
  
  if (!formData.value.embeddingModelId) {
    error.value = t('knowledge.create.err_emb_req')
    return
  }

  loading.value = true
  error.value = null

  try {
    const kbId = await createKnowledgeBase({
      name: formData.value.name,
      description: formData.value.description,
      embedding_model_id: formData.value.embeddingModelId,
      chunk_size: formData.value.chunkSize,
      chunk_overlap: formData.value.chunkOverlap,
    })
    
    // Navigate to knowledge base detail page
    router.push({ name: 'knowledge-detail', params: { id: kbId } })
  } catch (err: any) {
    console.error('Failed to create knowledge base:', err)
    error.value = err.message || t('knowledge.create.err_create_failed')
  } finally {
    loading.value = false
  }
}

const handleCancel = () => {
  router.push({ name: 'knowledge' })
}
</script>

<template>
  <div class="flex-1 flex flex-col overflow-hidden bg-background">
    <!-- Header -->
    <header class="h-14 border-b border-border/50 flex items-center px-8 bg-background/50 backdrop-blur-md">
      <div class="flex items-center gap-4">
        <Button variant="ghost" size="icon" class="h-9 w-9" @click="handleCancel">
          <ChevronLeft class="w-4 h-4" />
        </Button>
        <div>
          <nav class="text-xs text-muted-foreground mb-1">
            {{ t('nav.knowledge') }} > {{ t('knowledge.create.create_new') }}
          </nav>
          <h1 class="text-lg font-semibold">{{ t('knowledge.create.title') }}</h1>
        </div>
      </div>
    </header>

    <!-- Main Content -->
    <div class="flex-1 overflow-auto">
      <div class="max-w-3xl mx-auto px-8 py-8">
        <p class="text-sm text-muted-foreground mb-8">
          {{ t('knowledge.create.subtitle') }}
        </p>

        <!-- Error Message -->
        <div v-if="error" class="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
          {{ error }}
        </div>

        <!-- Form -->
        <form @submit.prevent="handleSubmit" class="space-y-8">
          <!-- GENERAL SETTINGS -->
          <div class="space-y-4">
            <h2 class="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {{ t('knowledge.create.section_general') }}
            </h2>
            
            <div class="space-y-2">
              <label class="text-sm font-medium">{{ t('knowledge.create.kb_name') }}</label>
              <Input
                v-model="formData.name"
                :placeholder="t('knowledge.create.kb_name_placeholder')"
                class="bg-background/50 border-border/40"
                required
              />
            </div>

            <div class="space-y-2">
              <label class="text-sm font-medium">{{ t('knowledge.create.desc') }}</label>
              <Textarea
                v-model="formData.description"
                :placeholder="t('knowledge.create.desc_placeholder')"
                class="bg-background/50 border-border/40 min-h-[100px]"
              />
            </div>
          </div>

          <!-- ARCHITECTURE -->
          <div class="space-y-4">
            <h2 class="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {{ t('knowledge.create.section_arch') }}
            </h2>
            
            <div class="space-y-2">
              <label class="text-sm font-medium">{{ t('knowledge.create.emb_model') }}</label>
              <Select v-model="formData.embeddingModelId" required>
                <SelectTrigger class="bg-background/50 border-border/40">
                  <SelectValue :placeholder="t('knowledge.create.select_emb')" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem
                    v-for="model in embeddingModels"
                    :key="model.id"
                    :value="model.id"
                  >
                    {{ model.name }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div class="space-y-2">
              <label class="text-sm font-medium">{{ t('knowledge.create.vec_store') }}</label>
              <Select :model-value="vectorStoreTypes[0]!.value" disabled>
                <SelectTrigger class="bg-background/50 border-border/40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem
                    v-for="store in vectorStoreTypes"
                    :key="store.value"
                    :value="store.value"
                  >
                    {{ store.label }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <p class="text-xs text-muted-foreground">
                {{ t('knowledge.create.vec_store_desc') }}
              </p>
            </div>
          </div>

          <!-- CHUNKING STRATEGY -->
          <div class="space-y-4">
            <h2 class="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              {{ t('knowledge.create.section_chunking') }}
            </h2>
            
            <div class="space-y-2">
              <label class="text-sm font-medium">{{ t('knowledge.create.chunk_size') }}</label>
              <div class="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  class="h-9 w-9"
                  @click="adjustChunkSize(-64)"
                >
                  -
                </Button>
                <Input
                  v-model.number="formData.chunkSize"
                  type="number"
                  min="128"
                  max="2048"
                  step="64"
                  class="bg-background/50 border-border/40 text-center"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  class="h-9 w-9"
                  @click="adjustChunkSize(64)"
                >
                  +
                </Button>
                <span class="text-sm text-muted-foreground ml-2">{{ t('knowledge.create.tokens') }}</span>
              </div>
            </div>

            <div class="space-y-2">
              <label class="text-sm font-medium">{{ t('knowledge.create.chunk_overlap') }}</label>
              <div class="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  class="h-9 w-9"
                  @click="adjustChunkOverlap(-10)"
                >
                  -
                </Button>
                <Input
                  v-model.number="formData.chunkOverlap"
                  type="number"
                  min="0"
                  :max="formData.chunkSize"
                  step="10"
                  class="bg-background/50 border-border/40 text-center"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  class="h-9 w-9"
                  @click="adjustChunkOverlap(10)"
                >
                  +
                </Button>
                <span class="text-sm text-muted-foreground ml-2">{{ t('knowledge.create.tokens') }}</span>
              </div>
            </div>
          </div>

          <!-- Actions -->
          <div class="flex items-center justify-end gap-4 pt-6 border-t border-border/50">
            <Button
              type="button"
              variant="ghost"
              @click="handleCancel"
              :disabled="loading"
            >
              {{ t('knowledge.create.cancel') }}
            </Button>
            <Button
              type="submit"
              :disabled="loading || !formData.name.trim() || !formData.embeddingModelId"
            >
              {{ t('knowledge.create.create_continue') }}
              <ArrowRight class="w-4 h-4 ml-2" />
            </Button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
