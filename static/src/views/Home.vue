<template>
  <div class="home">
    <div class="home-inner">
      <!-- 最近更新海报轮播 -->
      <section class="hero" v-if="carouselItems.length">
        <div class="hero-slide" v-for="(v, i) in carouselItems" :key="v._key"
             :class="{ active: i === heroIdx }"
             @click="goToItem(v)">
          <div class="hero-bg" :style="heroBg(v)"></div>
          <div class="hero-shade"></div>
          <img class="hero-poster" :src="$imgUrl(v.cover)" @error="$imgFallback" v-if="$imgUrl(v.cover)" loading="lazy" />
          <div class="hero-content">
            <span class="hero-num">{{ i + 1 }}</span>
            <h2 class="hero-title">{{ v.title }}</h2>
            <p class="hero-meta">
              <span v-if="v.type === 'series'" class="type-badge">剧集</span>
              {{ v.bangou || v.id }} · {{ v.region || '' }}{{ v.date ? ' · ' + v.date : '' }}
            </p>
          </div>
        </div>
        <div class="hero-nav">
          <span v-for="(v, i) in carouselItems" :key="i"
                :class="{ active: i === heroIdx }" @click.stop="heroIdx = i"></span>
        </div>
      </section>

      <!-- 最近更新列表（最新在前，仅铺满一屏） -->
      <section class="home-section" v-if="recentItems.length">
        <div class="section-title">
          最近更新
          <router-link to="/recent" class="more">查看全部
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>
          </router-link>
        </div>
        <div class="recent-grid">
          <div class="poster-card screw-corners" v-for="v in recentItems" :key="v._key"
               @click="goToItem(v)">
            <div class="cover">
              <img :src="$imgUrl(v.cover)" @error="$imgFallback" v-if="$imgUrl(v.cover)" loading="lazy" />
              <div class="cover-placeholder" v-else><span class="placeholder-label">{{ v.site || v.region || '' }}</span></div>
              <span v-if="v.type === 'series'" class="type-badge-float">剧集</span>
            </div>
            <div class="title">{{ v.title }}</div>
            <div class="meta">{{ v.bangou || v.id }} · {{ v.date || v.first_imported_at?.slice(0, 10) || '' }}</div>
          </div>
        </div>
      </section>

      <!-- 空状态引导（C4） -->
      <section class="empty-state" v-if="!loading && !recentItems.length">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 8h20"/><path d="M8 20v-8h8v8"/></svg>
        <h3>这里还是空的</h3>
        <p>还没有任何入库内容。下一步：</p>
        <ol>
          <li v-if="store.isAdmin">到「项目设置 - 导入工作台」添加远端数据源并执行导入</li>
          <li v-else>请联系管理员在项目设置中导入数据源</li>
          <li v-if="store.isAdmin">导入完成后，可在「项目设置 - 自动更新」配置定期自动更新</li>
        </ol>
      </section>

      <footer style="padding: 24px; text-align: center; color: var(--text-muted); font-size: var(--text-sm);">
        {{ store.siteName }} · 仅供个人使用
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore, imgUrl } from '../stores/app.js'

defineOptions({ name: 'HomeView' })

const store = useAppStore()
const router = useRouter()
const carouselItems = ref([])
const heroIdx = ref(0)
const recentItems = ref([])
const loading = ref(true)
let carouselTimer = null

const CAROUSEL_SIZE = 8
const ONE_SCREEN_SIZE = 24

function heroBg(v) {
  const u = imgUrl(v.backdrop) || imgUrl(v.cover)
  return u ? { backgroundImage: `url("${u}")` } : {}
}

function goToItem(v) {
  if (v.type === 'series') {
    router.push(`/series/${v.id}`)
  } else {
    router.push(`/video/${v.bangou}`)
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const data = await store.fetchRecentUpdates(1, 60)
    const items = (data.items || []).map(v => ({
      ...v,
      _key: `${v.type}-${v.bangou || v.id}`
    }))
    recentItems.value = items.slice(0, ONE_SCREEN_SIZE)
    // 轮播取最近更新内容随机洗牌（随机轮播最近更新，而非随机推荐）
    carouselItems.value = [...items].slice(0, CAROUSEL_SIZE)
    for (let i = carouselItems.value.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[carouselItems.value[i], carouselItems.value[j]] = [carouselItems.value[j], carouselItems.value[i]]
    }
    heroIdx.value = 0
  } catch { /* ignore */ }
  loading.value = false

  carouselTimer = setInterval(() => {
    if (carouselItems.value.length > 1)
      heroIdx.value = (heroIdx.value + 1) % carouselItems.value.length
  }, 5000)
})

