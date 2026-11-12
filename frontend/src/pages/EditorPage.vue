<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { MarkerType, VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { api } from '../api.js'
import { layout } from '../layout.js'
import { serviceColor } from '../format.js'
import EditorNode from '../components/EditorNode.vue'

const route = useRoute()
const router = useRouter()
const { screenToFlowCoordinate, fitView, getViewport } = useVueFlow('editor')

const catalog = ref({ services: [] })
const dags = ref([])
const search = ref('')
const nodes = ref([])
const edges = ref([])
const order = ref('')
const original = ref(null)
const result = ref(null) // {node, slot}
const deliveries = ref([])
const selectedId = ref(null)
const check = ref({ ok: null, errors: [], warnings: [], yaml: '' })
const showYaml = ref(false)
const dirty = ref(false)
const saving = ref(false)
const message = ref('')
let loading = false

// --- 카탈로그 -----------------------------------------------------------------
const specs = computed(() => {
  const m = {}
  for (const s of catalog.value.services) for (const a of s.actions) m[`${s.name}.${a.name}`] = a
  return m
})
const palette = computed(() => {
  const q = search.value.trim().toLowerCase()
  return catalog.value.services
    .map((s) => ({ ...s, actions: s.actions.filter((a) => !q || `${s.name}.${a.name}`.toLowerCase().includes(q)) }))
    .filter((s) => s.actions.length)
})

function nodeData(service, action, options = {}) {
  return {
    service,
    action,
    color: serviceColor(service),
    spec: specs.value[`${service}.${action}`] || null,
    options: { fresh_for: options.fresh_for ?? null, retries: options.retries ?? null, retry_delay: options.retry_delay ?? null },
  }
}

function edgeOf(source, sourceSlot, target, targetSlot) {
  return {
    id: `${source}.${sourceSlot}->${target}.${targetSlot}`,
    source,
    target,
    sourceHandle: `out:${sourceSlot}`,
    targetHandle: `in:${targetSlot}`,
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
    label: `${sourceSlot} → ${targetSlot}`,
    labelBgPadding: [5, 2],
    labelBgBorderRadius: 5,
  }
}

// --- 불러오기 -----------------------------------------------------------------
async function loadLists() {
  ;[catalog.value, dags.value] = await Promise.all([api.get('/api/catalog'), api.get('/api/dags')])
}

function blank() {
  loading = true
  order.value = 'new_dag'
  original.value = null
  nodes.value = []
  edges.value = []
  result.value = null
  deliveries.value = []
  selectedId.value = null
  check.value = { ok: null, errors: [], warnings: [], yaml: '' }
  nextTick(() => {
    loading = false
    dirty.value = false
  })
}

function openDag(d) {
  loading = true
  order.value = d.order
  original.value = d.order
  nodes.value = d.nodes.map((n) => ({
    id: n.name,
    type: 'editor',
    position: n.position ? { x: n.position[0], y: n.position[1] } : null,
    data: nodeData(n.service, n.action, n),
  }))
  edges.value = d.edges.map((e) => edgeOf(e.from, e.from_slot, e.to, e.to_slot))
  result.value = { ...d.result }
  deliveries.value = d.deliveries.map((x) => ({ ...x }))
  if (nodes.value.some((n) => !n.position)) autoLayout(false)
  selectedId.value = null
  nextTick(() => {
    fitView({ padding: 0.2 })
    loading = false
    dirty.value = false
  })
}

async function select(name) {
  if (dirty.value && !confirm('저장하지 않은 변경이 있습니다. 버릴까요?')) return
  dirty.value = false
  router.push(name ? `/editor/${name}` : '/editor')
}

let first = true
watch(
  () => route.params.order,
  async (name) => {
    await loadLists()
    const d = dags.value.find((x) => x.order === name)
    if (d) openDag(d)
    else if (first && !name && dags.value.length) router.replace(`/editor/${dags.value[0].order}`)
    else blank()
    first = false
  },
  { immediate: true },
)

onBeforeRouteLeave(() => !dirty.value || confirm('저장하지 않은 변경이 있습니다. 나갈까요?'))

// --- 편집 ---------------------------------------------------------------------
function uniqueName(base) {
  const taken = new Set(nodes.value.map((n) => n.id))
  if (!taken.has(base)) return base
  for (let i = 2; ; i++) if (!taken.has(`${base}_${i}`)) return `${base}_${i}`
}

function addNode(service, action, position) {
  const id = uniqueName(action)
  if (!position) {
    const vp = getViewport()
    position = { x: (-vp.x + 120) / vp.zoom + nodes.value.length * 30, y: (-vp.y + 80) / vp.zoom + nodes.value.length * 30 }
  }
  nodes.value = [...nodes.value, { id, type: 'editor', position, data: nodeData(service, action) }]
  const spec = specs.value[`${service}.${action}`]
  if (!result.value && spec?.outputs.length) result.value = { node: id, slot: spec.outputs[0] }
  selectedId.value = id
}

function onDragStart(e, service, action) {
  e.dataTransfer.setData('application/msdf-action', JSON.stringify({ service, action }))
  e.dataTransfer.effectAllowed = 'move'
}
function onDrop(e) {
  const raw = e.dataTransfer.getData('application/msdf-action')
  if (!raw) return
  const { service, action } = JSON.parse(raw)
  const p = screenToFlowCoordinate({ x: e.clientX, y: e.clientY })
  addNode(service, action, { x: p.x - 115, y: p.y - 30 })
}

function onConnect(c) {
  if (c.source === c.target) return
  const outSlot = c.sourceHandle?.replace(/^out:/, '')
  const inSlot = c.targetHandle?.replace(/^in:/, '')
  if (!outSlot || !inSlot) return
  // 입력 슬롯 하나에는 엣지 하나: 기존 연결을 바꾼다
  edges.value = [
    ...edges.value.filter((e) => !(e.target === c.target && e.targetHandle === c.targetHandle)),
    edgeOf(c.source, outSlot, c.target, inSlot),
  ]
}
function isValidConnection(c) {
  return c.source !== c.target && c.sourceHandle?.startsWith('out:') && c.targetHandle?.startsWith('in:')
}

function setResult(r) {
  result.value = r
}

const selected = computed(() => nodes.value.find((n) => n.id === selectedId.value) || null)

function renameNode(oldId, raw) {
  const id = raw.trim()
  if (!id || id === oldId) return
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(id)) return alert('노드 이름은 영문, 숫자, _로 지으세요.')
  if (nodes.value.some((n) => n.id === id)) return alert(`'${id}' 노드가 이미 있습니다.`)
  nodes.value = nodes.value.map((n) => (n.id === oldId ? { ...n, id } : n))
  edges.value = edges.value.map((e) => {
    const s = e.source === oldId ? id : e.source
    const t = e.target === oldId ? id : e.target
    return edgeOf(s, e.sourceHandle.slice(4), t, e.targetHandle.slice(3))
  })
  if (result.value?.node === oldId) result.value = { ...result.value, node: id }
  selectedId.value = id
}

