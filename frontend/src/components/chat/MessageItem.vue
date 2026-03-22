<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { Button } from '@/components/ui/button'
import { Copy, Loader2, Bot, User, ThumbsUp, Check, RotateCcw, Pencil, X, Send } from 'lucide-vue-next'
import { renderMarkdown } from '@/utils/markdown'
import { getRagTraceByMessage, getRagTraceById, type RAGTraceResponse } from '@/services/api'

interface Props {
  id: string
  role: 'user' | 'assistant'
  content: string
  loading?: boolean
  modelName?: string
  timestamp?: number
  isLast?: boolean
  meta?: Record<string, unknown> | null
  params?: {
    temperature: number
    top_p: number
    max_tokens: number
    system_prompt?: string
  }
  attachments?: Array<{
    type: 'image'
    url: string
    file?: File
  }>
}

const props = defineProps<Props>()
const emit = defineEmits(['regenerate', 'edit', 'content-resize'])

const isEditing = ref(false)
const editContent = ref(props.content)

watch(() => props.content, (newVal) => {
  editContent.value = newVal
})

const handleEdit = () => {
  isEditing.value = true
  editContent.value = props.content
}

const cancelEdit = () => {
  isEditing.value = false
  editContent.value = props.content
}

const submitEdit = () => {
  if (editContent.value.trim() && editContent.value !== props.content) {
    emit('edit', editContent.value)
  }
  isEditing.value = false
}

const formattedModelName = computed(() => {
  if (!props.modelName) return ''
  
  const mapping: Record<string, string> = {
    'mock': 'Mock',
    'lmstudio': 'LM Studio',
    'ollama': 'Ollama',
    'gpt-4': 'GPT-4',
    'gpt-3.5-turbo': 'GPT-3.5'
  }
  
  const name = mapping[props.modelName] || props.modelName
  return name.startsWith('ollama:') ? name.replace('ollama:', '') : name
})

const formatTime = (ts?: number) => {
  if (!ts) return ''
  const date = new Date(ts)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

const renderedContent = computed(() => renderMarkdown(props.content))

// ----------------------------
// RAG Trace UI (lazy load on expand)
// ----------------------------

const ragOpen = ref(false)
const ragLoading = ref(false)
const ragError = ref<string | null>(null)
const ragTrace = ref<RAGTraceResponse | null>(null)

const ragUsed = computed(() => {
  const rag = (props.meta as any)?.rag
  // 只有当 retrieved_count > 0 时才认为"真正使用了知识库"
  return Boolean(rag?.used && rag?.retrieved_count > 0)
})

async function toggleRag() {
  console.log('[MessageItem] toggleRag clicked, current ragOpen:', ragOpen.value, 'messageId:', props.id)
  ragOpen.value = !ragOpen.value
  if (!ragOpen.value) {
    console.log('[MessageItem] RAG panel closed')
    return
  }
  if (ragTrace.value) {
    console.log('[MessageItem] RAG trace already loaded')
    return
  }
  ragLoading.value = true
  ragError.value = null
  try {
    console.log('[MessageItem] Fetching RAG trace for message:', props.id)
    ragTrace.value = await getRagTraceByMessage(props.id)
    // 若按 message_id 查不到且 meta 中有 trace_id，用 trace_id 兜底（解决 message_id 未同步场景）
    const traceId = (props.meta as any)?.rag?.trace_id
    if (!ragTrace.value?.rag_used && traceId) {
      console.log('[MessageItem] Fallback: fetching RAG trace by trace_id:', traceId)
      ragTrace.value = await getRagTraceById(traceId)
    }
    console.log('[MessageItem] RAG trace loaded:', ragTrace.value)
  } catch (e) {
    console.error('[MessageItem] Failed to load RAG trace:', e)
    ragError.value = e instanceof Error ? e.message : String(e)
  } finally {
    ragLoading.value = false
  }
}

const copied = ref(false)
const copyToClipboard = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (err) {
    console.error('Failed to copy:', err)
  }
}
const vFocus = {
  mounted: (el: HTMLElement) => el.focus()
}
</script>

