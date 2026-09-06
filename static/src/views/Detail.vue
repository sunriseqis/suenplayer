<template>
  <div class="detail" v-if="item && (item.bangou || item.id)">
    <div class="detail-hero-bg" v-if="displayBackdrop" :style="{ backgroundImage: `url(${$imgUrl(displayBackdrop)})` }"></div>
    <button class="btn-back" @click="router.back()">
      <svg width="20" height="20" viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" fill="currentColor"/></svg>
      返回
    </button>
    <div class="detail-content">
      <div class="detail-poster">
        <img :src="$imgUrl(displayCover)" @error="$imgFallback" v-if="displayCover" class="d-poster-img" loading="lazy" />
        <div class="cover-placeholder d-poster-img" v-else><span class="placeholder-label">{{ item.site }}</span></div>
      </div>
      <div class="detail-info">
        <span class="tag tag-red">{{ isSeries ? '剧集' : item.bangou }}</span>
        <h1 class="d-title">{{ item.title }}</h1>
        <div class="d-tags">
          <span class="tag tag-red">{{ item.region || '未分类' }}</span>
          <span class="tag tag-gray" v-if="item.group">{{ item.group }}</span>
          <span class="tag tag-gray" v-for="t in displayTags" :key="t">{{ t }}</span>
          <button v-if="store.isLoggedIn && !tagEditMode" class="icon-btn tag-edit-btn" @click="enterTagEdit" title="编辑标签">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
        </div>

        <!-- 评分 -->
        <div class="d-rating" v-if="item.rating">
          <span class="rating-score">{{ item.rating.toFixed(1) }}</span>
          <span class="rating-source" v-if="item.rating_source">{{ item.rating_source }}</span>
          <span class="rating-count" v-if="item.vote_count">({{ item.vote_count }} 人评分)</span>
        </div>

        <!-- 元数据全展示 -->
        <div class="d-meta card">
          <div class="meta-row" v-if="item.date"><span>日期</span><span class="mono">{{ item.date }}</span></div>
          <div class="meta-row" v-if="item.year"><span>年份</span><span class="mono">{{ item.year }}</span></div>
          <div class="meta-row" v-if="item.first_air_date"><span>首播</span><span class="mono">{{ item.first_air_date }}</span></div>
          <div class="meta-row" v-if="item.status"><span>状态</span><span>{{ statusText(item.status) }}</span></div>
          <div class="meta-row" v-if="isSeries && item.number_of_episodes"><span>总集数</span><span class="mono">{{ item.number_of_episodes }}</span></div>
          <div class="meta-row" v-if="item.homepage"><span>官网</span><a :href="item.homepage" target="_blank" rel="noopener" class="meta-link">{{ item.homepage }}</a></div>
          <div class="meta-row" v-if="item.runtime"><span>时长</span><span>{{ item.runtime }} 分钟</span></div>
          <div class="meta-row" v-if="item.country"><span>国家</span><span>{{ item.country }}</span></div>
          <div class="meta-row" v-if="item.studio"><span>制作</span><span>{{ item.studio }}</span></div>
          <div class="meta-row" v-if="item.certification"><span>分级</span><span>{{ item.certification }}</span></div>
          <div class="meta-row" v-if="item.original_language"><span>语言</span><span>{{ item.original_language }}</span></div>
          <div class="meta-row" v-if="displayCast.length"><span>演员</span><span class="meta-value">{{ displayCast.join('、') }}</span></div>
          <div class="meta-row" v-if="displayDirector.length"><span>导演</span><span class="meta-value">{{ displayDirector.join('、') }}</span></div>
          <div class="meta-row" v-if="item.site"><span>来源</span><span>{{ item.site }}</span></div>
        </div>

        <!-- 简介（当前季有独立简介时随季切换） -->
        <div class="d-overview" v-if="displayOverview">
          <div class="overview-label">{{ isSeries && activeSeason && activeSeason.season_overview ? (activeSeason.season_title || `第 ${activeSeason.season_number} 季`) + '简介' : '简介' }}</div>
          <div class="overview-text" :class="{ collapsed: overviewCollapsed }">{{ displayOverview }}</div>
          <button v-if="displayOverview.length > 120" class="overview-toggle" @click="overviewCollapsed = !overviewCollapsed">
            {{ overviewCollapsed ? '展开' : '收起' }} <svg class="chev" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>

        <div class="d-actions">
          <button class="btn btn-primary" style="flex:1; height:44px;" @click="playNow">
            <svg width="16" height="16" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>
            {{ isSeries ? '继续观看' : '立即播放' }}
          </button>
          <button class="btn btn-secondary dl-btn" :disabled="dlBusy" @click="startDownload" title="创建下载任务">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            下载
          </button>
          <button class="btn btn-secondary" style="width: 120px; height: 44px;" @click="toggleFav">
            <svg width="14" height="14" viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" :fill="isFav ? 'var(--accent)' : 'var(--text-secondary)'"/></svg>
            {{ isFav ? '已收藏' : '收藏' }}
          </button>
        </div>

        <!-- Tag editor -->
        <div v-if="tagEditMode" class="d-tag-editor">
          <div class="tag-editor-label">编辑标签</div>
          <div class="tag-editor-tags">
            <span class="tag tag-gray" v-for="t in editTags" :key="t">
              {{ t }}
              <button class="tag-remove" @click="removeTag(t)" aria-label="删除标签"><svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg></button>
            </span>
          </div>
          <div class="tag-editor-input-row">
            <input v-model="newTag" placeholder="输入标签，回车添加" @keyup.enter="addTag" class="tag-input" />
            <button class="btn btn-primary btn-sm" @click="saveTags" :disabled="savingTags">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              {{ savingTags ? '保存中...' : '保存' }}
            </button>
            <button class="btn btn-secondary btn-sm" @click="cancelTagEdit">取消</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 剧集季切换 -->
    <div class="season-section" v-if="isSeries && seasons.length">
      <!-- 多季展示季标签 -->
      <div class="season-tabs" v-if="seasons.length > 1">
        <button
          v-for="s in seasons"
          :key="s.id"
          :class="{ active: activeSeasonId === s.id }"
          @click="activeSeasonId = s.id"
        >{{ s.season_title || `第 ${s.season_number} 季` }}<span class="season-tab-count" v-if="seasonEpCount(s)">{{ seasonEpCount(s) }}集</span></button>
      </div>

      <!-- 集列表控制栏 -->
      <div class="episode-controls" v-if="activeSeason?.episodes?.length">
        <span class="ep-count">共 {{ activeSeason.episodes.length }} 集</span>
        <button class="sort-toggle" @click="toggleEpisodeSort">
          {{ episodeDesc ? '倒序' : '正序' }} <svg class="chev" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
      </div>

      <!-- 集列表 -->
      <div class="episode-list" v-if="activeSeason?.episodes?.length">
        <div
          class="episode-item"
          v-for="ep in sortedEpisodes"
          :key="ep.id"
          @click="playEpisode(ep)"
        >
          <div class="ep-still" v-if="ep.ep_still">
            <img :src="$imgUrl(ep.ep_still)" @error="$imgFallback" loading="lazy" />
          </div>
          <div class="ep-info">
            <div class="ep-title">
              {{ epDisplayTitle(ep) }}
              <button class="ep-dl-btn" :disabled="dlBusy" @click.stop="downloadEpisode(ep)" title="下载本集">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              </button>
            </div>
            <div class="ep-meta" v-if="epMeta(ep)">{{ epMeta(ep) }}</div>
            <div class="ep-overview" v-if="ep.ep_overview">{{ ep.ep_overview }}</div>
            <div class="ep-progress" v-if="epProgress[ep.id]">
              <div class="progress-bar"><div class="progress-fill" :style="{ width: (epProgress[ep.id] * 100) + '%' }"></div></div>
              <span class="progress-text">看到 {{ Math.round(epProgress[ep.id] * 100) }}%</span>
            </div>
          </div>
          <div class="ep-play-btn">
            <svg width="20" height="20" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>
          </div>
        </div>
      </div>
    </div>

    <!-- Related -->
    <section class="home-section" v-if="related.length">
      <div class="section-title">相关推荐</div>
      <div class="scroll-row">
        <div class="poster-card" style="width: 160px" v-for="v in related" :key="v.bangou || v.id"
             @click="navigateTo(v)">
          <div class="cover" style="aspect-ratio: 2/3">
            <img :src="$imgUrl(v.cover)" @error="$imgFallback" v-if="v.cover" loading="lazy" />
            <div class="cover-placeholder" v-else><span class="placeholder-label">{{ v.site }}</span></div>
          </div>
          <div class="title">{{ v.title }}</div>
          <div class="meta">{{ v.bangou || '' }} · {{ v.region }}</div>
        </div>
      </div>
    </section>

    <!-- Player Modal -->
    <Teleport to="body">
      <PlayerModal
        v-if="showPlayer"
        :targetId="playTargetId"
        :targetType="playTargetType"
        :title="playTitle"
        :cover="item.cover"
        :initialProgress="initialProgress"
        @close="showPlayer = false"
        @progress="saveProgress"
      />
    </Teleport>
  </div>
  <div class="detail-empty" v-else-if="!loading">内容未找到</div>
  <div class="detail-empty" v-else>加载中...</div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '../stores/app.js'