function removeNode(id) {
  nodes.value = nodes.value.filter((n) => n.id !== id)
  edges.value = edges.value.filter((e) => e.source !== id && e.target !== id)
  if (result.value?.node === id) result.value = null
  selectedId.value = null
}

function setOption(key, raw) {
  const n = selected.value
  if (!n) return
  let v = raw === '' ? null : raw
  if (v != null && (key === 'retries' || key === 'retry_delay')) v = Number(v)
  n.data.options = { ...n.data.options, [key]: v }
  dirty.value = true
}

function autoLayout(fit = true) {
  const { positions } = layout(
    nodes.value.map((n) => ({ id: n.id, width: 230, height: 70 + 24 * Math.max(n.data.spec?.inputs.length || 0, n.data.spec?.outputs.length || 1) })),
    edges.value.map((e) => ({ source: e.source, target: e.target })),
    { ranksep: 120, nodesep: 40 },
  )
  nodes.value = nodes.value.map((n) => ({ ...n, position: positions[n.id] }))
  if (fit) nextTick(() => fitView({ padding: 0.2 }))
}

// 연결 상태와 오류 표시는 노드를 고치지 않고 그릴 때 계산한다 (Vue Flow와 갱신이 맞물리지 않게)
function connectedOf(id) {
  return edges.value.filter((e) => e.target === id).map((e) => e.targetHandle.slice(3))
}
function hasError(id) {
  return check.value.errors.some((msg) => msg.includes(`'${id}'`))
}

