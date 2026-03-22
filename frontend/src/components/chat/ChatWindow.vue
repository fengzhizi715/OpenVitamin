<script setup lang="ts">
import { ref, nextTick, watch, onMounted, onUnmounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessageSquare, ArrowDown } from 'lucide-vue-next'
import { useChat } from '@/composables/useChat'
import { useSessions } from '@/composables/useSessions'
import { getSessionId, listModels, vlmGenerate, type ModelInfo } from '@/services/api'
import { Button } from '@/components/ui/button'
import ChatHeader from './ChatHeader.vue'
import SessionTitle from './SessionTitle.vue'
import MessageItem from './MessageItem.vue'
import ChatInput from './ChatInput.vue'

const { t } = useI18n()
const chat = useChat({
  temperature: 0.7,
  top_p: 0.9,
  max_tokens: 4096,
})

const abortController = ref<AbortController | null>(null)
const scrollContainerRef = ref<any>(null)
const sessionsStore = useSessions()
const userHasScrolledUp = ref(false)
const showScrollButton = ref(false)
const scrollTimeoutRef = ref<ReturnType<typeof setTimeout> | null>(null)
const availableModels = ref<ModelInfo[]>([])

const currentModelSupportsVision = computed(() => {
  const modelId = (chat.model.value || '').toLowerCase()
  if (modelId === 'auto') return true
  const model = availableModels.value.find((m) => m.id === chat.model.value)
  return model?.model_type === 'vlm'
})

const getViewport = () => {
  if (!scrollContainerRef.value) return null
  // 如果使用了 DynamicScroller，它本身就是滚动容器
  return scrollContainerRef.value.$el || scrollContainerRef.value
}

const handleScroll = (_event: Event) => {
  // vue-virtual-scroller 的 scroll 事件 target 有时不是实际滚动容器
  const viewport = getViewport() as HTMLElement | null
  if (!viewport) return

  const { scrollTop, scrollHeight, clientHeight } = viewport
  const isAtBottom = scrollHeight - scrollTop - clientHeight < 50
  
  userHasScrolledUp.value = !isAtBottom
  
  // 如果不在底部且有新消息（或者正在加载），显示回到投底部按钮
  if (!isAtBottom && chat.loading.value) {
    showScrollButton.value = true
  } else if (isAtBottom) {
    showScrollButton.value = false
  }
}

const scrollToBottom = async (behavior: ScrollBehavior = 'auto') => {
  await nextTick()
  if (scrollContainerRef.value && chat.messages.value.length > 0) {
    if (typeof scrollContainerRef.value.scrollToItem === 'function') {
      try {
        await nextTick()
        scrollContainerRef.value.scrollToItem(chat.messages.value.length - 1)
        return
      } catch (e) {
        console.debug('[ChatWindow] scrollToItem failed, fallback to scrollTo:', e)
      }
    }
  }
  const viewport = getViewport()
  if (viewport) {
    if (scrollTimeoutRef.value) clearTimeout(scrollTimeoutRef.value)
    scrollTimeoutRef.value = setTimeout(() => {
      viewport.scrollTo({ top: viewport.scrollHeight, behavior })
      scrollTimeoutRef.value = null
    }, 50)
  }
}

const handleMessageResize = async () => {
  await nextTick()
  // DynamicScroller 在图片加载后可能不会自动重新测量高度，强制刷新一次
  const scroller = scrollContainerRef.value
  if (scroller && typeof scroller.forceUpdate === 'function') {
    try {
      scroller.forceUpdate()
    } catch (e) {
      // ignore
    }
  }
  if (!userHasScrolledUp.value) {
    scrollToBottom('auto')
  }
}

// 监听消息数量变化（新消息添加时）
const stopWatch1 = watch(() => chat.messages.value.length, (newLen, oldLen) => {
  if (newLen > oldLen) {
    const lastMsg = chat.messages.value[newLen - 1]
    if (!lastMsg) return
    // 如果是用户发送的消息，强制滚动到底部
    if (lastMsg.role === 'user') {
      userHasScrolledUp.value = false
      scrollToBottom('smooth')
    } else if (!userHasScrolledUp.value) {
      // 如果是 AI 回复且用户没往上翻，跟随机滚动
      scrollToBottom('smooth')
    }
  }
})

