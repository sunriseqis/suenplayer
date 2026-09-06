<template>
  <div class="player-overlay" :class="{ 'cursor-none': isFullscreen && !showControls }" @click.self="$emit('close')">
    <div class="player-container" tabindex="0" ref="containerEl">
      <!-- 关闭按钮常驻可见：不随控制条自动隐藏，避免找不到退出入口 -->
      <button class="player-close player-close-floating" @click="$emit('close')" aria-label="关闭播放器" title="退出播放 (Esc)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
        <span>退出</span>
      </button>
      <div class="player-top" v-show="showControls">
        <span class="player-title">{{ title }}</span>
      </div>

      <!-- 测速状态覆盖层 -->
      <div class="probe-overlay" v-if="probeState === 'probing'">
        <div class="probe-panel">
          <div class="spinner"></div>
          <div class="probe-text">正在测速选线…</div>
          <div class="probe-sub">探测可用线路质量，请稍候</div>
        </div>
      </div>

      <!-- fresh-url 解析状态 -->
      <div class="probe-overlay" v-if="probeState === 'resolving'">
        <div class="probe-panel">
          <div class="spinner"></div>
          <div class="probe-text">正在解析播放地址…</div>
          <div class="probe-sub">页面源地址需要实时解析真实流地址</div>
        </div>
      </div>

      <!-- 线路选择面板 -->
      <div class="probe-overlay" v-if="probeState === 'selecting'">
        <div class="line-panel">
          <div class="line-title">选择播放线路</div>
          <div class="line-list">
            <div
              class="line-item"
              v-for="(ln, idx) in lineList"
              :key="idx"
              :class="{ primary: idx === 0, page: ln.url_type === 'page' }"
              @click="selectLine(ln)"
            >
              <span class="line-badge" v-if="idx === 0">推荐</span>
              <span class="line-badge page-badge" v-else-if="ln.url_type === 'page'">网页源</span>
              <span class="line-source">{{ ln.source || '线路' }}</span>
              <span class="line-label" v-if="ln.label">{{ ln.label }}</span>
              <span class="line-res" v-if="ln.resolution">{{ ln.resolution }}</span>
              <span class="line-score" v-if="ln.score !== undefined && ln.url_type !== 'page'">
                评分 {{ ln.score.toFixed(2) }}
              </span>
              <span class="line-latency" v-if="ln.latency_ms && ln.url_type !== 'page'">
                {{ ln.latency_ms }}ms
              </span>
            </div>
          </div>
          <button class="btn btn-secondary" style="width:100%;margin-top:12px" @click="retryProbe">重新测速</button>
        </div>
      </div>

      <!-- 错误覆盖层 -->
      <div class="probe-overlay" v-if="probeState === 'error'">
        <div class="probe-panel">
          <div class="player-error-text">{{ errorMsg }}</div>
          <button class="player-error-btn" @click="retryProbe">重试</button>
          <button class="player-error-btn btn-secondary" @click="showLineSelector">手动选线</button>
          <button class="player-error-btn btn-secondary" @click="$emit('close')">关闭</button>
        </div>
      </div>

      <div class="player-video-wrap" ref="videoWrap"
        @click="onTapVideo" @dblclick="onDblClick" @wheel.prevent="onWheel"
        @touchstart="onTouchStart" @touchmove="onTouchMove"
        @touchend="onTouchEnd" @touchcancel="onTouchEnd">
        <div class="touch-zone touch-zone-left"></div>
        <div class="touch-zone touch-zone-right"></div>
        <video ref="videoEl" class="player-video" playsinline preload="metadata" :poster="cover ? $imgUrl(cover) : ''"></video>
        <div class="player-big-play" v-if="!playing && showControls && probeState === 'ready'">
          <span class="big-play-btn" @click="togglePlay">
            <svg width="56" height="56" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>
          </span>
        </div>
        <div class="player-loading" v-if="loading && !playError && probeState === 'ready'">
          <div class="spinner"></div>
        </div>
        <div class="player-error" v-if="playError">
          <span class="player-error-text">{{ playError }}</span>
          <button class="player-error-btn" @click="retryProbe">重试</button>
          <button class="player-error-btn btn-secondary" @click="showLineSelector">换线路</button>
          <button class="player-error-btn btn-secondary" @click="$emit('close')">关闭</button>
        </div>
        <div class="seek-hint" v-if="seekHint.show" :style="{ left: seekHint.x + '%' }">
          <span class="seek-hint-text">{{ seekHint.dir }} {{ seekHint.sec }}秒</span>
        </div>
        <div class="speed-hint" v-if="isSpeeding">
          <span class="speed-hint-text">2X 快进中</span>
        </div>
        <!-- A3 续看提示 -->
        <div class="probe-overlay resume-overlay" v-if="resumeAsk">
          <div class="probe-panel">
            <div class="probe-text">继续播放？</div>
            <div class="probe-sub">检测到上次观看进度，可以接着上次的位置继续看</div>
            <div class="resume-actions">
              <button class="player-error-btn" @click="chooseResume(true)">续看</button>
              <button class="player-error-btn btn-secondary" @click="chooseResume(false)">从头播放</button>
            </div>
          </div>
        </div>
        <!-- M2 手机首次手势引导（仅首次，3 秒自动消失） -->
        <div class="gesture-guide" v-if="gestureGuide">
          <div class="gesture-guide-card">
            <div class="gesture-guide-row">
              <span class="gesture-side">左半屏</span><span>双击 = 后退 10 秒</span>
            </div>
            <div class="gesture-guide-row">
              <span class="gesture-side">右半屏</span><span>双击 = 前进 10 秒</span>
            </div>
          </div>
        </div>
      </div>

      <div class="player-controls" v-show="showControls && probeState === 'ready'">
        <div class="pc-progress" ref="progressBar"
          @mousedown="startDrag"
          @touchstart.prevent="startDrag"
          @mousemove="onProgressMove"
          @mouseleave="tooltipSec = null"
        >
          <div class="pc-progress-buffer" :style="{ width: buffered + '%' }"></div>
          <div class="pc-progress-fill" :style="{ width: dragActive ? dragPct : progress + '%' }"></div>
          <div class="pc-progress-dot" :style="{ left: dragActive ? dragPct : progress + '%' }"></div>
          <div class="pc-tooltip" v-if="tooltipSec !== null" :style="{ left: tooltipPct + '%' }">
            {{ tooltipSec }}
          </div>
        </div>
        <div class="pc-row">
          <div class="pc-left">
            <button @click.stop="togglePlay">
              <svg v-if="playing" width="22" height="22" viewBox="0 0 24 24"><path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" fill="currentColor"/></svg>
              <svg v-else width="22" height="22" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>
            </button>
            <span class="time-text">{{ currentTime }} / {{ duration }}</span>
          </div>
          <div class="pc-right">
            <button class="line-btn" @click.stop="showLineSelector" title="切换线路">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h16" stroke-linecap="round"/></svg>
              <span class="line-btn-text">{{ currentLine?.source || '线路' }}</span>
            </button>
            <div class="vol-wrap">
              <button @click.stop="toggleMute">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path v-if="!muted" d="M11 5L6 9H2v6h4l5 4V5zM19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.07" stroke-linecap="round"/><path v-else d="M11 5L6 9H2v6h4l5 4V5zM23 9l-6 6M17 9l6 6" stroke-linecap="round"/></svg>
              </button>
              <input class="vol-slider" type="range" min="0" max="1" step="0.05" :value="volLevel" @input="onVolInput">
            </div>
            <button class="speed-btn" @click.stop="cycleSpeed">{{ speed }}</button>
            <button @click.stop="toggleFullscreen">
              <svg v-if="!isFullscreen" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 00-2 2v3m18 0V5a2 2 0 00-2-2h-3m0 18h3a2 2 0 002-2v-3M3 16v3a2 2 0 002 2h3" stroke-linecap="round"/></svg>
              <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" stroke-linecap="round"/></svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useAppStore } from '../stores/app.js'