// --- 직렬화, 검증, 저장 -------------------------------------------------------
const payload = computed(() => {
  const ns = {}
  const layoutMap = {}
  for (const n of nodes.value) {
    const o = n.data.options
    ns[n.id] = { service: n.data.service, action: n.data.action }
    if (o.fresh_for) ns[n.id].fresh_for = o.fresh_for
    if (o.retries != null && !Number.isNaN(o.retries)) ns[n.id].retries = o.retries
    if (o.retry_delay != null && !Number.isNaN(o.retry_delay)) ns[n.id].retry_delay = o.retry_delay
    if (n.position) layoutMap[n.id] = [Math.round(n.position.x), Math.round(n.position.y)]
  }
  return {
    order: order.value.trim(),
    nodes: ns,
    edges: edges.value.map((e) => ({ from: `${e.source}.${e.sourceHandle.slice(4)}`, to: `${e.target}.${e.targetHandle.slice(3)}` })),
    result: result.value ? `${result.value.node}.${result.value.slot}` : '',
    deliveries: deliveries.value,
    layout: layoutMap,
  }
})

const localErrors = computed(() => {
  const errs = []
  if (!nodes.value.length) errs.push('노드가 없습니다. 왼쪽 목록에서 Action을 끌어다 놓으세요.')
  if (!result.value) errs.push('결과로 돌려줄 출력 슬롯을 ☆로 고르세요.')
  if (!deliveries.value.length) errs.push('결과를 받을 서비스(deliveries)를 하나 이상 추가하세요.')
  for (const d of deliveries.value) if (!d.requester || !d.on_success || !d.on_fail) errs.push('deliveries의 요청 서비스, on_success, on_fail을 모두 고르세요.')
  return errs
})

let timer = null
watch(
  () => JSON.stringify(payload.value),
  () => {
    if (!loading) dirty.value = true
    clearTimeout(timer)
    timer = setTimeout(validate, 350)
  },
)

async function validate() {
  if (localErrors.value.length) {
    check.value = { ok: false, errors: [], warnings: [], yaml: check.value.yaml }
    return
  }
  try {
    check.value = await api.post('/api/dags/validate', { dag: payload.value, original: original.value })
  } catch (e) {
    check.value = { ok: false, errors: [e.message], warnings: [], yaml: '' }
  }
}

async function save() {
  await validate()
  if (localErrors.value.length || !check.value.ok) {
    message.value = '오류를 고친 뒤 저장할 수 있습니다.'
    return
  }
  saving.value = true
  try {
    const out = await api.put(`/api/dags/${encodeURIComponent(payload.value.order)}`, { dag: payload.value, original: original.value })
    if (!out.ok) {
      check.value = { ...check.value, ok: false, errors: out.errors }
      message.value = '저장하지 못했습니다.'
      return
    }
    original.value = payload.value.order
    dirty.value = false
    message.value = `저장했습니다: ${out.path}`
    await loadLists()
    if (route.params.order !== payload.value.order) router.replace(`/editor/${payload.value.order}`)
  } catch (e) {
    message.value = `저장하지 못했습니다: ${e.message}`
  } finally {
    saving.value = false
  }
}

async function removeDag() {
  if (!original.value || !confirm(`DAG '${original.value}'를 지울까요? 파일도 지워집니다.`)) return
  await api.del(`/api/dags/${encodeURIComponent(original.value)}`)
  dirty.value = false
  await loadLists()
  router.push('/editor/')
  blank()
}

function newDag() {
  if (dirty.value && !confirm('저장하지 않은 변경이 있습니다. 버릴까요?')) return
  dirty.value = false
  if (route.params.order) router.push('/editor')
  else blank()
}

// --- deliveries ---------------------------------------------------------------
const serviceNames = computed(() => catalog.value.services.map((s) => s.name))
function actionsOf(svc, filter = () => true) {
  return (catalog.value.services.find((s) => s.name === svc)?.actions || []).filter(filter)
}
function addDelivery() {
  deliveries.value = [...deliveries.value, { requester: '', on_success: '', on_fail: '' }]
}
function setRequester(d, svc) {
  d.requester = svc
  const ok = actionsOf(svc, (a) => a.inputs.length === 1)[0]
  const fail = actionsOf(svc, (a) => a.inputs.length === 0)[0]
  d.on_success = ok ? `${svc}.${ok.name}` : ''
  d.on_fail = fail ? `${svc}.${fail.name}` : ''
}

