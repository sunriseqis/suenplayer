<template>
  <div class="page">
    <div class="page-header">
      <h1 class="page-title">下载</h1>
      <div class="header-actions">
        <!-- C2：按状态筛选 -->
        <select class="dl-filter" v-model="statusFilter">
          <option value="all">全部状态</option>
          <option value="running">进行中</option>
          <option value="done">已完成</option>
          <option value="error">失败</option>
          <option value="canceled">已取消</option>
        </select>
        <!-- C2：一键清理已完成 -->
        <button class="btn btn-secondary btn-sm" @click="clearDone"
                :disabled="clearing || !items.some(t => t.status === 'done')">清理已完成</button>
        <button class="btn btn-secondary btn-sm" @click="refresh" :disabled="loading">刷新</button>
      </div>
    </div>

    <div v-if="loading && !items.length" class="empty-state">加载中...</div>
    <div v-else-if="!filteredItems.length" class="empty-state">
      <p v-if="items.length">当前筛选条件下没有任务</p>
      <template v-else>
        <p>暂无下载任务</p>
        <p class="empty-hint">在视频详情页点击「下载」即可创建任务</p>
      </template>
    </div>

    <div v-else class="task-list">
      <div v-for="t in filteredItems" :key="t.id" class="task-card">
        <div class="task-main">
          <!-- B2: 已完成任务展示封面缩略图（后端懒生成 poster，加载失败回退占位），辅助快速识别内容 -->
          <div v-if="t.status === 'done'" class="task-thumb">
            <img v-if="!thumbFailed[t.id]" :src="`/api/download/${t.id}/poster`" loading="lazy"
                 alt="" @error="thumbFailed[t.id] = true" />
            <div v-else class="task-thumb-fallback">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="18" rx="2"/><polygon points="10 8 16 12 10 16"/></svg>
            </div>
          </div>
          <div class="task-info">
            <div class="task-title" :title="t.title">{{ t.title }}</div>
            <div class="task-meta">
              <span class="badge" :class="'badge-' + t.format">{{ t.format === 'm3u8' ? 'M3U8' : 'MP4' }}</span>
              <span v-if="t.site" class="task-site">{{ t.site }}</span>
              <span class="task-time">{{ fmtTime(t.created_at) }}</span>
            </div>
          </div>
          <div class="task-actions">
            <template v-if="isRunning(t.status)">
              <button class="btn btn-danger btn-sm" @click="cancelTask(t)">取消</button>
            </template>
            <template v-else-if="t.status === 'done'">
              <button class="btn btn-primary btn-sm" @click="togglePlayTask(t)">播放</button>
              <a class="btn btn-secondary btn-sm" :href="`/api/download/${t.id}/file`">取回</a>
              <button class="btn btn-danger btn-sm" @click="deleteTask(t)">删除</button>
            </template>
            <template v-else>
              <button v-if="t.status === 'error' || t.status === 'canceled'"
                      class="btn btn-secondary btn-sm" @click="retryTask(t)">重试</button>
              <button class="btn btn-danger btn-sm" @click="deleteTask(t)">删除</button>
            </template>
          </div>
        </div>

        <div class="task-progress-row">
          <div class="progress-track">
            <div class="progress-fill" :class="statusClass(t.status)"
                 :style="{ width: (t.progress || 0) + '%' }"></div>
          </div>
          <span class="progress-text">{{ statusText(t) }}</span>
        </div>

        <div v-if="t.status === 'error'" class="task-error">{{ t.message || t.error }}</div>

        <!-- 下载日志（可折叠） -->
        <div v-if="(t.log || []).length" class="task-log">
          <button class="log-toggle" @click="toggleLog(t.id)">
            <svg :class="{ open: logOpen === t.id }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
            下载日志 ({{ t.log.length }})
          </button>
          <pre v-if="logOpen === t.id" class="log-body">{{ t.log.join('\n') }}</pre>
        </div>
      </div>
    </div>

    <!-- B: 复用统一播放器，本地离线内容直接播放（localUrl 模式，跳过测速选线）：
         m3u8 任务播本地分片（hls.js 逐片拉取，可随意拖放）；mp4 任务播 faststart 预处理产物 -->
    <PlayerModal v-if="playTask && playTask.status === 'done'"
                 :localUrl="playTask.format === 'm3u8'
                   ? `/api/download/${playTask.id}/play.m3u8`
                   : `/api/download/${playTask.id}/play`"
                 :title="playTask.title"
                 @close="playTask = null" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { authFetch } from '../stores/app.js'
