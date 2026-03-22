<script setup lang="ts">
import { defineOptions } from 'vue'
import SkillsRegistryView from '@/components/skills/SkillsRegistryView.vue'

defineOptions({ name: 'SkillsView' })
</script>

<template>
  <div class="flex-1 flex flex-col min-h-0 h-full overflow-hidden">
    <SkillsRegistryView />
  </div>
</template>
