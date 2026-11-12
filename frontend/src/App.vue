<script setup>
import { ref } from 'vue'
import { api, usePoll } from './api.js'

const health = ref(null)
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
      </nav>
      <div class="grow" />
      <span v-if="error" class="badge s-failed">엔진 연결 끊김</span>
      <span v-else-if="health" class="badge" :class="health.live ? 's-done' : 's-queued'">
        서비스 {{ health.live }}/{{ health.total }} 연결
      </span>
    </header>
    <main class="page">
      <router-view />
    </main>
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
@media (max-width: 640px) {
  .top { gap: 8px; padding: 0 10px; }
  nav a { padding: 0 8px; font-size: 13px; }
  .top .badge { display: none; }
}
</style>