import { useUiStore } from '../stores/ui.js'
import PlayerModal from '../components/PlayerModal.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const ui = useUiStore()

const item = ref(null)
const isSeries = ref(false)
const seasons = ref([])
const activeSeasonId = ref(null)
const related = ref([])
const isFav = ref(false)
const showPlayer = ref(false)
const loading = ref(true)
const tagEditMode = ref(false)
const editTags = ref([])
const newTag = ref('')
const savingTags = ref(false)
const overviewCollapsed = ref(true)
const episodeDesc = ref(false)
const epProgress = ref({})

const playTargetId = ref(null)
const playTargetType = ref('video')
const playTitle = ref('')
const initialProgress = ref(0)

const displayTags = computed(() => {
  const tags = (item.value?.tags || '').split(',').filter(Boolean)
  const group = item.value?.group
  const site = item.value?.site
  return tags.filter(t => t !== group && t !== site)
})

const displayCast = computed(() => {
  const raw = item.value?.cast
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed
  } catch {}
  return raw.split(/[,;、]/).filter(Boolean)
})

const displayDirector = computed(() => {
  const raw = item.value?.director
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed
  } catch {}
  return raw.split(/[,;、]/).filter(Boolean)
})

const activeSeason = computed(() => {
  return seasons.value.find(s => s.id === activeSeasonId.value) || seasons.value[0] || null
})

