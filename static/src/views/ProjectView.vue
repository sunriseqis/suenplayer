<template>
  <div class="project-view">
    <div class="cat-header">
      <div class="cat-title">{{ project?.name || '项目' }}</div>
      <div class="header-actions">
        <select class="sort-select" v-model="sortBy" title="排序">
          <option value="default">默认排序</option>
          <option value="date">按日期（新到旧）</option>
          <option value="title">按标题</option>
          <option value="popularity">按热度（TMDB）</option>
          <option value="hot">按播放次数</option>
          <option value="rating">按评分</option>
          <option value="trending">按热播榜</option>
        </select>
        <button v-if="store.isAdmin" class="btn btn-secondary btn-sm edit-toggle"
                :class="{ active: store.editMode }" @click="store.toggleEdit()">
          {{ store.editMode ? '退出编辑' : '整理' }}
        </button>
      </div>
    </div>
    <p class="cat-sub" v-if="project">该项目仅展示由此项目 JSON 导入的分类与内容</p>

    <!-- 一级分类：拖拽 + 箭头排序（持久化） -->
    <div class="cat-tabs" ref="regionTabsEl">
      <button v-for="(r, idx) in regionList" :key="r.id"
              :class="{ active: r.id === regionId, dragging: dragIdx === idx }"
              :draggable="store.isAdmin && store.editMode"
              @click="switchRegion(r)"
              @dragstart="onDragStart(idx)"
              @dragover.prevent="onDragOver(idx)"
              @drop.prevent="onDrop"
              @dragend="dragIdx = -1">
        <span class="tab-arrows" v-if="store.isAdmin && store.editMode" @click.stop>
          <button class="arrow" :disabled="idx === 0" @click="moveRegion(idx, -1)" title="左移">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 6 9 12 15 18"/></svg>
          </button>
          <button class="arrow" :disabled="idx === regionList.length - 1" @click="moveRegion(idx, 1)" title="右移">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>
          </button>
        </span>
        {{ r.name }}
      </button>
    </div>

    <!-- 二级分类 -->
    <div class="cat-tabs cat-tabs-sub" v-if="groupList.length">
      <button class="all-btn" :class="{ active: !groupId }" @click="switchGroup(null)">全部</button>
      <button v-for="g in groupList" :key="g.id"
              :class="{ active: g.id === groupId }"
              @click="switchGroup(g)">{{ g.name }}</button>
    </div>

    <p class="count-line">共 {{ total }} 部<span v-if="sortBy !== 'default'"> · 已按{{ {date:'日期',title:'标题',popularity:'热度',hot:'播放次数',rating:'评分',trending:'热播榜'}[sortBy] }}排序</span></p>

    <div class="cat-grid" v-if="items.length">
      <div class="poster-card screw-corners"
           :class="{ selected: isSelectable(v) && store.isSelected(v.bangou) }"
           v-for="v in items" :key="v._key"
           @click="handleCardClick(v)">
        <div class="select-badge" v-if="store.editMode && isSelectable(v)">
          <span class="select-check" :class="{ on: store.isSelected(v.bangou) }">
            <svg v-if="store.isSelected(v.bangou)" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 12.5 10 18.5 20 6.5"/></svg>
          </span>
        </div>
        <span class="dedup-flag" v-if="v._mergedAway" title="该条目已被去重标记，导入时自动移除">已去重</span>
        <div class="cover" style="aspect-ratio: 2/3; height: auto;">
          <img :src="$imgUrl(v.cover)" @error="$imgFallback" v-if="v.cover" loading="lazy" />
          <div class="cover-placeholder" v-else><span class="placeholder-label">{{ v.site }}</span></div>
          <span v-if="v.content_type === 'series'" class="type-badge">剧集</span>
        </div>
        <div class="title">{{ v.title }}</div>
        <div class="meta">{{ v.bangou || v.id }} · {{ v.date || v.site }}</div>
      </div>
    </div>
    <div class="empty-inline" v-else-if="!loading">该项目暂无内容，请管理员在「项目设置 - 导入工作台」导入数据</div>

    <div class="pager-row" v-if="totalPages > 1">
      <PaginationBar :page="page" :total-pages="totalPages" @jump="switchPage" />
    </div>

    <!-- 编辑操作条 -->
    <div class="edit-bar" v-if="store.editMode">
      <span class="edit-count">已选 {{ store.selected.length }} 个</span>
      <div class="edit-actions">
        <button class="btn btn-primary btn-sm" :disabled="store.selected.length < 2 || busy" @click="openMerge">合并重复条目</button>
        <button class="btn btn-secondary btn-sm" :disabled="store.selected.length < 1 || busy" @click="openTransfer">批量转移分类</button>
        <button class="btn btn-secondary btn-sm" :disabled="store.selected.length !== 1 || busy" @click="openDedup">去重标记</button>
        <button class="btn btn-secondary btn-sm" :disabled="store.selected.length !== 1 || busy" @click="openMeta">元数据编辑</button>
      </div>
    </div>

    <!-- V2 弹窗 -->
    <Teleport to="body">
      <MergeModalV2 v-if="showMerge" :videos="selectedObjects" :project-id="projectId" @close="showMerge = false" @confirm="doMerge" />
      <TransferModalV2 v-if="showTransfer" :videos="selectedObjects" :categories="projectCategories" :project-id="projectId" @close="showTransfer = false" @confirm="doTransfer" />
      <DedupModalV2 v-if="showDedup" :keeper="selectedObjects[0]" :candidates="pageCandidates" :project-id="projectId" @close="showDedup = false" @confirm="doDedup" />
      <MetaModalV2 v-if="showMeta" :video="selectedObjects[0]" :categories="projectCategories" :project-id="projectId" @close="showMeta = false" @confirm="doMeta" />
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onActivated } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '../stores/app.js'
import { useUiStore } from '../stores/ui.js'
import { setSkipScroll } from '../router/index.js'
import PaginationBar from '../components/PaginationBar.vue'
import MergeModalV2 from '../components/MergeModalV2.vue'
import TransferModalV2 from '../components/TransferModalV2.vue'
import DedupModalV2 from '../components/DedupModalV2.vue'
import MetaModalV2 from '../components/MetaModalV2.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const ui = useUiStore()