const allOutputs = computed(() =>
  nodes.value.flatMap((n) => (n.data.spec?.outputs || []).map((slot) => ({ node: n.id, slot }))),
)
const resultValue = computed({
  get: () => (result.value ? `${result.value.node}.${result.value.slot}` : ''),
  set: (v) => {
    const [node, slot] = v.split('.')
    result.value = v ? { node, slot } : null
  },
})

onMounted(() => window.addEventListener('beforeunload', (e) => dirty.value && e.preventDefault()))
</script>

<template>
  <div class="editor">
    <aside class="left">
      <div class="block">
        <div class="row"><h3 class="grow">DAG</h3><button class="small" @click="newDag">+ 새 DAG</button></div>
        <div class="dag-list">
          <button v-for="d in dags" :key="d.order" class="dag-item" :class="{ on: d.order === original }" @click="select(d.order)">
            <b>{{ d.order }}</b>
            <span class="faint">노드 {{ d.nodes.length }}</span>
          </button>
          <div v-if="!dags.length" class="faint small-pad">아직 DAG가 없습니다.</div>
        </div>
      </div>
      <div class="block grow-block">
        <h3>Action <span class="faint normal">끌어다 놓기 또는 클릭</span></h3>
        <input v-model="search" placeholder="서비스나 Action 검색" />
        <div class="palette">
          <div v-for="s in palette" :key="s.name" class="pgroup">
            <div class="pservice" :style="{ color: serviceColor(s.name) }">
              <span class="dot" :style="{ background: serviceColor(s.name) }" />{{ s.name }}
              <span class="faint">{{ s.instances.length ? `인스턴스 ${s.instances.length}` : '꺼짐' }}</span>
            </div>
            <div
              v-for="a in s.actions"
              :key="a.name"
              class="paction"
              draggable="true"
              :style="{ '--svc': serviceColor(s.name) }"
              :title="`${a.file}:${a.line}`"
              @dragstart="onDragStart($event, s.name, a.name)"
              @click="addNode(s.name, a.name)"
            >
              <b>{{ a.name }}</b>
              <span class="faint io">{{ a.inputs.join(', ') || (a.params.length ? `params: ${a.params.join(', ')}` : '입력 없음') }} → {{ a.outputs.join(', ') }}</span>
            </div>
          </div>
          <div v-if="!palette.length" class="faint small-pad">등록된 Action이 없습니다.</div>
        </div>
      </div>
    </aside>

    <section class="center">
      <div class="toolbar row wrap">
        <label class="row order-field">
          <span class="muted">order</span>
          <input v-model="order" class="order-input" spellcheck="false" />
        </label>
        <span v-if="dirty" class="badge s-running">저장 안 됨</span>
        <span v-else-if="original" class="badge s-done">저장됨</span>
        <span v-if="check.ok === true && !localErrors.length" class="badge s-done">검증 통과</span>
        <span v-else-if="check.errors.length || localErrors.length" class="badge s-failed">오류 {{ check.errors.length + localErrors.length }}</span>
        <div class="grow" />
        <button @click="autoLayout()">자동 정렬</button>
        <button @click="showYaml = !showYaml">{{ showYaml ? 'YAML 닫기' : 'YAML 보기' }}</button>
        <button v-if="original" class="danger" @click="removeDag">삭제</button>
        <button class="primary" :disabled="saving" @click="save">{{ saving ? '저장 중…' : '저장' }}</button>
      </div>
      <div class="canvas" @dragover.prevent @drop="onDrop">
        <VueFlow
          id="editor"
          v-model:nodes="nodes"
          v-model:edges="edges"
          :default-edge-options="{ type: 'default' }"
          :delete-key-code="['Delete', 'Backspace']"
          :is-valid-connection="isValidConnection"
          :snap-to-grid="true"
          :snap-grid="[10, 10]"
          :min-zoom="0.25"
          fit-view-on-init
          @connect="onConnect"
          @node-click="({ node }) => (selectedId = node.id)"
          @pane-click="selectedId = null"
          @node-drag-stop="dirty = true"
        >
          <template #node-editor="p">
            <EditorNode
              :id="p.id"
              :data="p.data"
              :selected="p.selected"
              :connected="connectedOf(p.id)"
              :result="result"
              :has-error="hasError(p.id)"
              @result="setResult"
            />
          </template>
          <Background :gap="20" pattern-color="var(--line)" />
          <Controls />
          <MiniMap pannable zoomable :node-color="(n) => n.data?.color || 'var(--faint)'" />
        </VueFlow>
        <div v-if="!nodes.length" class="hint">왼쪽 목록에서 Action을 끌어다 놓고, 출력 점(●)에서 입력 점으로 끌어 연결하세요.</div>
      </div>
      <div class="checks">
        <div v-if="message" class="row msg"><span class="grow">{{ message }}</span><button class="ghost small" @click="message = ''">✕</button></div>
        <div v-for="(e, i) in [...localErrors, ...check.errors]" :key="'e' + i" class="err">✕ {{ e }}</div>
        <div v-for="(w, i) in check.warnings" :key="'w' + i" class="warn">! {{ w }}</div>
        <div v-if="check.ok && !localErrors.length && !check.warnings.length" class="ok">✓ 검증을 통과했습니다.</div>
        <pre v-if="showYaml">{{ check.yaml || '검증을 통과하면 저장될 YAML이 여기에 보입니다.' }}</pre>
      </div>
    </section>

    <aside class="right">
      <template v-if="selected">
        <div class="row">
          <h2 class="grow">노드</h2>
          <button class="ghost small" @click="selectedId = null">✕</button>
        </div>
        <label class="field">이름
          <input :value="selected.id" spellcheck="false" @change="renameNode(selected.id, $event.target.value)" />
        </label>
        <div class="kv">
          <span>서비스</span><b :style="{ color: selected.data.color }">{{ selected.data.service }}</b>
          <span>Action</span><b>{{ selected.data.action }}</b>
          <template v-if="selected.data.spec">
            <span>입력</span><span>{{ selected.data.spec.inputs.join(', ') || '–' }}</span>
            <span>출력</span><span>{{ selected.data.spec.outputs.join(', ') }}</span>
            <span v-if="selected.data.spec.params.length">params</span><span v-if="selected.data.spec.params.length">{{ selected.data.spec.params.join(', ') }} (order에서 받음)</span>
            <span>코드</span><span class="mono ellipsis" :title="selected.data.spec.file">{{ selected.data.spec.file.split('/').pop() }}:{{ selected.data.spec.line }}</span>
          </template>
        </div>
        <h3>옵션 <span class="faint normal">비우면 코드의 값을 씀</span></h3>
        <label class="field">fresh_for (예: 30m, 1h, 1d)
          <input :value="selected.data.options.fresh_for || ''" :placeholder="selected.data.spec?.fresh_for || '영구 캐시'" @change="setOption('fresh_for', $event.target.value.trim())" />
        </label>
        <label class="field">retries
          <input type="number" min="0" :value="selected.data.options.retries ?? ''" :placeholder="String(selected.data.spec?.retries ?? 0)" @change="setOption('retries', $event.target.value)" />
        </label>
        <label class="field">retry_delay (초)
          <input type="number" min="0" step="0.1" :value="selected.data.options.retry_delay ?? ''" placeholder="0" @change="setOption('retry_delay', $event.target.value)" />
        </label>
        <h3>결과</h3>
        <div class="row wrap">
          <button
            v-for="slot in selected.data.spec?.outputs || []"
            :key="slot"
            class="small"
            :class="{ primary: result?.node === selected.id && result?.slot === slot }"
            @click="setResult({ node: selected.id, slot })"
          >★ {{ slot }}</button>
        </div>
        <button class="danger" @click="removeNode(selected.id)">노드 삭제</button>
      </template>

      <template v-else>
        <h2>DAG 설정</h2>
        <label class="field">order 이름 (서비스가 order()로 부르는 이름)
          <input v-model="order" spellcheck="false" />
        </label>
        <label class="field">결과 슬롯
          <select v-model="resultValue">
            <option value="">고르세요</option>
            <option v-for="o in allOutputs" :key="o.node + o.slot" :value="`${o.node}.${o.slot}`">{{ o.node }}.{{ o.slot }}</option>
          </select>
        </label>
        <div class="row"><h3 class="grow">결과 배달 (deliveries)</h3><button class="small" @click="addDelivery">+ 추가</button></div>
        <div v-for="(d, i) in deliveries" :key="i" class="delivery">
          <label class="field">요청 서비스
            <select :value="d.requester" @change="setRequester(d, $event.target.value)">
              <option value="">고르세요</option>
              <option v-for="s in serviceNames" :key="s" :value="s">{{ s }}</option>
            </select>
          </label>
          <label class="field">on_success (입력 하나)
            <select v-model="d.on_success">
              <option value="">고르세요</option>
              <option v-for="a in actionsOf(d.requester, (a) => a.inputs.length === 1)" :key="a.name" :value="`${d.requester}.${a.name}`">{{ a.name }}</option>
            </select>
          </label>
          <label class="field">on_fail
            <select v-model="d.on_fail">
              <option value="">고르세요</option>
              <option v-for="a in actionsOf(d.requester)" :key="a.name" :value="`${d.requester}.${a.name}`">{{ a.name }}</option>
            </select>
          </label>
          <button class="danger small" @click="deliveries.splice(i, 1)">이 배달 삭제</button>
        </div>
        <div v-if="!deliveries.length" class="faint">결과를 받을 서비스가 없습니다.</div>
        <h3>도움말</h3>
        <ul class="help">
          <li>Action을 끌어다 놓으면 노드가 생깁니다.</li>
          <li>출력 점에서 입력 점으로 끌면 연결됩니다. 입력 하나에는 연결 하나만 됩니다.</li>
          <li>노드나 연결을 고르고 Delete로 지웁니다.</li>
          <li>☆를 누르면 그 출력이 이 DAG의 결과가 됩니다.</li>
          <li>저장하면 dags/ 폴더의 YAML 파일이 바뀌고 엔진에 바로 반영됩니다.</li>
        </ul>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.editor { display: grid; grid-template-columns: 260px 1fr 300px; height: 100%; min-height: 560px; }
