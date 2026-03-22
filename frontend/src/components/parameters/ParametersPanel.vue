<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Separator } from '@/components/ui/separator'
import { Settings2, History, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { useParameters } from '@/composables/useParameters'
import { useSystemMetrics } from '@/composables/useSystemMetrics'
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'

const { t } = useI18n()
const params = useParameters()
// 不自动轮询，手动控制
const { metrics, refresh } = useSystemMetrics({ pollInterval: 0 })

const memoryUsageText = computed(() => {
  const m = metrics.value
  if (!m) return '—'
  if (m.vram_total > 0) {
    return `${m.vram_used} / ${m.vram_total} GB`
  }
  return `${m.ram_used} / ${m.ram_total} GB`
})

// 推理速度：来自 /api/system/metrics 的 inference_speed（可选），无数据时显示占位
const inferenceSpeedText = computed(() => {
  const m = metrics.value
  const speed = m?.inference_speed
  if (speed != null && typeof speed === 'number' && speed >= 0) {
    return `${speed.toFixed(1)} t/s`
  }
  return '—'
})

const isCollapsed = ref(false)
let metricsPollTimer: ReturnType<typeof setInterval> | null = null

// 根据面板展开/折叠状态控制轮询
const startMetricsPolling = () => {
  if (metricsPollTimer) return
  refresh() // 立即刷新一次
  // 每10秒轮询一次（降低频率）
  metricsPollTimer = setInterval(() => {
    refresh()
  }, 10000)
}

const stopMetricsPolling = () => {
  if (metricsPollTimer) {
    clearInterval(metricsPollTimer)
    metricsPollTimer = null
  }
}

// 监听折叠状态
watch(isCollapsed, (collapsed) => {
  if (collapsed) {
    stopMetricsPolling()
  } else {
    startMetricsPolling()
  }
})

onMounted(() => {
  // 如果初始状态是展开的，开始轮询
  if (!isCollapsed.value) {
    startMetricsPolling()
  }
})

onUnmounted(() => {
  stopMetricsPolling()
})

// Slider 处理 (Radix Slider 接收数组)
const tempValue = {
  get: () => [params.temperature.value],
  set: (val: number[] | undefined) => { 
    const v = val?.[0]
    if (typeof v === 'number') params.temperature.value = v
  }
}

const topPValue = {
  get: () => [params.top_p.value],
  set: (val: number[] | undefined) => { 
    const v = val?.[0]
    if (typeof v === 'number') params.top_p.value = v
  }
}

const historyValue = {
  get: () => [params.maxHistoryMessages.value],
  set: (val: number[] | undefined) => { 
    const v = val?.[0]
    if (typeof v === 'number') params.maxHistoryMessages.value = v
  }
}
</script>

<template>
  <aside
    class="border-l bg-background flex flex-col h-full overflow-hidden transition-all duration-200"
    :class="isCollapsed ? 'w-12' : 'w-80'"
  >
    <div class="p-4 flex items-center justify-between text-sm font-bold tracking-wider uppercase text-muted-foreground shrink-0">
      <div v-if="!isCollapsed" class="flex items-center gap-2">
        <Settings2 class="w-4 h-4" />
        {{ t('chat.parameters.title') }}
      </div>
      <button
        class="ml-auto h-7 w-7 rounded-lg border border-border/50 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
        @click="isCollapsed = !isCollapsed"
      >
        <ChevronRight v-if="isCollapsed" class="w-4 h-4" />
        <ChevronLeft v-else class="w-4 h-4" />
      </button>
    </div>
    
    <Separator v-if="!isCollapsed" />

    <div v-if="!isCollapsed" class="flex-1 overflow-y-auto p-4 space-y-8">
      <!-- Temperature -->
      <div class="space-y-4">
        <div class="flex justify-between items-center">
          <label class="text-xs font-medium uppercase text-muted-foreground">{{ t('chat.parameters.temperature') }}</label>
          <span class="text-xs font-bold bg-muted px-1.5 py-0.5 rounded">{{ params.temperature.value.toFixed(1) }}</span>
        </div>
        <Slider 
          :model-value="tempValue.get()" 
          @update:model-value="tempValue.set"
          :max="2" 
          :min="0"
          :step="0.1" 
        />
        <div class="flex justify-between text-[10px] text-muted-foreground font-medium uppercase">
          <span>{{ t('chat.parameters.precise') }}</span>
          <span>{{ t('chat.parameters.creative') }}</span>
        </div>
      </div>

      <!-- Top P -->
      <div class="space-y-4">
        <div class="flex justify-between items-center">
          <label class="text-xs font-medium uppercase text-muted-foreground">{{ t('chat.parameters.top_p') }}</label>
          <span class="text-xs font-bold bg-muted px-1.5 py-0.5 rounded">{{ params.top_p.value.toFixed(1) }}</span>
        </div>
        <Slider 
          :model-value="topPValue.get()" 
          @update:model-value="topPValue.set"
          :max="1" 
          :min="0"
          :step="0.1" 
        />
      </div>

      <!-- Max Tokens -->
      <div class="space-y-3">
        <label class="text-xs font-medium uppercase text-muted-foreground">{{ t('chat.parameters.max_tokens') }}</label>
        <div class="relative">
          <Input
            v-model.number="params.maxTokens.value"
            type="number"
            class="h-10 pr-16 font-mono"
            :min="256"
            :max="8192"
          />
          <span class="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground font-bold uppercase">{{ t('chat.parameters.tokens') }}</span>
        </div>
        <p class="text-[10px] text-muted-foreground">256–8192</p>
      </div>

      <!-- Max History Messages -->
      <div class="space-y-4">
        <div class="flex justify-between items-center">
          <div class="flex items-center gap-1.5">
            <History class="w-3.5 h-3.5 text-muted-foreground" />
            <label class="text-xs font-medium uppercase text-muted-foreground">{{ t('chat.parameters.max_history') }}</label>
          </div>
          <span class="text-xs font-bold bg-muted px-1.5 py-0.5 rounded">{{ params.maxHistoryMessages.value }}</span>
        </div>
        <Slider 
          :model-value="historyValue.get()" 
          @update:model-value="historyValue.set"
          :max="50" 
          :min="1"
          :step="1" 
        />
      </div>

      <!-- System Prompt -->
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <label class="text-xs font-medium uppercase text-muted-foreground">{{ t('chat.parameters.system_prompt') }}</label>
            <p class="text-[10px] text-muted-foreground">{{ t('chat.parameters.override_desc') }}</p>
          </div>
          <Switch 
            :checked="params.useSystemPrompt.value" 
            @update:checked="params.useSystemPrompt.value = $event" 
          />
        </div>
        <Textarea 
          v-model="params.systemPrompt.value"
          :disabled="!params.useSystemPrompt.value"
          :placeholder="t('chat.parameters.system_prompt_placeholder')" 
          class="min-h-[120px] bg-muted/30 resize-none text-sm leading-relaxed"
        />
      </div>

      <!-- Context Window -->
      <div class="space-y-3">
        <label class="text-xs font-medium uppercase text-muted-foreground">{{ t('chat.parameters.context_window') }}</label>
        <div class="relative">
          <Input :model-value="params.contextWindow.value.toString()" disabled class="h-10 pr-16 font-mono opacity-50" />
          <span class="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground font-bold uppercase">{{ t('chat.parameters.tokens') }}</span>
        </div>
      </div>
    </div>

    <!-- Stats -->
    <div v-if="!isCollapsed" class="p-4 border-t bg-muted/10 grid grid-cols-2 gap-4">
      <div>
        <p class="text-[10px] font-bold text-muted-foreground uppercase">{{ t('chat.parameters.memory_usage') }}</p>
        <p class="text-sm font-bold">{{ memoryUsageText }}</p>
      </div>
      <div>
        <p class="text-[10px] font-bold text-muted-foreground uppercase">{{ t('chat.parameters.inference_speed') }}</p>
        <p class="text-sm font-bold">{{ inferenceSpeedText }}</p>
      </div>
    </div>
  </aside>
</template>
