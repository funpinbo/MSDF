<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'

const info = ref(null) // 서버가 준 원본 (경로, 서비스 목록 등)
const layers = ref([])
const rules = ref([])
const check = ref(null) // { ok, errors, yaml }
const saveMsg = ref('')
const loadError = ref('')
const dirty = ref(false)
const saving = ref(false)
let suppress = false // 불러오기로 바뀐 것은 '변경'으로 치지 않는다

const RULE_HELP = {
  order: '이 서비스(와 계층 값)가 order를 낼 수 있다',
  flow: 'from Action의 데이터가 to Action으로 흘러갈 수 있다',
  delete: 'target(service.action.slot) 데이터를 지울 수 있다',
}

function listText(v) {
  return Array.isArray(v) ? v.join(', ') : v ?? ''
}
function parseList(text) {
  return String(text || '')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
}

async function load() {
  try {
    const d = await api.get('/api/iam')
    info.value = d
    layers.value = d.layers.map((l) => ({
      name: l.name,
      kind: l.kind,
      values: (l.kind === 'ordered' ? l.levels : l.members).join(', '),
    }))
    rules.value = d.rules.map((r) => ({
      type: r.type,
      from: r.from || '',
      to: r.to || '',
      target: r.target || '',
      conditions: Object.fromEntries(Object.entries(r.conditions).map(([k, v]) => [k, listText(v)])),
    }))
    suppress = true
    dirty.value = false
    loadError.value = ''
    await validate()
  } catch (e) {
    loadError.value = e.message
  }
}
onMounted(load)

const layerNames = computed(() => ['service', ...layers.value.map((l) => l.name.trim()).filter((n) => n && n !== 'service')])

function body() {
  return {
    layers: layers.value
      .filter((l) => l.name.trim())
      .map((l) => ({
        name: l.name.trim(),
        kind: l.kind,
        levels: l.kind === 'ordered' ? parseList(l.values) : [],
        members: l.kind === 'flat' ? parseList(l.values) : [],
      })),
    rules: rules.value.map((r) => {
      const conditions = {}
      for (const name of layerNames.value) {
        const raw = (r.conditions[name] || '').trim()
        if (!raw) continue
        const items = parseList(raw)
        conditions[name] = items.length > 1 ? items : items[0]
      }
      return {
        type: r.type,
        from: r.type === 'flow' ? r.from.trim() : null,
        to: r.type === 'flow' ? r.to.trim() : null,
        target: r.type === 'delete' ? r.target.trim() : null,
        conditions,
      }
    }),
  }
}

let timer = null
watch(
  [layers, rules],
  () => {
    if (suppress) {
      suppress = false
      return
    }
    dirty.value = true
    saveMsg.value = ''
    clearTimeout(timer)
    timer = setTimeout(validate, 500)
  },
  { deep: true },
)

async function validate() {
  try {
    check.value = await api.post('/api/iam/validate', body())
  } catch (e) {
    check.value = { ok: false, errors: [e.message], yaml: '' }
  }
}

async function save() {
  saving.value = true
  try {
    const out = await api.put('/api/iam', body())
    if (out.ok) {
      saveMsg.value = `저장했습니다: ${out.path}. 새 order부터 바로 적용됩니다.`
      await load()
    } else {
      check.value = { ...check.value, ok: false, errors: out.errors }
      saveMsg.value = '저장하지 않았습니다. 오류를 고치세요.'
    }
  } catch (e) {
    saveMsg.value = e.message
  } finally {
    saving.value = false
  }
}

function addLayer() {
  layers.value.push({ name: '', kind: 'ordered', values: '' })
}
function addRule(type) {
  const conditions = {}
  // flow 규칙은 service가 아닌 모든 계층의 조건이 있어야 한다. 기본은 모두 허용
  if (type === 'flow') for (const n of layerNames.value) if (n !== 'service') conditions[n] = 'any'
  rules.value.push({ type, from: '', to: '', target: '', conditions })
}
function move(i, d) {
  const j = i + d
  if (j < 0 || j >= rules.value.length) return
  const arr = rules.value
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
}