import Hls from 'hls.js'
import mpegts from 'mpegts.js'

const props = defineProps({
  // 本地播放模式（localUrl）下不需要 targetId，在线模式必传
  targetId: { type: Number, default: null },
  targetType: { type: String, default: 'video' },
  title: { type: String, default: '' },
  cover: { type: String, default: '' },
  initialProgress: { type: Number, default: 0 },
  // B: 本地离线内容直接播放模式（Downloads 页传入 /api/download/{id}/play(.m3u8)），
  // 传入后跳过测速选线，按格式选择解码引擎直接起播
  localUrl: { type: String, default: '' }
})
const emit = defineEmits(['close', 'progress'])

const store = useAppStore()
const videoEl = ref(null)
const videoWrap = ref(null)
const containerEl = ref(null)
const progressBar = ref(null)

const playing = ref(false)
const loading = ref(true)
const currentTime = ref('0:00')
const duration = ref('0:00')
const progress = ref(0)
const buffered = ref(0)
const muted = ref(false)
const volLevel = ref(1)
const speed = ref('1.0×')
const showControls = ref(true)
const isFullscreen = ref(false)
const dragActive = ref(false)
const dragPct = ref(0)
const tooltipSec = ref(null)
const tooltipPct = ref(0)
const seekHint = ref({ show: false, dir: '', sec: 0, x: 50 })
const isSpeeding = ref(false)
const playError = ref('')
// A3 续看提示状态
const resumePending = ref(props.initialProgress > 0)
const resumeAsk = ref(false)
// M2 手机首次手势引导
const gestureGuide = ref(false)

// Probe state: 'probing' | 'selecting' | 'resolving' | 'ready' | 'error'
const probeState = ref('probing')
const errorMsg = ref('')
const lineList = ref([])
const currentLine = ref(null)

let hls = null
// 本地 TS 裸流使用 mpegts.js 点播引擎（isLive:false），与 hls 生命周期统一管理
let mpegtsPlayer = null
// P2-3: hls.js fatal 错误按官方恢复矩阵有限重试
let hlsNetRetries = 0
let hlsMediaRetries = 0
const HLS_MAX_RETRIES = 3
let speedTimer = null
let preSpeed = 1.0
const speeds = ['0.5×', '0.75×', '1.0×', '1.25×', '1.5×', '2.0×']
let progressTimer = null
let hideTimer = null
let loadTimer = null