onBeforeUnmount(() => {
  clearInterval(carouselTimer)
})
</script>

<style scoped>
.home { padding-bottom: 32px; display: flex; justify-content: center; }
.home-inner { width: 100%; max-width: 1440px; }
.home-section { padding: 24px 24px 0; }

.section-title {
  display: flex; align-items: center; gap: 10px;
  font-size: var(--text-xl); font-weight: 700; color: var(--text-primary);
  margin-bottom: 14px;
}
.section-title .more {
  display: inline-flex; align-items: center; gap: 2px;
  font-size: var(--text-base); font-weight: 500; color: var(--text-secondary);
  text-decoration: none;
}
.section-title .more:hover { color: var(--accent); }

/* Hero banner */
.hero { position: relative; margin: 0 24px 8px; border-radius: var(--radius-md); overflow: hidden; height: 320px; }
.hero-slide { position: absolute; inset: 0; display: flex; opacity: 0; transition: opacity .6s; cursor: pointer; }
.hero-slide.active { opacity: 1; z-index: 1; }
/* 全幅背景：backdrop 优先（16:9 横版剧照），无 backdrop 退化为 poster */
.hero-bg {
  position: absolute; inset: 0;
  background-size: cover; background-position: center 25%;
  transform: scale(1.02);
}
.hero-shade {
  position: absolute; inset: 0;
  background: linear-gradient(90deg, rgba(10,14,22,.92) 0%, rgba(10,14,22,.55) 42%, rgba(10,14,22,.08) 78%),
              linear-gradient(0deg, rgba(10,14,22,.55) 0%, transparent 40%);
}
/* 左侧海报小图：完整显示，垂直居中 */
.hero-poster {
  position: absolute; left: 40px; top: 50%; transform: translateY(-50%);
  height: calc(100% - 56px); width: auto; max-width: 220px;
  object-fit: contain; border-radius: var(--radius); box-shadow: 0 8px 28px rgba(0,0,0,.5);
}
.hero-content {
  position: absolute; left: 300px; right: 48px; top: 50%; transform: translateY(-50%);
  color: #fff; display: flex; flex-direction: column; justify-content: center;
  text-shadow: 0 2px 12px rgba(0,0,0,.6);
}
.hero-num { font-family: var(--font-display); font-size: 56px; opacity: .3; line-height: 1; margin-bottom: 6px; }
.hero-title { font-size: var(--text-3xl); font-weight: 700; line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.hero-meta { font-size: var(--text-base); opacity: .85; margin-top: 10px; font-family: var(--font-mono); }
.hero-nav { position: absolute; bottom: 16px; right: 32px; z-index: 2; display: flex; gap: 8px; }
.hero-nav span { width: 8px; height: 8px; border-radius: var(--radius-sm); background: rgba(255,255,255,0.25); cursor: pointer; transition: width .3s; }
.hero-nav span.active { width: 24px; background: var(--text-primary); }

.type-badge { display: inline-block; padding: 2px 8px; border-radius: var(--radius-sm); background: rgba(255,255,255,0.2); font-size: var(--text-xs); margin-right: 8px; }
.type-badge-float { position: absolute; top: 6px; right: 6px; padding: 2px 8px; border-radius: var(--radius-sm); background: var(--accent); color: var(--text-inverse); font-size: var(--text-xs); font-weight: 600; }

/* 最近更新网格 */
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

/* 空状态 */
.empty-state {
  margin: 40px 24px; padding: 48px 24px;
  border: 1px dashed var(--border); border-radius: var(--radius-md);
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  color: var(--text-secondary); text-align: left;
}
.empty-state h3 { margin: 6px 0 0; color: var(--text-primary); font-size: var(--text-xl); }
.empty-state p { margin: 0; font-size: var(--text-base); }
.empty-state ol { margin: 6px 0 0; padding-left: 20px; font-size: var(--text-base); line-height: 1.9; }

@media (max-width: 640px) {
  .home-section { padding: 16px 12px 0; }
  .hero { margin: 0 12px 8px; height: 210px; }
  .hero-poster { display: none; }
  .hero-content { left: 20px; right: 20px; }
  .hero-num { font-size: 36px; }
  .recent-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; }
  .empty-state { margin: 24px 12px; }
}
</style>