// --- 권한 시험 ---------------------------------------------------------------
const tryForm = ref({ order: '', requester: '', context: {} })
const tryResult = ref(null)
watch(info, (d) => {
  if (!d) return
  if (!tryForm.value.order) tryForm.value.order = d.orders[0] || ''
  if (!tryForm.value.requester) tryForm.value.requester = d.services[0] || ''
})
async function tryOrder() {
  try {
    tryResult.value = await api.post('/api/iam/try', tryForm.value)
  } catch (e) {
    tryResult.value = { ok: false, blocked: [e.message] }
  }
}
</script>

<template>
  <div class="iam-page">
    <div class="row wrap head">
      <div>
        <h2>권한 (IAM)</h2>
        <div class="faint" v-if="info">
          <span class="mono">{{ info.path }}</span>
          <span v-if="!info.exists"> · 파일이 없어 지금은 <b>모든 요청을 허용</b>합니다. 저장하면 기본이 거부로 바뀝니다.</span>
        </div>
      </div>
      <div class="grow" />
      <span v-if="check" class="badge" :class="check.ok ? 's-done' : 's-failed'">{{ check.ok ? '검증 통과' : `오류 ${check.errors.length}개` }}</span>
      <button class="ghost" :disabled="!dirty" @click="load">되돌리기</button>
      <button class="primary" :disabled="saving || !check?.ok" @click="save">저장</button>
    </div>
    <div v-if="loadError" class="error-box">{{ loadError }}</div>
    <div v-if="saveMsg" class="warn-box">{{ saveMsg }}</div>

    <div class="cols">
      <div class="main">
        <section class="card">
          <div class="card-pad sec-head">
            <h3>계층</h3>
            <span class="faint">계정 등급처럼 서비스가 <code>@context</code>로 알려 주는 값. <code>service</code> 계층은 엔진이 채웁니다.</span>
          </div>
          <table>
            <thead><tr><th>이름</th><th>종류</th><th>값 (쉼표로 구분, ordered는 낮은 것부터)</th><th></th></tr></thead>
            <tbody>
              <tr v-if="!layers.some((l) => l.name.trim() === 'service')">
                <td class="mono">service</td><td class="faint">flat</td><td class="faint">등록된 서비스 이름 (자동)</td><td></td>
              </tr>
              <tr v-for="(l, i) in layers" :key="i">
                <td><input v-model="l.name" placeholder="account" /></td>
                <td>
                  <select v-model="l.kind"><option value="ordered">ordered (등급)</option><option value="flat">flat (목록)</option></select>
                </td>
                <td><input v-model="l.values" class="wide" :placeholder="l.kind === 'ordered' ? 'free, pro, admin' : '비우면 아무 값'" /></td>
                <td><button class="ghost small danger" @click="layers.splice(i, 1)">삭제</button></td>
              </tr>
            </tbody>
          </table>
          <div class="card-pad"><button class="small" @click="addLayer">+ 계층</button></div>
        </section>

        <section class="card">
          <div class="card-pad sec-head">
            <h3>규칙</h3>
            <span class="faint">맞는 규칙이 하나라도 있으면 통과합니다. 조건 칸을 비우면 그 계층은 보지 않습니다. <code>any</code>는 모두 허용.</span>
          </div>
          <div class="rules">
            <div v-for="(r, i) in rules" :key="i" class="rule">
              <div class="row wrap">
                <select v-model="r.type" class="type">
                  <option value="order">order</option><option value="flow">flow</option><option value="delete">delete</option>
                </select>
                <template v-if="r.type === 'flow'">
                  <input v-model="r.from" list="iam-actions" placeholder="from: source.load 또는 source.*" />
                  <span class="faint">→</span>
                  <input v-model="r.to" list="iam-actions" placeholder="to: transform.*" />
                </template>
                <input v-else-if="r.type === 'delete'" v-model="r.target" class="wide" placeholder="target: service.action.slot (패턴 가능)" />
                <span v-else class="faint">{{ RULE_HELP.order }}</span>
                <div class="grow" />
                <button class="ghost small" title="위로" @click="move(i, -1)">↑</button>
                <button class="ghost small" title="아래로" @click="move(i, 1)">↓</button>
                <button class="ghost small danger" @click="rules.splice(i, 1)">삭제</button>
              </div>
              <div class="conds">
                <label v-for="name in layerNames" :key="name" class="field">
                  {{ name }}
                  <input v-model="r.conditions[name]" :list="name === 'service' ? 'iam-services' : undefined" :placeholder="name === 'service' ? '서비스 (패턴)' : 'any, >=pro, a,b'" />
                </label>
              </div>
            </div>
            <div v-if="!rules.length" class="empty">규칙이 없습니다. 저장하면 모든 요청이 막힙니다.</div>
          </div>
          <div class="card-pad row wrap">
            <button class="small" @click="addRule('order')">+ order 규칙</button>
            <button class="small" @click="addRule('flow')">+ flow 규칙</button>
            <button class="small" @click="addRule('delete')">+ delete 규칙</button>
          </div>
        </section>
      </div>

      <aside class="side">
        <section v-if="check && check.errors.length" class="card card-pad">
          <h3>오류</h3>
          <ul class="errs"><li v-for="(e, i) in check.errors" :key="i">{{ e }}</li></ul>
        </section>

        <section class="card card-pad">
          <h3>권한 시험</h3>
          <p class="faint">이 서비스가 이 order를 내면 통과하는지, 실행하지 않고 지금 저장된 규칙으로 확인합니다.</p>
          <div class="try">
            <label class="field">order
              <select v-model="tryForm.order"><option v-for="o in info?.orders || []" :key="o">{{ o }}</option></select>
            </label>
            <label class="field">요청 서비스
              <select v-model="tryForm.requester"><option v-for="s in info?.services || []" :key="s">{{ s }}</option></select>
            </label>
            <label v-for="name in layerNames.filter((n) => n !== 'service')" :key="name" class="field">{{ name }}
              <input v-model="tryForm.context[name]" />
            </label>
            <button @click="tryOrder">확인</button>
          </div>
          <div v-if="tryResult" class="try-result">
            <span class="badge" :class="tryResult.ok ? 's-done' : 's-failed'">{{ tryResult.ok ? '허용' : '거부' }}</span>
            <span v-if="tryResult.note" class="faint"> {{ tryResult.note }}</span>
            <ul v-if="tryResult.blocked?.length"><li v-for="b in tryResult.blocked" :key="b" class="mono">{{ b }}</li></ul>
          </div>
          <p v-if="dirty" class="faint">저장하지 않은 변경은 시험에 반영되지 않습니다.</p>
        </section>

        <section class="card card-pad">
          <h3>iam.yaml 미리보기</h3>
          <pre class="yaml">{{ check?.yaml || info?.yaml }}</pre>
        </section>
      </aside>
    </div>

    <datalist id="iam-actions">
      <option v-for="a in info?.actions || []" :key="a" :value="a" />
      <option v-for="s in info?.services || []" :key="'*' + s" :value="`${s}.*`" />
    </datalist>
    <datalist id="iam-services"><option v-for="s in info?.services || []" :key="s" :value="s" /></datalist>
  </div>