// A3: 浏览器无法解码、需给出明确提示（而非静默黑屏）的容器格式
const UNSUPPORTED_FORMAT_NAMES = {
  avi: 'AVI', wmv: 'WMV', flv: 'FLV', rmvb: 'RMVB', rm: 'RM',
  mpg: 'MPEG', mpeg: 'MPEG', vob: 'VOB', '3gp': '3GP', asf: 'ASF'
}

function urlExt(u) {
  try {
    const p = String(u || '').split('?')[0]
    const i = p.lastIndexOf('.')
    return i >= 0 ? p.slice(i + 1).toLowerCase() : ''
  } catch { return '' }
}

// 统一销毁当前解码引擎（hls.js / mpegts.js），顺序遵循各官方文档
function destroyEngine() {
  if (hls) {
    try { hls.destroy() } catch { /* ignore */ }
    hls = null
  }
  if (mpegtsPlayer) {
    try {
      mpegtsPlayer.pause()
      mpegtsPlayer.unload()
      mpegtsPlayer.detachMediaElement()
      mpegtsPlayer.destroy()
    } catch { /* ignore */ }
    mpegtsPlayer = null
  }
}

function resetVideoEl(el) {
  el.removeEventListener('error', onNonHlsError)
  el.pause()
  el.src = ''
  el.load()
}

// --- Probe logic ---
async function startProbe() {
  probeState.value = 'probing'
  playError.value = ''
  try {
    const data = await store.probePlay(props.targetId, props.targetType)
    if (data.error) {
      errorMsg.value = data.error
      probeState.value = 'error'
      return
    }
    const all = data.all || []
    if (!all.length && data.primary) {
      all.push(data.primary)
    }
    lineList.value = all
    currentLine.value = data.primary || all[0] || null
    if (!currentLine.value) {
      errorMsg.value = '没有可用播放线路'
      probeState.value = 'error'
      return
    }
    await startPlay(currentLine.value)
  } catch (e) {
    errorMsg.value = '测速失败：' + (e.message || '网络错误')
    probeState.value = 'error'
  }
}

async function startPlay(line) {
  currentLine.value = line
  playError.value = ''

  // Page URL: resolve through fresh-url first
  if (line.url_type === 'page') {
    probeState.value = 'resolving'
    try {
      const fresh = await store.fetchFreshUrl(line.url)
      if (fresh.url) {
        line = { ...line, url: fresh.url, url_type: 'stream' }
      } else {
        playError.value = '页面源解析失败：' + (fresh.error || '无法获取真实地址')
        probeState.value = 'ready'
        return
      }
    } catch (e) {
      playError.value = '页面源解析失败：' + (e.message || '网络错误')
      probeState.value = 'ready'
      return
    }
  }

  probeState.value = 'ready'
  loading.value = true
  // 站点代理规则命中的线路：经后端 /api/proxy 中转（后端已按规则判定 proxied）
  let playUrl = line.url
  if (line.proxied) playUrl = `/api/proxy?url=${encodeURIComponent(line.url)}`
  await loadVideo(playUrl)
}

// P2-1: 非 HLS 分支的 error 监听器用具名函数，可摘除、天然去重
// A3: 按 MediaError 错误码给出明确、可行动的错误提示，而非静默黑屏
function onNonHlsError() {
  const el = videoEl.value
  const code = el && el.error ? el.error.code : 0
  const msgs = {
    1: '视频加载已中止',
    2: '网络错误：视频下载中断，请检查网络后重试',
    3: '解码失败：视频编码不受当前浏览器支持（建议 H.264/AAC 编码的 MP4）',
    4: '格式不支持或地址不可用'
  }
  playError.value = (msgs[code] || '视频加载失败（无法解码或地址不可用）')
  loading.value = false
}

async function selectLine(line) {
  // Destroy old player
  destroyEngine()
  const el = videoEl.value
  if (el) {
    // P2-1: 换源清空 src 前先摘掉 error 监听器，避免空源 error 触发虚假错误提示
    resetVideoEl(el)
  }
  playing.value = false
  await startPlay(line)
}

function showLineSelector() {
  probeState.value = 'selecting'
  playError.value = ''
}

function retryProbe() {
  destroyEngine()
  const el = videoEl.value
  if (el) {
    // P2-1: 清空 src 前先摘掉 error 监听器
    resetVideoEl(el)
  }
  playing.value = false
  startProbe()
}

