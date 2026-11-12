<script setup>
import { computed } from 'vue'
import { MarkerType, VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { Handle, Position } from '@vue-flow/core'
import { layout } from '../layout.js'
import { STATUS, ms, serviceColor } from '../format.js'

const props = defineProps({ dag: { type: Object, required: true }, run: { type: Object, required: true }, steps: { type: Array, required: true } })
const emit = defineEmits(['pick'])

const byNode = computed(() => {
  const m = {}
  for (const s of props.steps) if (s.node) m[s.node] = s // 재계획이 있으면 마지막 것
  return m
})
const cached = computed(() => new Set(props.run.plan?.cached || []))
const joined = computed(() => new Set(props.run.plan?.joined || []))
const deliver = computed(() => [...props.steps].reverse().find((s) => s.kind !== 'produce'))

const graph = computed(() => {
  const ns = props.dag.nodes.map((n) => ({ id: n.name, width: 190, height: 74 }))
  ns.push({ id: '@deliver', width: 190, height: 74 })
  const es = props.dag.edges.map((e) => ({ source: e.from, target: e.to }))
  es.push({ source: props.dag.result.node, target: '@deliver' })
  const { positions } = layout(ns, es, { ranksep: 70, nodesep: 24 })
  const nodes = props.dag.nodes.map((n) => {
    const s = byNode.value[n.name]
    const state = s ? s.status : cached.value.has(n.name) ? 'cached' : joined.value.has(n.name) ? 'joined' : 'none'
    return { id: n.name, type: 'run', position: positions[n.name], data: { ...n, state, step: s } }
  })
  const d = deliver.value
  nodes.push({
    id: '@deliver',
    type: 'run',
    position: positions['@deliver'],
    data: { name: d?.kind === 'deliver_fail' ? '실패 통지' : '결과 배달', service: props.run.requester, action: d?.action || '', state: d ? d.status : 'none', step: d },
  })
  const edges = es.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
    style: { stroke: 'var(--faint)', strokeDasharray: e.target === '@deliver' ? '5 4' : undefined },
  }))
  return { nodes, edges }
})
const LABEL = { ...STATUS, cached: '캐시', joined: '합류', none: '실행 안 함' }
</script>

<template>
  <div class="rg">
    <VueFlow :id="`run-${run.run_id}`" :nodes="graph.nodes" :edges="graph.edges" :nodes-draggable="false" :nodes-connectable="false" fit-view-on-init :min-zoom="0.3" @node-click="({ node }) => node.data.step && emit('pick', node.data.step)">
      <template #node-run="{ data }">
        <div class="rnode" :class="`st-${data.state}`" :style="{ '--svc': serviceColor(data.service) }">
          <Handle type="target" :position="Position.Left" class="h" />
          <div class="row"><span class="svc grow">{{ data.service }}</span><span class="badge" :class="`s-${data.state === 'joined' ? 'cached' : data.state === 'none' ? 'queued' : data.state}`">{{ LABEL[data.state] }}</span></div>
          <b>{{ data.name }}</b>
          <div class="faint small">
            <template v-if="data.step">시도 {{ data.step.attempts + (data.step.status === 'done' ? 1 : 0) }} · {{ ms(data.step.duration_ms) }}</template>
            <template v-else-if="data.state === 'cached'">저장된 결과를 씀</template>
            <template v-else-if="data.state === 'joined'">다른 실행이 만드는 중</template>
          </div>
          <Handle type="source" :position="Position.Right" class="h" />
        </div>
      </template>
      <Background :gap="20" pattern-color="var(--line)" />
      <Controls :show-interactive="false" />
    </VueFlow>
  </div>
</template>

<style scoped>
.rg { height: 300px; border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; background: var(--panel); }
.rnode { width: 190px; background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--svc); border-radius: 9px; padding: 7px 10px; font-size: 12px; box-shadow: var(--shadow); cursor: pointer; }
.rnode b { font-size: 14px; }
.svc { color: var(--svc); font-weight: 650; text-transform: uppercase; font-size: 11px; letter-spacing: 0.04em; }
.st-failed { border-color: var(--fail); border-left-color: var(--fail); }
.st-running, .st-leased { border-color: var(--run); animation: pulse 1.6s infinite; }
.st-cached, .st-joined { border-style: dashed; }
.st-none { opacity: 0.55; }
.small { font-size: 11px; margin-top: 2px; }
.h { opacity: 0; }
</style>
