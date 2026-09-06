<template>
  <div class="recent-page">
    <div class="page-inner">
      <h2 class="page-title">最近更新</h2>

      <!-- 全量列表（默认）：新到旧，分页 -->
      <template v-if="!activeProject">
        <div class="recent-grid" v-if="items.length">
          <div class="poster-card screw-corners" v-for="v in items" :key="v._key" @click="goToItem(v)">
            <div class="cover">
              <img :src="$imgUrl(v.cover)" @error="$imgFallback" v-if="$imgUrl(v.cover)" loading="lazy" />
              <div class="cover-placeholder" v-else><span class="placeholder-label">{{ v.site || v.region || '' }}</span></div>
              <span v-if="v.type === 'series'" class="type-badge-float">剧集</span>
            </div>
            <div class="title">{{ v.title }}</div>
            <div class="meta">{{ v.bangou || v.id }} · {{ v.date || (v.first_imported_at || '').slice(0, 10) }}</div>
          </div>
        </div>
        <div class="empty-inline" v-else-if="!loading">暂无更新记录</div>
        <div class="pager-row" v-if="totalPages > 1">
          <PaginationBar :page="page" :total-pages="totalPages" @jump="onJump" />
        </div>
      </template>

      <!-- 项目子标签视图：仅该项目的最近更新（服务端过滤） -->
      <template v-else>
        <div class="recent-grid" v-if="projectItems.length">
          <div class="poster-card screw-corners" v-for="v in projectItems" :key="v._key" @click="goToItem(v)">
            <div class="cover">
              <img :src="$imgUrl(v.cover)" @error="$imgFallback" v-if="$imgUrl(v.cover)" loading="lazy" />
              <div class="cover-placeholder" v-else><span class="placeholder-label">{{ v.site || v.region || '' }}</span></div>
              <span v-if="v.type === 'series'" class="type-badge-float">剧集</span>
            </div>
            <div class="title">{{ v.title }}</div>
            <div class="meta">{{ v.bangou || v.id }} · {{ v.date || (v.first_imported_at || '').slice(0, 10) }}</div>
          </div>
        </div>
        <div class="empty-inline project-error" v-else-if="projectError">{{ projectError }}</div>
        <div class="empty-inline" v-else-if="!projectLoading">该项目暂无更新记录</div>
        <div class="pager-row" v-if="projectTotalPages > 1">
          <PaginationBar :page="projectPage" :total-pages="projectTotalPages" @jump="onProjectJump" />
        </div>
      </template>

      <!-- 按来源（项目）切换的子标签：不加「全部」，再次点击已选项可回到全量 -->
      <div class="subtabs" v-if="store.projects.length">
        <span class="subtabs-label">按来源：</span>
        <button v-for="p in store.projects" :key="p.id"
                class="subtab" :class="{ active: activeProject?.id === p.id }"
                @click="toggleProject(p)">{{ p.name }}</button>
      </div>
      <div class="subtabs-hint" v-if="store.projects.length">再次点击已选来源可返回全量列表</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app.js'
import PaginationBar from '../components/PaginationBar.vue'

const store = useAppStore()
const router = useRouter()

const items = ref([])
const page = ref(1)
const total = ref(0)
const loading = ref(true)
const PAGE_SIZE = 60

const activeProject = ref(null)
const projectItems = ref([])
const projectLoading = ref(false)
const projectPage = ref(1)
const projectTotal = ref(0)
const projectError = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const projectTotalPages = computed(() => Math.max(1, Math.ceil(projectTotal.value / PAGE_SIZE)))

function decorate(v, type) {
  return { ...v, type, _key: `${type}-${v.bangou || v.id}` }
}

async function loadFull() {
  loading.value = true
  try {
    const data = await store.fetchRecentUpdates(page.value, PAGE_SIZE)
    items.value = [
      ...(data.items || []).map(v => decorate(v, v.type || 'video'))
    ]
    total.value = data.total || items.value.length
  } catch {
    items.value = []
    total.value = 0
  }
  loading.value = false
}

