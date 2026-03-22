import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

export type ViewType = 'chat' | 'workflow' | 'images' | 'models' | 'knowledge' | 'agents' | 'skills' | 'logs' | 'settings'

// 路由名称到 ViewType 的映射
const routeNameToViewType: Record<string, ViewType> = {
  'chat': 'chat',
  'workflow': 'workflow',
  'workflow-create': 'workflow',
  'workflow-detail': 'workflow',
  'workflow-edit': 'workflow',
  'workflow-run': 'workflow',
  'workflow-versions': 'workflow',
  'images': 'images',
  'images-history': 'images',
  'images-job-detail': 'images',
  'models': 'models',
  'models-llm': 'models',
  'models-vlm': 'models',
  'models-asr': 'models',
  'models-perception': 'models',
  'models-perception-detection': 'models',
  'models-perception-segmentation': 'models',
  'models-perception-tracking': 'models',
  'models-embedding': 'models',
  'models-image-generation': 'models',
  'model-config': 'models',
  'knowledge': 'knowledge',
  'knowledge-create': 'knowledge',  // 创建知识库页面也属于 knowledge 视图
  'knowledge-detail': 'knowledge',  // 知识库详情页面也属于 knowledge 视图
  'agents': 'agents',
  'agents-create': 'agents',
  'agents-run': 'agents',
  'agents-trace': 'agents',   // 智能体执行追踪页面也属于 agents 视图
  'agents-edit': 'agents',
  'skills': 'skills',
  'skills-create': 'skills',
  'skill-detail': 'skills',   // 技能详情页面也属于 skills 视图
  'logs': 'logs',
  'settings': 'settings',
  'settings-general': 'settings',
  'settings-backup': 'settings',
  'settings-model-backup': 'settings',
  'settings-backend': 'settings',
  'settings-object-detection': 'settings',
  'settings-asr': 'settings',
  'settings-runtime': 'settings',
  'settings-image-generation': 'settings'
}

export function useNavigation() {
  const router = useRouter()
  const route = useRoute()

  // 从路由名称计算当前视图
  const activeView = computed<ViewType>(() => {
    const routeName = route.name as string
    return routeNameToViewType[routeName] || 'chat'
  })

  function setView(view: ViewType) {
    // 使用路由导航，而不是直接修改状态
    router.push({ name: view })
  }

  return {
    activeView,
    setView
  }
}
