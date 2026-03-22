<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Plus, MessageSquare, Trash2 } from 'lucide-vue-next'
import { useSessions } from '@/composables/useSessions'

const { t } = useI18n()
const sessionsStore = useSessions()

function formatRelativeTime(iso: string): string {
  const timeMs = Date.parse(iso)
  if (!Number.isFinite(timeMs)) return ''
  const diff = Date.now() - timeMs
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return t('common.time.just_now')
  if (mins === 1) return t('common.time.min_ago', { n: mins })
  if (mins < 60) return t('common.time.mins_ago', { n: mins })
  const hours = Math.floor(mins / 60)
  if (hours === 1) return t('common.time.hour_ago', { n: hours })
  if (hours < 24) return t('common.time.hours_ago', { n: hours })
  const days = Math.floor(hours / 24)
  if (days === 1) return t('common.time.day_ago', { n: days })
  return t('common.time.days_ago', { n: days })
}

async function handleNewChat() {
  sessionsStore.newChat()
  // 立即刷新列表，让“新对话”体验更顺滑（虽然 session 会在首次发送后创建）
  await sessionsStore.refreshSessions()
}

async function handleSelectSession(id: string) {
  await sessionsStore.selectSession(id)
}

async function handleDeleteSession(id: string) {
  await sessionsStore.removeSession(id)
}

onMounted(() => {
  // 只在 chat 路由时执行初始化
  const currentPath = window.location.pathname
  if (currentPath !== '/chat') {
    console.log('[HistorySidebar] Skipping initialization, not on chat route:', currentPath)
    return
  }
  
  console.log('[HistorySidebar] Initializing on chat route')
  sessionsStore.refreshSessions()
})
</script>

<template>
  <aside class="w-64 border-r border-border/50 bg-muted/5 flex flex-col h-full overflow-hidden shadow-sm dark:shadow-none">
    <!-- New Chat Button -->
    <div class="p-4 border-b border-border/50">
      <Button class="w-full justify-start gap-2" variant="default" @click="handleNewChat">
        <Plus class="w-4 h-4" />
        {{ t('chat.new_conversation') }}
      </Button>
    </div>

    <!-- Recent History -->
    <div class="flex-1 min-h-0 flex flex-col">
      <div class="px-4 py-3 border-b border-border/50">
        <h3 class="text-[10px] font-bold tracking-wider text-muted-foreground uppercase">
          {{ t('nav.history') }}
        </h3>
      </div>
      <ScrollArea class="flex-1">
        <div class="space-y-1 p-2">
          <div v-if="sessionsStore.sessionsLoading.value" class="px-2 py-2 text-xs text-muted-foreground">
            {{ t('chat.message.loading') }}
          </div>
          <div v-if="sessionsStore.sessionsError.value" class="px-2 py-2 text-xs text-destructive">
            {{ sessionsStore.sessionsError.value }}
          </div>
          <button
            v-for="s in sessionsStore.sessions.value"
            :key="s.id"
            :class="[
              'w-full flex items-start gap-3 px-3 py-2.5 rounded-md text-sm transition-colors text-left',
              sessionsStore.activeSessionId.value === s.id
                ? 'bg-primary/10 text-foreground border border-primary/20'
                : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
            ]"
            @click="handleSelectSession(s.id)"
          >
            <MessageSquare 
              :class="[
                'w-4 h-4 mt-0.5 shrink-0',
                sessionsStore.activeSessionId.value === s.id ? 'text-primary' : 'text-muted-foreground'
              ]" 
            />
            <div class="flex-1 min-w-0 flex flex-col">
              <span class="truncate w-full text-left">{{ s.title }}</span>
              <span class="text-[10px] text-muted-foreground/70">{{ formatRelativeTime(s.updated_at) }}</span>
            </div>
            <button
              class="shrink-0 p-1 rounded hover:bg-muted/60"
              :title="t('chat.delete_conversation')"
              @click.stop="handleDeleteSession(s.id)"
            >
              <Trash2 class="w-4 h-4 text-muted-foreground hover:text-foreground" />
            </button>
          </button>
        </div>
      </ScrollArea>
    </div>
  </aside>
</template>