// 季级元数据跟随：当前季带独立封面/简介（TMDB 多季各不相同）时覆盖剧级展示，
// 该季缺省时回退剧级字段
const displayCover = computed(() => {
  const s = isSeries.value ? activeSeason.value : null
  return (s && s.season_cover) || item.value?.cover || ''
})
const displayBackdrop = computed(() => item.value?.backdrop || '')
const displayOverview = computed(() => {
  const s = isSeries.value ? activeSeason.value : null
  return (s && s.season_overview) || item.value?.overview || ''
})

const sortedEpisodes = computed(() => {
  const eps = activeSeason.value?.episodes || []
  const arr = [...eps]
  if (episodeDesc.value) {
    arr.sort((a, b) => (b.ep_number || 0) - (a.ep_number || 0))
  } else {
    arr.sort((a, b) => (a.ep_number || 0) - (b.ep_number || 0))
  }
  return arr
})

// 集标题兜底：源数据常出现整季标题雷同（如全为“第01集”）的脏数据。
// 标题里含数字且与集号矛盾时按集号显示；无数字的标题（“番外篇”等）保留
function seasonEpCount(s) {
  return s.episodes?.length || s.episode_count || 0
}
const dlBusy = ref(false)
async function startDownload() {
  if (!item.value || dlBusy.value) return
  dlBusy.value = true
  try {
    if (isSeries.value) {
      // 整季下载：每集各建一个任务
      const all = (seasons.value || []).flatMap(s => s.episodes || [])
      if (!all.length) { ui.toast('该剧集没有可下载的集', 'error'); return }
      if (all.length > 20 && !(await ui.confirm(`共 ${all.length} 集，将创建 ${all.length} 个下载任务，继续？`))) return
      let okN = 0
      for (const ep of all) {
        try {
          const r = await store.createDownload({
            target_type: 'episode', target_id: ep.id,
            project_id: item.value.project_id,
            title: `${item.value.title} - ${epDisplayTitle(ep)}`,
          })
          if (!r.error) okN += 1
        } catch {}
      }
      ui.toast(`已创建 ${okN}/${all.length} 个下载任务`, okN ? 'success' : 'error')
      if (okN) router.push('/downloads')
    } else {
      const r = await store.createDownload({
        target_type: 'video',
        target_id: item.value.id,
        bangou: item.value.bangou,
        project_id: item.value.project_id,
        title: item.value.title,
        site: item.value.site || '',
      })
      if (r.error) throw new Error(r.error)
      ui.toast('下载任务已创建，可在「下载任务」页查看进度', 'success')
      router.push('/downloads')
    }
  } catch (e) {
    ui.toast(e.message || '创建下载任务失败', 'error')
  }
  dlBusy.value = false
}
async function downloadEpisode(ep) {
  if (dlBusy.value) return
  dlBusy.value = true
  try {
    const r = await store.createDownload({
      target_type: 'episode',
      target_id: ep.id,
      project_id: item.value.project_id,
      title: `${item.value.title} - ${epDisplayTitle(ep)}`,
    })
    if (r.error) throw new Error(r.error)
    ui.toast(`已创建下载：${epDisplayTitle(ep)}`, 'success')
  } catch (e) {
    ui.toast(e.message || '创建下载任务失败', 'error')
  }
  dlBusy.value = false
}
function epMeta(ep) {
  const parts = []
  if (ep.duration) parts.push(`${Math.round(ep.duration)}分钟`)
  if (ep.ep_rating) parts.push(`★ ${Number(ep.ep_rating).toFixed(1)}`)
  if (ep.air_date) parts.push(ep.air_date)
  return parts.join(' · ')
}
function epDisplayTitle(ep) {
  const title = String(ep.ep_title || '').trim()
  const n = ep.ep_number
  if (!title) return n ? `第 ${n} 集` : '未命名'
  if (!n) return title
  const m = title.match(/\d+/)
  if (m && parseInt(m[0], 10) !== n) return `第 ${n} 集`
  return title
}

