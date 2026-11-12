<script setup>
import { computed, markRaw, ref, shallowRef, watch } from 'vue'
import { VueFlow, MarkerType, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { api, usePoll } from '../api.js'
import { layout } from '../layout.js'
import { ago, lastLine, ms, num, pct, serviceColor, short, time } from '../format.js'
import KpiCard from '../components/KpiCard.vue'
import MapNode from '../components/MapNode.vue'
import ServiceGroup from '../components/ServiceGroup.vue'
import StatusBadge from '../components/StatusBadge.vue'
import TimelineChart from '../components/TimelineChart.vue'

const WINDOWS = [
  { v: 900, label: '15분' },
  { v: 3600, label: '1시간' },
  { v: 86400, label: '24시간' },
  { v: 0, label: '전체' },
]
const windowSec = ref(3600)
const data = shallowRef(null)
const showFailures = ref(true)
const selected = ref(null)
const recent = ref([])
const nodeTypes = { action: markRaw(MapNode), service: markRaw(ServiceGroup) }

const { fitView } = useVueFlow('map')
const { error, refresh } = usePoll(async () => {
  data.value = await api.get('/api/overview', { window: windowSec.value })
  if (selected.value) await loadRecent()
}, 2000)
watch(windowSec, refresh)

// 구조(노드·엣지 목록)가 바뀔 때만 다시 배치한다. 수치만 바뀌면 자리를 유지한다.
const NODE_W = 200
const NODE_H = 104
const structure = computed(() => {
  const d = data.value
  if (!d) return null
  const ids = []
  for (const s of d.services) for (const a of s.actions) ids.push(`${s.name}.${a.name}`)
  for (const e of d.edges) for (const id of [e.from, e.to]) if (!ids.includes(id)) ids.push(id)
  const edgeKeys = d.edges.map((e) => `${e.from}>${e.to}:${e.kind}`)
  return { key: ids.join('|') + '#' + edgeKeys.join('|'), ids }
})
const placed = shallowRef({ key: null, positions: {}, groups: {} })
watch(structure, (st) => {
  if (!st || st.key === placed.value.key) return
  const nodes = st.ids.map((id) => ({ id, width: NODE_W, height: NODE_H, group: id.split('.')[0] }))
  const edges = data.value.edges.filter((e) => e.kind !== 'failure').map((e) => ({ source: e.from, target: e.to }))
  const { positions, groups } = layout(nodes, edges, { nodesep: 28, ranksep: 110 })
  placed.value = { key: st.key, positions, groups }
  setTimeout(() => fitView({ padding: 0.15 }), 50)
})

const services = computed(() => Object.fromEntries((data.value?.services || []).map((s) => [s.name, s])))

const nodes = computed(() => {
  const d = data.value
  if (!d || !structure.value) return []
  const out = []
  for (const [name, box] of Object.entries(placed.value.groups)) {
    out.push({
      id: `group:${name}`,
      type: 'service',
      position: { x: box.x, y: box.y },
      data: { name, color: serviceColor(name), width: box.width, height: box.height, instances: services.value[name]?.instances.length || 0 },
      draggable: false,
      selectable: false,
      focusable: false,
      zIndex: -1,
    })
  }
  for (const id of structure.value.ids) {
    const [svc, act] = [id.split('.')[0], id.split('.').slice(1).join('.')]
    out.push({
      id,
      type: 'action',
      position: placed.value.positions[id] || { x: 0, y: 0 },
      data: {
        service: svc,
        action: act,
        color: serviceColor(svc),
        live: (services.value[svc]?.instances.length || 0) > 0,
        stats: d.actions[id] || {},
      },
      draggable: false,
    })
  }
  return out
})

const edges = computed(() => {
  const d = data.value
  if (!d) return []
  const max = Math.max(1, ...d.edges.map((e) => e.count))
  return d.edges
    .filter((e) => e.kind !== 'failure' || (showFailures.value && e.count > 0))
    .map((e) => {
      const color = e.kind === 'failure' ? 'var(--fail)' : e.kind === 'delivery' ? 'var(--accent)' : e.failed ? 'var(--fail)' : 'var(--faint)'
      const width = 1.5 + (Math.log1p(e.count) / Math.log1p(max)) * 3
      return {
        id: `${e.from}>${e.to}:${e.kind}`,
        source: e.from,
        target: e.to,
        animated: e.running > 0,
        label: e.count ? `${num(e.count)}${e.failed ? ` · 실패 ${e.failed}` : ''}` : '',
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 6,
        style: { stroke: color, strokeWidth: width, strokeDasharray: e.kind === 'data' ? undefined : '6 5' },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
        data: e,
      }
    })
})

const t = computed(() => data.value?.totals || {})
const runRate = computed(() => {
  const done = t.value.runs_done || 0
  const failed = t.value.runs_failed || 0
  return done + failed ? done / (done + failed) : null
})
const liveServices = computed(() => (data.value?.services || []).filter((s) => s.instances.length).length)
const dagRows = computed(() =>
  Object.entries(data.value?.dags || {})
    .map(([order, s]) => ({ order, ...s }))
    .sort((a, b) => (b.last_run || 0) - (a.last_run || 0)),
)

async function loadRecent() {
  const [svc, ...rest] = selected.value.split('.')
  const act = rest.join('.')
  const rows = await api.get('/api/steps', { service: svc, limit: 60 })
  recent.value = rows.filter((r) => r.action === act).slice(0, 12)
}
async function onNodeClick({ node }) {
  if (node.type !== 'action') return
  selected.value = node.id
  await loadRecent()
}
const selectedInfo = computed(() => {
  if (!selected.value || !data.value) return null
  const [svc, ...rest] = selected.value.split('.')
  const act = rest.join('.')
  const spec = services.value[svc]?.actions.find((a) => a.name === act)
  return {
    service: svc,
    action: act,
    spec,
    stats: data.value.actions[selected.value] || {},
    instances: services.value[svc]?.instances || [],
    inEdges: data.value.edges.filter((e) => e.to === selected.value),
    outEdges: data.value.edges.filter((e) => e.from === selected.value),
  }
})
</script>

<template>
  <div class="map-page">
    <div class="bar row wrap">
      <h2>실시간 데이터 흐름</h2>
      <span class="faint">2초마다 갱신</span>
      <div class="grow" />
      <label class="row muted"><input v-model="showFailures" type="checkbox" /> 실패 통지 경로</label>
      <div class="seg">
        <button v-for="w in WINDOWS" :key="w.v" :class="{ on: windowSec === w.v }" @click="windowSec = w.v">{{ w.label }}</button>
      </div>
    </div>
    <div v-if="error" class="error-box">엔진에서 데이터를 받지 못했습니다: {{ error }}</div>

    <div class="kpis">
      <KpiCard label="실행" :value="num(t.runs)" :sub="`진행 중 ${num(t.runs_running)}`" />
      <KpiCard label="실행 성공률" :value="pct(runRate)" :sub="`성공 ${num(t.runs_done)} · 실패 ${num(t.runs_failed)}`" tone="ok" />
      <KpiCard label="실패한 단계" :value="num(t.steps_failed)" :sub="`재시도 ${num(t.retries)}회`" :tone="t.steps_failed ? 'fail' : ''" />
      <KpiCard label="처리한 단계" :value="num(t.steps_done)" :sub="`실행 중 ${num(t.steps_running)} · 대기 ${num(t.steps_queued)}`" tone="run" />
      <KpiCard label="캐시 적중률" :value="pct(t.cache_hit_rate)" :sub="`전부 캐시로 끝난 실행 ${num(t.cache_full_hits)}`" tone="cache" />
      <KpiCard label="서비스" :value="`${liveServices}/${data?.services.length ?? 0}`" sub="연결됨 / 전체" />
    </div>

    <div class="main">
      <div class="canvas card">
        <VueFlow
          id="map"
          :nodes="nodes"
          :edges="edges"
          :node-types="nodeTypes"
          :nodes-connectable="false"
          :elements-selectable="true"
          :min-zoom="0.2"
          :max-zoom="2"
          fit-view-on-init
          @node-click="onNodeClick"
          @pane-click="selected = null"
        >
          <Background :gap="22" pattern-color="var(--line)" />
          <Controls :show-interactive="false" />
          <MiniMap pannable zoomable :node-color="(n) => (n.type === 'service' ? 'transparent' : n.data.color)" />
        </VueFlow>
        <div class="legend">
          <span><i class="ln data" />데이터</span>
          <span><i class="ln deliver" />결과 배달</span>
          <span><i class="ln fail" />실패 통지</span>
          <span class="faint">숫자 = 이동한 데이터 수(캐시 포함), 움직이는 선 = 실행 중</span>
        </div>
        <div v-if="data && !nodes.length" class="empty overlay">등록된 서비스와 DAG가 없습니다. <router-link to="/editor">DAG 편집기</router-link>에서 만들어 보세요.</div>
      </div>

      <aside v-if="selectedInfo" class="side card">
        <div class="row">
          <div class="grow">
            <div class="svc" :style="{ color: serviceColor(selectedInfo.service) }">{{ selectedInfo.service }}</div>
            <h2>{{ selectedInfo.action }}</h2>
          </div>
          <button class="ghost" aria-label="닫기" @click="selected = null">✕</button>
        </div>
        <div class="stat-grid">
          <div><b class="ok">{{ num(selectedInfo.stats.done) }}</b><span>완료</span></div>
          <div><b class="fail">{{ num(selectedInfo.stats.failed) }}</b><span>실패</span></div>
          <div><b class="cache">{{ num(selectedInfo.stats.cached) }}</b><span>캐시</span></div>
          <div><b class="run">{{ num(selectedInfo.stats.running) }}</b><span>실행 중</span></div>
          <div><b>{{ ms(selectedInfo.stats.avg_ms) }}</b><span>평균 시간</span></div>
          <div><b>{{ num(selectedInfo.stats.retries) }}</b><span>재시도</span></div>
        </div>
        <div v-if="selectedInfo.stats.last_error" class="error-box small">최근 오류: {{ selectedInfo.stats.last_error }}</div>
        <template v-if="selectedInfo.spec">
          <h3>선언</h3>
          <div class="kv">
            <span>입력</span><span>{{ selectedInfo.spec.inputs.join(', ') || '–' }}</span>
            <span>출력</span><span>{{ selectedInfo.spec.outputs.join(', ') }}</span>
            <span v-if="selectedInfo.spec.params.length">params</span><span v-if="selectedInfo.spec.params.length">{{ selectedInfo.spec.params.join(', ') }}</span>
            <span>버전</span><span class="mono">{{ selectedInfo.spec.version }}</span>
            <span>코드</span><span class="mono ellipsis" :title="selectedInfo.spec.file">{{ selectedInfo.spec.file.split('/').pop() }}:{{ selectedInfo.spec.line }}</span>
          </div>
        </template>
        <h3>연결</h3>
        <div class="conn">
          <div v-for="e in selectedInfo.inEdges" :key="'i' + e.from + e.kind">← {{ e.from }} <span class="faint">({{ e.orders.join(', ') }})</span></div>
          <div v-for="e in selectedInfo.outEdges" :key="'o' + e.to + e.kind">→ {{ e.to }} <span class="faint">({{ e.kind === 'data' ? e.orders.join(', ') : e.kind === 'delivery' ? '결과 배달' : '실패 통지' }})</span></div>
          <div v-if="!selectedInfo.inEdges.length && !selectedInfo.outEdges.length" class="faint">어느 DAG에도 쓰이지 않습니다.</div>
        </div>
        <h3>인스턴스</h3>
        <div v-if="!selectedInfo.instances.length" class="faint">떠 있는 인스턴스가 없습니다.</div>
        <div v-for="i in selectedInfo.instances" :key="i.id" class="row inst">
          <span class="mono">{{ i.address }}</span>
          <StatusBadge :status="i.busy ? 'running' : 'done'" :label="i.busy ? '실행 중' : '쉬는 중'" />
        </div>
        <h3>최근 단계</h3>
        <table class="mini">
          <tbody>
            <tr v-for="r in recent" :key="r.run_id + r.step_no" class="clickable" @click="$router.push(`/runs/${r.run_id}`)">
              <td class="faint">{{ time(r.queued_at) }}</td>
              <td><StatusBadge :status="r.status" /></td>
              <td class="num">{{ ms(r.duration_ms) }}</td>
            </tr>
          </tbody>
        </table>
        <router-link :to="{ path: '/logs/steps', query: { service: selectedInfo.service } }">이 서비스의 단계 로그 전체 →</router-link>
      </aside>
    </div>

    <div class="bottom">
      <div class="card card-pad">
        <div class="row"><h2>DAG별 실행</h2><div class="grow" /><router-link to="/logs/runs">실행 로그 →</router-link></div>
        <table>
          <thead>
            <tr><th>DAG</th><th class="num">실행</th><th class="num">성공</th><th class="num">실패</th><th class="num">진행</th><th class="num">전부 캐시</th><th class="num">평균 시간</th><th>마지막 실행</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in dagRows" :key="r.order" class="clickable" @click="$router.push({ path: '/logs/runs', query: { order: r.order } })">
              <td><b>{{ r.order }}</b></td>
              <td class="num">{{ num(r.runs) }}</td>
              <td class="num ok">{{ num(r.done) }}</td>
              <td class="num" :class="{ fail: r.failed }">{{ num(r.failed) }}</td>
              <td class="num">{{ num(r.running) }}</td>
              <td class="num cache">{{ num(r.cache_hits) }}</td>
              <td class="num">{{ ms(r.avg_ms) }}</td>
              <td class="faint">{{ ago(r.last_run) }}</td>
            </tr>
            <tr v-if="!dagRows.length"><td colspan="8" class="empty">이 기간에 실행이 없습니다.</td></tr>
          </tbody>
        </table>
      </div>
      <div class="card card-pad">
        <div class="row"><h2>처리량</h2><span class="faint">완료 <i class="sw ok-bg" /> 실패 <i class="sw fail-bg" /></span></div>
        <TimelineChart v-if="data" :buckets="data.timeline" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.map-page { padding: 16px 18px 24px; display: grid; gap: 14px; }
.bar h2 { font-size: 17px; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.seg button { border: 0; border-radius: 0; background: var(--panel); padding: 5px 11px; color: var(--muted); }
.seg button.on { background: var(--accent); color: #fff; }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.main { display: flex; gap: 14px; min-height: 0; }
.canvas { position: relative; flex: 1; height: min(62vh, 640px); min-height: 380px; overflow: hidden; }
.legend {
  position: absolute; left: 12px; top: 10px; display: flex; gap: 14px; flex-wrap: wrap;
  font-size: 12px; color: var(--muted); background: color-mix(in srgb, var(--panel) 88%, transparent);
  padding: 5px 10px; border-radius: 8px; border: 1px solid var(--line-2);
}
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.ln { display: inline-block; width: 22px; height: 0; border-top: 2px solid var(--faint); }
.ln.deliver { border-top: 2px dashed var(--accent); }
.ln.fail { border-top: 2px dashed var(--fail); }
.overlay { position: absolute; inset: 0; display: grid; place-items: center; }
.side { width: 330px; flex-shrink: 0; padding: 14px 16px; display: grid; gap: 10px; align-content: start; max-height: min(62vh, 640px); overflow: auto; }
.side .svc { font-size: 11px; font-weight: 650; text-transform: uppercase; letter-spacing: 0.04em; }
.stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.stat-grid div { background: var(--panel-2); border-radius: 8px; padding: 7px 9px; display: grid; }
.stat-grid b { font-size: 16px; font-variant-numeric: tabular-nums; }
.stat-grid span { font-size: 11px; color: var(--muted); }
.kv { display: grid; grid-template-columns: 60px 1fr; gap: 4px 10px; font-size: 13px; }
.kv > span:nth-child(odd) { color: var(--muted); }
.conn { display: grid; gap: 3px; font-size: 13px; }
.inst { justify-content: space-between; font-size: 12px; }
.mini td { padding: 5px 6px; font-size: 12px; }
.small { font-size: 12px; }
.bottom { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; }
.bottom h2 { margin-bottom: 8px; }
.ok { color: var(--ok); }
.fail { color: var(--fail); }
.cache { color: var(--cache); }
.run { color: var(--run); }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; vertical-align: -1px; margin: 0 8px 0 2px; }
.ok-bg { background: var(--ok); }
.fail-bg { background: var(--fail); }
@media (max-width: 1100px) {
  .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .bottom { grid-template-columns: 1fr; }
  .main { flex-direction: column; }
  .side { width: auto; max-height: none; }
}
@media (max-width: 640px) {
  .map-page { padding: 12px; }
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .canvas { height: 60vh; }
  .bottom table th:nth-child(n + 5), .bottom table td:nth-child(n + 5) { display: none; }
}
</style>
