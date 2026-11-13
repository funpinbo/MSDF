<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, usePoll } from '../api.js'
import { KIND, ago, lastLine, ms, num, pct, serviceColor, short, time } from '../format.js'
import Drawer from '../components/Drawer.vue'
import StatusBadge from '../components/StatusBadge.vue'
import StepDetail from '../components/StepDetail.vue'

const route = useRoute()
const router = useRouter()
const TABS = [
  { id: 'runs', label: '실행' },
  { id: 'steps', label: '단계' },
  { id: 'services', label: '서비스' },
  { id: 'dags', label: 'DAG' },
  { id: 'subscriptions', label: '구독' },
  { id: 'engine', label: '엔진 로그' },
]
const tab = computed(() => route.params.tab || 'runs')

// 필터는 주소(query)에 둔다: 링크로 공유할 수 있다
const f = ref({ order: '', service: '', status: '', q: '' })
watch(
  () => route.query,
  (q) => {
    f.value = { order: q.order || '', service: q.service || '', status: q.status || '', q: q.q || '' }
  },
  { immediate: true },
)
function setFilter(patch) {
  router.replace({ query: Object.fromEntries(Object.entries({ ...f.value, ...patch }).filter(([, v]) => v)) })
}
function go(t, query = {}) {
  router.push({ path: `/logs/${t}`, query })
}

const catalog = ref({ services: [] })
const dags = ref([])
const overview = ref(null)
const runs = ref([])
const steps = ref([])
const events = ref([])
const subs = ref([])
const live = ref(true)
const picked = ref(null)
const eventBox = ref(null)
let lastSeq = 0

const { error, refresh } = usePoll(async () => {
  if (!live.value) return
  const jobs = [api.get('/api/catalog').then((c) => (catalog.value = c))]
  if (!dags.value.length || tab.value === 'dags') jobs.push(api.get('/api/dags').then((d) => (dags.value = d)))
  if (tab.value === 'runs') jobs.push(api.get('/api/runs', { order: f.value.order, requester: f.value.service, status: f.value.status, limit: 200 }).then((r) => (runs.value = r)))
  if (tab.value === 'steps') jobs.push(api.get('/api/steps', { ...f.value, limit: 300 }).then((s) => (steps.value = s)))
  if (tab.value === 'services' || tab.value === 'dags') jobs.push(api.get('/api/overview', { window: 0 }).then((o) => (overview.value = o)))
  if (tab.value === 'engine') jobs.push(loadEvents())
  if (tab.value === 'subscriptions') jobs.push(api.get('/api/subscriptions').then((s) => (subs.value = s)))
  await Promise.all(jobs)
}, 2000)
watch(tab, () => (picked.value = null))
watch([tab, f], () => {
  if (tab.value === 'engine') {
    events.value = []
    lastSeq = 0
  }
  refresh()
}, { deep: true })

async function loadEvents() {
  const more = await api.get('/api/events', { after: lastSeq, limit: 1000 })
  if (!more.length) return
  lastSeq = more[more.length - 1].seq
  const box = eventBox.value
  const stick = !box || box.scrollTop + box.clientHeight >= box.scrollHeight - 30
  events.value = [...events.value, ...more].slice(-3000)
  if (stick) nextTick(() => eventBox.value && (eventBox.value.scrollTop = eventBox.value.scrollHeight))
}
const shownEvents = computed(() => {
  const q = f.value.q.toLowerCase()
  return events.value.filter(
    (e) => (!f.value.status || e.level === f.value.status) && (!q || e.message.toLowerCase().includes(q)) && (!f.value.service || e.message.includes(f.value.service)),
  )
})

const serviceNames = computed(() => catalog.value.services.map((s) => s.name))
const dagNames = computed(() => dags.value.map((d) => d.order))

