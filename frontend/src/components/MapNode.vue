<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { ms, num } from '../format.js'

const props = defineProps({ data: { type: Object, required: true } })
const s = computed(() => props.data.stats || {})
const total = computed(() => (s.value.done || 0) + (s.value.failed || 0))
const rate = computed(() => (total.value ? (s.value.done || 0) / total.value : null))
</script>

<template>
  <div class="mnode" :class="{ running: s.running > 0, failing: s.failed > 0, off: !data.live }" :style="{ '--svc': data.color }">
    <Handle type="target" :position="Position.Left" class="h" />
    <div class="head">
      <span class="svc">{{ data.service }}</span>
      <span v-if="!data.live" class="off-tag">꺼짐</span>
      <span v-else-if="s.running" class="run-tag">실행 {{ s.running }}</span>
    </div>
    <div class="name">{{ data.action }}</div>
    <div class="stats">
      <span class="ok" title="완료">✓ {{ num(s.done) }}</span>
      <span class="fail" title="실패">✕ {{ num(s.failed) }}</span>
      <span class="cache" title="캐시로 건너뜀">⚡ {{ num(s.cached) }}</span>
      <span v-if="s.queued" class="faint" title="대기">⧗ {{ num(s.queued) }}</span>
    </div>
    <div class="bar" :title="rate == null ? '아직 실행 없음' : `성공률 ${Math.round(rate * 100)}%`">
      <div class="bar-ok" :style="{ width: rate == null ? '0%' : `${rate * 100}%` }" />
    </div>
    <div class="foot faint">
      <span>평균 {{ ms(s.avg_ms) }}</span>
      <span v-if="s.retries">재시도 {{ s.retries }}</span>
    </div>
    <Handle type="source" :position="Position.Right" class="h" />
  </div>
</template>

<style scoped>
.mnode {
  width: 200px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-left: 4px solid var(--svc);
  border-radius: 9px;
  padding: 8px 10px 7px;
  box-shadow: var(--shadow);
  font-size: 12px;
}
.mnode.running { border-color: var(--run); border-left-color: var(--svc); animation: pulse 1.6s infinite; }
.mnode.failing .name { color: var(--fail); }
.mnode.off { opacity: 0.6; }
.head { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.svc { color: var(--svc); font-weight: 650; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
.run-tag { color: var(--run); font-weight: 600; font-size: 11px; }
.off-tag { color: var(--faint); font-size: 11px; }
.name { font-size: 14px; font-weight: 650; margin: 1px 0 5px; }
.stats { display: flex; gap: 9px; font-variant-numeric: tabular-nums; font-weight: 600; }
.ok { color: var(--ok); }
.fail { color: var(--fail); }
.cache { color: var(--cache); }
.bar { height: 4px; border-radius: 3px; background: var(--fail-soft); margin: 6px 0 4px; overflow: hidden; }
.bar-ok { height: 100%; background: var(--ok); }
.foot { display: flex; justify-content: space-between; font-size: 11px; }
.h { opacity: 0; }
</style>
