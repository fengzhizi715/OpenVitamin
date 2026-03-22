import { ref, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import { getSystemMetrics, type SystemMetrics } from '@/services/api'

export interface UseSystemMetricsOptions {
  /** 轮询间隔（毫秒），不传则仅首次加载 */
  pollInterval?: number
}

/**
 * 通用系统指标（VRAM、CPU、RAM 等）获取
 * 多处复用：模型配置、智能体创建/列表、设置页
 */
export function useSystemMetrics(options?: UseSystemMetricsOptions) {
  const metrics = ref<SystemMetrics | null>(null)

  const refresh = async () => {
    try {
      metrics.value = await getSystemMetrics()
    } catch {
      metrics.value = null
    }
  }

  let pollTimer: ReturnType<typeof setInterval> | null = null

  const startPolling = () => {
    if (pollTimer) return
    refresh()
    if (options?.pollInterval && options.pollInterval > 0) {
      pollTimer = setInterval(refresh, options.pollInterval)
    }
  }

  const stopPolling = () => {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  onMounted(() => {
    startPolling()
  })

  onActivated(() => {
    startPolling()
  })

  onDeactivated(() => {
    stopPolling()
  })

  onUnmounted(() => {
    stopPolling()
  })

  return { metrics, refresh }
}
