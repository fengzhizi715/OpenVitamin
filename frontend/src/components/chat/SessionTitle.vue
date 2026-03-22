<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { Pencil, Check, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

const props = defineProps<{
  title: string | null | undefined
  sessionId: string | null
}>()

const emit = defineEmits<{
  (e: 'update:title', sessionId: string, newTitle: string): void
}>()

const { t } = useI18n()

const isEditing = ref(false)
const editValue = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

const displayTitle = computed(() => {
  return props.title || t('chat.new_conversation')
})

const canEdit = computed(() => {
  return !!props.sessionId
})

function startEdit() {
  if (!canEdit.value) return
  editValue.value = props.title || ''
  isEditing.value = true
  nextTick(() => {
    inputRef.value?.focus()
    inputRef.value?.select()
  })
}

function cancelEdit() {
  isEditing.value = false
  editValue.value = ''
}

function confirmEdit() {
  const newTitle = editValue.value.trim()
  if (newTitle && props.sessionId && newTitle !== props.title) {
    emit('update:title', props.sessionId, newTitle)
  }
  isEditing.value = false
  editValue.value = ''
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    confirmEdit()
  } else if (e.key === 'Escape') {
    cancelEdit()
  }
}

// Watch for external title changes
watch(() => props.title, (newTitle) => {
  if (!isEditing.value) {
    editValue.value = newTitle || ''
  }
})
</script>

<template>
  <div class="flex items-center gap-2">
    <!-- View Mode -->
    <div
      v-if="!isEditing"
      class="flex items-center gap-2 group cursor-pointer"
      @click="startEdit"
    >
      <h2 
        class="text-sm font-medium text-foreground truncate max-w-[300px] hover:text-primary transition-colors"
        :title="displayTitle"
      >
        {{ displayTitle }}
      </h2>
      <Button
        v-if="canEdit"
        variant="ghost"
        size="icon"
        class="h-6 w-6 opacity-60 hover:opacity-100 transition-opacity"
        @click.stop="startEdit"
      >
        <Pencil class="w-3 h-3" />
      </Button>
    </div>

    <!-- Edit Mode -->
    <div
      v-else
      class="flex items-center gap-1"
    >
      <Input
        ref="inputRef"
        v-model="editValue"
        class="h-7 text-sm w-[250px]"
        :placeholder="t('chat.title_placeholder')"
        @keydown="handleKeydown"
        @blur="confirmEdit"
      />
      <Button
        variant="ghost"
        size="icon"
        class="h-7 w-7"
        @click="confirmEdit"
      >
        <Check class="w-4 h-4 text-emerald-500" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="h-7 w-7"
        @click="cancelEdit"
      >
        <X class="w-4 h-4 text-muted-foreground" />
      </Button>
    </div>
  </div>
</template>