</template>

<style scoped>
.iam-page { padding: 16px 18px 28px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; max-width: 1380px; margin: 0 auto; }
.head h2 { margin: 0 0 2px; }
h3 { margin: 0; font-size: 15px; }
.cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 360px); gap: 14px; align-items: start; }
.main, .side { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; min-width: 0; }
.sec-head { display: grid; gap: 4px; border-bottom: 1px solid var(--line-2); }
td input, td select { width: 100%; }
input.wide { flex: 1; min-width: 200px; }
.rules { display: grid; }
.rule { padding: 12px 16px; border-bottom: 1px solid var(--line-2); display: grid; gap: 8px; }
.rule .type { width: 96px; font-weight: 600; }
.rule input { min-width: 160px; }
.conds { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.conds input { width: 100%; }
.errs { margin: 8px 0 0; padding-left: 18px; color: var(--fail); display: grid; gap: 4px; }
.try { display: grid; gap: 8px; margin-top: 8px; }
.try select, .try input { width: 100%; }
.try-result { margin-top: 10px; }
.try-result ul { margin: 8px 0 0; padding-left: 18px; color: var(--fail); }
.yaml { margin: 8px 0 0; padding: 10px; background: var(--panel-2); border-radius: 8px; overflow: auto; max-height: 340px; white-space: pre; }
@media (max-width: 1000px) {
  .cols { grid-template-columns: 1fr; }
}
</style>