const projectId = computed(() => parseInt(route.params.id))
const project = computed(() => store.projects.find(p => p.id === projectId.value))

const regionList = ref([])
const regionId = ref(null)
const groupId = ref(null)
const items = ref([])
const total = ref(0)
const page = ref(1)
const limit = 28
const totalPages = ref(1)
const loading = ref(true)
const sortBy = ref('default')
const showMerge = ref(false)
const showTransfer = ref(false)
const showDedup = ref(false)
const showMeta = ref(false)
const busy = ref(false)
const dragIdx = ref(-1)
const allCategories = ref([])

const groupList = computed(() => {
  const r = regionList.value.find(x => x.id === regionId.value)
  return r?.children || []
})

const selectedObjects = computed(() =>
  items.value.filter(v => store.isSelected(v.bangou))
)
const pageCandidates = computed(() => items.value.filter(v => isSelectable(v)))

function isSelectable(v) {
  return v.content_type === 'video' && !!v.bangou
}

function handleCardClick(v) {
  if (store.editMode && isSelectable(v)) {
    store.toggleSelect(v)
  } else {
    if (v.content_type === 'series') router.push(`/series/${v.id}`)
    else router.push(`/video/${v.bangou}`)
  }
}

async function loadCategories() {
  try {
    const data = await store.fetchCategoryTree()
    const cats = (data.categories || []).filter(c => c.project_id === projectId.value)
    allCategories.value = cats
    regionList.value = cats
    if (regionId.value == null || !cats.some(c => c.id === regionId.value)) {
      regionId.value = cats[0]?.id ?? null
      groupId.value = null
    }
  } catch {
    regionList.value = []
  }
}

