<template>
  <nav class="nav">
    <router-link to="/" class="nav-logo">{{ store.siteName }}</router-link>
    <div class="nav-links">
      <router-link to="/" exact-active-class="active">首页</router-link>
      <router-link to="/recent" active-class="active">最近更新</router-link>
      <router-link v-for="p in store.activeProjects" :key="p.id" :to="`/project/${p.id}`" active-class="active">{{ p.name }}</router-link>
      <router-link v-if="store.hasLive" to="/live" active-class="active">直播</router-link>
      <router-link to="/downloads" active-class="active">下载任务</router-link>
      <router-link to="/settings" active-class="active">项目设置</router-link>
    </div>
    <div class="nav-right">
      <span v-if="store.currentUser" class="nav-user" :title="store.currentUser.username">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/></svg>
        {{ store.currentUser.display_name || store.currentUser.username }}
      </span>
      <button class="icon-btn icon-btn-menu" @click="menuOpen = !menuOpen" title="菜单">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
      <button class="icon-btn" @click="showSearch = true" title="搜索">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M16 16L20 20"/></svg>
      </button>
      <router-link class="icon-btn" to="/favorites" title="收藏">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21.2l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z"/></svg>
      </router-link>
      <router-link class="icon-btn" to="/history" title="观看历史">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>
      </router-link>
      <button class="icon-btn" @click="toggleTheme" :title="themeMode === 'dark' ? '跟随系统 / 亮色' : themeMode === 'light' ? '暗色 / 跟随系统' : '亮色 / 暗色'">
        <svg v-if="themeMode === 'light'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
        <svg v-else-if="themeMode === 'dark'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
        <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
      </button>
      <button class="icon-btn" @click="authAction" :title="store.isLoggedIn ? '退出登录' : '登录'">
        <svg v-if="store.isLoggedIn" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
      </button>
    </div>

    <!-- 移动端抽屉菜单 -->
    <Teleport to="body">
      <div v-if="menuOpen" class="drawer-overlay" @click="menuOpen = false">
        <div class="drawer" @click.stop>
          <div class="drawer-header">
            <span class="nav-logo" style="font-size:20px">{{ store.siteName }}</span>
            <button class="icon-btn" @click="menuOpen = false" title="关闭">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
            </button>
          </div>
          <div class="drawer-user" v-if="store.currentUser">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/></svg>
            {{ store.currentUser.display_name || store.currentUser.username }}
          </div>
          <div class="drawer-links">
            <router-link to="/" @click="menuOpen = false" exact-active-class="active">首页</router-link>
            <router-link to="/recent" @click="menuOpen = false" active-class="active">最近更新</router-link>
            <router-link v-for="p in store.activeProjects" :key="p.id" :to="`/project/${p.id}`" @click="menuOpen = false" active-class="active">{{ p.name }}</router-link>
            <router-link v-if="store.hasLive" to="/live" @click="menuOpen = false" active-class="active">直播</router-link>
            <router-link to="/favorites" @click="menuOpen = false" active-class="active">收藏</router-link>
            <router-link to="/history" @click="menuOpen = false" active-class="active">观看历史</router-link>
            <router-link to="/downloads" @click="menuOpen = false" active-class="active">下载任务</router-link>
            <router-link to="/settings" @click="menuOpen = false" active-class="active">项目设置</router-link>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 浮动搜索弹窗 -->
    <Teleport to="body">
      <div v-if="showSearch" class="search-overlay" @click.self="closeSearch">
        <div class="search-popup" @click.stop>
          <div class="search-bar-row">
            <div class="search-popup-input">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M16 16L20 20"/></svg>
              <input ref="searchInput" v-model="query" placeholder="搜索影片番号、标题..." @keyup.enter="doSearch" />
              <button v-if="query" class="search-clear" @click="query = ''" title="清空">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
              </button>
            </div>
            <button class="search-submit" @click="doSearch">搜索</button>
          </div>
          <div class="search-filters">
            <div class="filter-section" v-if="allTags.length">
              <span class="filter-label">标签</span>
              <div class="filter-chips">
                <button v-for="t in allTags" :key="t"
                        class="chip" :class="{ active: activeTags.includes(t), disabled: activeTags.length + activeSites.length > 0 && !activeTags.includes(t) && !availableTags.includes(t) }"
                        :disabled="activeTags.length + activeSites.length > 0 && !activeTags.includes(t) && !availableTags.includes(t)"
                        @click="toggleTag(t)">{{ t }}</button>
              </div>
            </div>
            <div class="filter-section" v-if="allSites.length">
              <span class="filter-label">站点</span>
              <div class="filter-chips">
                <button v-for="s in allSites" :key="s"
                        class="chip" :class="{ active: activeSites.includes(s), disabled: activeTags.length + activeSites.length > 0 && !activeSites.includes(s) && !availableSites.includes(s) }"
                        :disabled="activeTags.length + activeSites.length > 0 && !activeSites.includes(s) && !availableSites.includes(s)"
                        @click="toggleSite(s)">{{ s }}</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </nav>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app.js'
