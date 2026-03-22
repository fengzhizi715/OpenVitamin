<script setup lang="ts">
import NavigationSidebar from '@/components/layout/NavigationSidebar.vue'
import { onMounted } from 'vue'

onMounted(() => {
  // Initialize theme from localStorage if available, otherwise default to dark
  const savedTheme = localStorage.getItem('platform-theme') || 'dark'
  const root = document.documentElement
  root.classList.remove('light', 'dark')
  
  if (savedTheme === 'system') {
    const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    root.classList.add(systemTheme)
  } else {
    root.classList.add(savedTheme)
  }
})
</script>

<template>
  <div class="flex h-screen w-full bg-background text-foreground overflow-hidden">
    <!-- Navigation Sidebar (Left) -->
    <NavigationSidebar />
    
    <!-- Main content: flex-1 + min-w-0 确保与侧边栏并排且正确收缩 -->
    <div class="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden">
      <router-view v-slot="{ Component, route }">
        <keep-alive :include="['ChatView', 'WorkflowView', 'AgentsView', 'ModelsView', 'KnowledgeView', 'SkillsView', 'SettingsGeneralView', 'SettingsBackendView', 'SettingsObjectDetectionView', 'SettingsAsrView', 'SettingsBackupView', 'SettingsRuntimeView', 'SettingsModelBackupView']">
          <component :is="Component" :key="route.path" />
        </keep-alive>
      </router-view>
    </div>
  </div>
</template>

<style>
/* Reset some default styles */
html, body, #app {
  height: 100%;
  margin: 0;
  padding: 0;
}
</style>