function statusText(s) {
  const map = { ended: '已完结', ongoing: '连载中', upcoming: '即将播出' }
  return map[s] || s
}

function loadEpisodeSortPref() {
  try {
    const v = localStorage.getItem('suenplayer-episode-sort')
    episodeDesc.value = v === 'desc'
  } catch {}
}

function toggleEpisodeSort() {
  episodeDesc.value = !episodeDesc.value
  try {
    localStorage.setItem('suenplayer-episode-sort', episodeDesc.value ? 'desc' : 'asc')
  } catch {}
}

onMounted(async () => {
  loadEpisodeSortPref()
  await store.checkAuth()
  await loadDetail()
})

watch(() => route.params, async () => {
  await loadDetail()
})

// P2-6: 详情加载竞态保护——只接受最后一次调用的响应写入 state
let loadSeq = 0

async function loadDetail() {
  const seq = ++loadSeq
  loading.value = true
  item.value = null
  seasons.value = []
  related.value = []
  isFav.value = false

  const seriesId = route.params.series_id
  const bangou = route.params.bangou

  try {
    if (seriesId) {
      isSeries.value = true
      const data = await store.fetchSeriesDetail(seriesId)
      if (seq !== loadSeq) return
      item.value = data
      seasons.value = data.seasons || []
      if (seasons.value.length) {
        activeSeasonId.value = seasons.value[0].id
      }
      await checkFavStatus('series', data.id)
      if (seq !== loadSeq) return
      await loadRelated(data.region, data.id, 'series')
    } else if (bangou) {
      isSeries.value = false
      const data = await store.fetchVideo(bangou)
      if (seq !== loadSeq) return
      item.value = data
      await checkFavStatus('video', data.id)
      if (seq !== loadSeq) return
      await loadRelated(data.region, data.id, 'video')
    }
  } catch (e) {
    console.error('loadDetail error', e)
  }
  if (seq !== loadSeq) return

  // Load episode progress from history
  try {
    const hist = await store.fetchHistory()
    if (seq !== loadSeq) return
    const arr = Array.isArray(hist) ? hist : []
    const map = {}
    for (const h of arr) {
      if (h.target_type === 'episode' && h.target_id) {
        map[h.target_id] = h.progress || 0
      }
    }
    epProgress.value = map
  } catch {}

  if (seq !== loadSeq) return
  loading.value = false
}