import { useUiStore } from '../stores/ui.js'

const router = useRouter()
const store = useAppStore()
const ui = useUiStore()
const themeMode = ref('auto')
const showSearch = ref(false)
const menuOpen = ref(false)
const query = ref('')
const searchInput = ref(null)
const allTags = ref([])
const allSites = ref([])
const availableTags = ref([])
const availableSites = ref([])
const activeTags = ref([])
const activeSites = ref([])
let abortController = null

const THEME_NAMES = { light: '亮色主题', dark: '暗色主题', auto: '跟随系统' }

onMounted(() => {
  const saved = window.__THEME__ ? window.__THEME__.get() : 'auto'
  themeMode.value = saved
})

function toggleTheme() {
  const next = window.__THEME__.toggle()
  themeMode.value = next
  // D3: 主题切换提示条
  ui.themeChanged(THEME_NAMES[next] || next)
}

async function closeSearch() {
  showSearch.value = false
  query.value = ''
  activeTags.value = []
  activeSites.value = []
}

function doSearch() {
  const q = query.value.trim()
  if (!q && !activeTags.value.length && !activeSites.value.length) return
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  if (activeTags.value.length) params.set('tags', activeTags.value.join(','))
  if (activeSites.value.length) params.set('site', activeSites.value.join(','))
  const href = params.toString() ? `/search?${params.toString()}` : '/search'
  router.push(href)
  closeSearch()
}

function toggleTag(t) {
  const idx = activeTags.value.indexOf(t)
  if (idx >= 0) activeTags.value.splice(idx, 1)
  else activeTags.value.push(t)
  fetchFilters()
}

function toggleSite(s) {
  const idx = activeSites.value.indexOf(s)
  if (idx >= 0) activeSites.value.splice(idx, 1)
  else activeSites.value.push(s)
  fetchFilters()
}

async function fetchFilters() {
  abortController?.abort()
  abortController = new AbortController()
  try {
    const params = new URLSearchParams()
    if (activeTags.value.length) params.set('tags', activeTags.value.join(','))
    if (activeSites.value.length) params.set('site', activeSites.value.join(','))
    const qs = params.toString()
    const url = '/api/filters' + (qs ? '?' + qs : '')
    const [allRes, availRes] = await Promise.all([
      fetch('/api/filters', { signal: abortController.signal }),
      activeTags.value.length || activeSites.value.length
        ? fetch(url, { signal: abortController.signal })
        : Promise.resolve(null),
    ])
    if (!allRes.ok) return
    const allData = await allRes.json()
    allTags.value = allData.tags || []
    allSites.value = allData.sites || []
    if (availRes) {
      const availData = await availRes.json()
      availableTags.value = availData.tags || []
      availableSites.value = availData.sites || []
    } else {
      availableTags.value = allData.tags || []
      availableSites.value = allData.sites || []
    }
  } catch {}
}

function authAction() {
  if (store.isLoggedIn) {
    store.logout()
    router.push('/login')
  } else {
    router.push('/login')
  }
}

watch(showSearch, async (v) => {
  if (v) { await nextTick(); searchInput.value?.focus(); fetchFilters() }
})

onBeforeUnmount(() => { abortController?.abort() })
</script>

<style scoped>
.icon-btn {
  display: flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border-radius: var(--radius-full);
  border: none; background: none; cursor: pointer;
  color: var(--text-secondary);
  transition: background .15s, color .15s;
  text-decoration: none;
}
.icon-btn:hover { background: var(--bg-input); color: var(--text-primary); }

