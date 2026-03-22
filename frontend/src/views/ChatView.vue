<script setup lang="ts">
import { defineOptions } from 'vue'
import HistorySidebar from '@/components/layout/HistorySidebar.vue'
import ChatWindow from '@/components/chat/ChatWindow.vue'
import ParametersPanel from '@/components/parameters/ParametersPanel.vue'

defineOptions({ name: 'ChatView' })
</script>

<template>
  <div class="flex flex-1 min-w-0 min-h-0 overflow-hidden">
    <HistorySidebar />
    <div class="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
      <ChatWindow />
    </div>
    <ParametersPanel />
  </div>
</template>