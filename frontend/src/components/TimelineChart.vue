<script setup>
import { computed } from 'vue'
import { time } from '../format.js'

const props = defineProps({ buckets: { type: Array, required: true }, height: { type: Number, default: 110 } })
const W = 600
const max = computed(() => Math.max(1, ...props.buckets.map((b) => b.done + b.failed)))
const bw = computed(() => W / Math.max(1, props.buckets.length))
function h(v) {
  return (v / max.value) * (props.height - 22)
}
</script>

<template>
  <svg class="chart" :viewBox="`0 0 ${W} ${height}`" preserveAspectRatio="none" role="img" aria-label="시간대별 처리량">
    <line x1="0" :x2="W" :y1="height - 18" :y2="height - 18" class="axis" />
    <g v-for="(b, i) in buckets" :key="i">
      <title>{{ time(b.t) }} · 완료 {{ b.done }} · 실패 {{ b.failed }}</title>
      <rect :x="i * bw + 1.5" :width="bw - 3" :y="height - 18 - h(b.done)" :height="h(b.done)" rx="2" class="done" />
      <rect :x="i * bw + 1.5" :width="bw - 3" :y="height - 18 - h(b.done) - h(b.failed)" :height="h(b.failed)" rx="2" class="failed" />
    </g>
    <text x="0" :y="height - 4" class="tick">{{ time(buckets[0]?.t) }}</text>
    <text :x="W" :y="height - 4" text-anchor="end" class="tick">지금</text>
    <text x="2" y="10" class="tick">최대 {{ max }}</text>
  </svg>
</template>

<style scoped>
.chart { width: 100%; height: auto; display: block; }
.axis { stroke: var(--line); }
.done { fill: var(--ok); opacity: 0.85; }
.failed { fill: var(--fail); }
.tick { fill: var(--faint); font-size: 10px; }
</style>