.nav-user {
  display: inline-flex; align-items: center; gap: 6px;
  max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: var(--text-sm); color: var(--text-secondary);
  padding: 4px 10px; border-radius: var(--radius-full);
  background: var(--bg-input);
}

.search-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: var(--surface-overlay);
  display: flex; justify-content: center; align-items: flex-start; padding-top: 10vh;
  overflow-y: auto;
}
.search-popup {
  display: flex; flex-direction: column; gap: 8px;
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: var(--radius-lg); padding: 12px; width: 520px;
  max-width: calc(100vw - 24px); min-height: 56px;
}
.search-bar-row {
  display: flex; gap: var(--space-3); align-items: center;
}
.search-popup-input {
  display: flex; align-items: center; gap: 8px; flex: 1;
  background: var(--bg-input); border-radius: var(--radius-md);
  padding: 0 12px; height: 36px;
}
.search-popup-input input {
  flex: 1; border: none; outline: none; background: none;
  color: var(--text-primary); font-size: var(--text-lg); font-family: var(--font-body);
}
.search-popup-input input::placeholder { color: var(--text-muted); }
.search-clear {
  display: flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: var(--radius-full); border: none;
  background: var(--border-light); color: var(--text-secondary);
  cursor: pointer; flex: none;
}
.search-submit {
  height: 36px; padding: 0 20px; border-radius: var(--radius-md);
  border: none; background: var(--accent); color: var(--text-inverse);
  font-size: var(--text-md); font-family: var(--font-body); font-weight: 600; cursor: pointer;
}

/* 汉堡菜单按钮：桌面隐藏，手机显示 */
.icon-btn-menu { display: none; }
@media (max-width: 640px) {
  .icon-btn-menu { display: flex; }
  .nav-user { display: none; }
  /* 导航链接收进抽屉菜单，避免项目增多后横向溢出 */
  .nav-links { display: none; }
  .nav-right { gap: 6px; }
  .icon-btn { width: 30px; height: 30px; }
}

/* 移动端抽屉 */
.drawer-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: var(--surface-overlay);
}
.drawer {
  width: 260px; height: 100%; background: var(--bg-card);
  border-right: 1px solid var(--border-light);
  display: flex; flex-direction: column;
  animation: slideIn .2s ease-out;
}
@keyframes slideIn {
  from { transform: translateX(-100%); }
  to { transform: translateX(0); }
}
.drawer-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-4); border-bottom: 1px solid var(--border-light);
}
.drawer-user {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 20px; font-size: var(--text-base); color: var(--text-secondary);
  border-bottom: 1px solid var(--border-light);
}
.drawer-links {
  display: flex; flex-direction: column; padding: 12px 0;
  overflow-y: auto;
}
.drawer-links a {
  display: block; padding: 14px 20px; font-size: var(--text-lg);
  color: var(--text-secondary); transition: background .15s;
}
.drawer-links a:hover { background: var(--bg-input); }
.drawer-links a.active { color: var(--text-primary); font-weight: 600; }

.search-filters {
  width: 100%;
}
.filter-section {
  display: flex; align-items: flex-start; gap: 8px; margin-top: var(--space-2); flex-wrap: wrap;
}
.filter-label {
  font-size: var(--text-base); color: var(--text-muted); white-space: nowrap; line-height: 28px;
}
.filter-chips {
  display: flex; flex-wrap: wrap; gap: var(--space-2);
}
.chip {
  padding: 3px 10px; border-radius: 99px; border: 1px solid var(--border-light);
  background: var(--bg-input); color: var(--text-secondary); font-size: var(--text-base);
  cursor: pointer; transition: all .15s; font-family: var(--font-body);
}
.chip:hover { border-color: var(--accent); color: var(--text-primary); }
.chip.active { background: var(--accent); color: var(--text-inverse); border-color: var(--accent); }
.chip.disabled { opacity: 0.3; cursor: default; }
.chip.disabled:hover { border-color: var(--border-light); color: var(--text-secondary); }

@media (max-width: 640px) {
  .search-overlay { padding-top: 4vh; }
  .search-popup { width: calc(100vw - 16px); }
}
</style>