async function checkFavStatus(targetType, targetId) {
  try {
    isFav.value = await store.checkFav(targetType, targetId)
  } catch { isFav.value = false }
}

async function loadRelated(region, excludeId, excludeType) {
  try {
    if (!region) return
    const [vData, sData] = await Promise.all([
      store.fetchVideos({ region, limit: 8 }),
      store.fetchSeries({ region, limit: 8 })
    ])
    const vItems = (vData.items || []).filter(v => !(excludeType === 'video' && v.id === excludeId))
    const sItems = (sData.items || []).filter(s => !(excludeType === 'series' && s.id === excludeId))
    related.value = [...vItems, ...sItems].slice(0, 8)
  } catch {}
}

function navigateTo(v) {
  if (v.type === 'series' || v.number_of_seasons) {
    router.push(`/series/${v.id}`)
  } else {
    router.push(`/video/${v.bangou}`)
  }
}

function playNow() {
  if (isSeries.value) {
    // Find the episode with the most progress, or first episode
    const eps = activeSeason.value?.episodes || []
    if (!eps.length) return
    let bestEp = eps[0]
    let bestProg = epProgress.value[bestEp.id] || 0
    for (const ep of eps) {
      const p = epProgress.value[ep.id] || 0
      if (p > 0 && p < 0.95 && p > bestProg) {
        bestEp = ep
        bestProg = p
      }
    }
    playEpisode(bestEp)
  } else {
    playTargetId.value = item.value.id
    playTargetType.value = 'video'
    playTitle.value = item.value.title
    initialProgress.value = parseFloat(route.query.progress || '0')
    showPlayer.value = true
  }
}

function playEpisode(ep) {
  playTargetId.value = ep.id
  playTargetType.value = 'episode'
  playTitle.value = `${item.value.title} - ${epDisplayTitle(ep)}`
  initialProgress.value = epProgress.value[ep.id] || 0
  showPlayer.value = true
}

async function saveProgress({ targetId, targetType, progress }) {
  await store.addHistory(targetType, targetId, progress)
  if (targetType === 'episode') {
    epProgress.value[targetId] = progress
  }
}

async function toggleFav() {
  const targetType = isSeries.value ? 'series' : 'video'
  const targetId = item.value.id
  isFav.value = await store.toggleFav(targetType, targetId)
}

function addTag() {
  const t = newTag.value.trim()
  if (t && !editTags.value.includes(t)) {
    editTags.value.push(t)
  }
  newTag.value = ''
}

function removeTag(t) {
  editTags.value = editTags.value.filter(x => x !== t)
}

function enterTagEdit() {
  editTags.value = (item.value?.tags || '').split(',').filter(Boolean)
  tagEditMode.value = true
}

