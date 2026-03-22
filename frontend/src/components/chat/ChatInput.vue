<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Paperclip, ArrowUp, Square, Globe, Eye, AlertTriangle, Mic } from 'lucide-vue-next'
import { asrTranscribe } from '@/services/api'

interface Props {
  loading?: boolean
  disabled?: boolean
  modelId?: string  // Add modelId prop to detect VLM models
  modelSupportsVision?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
  disabled: false,
  modelId: '',
  modelSupportsVision: false
})

const emit = defineEmits<{
  (e: 'send', content: string): void
  (e: 'send-with-files', content: string, files: File[]): void
  (e: 'stop'): void
  (e: 'voice-transcribed', text: string): void
}>()

const { t } = useI18n()
const message = ref('')
const webSearchEnabled = ref(true)
const visionEnabled = ref(true)
const uploadedFiles = ref<File[]>([])
const fileInputRef = ref<HTMLInputElement | null>(null)

// 麦克风录音 (ASR)
const MAX_RECORDING_SECONDS = 120  // 最大录音时长 2 分钟
const isRecording = ref(false)
const asrLoading = ref(false)
const asrError = ref<string | null>(null)
let mediaRecorder: MediaRecorder | null = null
let audioChunks: Blob[] = []
let recordingTimerRef: ReturnType<typeof setTimeout> | null = null

// Create preview URLs for uploaded files
const filePreviewUrls = computed(() => {
  return uploadedFiles.value.map(file => URL.createObjectURL(file))
})

// Check if current model supports image input.
// 'auto' mode is considered image-capable because backend will auto-switch to VLM when images are detected.
const isCurrentModelVLM = computed(() => {
  const id = props.modelId?.toLowerCase() ?? ''
  if (id === 'auto') return true
  return props.modelSupportsVision === true
})

// Show warning when images are attached but current model isn't VLM
// Note: auto mode won't show warning because backend handles the switch
const showVLMWarning = computed(() => {
  return !isCurrentModelVLM.value && uploadedFiles.value.length > 0
})

// Clear ASR error when user edits message
watch(() => message.value, () => {
  if (asrError.value) asrError.value = null
})

// Watch for model changes to clear files if switching away from image-capable model.
watch(
  () => [props.modelId, props.modelSupportsVision] as const,
  ([newModel, newSupportsVision], [oldModel, oldSupportsVision]) => {
    const wasAuto = (oldModel?.toLowerCase() ?? '') === 'auto'
    const isAuto = (newModel?.toLowerCase() ?? '') === 'auto'
    const wasImageCapable = wasAuto || oldSupportsVision === true
    const isImageCapable = isAuto || newSupportsVision === true

    if (wasImageCapable && !isImageCapable && uploadedFiles.value.length > 0) {
      uploadedFiles.value = []
    }
  }
)

const handleSend = () => {
  if (message.value.trim() && !props.loading && !props.disabled) {
    if (uploadedFiles.value.length > 0) {
      emit('send-with-files', message.value, uploadedFiles.value)
    } else {
      emit('send', message.value)
    }
    message.value = ''
    uploadedFiles.value = []
  }
}

const handleStop = () => {
  emit('stop')
}

const handleKeydown = (e: KeyboardEvent) => {
  if (e.isComposing) return

  // Enter 默认换行，不自动发送
  // 用户需要手动点击发送按钮
}

const handleFileSelect = (e: Event) => {
  const target = e.target as HTMLInputElement
  const files = target.files
  if (files) {
    // Filter for image files only
    const imageFiles = Array.from(files).filter(file => 
      file.type.startsWith('image/')
    )
    
    if (imageFiles.length > 0) {
      uploadedFiles.value = [...uploadedFiles.value, ...imageFiles]
    }
    
    // Clear the input
    if (fileInputRef.value) {
      fileInputRef.value.value = ''
    }
  }
}

const removeFile = (index: number) => {
  uploadedFiles.value.splice(index, 1)
}

const triggerFileInput = () => {
  if (fileInputRef.value) {
    fileInputRef.value.click()
  }
}

// 清除录音定时器
const clearRecordingTimer = () => {
  if (recordingTimerRef) {
    clearTimeout(recordingTimerRef)
    recordingTimerRef = null
  }
}

// 麦克风录音 → ASR → 文本
const toggleVoiceInput = async () => {
  if (asrLoading.value || props.loading || props.disabled) return

  if (isRecording.value) {
    // 停止录音
    clearRecordingTimer()
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop()
    }
    return
  }

  try {
    asrError.value = null
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm'
    mediaRecorder = new MediaRecorder(stream)
    audioChunks = []

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data)
    }

    mediaRecorder.onstop = async () => {
      clearRecordingTimer()
      stream.getTracks().forEach((t) => t.stop())
      if (audioChunks.length === 0) {
        isRecording.value = false
        return
      }
      const blob = new Blob(audioChunks, { type: mimeType })
      isRecording.value = false
      asrLoading.value = true
      try {
        const result = await asrTranscribe(blob)
        const text = (result.text || '').trim()
        if (text) {
          message.value = message.value ? `${message.value}\n${text}` : text
          emit('voice-transcribed', text)
        }
      } catch (err) {
        asrError.value = err instanceof Error ? err.message : String(err)
      } finally {
        asrLoading.value = false
      }
    }

    mediaRecorder.start()
    isRecording.value = true

    // 最大录音时长：超时自动停止
    recordingTimerRef = setTimeout(() => {
      if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop()
      }
    }, MAX_RECORDING_SECONDS * 1000)
  } catch (err) {
    asrError.value = err instanceof Error ? err.message : String(err)
    if (err instanceof Error && err.name === 'NotAllowedError') {
      asrError.value = t('chat.voice_permission_denied')
    }
  }
}

