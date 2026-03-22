import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

// 路由配置
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/chat'
  },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('@/views/ChatView.vue'),
    meta: {
      title: 'Chat'
    }
  },
  {
    path: '/workflow',
    name: 'workflow',
    component: () => import('@/views/WorkflowView.vue'),
    meta: {
      title: 'Workflow'
    }
  },
  {
    path: '/workflow/create',
    name: 'workflow-create',
    component: () => import('@/components/workflow/CreateWorkflowView.vue'),
    meta: {
      title: 'Create Workflow'
    }
  },
  {
    path: '/workflow/:id',
    name: 'workflow-detail',
    component: () => import('@/components/workflow/WorkflowDetailView.vue'),
    meta: {
      title: 'Workflow Detail'
    }
  },
  {
    path: '/workflow/:id/edit',
    name: 'workflow-edit',
    component: () => import('@/components/workflow/EditWorkflowView.vue'),
    meta: {
      title: 'Edit Workflow'
    }
  },
  {
    path: '/workflow/:id/run',
    name: 'workflow-run',
    component: () => import('@/components/workflow/WorkflowExecutionView.vue'),
    meta: {
      title: 'Run Workflow'
    }
  },
  {
    path: '/workflow/:id/versions',
    name: 'workflow-versions',
    component: () => import('@/components/workflow/WorkflowVersionsView.vue'),
    meta: {
      title: 'Workflow Versions'
    }
  },
  {
    path: '/images',
    name: 'images',
    component: () => import('@/views/ImageGenerationView.vue'),
    meta: {
      title: 'Image Generation'
    }
  },
  {
    path: '/images/history',
    name: 'images-history',
    component: () => import('@/views/ImageGenerationHistoryView.vue'),
    meta: {
      title: 'Image Generation History'
    }
  },
  {
    path: '/images/jobs/:jobId',
    name: 'images-job-detail',
    component: () => import('@/views/ImageGenerationView.vue'),
    meta: {
      title: 'Image Generation Job'
    }
  },
  {
    path: '/models',
    name: 'models',
    component: () => import('@/views/ModelsView.vue'),
    meta: {
      title: 'Models'
    }
  },
  {
    path: '/models/llm',
    name: 'models-llm',
    component: () => import('@/views/ModelsView.vue'),
    meta: {
      title: 'Models',
      capability: 'llm'
    }
  },
  {
    path: '/models/vlm',
    name: 'models-vlm',
    component: () => import('@/views/ModelsView.vue'),
    meta: {
      title: 'Models',
      capability: 'vlm'
    }
  },
  {
    path: '/models/asr',
    name: 'models-asr',
    component: () => import('@/views/ModelsView.vue'),
    meta: {
      title: 'Models',
      capability: 'asr'
    }
  },
  {
    path: '/models/perception',
    name: 'models-perception',
    component: () => import('@/views/ModelsView.vue'),
    meta: {
      title: 'Models',
      capability: 'perception'
    }
  },
  {
    path: '/models/perception/object-detection',
    name: 'models-perception-detection',
    component: () => import('@/views/ModelsView.vue'),
    meta: {
      title: 'Models',
      capability: 'perception',
      subtype: 'object-detection'
    }
  },
  {
    path: '/models/perception/segmentation',
    name: 'models-perception-segmentation',
    component: () => import('@/views/ModelsView.vue'),
    meta: {
      title: 'Models',
      capability: 'perception',
      subtype: 'segmentation'
    }
  },
  {
    path: '/models/perception/tracking',
    name: 'models-perception-tracking',
    component: () => import('@/views/ModelsView.vue'),
    meta: {
      title: 'Models',
      capability: 'perception',
      subtype: 'tracking'
    }
  },
  {
    path: '/models/embedding',
    name: 'models-embedding',
    component: () => import('@/views/ModelsView.vue'),
    meta: {
      title: 'Models',
      capability: 'embedding'
    }
  },
  {
    path: '/models/image-generation',
    name: 'models-image-generation',
    component: () => import('@/views/ModelsView.vue'),
    meta: {
      title: 'Models',
      capability: 'image_generation'
    }
  },
  {
    path: '/models/:id/config',
    name: 'model-config',
    component: () => import('@/components/models/ModelConfigView.vue'),
    meta: {
      title: 'Model Config'
    }
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('@/views/KnowledgeView.vue'),
    meta: {
      title: 'Knowledge Base'
    }
  },
  {
    path: '/knowledge/create',
    name: 'knowledge-create',
    component: () => import('@/components/knowledge/CreateKnowledgeBaseView.vue'),
    meta: {
      title: 'Create Knowledge Base'
    }
  },
  {
    path: '/knowledge/:id',
    name: 'knowledge-detail',
    component: () => import('@/components/knowledge/KnowledgeBaseDetailView.vue'),
    meta: {
      title: 'Knowledge Base Detail'
    }
  },
  {
    path: '/agents',
    name: 'agents',
    component: () => import('@/views/AgentsView.vue'),
    meta: {
      title: 'Agents'
    }
  },
  {
    path: '/agents/create',
    name: 'agents-create',
    component: () => import('@/components/agents/CreateAgentView.vue'),
    meta: {
      title: 'Create Agent'
    }
  },
  {
    path: '/agents/:id/run',
    name: 'agents-run',
    component: () => import('@/components/agents/AgentExecutionView.vue'),
    meta: {
      title: 'Agent Execution'
    }
  },
  {
    path: '/agents/:id/trace',
    name: 'agents-trace',
    component: () => import('@/components/agents/AgentExecutionTraceView.vue'),
    meta: {
      title: 'Agent Execution Trace'
    }
  },
  {
    path: '/agents/:id/edit',
    name: 'agents-edit',
    component: () => import('@/components/agents/EditAgentView.vue'),
    meta: {
      title: 'Edit Agent'
    }
  },
  {
    path: '/skills',
    name: 'skills',
    component: () => import('@/views/SkillsView.vue'),
    meta: {
      title: 'Skills'
    }
  },
  {
    path: '/skills/create',
    name: 'skills-create',
    component: () => import('@/components/skills/CreateSkillView.vue'),
    meta: {
      title: 'Create Skill'
    }
  },
  {
    path: '/skills/:id',
    name: 'skill-detail',
    component: () => import('@/components/skills/SkillDetailView.vue'),
    meta: {
      title: 'Skill Detail'
    }
  },
  {
    path: '/logs',
    name: 'logs',
    component: () => import('@/views/LogsView.vue'),
    meta: {
      title: 'Logs'
    }
  },
  {
    path: '/settings',
    name: 'settings',
    redirect: '/settings/general',
    meta: {
      title: 'Settings'
    }
  },
  {
    path: '/settings/general',
    name: 'settings-general',
    component: () => import('@/views/SettingsGeneralView.vue'),
    meta: {
      title: 'General Settings'
    }
  },
  {
    path: '/settings/backend',
    name: 'settings-backend',
    component: () => import('@/views/SettingsBackendView.vue'),
    meta: {
      title: 'Backend Configuration'
    }
  },
  {
    path: '/settings/object-detection',
    name: 'settings-object-detection',
    component: () => import('@/views/SettingsObjectDetectionView.vue'),
    meta: {
      title: 'Object Detection (YOLO)'
    }
  },
  {
    path: '/settings/image-generation',
    name: 'settings-image-generation',
    component: () => import('@/views/SettingsImageGenerationView.vue'),
    meta: {
      title: 'Image Generation'
    }
  },
  {
    path: '/settings/asr',
    name: 'settings-asr',
    component: () => import('@/views/SettingsAsrView.vue'),
    meta: {
      title: 'ASR Configuration'
    }
  },
  {
    path: '/settings/backup',
    name: 'settings-backup',
    component: () => import('@/views/SettingsBackupView.vue'),
    meta: {
      title: 'Database Backup'
    }
  },
  {
    path: '/settings/model-backup',
    name: 'settings-model-backup',
    component: () => import('@/views/SettingsModelBackupView.vue'),
    meta: {
      title: 'Model Config Backup'
    }
  },
  {
    path: '/settings/runtime',
    name: 'settings-runtime',
    component: () => import('@/views/SettingsRuntimeView.vue'),
    meta: {
      title: 'Runtime Configuration'
    }
  },
  {
    path: '/optimization',
    name: 'optimization',
    component: () => import('@/views/OptimizationDashboard.vue'),
    meta: {
      title: 'Optimization Dashboard'
    }
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/chat'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫：确保路由正确导航
router.beforeEach((to, from, next) => {
  // 记录路由变化，便于调试
  console.log('[Router] Navigating from', from.path, 'to', to.path)
  next()
})

router.afterEach((to) => {
  // 路由变化后，更新页面标题
  if (to.meta.title) {
    document.title = `${to.meta.title} - OpenVitamin大模型与智能体应用平台`
  }
})

export default router