function cancelTagEdit() {
  tagEditMode.value = false
  editTags.value = []
}

async function saveTags() {
  savingTags.value = true
  try {
    // 改走 store.setVideoTags（内部 authFetch 带 Authorization 头 + jfetch 错误检查）：
    // 原裸 fetch 无 Bearer 头，HTTP 局域网部署下 Secure cookie 不落盘，保存必 401 且静默失败。
    // project_id 不传（本视图无项目上下文），与原行为一致，由后端按默认项目归属。
    const updated = await store.setVideoTags(item.value.bangou, editTags.value)
    item.value.tags = updated.tags
    tagEditMode.value = false
  } catch (e) {
    ui.toast(e.message || '标签保存失败', 'error')
  }
  savingTags.value = false
}
</script>

<style scoped>
.btn-back {
  display: inline-flex; align-items: center; gap: var(--space-2);
  margin: 16px 48px 0; padding: var(--space-2) var(--space-4);
  border: none; border-radius: var(--radius);
  background: var(--bg-card); color: var(--text-primary);
  cursor: pointer; font-size: var(--text-lg); transition: background .2s;
}
.btn-back:hover { background: var(--border-light); }
.detail { padding-bottom: 32px; }

@media (max-width: 768px) {
  .btn-back { margin: 12px 16px 0; padding: 10px 14px; font-size: var(--text-xl); }
}
.detail-content { display: flex; gap: 32px; padding: 20px 32px; }
.detail-poster { flex-shrink: 0; width: 360px; }
.d-poster-img { width: 360px; aspect-ratio: 2/3; border-radius: var(--radius-md); object-fit: contain; background: var(--recessed); }
.detail-info { flex: 1; display: flex; flex-direction: column; gap: 16px; }
.d-title { font-family: var(--font-display); font-size: 30px; line-height: 1.15; }
.d-tags { display: flex; gap: var(--space-2); align-items: center; flex-wrap: wrap; }
.d-rating { display: flex; align-items: center; gap: 8px; }
.rating-score { font-size: var(--text-3xl); font-weight: 700; color: var(--accent); }
.rating-source { font-size: var(--text-md); color: var(--text-muted); }
.rating-count { font-size: var(--text-sm); color: var(--text-muted); }
.d-meta { display: flex; flex-direction: column; gap: var(--space-3); }
.meta-row { display: flex; gap: var(--space-6); font-size: var(--text-md); }
.meta-row span:first-child { color: var(--text-muted); width: 48px; flex-shrink: 0; }
.meta-value { flex: 1; }
.mono { font-family: var(--font-mono); }
.d-overview { background: var(--panel); border-radius: var(--radius-lg); padding: var(--space-5); box-shadow: var(--shadow-card); }
.overview-label { font-size: var(--text-sm); color: var(--text-muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; }
.overview-text { font-size: var(--text-md); line-height: 1.6; color: var(--text-secondary); }
.overview-text.collapsed { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.overview-toggle { background: none; border: none; color: var(--accent); font-size: var(--text-sm); cursor: pointer; margin-top: 6px; padding: 0; }
.d-actions { display: flex; gap: var(--space-3); }

/* Season section */
.detail-hero-bg {
  position: absolute; inset: 0; background-size: cover; background-position: center 20%;
  opacity: 0.18; filter: blur(2px) saturate(0.9); pointer-events: none;
}
.detail-hero-bg::after { content: ''; position: absolute; inset: 0; background: linear-gradient(180deg, transparent, var(--bg) 92%); }
.detail { position: relative; }
.detail .btn-back, .detail-content, .season-section { position: relative; z-index: 1; }
.dl-btn { height: 44px; }
.ep-dl-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; margin-left: 6px; padding: 0;
  border: none; border-radius: var(--radius-sm); background: transparent;
  color: var(--text-muted); cursor: pointer; vertical-align: middle;
  opacity: 0; transition: opacity .15s, background .15s, color .15s;
}
.episode-item:hover .ep-dl-btn { opacity: 1; }
.ep-dl-btn:hover { background: var(--bg-input); color: var(--accent); }
.season-tab-count { margin-left: 6px; font-size: var(--text-xs); opacity: 0.65; font-weight: 400; }
.meta-link { color: var(--accent); text-decoration: none; word-break: break-all; }
.meta-link:hover { text-decoration: underline; }
.season-section { padding: 0 48px 32px; max-width: 1200px; }
.season-tabs { display: flex; gap: 8px; margin-bottom: 16px; overflow-x: auto; }
.season-tabs button { padding: var(--space-2) var(--space-4); border-radius: var(--radius-xl); font-size: var(--text-base); background: var(--bg-input); color: var(--text-secondary); white-space: nowrap; border: none; cursor: pointer; }
.season-tabs button.active { background: var(--accent); color: var(--text-inverse); font-weight: 600; }
.episode-controls { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.ep-count { font-size: var(--text-sm); color: var(--text-muted); }
.sort-toggle { background: var(--bg-input); border: none; border-radius: var(--radius); padding: 4px 12px; font-size: var(--text-sm); color: var(--text-secondary); cursor: pointer; }
.episode-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.episode-item { display: flex; flex-direction: column; align-items: stretch; gap: 6px; padding: 8px 10px; border-radius: var(--radius-md); background: var(--panel); box-shadow: var(--shadow-card); cursor: pointer; transition: transform .15s, box-shadow .15s; }
.episode-item:hover { transform: translateY(-2px); box-shadow: var(--shadow-floating); }
.ep-still { width: 100%; height: 68px; border-radius: var(--radius-sm); overflow: hidden; flex-shrink: 0; background: var(--recessed); }
.ep-still img { width: 100%; height: 100%; object-fit: cover; }
.ep-info { flex: 1; min-width: 0; }
.ep-title { font-size: var(--text-sm); font-weight: 600; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ep-meta { font-size: var(--text-xs); color: var(--text-muted); margin-top: 2px; }
.ep-overview { font-size: var(--text-xs); color: var(--text-secondary); margin-top: 4px; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
.ep-progress { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.ep-progress .progress-bar { flex: 1; height: 3px; background: var(--recessed); border-radius: 2px; }
.ep-progress .progress-fill { height: 100%; background: var(--accent); border-radius: 2px; }
.ep-progress .progress-text { font-size: var(--text-xs); color: var(--text-muted); white-space: nowrap; }
.ep-play-btn { display: none; }

/* Tag editor */
.d-tag-editor { margin-top: 16px; padding: 12px; border: 1px solid var(--border-light); border-radius: var(--radius-md); }
.tag-editor-label { font-size: var(--text-sm); color: var(--text-muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; }
.tag-editor-tags { display: flex; gap: var(--space-2); flex-wrap: wrap; margin-bottom: 8px; min-height: 24px; }
.tag-remove { background: none; border: none; color: inherit; cursor: pointer; font-size: var(--text-xs); margin-left: 2px; opacity: 0.6; }
.tag-remove:hover { opacity: 1; }
.tag-edit-btn { flex-shrink: 0; opacity: 0.5; transition: opacity .15s; }
.tag-edit-btn:hover { opacity: 1; background: var(--bg-input); }
.tag-editor-input-row { display: flex; gap: 8px; }
.tag-input { flex: 1; height: 32px; padding: 0 10px; border-radius: var(--radius); border: 1px solid var(--border-light); background: var(--bg-input); color: var(--text-primary); font-size: var(--text-base); outline: none; }
.tag-input:focus { border-color: var(--accent); }

@media (max-width: 768px) {
  .detail-content { flex-direction: column; padding: var(--space-4); gap: 16px; }
  .detail-poster, .d-poster-img { width: 100%; }
  .d-title { font-size: 24px; }
  .season-section { padding: 0 16px 24px; }
  .episode-item { gap: 6px; padding: 8px; }
  .episode-list { grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); }
  .ep-still { width: 100%; height: 50px; }
}
</style>
