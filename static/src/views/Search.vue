<template>
  <div class="search-page">
    <div class="search-hero">
      <div class="search-bar-large">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M16 16L20 20" stroke-linecap="round"/></svg>
        <input v-model="query" @keydown.enter="onSearch" placeholder="搜索影片..." />
        <button class="btn btn-primary" style="border-radius: var(--radius-lg); padding: var(--space-2) var(--space-4);" @click="onSearch">搜索</button>
      </div>
    </div>
    <p v-if="total > 0" style="padding: 0 24px; color: var(--text-muted); font-size: var(--text-base);">
      找到 {{ total }} 条结果
    </p>

    <!-- B3：排序与筛选控件 -->
    <div class="search-filter-bar" v-if="searched">
      <div class="filter-group">
        <label class="filter-label">排序</label>
        <select class="filter-select" v-model="sortBy">
          <option value="newest">最新</option>
          <option value="oldest">最旧</option>
          <option value="title">标题</option>
        </select>
      </div>
      <div class="filter-group">
        <label class="filter-label">类型</label>
        <div class="filter-chips">
          <button class="filter-chip" :class="{ active: typeFilter === 'all' }" @click="typeFilter = 'all'">全部</button>
          <button class="filter-chip" :class="{ active: typeFilter === 'video' }" @click="typeFilter = 'video'">影视</button>
          <button class="filter-chip" :class="{ active: typeFilter === 'series' }" @click="typeFilter = 'series'">剧集</button>
        </div>
      </div>
      <div class="filter-group" v-if="siteOptions.length > 1">
        <label class="filter-label">来源</label>
        <div class="filter-chips">
          <button class="filter-chip" :class="{ active: siteFilter === '' }" @click="siteFilter = ''">全部来源</button>
          <button v-for="s in siteOptions" :key="s" class="filter-chip" :class="{ active: siteFilter === s }" @click="siteFilter = s">{{ s }}</button>
        </div>
      </div>
    </div>

    <div class="cat-grid" v-if="pagedItems.length">
      <div class="poster-card screw-corners" v-for="v in pagedItems" :key="v._key"
           @click="go(v)">
        <div class="cover" style="aspect-ratio: 2/3; height: auto;">
          <img :src="$imgUrl(v.cover)" @error="$imgFallback" v-if="v.cover" loading="lazy" />
          <div class="cover-placeholder" v-else><span class="placeholder-label">{{ v.site }}</span></div>
          <span v-if="v.content_type === 'series'" class="type-badge">剧集</span>
        </div>
        <div class="title">{{ v.title }}</div>
        <div class="meta">{{ v.bangou || v.id }} · {{ v.date || v.site }}</div>
      </div>
    </div>

    <!-- C4：空状态引导 -->
    <div class="search-empty" v-else-if="searched">
      <div class="search-empty-icon">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="11" cy="11" r="7"/><path d="M16 16L21 21" stroke-linecap="round"/></svg>
      </div>
      <div class="search-empty-title">没有找到相关内容</div>
      <div class="search-empty-text">可以尝试以下做法：</div>
      <ol class="search-empty-list">
        <li>换个关键词或缩短关键词后重新搜索</li>
        <li>检查类型与来源筛选条件是否过窄</li>
        <li>如果是新账号，先到「项目设置」导入数据源，再回来搜索</li>
      </ol>
    </div>

    <!-- D6：分页跳页 -->
    <div class="search-pager-wrap" v-if="totalPages > 1">
      <PaginationBar :page="page" :total-pages="totalPages" @jump="goPage" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '../stores/app.js'
import PaginationBar from '../components/PaginationBar.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const query = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const limit = 28
const totalPages = ref(1)
const searched = ref(false)
// B3 排序与筛选（对当前结果做客户端处理，不发明后端参数）
const sortBy = ref('newest')
const typeFilter = ref('all')
const siteFilter = ref('')

const siteOptions = computed(() => {
  const set = new Set()
  for (const it of items.value) {
    if (it.site) set.add(it.site)
  }
  return Array.from(set).sort()
})

const filteredItems = computed(() => {
  let arr = items.value
  if (typeFilter.value !== 'all') {
    arr = arr.filter(v => v.content_type === typeFilter.value)
  }
  if (siteFilter.value) {
    arr = arr.filter(v => v.site === siteFilter.value)
  }
  const dateOf = (v) => v.date || ''
  const titleOf = (v) => (v.title || '').toLowerCase()
  if (sortBy.value === 'newest') arr = [...arr].sort((a, b) => dateOf(b).localeCompare(dateOf(a)))
  else if (sortBy.value === 'oldest') arr = [...arr].sort((a, b) => dateOf(a).localeCompare(dateOf(b)))
  else if (sortBy.value === 'title') arr = [...arr].sort((a, b) => titleOf(a).localeCompare(titleOf(b)))
  return arr
})

// 筛选排序在当前页结果上进行；分页仍由后端承担
const pagedItems = computed(() => filteredItems.value)

onMounted(() => {
  if (route.query.q || route.query.tags || route.query.site) {
    query.value = route.query.q || ''
    page.value = parseInt(route.query.page) || 1
    search()
  }
})

