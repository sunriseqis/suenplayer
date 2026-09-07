import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // hls.js chunk 已在播放器内动态 import、仅起播时加载，不构成首屏负担，故提高体积警告线
  build: { chunkSizeWarningLimit: 600 },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true
      }
    }
  }
})