async function loadVideo(playUrl) {
  const el = videoEl.value
  if (!el || !playUrl) return

  // P2-1: 每次 loadVideo 先移除旧监听器，避免多次换线后监听器累积
  el.removeEventListener('error', onNonHlsError)
  hlsNetRetries = 0
  hlsMediaRetries = 0
  clearTimeout(loadTimer)

  function seekInit() {
    loading.value = false
    if (props.initialProgress > 0 && el.duration) {
      el.currentTime = props.initialProgress * el.duration
    }
    // A3：有上次进度时暂停并弹出续看提示，由用户决定续看或从头播
    if (resumePending.value) {
      resumeAsk.value = true
      return
    }
    el.play().then(() => { playing.value = true }).catch(() => {})
  }

  // A3: 按扩展名做格式路由——m3u8 走 hls.js，ts 走 mpegts.js（点播），其余走原生；
  // 浏览器普遍不支持的容器格式直接给出友好提示，避免静默黑屏
  const ext = urlExt(playUrl)
  if (UNSUPPORTED_FORMAT_NAMES[ext]) {
    loading.value = false
    playError.value = `暂不支持 ${UNSUPPORTED_FORMAT_NAMES[ext]} 格式在线播放，建议转码为 MP4（H.264/AAC）后重新下载，或使用本地播放器打开`
    return
  }
  const isHls = ext === 'm3u8' || playUrl.includes('.m3u8')
  const isTs = ext === 'ts'
  if (Hls.isSupported() && isHls) {
    hls = new Hls()
    hls.loadSource(playUrl)
    hls.attachMedia(el)
    hls.on(Hls.Events.MANIFEST_PARSED, seekInit)
    hls.on(Hls.Events.ERROR, (_evt, data) => {
      if (!data || !data.fatal) return
      // P2-3: 按官方错误恢复矩阵有限重试，多次失败才报错
      if (data.type === Hls.ErrorTypes.NETWORK_ERROR && hlsNetRetries < HLS_MAX_RETRIES) {
        hlsNetRetries += 1
        hls.startLoad()
        return
      }
      if (data.type === Hls.ErrorTypes.MEDIA_ERROR && hlsMediaRetries < HLS_MAX_RETRIES) {
        hlsMediaRetries += 1
        hls.recoverMediaError()
        return
      }
      const msg = data.response?.code === 403
        ? '播放地址被拒绝（403），可能是代理/CDN 需要更高权限'
        : data.response?.code
          ? `加载失败（HTTP ${data.response.code}）`
          : '视频加载失败'
      playError.value = msg
      loading.value = false
    })
  } else if (isTs && mpegts && mpegts.isSupported()) {
    // A3: TS 点播走 mpegts.js 软解（isLive:false），直播/点播同一套底层库
    mpegtsPlayer = mpegts.createPlayer({
      type: 'mpegts',
      isLive: false,
      url: playUrl
    }, {
      enableWorker: true,
      lazyLoad: true,
      lazyLoadMaxDuration: 3 * 60
    })
    mpegtsPlayer.attachMediaElement(el)
    mpegtsPlayer.load()
    mpegtsPlayer.on(mpegts.Events.ERROR, (errType, errDetail) => {
      // 与 hls/native 分支统一的错误出口
      playError.value = `TS 视频加载失败（${errType}）：${errDetail || '未知错误'}`
      loading.value = false
    })
    // loadedmetadata 后走与其它分支一致的 seek/续看逻辑
    el.addEventListener('loadedmetadata', seekInit, { once: true })
    loadTimer = setTimeout(() => {
      if (loading.value && el.readyState < 1) {
        playError.value = '视频加载超时，请检查网络或重试'
        loading.value = false
      }
    }, 15000)
  } else {
    el.src = playUrl
    el.addEventListener('loadedmetadata', seekInit, { once: true })
    // P2-1: 具名监听器，配合 loadVideo 开头的 removeEventListener 防累积
    el.addEventListener('error', onNonHlsError)
    loadTimer = setTimeout(() => {
      if (loading.value && el.readyState < 1) {
        playError.value = '视频加载超时，请检查网络或重试'
        loading.value = false
      }
    }, 15000)
  }
}

// --- Touch interaction ---
let lastTouchZones = { left: 0, right: 0 }
let touchStartX = 0
let touchStartY = 0
let touchMoved = false
const SWIPE_THRESHOLD = 30

function onTouchStart(e) {
  const t = e.touches[0]
  touchStartX = t.clientX
  touchStartY = t.clientY
  touchMoved = false
  clearTimeout(speedTimer)
  speedTimer = setTimeout(() => {
    if (!playing.value) return
    isSpeeding.value = true
    const el = videoEl.value
    if (el) { preSpeed = el.playbackRate; el.playbackRate = 2.0 }
  }, 600)
}

function onTouchMove(e) {
  if (!e.touches.length) return
  const t = e.touches[0]
  const dx = t.clientX - touchStartX
  const dy = t.clientY - touchStartY
  if (Math.abs(dx) < SWIPE_THRESHOLD && Math.abs(dy) < SWIPE_THRESHOLD) return
  clearTimeout(speedTimer)
  touchMoved = true
  if (Math.abs(dx) > Math.abs(dy)) {
    e.preventDefault()
    const rect = videoWrap.value?.getBoundingClientRect()
    if (!rect) return
    const pct = Math.max(0, Math.min(100, ((t.clientX - rect.left) / rect.width) * 100))
    dragPct.value = pct
    dragActive.value = true
  }
}

function onTouchEnd(e) {
  clearTimeout(speedTimer)
  if (isSpeeding.value) {
    isSpeeding.value = false
    if (videoEl.value) videoEl.value.playbackRate = preSpeed
    return
  }
  if (touchMoved) {
    if (dragActive.value) {
      dragActive.value = false
      const el = videoEl.value
      if (el && el.duration) el.currentTime = (dragPct.value / 100) * el.duration
    }
    return
  }
  const rect = videoWrap.value?.getBoundingClientRect()
  if (!rect) return
  const pctX = (touchStartX - rect.left) / rect.width
  const zone = pctX < 0.35 ? 'left' : pctX > 0.65 ? 'right' : null
  if (!zone) { onTapVideo(); return }
  const now = Date.now()
  if (now - lastTouchZones[zone] < 350) {
    lastTouchZones[zone] = 0
    const sec = zone === 'left' ? -10 : 10
    seekBy(sec)
    showSeekHint(sec, zone === 'left' ? 15 : 85)
    showControlsTemporarily()
    return
  }
  lastTouchZones[zone] = now
}