watch(() => route.query, () => {
  if (route.query.q || route.query.tags || route.query.site) {
    query.value = route.query.q || ''
    page.value = parseInt(route.query.page) || 1
    search()
  }
})

async function search() {
  const q = query.value.trim()
  if (!q && !route.query.tags && !route.query.site) return
  searched.value = true
  try {
    const params = {}
    if (q) params.q = q
    if (route.query.tags) params.tags = route.query.tags
    if (route.query.site) params.site = route.query.site
    params.page = page.value
    params.limit = limit
    const [vData, sData] = await Promise.all([
      store.fetchVideos(params).catch(() => ({ items: [], total: 0 })),
      store.fetchSeries(params).catch(() => ({ items: [], total: 0 }))
    ])
    const vItems = (vData.items || []).map(v => ({ ...v, content_type: 'video', _key: `v-${v.bangou}` }))
    const sItems = (sData.items || []).map(s => ({ ...s, content_type: 'series', _key: `s-${s.id}` }))
    items.value = [...vItems, ...sItems]
    total.value = (vData.total || 0) + (sData.total || 0)
    totalPages.value = Math.max(Math.ceil((vData.total || 0) / limit), Math.ceil((sData.total || 0) / limit))
  } catch {}
}

function go(v) {
  if (v.content_type === 'series') {
    router.push(`/series/${v.id}`)
  } else {
    router.push(`/video/${v.bangou}`)
  }
}

function onSearch() {
  const q = query.value.trim()
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  if (route.query.tags) params.set('tags', route.query.tags)
  if (route.query.site) params.set('site', route.query.site)
  params.set('page', '1')
  page.value = 1
  router.push(`/search?${params.toString()}`)
}

function goPage(p) {
  page.value = p
  const params = new URLSearchParams()
  if (query.value.trim()) params.set('q', query.value.trim())
  if (route.query.tags) params.set('tags', route.query.tags)
  if (route.query.site) params.set('site', route.query.site)
  if (p > 1) params.set('page', p)
  router.push(`/search?${params.toString()}`)
}
</script>

<style scoped>
.search-page { max-width: 1440px; margin: 0 auto; }
.search-hero { padding: 32px 24px; display: flex; justify-content: center; }
.search-bar-large { display: flex; align-items: center; gap: 8px; width: 100%; max-width: 600px; height: 44px; border-radius: 22px; padding: 0 16px; background: var(--bg-input); }
.search-bar-large input { flex: 1; font-size: var(--text-lg); }
.search-filter-bar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 16px;
  padding: 8px 24px 4px;
}
.filter-group { display: flex; align-items: center; gap: 8px; }
.filter-label { font-size: var(--text-sm); color: var(--text-muted); white-space: nowrap; }
.filter-select {
  height: 30px; padding: 0 8px; border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary);
  border: 1px solid var(--border-light); font-size: var(--text-sm);
}
.filter-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.filter-chip {
  padding: 4px 12px; border-radius: var(--radius-full);
  background: var(--bg-input); color: var(--text-secondary);
  border: 1px solid var(--border-light); font-size: var(--text-sm); cursor: pointer;
}
.filter-chip:hover { border-color: var(--accent); color: var(--text-primary); }
.filter-chip.active { background: var(--accent); color: var(--text-inverse); border-color: var(--accent); font-weight: 600; }
.cat-grid { padding: 24px; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.search-pager-wrap { display: flex; justify-content: center; padding: var(--space-4); }
.search-empty {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 56px 24px; text-align: center;
}
.search-empty-icon { color: var(--text-muted); opacity: 0.6; }
.search-empty-title { font-size: var(--text-xl); font-weight: 600; color: var(--text-primary); }
.search-empty-text { color: var(--text-muted); font-size: var(--text-base); }
.search-empty-list {
  margin: 8px auto 0; padding-left: 20px; text-align: left;
  color: var(--text-secondary); font-size: var(--text-base);
  display: flex; flex-direction: column; gap: 6px; max-width: 420px;
}
.cover { position: relative; overflow: hidden; }
.cover img { width: 100%; height: 100%; object-fit: contain; display: block; }
.cover { background: var(--recessed); }
.cover-placeholder { background: linear-gradient(135deg, var(--recessed), var(--deep-shadow)); display: flex; align-items: center; justify-content: center; }
.placeholder-label { font-size: var(--text-base); color: var(--text-muted); font-weight: 600; }
.type-badge { position: absolute; top: 6px; right: 6px; padding: 2px 8px; border-radius: var(--radius-sm); background: var(--accent); color: var(--text-inverse); font-size: var(--text-xs); font-weight: 600; }
@media (max-width: 640px) {
  .cat-grid { grid-template-columns: repeat(2, 1fr); padding: 12px; gap: var(--space-3); }
  .search-hero { padding: 20px 12px; }
  .search-bar-large { height: 40px; font-size: var(--text-md); }
  .search-filter-bar { padding: 4px 12px; gap: 10px; }
}
</style>
