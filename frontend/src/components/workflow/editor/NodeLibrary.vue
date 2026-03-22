<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  Brain,
  User,
  Layers,
  FileText,
  MessageSquare,
  LogIn,
  LogOut,
  Variable,
  GitBranch,
  Repeat,
  Copy,
  Sparkles,
  Globe,
  Code,
  Terminal,
  type LucideIcon,
} from 'lucide-vue-next'
import { NODE_LIBRARY, NODE_CATEGORY_LABELS, type NodeLibraryItem, type EditorNodeType, type NodeCategory } from './types'

const { t } = useI18n()

const iconMap: Record<EditorNodeType, typeof Brain> = {
  start: Brain,
  llm: Brain,
  agent: User,
  embedding: Layers,
  prompt_template: FileText,
  system_prompt: MessageSquare,
  input: LogIn,
  output: LogOut,
  variable: Variable,
  condition: GitBranch,
  loop: Repeat,
  parallel: Copy,
  skill: Sparkles,
  http_request: Globe,
  python: Code,
  shell: Terminal,
}

const categories: NodeCategory[] = ['ai', 'prompt', 'data', 'logic', 'tool']

function getIcon(item: NodeLibraryItem): LucideIcon {
  return iconMap[item.type] ?? Brain
}

function onDragStart(e: DragEvent, item: NodeLibraryItem) {
  if (item.disabled || !e.dataTransfer) return
  e.dataTransfer.setData('application/vnd.workflow-node', JSON.stringify({ type: item.type, label: item.label }))
  e.dataTransfer.effectAllowed = 'move'
}
</script>

<template>
  <div class="flex flex-col h-full bg-card border-r border-border/50 overflow-hidden">
    <div class="px-4 py-3 border-b border-border/50">
      <h2 class="text-sm font-semibold text-foreground">{{ t('workflow_editor.node_library_title') }}</h2>
      <p class="text-xs text-muted-foreground mt-0.5">{{ t('workflow_editor.node_library_desc') }}</p>
    </div>
    <div class="flex-1 overflow-y-auto p-3 space-y-6">
      <template v-for="cat in categories" :key="cat">
        <div class="space-y-2">
          <h3 class="text-xs font-medium uppercase tracking-wider text-muted-foreground px-1">
            {{ t(`workflow_editor.category_${cat}`) || NODE_CATEGORY_LABELS[cat] }}
          </h3>
          <div class="space-y-1">
            <div
              v-for="item in NODE_LIBRARY.filter((n) => n.category === cat)"
              :key="item.type"
              class="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-border/50 bg-background/80 transition-colors"
              :class="item.disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-grab active:cursor-grabbing hover:border-primary/50 hover:bg-muted/30'"
              :draggable="!item.disabled"
              @dragstart="onDragStart($event, item)"
            >
              <component
                :is="getIcon(item)"
                class="w-5 h-5 shrink-0 text-muted-foreground"
              />
              <div class="min-w-0">
                <div class="text-sm font-medium text-foreground">{{ item.label }}</div>
                <div v-if="item.disabledReason" class="text-[11px] text-muted-foreground truncate">{{ item.disabledReason }}</div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