function actionStats(svc, act) {
  return overview.value?.actions[`${svc}.${act}`] || {}
}
function serviceTotals(s) {
  const t = { done: 0, failed: 0, running: 0, cached: 0 }
  for (const a of s.actions) {
    const st = actionStats(s.name, a.name)
    for (const k of Object.keys(t)) t[k] += st[k] || 0
  }
  return t
}
function dagStats(order) {
  return overview.value?.dags[order] || {}
}
function rate(s) {
  const d = (s.done || 0) + (s.failed || 0)
  return d ? s.done / d : null
}
</script>

<template>
  <div class="logs">
    <div class="tabs">
      <router-link v-for="t in TABS" :key="t.id" :to="{ path: `/logs/${t.id}`, query: $route.query }" :class="{ active: tab === t.id }">{{ t.label }}</router-link>
      <div class="grow" />
      <label class="row muted live"><input v-model="live" type="checkbox" /> 실시간</label>
    </div>

    <div v-if="!['services', 'dags', 'subscriptions'].includes(tab)" class="filters row wrap">
      <select v-if="tab !== 'engine'" :value="f.order" @change="setFilter({ order: $event.target.value })">
        <option value="">모든 DAG</option>
        <option v-for="d in dagNames" :key="d" :value="d">{{ d }}</option>
      </select>
      <select :value="f.service" @change="setFilter({ service: $event.target.value })">
        <option value="">{{ tab === 'runs' ? '모든 요청 서비스' : '모든 서비스' }}</option>
        <option v-for="s in serviceNames" :key="s" :value="s">{{ s }}</option>
      </select>
      <select :value="f.status" @change="setFilter({ status: $event.target.value })">
        <template v-if="tab === 'engine'">
          <option value="">모든 수준</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </template>
        <template v-else>
          <option value="">모든 상태</option>
          <option value="running">진행 중</option>
          <option value="done">완료</option>
          <option value="failed">실패</option>
          <option v-if="tab === 'steps'" value="queued">대기</option>
          <option v-if="tab === 'steps'" value="cancelled">취소</option>
        </template>
      </select>
      <input v-if="tab !== 'runs'" :value="f.q" class="search" placeholder="검색 (run id, Action, 오류 내용)" @change="setFilter({ q: $event.target.value })" />
      <button v-if="Object.values(f).some(Boolean)" class="ghost" @click="setFilter({ order: '', service: '', status: '', q: '' })">필터 지우기</button>
      <div class="grow" />
      <span v-if="error" class="badge s-failed">{{ error }}</span>
    </div>

    <!-- 실행 -->
    <div v-if="tab === 'runs'" class="card table-wrap">
      <table>
        <thead>
          <tr><th>시작</th><th>DAG</th><th>요청 서비스</th><th>상태</th><th class="num">실행</th><th class="num">캐시</th><th class="num">걸린 시간</th><th>params</th><th>run</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in runs" :key="r.run_id" class="clickable" @click="$router.push(`/runs/${r.run_id}`)">
            <td class="faint nowrap">{{ time(r.created_at) }}</td>
            <td><b>{{ r.order_name }}</b></td>
            <td><span class="dot" :style="{ background: serviceColor(r.requester) }" />{{ r.requester }}</td>
            <td><StatusBadge :status="r.status === 'running' ? 'running' : r.status" /><span v-if="r.replans" class="faint"> 재계획 {{ r.replans }}</span><span v-if="r.refresh_no" class="faint" title="source가 바뀌어 다시 계산한 구독 refresh"> refresh #{{ r.refresh_no }}</span></td>
            <td class="num">{{ r.plan?.steps.length ?? '–' }}</td>
            <td class="num cache">{{ r.plan?.cached.length ?? '–' }}</td>
            <td class="num">{{ ms(r.duration_ms) }}</td>
            <td class="mono ellipsis params">{{ JSON.stringify(r.params) }}</td>
            <td class="mono faint">{{ short(r.run_id) }}</td>
          </tr>
          <tr v-if="!runs.length"><td colspan="9" class="empty">실행 기록이 없습니다.</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 구독 -->
    <div v-if="tab === 'subscriptions'" class="card table-wrap">
      <p class="faint sub-note">결과가 기대는 source가 <code>invalidate()</code>되면 다시 계산해 같은 request_id로 다시 배달합니다. 결과가 같으면 보내지 않습니다.</p>
      <table>
        <thead>
          <tr><th>시작</th><th>DAG</th><th>요청 서비스</th><th>상태</th><th class="num">refresh</th><th>마지막 refresh</th><th>만료</th><th>source</th><th>meta</th><th>request</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in subs" :key="s.request_id" class="clickable" @click="$router.push(`/runs/${s.request_id}`)">
            <td class="faint nowrap">{{ time(s.created_at) }}</td>
            <td><b>{{ s.order_name }}</b></td>
            <td><span class="dot" :style="{ background: serviceColor(s.requester) }" />{{ s.requester }}</td>
            <td>
              <StatusBadge :status="s.status" />
              <span v-if="s.status === 'ended'" class="faint"> {{ { expired: '만료', cancelled: '취소', denied: '권한 없음', dag_changed: 'DAG 바뀜', requester_gone: '요청 서비스 없음' }[s.ended_reason] || s.ended_reason }}</span>
              <span v-else-if="s.dirty" class="faint"> 갱신 대기</span>
              <span v-else-if="s.active_run" class="faint"> 갱신 중</span>
            </td>
            <td class="num">{{ s.refresh_count }}</td>
            <td class="faint nowrap">{{ s.last_refresh_at ? ago(s.last_refresh_at) : '–' }}</td>
            <td class="faint nowrap">{{ s.expires_at ? time(s.expires_at) : '없음' }}</td>
            <td class="mono ellipsis params">{{ s.sources.join(', ') }}</td>
            <td class="mono ellipsis params">{{ JSON.stringify(s.meta) }}</td>
            <td class="mono faint">{{ short(s.request_id) }}</td>
          </tr>
          <tr v-if="!subs.length"><td colspan="10" class="empty">구독이 없습니다. <code>order(..., subscribe="30m")</code>로 만듭니다.</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 단계 -->
    <div v-if="tab === 'steps'" class="card table-wrap">
      <table>
        <thead>
          <tr><th>대기열</th><th>DAG / run</th><th>노드</th><th>서비스.Action</th><th>종류</th><th>상태</th><th class="num">시도</th><th class="num">대기</th><th class="num">실행</th><th>오류</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in steps" :key="s.run_id + s.step_no" class="clickable" :class="{ selected: picked && picked.run_id === s.run_id && picked.step_no === s.step_no }" @click="picked = s">
            <td class="faint nowrap">{{ time(s.queued_at) }}</td>
            <td>{{ s.order_name }} <span class="mono faint">{{ short(s.run_id, 6) }}:{{ s.step_no }}</span></td>
            <td>{{ s.node || '–' }}</td>
            <td><span class="dot" :style="{ background: serviceColor(s.service) }" />{{ s.service }}.<b>{{ s.action }}</b></td>
            <td class="faint">{{ KIND[s.kind] }}</td>
            <td><StatusBadge :status="s.status" /></td>
            <td class="num">{{ s.attempts }}</td>
            <td class="num">{{ ms(s.wait_ms) }}</td>
            <td class="num">{{ ms(s.duration_ms) }}</td>
            <td class="err-cell">{{ lastLine(s.error) }}</td>
          </tr>
          <tr v-if="!steps.length"><td colspan="10" class="empty">조건에 맞는 단계가 없습니다.</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 서비스 -->
    <div v-if="tab === 'services'" class="cards">
      <div v-for="s in catalog.services" :key="s.name" class="card card-pad svc-card" :style="{ '--svc': serviceColor(s.name) }">
        <div class="row">
          <span class="dot big" />
          <h2 class="grow">{{ s.name }}</h2>
          <StatusBadge :status="s.instances.length ? 'done' : 'cancelled'" :label="s.instances.length ? `인스턴스 ${s.instances.length}` : '꺼짐'" />
        </div>
        <div class="faint mono ellipsis" :title="s.file">{{ s.file }}</div>
        <div class="mini-stats">
          <span class="ok">✓ {{ num(serviceTotals(s).done) }}</span>
          <span class="fail">✕ {{ num(serviceTotals(s).failed) }}</span>
          <span class="cache">⚡ {{ num(serviceTotals(s).cached) }}</span>
          <span class="run">⟳ {{ num(serviceTotals(s).running) }}</span>
          <span class="faint">성공률 {{ pct(rate(serviceTotals(s))) }}</span>
        </div>
        <h3>Action</h3>
        <table class="inner">
          <tbody>
            <tr v-for="a in s.actions" :key="a.name">
              <td><b>{{ a.name }}</b><div class="faint small">{{ a.inputs.join(', ') || (a.params.length ? 'params: ' + a.params.join(', ') : '–') }} → {{ a.outputs.join(', ') }}</div></td>
              <td class="num ok">{{ num(actionStats(s.name, a.name).done) }}</td>
              <td class="num fail">{{ num(actionStats(s.name, a.name).failed) }}</td>
              <td class="num">{{ ms(actionStats(s.name, a.name).avg_ms) }}</td>
            </tr>
          </tbody>
        </table>
        <h3>인스턴스</h3>
        <div v-if="!s.instances.length" class="faint">떠 있는 인스턴스가 없습니다.</div>
        <div v-for="i in s.instances" :key="i.id" class="row inst">
          <span class="mono">{{ i.address }}</span>
          <span class="faint">심박 {{ i.last_seen_s }}초 전 · 가동 {{ ms(i.up_s * 1000) }}</span>
          <StatusBadge :status="i.busy ? 'running' : 'done'" :label="i.busy ? '실행 중' : '쉬는 중'" />
        </div>
        <div class="row wrap links">
          <span v-if="s.orders.length" class="faint">order: {{ s.orders.join(', ') }}</span>
          <span v-if="s.dags.length" class="faint">쓰이는 DAG: {{ s.dags.join(', ') }}</span>
        </div>
        <div class="row wrap">
          <button class="small" @click="go('steps', { service: s.name })">단계 로그</button>
          <button class="small" @click="go('steps', { service: s.name, status: 'failed' })">실패만</button>
          <button class="small" @click="go('engine', { service: s.name })">엔진 로그</button>
        </div>
      </div>
      <div v-if="!catalog.services.length" class="empty">등록된 서비스가 없습니다.</div>
    </div>

    <!-- DAG -->
    <div v-if="tab === 'dags'" class="cards">
      <div v-for="d in dags" :key="d.order" class="card card-pad dag-card">
        <div class="row">
          <h2 class="grow">{{ d.order }}</h2>
          <router-link :to="`/editor/${d.order}`">편집기에서 열기 →</router-link>
        </div>
        <div class="faint mono ellipsis">{{ d.source }}</div>
        <div class="mini-stats">
          <span>실행 {{ num(dagStats(d.order).runs) }}</span>
          <span class="ok">성공 {{ num(dagStats(d.order).done) }}</span>
          <span class="fail">실패 {{ num(dagStats(d.order).failed) }}</span>
          <span class="cache">전부 캐시 {{ num(dagStats(d.order).cache_hits) }}</span>
          <span class="faint">평균 {{ ms(dagStats(d.order).avg_ms) }} · 마지막 {{ ago(dagStats(d.order).last_run) || '없음' }}</span>
        </div>
        <div class="flow">
          <span v-for="(n, i) in d.nodes" :key="n.name" class="row">
            <span class="chip" :style="{ '--svc': serviceColor(n.service) }">{{ n.name }} <span class="faint">{{ n.service }}.{{ n.action }}</span></span>
            <span v-if="i < d.nodes.length - 1" class="faint">→</span>
          </span>
          <span class="faint">⇒ {{ d.deliveries.map((x) => x.requester).join(', ') }}</span>
        </div>
        <details>
          <summary>YAML</summary>
          <pre>{{ d.yaml }}</pre>
        </details>
        <div class="row wrap">
          <button class="small" @click="go('runs', { order: d.order })">실행 로그</button>
          <button class="small" @click="go('steps', { order: d.order, status: 'failed' })">실패한 단계</button>
        </div>
      </div>
      <div v-if="!dags.length" class="empty">DAG가 없습니다. <router-link to="/editor">편집기에서 만들기</router-link></div>
    </div>

    <!-- 엔진 로그 -->
    <div v-if="tab === 'engine'" ref="eventBox" class="card events mono">
      <div v-for="e in shownEvents" :key="e.seq" class="ev" :class="`lv-${e.level}`">
        <span class="faint">{{ time(e.t) }}</span>
        <span class="lv">{{ e.level }}</span>
        <span class="faint lg">{{ e.logger.replace('msdf.', '') }}</span>
        <span class="msg">{{ e.message }}</span>
      </div>
      <div v-if="!shownEvents.length" class="empty">엔진 로그가 없습니다. 엔진이 시작된 뒤의 로그만 보관합니다.</div>
    </div>

    <Drawer v-if="picked" :title="`단계 ${picked.step_no} · ${picked.service}.${picked.action}`" @close="picked = null">
      <StepDetail :step="picked" />
    </Drawer>
  </div>