onUnmounted(() => {
  clearRecordingTimer()
})
</script>

<template>
  <div class="border-t border-border/50 bg-background shadow-[0_-4px_12px_rgba(0,0,0,0.03)] dark:shadow-none">
    <div class="max-w-3xl mx-auto px-4 py-4 space-y-3">
      <!-- Plugin Tags -->
      <div class="flex items-center gap-2">
        <Badge 
          v-if="webSearchEnabled"
          class="h-5 px-2.5 gap-1.5 bg-emerald-500/10 text-emerald-500 border-none text-[10px] font-medium"
        >
          <Globe class="w-3 h-3" />
          {{ t('chat.web_search') }}
        </Badge>
        <Badge 
          v-if="visionEnabled"
          class="h-5 px-2.5 gap-1.5 bg-muted text-muted-foreground border-none text-[10px] font-medium"
        >
          <Eye class="w-3 h-3" />
          {{ t('chat.vision') }}
        </Badge>
      </div>

      <!-- File Preview -->
      <div v-if="uploadedFiles.length > 0" class="flex flex-wrap gap-2">
        <div 
          v-for="(file, index) in uploadedFiles" 
          :key="index"
          class="relative group"
        >
          <div class="w-16 h-16 rounded-lg border border-border overflow-hidden">
            <img 
              :src="filePreviewUrls[index]" 
              :alt="file.name"
              class="w-full h-full object-cover"
            />
          </div>
          <Button
            variant="ghost"
            size="icon"
            class="absolute -top-2 -right-2 h-6 w-6 rounded-full bg-destructive text-destructive-foreground opacity-0 group-hover:opacity-100 transition-opacity"
            @click="removeFile(index)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 6 6 18"/>
              <path d="m6 6 12 12"/>
            </svg>
          </Button>
        </div>
      </div>

      <!-- Input Area -->
      <div class="relative group">
        <Textarea 
          v-model="message"
          :disabled="loading || disabled"
          :placeholder="t('chat.input_placeholder')"
          class="min-h-[60px] max-h-[200px] pr-28 py-4 resize-none bg-muted/20 border border-border rounded-xl focus-visible:ring-2 focus-visible:ring-primary/20 focus-visible:border-primary focus-visible:bg-background transition-all disabled:opacity-50 text-sm"
          @keydown="handleKeydown"
        />
        
        <!-- Hidden File Input -->
        <input
          ref="fileInputRef"
          type="file"
          accept="image/*"
          multiple
          class="hidden"
          @change="handleFileSelect"
        />
        
        <!-- Left Icons -->
        <div class="absolute left-3 bottom-3 flex items-center gap-2">
          <Button 
            variant="ghost" 
            size="icon" 
            class="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted"
            :disabled="loading || disabled"
            @click="triggerFileInput"
          >
            <Paperclip class="w-4 h-4" />
          </Button>
          <Button 
            variant="ghost" 
            size="icon" 
            class="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted"
            :class="{ 'text-destructive animate-pulse': isRecording }"
            :disabled="loading || disabled"
            :title="isRecording ? t('chat.voice_stop') : asrLoading ? t('chat.voice_transcribing') : t('chat.voice_start')"
            @click="toggleVoiceInput"
          >
            <Mic v-if="!isRecording && !asrLoading" class="w-4 h-4" />
            <Square v-else-if="isRecording" class="w-4 h-4" />
            <span v-else class="text-xs text-muted-foreground">{{ t('chat.voice_transcribing') }}</span>
          </Button>
          
          <!-- VLM Warning -->
          <div v-if="showVLMWarning" class="flex items-center gap-1 text-amber-600 bg-amber-50 px-2 py-1 rounded text-xs">
            <AlertTriangle class="w-3 h-3" />
            <span class="hidden sm:inline">{{ t('chat.vision.model_not_supported') }}</span>
          </div>
          <!-- ASR Error -->
          <div v-if="asrError" class="flex items-center gap-1 text-destructive bg-destructive/10 px-2 py-1 rounded text-xs">
            <AlertTriangle class="w-3 h-3 shrink-0" />
            <span>{{ asrError }}</span>
          </div>
        </div>

        <!-- Right Icons -->
        <div class="absolute right-3 bottom-3 flex items-center gap-2">
          <Button 
            v-if="loading"
            variant="ghost" 
            size="icon" 
            class="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted"
            @click="handleStop"
          >
            <Square class="w-4 h-4" />
          </Button>
          <Button 
            size="icon" 
            class="h-8 w-8 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90"
            :disabled="!message.trim() || loading || disabled"
            @click="handleSend"
          >
            <ArrowUp class="w-4 h-4" />
          </Button>
        </div>
      </div>

      <!-- Footer Disclaimer -->
      <p class="text-[10px] text-center text-muted-foreground">
        {{ t('chat.input_footer') }}
      </p>
    </div>
  </div>
</template>