async function loadProject(p) {
  projectLoading.value = true
  projectError.value = ''
  projectItems.value = []
  try {
    // 服务端过滤：条目自带 project_id / project，403 表示无权限项目，未知项目返回空页
    const data = await store.fetchRecentUpdates(projectPage.value, PAGE_SIZE, p.name)
    projectItems.value = (data.items || []).map(v => decorate(v, v.type || 'video'))
    projectTotal.value = data.total || projectItems.value.length
  } catch (e) {
    projectItems.value = []
    projectTotal.value = 0
    if (e.status === 403) {
      projectError.value = '无权访问该项目，请联系管理员开通该项目的可见权限'
    } else {
      projectError.value = e.message || '加载失败，请稍后重试'
    }
  }
  projectLoading.value = false
}

function toggleProject(p) {
  if (activeProject.value?.id === p.id) {
    activeProject.value = null
    projectItems.value = []
    projectTotal.value = 0
    projectError.value = ''
  } else {
    activeProject.value = p
    projectPage.value = 1
    loadProject(p)
  }
}

function onProjectJump(p) {
  if (!activeProject.value) return
  projectPage.value = p
  loadProject(activeProject.value)
}

function onJump(p) {
  page.value = p
  loadFull()
}

function goToItem(v) {
  if (v.type === 'series') router.push(`/series/${v.id}`)
  else router.push(`/video/${v.bangou}`)
}

watch(page, loadFull, { immediate: true })
watch(() => store.projects.length, (n) => { if (!n) activeProject.value = null })
</script>

<style scoped>
.recent-page { display: flex; justify-content: center; padding-bottom: 40px; }
.page-inner { width: 100%; max-width: 1440px; padding: 20px 24px 0; }
.page-title { margin: 0 0 16px; font-size: var(--text-2xl); color: var(--text-primary); }

.recent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 14px;
}
.cover { position: relative; aspect-ratio: 2/3; overflow: hidden; border-radius: var(--radius-sm); background: var(--recessed); }
.cover-placeholder { width: 100%; height: 100%; background: linear-gradient(135deg, var(--recessed), var(--deep-shadow)); display: flex; align-items: center; justify-content: center; }
.cover img { width: 100%; height: 100%; object-fit: contain; display: block; }
.placeholder-label { font-size: var(--text-lg); color: var(--text-muted); font-weight: 600; }
.poster-card { cursor: pointer; }
.poster-card .title {
  margin-top: 8px; font-size: var(--text-base); color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.poster-card .meta {
  margin-top: 2px; font-size: var(--text-sm); color: var(--text-muted); font-family: var(--font-mono);
}
.type-badge-float { position: absolute; top: 6px; right: 6px; padding: 2px 8px; border-radius: var(--radius-sm); background: var(--accent); color: var(--text-inverse); font-size: var(--text-xs); font-weight: 600; }

.empty-inline { padding: 48px 0; text-align: center; color: var(--text-muted); }
.empty-inline.project-error { color: var(--warning, var(--accent)); }

.pager-row { display: flex; justify-content: center; margin-top: 22px; }

.subtabs {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  margin-top: 26px; padding-top: 16px; border-top: 1px solid var(--border-light);
}
.subtabs-label { font-size: var(--text-base); color: var(--text-muted); }
.subtab {
  padding: 6px 16px; border-radius: 99px; border: 1px solid var(--border-light);
  background: var(--bg-input); color: var(--text-secondary); font-size: var(--text-base);
  cursor: pointer; transition: all .15s;
}
.subtab:hover { border-color: var(--accent); color: var(--text-primary); }
.subtab.active { background: var(--accent); color: var(--text-inverse); border-color: var(--accent); font-weight: 600; }
.subtabs-hint { margin-top: 8px; font-size: var(--text-sm); color: var(--text-muted); }

@media (max-width: 640px) {
  .page-inner { padding: 14px 12px 0; }
  .recent-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; }
}
</style>
