<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useNavigation, type ViewType } from '@/composables/useNavigation'
import { useI18n } from 'vue-i18n'
import { 
  MessageSquare, 
  Settings,
  Database,
  BookOpen,
  BarChart3,
  User,
  Bot,
  Zap,
  Sparkles,
  Workflow,
  ChevronLeft,
  Image
} from 'lucide-vue-next'
import { getSystemConfig } from '@/services/api'

const { activeView, setView } = useNavigation()
const { t } = useI18n()

// Collapsible sidebar state
const isCollapsed = ref(false)
const systemVersion = ref<string>('')
const toggleSidebar = () => {
  isCollapsed.value = !isCollapsed.value
}

onMounted(async () => {
  try {
    const config = await getSystemConfig()
    systemVersion.value = config.version || ''
  } catch (error) {
    console.error('Failed to fetch system version:', error)
  }
})

// Navigation items grouped by category
const navGroups = computed(() => [
  {
    id: 'primary',
    label: '',
    items: [
      { id: 'chat' as ViewType, label: t('nav.chat'), icon: MessageSquare },
      { id: 'images' as ViewType, label: t('nav.images'), icon: Image },
      { id: 'agents' as ViewType, label: t('nav.agents'), icon: Bot },
      { id: 'workflow' as ViewType, label: t('nav.workflow'), icon: Workflow },
      { id: 'knowledge' as ViewType, label: t('nav.knowledge'), icon: BookOpen },
      { id: 'skills' as ViewType, label: t('nav.skills'), icon: Sparkles },
      { id: 'models' as ViewType, label: t('nav.models'), icon: Database },
    ]
  },
  {
    id: 'system',
    label: t('nav.system') || 'System',
    items: [
      { id: 'logs' as ViewType, label: t('nav.logs'), icon: BarChart3 },
      { id: 'settings' as ViewType, label: t('nav.settings'), icon: Settings },
    ]
  }
])
</script>