// 监听最后一条消息的内容变化（流式更新时跟随到底部，节流避免闪烁）
let scrollThrottle: ReturnType<typeof setTimeout> | null = null
const stopWatch2 = watch(() => {
  const lastMsg = chat.messages.value[chat.messages.value.length - 1]
  return lastMsg ? lastMsg.content : ''
}, () => {
  if (!userHasScrolledUp.value) {
    if (scrollThrottle) return
    scrollThrottle = setTimeout(() => {
      scrollThrottle = null
      scrollToBottom('auto')
    }, 400)
  } else {
    showScrollButton.value = true
  }
})

// 监听 activeSessionId 变化，自动加载或清空消息
const stopWatch3 = watch(
  () => sessionsStore.activeSessionId.value,
  async (newId, oldId) => {
    console.log('[ChatWindow] activeSessionId changed:', { oldId, newId })
    // 如果从有值变成 null，清空消息（新建聊天）
    if (!newId && oldId) {
      console.log('[ChatWindow] Clearing messages for new chat')
      chat.clearMessages()
      return
    }
    // 如果从 null 变成有值，或者切换会话，加载消息
    if (newId) {
      console.log('[ChatWindow] Loading messages for session:', newId)
      await loadMessagesForActiveSession()
      // loadMessagesForActiveSession already handles scrolling, no need to call again
    }
  },
  { immediate: false }
)

const handleSendMessage = async (content: string) => {
  abortController.value = new AbortController()
  showScrollButton.value = false
  userHasScrolledUp.value = false
  
  await chat.sendMessage(content, { stream: true, signal: abortController.value.signal })
  abortController.value = null
  
  const sid = getSessionId()
  if (sid && sid !== sessionsStore.activeSessionId.value) {
    sessionsStore.activeSessionId.value = sid
  }
  await sessionsStore.refreshSessions()
  // 同步落库后的 message.id / meta（包含 rag）
  if (sessionsStore.activeSessionId.value) {
    await loadMessagesForActiveSession()
  }
}

const handleSendMessageWithFiles = async (content: string, files: File[]) => {
  abortController.value = new AbortController()
  showScrollButton.value = false
  userHasScrolledUp.value = false
  
  const modelId = (chat.model.value || '').toLowerCase()
  const isAutoMode = modelId === 'auto'
  const isVlmModel = currentModelSupportsVision.value === true

  // Auto mode: send through unified chat endpoint with attachments
  // Backend will auto-switch to VLM when images are detected
  if (isAutoMode) {
    const attachments = files.map((file) => ({
      type: 'image' as const,
      url: URL.createObjectURL(file),
      file,
    }))
    await chat.sendMessage(content, { stream: true, signal: abortController.value.signal }, attachments)
    abortController.value = null
  }
  // Specific VLM model selected: use dedicated VLM endpoint
  else if (!isVlmModel) {
    // Non-VLM model: ignore images, send text only
    await chat.sendMessage(content, { stream: true, signal: abortController.value.signal })
    abortController.value = null
  } else {
    // VLM 当前只支持单张图；取第一张，其余忽略（UI 仍可预览但不会参与推理/持久化）
    const imageFile = files[0]
    if (!imageFile) {
      await chat.sendMessage(content, { stream: true, signal: abortController.value.signal })
      abortController.value = null
      return
    }

    const attachments = files.map((file) => ({
      type: 'image' as const,
      url: URL.createObjectURL(file),
      file,
    }))

    // 1) 先把用户消息写入 UI（带附件预览）
    const userMsg = chat.addMessage('user', content, undefined, undefined, attachments)

    // 2) 添加助手占位消息
    const assistantMsg = chat.addMessage('assistant', '', chat.model.value, {
      temperature: chat.temperature.value,
      top_p: chat.top_p.value,
      max_tokens: Number(chat.max_tokens.value),
      system_prompt: undefined,
    })
    assistantMsg.loading = true
    chat.loading.value = true

    try {
      // VLM 推理延迟敏感：默认将输出长度控制在更保守范围，避免超长生成导致响应过慢
      const vlmMaxTokens = Math.min(Math.max(Number(chat.max_tokens.value) || 512, 64), 1024)
      const res = await vlmGenerate(
        {
          model: chat.model.value,
          prompt: content,
          temperature: chat.temperature.value,
          max_tokens: vlmMaxTokens,
        },
        imageFile,
        { signal: abortController.value.signal }
      )
      assistantMsg.content = res.text || ''
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      assistantMsg.content = `Error: ${msg}`
    } finally {
      assistantMsg.loading = false
      chat.loading.value = false
      abortController.value = null
    }
  }
  
  const sid = getSessionId()
  if (sid && sid !== sessionsStore.activeSessionId.value) {
    sessionsStore.activeSessionId.value = sid
  }
  await sessionsStore.refreshSessions()
  if (sessionsStore.activeSessionId.value) {
    await loadMessagesForActiveSession()
  }
}

