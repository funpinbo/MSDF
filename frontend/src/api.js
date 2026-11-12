import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'

// --- 엔진 토큰 ---------------------------------------------------------------
// msdf up --token으로 띄운 엔진은 모든 API에 토큰을 요구한다. 브라우저에만 저장한다.
const TOKEN_KEY = 'msdf.token'
function readToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}
export const auth = reactive({ token: readToken(), needed: false, wrong: false })
export function setToken(value) {
  auth.token = value.trim()
  auth.needed = false
  auth.wrong = false
  try {
    localStorage.setItem(TOKEN_KEY, auth.token)
  } catch {
    /* 저장할 수 없는 브라우저면 이번 탭에서만 쓴다 */
  }
  live.restart()
}

async function request(method, path, body) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined })
  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (res.status === 401) {
    auth.wrong = Boolean(auth.token)
    auth.needed = true
    throw new Error('엔진 토큰이 필요합니다')
  }
  if (!res.ok) {
    const detail = data?.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `${res.status}`)
  }
  return data
}

export const api = {
  get: (path, params) => {
    const q = params
      ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null)).toString()
      : ''
    return request('GET', path + q)
  },
  post: (path, body) => request('POST', path, body),
  put: (path, body) => request('PUT', path, body),
  del: (path) => request('DELETE', path),
}

// --- 실시간 신호 (SSE) --------------------------------------------------------
// 엔진은 상태가 바뀔 때만 /api/stream으로 신호를 보낸다. 화면은 신호를 받을 때 다시 읽는다.
// 연결이 끊기면 예전처럼 주기적으로 읽는다.
const listeners = new Set()
let source = null
export const live = reactive({
  connected: false,
  start() {
    if (source || typeof EventSource === 'undefined') return
    const q = auth.token ? `?token=${encodeURIComponent(auth.token)}` : ''
    const es = new EventSource(`/api/stream${q}`)
    es.onopen = () => (live.connected = true)
    es.onmessage = () => listeners.forEach((fn) => fn())
    es.onerror = () => {
      live.connected = false
      // 토큰이 틀리면 EventSource는 상태 코드를 알려 주지 않는다. 일반 요청이 401을 대신 알린다.
      if (auth.needed) {
        es.close()
        source = null
      }
    }
    source = es
  },
  restart() {
    if (source) source.close()
    source = null
    live.connected = false
    live.start()
  },
})

/**
 * 화면 데이터를 불러온다. 엔진이 변경 신호를 보낼 때 다시 읽고(최소 간격 throttle),
 * 신호가 끊긴 동안에는 ms마다 읽는다. 탭이 보이지 않으면 쉰다.
 */
export function usePoll(load, ms = 2000, throttle = 600) {
  const error = ref(null)
  const loading = ref(false)
  const paused = ref(false)
  let timer = null
  let last = 0
  let pending = null
  async function tick() {
    if (paused.value || document.hidden || loading.value) return
    loading.value = true
    last = Date.now()
    try {
      await load()
      error.value = null
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      loading.value = false
    }
  }
  function onSignal() {
    const wait = throttle - (Date.now() - last)
    if (wait <= 0) return tick()
    if (!pending) pending = setTimeout(() => ((pending = null), tick()), wait)
  }
  function onInterval() {
    // 신호가 살아 있으면 가끔만(안전망) 읽는다
    if (!live.connected || Date.now() - last > 15000) tick()
  }
  onMounted(() => {
    live.start()
    listeners.add(onSignal)
    tick()
    timer = setInterval(onInterval, ms)
  })
  onBeforeUnmount(() => {
    listeners.delete(onSignal)
    clearInterval(timer)
    clearTimeout(pending)
  })
  return { error, loading, paused, refresh: tick }
}
