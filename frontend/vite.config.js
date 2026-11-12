import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

// 빌드 결과는 파이썬 패키지 안(ms_dataflow/ui/dist)에 둔다. 저장소에는 넣지 않는다.
export default defineConfig({
  base: '/ui/',
  plugins: [vue()],
  build: {
    outDir: fileURLToPath(new URL('../ms_dataflow/ui/dist', import.meta.url)),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
  server: {
    // npm run dev: 엔진(msdf up)이 8787에서 돌고 있어야 한다
    proxy: { '/api': 'http://127.0.0.1:8787' },
  },
})
