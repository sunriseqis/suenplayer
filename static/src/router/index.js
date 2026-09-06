import { createRouter, createWebHistory } from 'vue-router'
import { useAppStore } from '../stores/app.js'

const routes = [
  { path: '/', name: 'home', component: () => import('../views/Home.vue') },
  { path: '/recent', name: 'recent', component: () => import('../views/RecentUpdates.vue') },
  { path: '/project/:id', name: 'project', component: () => import('../views/ProjectView.vue') },
  { path: '/live', name: 'live', component: () => import('../views/LiveView.vue') },
  { path: '/admin', name: 'admin', component: () => import('../views/AdminView.vue') },
  { path: '/video/:bangou', name: 'detail', component: () => import('../views/Detail.vue') },
  { path: '/series/:series_id', name: 'seriesDetail', component: () => import('../views/Detail.vue') },
  { path: '/search', name: 'search', component: () => import('../views/Search.vue') },
  { path: '/settings', name: 'settings', component: () => import('../views/Settings.vue') },
  { path: '/favorites', name: 'favorites', component: () => import('../views/Favorites.vue') },
  { path: '/history', name: 'history', component: () => import('../views/History.vue') },
  { path: '/downloads', name: 'downloads', component: () => import('../views/Downloads.vue') },
  { path: '/login', name: 'login', component: () => import('../views/Login.vue') },
]

const scrollPositions = {}
const MAX_SCROLL_ENTRIES = 50
let skipScroll = false

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (skipScroll) { skipScroll = false; return false }
    if (savedPosition) return savedPosition
    if (from.name) scrollPositions[from.fullPath] = { x: window.scrollX, y: window.scrollY }
    const keys = Object.keys(scrollPositions)
    if (keys.length > MAX_SCROLL_ENTRIES) {
      delete scrollPositions[keys[0]]
    }
    if (scrollPositions[to.fullPath]) return scrollPositions[to.fullPath]
    return { x: 0, y: 0 }
  }
})

export function setSkipScroll() { skipScroll = true }

let authChecked = false
router.beforeEach(async (to, from) => {
  const store = useAppStore()
  const hasToken = !!localStorage.getItem('suen_token')
  if (!authChecked) {
    // 首次导航：完整校验一次（/auth/verify）
    await store.checkAuth()
    authChecked = true
  } else if (hasToken && !store.isLoggedIn) {
    // 每次导航都生效：本地有 token 但登录态已失效（如 401 清理后的中间窗口），
    // 再校验一次，避免 _loggedIn 长期失真导致守卫不再拦截
    await store.checkAuth()
  }
  if (to.name === 'login') {
    if (store.isLoggedIn) {
      return { path: '/' }
    }
    return true
  }
  if (!store.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
})

export default router