let _moveHandler = null
let _upHandler = null

function onLoadedMeta() {
  const el = videoEl.value
  if (!el) return
  duration.value = fmt(el.duration)
  updateBuffer()
}
function onEnded() { playing.value = false }
function onWaiting() { loading.value = true }
function onPlaying() { loading.value = false }
function onCanplay() { loading.value = false }

onMounted(async () => {
  containerEl.value?.focus()
  // B: 本地离线内容直接播放模式——跳过测速选线，按扩展名选引擎直接起播
  if (props.localUrl) {
    probeState.value = 'ready'
    loadVideo(props.localUrl)
  } else {
    await startProbe()
  }

  // M2：触屏设备首次打开播放器时显示 3 秒双击手势引导（仅一次）
  try {
    const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0
    const seen = localStorage.getItem('suenplayer-gesture-guide') === '1'
    if (isTouch && !seen) {
      localStorage.setItem('suenplayer-gesture-guide', '1')
      gestureGuide.value = true
      setTimeout(() => { gestureGuide.value = false }, 3000)
    }
  } catch {}

  const el = videoEl.value
  if (!el) return
  el.addEventListener('timeupdate', updateTime)
  el.addEventListener('progress', updateBuffer)
  el.addEventListener('loadedmetadata', onLoadedMeta)
  el.addEventListener('ended', onEnded)
  el.addEventListener('waiting', onWaiting)
  el.addEventListener('playing', onPlaying)
  el.addEventListener('canplay', onCanplay)

  document.addEventListener('keydown', onKey)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  document.addEventListener('webkitfullscreenchange', onFullscreenChange)
  progressTimer = setInterval(reportProgress, 10000)
  scheduleHideControls()
})

onBeforeUnmount(() => {
  // A1: hls/mpegts/原生三套引擎统一由 destroyEngine 销毁，防泄漏
  destroyEngine()
  clearInterval(progressTimer)
  clearTimeout(hideTimer)
  clearTimeout(speedTimer)
  clearTimeout(loadTimer)
  reportProgress()
  const el = videoEl.value
  if (el) {
    el.removeEventListener('timeupdate', updateTime)
    el.removeEventListener('progress', updateBuffer)
    el.removeEventListener('loadedmetadata', onLoadedMeta)
    el.removeEventListener('ended', onEnded)
    el.removeEventListener('waiting', onWaiting)
    el.removeEventListener('playing', onPlaying)
    el.removeEventListener('canplay', onCanplay)
  }
  document.removeEventListener('keydown', onKey)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  document.removeEventListener('webkitfullscreenchange', onFullscreenChange)
  if (_moveHandler) document.removeEventListener('mousemove', _moveHandler)
  if (_upHandler) document.removeEventListener('mouseup', _upHandler)
  if (_moveHandler) document.removeEventListener('touchmove', _moveHandler)
  if (_upHandler) document.removeEventListener('touchend', _upHandler)
})

function reportProgress() {
  // B: 本地离线内容不走在线进度上报（无 targetId）
  if (props.localUrl) return
  const el = videoEl.value
  if (!el || !el.duration) return
  emit('progress', { targetId: props.targetId, targetType: props.targetType, progress: el.currentTime / el.duration })
}

function togglePlay() {
  const el = videoEl.value
  if (!el) return
  if (el.paused) {
    // P2-2: 不丢弃 play() 的 Promise，按真实结果更新播放状态
    el.play().then(() => { playing.value = true }).catch(() => {
      playing.value = false
      loading.value = false
    })
  } else {
    el.pause()
    playing.value = false
  }
  showControlsTemporarily()
}

// A3：续看提示选择
function chooseResume(resume) {
  resumeAsk.value = false
  resumePending.value = false
  const el = videoEl.value
  if (!el) return
  if (!resume) el.currentTime = 0
  el.play().then(() => { playing.value = true }).catch(() => {})
}

function onTapVideo() {
  if (dragActive.value) return
  if (showControls.value) hideControls()
  else showControlsTemporarily()
}

function showSeekHint(sec, x) {
  seekHint.value = { show: true, dir: sec > 0 ? '+' : '', sec: Math.abs(sec), x: Math.max(5, Math.min(95, x)) }
  setTimeout(() => seekHint.value.show = false, 600)
}

function updateTime() {
  const el = videoEl.value
  if (!el || dragActive.value) return
  currentTime.value = fmt(el.currentTime)
  progress.value = el.duration ? (el.currentTime / el.duration) * 100 : 0
}

function updateBuffer() {
  const el = videoEl.value
  if (!el || !el.duration || !el.buffered.length) return
  const end = el.buffered.end(el.buffered.length - 1)
  buffered.value = (end / el.duration) * 100
}

