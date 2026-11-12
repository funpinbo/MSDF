<script setup>
import { ref } from 'vue'
import { api, auth, live, setToken, usePoll } from './api.js'

const health = ref(null)
const tokenInput = ref('')
function submitToken() {
  if (tokenInput.value.trim()) setToken(tokenInput.value)
  tokenInput.value = ''
}
const { error } = usePoll(async () => {
  const cat = await api.get('/api/catalog')
  const live = cat.services.filter((s) => s.instances.length).length
  health.value = { live, total: cat.services.length }
}, 5000)
</script>

<template>
  <div class="shell">
    <header class="top">
      <router-link to="/" class="brand">
        <span class="logo" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="20" height="20"><circle cx="5" cy="6" r="2.6" /><circle cx="5" cy="18" r="2.6" /><circle cx="19" cy="12" r="2.6" /><path d="M7.4 7.2 16.6 11M7.4 16.8 16.6 13" /></svg>
        </span>
        MSDF
      </router-link>
      <nav>
        <router-link to="/" exact-active-class="active">실시간 맵</router-link>
        <router-link to="/editor" active-class="active">DAG 편집기</router-link>
        <router-link to="/logs" active-class="active" :class="{ active: $route.name === 'run' }">로그</router-link>
        <router-link to="/iam" active-class="active">권한</router-link>
      </nav>
      <div class="grow" />
      <span
        class="live"
        :class="{ on: live.connected }"
        :title="live.connected ? '엔진이 변경을 바로 알려 줍니다' : '실시간 연결이 끊겨 주기적으로 다시 읽습니다'"
      >{{ live.connected ? '실시간' : '폴링' }}</span>
      <span v-if="error" class="badge s-failed">엔진 연결 끊김</span>
      <span v-else-if="health" class="badge" :class="health.live ? 's-done' : 's-queued'">
        서비스 {{ health.live }}/{{ health.total }} 연결
      </span>
    </header>
    <main class="page">
      <router-view />
    </main>
    <div v-if="auth.needed" class="token-backdrop">
      <form class="card card-pad token-box" @submit.prevent="submitToken">
        <h3>엔진 토큰</h3>
        <p class="faint">
          이 엔진은 <code>msdf up --token</code>(또는 <code>MSDF_TOKEN</code>)으로 띄워져 있습니다.
          같은 값을 입력하세요. 이 브라우저에만 저장됩니다.
        </p>
        <p v-if="auth.wrong" class="err">토큰이 맞지 않습니다.</p>
        <input v-model="tokenInput" type="password" autocomplete="current-password" placeholder="토큰" autofocus />
        <button class="btn primary" type="submit">연결</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.shell { display: flex; flex-direction: column; height: 100%; }
.top {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 0 18px;
  height: 52px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.brand { display: flex; align-items: center; gap: 8px; font-weight: 700; color: var(--text); letter-spacing: 0.02em; }
.brand:hover { text-decoration: none; }
.logo svg { fill: var(--accent); stroke: var(--accent); stroke-width: 1.6; }
nav { display: flex; gap: 2px; height: 100%; }
nav a {
  display: flex;
  align-items: center;
  padding: 0 14px;
  color: var(--muted);
  font-weight: 550;
  border-bottom: 2px solid transparent;
}
nav a:hover { color: var(--text); text-decoration: none; }
nav a.active { color: var(--text); border-bottom-color: var(--accent); }
.page { flex: 1; min-height: 0; overflow: auto; }
.live { font-size: 12px; color: var(--faint); display: flex; align-items: center; gap: 6px; }
.live::before { content: ''; width: 7px; height: 7px; border-radius: 50%; background: var(--faint); }
.live.on { color: var(--ok); }
.live.on::before { background: var(--ok); }
.token-backdrop {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35);
  display: flex; align-items: center; justify-content: center; z-index: 50; padding: 16px;
}
.token-box { display: grid; gap: 10px; width: min(420px, 100%); }
.token-box h3, .token-box p { margin: 0; }
.token-box .err { color: var(--fail); }
@media (max-width: 640px) {
  .top { gap: 8px; padding: 0 10px; }
  nav a { padding: 0 8px; font-size: 13px; }
  .top .badge { display: none; }
}
</style>
