import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
import './style.css'
import App from './App.vue'
import MapPage from './pages/MapPage.vue'
import EditorPage from './pages/EditorPage.vue'
import LogsPage from './pages/LogsPage.vue'
import RunPage from './pages/RunPage.vue'
import IamPage from './pages/IamPage.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'map', component: MapPage, meta: { title: '실시간 맵' } },
    { path: '/editor/:order?', name: 'editor', component: EditorPage, meta: { title: 'DAG 편집기' } },
    { path: '/logs/:tab?', name: 'logs', component: LogsPage, meta: { title: '로그' } },
    { path: '/runs/:id', name: 'run', component: RunPage, meta: { title: '실행 상세' } },
    { path: '/iam', name: 'iam', component: IamPage, meta: { title: '권한' } },
  ],
})
router.afterEach((to) => {
  document.title = `${to.meta.title || 'MSDF'} · MSDF 엔진`
})

createApp(App).use(router).mount('#app')
