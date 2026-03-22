<script setup lang="ts">
import { onMounted, inject } from 'vue'
import { useVueFlow } from '@vue-flow/core'

const setScreenToFlowCoordinate = inject<(fn: (pos: { x: number; y: number }) => { x: number; y: number }) => void>(
  'workflowCanvasSetScreenToFlowCoordinate',
  () => {}
)

const { screenToFlowCoordinate } = useVueFlow()

onMounted(() => {
  setScreenToFlowCoordinate(screenToFlowCoordinate)
})
</script>

<template>
  <div style="position: absolute; pointer-events: none; width: 0; height: 0; overflow: hidden" aria-hidden="true" />
</template>