.left, .right { background: var(--panel); border-right: 1px solid var(--line); overflow: auto; }
.right { border-right: 0; border-left: 1px solid var(--line); padding: 14px; display: grid; gap: 12px; align-content: start; }
.left { display: flex; flex-direction: column; }
.block { padding: 12px; border-bottom: 1px solid var(--line); display: grid; gap: 8px; }
.grow-block { flex: 1; align-content: start; border-bottom: 0; }
.normal { text-transform: none; letter-spacing: 0; font-weight: 400; }
.dag-list { display: grid; gap: 2px; max-height: 200px; overflow: auto; }
.dag-item { justify-content: space-between; border-color: transparent; background: transparent; width: 100%; }
.dag-item:hover { background: var(--panel-2); }
.dag-item.on { background: var(--accent-soft); border-color: var(--accent); }
.small-pad { padding: 8px 4px; }
.palette { display: grid; gap: 12px; }
.pgroup { display: grid; gap: 4px; }
.pservice { font-size: 12px; font-weight: 650; display: flex; align-items: center; gap: 6px; text-transform: uppercase; letter-spacing: 0.03em; }
.pservice .faint { text-transform: none; font-weight: 400; margin-left: auto; }
.dot { width: 8px; height: 8px; border-radius: 50%; }
.paction {
  border: 1px solid var(--line);
  border-left: 3px solid var(--svc);
  border-radius: 7px;
  padding: 6px 9px;
  cursor: grab;
  background: var(--panel-2);
  display: grid;
}
.paction:hover { border-color: var(--svc); }
.io { font-size: 11px; }
.center { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.toolbar { padding: 8px 12px; background: var(--panel); border-bottom: 1px solid var(--line); }
.order-input { width: 200px; font-weight: 650; }
.canvas { flex: 1; position: relative; min-height: 320px; }
.hint { position: absolute; inset: auto 0 40% 0; text-align: center; color: var(--muted); pointer-events: none; padding: 0 20px; }
.checks { max-height: 34%; overflow: auto; padding: 8px 12px; border-top: 1px solid var(--line); background: var(--panel); display: grid; gap: 4px; font-size: 13px; }
.checks:empty { display: none; }
.err { color: var(--fail); }
.warn { color: var(--run); }
.ok { color: var(--ok); }
.msg { color: var(--accent); }
.kv { display: grid; grid-template-columns: 64px 1fr; gap: 4px 10px; font-size: 13px; }
.kv > span:nth-child(odd) { color: var(--muted); }
.delivery { display: grid; gap: 6px; padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel-2); }
.help { margin: 0; padding-left: 18px; color: var(--muted); font-size: 12px; display: grid; gap: 3px; }
@media (max-width: 1100px) {
  .editor { grid-template-columns: 220px 1fr; }
  .right { grid-column: 1 / -1; border-left: 0; border-top: 1px solid var(--line); }
}
@media (max-width: 720px) {
  .editor { grid-template-columns: 1fr; height: auto; }
  .left { max-height: 260px; }
  .canvas { height: 60vh; }
}
</style>
