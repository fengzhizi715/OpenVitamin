<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { 
  Settings2, 
  ExternalLink, 
  HardDrive, 
  Box, 
  Bot,
  Loader2,
  FileJson
} from 'lucide-vue-next'

const router = useRouter()
const { t } = useI18n()

export interface ModelAsset {
  id: string
  name: string
  size?: string
  format: string
  source: string
  status: 'active' | 'detached'
  backend?: string
  quant?: string
  device?: string
  description?: string
  loading?: boolean // Added loading state
}

const props = defineProps<{
  model: ModelAsset
}>()

const emit = defineEmits<{
  (e: 'load', modelId: string): void
  (e: 'unload', modelId: string): void
  (e: 'settings', modelId: string): void
}>()

const getSourceIcon = (source: string) => {
  if (source.toLowerCase().includes('huggingface')) return ExternalLink
  if (source.toLowerCase().includes('ollama')) return Bot
  if (source.toLowerCase().includes('cloud')) return ExternalLink
  return HardDrive
}
</script>

<template>
  <div 
    class="group relative bg-card/40 border border-border/50 rounded-xl overflow-hidden hover:border-primary/30 transition-all flex flex-col h-full shadow-sm hover:shadow-md"
    :class="{ 'border-primary/50 ring-1 ring-primary/20': model.status === 'active' }"
  >
    <!-- Card Header -->
    <div class="p-5 flex-1">
      <div class="flex items-start justify-between mb-4">
        <div class="flex flex-col gap-1">
          <Badge variant="secondary" class="w-fit text-[10px] h-5 px-2 bg-muted/50 text-muted-foreground border-none font-bold tracking-wider">
            {{ t('models.card.model_asset') }}
          </Badge>
          <h3 class="text-xl font-bold tracking-tight text-foreground group-hover:text-primary transition-colors">
            {{ model.name }}
          </h3>
        </div>
        <span v-if="model.size" class="text-xs font-mono text-muted-foreground/70">{{ model.size }}</span>
      </div>

      <!-- Info Row -->
      <div class="flex items-center gap-4 text-xs text-muted-foreground mb-6">
        <div class="flex items-center gap-1.5 font-medium uppercase tracking-tight">
          <Box class="w-3.5 h-3.5" />
          {{ model.format }}
        </div>
        <div class="flex items-center gap-1.5 font-medium uppercase tracking-tight">
          <component :is="getSourceIcon(model.source)" class="w-3.5 h-3.5" />
          {{ model.source }}
        </div>
      </div>

      <!-- Runtime Binding Section -->
      <div class="space-y-3 pt-4 border-t border-border/30">
        <div class="flex items-center justify-between">
          <span class="text-[10px] font-bold tracking-widest text-muted-foreground/60 uppercase">{{ t('models.card.runtime_binding') }}</span>
          <div class="flex items-center gap-1.5">
            <div 
              class="w-1.5 h-1.5 rounded-full" 
              :class="model.status === 'active' ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-muted-foreground/30'"
            ></div>
            <span 
              class="text-[10px] font-bold tracking-wider uppercase"
              :class="model.status === 'active' ? 'text-emerald-500' : 'text-muted-foreground/50'"
            >
              {{ model.status === 'active' ? t('models.card.status.active') : t('models.card.status.detached') }}
            </span>
          </div>
        </div>

        <div class="grid grid-cols-3 gap-2">
          <div class="flex flex-col gap-0.5">
            <span class="text-[10px] text-muted-foreground/50 font-bold uppercase tracking-tighter">{{ t('models.card.backend') }}</span>
            <span class="text-xs font-medium">{{ model.backend || '-' }}</span>
          </div>
          <div class="flex flex-col gap-0.5">
            <span class="text-[10px] text-muted-foreground/50 font-bold uppercase tracking-tighter">{{ t('models.card.quant') }}</span>
            <span class="text-xs font-medium">{{ model.quant || '-' }}</span>
          </div>
          <div class="flex flex-col gap-0.5">
            <span class="text-[10px] text-muted-foreground/50 font-bold uppercase tracking-tighter">{{ t('models.card.device') }}</span>
            <span class="text-xs font-medium">{{ model.device || '-' }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Actions Footer -->
    <div class="p-4 bg-muted/20 border-t border-border/30 flex flex-nowrap items-center gap-2">
      <!-- Cloud models are always active, don't show load/unload -->
      <div v-if="['openai', 'gemini', 'deepseek', 'kimi'].includes(model.backend || '')" class="flex-1">
        <Badge variant="outline" class="w-full justify-center h-10 border-emerald-500/30 bg-emerald-500/5 text-emerald-500 font-bold uppercase tracking-wide">
          {{ t('models.card.cloud_connected') }}
        </Badge>
      </div>
      
      <template v-else>
        <Button 
          v-if="model.status === 'active'"
          variant="secondary" 
          class="flex-1 min-w-[5rem] font-bold tracking-wide h-10 bg-muted/60 text-foreground hover:bg-muted/80 border-none relative overflow-hidden shrink-0"
          :disabled="model.loading"
          @click="emit('unload', model.id)"
        >
          <div v-if="model.loading" class="absolute inset-0 flex items-center justify-center bg-muted/20">
            <Loader2 class="w-4 h-4 animate-spin" />
          </div>
          <span class="whitespace-nowrap" :class="{ 'opacity-0': model.loading }">{{ t('models.card.unload') }}</span>
        </Button>
        <Button 
          v-else
          variant="default" 
          class="flex-1 min-w-[5rem] font-bold tracking-wide h-10 bg-blue-600 hover:bg-blue-700 text-white shadow-lg shadow-blue-500/20 relative overflow-hidden shrink-0"
          :disabled="model.loading"
          @click="emit('load', model.id)"
        >
          <div v-if="model.loading" class="absolute inset-0 flex items-center justify-center bg-blue-700/50">
            <Loader2 class="w-4 h-4 animate-spin text-white" />
          </div>
          <span class="whitespace-nowrap" :class="{ 'opacity-0': model.loading }">{{ t('models.card.load') }}</span>
        </Button>
      </template>
      
      <!-- Configure: icon only -->
      <Button 
        variant="outline" 
        size="icon"
        class="h-10 w-10 shrink-0 border-primary/40 text-primary hover:bg-primary/10 hover:border-primary/60"
        :title="t('models.card.configure')"
        @click="emit('settings', model.id)"
      >
        <Settings2 class="w-4 h-4" />
      </Button>
      <Button 
        v-if="model.backend === 'local'"
        variant="outline" 
        size="icon"
        class="h-10 w-10 shrink-0 border-border/50 hover:bg-muted/50"
        :title="t('models.card.edit_model_json')"
        @click="router.push({ name: 'model-config', params: { id: model.id } })"
      >
        <FileJson class="w-4 h-4" />
      </Button>
    </div>
  </div>
</template>
