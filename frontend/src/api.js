import { onBeforeUnmount, onMounted, ref } from 'vue'

async function request(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
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

/** 주기적으로 불러온다. 탭이 보이지 않으면 쉰다. */
export function usePoll(load, ms = 2000) {
  const error = ref(null)
  const loading = ref(false)
  const paused = ref(false)
  let timer = null
  async function tick() {
    if (paused.value || document.hidden || loading.value) return
    loading.value = true
    try {
      await load()
      error.value = null
    } catch (e) {
      error.value = e.message || String(e)
    } finally {
      loading.value = false
    }
  }
  onMounted(() => {
    tick()
    timer = setInterval(tick, ms)
  })
  onBeforeUnmount(() => clearInterval(timer))
  return { error, loading, paused, refresh: tick }
}