const handleRegenerate = async () => {
  abortController.value = new AbortController()
  showScrollButton.value = false
  userHasScrolledUp.value = false
  await chat.regenerate({ stream: true, signal: abortController.value.signal })
  abortController.value = null
  if (sessionsStore.activeSessionId.value) {
    await loadMessagesForActiveSession()
  }
}

const handleEditMessage = async (id: string, newContent: string) => {
  abortController.value = new AbortController()
  showScrollButton.value = false
  userHasScrolledUp.value = false
  await chat.editAndResubmit(id, newContent, { stream: true, signal: abortController.value.signal })
  abortController.value = null
  if (sessionsStore.activeSessionId.value) {
    await loadMessagesForActiveSession()
  }
}

const handleStop = () => {
  if (abortController.value) {
    abortController.value.abort()
    abortController.value = null
  }
}

const handleUpdateTitle = async (sessionId: string, newTitle: string) => {
  await sessionsStore.updateSessionTitle(sessionId, newTitle)
}

async function loadMessagesForActiveSession() {
  try {
    chat.error.value = null
    const msgs = await sessionsStore.loadActiveSessionMessages()
    chat.setMessages(
      msgs.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        timestamp: m.timestamp,
        loading: false,
        modelName: m.modelName,
        meta: m.meta,
        params: m.params,
        attachments: m.attachments,
      }))
    )
  } catch (e) {
    chat.error.value = e instanceof Error ? e.message : String(e)
    return
  }
  
  // Reset scroll state and ensure we're at the bottom
  userHasScrolledUp.value = false
  showScrollButton.value = false
  
  // Wait for virtual scroller to render items, then scroll to bottom
  await nextTick()
  // 清理之前的定时器（如果存在）
  if (scrollTimeoutRef.value) {
    clearTimeout(scrollTimeoutRef.value)
  }
  scrollTimeoutRef.value = setTimeout(async () => {
    await scrollToBottom('auto')
    scrollTimeoutRef.value = null
  }, 100)
}

onMounted(async () => {
  const currentPath = window.location.pathname
  if (currentPath !== '/chat') return

  try {
    const modelRes = await listModels()
    availableModels.value = modelRes?.data || []
  } catch (e) {
    console.warn('[ChatWindow] Failed to load model metadata, fallback behavior will apply:', e)
    availableModels.value = []
  }

  await sessionsStore.refreshSessions()
  if (sessionsStore.activeSessionId.value) {
    await loadMessagesForActiveSession()
  }
})

onUnmounted(() => {
  // 1. 取消正在进行的请求
  if (abortController.value) {
    abortController.value.abort()
    abortController.value = null
  }
  
  // 2. 清理定时器
  if (scrollTimeoutRef.value) {
    clearTimeout(scrollTimeoutRef.value)
    scrollTimeoutRef.value = null
  }
  
  // 3. 显式停止 watch（虽然 Vue 会自动清理，但显式更安全）
  stopWatch1()
  stopWatch2()
  stopWatch3()
})
</script>

<style scoped>
.scroller {
  overflow-y: auto;
  min-height: 0;
}

/* Optional: Customize scrollbar to match the design */
.scroller::-webkit-scrollbar {
  width: 6px;
}

