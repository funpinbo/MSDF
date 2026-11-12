export const STATUS = {
  queued: '대기',
  leased: '배정',
  running: '실행 중',
  saved: '저장됨',
  done: '완료',
  failed: '실패',
  cancelled: '취소',
}
export const KIND = { produce: '생산', deliver: '배달', deliver_fail: '실패 통지' }

export function time(t) {
  if (!t) return ''
  const d = new Date(t * 1000)
  const p = (n) => String(n).padStart(2, '0')
  const hms = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  return d.toDateString() === new Date().toDateString() ? hms : `${d.getMonth() + 1}/${d.getDate()} ${hms}`
}

export function ago(t) {
  if (!t) return ''
  const s = Date.now() / 1000 - t
  if (s < 60) return `${Math.max(0, Math.round(s))}초 전`
  if (s < 3600) return `${Math.round(s / 60)}분 전`
  if (s < 86400) return `${Math.round(s / 3600)}시간 전`
  return `${Math.round(s / 86400)}일 전`
}

export function ms(v) {
  if (v == null) return '–'
  if (v < 1000) return `${Math.round(v)}ms`
  if (v < 60000) return `${(v / 1000).toFixed(v < 10000 ? 2 : 1)}s`
  return `${Math.floor(v / 60000)}m ${Math.round((v % 60000) / 1000)}s`
}

export function pct(v) {
  return v == null ? '–' : `${Math.round(v * 100)}%`
}

export function num(v) {
  return (v ?? 0).toLocaleString('ko-KR')
}

export function short(id, n = 8) {
  return id ? String(id).slice(0, n) : ''
}

export function lastLine(text) {
  if (!text) return ''
  const lines = String(text).trim().split('\n').filter(Boolean)
  return lines[lines.length - 1] || ''
}

/** 서비스 이름마다 고정된 색 (팔레트 8색 중 하나) */
const PALETTE = ['--c1', '--c2', '--c3', '--c4', '--c5', '--c6', '--c7', '--c8']
export function serviceColor(name) {
  let h = 0
  for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return `var(${PALETTE[h % PALETTE.length]})`
}
