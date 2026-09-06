<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">我的收藏</h2>
      <button v-if="list.length" class="btn-export" @click="exportM3u8">导出 M3U8</button>
    </div>
    <div v-if="loading" class="empty">加载中...</div>
    <div v-else-if="!list.length" class="empty">
      <p>还没有收藏任何影片</p>
      <p class="empty-hint">在影片详情页点击收藏即可添加；先到「首页」看看最近更新，找到感兴趣的内容</p>
    </div>
    <div v-else class="grid">
      <div v-for="item in list" :key="item.id" class="card" @click="go(item)">
        <div class="cover" :style="{ backgroundImage: item.cover ? `url(${$imgUrl(item.cover)})` : undefined }">
          <span class="fav-badge">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 21s-7.5-4.7-10-9.3C.5 8 2.6 4.5 6.1 4.5c2 0 3.6 1.1 4.4 2.7h3c.8-1.6 2.4-2.7 4.4-2.7 3.5 0 5.6 3.5 4.1 7.2C19.5 16.3 12 21 12 21z" transform="scale(0.9) translate(1.3,0)"/></svg>
          </span>
          <span v-if="item.target_type === 'series'" class="type-badge">剧集</span>
          <!-- C3：不进详情页直接取消收藏 -->
          <button class="unfav-btn" @click.stop="unfav(item)" :disabled="item._unfaving">取消收藏</button>
        </div>
        <div class="card-title">{{ item.title }}</div>
        <div class="card-meta">{{ item.bangou || (item.target_type === 'series' ? '剧集' : '') }}<span v-if="item.date"> · {{ item.date }}</span></div>
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

onMounted(async () => {
  try {
    list.value = await store.fetchFavorites()
  } catch (e) { /* offline */ }
  loading.value = false
})

// C3：直接在收藏页取消收藏
async function unfav(item) {
  item._unfaving = true
  try {
    await store.removeFavorite(item.id)
    list.value = list.value.filter(x => x.id !== item.id)
    ui.success('已取消收藏')
  } catch (e) {
    item._unfaving = false
    ui.error('取消收藏失败，请稍后重试')
  }
}

async function go(item) {
  if (item.target_type === 'video') {
    router.push(`/video/${item.bangou}`)
  } else if (item.target_type === 'series') {
    router.push(`/series/${item.target_id}`)
  } else if (item.target_type === 'episode') {
    try {
      const ep = await store.fetchEpisodeDetail(item.target_id)
      if (ep?.series_id) {
        router.push(`/series/${ep.series_id}?episode=${item.target_id}`)
      } else {
        ui.error('无法定位剧集')
      }
    } catch {
      ui.error('无法定位剧集')
    }
  }
}

async function exportM3u8() {
  const lines = ['#EXTM3U']
  const skipped = []
  let count = 0

  for (const v of list.value) {
    // Only videos can be exported directly; series/episodes skipped
    if (v.target_type !== 'video') {
      skipped.push(v.title || v.bangou || '剧集')
      continue
    }
    if (v.site === '俄罗斯') {
      skipped.push(v.title || v.bangou)
      continue
    }
    const url = await store.getPlayUrl(v)
    if (url) {
      lines.push(`#EXTINF:-1,${(v.title || v.bangou).replace(/,/g, '')}`)
      lines.push(url)
      count++
    } else {
      skipped.push(v.title || v.bangou)
    }
  }

  if (!count) {
    ui.error('没有可导出的视频')
    return
  }

  const blob = new Blob([lines.join('\n')], { type: 'application/x-mpegurl' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'favorites.m3u8'
  a.click()
  URL.revokeObjectURL(a.href)

  if (skipped.length) {
    ui.success(`导出完成，共 ${count} 条。已跳过 ${skipped.length} 个（剧集/俄罗斯视频等无法直接导出）`)
  } else {
    ui.success(`导出完成，共 ${count} 条。`)
  }
}
</script>

<style scoped>
.page { padding: 24px 32px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.page-title { font-family: var(--font-display); font-size: var(--text-3xl); color: var(--text-primary); margin: 0; letter-spacing: 1px; }
.btn-export { padding: var(--space-2) var(--space-4); border-radius: var(--radius-xl); font-size: var(--text-base); background: var(--bg-input); color: var(--text-secondary); border: none; cursor: pointer; }
.btn-export:hover { background: var(--accent); color: var(--text-inverse); }
.empty { color: var(--text-muted); margin-top: 60px; text-align: center; }
.empty-hint { font-size: var(--text-md); margin-top: var(--space-2); opacity: .7; }
.unfav-btn {
  position: absolute; bottom: 8px; right: 8px;
  padding: 4px 10px; border-radius: var(--radius-sm);
  background: rgba(0,0,0,0.55); color: var(--text-inverse);
  border: 1px solid rgba(255,255,255,0.25); font-size: var(--text-xs);
  cursor: pointer;
}
.unfav-btn:hover { background: var(--error); border-color: var(--error); }
.unfav-btn:disabled { opacity: 0.4; cursor: default; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; }
.card { cursor: pointer; transition: transform .15s; }
.card:hover { transform: translateY(-4px); }
.cover {
  width: 100%; aspect-ratio: 2/3; border-radius: var(--radius);
  background: var(--bg-input); background-size: contain; background-position: center; background-repeat: no-repeat;
  position: relative;
}
.fav-badge {
  position: absolute; top: 8px; left: 8px;
  width: 24px; height: 24px; border-radius: var(--radius-full);
  background: var(--accent); color: var(--text-inverse);
  display: flex; align-items: center; justify-content: center;
  font-size: var(--text-sm);
}
.type-badge {
  position: absolute; top: 8px; right: 8px;
  padding: 2px 8px; border-radius: var(--radius-sm);
  background: var(--accent); color: var(--text-inverse);
  font-size: var(--text-xs); font-weight: 600;
}
.card-title { color: var(--text-primary); font-size: var(--text-md); font-weight: 500; margin-top: 6px; }
.card-meta { color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--text-sm); }
@media (max-width: 640px) {
  .page { padding: 16px 12px; }
  .grid { grid-template-columns: repeat(2, 1fr); gap: var(--space-3); }
  .card-title { font-size: var(--text-base); }
}
</style>