async function loadItems() {
  loading.value = true
  try {
    const region = regionList.value.find(x => x.id === regionId.value)
    const group = groupList.value.find(x => x.id === groupId.value)
    const params = { page: page.value, limit }
    if (['popularity', 'hot', 'rating', 'trending'].includes(sortBy.value)) params.sort = sortBy.value
    if (region) params.region = region.name
    if (group) params.group = group.name
    const [vData, sData] = await Promise.all([
      store.fetchVideos(params).catch(() => ({ items: [], total: 0 })),
      store.fetchSeries(params).catch(() => ({ items: [], total: 0 }))
    ])
    const vItems = (vData.items || []).filter(v => v.project_id === projectId.value)
      .map(v => ({ ...v, content_type: 'video', _key: `v-${v.bangou}`, _selectKey: v.bangou }))
    const sItems = (sData.items || []).filter(s => s.project_id === projectId.value)
      .map(s => ({ ...s, content_type: 'series', _key: `s-${s.id}`, _selectKey: `series-${s.id}` }))
    let merged = [...vItems, ...sItems]
    if (sortBy.value === 'date') {
      merged.sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
    } else if (sortBy.value === 'title') {
      merged.sort((a, b) => String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN'))
    }
    items.value = merged
    total.value = (vData.total || 0) + (sData.total || 0)
    totalPages.value = Math.max(Math.ceil((vData.total || 0) / limit), Math.ceil((sData.total || 0) / limit), 1)
  } catch {
    items.value = []
    total.value = 0
  }
  loading.value = false
}

// 排序持久化（拖拽 + 箭头），经 /api/categories/reorder 落库
async function persistOrder() {
  const orders = regionList.value.map((c, i) => ({ id: c.id, sort_order: (i + 1) * 1000 }))
  try {
    await store.reorderCategories(orders)
  } catch (e) {
    ui.toast(e.message || '排序保存失败', 'error')
  }
}

function moveRegion(idx, dir) {
  const target = idx + dir
  if (target < 0 || target >= regionList.value.length) return
  const arr = [...regionList.value]
  ;[arr[idx], arr[target]] = [arr[target], arr[idx]]
  regionList.value = arr
  persistOrder()
}

function onDragStart(idx) { dragIdx.value = idx }
function onDragOver(idx) {
  if (dragIdx.value < 0 || dragIdx.value === idx) return
  const arr = [...regionList.value]
  const [moved] = arr.splice(dragIdx.value, 1)
  arr.splice(idx, 0, moved)
  dragIdx.value = idx
  regionList.value = arr
}
function onDrop() {
  if (dragIdx.value >= 0) persistOrder()
  dragIdx.value = -1
}

function switchRegion(r) {
  if (regionId.value === r.id) return
  regionId.value = r.id
  groupId.value = null
  page.value = 1
  setSkipScroll()
  loadItems()
}

function switchGroup(g) {
  groupId.value = g?.id ?? null
  page.value = 1
  setSkipScroll()
  loadItems()
}

function switchPage(p) {
  page.value = p
  setSkipScroll()
  loadItems()
}

watch(sortBy, () => { loadItems() })
watch(() => route.params.id, () => {
  regionId.value = null
  groupId.value = null
  page.value = 1
  loadCategories().then(loadItems)
})

onActivated(() => { loadItems() })

onMounted(async () => {
  await loadCategories()
  loadItems()
})

/* ─── 整理操作（V2 交互） ─── */
function openMerge() { if (store.selected.length >= 2) showMerge.value = true }
function openTransfer() { if (store.selected.length >= 1) showTransfer.value = true }
function openDedup() { if (store.selected.length === 1) showDedup.value = true }
function openMeta() { if (store.selected.length === 1) showMeta.value = true }

async function doMerge(payload) {
  busy.value = true
  try {
    await store.mergeVideos({ ...payload, project_id: projectId.value })
    showMerge.value = false
    store.clearSelection()
    store.toggleEdit()
    await loadItems()
    // 规则自动应用提示：合并规则已写入，后续导入自动应用
    ui.toast('合并完成，已写入合并规则，后续导入将自动应用', 'success', 5000)
  } catch (e) {
    ui.toast(e.message || '合并失败', 'error')
  }
  busy.value = false
}

async function doTransfer(payload) {
  busy.value = true
  try {
    await store.transferVideos({ ...payload, project_id: projectId.value })
    showTransfer.value = false
    store.clearSelection()
    store.toggleEdit()
    await loadItems()
    ui.toast('转移完成，已写入转移规则，后续导入将自动应用', 'success', 5000)
  } catch (e) {
    ui.toast(e.message || '转移失败', 'error')
  }
  busy.value = false
}

async function doDedup(payload) {
  busy.value = true
  try {
    await store.setDedup(payload.keeper, { removed: payload.removed, fields: payload.fields, project_id: projectId.value })
    showDedup.value = false
    store.clearSelection()
    store.toggleEdit()
    await loadItems()
    ui.toast(`去重标记完成（${payload.removed.length} 条），重复条目在导入时将自动移除`, 'success', 5000)
  } catch (e) {
    ui.toast(e.message || '去重标记失败', 'error')
  }
  busy.value = false
}

async function doMeta(payload) {
  busy.value = true
  try {
    await store.putOverrides({ bangou: payload.bangou, ...payload.fields, project_id: projectId.value })
    showMeta.value = false
    store.clearSelection()
    store.toggleEdit()
    await loadItems()
    ui.toast('元数据已更新，覆盖将在后续导入时保持', 'success', 5000)
  } catch (e) {
    ui.toast(e.message || '元数据更新失败', 'error')
  }
  busy.value = false
}

const projectCategories = computed(() => allCategories.value)
</script>

<style scoped>
.project-view { max-width: 1440px; margin: 0 auto; }
.cat-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 24px 4px; gap: 12px; flex-wrap: wrap; }
.cat-title { font-size: var(--text-2xl); font-weight: 600; }
.cat-sub { padding: 2px 24px 0; color: var(--text-muted); font-size: var(--text-sm); margin: 0; }
.header-actions { display: flex; align-items: center; gap: 10px; }
.sort-select {
  height: 30px; padding: 0 8px; border-radius: var(--radius-sm);
  border: 1px solid var(--border-light); background: var(--bg-input);
  color: var(--text-secondary); font-size: var(--text-sm);
}
.edit-toggle.active { background: var(--accent); color: var(--text-inverse); }

