import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { streamLogs, type LogEntry } from '@/services/api'

interface LogEntryWithId extends LogEntry {
  id: string
}

const logs = ref<LogEntryWithId[]>([])
const isStreaming = ref(true)
const error = ref<string | null>(null)
let stopLogsStream: (() => void) | null = null

export function useLogs() {
  const { t } = useI18n()
  
  const startStreaming = () => {
    if (stopLogsStream) return // Already streaming
    
    error.value = null
    isStreaming.value = true
    
    stopLogsStream = streamLogs(
      (entry) => {
        if (!isStreaming.value) return
        
        const newEntry: LogEntryWithId = {
          ...entry,
          id: Math.random().toString(36).substr(2, 9)
        }
        
        logs.value.push(newEntry)
        if (logs.value.length > 1000) {
          logs.value.shift()
        }
      },
      (err) => {
        error.value = err.message || t('logs.error_state.message')
        isStreaming.value = false
        stopLogsStream = null
      }
    )
  }

  const stopStreaming = () => {
    if (stopLogsStream) {
      stopLogsStream()
      stopLogsStream = null
      isStreaming.value = false
    }
  }

  const clearLogs = () => {
    logs.value = []
  }

  return {
    logs,
    isStreaming,
    error,
    startStreaming,
    stopStreaming,
    clearLogs
  }
}