function startDrag(e) {
  dragActive.value = true
  updateDrag(e)
  _moveHandler = (ev) => { requestAnimationFrame(() => updateDrag(ev)) }
  _upHandler = (ev) => {
    dragActive.value = false
    document.removeEventListener('mousemove', _moveHandler)
    document.removeEventListener('mouseup', _upHandler)
    document.removeEventListener('touchmove', _moveHandler)
    document.removeEventListener('touchend', _upHandler)
    _moveHandler = null; _upHandler = null
    seekToDrag(ev)
  }
  document.addEventListener('mousemove', _moveHandler)
  document.addEventListener('mouseup', _upHandler)
  document.addEventListener('touchmove', _moveHandler, { passive: false })
  document.addEventListener('touchend', _upHandler)
}

function updateDrag(e) {
  const bar = progressBar.value
  if (!bar) return
  const touch = e.touches ? e.touches[0] : e
  const rect = bar.getBoundingClientRect()
  const pct = Math.max(0, Math.min(100, ((touch.clientX - rect.left) / rect.width) * 100))
  dragPct.value = pct
}

function seekToDrag(e) {
  const el = videoEl.value
  if (!el || !el.duration) return
  el.currentTime = (dragPct.value / 100) * el.duration
  progress.value = dragPct.value
  currentTime.value = fmt(el.currentTime)
}

function onProgressMove(e) {
  const bar = progressBar.value
  if (!bar || !videoEl.value?.duration) { tooltipSec.value = null; return }
  const rect = bar.getBoundingClientRect()
  const pct = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100))
  tooltipPct.value = pct
  const sec = Math.floor((pct / 100) * videoEl.value.duration)
  tooltipSec.value = fmt(sec)
}

function toggleMute() {
  const el = videoEl.value
  if (!el) return
  el.muted = !el.muted
  muted.value = el.muted
  showControlsTemporarily()
}

function onVolInput(e) {
  const el = videoEl.value
  if (!el) return
  const v = parseFloat(e.target.value)
  el.volume = v
  volLevel.value = v
  el.muted = v === 0
  muted.value = el.muted
}

function toggleFullscreen() {
  const el = containerEl.value || videoWrap.value
  if (!el) return
  if (document.fullscreenElement || document.webkitFullscreenElement) {
    const exitFS = document.exitFullscreen || document.webkitExitFullscreen
    if (exitFS) exitFS.call(document)
    if (screen.orientation?.unlock) screen.orientation.unlock()
  } else {
    const requestFS = el.requestFullscreen || el.webkitRequestFullscreen || el.webkitEnterFullscreen
    if (requestFS) requestFS.call(el)
    if (screen.orientation?.lock) screen.orientation.lock('landscape').catch(() => {})
  }
  showControlsTemporarily()
}

function onFullscreenChange() {
  isFullscreen.value = !!(document.fullscreenElement || document.webkitFullscreenElement)
}

function cycleSpeed() {
  const el = videoEl.value
  if (!el) return
  const idx = speeds.indexOf(speed.value)
  const next = (idx + 1) % speeds.length
  speed.value = speeds[next]
  el.playbackRate = parseFloat(speed.value)
  showControlsTemporarily()
}

function showControlsTemporarily() {
  showControls.value = true
  clearTimeout(hideTimer)
  scheduleHideControls()
}

function scheduleHideControls() {
  clearTimeout(hideTimer)
  if (!playing.value) return
  // D1：窗口模式与全屏模式均支持控制条自动隐藏（鼠标移开隐藏、移入显示）
  hideTimer = setTimeout(() => {
    if (playing.value && !dragActive.value) showControls.value = false
  }, 6000)
}

function hideControls() {
  showControls.value = false
  clearTimeout(hideTimer)
}

function onKey(e) {
  if (containerEl.value && document.activeElement !== containerEl.value && !containerEl.value?.contains(document.activeElement)) return
  if (e.key === 'Escape') emit('close')
  if (e.key === ' ') { e.preventDefault(); togglePlay() }
  if (e.key === 'ArrowLeft') { seekBy(-10); showControlsTemporarily() }
  if (e.key === 'ArrowRight') { seekBy(10); showControlsTemporarily() }
  // A2: 对齐主流播放器键盘习惯——上下调音量、F 全屏、M 静音
  if (e.key === 'ArrowUp') { e.preventDefault(); adjustVolume(0.1) }
  if (e.key === 'ArrowDown') { e.preventDefault(); adjustVolume(-0.1) }
  if (e.key === 'f' || e.key === 'F') toggleFullscreen()
  if (e.key === 'm' || e.key === 'M') toggleMute()
}

// A2: 统一音量步进入口（键盘上下键），同步音量图标状态
function adjustVolume(delta) {
  const el = videoEl.value
  if (!el) return
  el.volume = Math.max(0, Math.min(1, el.volume + delta))
  volLevel.value = el.volume
  if (delta > 0 && el.volume > 0 && el.muted) { el.muted = false; muted.value = false }
  showControlsTemporarily()
}

// A2: 桌面双击切换全屏（主流习惯）；触屏设备保留单击切控制条 + 双击手势快进，避免冲突
function onDblClick() {
  if ('ontouchstart' in window || navigator.maxTouchPoints > 0) return
  toggleFullscreen()
}