<template>
  <div :class="['flex w-full gap-4 mb-6', role === 'user' ? 'justify-end' : 'justify-start']">
    <!-- Avatar -->
    <div 
      :class="[
        'w-8 h-8 rounded-full flex items-center justify-center shrink-0',
        role === 'user' 
          ? 'bg-primary text-primary-foreground' 
          : 'bg-blue-600 text-white'
      ]"
    >
      <User v-if="role === 'user'" class="w-4 h-4" />
      <Bot v-else class="w-4 h-4" />
    </div>

    <!-- Message Content -->
    <div :class="['flex-1 max-w-[85%]', role === 'user' ? 'flex justify-end' : '']">
      <div :class="['space-y-2', role === 'user' ? 'items-end' : 'items-start']">
        <!-- Header: Role & Time -->
        <div class="flex items-center gap-2 text-xs text-muted-foreground">
          <span class="font-medium capitalize">{{ role === 'user' ? t('chat.message.user') : t('chat.message.assistant') }}</span>
          <span v-if="role === 'assistant' && formattedModelName" class="px-1.5 py-0.5 rounded-md bg-muted text-[10px] font-medium uppercase tracking-wider">
            {{ formattedModelName }}
          </span>
          <span>{{ formatTime(timestamp) }}</span>
          <Loader2 v-if="loading && role === 'assistant'" class="w-3 h-3 animate-spin" />

          <!-- 🧠 Knowledge Used -->
          <button
            v-if="role === 'assistant' && !loading && ragUsed"
            class="ml-1 text-[10px] px-2 py-0.5 rounded-md bg-muted hover:bg-muted/80 text-foreground/80 hover:text-foreground transition-colors cursor-pointer relative z-10"
            @click.stop.prevent="toggleRag"
            type="button"
          >
            🧠 {{ t('chat.message.knowledge_used') }}
          </button>
        </div>

        <!-- Message Text -->
        <div 
          :class="[
            'rounded-2xl px-4 py-3 text-sm leading-relaxed relative group/msg border shadow-sm break-words min-w-[60px]',
            role === 'user' 
              ? 'bg-primary text-primary-foreground border-primary shadow-primary/10' 
              : 'bg-card text-foreground border-border'
          ]"
        >
          <!-- Attachments -->
          <div v-if="attachments?.length" class="mb-3 flex flex-wrap gap-2">
            <div 
              v-for="(attachment, index) in attachments" 
              :key="index"
              class="relative group/attachment"
            >
              <img 
                :src="attachment.url" 
                :alt="`Attachment ${index + 1}`"
                class="max-w-[200px] max-h-[200px] rounded-lg border border-border object-contain bg-muted/50"
                @load="emit('content-resize')"
              />
            </div>
          </div>
          
          <div v-if="isEditing" class="flex flex-col gap-2 min-w-[200px] sm:min-w-[400px]">
            <textarea 
              v-model="editContent"
              class="w-full bg-transparent border-none focus:ring-0 text-sm resize-none overflow-hidden"
              rows="3"
              v-focus
              @keydown.enter.prevent.ctrl="submitEdit"
              @keydown.esc="cancelEdit"
            ></textarea>
            <div class="flex justify-end gap-2 mt-2">
              <Button variant="ghost" size="sm" class="h-7 px-2 text-[10px]" @click="cancelEdit">
                <X class="w-3 h-3 mr-1" /> {{ t('chat.message.cancel') }}
              </Button>
              <Button variant="secondary" size="sm" class="h-7 px-2 text-[10px]" @click="submitEdit">
                <Send class="w-3 h-3 mr-1" /> {{ t('chat.message.save_submit') }}
              </Button>
            </div>
          </div>
          <div 
            v-else
            class="prose prose-sm dark:prose-invert max-w-none prose-p:leading-relaxed prose-pre:p-0 prose-pre:bg-transparent prose-code:text-primary prose-code:bg-primary/10 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none"
            v-html="renderedContent"
          ></div>
          
          <!-- Parameters Display (Subtle) -->
          <div v-if="role === 'assistant' && params" class="mt-2 pt-2 border-t border-border/20 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground/50 font-mono">
            <span>temp: {{ params.temperature }}</span>
            <span>top_p: {{ params.top_p }}</span>
            <span>tokens: {{ params.max_tokens }}</span>
            <span v-if="params.system_prompt" class="truncate max-w-[300px]" :title="params.system_prompt">sys: {{ params.system_prompt }}</span>
          </div>
        </div>

        <!-- RAG Trace Panel (collapsed by default) -->
        <div
          v-if="role === 'assistant' && ragUsed && ragOpen"
          class="rounded-xl border border-border bg-muted/30 px-3 py-2 text-xs space-y-2 mt-2"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2">
              <span class="font-medium">{{ t('chat.message.rag_trace') }}</span>
              <span v-if="ragLoading" class="text-muted-foreground">{{ t('chat.message.loading') }}</span>
              <span v-else-if="ragError" class="text-destructive text-[10px]">{{ ragError }}</span>
            </div>
            <button
              class="text-muted-foreground hover:text-foreground text-[10px]"
              @click="ragOpen = false"
              type="button"
            >
              {{ t('chat.message.close') }}
            </button>
          </div>

          <template v-if="!ragLoading && !ragError && ragTrace?.rag_used && ragTrace?.trace">
            <div class="text-muted-foreground">
              <span class="font-medium text-foreground">{{ t('chat.message.rag_name') }}:</span>
              {{ ragTrace.trace.rag_type }} / {{ ragTrace.trace.rag_id }}
            </div>
            <div class="text-muted-foreground">
              <span class="font-medium text-foreground">{{ t('chat.message.hit') }}:</span>
              {{ ragTrace.trace.retrieved_count }} {{ t('chat.message.chunks') }}
            </div>

            <div v-if="ragTrace.trace.retrieved_count === 0" class="rounded-lg border border-border/60 bg-background/40 px-2 py-2 text-muted-foreground">
              <div class="text-[11px]">
                ⚠️ {{ t('chat.message.no_rag_result') }}
                <ul class="list-disc list-inside mt-1 space-y-0.5">
                  <li>{{ t('chat.message.no_rag_reason1') }}</li>
                  <li>{{ t('chat.message.no_rag_reason2') }}</li>
                  <li>{{ t('chat.message.no_rag_reason3') }}（当前: {{ ragTrace.trace.score_threshold ?? 1.2 }}）</li>
                </ul>
              </div>
            </div>

            <div v-if="ragTrace.trace.chunks?.length" class="space-y-2">
              <div class="font-medium text-foreground">{{ t('chat.message.hit_docs') }}</div>
              <div
                v-for="c in ragTrace.trace.chunks"
                :key="`${c.rank}-${c.chunk_id}`"
                class="rounded-lg border border-border/60 bg-background/40 px-2 py-2"
              >
                <div class="flex items-center justify-between gap-2">
                  <div class="min-w-0">
                    <div class="truncate">
                      <span class="font-medium">{{ c.doc_name || t('chat.message.unknown') }}</span>
                    </div>
                    <div class="text-[10px] text-muted-foreground">
                      {{ t('chat.message.rank') }} #{{ c.rank }} · {{ t('chat.message.score') }} {{ (c.score ?? 0).toFixed(4) }}
                    </div>
                  </div>
                </div>

                <details class="mt-2">
                  <summary class="cursor-pointer text-[10px] text-muted-foreground hover:text-foreground">
                    {{ t('chat.message.content_expand') }}
                  </summary>
                  <pre class="mt-2 whitespace-pre-wrap text-[11px] leading-relaxed text-foreground/90">{{ c.content }}</pre>
                </details>
              </div>
            </div>
          </template>

          <template v-else-if="!ragLoading && !ragError">
            <div class="text-muted-foreground">{{ t('chat.message.no_trace') }}</div>
          </template>
        </div>

        <!-- Feedback & Action Buttons -->
        <div class="flex items-center gap-2 opacity-0 group-hover/msg:opacity-100 transition-opacity">
          <!-- Assistant Actions -->
          <template v-if="role === 'assistant' && !loading">
            <Button 
              variant="ghost" 
              size="sm" 
              class="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
              :title="t('chat.message.helpful')"
            >
              <ThumbsUp class="w-3.5 h-3.5" />
            </Button>
            <Button 
              v-if="isLast"
              variant="ghost" 
              size="sm" 
              class="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground"
              @click="emit('regenerate')"
            >
              <RotateCcw class="w-3.5 h-3.5" />
              <span>{{ t('chat.message.regenerate') }}</span>
            </Button>
          </template>

          <!-- User Actions -->
          <template v-if="role === 'user' && !isEditing">
            <Button 
              variant="ghost" 
              size="sm" 
              class="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
              @click="handleEdit"
            >
              <Pencil class="w-3.5 h-3.5" />
            </Button>
          </template>

          <!-- Common Actions -->
          <Button 
            variant="ghost" 
            size="sm" 
            class="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground overflow-hidden"
            :class="[copied ? 'w-20' : 'w-7 sm:w-20']"
            @click="copyToClipboard(content)"
          >
            <Check v-if="copied" class="w-3.5 h-3.5 text-green-500" />
            <Copy v-else class="w-3.5 h-3.5" />
            <span class="hidden sm:inline">{{ copied ? t('chat.message.copied') : t('chat.message.copy') }}</span>
          </Button>
        </div>

      </div>
    </div>
  </div>
</template>
