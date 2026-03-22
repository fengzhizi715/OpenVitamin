<script setup lang="ts">
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { 
  Plus, 
  MessageSquare, 
  Database,
  BarChart3,
  User
} from 'lucide-vue-next'

const activeNav = ref('chat')

const recentHistory = [
  { id: 1, title: 'Fixing React state bug', time: '2 mins ago' },
  { id: 2, title: 'Explain Llama-3 Quantization', time: 'Yesterday' },
  { id: 3, title: 'Marketing Email Draft', time: '3 days ago' },
]

const navItems = [
  { id: 'chat', label: 'CHAT', icon: MessageSquare },
  { id: 'models', label: 'MODELS', icon: Database },
  { id: 'logs', label: 'LOGS', icon: BarChart3 },
]
</script>

<template>
  <aside class="w-64 border-r border-border/50 bg-background flex flex-col h-full overflow-hidden">
    <!-- Header -->
    <div class="p-4 flex items-center gap-3 border-b border-border/50">
      <div class="w-8 h-8 bg-blue-600 rounded-md flex items-center justify-center shrink-0">
        <MessageSquare class="w-5 h-5 text-white" />
      </div>
      <div class="min-w-0">
        <h2 class="text-sm font-semibold leading-tight">AI Console</h2>
        <p class="text-xs text-muted-foreground">Local-First Engine</p>
      </div>
    </div>

    <!-- New Chat Button -->
    <div class="p-4 pb-3">
      <Button class="w-full justify-start gap-2" variant="default">
        <Plus class="w-4 h-4" />
        New Chat
      </Button>
    </div>

    <!-- Recent History -->
    <div class="px-4 pb-4 flex-1 min-h-0 flex flex-col">
      <h3 class="text-[10px] font-bold tracking-wider text-muted-foreground uppercase mb-2 px-2">
        RECENT HISTORY
      </h3>
      <ScrollArea class="flex-1">
        <div class="space-y-1 px-2">
          <button
            v-for="item in recentHistory"
            :key="item.id"
            class="w-full flex flex-col items-start px-2 py-2 rounded-md text-sm transition-colors text-left hover:bg-muted/50 text-muted-foreground hover:text-foreground"
          >
            <span class="truncate w-full text-left">{{ item.title }}</span>
            <span class="text-[10px] text-muted-foreground/70">{{ item.time }}</span>
          </button>
        </div>
      </ScrollArea>
    </div>

    <!-- Navigation Menu -->
    <div class="px-4 py-3 space-y-1 border-t border-border/50">
      <button
        v-for="nav in navItems"
        :key="nav.id"
        :class="[
          'w-full flex items-center gap-3 px-2 py-2 rounded-md text-sm transition-colors',
          activeNav === nav.id 
            ? 'bg-primary text-primary-foreground font-medium' 
            : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
        ]"
        @click="activeNav = nav.id"
      >
        <component :is="nav.icon" class="w-4 h-4 shrink-0" />
        <span class="text-xs font-medium tracking-wide">{{ nav.label }}</span>
      </button>
    </div>

    <!-- Bottom Section -->
    <div class="mt-auto border-t border-border/50 py-2 flex justify-center">
      <!-- User Profile -->
      <Button variant="ghost" size="icon" class="h-10 w-10 text-muted-foreground hover:text-foreground shrink-0">
        <User class="w-5 h-5" />
      </Button>
    </div>
  </aside>
</template>
