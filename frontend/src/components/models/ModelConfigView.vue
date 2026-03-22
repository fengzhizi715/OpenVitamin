<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ChevronLeft, Loader2, AlertCircle } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import LocalModelConfigEditor from './LocalModelConfigEditor.vue'
import { listModels } from '@/services/api'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const modelId = computed(() => route.params.id as string)
const model = ref<any>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const loadModel = async () => {
  loading.value = true
  error.value = null
  try {
    const res = await listModels()
    const found = (res.data || []).find((m: any) => m.id === modelId.value)
    if (found) {
      model.value = found
    } else {
      error.value = 'Model not found'
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load model'
  } finally {
    loading.value = false
  }
}

const handleClose = () => {
  router.push({ name: 'models' })
}

const handleSaved = () => {
  loadModel()
}

onMounted(() => {
  loadModel()
})
</script>

<template>
  <div class="flex-1 flex flex-col min-h-0 bg-background overflow-hidden">
    <!-- Header -->
    <header class="h-14 border-b border-border/50 flex items-center gap-4 px-6 shrink-0">
      <Button
        variant="ghost"
        size="sm"
        class="gap-2 -ml-2"
        @click="handleClose"
      >
        <ChevronLeft class="w-4 h-4" />
        {{ t('common.back') || 'Back' }}
      </Button>
      <div class="flex-1 min-w-0">
        <h1 class="text-lg font-semibold truncate">
          {{ model?.name || modelId || t('models.card.configure') }}
        </h1>
        <p class="text-xs text-muted-foreground">model.json</p>
      </div>
    </header>

    <!-- Content -->
    <div class="flex-1 overflow-hidden">
      <div v-if="loading" class="flex flex-col items-center justify-center h-full text-muted-foreground">
        <Loader2 class="w-8 h-8 animate-spin mb-4" />
        <p class="text-sm">{{ t('common.loading') || 'Loading...' }}</p>
      </div>
      <div v-else-if="error" class="flex flex-col items-center justify-center h-full">
        <AlertCircle class="w-10 h-10 text-destructive mb-4" />
        <p class="text-sm text-destructive mb-4">{{ error }}</p>
        <Button variant="outline" @click="handleClose">{{ t('common.back') || 'Back' }}</Button>
      </div>
      <div v-else-if="model?.backend !== 'local'" class="flex flex-col items-center justify-center h-full">
        <p class="text-sm text-muted-foreground mb-4">{{ t('models.config.local_only') }}</p>
        <Button variant="outline" @click="handleClose">{{ t('common.back') }}</Button>
      </div>
      <div v-else class="h-full flex">
        <LocalModelConfigEditor
          :model="model"
          @close="handleClose"
          @saved="handleSaved"
        />
      </div>
    </div>
  </div>
</template>