.scroller::-webkit-scrollbar-track {
  background: transparent;
}

.scroller::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.2);
  border-radius: 3px;
}

.scroller::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.4);
}
</style>

<template>
  <div class="flex-1 flex flex-col min-w-0 min-h-0 bg-background overflow-hidden">
    <ChatHeader 
      v-model="chat.model.value" 
      :knowledge-base-id="chat.knowledgeBaseId.value"
      @update:knowledge-base-id="chat.knowledgeBaseId.value = $event"
    />
    
    <!-- Session Title Bar -->
    <div class="h-10 border-b border-border/30 flex items-center px-6 bg-muted/20 gap-3">
      <span class="text-xs font-medium text-muted-foreground uppercase tracking-wider">{{ t('chat.session_title') }}</span>
      <SessionTitle
        :title="sessionsStore.currentSession.value?.title"
        :session-id="sessionsStore.activeSessionId.value"
        @update:title="handleUpdateTitle"
      />
    </div>
    
    <div class="flex-1 min-h-0 flex flex-col overflow-hidden relative">
      <div v-if="chat.messages.value.length === 0" class="flex-1 flex flex-col items-center justify-center py-40 space-y-4">
        <div class="w-16 h-16 rounded-3xl bg-primary/10 flex items-center justify-center">
          <MessageSquare class="w-8 h-8 text-primary" />
        </div>
        <div class="text-center space-y-1">
          <p class="text-lg font-bold text-foreground">{{ t('chat.new_conversation') }}</p>
          <p class="text-sm text-muted-foreground max-w-[240px]">{{ t('chat.new_conversation_desc') }}</p>
        </div>
      </div>

      <DynamicScroller
        v-else
        ref="scrollContainerRef"
        :items="chat.messages.value"
        :min-item-size="80"
        type-field="role"
        class="flex-1 min-h-0 scroller"
        key-field="id"
        @scroll="handleScroll"
      >
        <template #default="{ item, index, active }">
          <DynamicScrollerItem
            :item="item"
            :active="active"
            :size-dependencies="[item.content, item.attachments?.length]"
            :index="index"
          >
            <div class="max-w-4xl mx-auto px-6 py-2">
              <MessageItem 
                :id="item.id"
                :role="item.role"
                :content="item.content"
                :loading="item.loading"
                :model-name="item.modelName"
                :timestamp="item.timestamp"
                :meta="item.meta"
                :params="item.params"
                :attachments="item.attachments"
                :is-last="index === chat.messages.value.length - 1"
                @regenerate="handleRegenerate"
                @edit="(newContent) => handleEditMessage(item.id, newContent)"
                @content-resize="handleMessageResize"
              />
            </div>
          </DynamicScrollerItem>
        </template>
      </DynamicScroller>

      <!-- Scroll to Bottom Button -->
      <transition 
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="translate-y-4 opacity-0"
        enter-to-class="translate-y-0 opacity-100"
        leave-active-class="transition duration-150 ease-in"
        leave-from-class="translate-y-0 opacity-100"
        leave-to-class="translate-y-4 opacity-0"
      >
        <div v-if="showScrollButton" class="absolute bottom-4 right-1/2 translate-x-1/2 z-10">
          <Button 
            size="sm" 
            class="rounded-full shadow-lg gap-2"
            @click="() => { userHasScrolledUp = false; scrollToBottom('smooth'); }"
          >
            <ArrowDown class="w-4 h-4" />
            <span>{{ t('chat.new_messages') }}</span>
          </Button>
        </div>
      </transition>
    </div>

    <div v-if="chat.error.value" class="max-w-4xl mx-auto w-full px-6 mb-2 shrink-0">
      <div class="bg-destructive/10 text-destructive text-xs p-3 rounded-lg border border-destructive/20">
        {{ chat.error.value }}
      </div>
    </div>

    <div class="shrink-0">
      <ChatInput 
        :loading="chat.loading.value"
        :model-id="chat.model.value"
        :model-supports-vision="currentModelSupportsVision"
        @send="handleSendMessage"
        @send-with-files="handleSendMessageWithFiles"
        @stop="handleStop"
      />
    </div>
  </div>
</template>
