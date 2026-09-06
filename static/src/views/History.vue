<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">观看历史</h2>
      <div class="header-actions">
        <button v-if="selectedIds.length" class="btn-action" @click="batchDelete">删除选中 ({{ selectedIds.length }})</button>
        <button v-if="list.length" class="btn-action btn-danger" @click="clearAll">清空历史</button>
      </div>
    </div>
    <div v-if="loading" class="empty">加载中...</div>
    <div v-else-if="!list.length" class="empty">
      <p>还没有观看记录</p>
      <p class="empty-hint">播放过的影片会出现在这里；先到「首页」看看最近更新的内容</p>
    </div>
    <div v-else class="grid">
      <div v-for="item in list" :key="item.id" class="card"
           :class="{ selected: selectedIds.includes(item.id) }"
           @click="toggleSelect($event, item.id)">
        <div class="card-check" @click.stop="toggleSelect($event, item.id)">
          <input type="checkbox" :checked="selectedIds.includes(item.id)" />
        </div>
        <div class="card-body" @click="go(item)">
          <div class="cover" :style="{ backgroundImage: item.cover ? `url(${$imgUrl(item.cover)})` : undefined }">
            <span v-if="item.target_type === 'series'" class="type-badge">剧集</span>
            <span v-if="item.target_type === 'episode'" class="type-badge">集</span>
            <div class="progress-bar"><div class="progress-fill" :style="{ width: (item.progress || 0) * 100 + '%' }" /></div>
          </div>
          <div class="card-title">{{ item.title }}</div>
          <div class="card-meta">
            {{ item.bangou || (item.target_type === 'series' ? '剧集' : item.target_type === 'episode' ? '单集' : '') }}
            <span v-if="item.date"> · {{ item.date }}</span>
          </div>
        </div>
        <button class="card-del" @click.stop="deleteSingle(item.id)" aria-label="删除该记录">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app.js'
import { useUiStore } from '../stores/ui.js'

const store = useAppStore()
const ui = useUiStore()
const router = useRouter()
const list = ref([])
const loading = ref(true)
const selectedIds = ref([])

onMounted(async () => {
  try {
    list.value = await store.fetchHistory()
  } catch (e) { /* offline */ }
  loading.value = false
})

async function go(item) {
  if (item.target_type === 'video') {
    router.push(`/video/${item.bangou}?progress=${(item.progress || 0).toFixed(2)}`)
  } else if (item.target_type === 'series') {
    router.push(`/series/${item.target_id}`)
  } else if (item.target_type === 'episode') {
    try {
      const ep = await store.fetchEpisodeDetail(item.target_id)
      if (ep?.series_id) {
        router.push(`/series/${ep.series_id}?episode=${item.target_id}&progress=${(item.progress || 0).toFixed(2)}`)
      } else {
        ui.error('无法定位剧集')
      }
    } catch {
      ui.error('无法定位剧集')
    }
  }
}

function toggleSelect(e, id) {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

async function deleteSingle(id) {
  await store.deleteHistoryItem(id)
  list.value = list.value.filter(i => i.id !== id)
  selectedIds.value = selectedIds.value.filter(i => i !== id)
}

async function batchDelete() {
  const ids = [...selectedIds.value]
  await store.batchDeleteHistory(ids)
  list.value = list.value.filter(i => !ids.includes(i.id))
  selectedIds.value = []
}

async function clearAll() {
  const yes = await ui.confirm('确定清空所有观看历史？', { danger: true })
  if (!yes) return
  await store.clearHistory()
  list.value = []
  selectedIds.value = []
  ui.success('已清空观看历史')
}
</script>

<style scoped>
.page { padding: 24px 32px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.page-title { font-family: var(--font-display); font-size: var(--text-3xl); color: var(--text-primary); margin: 0; letter-spacing: 1px; }
.header-actions { display: flex; gap: 8px; }
.btn-action { padding: var(--space-2) var(--space-4); border-radius: var(--radius-xl); font-size: var(--text-base); background: var(--bg-input); color: var(--text-secondary); border: none; cursor: pointer; }
.btn-action:hover { background: var(--accent); color: var(--text-inverse); }
.btn-danger:hover { background: var(--accent); color: var(--text-inverse); }
.empty { color: var(--text-muted); margin-top: 60px; text-align: center; }
.empty-hint { font-size: var(--text-md); margin-top: var(--space-2); opacity: .7; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; }
.card { position: relative; cursor: pointer; transition: transform .15s; border-radius: var(--radius); overflow: hidden; }
.card:hover { transform: translateY(-4px); }
.card.selected { outline: 2px solid var(--accent); }
.card-check { position: absolute; top: 6px; left: 6px; z-index: 2; }
.card-check input { width: 18px; height: 18px; cursor: pointer; accent-color: var(--accent); }
.card-body { cursor: pointer; }
.card-del {
  position: absolute; top: 6px; right: 6px; z-index: 2;
  width: 24px; height: 24px; border-radius: 12px;
  background: var(--surface-overlay); color: var(--text-inverse);
  border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
}
/* A2/M1：删除按钮始终显示（悬停显示在手机上永远看不到，属 bug 级） */
.card-del:hover { background: var(--error); }
.cover {
  width: 100%; aspect-ratio: 2/3; border-radius: var(--radius);
  background: var(--bg-input); background-size: contain; background-position: center; background-repeat: no-repeat;
  position: relative; overflow: hidden;
}
.type-badge {
  position: absolute; top: 6px; right: 6px;
  padding: 2px 8px; border-radius: var(--radius-sm);
  background: var(--accent); color: var(--text-inverse);
  font-size: var(--text-xs); font-weight: 600;
}
.progress-bar { position: absolute; bottom: 0; left: 0; right: 0; height: 3px; background: var(--border-light); }
.progress-fill { height: 3px; background: var(--accent); }
.card-title { color: var(--text-primary); font-size: var(--text-md); font-weight: 500; margin-top: 6px; }
.card-meta { color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--text-sm); }
@media (max-width: 640px) {
  .page { padding: 16px 12px; }
  .grid { grid-template-columns: repeat(2, 1fr); gap: var(--space-3); }
  .card-title { font-size: var(--text-base); }
}
</style>
