import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { imgUrl } from './stores/app.js'
import './styles/main.css'

// 封面加载失败的兜底：换成一个“无封面”占位 SVG（data URI 不会再次失败），
// 避免页面留下破图图标。dataset.fb 防止占位图自身再次触发 error。
const COVER_FALLBACK =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="300"><rect width="200" height="300" fill="#d6dbe3"/><text x="100" y="150" font-family="sans-serif" font-size="15" fill="#8a93a3" text-anchor="middle" dominant-baseline="middle">无封面</text></svg>`
  )

const app = createApp(App)
app.config.globalProperties.$imgUrl = imgUrl
app.config.globalProperties.$imgFallback = (e) => {
  const el = e.target
  if (!el || el.dataset.fb) { if (el) el.style.visibility = 'hidden'; return }
  el.dataset.fb = '1'
  el.src = COVER_FALLBACK
}
app.use(createPinia())
app.use(router)
app.mount('#app')
