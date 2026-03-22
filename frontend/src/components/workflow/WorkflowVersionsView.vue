<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, GitCompare, RotateCcw, Rocket, Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  diffWorkflowVersions,
  getWorkflow,
  listWorkflowVersions,
  publishWorkflowVersion,
  rollbackWorkflowVersion,
  type WorkflowRecord,
  type WorkflowVersionRecord,
} from '@/services/api'

const route = useRoute()
const router = useRouter()
const workflowId = route.params.id as string

const workflow = ref<WorkflowRecord | null>(null)
const versions = ref<WorkflowVersionRecord[]>([])
const loading = ref(false)
const diffLoading = ref(false)
const rollbackLoading = ref(false)
const publishLoadingId = ref('')

const baseVersionId = ref('')
const targetVersionId = ref('')
const diffResult = ref<any | null>(null)

const canDiff = computed(() => !!baseVersionId.value && !!targetVersionId.value && baseVersionId.value !== targetVersionId.value)

function goBack() {
  router.push({ name: 'workflow-detail', params: { id: workflowId } })
}

async function loadData() {
  loading.value = true
  try {
    const [wf, verRes] = await Promise.all([
      getWorkflow(workflowId),
      listWorkflowVersions(workflowId, { limit: 200, offset: 0 }),
    ])
    workflow.value = wf
    versions.value = verRes.items || []
    if (versions.value.length >= 2) {
      targetVersionId.value = versions.value[0]?.version_id || ''
      baseVersionId.value = versions.value[1]?.version_id || ''
    } else if (versions.value.length === 1) {
      targetVersionId.value = versions.value[0]?.version_id || ''
      baseVersionId.value = versions.value[0]?.version_id || ''
    }
  } finally {
    loading.value = false
  }
}

async function doDiff() {
  if (!canDiff.value) return
  diffLoading.value = true
  try {
    diffResult.value = await diffWorkflowVersions(workflowId, baseVersionId.value, targetVersionId.value)
  } finally {
    diffLoading.value = false
  }
}

async function doPublish(versionId: string) {
  publishLoadingId.value = versionId
  try {
    await publishWorkflowVersion(workflowId, versionId)
    await loadData()
  } finally {
    publishLoadingId.value = ''
  }
}

async function doRollback(versionId: string) {
  const ok = window.confirm('Rollback will create a new version from this version and publish it. Continue?')
  if (!ok) return
  rollbackLoading.value = true
  try {
    await rollbackWorkflowVersion(workflowId, versionId, { publish: true })
    await loadData()
  } finally {
    rollbackLoading.value = false
  }
}

onMounted(() => {
  void loadData()
})
</script>

<template>
  <div class="flex flex-col h-full bg-background">
    <div class="flex items-center gap-4 px-8 py-6 border-b border-border/50">
      <Button variant="ghost" size="icon" @click="goBack">
        <ArrowLeft class="w-5 h-5" />
      </Button>
      <div class="flex-1">
        <h1 class="text-2xl font-bold tracking-tight">Workflow Versions</h1>
        <p class="text-sm text-muted-foreground">{{ workflow?.name || workflowId }}</p>
      </div>
    </div>

    <div class="flex-1 overflow-auto p-8">
      <div v-if="loading" class="text-sm text-muted-foreground flex items-center gap-2">
        <Loader2 class="w-4 h-4 animate-spin" />
        Loading versions...
      </div>

      <div v-else class="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <Card class="xl:col-span-2">
          <CardHeader>
            <CardTitle>Version List</CardTitle>
          </CardHeader>
          <CardContent>
            <div v-if="versions.length === 0" class="text-sm text-muted-foreground">No versions.</div>
            <div v-else class="space-y-3">
              <div v-for="v in versions" :key="v.version_id" class="rounded-lg border border-border/60 p-3">
                <div class="flex items-center justify-between gap-3">
                  <div>
                    <div class="text-sm font-medium">v{{ v.version_number }}</div>
                    <div class="text-xs text-muted-foreground mt-1">{{ v.version_id }}</div>
                  </div>
                  <Badge variant="secondary">{{ v.state }}</Badge>
                </div>
                <div class="text-xs text-muted-foreground mt-2">
                  Created: {{ v.created_at }} · By: {{ v.created_by || '-' }}
                </div>
                <div class="text-xs text-muted-foreground mt-1">
                  Published: {{ v.published_at || '-' }} · By: {{ v.published_by || '-' }}
                </div>
                <div class="text-sm mt-2">{{ v.description || '-' }}</div>
                <div class="flex items-center gap-2 mt-3">
                  <Button variant="outline" size="sm" class="gap-1" :disabled="publishLoadingId === v.version_id" @click="doPublish(v.version_id)">
                    <Rocket class="w-3.5 h-3.5" />
                    Publish
                  </Button>
                  <Button variant="outline" size="sm" class="gap-1" :disabled="rollbackLoading" @click="doRollback(v.version_id)">
                    <RotateCcw class="w-3.5 h-3.5" />
                    Rollback
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Version Diff</CardTitle>
          </CardHeader>
          <CardContent class="space-y-3">
            <div class="space-y-1">
              <label class="text-xs text-muted-foreground">From</label>
              <select v-model="baseVersionId" class="h-9 w-full rounded border border-input bg-background px-2 text-sm">
                <option value="">Select version</option>
                <option v-for="v in versions" :key="`from-${v.version_id}`" :value="v.version_id">v{{ v.version_number }}</option>
              </select>
            </div>
            <div class="space-y-1">
              <label class="text-xs text-muted-foreground">To</label>
              <select v-model="targetVersionId" class="h-9 w-full rounded border border-input bg-background px-2 text-sm">
                <option value="">Select version</option>
                <option v-for="v in versions" :key="`to-${v.version_id}`" :value="v.version_id">v{{ v.version_number }}</option>
              </select>
            </div>
            <Button class="w-full gap-2" :disabled="!canDiff || diffLoading" @click="doDiff">
              <GitCompare class="w-4 h-4" />
              Compare
            </Button>
            <div v-if="diffResult" class="text-xs space-y-2 rounded border border-border/60 bg-muted/20 p-3">
              <div>Nodes: +{{ diffResult.summary.node_added }} / -{{ diffResult.summary.node_removed }} / ~{{ diffResult.summary.node_changed }}</div>
              <div>Edges: +{{ diffResult.summary.edge_added }} / -{{ diffResult.summary.edge_removed }}</div>
              <div class="pt-2 border-t border-border/40">
                <div class="font-medium mb-1">Changed Nodes</div>
                <div class="max-h-28 overflow-auto">{{ (diffResult.nodes.changed || []).join(', ') || '-' }}</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  </div>
</template>