import { useUiStore } from '../stores/ui.js'
import PlayerModal from '../components/PlayerModal.vue'

const ui = useUiStore()
const items = ref([])
const loading = ref(false)
const playTask = ref(null)
const logOpen = ref('')
const statusFilter = ref('all')
// B2: 封面加载失败标记（回退占位图标），key 为任务 id
const thumbFailed = ref({})
const clearing = ref(false)
// P2-9: 自适应轮询间隔 + refresh 防重入
let timer = null
let refreshInFlight = false
const ACTIVE_POLL_MS = 1000
const IDLE_POLL_MS = 8000

// C2：按状态筛选（客户端过滤）
const filteredItems = computed(() => {
  if (statusFilter.value === 'all') return items.value
  if (statusFilter.value === 'running') return items.value.filter(t => t.status === 'pending' || t.status === 'running')
  return items.value.filter(t => t.status === statusFilter.value)
})

async function refresh() {
  if (refreshInFlight) return
  refreshInFlight = true
  // 仅首次（列表为空）展示加载态，避免轮询期间界面抖动
  if (!items.value.length) loading.value = true
  try {
    const r = await authFetch('/api/download/tasks')
    const data = await r.json()
    items.value = (data.items || []).map(t => {
      if (t.status === 'running' && t.progress) {
        t.progress = Math.max(t.progress, 1)
      }
      return t
    })
    schedulePoll(items.value.some(t => t.status === 'pending' || t.status === 'running'))
  } catch {
    schedulePoll(false)
  }
  loading.value = false
  refreshInFlight = false
}

function schedulePoll(hasActive) {
  if (timer) clearInterval(timer)
  // P2-9: 有进行中任务保持 1s 快轮询；空闲时降频到 8s，减少无效请求
  timer = setInterval(refresh, hasActive ? ACTIVE_POLL_MS : IDLE_POLL_MS)
}

function toggleLog(id) {
  logOpen.value = logOpen.value === id ? '' : id
}

function isRunning(s) { return s === 'pending' || s === 'running' }
function statusClass(s) {
  if (s === 'done') return 'ok'
  if (s === 'error' || s === 'canceled') return 'err'
  return 'run'
}
function statusText(t) {
  if (t.status === 'pending') return '等待中'
  if (t.status === 'running') return `${t.progress || 0}%` + (t.message ? ` · ${t.message}` : '')
  if (t.status === 'done') return '已完成' + (t.size ? `（${fmtSize(t.size)}）` : '')
  if (t.status === 'canceled') return '已取消'
  if (t.status === 'error') return '失败'
  return t.status
}
function fmtSize(n) {
  if (!n) return ''
  if (n > 1 << 30) return (n / (1 << 30)).toFixed(2) + ' GB'
  if (n > 1 << 20) return (n / (1 << 20)).toFixed(1) + ' MB'
  return (n / (1 << 10)).toFixed(0) + ' KB'
}
function fmtTime(s) {
  if (!s) return ''
  const d = new Date(s)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function cancelTask(t) {
  await authFetch(`/api/download/${t.id}/cancel`, { method: 'POST' })
  refresh()
}
async function retryTask(t) {
  const r = await authFetch(`/api/download/${t.id}/retry`, { method: 'POST' })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) { ui.error(data.error || '重试失败'); return }
  if (playTask.value?.id === t.id) playTask.value = null
  refresh()
}
async function deleteTask(t) {
  if (t.status === 'running' || t.status === 'pending') {
    const yes = await ui.confirm('下载正在进行，确定删除该任务？', { danger: true })
    if (!yes) return
  }
  await authFetch(`/api/download/${t.id}`, { method: 'DELETE' })
  if (playTask.value?.id === t.id) playTask.value = null
  refresh()
}
// C2：一键清理已完成任务（复用已有的单任务删除接口）
async function clearDone() {
  const doneList = items.value.filter(t => t.status === 'done')
  if (!doneList.length) return
  const yes = await ui.confirm(`确定清理全部 ${doneList.length} 个已完成任务？`, { danger: true })
  if (!yes) return
  clearing.value = true
  let okCount = 0
  for (const t of doneList) {
    try {
      const r = await authFetch(`/api/download/${t.id}`, { method: 'DELETE' })
      if (r.ok) okCount++
    } catch {}
  }
  clearing.value = false
  if (playTask.value && doneList.some(t => t.id === playTask.value.id)) playTask.value = null
  await refresh()
  ui.success(`已清理 ${okCount} 个已完成任务`)
}
function togglePlayTask(t) {
  playTask.value = playTask.value?.id === t.id ? null : t
}