.cat-tabs { display: flex; gap: 8px; padding: 12px 24px; overflow-x: auto; }
.cat-tabs button {
  display: inline-flex; align-items: center; gap: 6px;
  padding: var(--space-2) var(--space-4); border-radius: var(--radius-xl); font-size: var(--text-base);
  background: var(--bg-input); color: var(--text-secondary); white-space: nowrap;
  border: none; cursor: pointer;
}
.cat-tabs button.active { background: var(--accent); color: var(--text-inverse); font-weight: 600; }
.cat-tabs button.dragging { opacity: 0.5; }
.tab-arrows { display: inline-flex; gap: 2px; }
.arrow {
  display: inline-flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; border-radius: var(--radius-sm);
  border: none; background: var(--border-light); color: var(--text-secondary); cursor: pointer; padding: 0;
}
.arrow:hover:not(:disabled) { background: var(--accent); color: var(--text-inverse); }
.arrow:disabled { opacity: 0.3; cursor: default; }
.cat-tabs-sub { padding-top: 0; }
.cat-tabs-sub button { font-size: var(--text-sm); padding: 4px 12px; }
.all-btn { min-width: 40px; }

.count-line { padding: 4px 24px 0; color: var(--text-muted); font-size: var(--text-base); margin: 0; }
.cat-grid { padding: 20px 24px; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.cat-grid > .poster-card { min-width: 0; }
.poster-card { position: relative; cursor: pointer; }
.poster-card.selected { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: var(--radius); }
.select-badge { position: absolute; top: 6px; left: 6px; z-index: 5; width: 24px; height: 24px; border-radius: var(--radius-full); background: rgba(0,0,0,0.35); display: flex; align-items: center; justify-content: center; }
.select-check { width: 18px; height: 18px; border-radius: var(--radius-full); border: 2px solid #fff; color: var(--text-inverse); display: flex; align-items: center; justify-content: center; }
.select-check.on { background: var(--accent); border-color: var(--accent); }
.dedup-flag {
  position: absolute; top: 6px; left: 6px; z-index: 4;
  padding: 2px 8px; border-radius: var(--radius-sm);
  background: var(--error); color: #fff; font-size: var(--text-xs); font-weight: 600;
}
.pagination, .pager-row { display: flex; justify-content: center; padding: var(--space-4); }
.cover { position: relative; overflow: hidden; }
.cover img { width: 100%; height: 100%; object-fit: contain; display: block; }
.cover { background: var(--recessed); }
.cover-placeholder { background: linear-gradient(135deg, var(--recessed), var(--deep-shadow)); display: flex; align-items: center; justify-content: center; }
.placeholder-label { font-size: var(--text-base); color: var(--text-muted); font-weight: 600; }
.type-badge { position: absolute; top: 6px; right: 6px; padding: 2px 8px; border-radius: var(--radius-sm); background: var(--accent); color: var(--text-inverse); font-size: var(--text-xs); font-weight: 600; }
.empty-inline { padding: 48px 24px; text-align: center; color: var(--text-muted); }

.edit-bar {
  position: sticky; bottom: 0; z-index: 20;
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 12px 24px; margin-top: 12px; flex-wrap: wrap;
  background: var(--bg-card); border-top: 1px solid var(--border-light);
  box-shadow: var(--shadow-sharp);
}
.edit-count { font-size: var(--text-md); color: var(--text-secondary); }
.edit-actions { display: flex; gap: var(--space-3); flex-wrap: wrap; }

@media (max-width: 640px) {
  .cat-grid { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); padding: 12px; gap: 10px; }
  .cat-grid > .poster-card { min-width: 0; }
  .cat-header { padding: 12px 12px 4px; }
  .cat-tabs { padding: 10px 12px; }
  .cat-tabs button { font-size: var(--text-sm); padding: 5px 12px; }
  .cat-tabs-sub button { font-size: var(--text-xs); padding: var(--space-1) var(--space-3); }
  .count-line { padding: 4px 12px 0; }
  .edit-bar { flex-direction: column; align-items: stretch; padding: 12px; }
}
</style>