function onWheel(e) {
  const el = videoEl.value
  if (!el) return
  if (e.shiftKey) {
    const delta = e.deltaY > 0 ? 10 : -10
    seekBy(delta)
    showSeekHint(delta, progress.value + (delta > 0 ? 5 : -5))
    showControlsTemporarily()
  } else {
    const delta = e.deltaY > 0 ? -0.05 : 0.05
    el.volume = Math.max(0, Math.min(1, el.volume + delta))
    volLevel.value = el.volume
    if (el.volume > 0 && el.muted) { el.muted = false; muted.value = false }
    showControlsTemporarily()
  }
}

function seekBy(seconds) {
  const el = videoEl.value
  if (!el || !el.duration) return
  el.currentTime = Math.max(0, Math.min(el.duration, el.currentTime + seconds))
}

function fmt(t) {
  if (!t || isNaN(t)) return '0:00'
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const s = Math.floor(t % 60).toString().padStart(2, '0')
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s}`
  return `${m}:${s}`
}
</script>

<style scoped>
.player-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 300;
  display: flex; align-items: center; justify-content: center;
}
.cursor-none { cursor: none; }
.player-container {
  width: 100%; height: 100%; max-width: 100%; max-height: 100%;
  display: flex; flex-direction: column; outline: none;
}
.player-top {
  display: flex; justify-content: space-between; align-items: center;
  padding: var(--space-2) var(--space-4) var(--space-2) 72px; flex-shrink: 0;
}
.player-title {
  font-size: var(--text-md); color: var(--text-secondary); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; flex: 1; margin-right: 12px;
}
.player-close {
  font-size: var(--text-3xl); color: var(--text-inverse); background: none; border: none; cursor: pointer;
  width: 36px; height: 36px; display: flex; align-items: center; justify-content: center;
}
/* 常驻关闭按钮：半透明底、文字标识，控制条隐藏时也可见 */
.player-close-floating {
  position: absolute; top: 10px; left: 12px; z-index: 30;
  width: auto; padding: 0 12px; height: 32px; gap: 6px;
  display: flex; align-items: center;
  background: rgba(0, 0, 0, 0.55); border-radius: 16px;
  color: #fff; font-size: var(--text-sm); font-weight: 600;
  transition: background .15s;
}
.player-close-floating:hover { background: rgba(0, 0, 0, 0.8); }

/* Probe / Line overlays */
.probe-overlay {
  position: absolute; inset: 0; z-index: 10;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.6);
}
.probe-panel {
  background: var(--panel); border-radius: var(--radius-lg); padding: 32px;
  display: flex; flex-direction: column; align-items: center; gap: 12px;
  min-width: 280px; max-width: 90vw;
}
.probe-text { color: var(--text-primary); font-size: var(--text-xl); font-weight: 600; }
.probe-sub { color: var(--text-muted); font-size: var(--text-base); }

.line-panel {
  background: var(--panel); border-radius: var(--radius-lg); padding: 24px;
  width: 480px; max-width: 90vw; max-height: 80vh; overflow-y: auto;
}
.line-title { font-size: var(--text-xl); font-weight: 600; color: var(--text-primary); margin-bottom: 16px; }
.line-list { display: flex; flex-direction: column; gap: 8px; }
.line-item {
  display: flex; align-items: center; gap: 10px; padding: 12px;
  border-radius: var(--radius-md); background: var(--bg-input); cursor: pointer;
  transition: background .15s;
}
.line-item:hover { background: var(--recessed); }
.line-item.primary { border: 1px solid var(--accent); }
.line-badge {
  font-size: var(--text-xs); color: var(--text-inverse); background: var(--accent);
  border-radius: var(--radius-sm); padding: 2px 6px; white-space: nowrap;
}
.line-badge.page-badge { background: var(--info); }
.line-source { font-weight: 600; color: var(--text-primary); }
.line-label { font-size: var(--text-sm); color: var(--text-secondary); }
.line-res { font-size: var(--text-sm); color: var(--text-muted); }
.line-score { font-size: var(--text-sm); color: var(--success); margin-left: auto; }
.line-latency { font-size: var(--text-sm); color: var(--text-muted); }

.player-video-wrap {
  position: relative; flex: 1; min-height: 0; background: var(--recessed); box-shadow: var(--shadow-recessed); border-radius: var(--radius-md); overflow: hidden;
  display: flex; align-items: center; justify-content: center;
}
.touch-zone { position: absolute; top: 0; bottom: 0; width: 40%; z-index: 2; }
.touch-zone-left { left: 0; }
.touch-zone-right { right: 0; }
.player-video { width: 100%; height: 100%; display: block; object-fit: contain; }
.player-big-play {
  position: absolute; inset: 0; display: flex;
  align-items: center; justify-content: center; pointer-events: none;
}
.big-play-btn { pointer-events: auto; display: flex; cursor: pointer; }
.big-play-btn svg { width: 72px; height: 72px; border-radius: 36px; background: rgba(0,0,0,0.55); padding: var(--space-4); transition: transform 0.2s; }
.big-play-btn svg:hover { transform: scale(1.1); }
.player-loading { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: none; }
.player-error { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; background: var(--surface-overlay); z-index: 5; }
.player-error-text { color: var(--text-inverse); font-size: var(--text-lg); text-align: center; padding: 0 32px; max-width: 480px; line-height: 1.5; }
.player-error-btn { padding: 8px 24px; border-radius: 18px; border: none; background: var(--accent); color: var(--text-inverse); font-size: var(--text-md); cursor: pointer; }
.player-error-btn.btn-secondary { background: var(--panel); color: var(--text-primary); }
.spinner { width: 40px; height: 40px; border: 3px solid rgba(255,255,255,0.2); border-top-color: var(--text-inverse); border-radius: var(--radius-full); animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.seek-hint { position: absolute; bottom: 20%; z-index: 3; transform: translateX(-50%); background: rgba(0,0,0,0.45); border-radius: var(--radius-md); padding: var(--space-2) var(--space-4); pointer-events: none; }
.seek-hint-text { color: var(--text-inverse); font-size: var(--text-lg); font-family: var(--font-mono); }
.speed-hint { position: absolute; top: 15%; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.45); border-radius: var(--radius-xl); padding: var(--space-2) var(--space-4); z-index: 10; pointer-events: none; display: flex; align-items: center; backdrop-filter: blur(4px); }
.speed-hint-text { color: var(--text-inverse); font-size: var(--text-md); font-weight: 500; }
.player-controls {
  padding: 8px 16px 12px; flex-shrink: 0;
  background: linear-gradient(transparent, rgba(0,0,0,0.72) 55%, rgba(0,0,0,0.85));
  backdrop-filter: blur(6px);
}
.player-controls button { color: rgba(255,255,255,0.92); border-radius: var(--radius-sm); transition: background .15s, color .15s; }
.player-controls button:hover { color: #fff; background: rgba(255,255,255,0.14); }
.pc-progress { height: 20px; position: relative; cursor: pointer; display: flex; align-items: center; touch-action: none; }
.pc-progress::before { content: ''; position: absolute; left: 0; right: 0; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.25); }
.pc-progress-buffer { position: absolute; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.35); z-index: 0; }
.pc-progress-fill { position: absolute; height: 4px; border-radius: 2px; background: var(--accent); z-index: 1; transition: none; }
.pc-progress-dot { position: absolute; width: 16px; height: 16px; border-radius: var(--radius-full); background: var(--accent); transform: translateX(-50%); z-index: 2; box-shadow: 0 0 4px rgba(0,0,0,0.4); transition: none; }
.pc-tooltip { position: absolute; bottom: 100%; transform: translateX(-50%); background: rgba(0,0,0,0.8); color: var(--text-inverse); font-size: var(--text-sm); padding: 2px 6px; border-radius: var(--radius-sm); white-space: nowrap; font-family: var(--font-mono); margin-bottom: 4px; pointer-events: none; }
.pc-row { display: flex; justify-content: space-between; align-items: center; height: 40px; }
.pc-left, .pc-right { display: flex; align-items: center; gap: var(--space-3); }
.pc-left button, .pc-right button { width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; background: none; border: none; cursor: pointer; padding: 0; }
.time-text { font-family: var(--font-mono); font-size: var(--text-base); color: var(--text-inverse); }
.speed-btn { font-size: var(--text-base); color: var(--text-inverse); font-family: var(--font-mono); width: auto !important; padding: 0 8px !important; }
.line-btn { font-size: var(--text-base); color: rgba(255,255,255,0.95) !important; width: auto !important; padding: 0 10px !important; height: 32px; border: 1px solid rgba(255,255,255,0.28); border-radius: var(--radius-full); display: inline-flex; align-items: center; gap: 5px; background: rgba(255,255,255,0.08); }
.line-btn-text { max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--text-sm); font-weight: 700; color: #fff; }
.vol-wrap { display: flex; align-items: center; gap: var(--space-2); }
.vol-slider { width: 60px; height: 4px; cursor: pointer; accent-color: var(--text-inverse); background: transparent; border-radius: 2px; }

/* A3 续看提示 */
.resume-overlay { z-index: 12; }
.resume-actions { display: flex; gap: 12px; margin-top: 6px; }

/* M2 手势引导 */
.gesture-guide {
  position: absolute; inset: 0; z-index: 12;
  display: flex; align-items: center; justify-content: center;
  pointer-events: none;
}
.gesture-guide-card {
  background: rgba(0,0,0,0.65); border-radius: var(--radius-lg);
  padding: 20px 28px; display: flex; flex-direction: column; gap: 10px;
  animation: gestureFade 3s ease forwards;
}
.gesture-guide-row { display: flex; align-items: center; gap: 10px; color: var(--text-inverse); font-size: var(--text-md); }
.gesture-side { font-weight: 600; color: var(--accent); }
@keyframes gestureFade {
  0% { opacity: 0; transform: scale(0.96); }
  8% { opacity: 1; transform: scale(1); }
  85% { opacity: 1; }
  100% { opacity: 0; }
}

@media (max-width: 640px) {
  .player-controls { padding: 4px 12px 8px; }
  .pc-progress { height: 28px; }
  .pc-progress-dot { width: 20px; height: 20px; }
  .pc-row { height: 36px; gap: 4px; }
  .pc-left, .pc-right { gap: var(--space-2); }
  .pc-left button, .pc-right button { width: 44px; height: 44px; padding: 10px; }
  .time-text { font-size: var(--text-sm); }
  .touch-zone { width: 35%; }
  .line-panel { width: calc(100vw - 24px); padding: 16px; }
}
</style>
