<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, usePoll } from '../api.js'
import { KIND, lastLine, ms, time } from '../format.js'
import Drawer from '../components/Drawer.vue'
import LineageTree from '../components/LineageTree.vue'
import RunGraph from '../components/RunGraph.vue'
import StatusBadge from '../components/StatusBadge.vue'
import StepDetail from '../components/StepDetail.vue'

const route = useRoute()
const data = ref(null)
const picked = ref(null)
const lineage = ref(null)
const { error } = usePoll(async () => {
  data.value = await api.get(`/api/runs/${route.params.id}`)
  const r = data.value.run
  if (r.status === 'done' && r.result_artifact && !lineage.value) {
    lineage.value = await api.get(`/api/artifacts/${r.result_artifact}`).catch(() => null)
  }
}, 1500)

const cancelling = ref(false)
const cancelMsg = ref('')
async function cancelRun() {
  if (!confirm('이 실행을 취소할까요? 요청한 서비스에는 실패 배달(status="cancelled")이 갑니다.')) return
  cancelling.value = true
  try {
    const out = await api.post(`/api/runs/${route.params.id}/cancel`)
    cancelMsg.value = out.ok
      ? `단계 ${out.cancelled}개를 멈췄습니다` + (out.kept ? ` (다른 요청과 공유하는 단계 ${out.kept}개는 계속 실행)` : '')
      : `이미 ${out.status} 상태입니다`
  } catch (e) {
    cancelMsg.value = e.message
  } finally {
    cancelling.value = false
  }
}

const failed = computed(() => data.value?.steps.find((s) => s.status === 'failed'))
const span = computed(() => {
  const st = data.value?.steps || []
  const t0 = Math.min(...st.map((s) => s.queued_at || Infinity), data.value?.run.created_at || Infinity)
  const t1 = Math.max(...st.map((s) => s.done_at || s.started_at || s.queued_at || 0), t0 + 0.001)
  return { t0, t1, len: t1 - t0 }
})
function bar(s) {
  const { t0, len } = span.value
  const a = s.started_at || s.queued_at || t0
  const w = s.queued_at || a
  const b = s.done_at || (s.status === 'running' ? Date.now() / 1000 : a)
  return {
    wait: { left: `${((w - t0) / len) * 100}%`, width: `${Math.max(((a - w) / len) * 100, 0)}%` },
    run: { left: `${((a - t0) / len) * 100}%`, width: `${Math.max(((b - a) / len) * 100, 0.6)}%` },
  }
}
</script>

<template>
  <div class="run-page">
    <div class="row wrap">
      <router-link to="/logs/runs">← 실행 로그</router-link>
    </div>
    <div v-if="error" class="error-box">{{ error }}</div>
    <template v-if="data">
      <div class="card card-pad head">
        <div class="row wrap">
          <h2>{{ data.run.order_name }}</h2>
          <StatusBadge :status="data.run.status === 'running' ? 'running' : data.run.status" />
          <span class="mono faint">{{ data.run.run_id }}</span>
          <div class="grow" />
          <span v-if="cancelMsg" class="faint">{{ cancelMsg }}</span>
          <button v-if="data.run.status === 'running'" class="danger" :disabled="cancelling" @click="cancelRun">실행 취소</button>
        </div>
        <div class="meta">
          <span><span class="faint">요청</span> {{ data.run.requester }}</span>
          <span><span class="faint">시작</span> {{ time(data.run.created_at) }}</span>
          <span><span class="faint">걸린 시간</span> {{ ms(data.run.duration_ms) }}</span>
          <span><span class="faint">params</span> <code>{{ JSON.stringify(data.run.params) }}</code></span>
          <span v-if="Object.keys(data.run.context).length"><span class="faint">context</span> <code>{{ JSON.stringify(data.run.context) }}</code></span>
          <span v-if="data.run.plan"><span class="faint">계획</span> 실행 {{ data.run.plan.steps.length }} · 캐시 {{ data.run.plan.cached.length }} · 합류 {{ data.run.plan.joined.length }}</span>
          <span v-if="data.run.replans"><span class="faint">재계획</span> {{ data.run.replans }}회</span>
        </div>
      </div>

      <div v-if="failed" class="card card-pad fail-card">
        <h3>실패 위치</h3>
        <div class="row wrap"><b>{{ failed.service }}.{{ failed.action }}</b><span class="faint">노드 {{ failed.node }} · 단계 {{ failed.step_no }} · {{ failed.attempts }}번 시도</span></div>
        <pre>{{ failed.error }}</pre>
      </div>

      <RunGraph v-if="data.dag" :dag="data.dag" :run="data.run" :steps="data.steps" @pick="picked = $event" />
      <div v-else class="warn-box">이 실행의 DAG '{{ data.run.order_name }}'가 지금은 없습니다 (삭제되었거나 이름이 바뀜).</div>

      <div class="card">
        <table>
          <thead>
            <tr><th>#</th><th>종류</th><th>노드 / Action</th><th>상태</th><th class="num">시도</th><th class="num">대기</th><th class="num">실행</th><th class="tl">타임라인</th></tr>
          </thead>
          <tbody>
            <tr v-for="s in data.steps" :key="s.step_no" class="clickable" @click="picked = s">
              <td>{{ s.step_no }}</td>
              <td>{{ KIND[s.kind] }}</td>
              <td><b>{{ s.node || '–' }}</b> <span class="faint">{{ s.service }}.{{ s.action }}</span>
                <div v-if="s.error" class="faint err-line">{{ lastLine(s.error) }}</div></td>
              <td><StatusBadge :status="s.status" /></td>
              <td class="num">{{ s.attempts }}</td>
              <td class="num">{{ ms(s.wait_ms) }}</td>
              <td class="num">{{ ms(s.duration_ms) }}</td>
              <td class="tl"><div class="track"><div class="w" :style="bar(s).wait" /><div class="r" :class="`b-${s.status}`" :style="bar(s).run" /></div></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="lineage" class="card card-pad">
        <h3>결과 데이터의 계보</h3>
        <LineageTree :node="lineage" />
      </div>
    </template>

    <Drawer v-if="picked" :title="`단계 ${picked.step_no}`" @close="picked = null">
      <StepDetail :step="{ ...picked, order_name: data?.run.order_name, requester: data?.run.requester }" />
    </Drawer>
  </div>
</template>

<style scoped>
.run-page { padding: 16px 18px 28px; display: grid; gap: 14px; max-width: 1280px; margin: 0 auto; }
.head { display: grid; gap: 8px; }
.meta { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; }
.fail-card { border-color: var(--fail); display: grid; gap: 8px; }
.fail-card pre { color: var(--fail); }
.err-line { font-size: 12px; color: var(--fail); max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tl { width: 28%; min-width: 140px; }
.track { position: relative; height: 10px; background: var(--panel-2); border-radius: 5px; margin-top: 4px; }
.track .w, .track .r { position: absolute; top: 0; bottom: 0; border-radius: 5px; }
.track .w { background: var(--line); }
.r { background: var(--accent); }
.b-done { background: var(--ok); }
.b-failed { background: var(--fail); }
.b-cancelled { background: var(--cancel); }
.b-running { background: var(--run); }
@media (max-width: 720px) {
  .tl, th:nth-child(6), td:nth-child(6), th:nth-child(2), td:nth-child(2) { display: none; }
}
</style>