onMounted(() => {
  refresh()
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.page { padding: var(--space-5); max-width: 860px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-4); }
.page-title { font-size: var(--text-4xl); font-weight: 700; font-family: var(--font-display); }
.header-actions { display: flex; gap: 8px; align-items: center; }
.dl-filter {
  height: 30px; padding: 0 8px; border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary);
  border: 1px solid var(--border-light); font-size: var(--text-sm);
}
.empty-state { text-align: center; padding: 60px 20px; color: var(--text-muted); }
.empty-hint { font-size: var(--text-md); margin-top: var(--space-2); color: var(--text-muted); opacity: .7; }

.task-list { display: flex; flex-direction: column; gap: var(--space-3); }
.task-card {
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: var(--radius); padding: 12px 14px;
}
.task-main { display: flex; justify-content: space-between; gap: var(--space-3); align-items: flex-start; }
.task-info { flex: 1; min-width: 0; }
/* B2: 封面缩略图 */
.task-thumb {
  width: 96px; height: 60px; flex-shrink: 0; border-radius: var(--radius-md);
  overflow: hidden; background: rgba(255,255,255,0.06);
}
.task-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.task-thumb-fallback {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  color: var(--text-muted);
}
.task-title { font-size: var(--text-lg); font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { display: flex; align-items: center; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
.task-site { font-size: var(--text-sm); color: var(--text-muted); }
.task-time { font-size: var(--text-sm); color: var(--text-muted); }
.badge {
  font-size: var(--text-xs); padding: 2px 6px; border-radius: var(--radius-sm); font-weight: 600;
}
.badge-m3u8 { background: rgba(255,71,87,0.12); color: var(--accent); }
.badge-mp4 { background: rgba(34,197,94,0.15); color: var(--success); }

.task-actions { display: flex; gap: var(--space-2); flex-shrink: 0; flex-wrap: wrap; justify-content: flex-end; }

.task-progress-row { display: flex; align-items: center; gap: var(--space-3); margin-top: 10px; }
.progress-track { flex: 1; height: 6px; background: var(--bg-input); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; border-radius: 3px; transition: width .4s; }
.progress-fill.run { background: var(--accent); }
.progress-fill.ok { background: var(--success); }
.progress-fill.err { background: var(--error); }
.progress-text { font-size: var(--text-base); color: var(--text-muted); min-width: 80px; text-align: right; }

.task-error { margin-top: var(--space-2); font-size: var(--text-base); color: var(--error); word-break: break-all; }
.task-log { margin-top: 10px; }
.log-toggle {
  display: inline-flex; align-items: center; gap: 5px;
  background: none; border: none; cursor: pointer;
  font-size: var(--text-base); color: var(--text-muted); font-family: var(--font-body);
  padding: 2px 4px; border-radius: var(--radius-sm); transition: color .15s;
}
.log-toggle:hover { color: var(--text-primary); }
.log-toggle svg { transition: transform .2s; }
.log-toggle svg.open { transform: rotate(180deg); }
.log-body {
  margin-top: 6px; padding: 8px 10px;
  background: var(--bg-input); border: 1px solid var(--border-light);
  border-radius: var(--radius); font-size: var(--text-sm); line-height: 1.5;
  color: var(--text-secondary); overflow-x: auto;
  max-height: 220px; overflow-y: auto;
  white-space: pre-wrap; word-break: break-all;
  font-family: var(--font-mono);
}
</style>