<template>
  <aside 
    :class="[
      'border-r border-border/40 bg-background flex flex-col h-full overflow-hidden relative z-20 transition-all duration-300',
      isCollapsed ? 'w-[72px]' : 'w-[200px]'
    ]"
  >
    <!-- Header：收缩时仅 Logo，展开时 Logo + 收起按钮 -->
    <div
      :class="[
        'flex p-3 transition-all duration-200 shrink-0',
        isCollapsed ? 'justify-center' : 'items-center justify-between'
      ]"
    >
      <div
        class="w-11 h-11 bg-gradient-to-br from-[#4f46e5] to-[#7c3aed] rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-500/25 active:scale-95 transition-transform cursor-pointer shrink-0"
        :title="isCollapsed ? (t('nav.expand') || 'Expand') : (t('nav.collapse') || 'Collapse')"
        @click="toggleSidebar"
      >
        <Zap class="w-6 h-6 text-white" />
      </div>
      <button
        v-if="!isCollapsed"
        @click="toggleSidebar"
        class="p-2 rounded-xl text-muted-foreground/60 hover:text-foreground hover:bg-muted/60 transition-all"
      >
        <ChevronLeft class="w-5 h-5" />
      </button>
    </div>

    <!-- Navigation Menu - Scrollable -->
    <div class="flex-1 overflow-y-auto overflow-x-hidden px-3 py-2 space-y-6 scrollbar-thin">
      <div 
        v-for="(group, groupIndex) in navGroups" 
        :key="group.id"
        class="space-y-2"
      >
        <!-- Group Label -->
        <div 
          v-if="!isCollapsed && group.label" 
          class="px-3 pt-1"
        >
          <span class="text-[11px] font-bold tracking-[0.08em] text-muted-foreground/40 uppercase">
            {{ group.label }}
          </span>
        </div>
        <div 
          v-else-if="groupIndex > 0"
          class="px-3 pt-2 flex justify-center"
        >
          <div class="w-6 h-px bg-border/30"></div>
        </div>

        <!-- Nav Items -->
        <div :class="['space-y-1', isCollapsed ? 'flex flex-col items-center' : '']">
          <button
            v-for="nav in group.items"
            :key="nav.id"
            :class="[
              'group w-full flex items-center transition-all duration-200 relative',
              isCollapsed
                ? 'justify-center w-11 h-11 min-w-11 rounded-2xl'
                : 'justify-start py-3 px-4 rounded-2xl gap-3.5',
              activeView === nav.id
                ? 'bg-[#4f46e5] text-white shadow-lg shadow-indigo-500/30'
                : 'text-muted-foreground/70 hover:bg-muted/60 hover:text-foreground'
            ]"
            @click="setView(nav.id)"
            :title="isCollapsed ? nav.label : ''"
          >
            <component
              :is="nav.icon"
              :class="[
                'shrink-0 transition-all duration-200',
                isCollapsed ? 'w-5 h-5' : 'w-[22px] h-[22px]',
                activeView === nav.id ? 'stroke-[2px]' : 'stroke-[1.8px]'
              ]"
            />
            <span
              v-if="!isCollapsed"
              class="text-[14px] font-medium tracking-tight"
            >
              {{ nav.label }}
            </span>
            <!-- Active: 展开时右侧圆点 -->
            <div
              v-if="activeView === nav.id && !isCollapsed"
              class="absolute right-3 w-2 h-2 bg-white/90 rounded-full"
            />
            <!-- Active: 收缩时左侧竖条 -->
            <div
              v-if="activeView === nav.id && isCollapsed"
              class="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-white/90 rounded-r"
            />
          </button>
        </div>
      </div>
    </div>

    <!-- Bottom Section：收起/展开改为点 Logo，此处保留版本与用户区 -->
    <div class="mt-auto p-3 border-t border-border/30 space-y-2">
      <div
        v-if="systemVersion"
        :class="[
          'rounded-2xl border border-border/40 bg-muted/30 transition-all',
          isCollapsed ? 'px-2 py-2 flex justify-center' : 'px-3 py-2.5'
        ]"
        :title="isCollapsed ? `${t('nav.version') || 'Version'} v${systemVersion}` : ''"
      >
        <span v-if="isCollapsed" class="text-[11px] font-semibold text-muted-foreground/70">v{{ systemVersion }}</span>
        <div v-else class="flex items-center justify-between gap-3">
          <span class="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground/45">{{ t('nav.version') }}</span>
          <span class="text-[12px] font-semibold text-foreground/80">v{{ systemVersion }}</span>
        </div>
      </div>
      <!-- User Profile -->
      <button 
        class="w-full flex items-center gap-3 group transition-all duration-200 rounded-2xl p-2.5 hover:bg-muted/60"
        :class="isCollapsed ? 'justify-center' : 'justify-start'"
      >
        <div class="relative shrink-0">
          <div class="rounded-full bg-gradient-to-br from-muted/80 to-muted/40 border border-border/50 flex items-center justify-center overflow-hidden group-hover:border-indigo-500/50 transition-all duration-300 relative z-10"
            :class="isCollapsed ? 'w-9 h-9' : 'w-9 h-9'"
          >
            <User class="text-muted-foreground/70 group-hover:text-indigo-400 transition-colors"
              :class="isCollapsed ? 'w-[18px] h-[18px]' : 'w-[18px] h-[18px]'"
            />
          </div>
          <!-- Online Status Indicator -->
          <div class="absolute bottom-0 right-0 w-2.5 h-2.5 bg-emerald-500 border-2 border-background rounded-full z-20"></div>
        </div>
        <div v-if="!isCollapsed" class="flex flex-col items-start min-w-0">
          <span class="text-[13px] font-medium text-foreground/90 truncate">{{ t('nav.guest') }}</span>
          <span class="text-[11px] text-muted-foreground/50 truncate">{{ t('nav.online') }}</span>
        </div>
      </button>
    </div>
  </aside>
</template>
