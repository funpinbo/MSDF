<script setup>
import { ref, watch } from 'vue'
import { api } from '../api.js'
import { KIND, ms, short, time } from '../format.js'
import LineageTree from './LineageTree.vue'
import StatusBadge from './StatusBadge.vue'

const props = defineProps({ step: { type: Object, required: true } })
const lineage = ref(null)
const lineageError = ref('')
watch(
  () => props.step,
  () => {
    lineage.value = null
    lineageError.value = ''
  },
)
async function openLineage(id) {
  try {
    lineage.value = await api.get(`/api/artifacts/${id}`)
  } catch (e) {
    lineageError.value = e.message
  }
}
</script>

<template>
  <div class="sd">
    <div class="row wrap">
      <StatusBadge :status="step.status" />
      <span class="badge s-queued">{{ KIND[step.kind] }}</span>
      <b>{{ step.service }}.{{ step.action }}</b>
      <span v-if="step.node" class="faint">노드 {{ step.node }}</span>
    </div>
    <div class="kv">
      <span>실행</span><span><router-link :to="`/runs/${step.run_id}`" class="mono">{{ step.run_id }}</router-link> · 단계 {{ step.step_no }}</span>
      <span v-if="step.order_name">DAG</span><span v-if="step.order_name">{{ step.order_name }} <span class="faint">(요청 {{ step.requester }})</span></span>
      <span>시도</span><span>{{ step.attempts }}회 실패 / 최대 {{ step.max_retries }}회 재시도</span>
      <span>대기열</span><span>{{ time(step.queued_at) }}</span>
      <span>시작</span><span>{{ time(step.started_at) || '–' }} <span class="faint">(대기 {{ ms(step.wait_ms) }})</span></span>
      <span>끝</span><span>{{ time(step.done_at) || '–' }} <span class="faint">(실행 {{ ms(step.duration_ms) }})</span></span>
      <span v-if="step.worker">Worker</span><span v-if="step.worker" class="mono">{{ step.worker }}</span>
      <span v-if="step.version">버전</span><span v-if="step.version" class="mono">{{ step.version }}</span>
      <span v-if="step.fail_status">통지 사유</span><span v-if="step.fail_status">{{ step.fail_status }}</span>
    </div>
    <template v-if="step.error">
      <h3>{{ step.status === 'failed' ? '오류' : '마지막 오류' }}</h3>
      <pre class="err">{{ step.error }}</pre>
    </template>
    <template v-if="Object.keys(step.params || {}).length">
      <h3>params</h3>
      <pre>{{ JSON.stringify(step.params, null, 2) }}</pre>
    </template>
    <template v-if="Object.keys(step.inputs || {}).length">
      <h3>입력</h3>
      <div v-for="(id, slot) in step.inputs" :key="slot" class="row io">
        <span class="faint">{{ slot }}</span><span class="mono">{{ short(id, 16) }}</span>
        <button class="small" @click="openLineage(id)">계보</button>
      </div>
    </template>
    <template v-if="Object.keys(step.outputs || {}).length">
      <h3>출력</h3>
      <div v-for="(o, slot) in step.outputs" :key="slot" class="row io">
        <span class="faint">{{ slot }}</span><span class="mono">{{ short(o.artifact_id, 16) }}</span>
        <button class="small" :disabled="step.status !== 'done'" @click="openLineage(o.artifact_id)">계보</button>
      </div>
    </template>
    <div v-if="lineageError" class="error-box">{{ lineageError }}</div>
    <template v-if="lineage">
      <h3>데이터 계보</h3>
      <LineageTree :node="lineage" />
    </template>
  </div>
</template>

<style scoped>
.sd { display: grid; gap: 10px; }
.kv { display: grid; grid-template-columns: 76px 1fr; gap: 5px 12px; font-size: 13px; }
.kv > span:nth-child(odd) { color: var(--muted); }
.err { color: var(--fail); }
.io { font-size: 13px; }
</style>