</template>

<style scoped>
.logs { padding: 0 18px 24px; display: grid; gap: 12px; align-content: start; }
.sub-note { margin: 10px 12px; }
.tabs { position: sticky; top: 0; background: var(--bg); z-index: 5; padding-top: 6px; }
.live { padding-right: 4px; font-size: 13px; }
.filters select, .filters input { font-size: 13px; }
.search { width: 280px; }
.table-wrap { overflow: auto; max-height: calc(100vh - 190px); }
.nowrap { white-space: nowrap; }
.params { max-width: 220px; }
.err-cell { color: var(--fail); font-size: 12px; max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; background: var(--svc); }
.dot.big { width: 11px; height: 11px; margin: 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 12px; }
.svc-card, .dag-card { display: grid; gap: 8px; align-content: start; border-top: 3px solid var(--svc, var(--accent)); }
.mini-stats { display: flex; flex-wrap: wrap; gap: 12px; font-weight: 600; font-size: 13px; font-variant-numeric: tabular-nums; }
.inner td { padding: 5px 4px; }
.small { font-size: 11px; }
.inst { font-size: 12px; justify-content: space-between; flex-wrap: wrap; }
.links { font-size: 12px; gap: 4px 14px; }
.flow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 13px; }
.chip { border: 1px solid var(--line); border-left: 3px solid var(--svc); border-radius: 6px; padding: 2px 8px; }
details summary { cursor: pointer; color: var(--muted); font-size: 13px; }
details pre { margin-top: 6px; }
.events { max-height: calc(100vh - 190px); overflow: auto; padding: 8px 0; font-size: 12px; }
.ev { display: grid; grid-template-columns: 80px 64px 74px 1fr; gap: 10px; padding: 2px 14px; }
.ev:hover { background: var(--panel-2); }
.lv { font-weight: 650; }
.lv-WARNING .lv, .lv-WARNING .msg { color: var(--run); }
.lv-ERROR .lv, .lv-ERROR .msg { color: var(--fail); }
.msg { word-break: break-word; }
.ok { color: var(--ok); }
.fail { color: var(--fail); }
.cache { color: var(--cache); }
.run { color: var(--run); }
@media (max-width: 720px) {
  .logs { padding: 0 10px 20px; }
  .cards { grid-template-columns: 1fr; }
  .search { width: 100%; }
  .ev { grid-template-columns: 70px 1fr; }
  .ev .lv, .ev .lg { display: none; }
}
</style>
