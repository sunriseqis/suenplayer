<template>
  <div class="live-view">
    <div class="page-inner">
      <h2 class="page-title">直播</h2>
      <div class="live-layout">
        <!-- 分组侧栏 -->
        <aside class="group-side">
          <button v-for="g in groups" :key="g.name"
                  class="group-item" :class="{ active: g.name === activeGroup }"
                  @click="selectGroup(g.name)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="4" width="20" height="14" rx="2"/><path d="M8 21h8"/></svg>
            <span class="group-name">{{ g.name }}</span>
            <span class="group-count">{{ g.count }}</span>
          </button>
          <div class="group-empty" v-if="!groups.length && !loading">暂无直播频道，请管理员导入直播源</div>
        </aside>

        <!-- 频道列表 + 播放器 -->
        <main class="live-main">
          <div class="player-box" v-if="currentChannel" ref="playerBoxEl"
               @mousemove="onPlayerMouseMove" @mouseleave="onPlayerMouseLeave">
            <video ref="videoEl" class="live-video" playsinline autoplay
                   @play="onVideoPlay" @pause="onVideoPause" @volumechange="onVolumeChange"
                   @click="onVideoClick" @dblclick="onVideoDblClick"></video>

            <!-- 浮动状态显示（不拦截点击，避免挡住下层交互） -->
            <div class="player-status-badge" v-if="statusText">{{ statusText }}</div>

            <!-- 内嵌直播场景定制控制栏（A1: JS 驱动显隐，修复全屏下永久隐藏的层级 bug） -->
            <div class="live-controls-overlay" :class="{ 'controls-hidden': !controlsVisible }">
              <div class="ctrl-left">
                <button class="ctrl-btn" @click="togglePlay" :title="playing ? '暂停' : '播放'">
                  <svg v-if="!playing" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                  <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
                </button>
                <button class="ctrl-btn" @click="reconnectStream" title="重新连接 / 刷新流">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                </button>
                <div class="volume-group">
                  <button class="ctrl-btn" @click="toggleMute" :title="isMuted ? '取消静音' : '静音'">
                    <svg v-if="isMuted || volume === 0" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>
                    <svg v-else-if="volume < 0.5" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M18.5 12c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM5 9v6h4l5 5V4L9 9H5z"/></svg>
                    <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L9 9H5zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
                  </button>
                  <input type="range" min="0" max="1" step="0.05" :value="isMuted ? 0 : volume" @input="onVolumeInput" class="volume-slider" />
                </div>
              </div>
              <div class="ctrl-right">
                <span class="live-indicator"><span class="dot"></span>直播中</span>
                <button class="ctrl-btn" @click="toggleFullscreen" title="全屏">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
                </button>
              </div>
            </div>

            <!-- 点击中央主播放/未连通兜底按钮 -->
            <div class="player-fallback" v-if="!playing && !statusText" @click="playCurrent">
              <button class="play-btn">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
              </button>
            </div>
          </div>

          <div class="channel-head" v-if="currentChannel">
            <div class="ch-info">
              <div class="ch-name">{{ currentChannel.name }}</div>
              <div class="ch-meta" v-if="currentSource">
                源 {{ sourceIdx + 1 }}/{{ currentChannel.sources?.length || 0 }}
                <template v-if="currentSource.isp"> · {{ currentSource.isp }}</template>
                <template v-if="currentSource.node_ip"> · 节点 {{ maskIp(currentSource.node_ip) }}</template>
                <template v-if="currentSource.speed_mbps != null"> · {{ currentSource.speed_mbps }} Mbps</template>
                <template v-if="currentSource.delay_ms != null"> · {{ currentSource.delay_ms }} ms</template>
              </div>
            </div>
            <!-- 多源手动切换：固定位于左侧，向右自然展开 -->
            <div class="source-list" v-if="(currentChannel.sources?.length || 0) > 1">
              <span class="source-label">线路切换：</span>
              <button v-for="(s, i) in currentChannel.sources" :key="s.id"
                      class="source-chip" :class="{ active: i === sourceIdx, failed: failedIds.has(s.id) }"
                      @click="switchSource(i)">
                源{{ i + 1 }}
                <span class="src-quality" v-if="failedIds.has(s.id)">失败</span>
                <span class="src-quality" v-else-if="s.delay_ms != null">{{ s.delay_ms }}ms</span>
              </button>
            </div>
          </div>

          <div class="channel-grid" v-if="channels.length">
            <button v-for="c in channels" :key="c.id"
                    class="channel-card" :class="{ active: currentChannel?.id === c.id }"
                    @click="playChannel(c)">
              <img class="ch-logo" :src="proxyLogo(c.logo_url)" v-if="c.logo_url" />
              <div class="ch-logo-ph" v-else>{{ c.name?.slice(0, 2) }}</div>
              <div class="ch-card-name">{{ c.name }}</div>
            </button>
          </div>
          <div class="empty-inline" v-else-if="!loading && activeGroup">该分组暂无频道</div>
        </main>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount, onActivated, onDeactivated } from 'vue'
import { useAppStore } from '../stores/app.js'
import { useUiStore } from '../stores/ui.js'
// 解码引擎按需加载：仅在真正起播直播流时才动态引入 hls.js / mpegts.js
let Hls = null
let mpegts = null

defineOptions({ name: 'LiveView' })

const store = useAppStore()
const ui = useUiStore()

const groups = ref([])
const channels = ref([])
const activeGroup = ref('')
const currentChannel = ref(null)
const sourceIdx = ref(0)
const playing = ref(false)
const statusText = ref('')
const videoEl = ref(null)
const playerBoxEl = ref(null)
const loading = ref(true)

const volume = ref(1)
const isMuted = ref(false)

// A1/A2: 控制条显隐由 JS 驱动（原 CSS :fullscreen .player-box:hover 规则在
// player-box 自身为全屏元素时永不匹配，导致全屏时控制条永久消失）
const controlsVisible = ref(true)
let controlsHideTimer = null
const CONTROLS_HIDE_DELAY_MS = 4000
// A2: 键盘快捷键只在直播页激活时生效（keep-alive 下切页后按键不串扰）
let isActivePage = true

function isTouchDevice() {
  return 'ontouchstart' in window || navigator.maxTouchPoints > 0
}

function showLiveControls() {
  controlsVisible.value = true
  clearTimeout(controlsHideTimer)
  scheduleHideLiveControls()
}

function scheduleHideLiveControls() {
  clearTimeout(controlsHideTimer)
  if (!playing.value) return
  controlsHideTimer = setTimeout(() => { controlsVisible.value = false }, CONTROLS_HIDE_DELAY_MS)
}

function onPlayerMouseMove() {
  showLiveControls()
}

function onPlayerMouseLeave() {
  if (playing.value) {
    clearTimeout(controlsHideTimer)
    controlsHideTimer = setTimeout(() => { controlsVisible.value = false }, CONTROLS_HIDE_DELAY_MS)
  }
}

// A2: 桌面单击切播放/暂停（主流习惯）；触屏单击切控制条显隐（避免误触暂停）
function onVideoClick() {
  if (isTouchDevice()) {
    if (controlsVisible.value) {
      clearTimeout(controlsHideTimer)
      controlsVisible.value = false
    } else {
      showLiveControls()
    }
    return
  }
  togglePlay()
  showLiveControls()
}

// A2: 桌面双击切全屏；触屏保留双击未来扩展（当前无绑定手势，直接忽略防冲突）
function onVideoDblClick() {
  if (isTouchDevice()) return
  toggleFullscreen()
}

// A2: 对齐主流播放器键盘习惯（空格播放/暂停、F 全屏、M 静音、上下调音量）；
// 输入框聚焦时不拦截；仅在本页激活时响应
function onLiveKey(e) {
  if (!isActivePage) return
  const tag = (document.activeElement?.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return
  if (!currentChannel.value) return
  if (e.key === ' ') { e.preventDefault(); togglePlay(); showLiveControls() }
  else if (e.key === 'f' || e.key === 'F') toggleFullscreen()
  else if (e.key === 'm' || e.key === 'M') toggleMute()
  else if (e.key === 'ArrowUp') { e.preventDefault(); adjustLiveVolume(0.05) }
  else if (e.key === 'ArrowDown') { e.preventDefault(); adjustLiveVolume(-0.05) }
}

function adjustLiveVolume(delta) {
  const video = videoEl.value
  if (!video) return
  video.volume = Math.max(0, Math.min(1, video.volume + delta))
  volume.value = video.volume
  if (delta > 0 && video.volume > 0 && video.muted) {
    video.muted = false
    isMuted.value = false
  }
  showLiveControls()
}

let hls = null
let mpegtsPlayer = null
let switchLock = false
const failedIds = ref(new Set())
// 起播超时 30s： udpxy/上游会话常有慢启动爬坡（先十几KB/s 再到 Mbps 级），
// 短超时会把慢源误判失效。超时后不再自动换源，只提示用户手动更换线路。
const PLAY_TIMEOUT_MS = 30000

// P2-3: hls.js fatal 错误按官方恢复矩阵有限重试（每源重置计数）
let hlsNetRetries = 0
let hlsMediaRetries = 0
const HLS_MAX_RETRIES = 3

// P2-4: 起播成功后断流感知与自动重连（带退避，避免重试风暴）
let reconnectTimer = null
let reconnectAttempts = 0
let dropGuard = false
let stallTimer = null
const MAX_RECONNECT_ATTEMPTS = 6
const STALL_GRACE_MS = 8000

// P2-5: 分组切换竞态保护：只接受最后一次请求的响应
let groupSeq = 0

// P2-7: 无 MSE 环境判断已由解码引擎按需加载取代，删除原静态 hasMseSupport/isNoMseEnv 死代码

const currentSource = computed(() => {
  return currentChannel.value?.sources?.[sourceIdx.value] || null
})

function maskIp(ip) {
  if (!ip) return ''
  const parts = String(ip).split('.')
  if (parts.length === 4) return `${parts[0]}.${parts[1]}.***.${parts[3]}`
  return String(ip).slice(0, 4) + '***'
}

function getToken() {
  return localStorage.getItem('suen_token') || ''
}

// 将 logo URL 通过服务端代理，解决浏览器无法直接访问局域网地址的问题
function proxyLogo(url) {
  if (!url) return ''
  const token = getToken()
  return `/api/live/logo?url=${encodeURIComponent(url)}&token=${encodeURIComponent(token)}`
}

async function loadGroups() {
  loading.value = true
  try {
    const list = await store.fetchLiveGroups()
    groups.value = Array.isArray(list) ? list : (list.groups || [])
    if (groups.value.length && !activeGroup.value) {
      await selectGroup(groups.value[0].name)
    }
  } catch (e) {
    ui.toast(e.message || '直播分组加载失败', 'error')
  }
  loading.value = false
}

async function selectGroup(name) {
  activeGroup.value = name
  // P2-5: 自增序号防竞态——慢响应不得覆盖新分组的列表
  const mySeq = ++groupSeq
  try {
    const list = await store.fetchLiveChannels(name)
    if (mySeq !== groupSeq) return
    channels.value = Array.isArray(list) ? list : (list.channels || [])
    // 首次进入自动起播第一个频道，避免空黑屏
    if (channels.value.length && !currentChannel.value) {
      if (mySeq !== groupSeq) return
      await playChannel(channels.value[0])
    }
  } catch {
    if (mySeq === groupSeq) channels.value = []
  }
}

async function playChannel(c) {
  try {
    const ch = await store.fetchLiveChannel(c.id)
    currentChannel.value = ch
    failedIds.value = new Set()
    reconnectAttempts = 0
    const validSources = ch.sources || []
    // 优先选择默认源且未超时的正常源；若默认源已知超时则优先选其他健康源
    let bestIdx = validSources.findIndex(s => s.is_default && (s.fail_count || 0) < 3 && s.probe_status !== 'timeout')
    if (bestIdx < 0) {
      bestIdx = validSources.findIndex(s => (s.fail_count || 0) < 3 && s.probe_status !== 'timeout')
    }
    if (bestIdx < 0) {
      bestIdx = validSources.findIndex(s => s.is_default)
    }
    if (bestIdx < 0 && validSources.length) {
      bestIdx = 0
    }
    sourceIdx.value = Math.max(0, bestIdx)
    // 等待 v-if="currentChannel" 的播放器 DOM 渲染完成，否则 videoEl 为 null，
    // 首次起播必然以 "no video element" 瞬时失败
    await nextTick()
    await playCurrent()
  } catch (e) {
    ui.toast(e.message || '频道加载失败', 'error')
  }
}

async function playCurrent() {
  const ch = currentChannel.value
  const src = ch?.sources?.[sourceIdx.value]
  if (!ch || !src) return
  if (switchLock) return
  switchLock = true
  statusText.value = '连接中…'
  playing.value = false
  let ok = false
  let errMsg = ''
  try {
    await openStream(src.url)
    ok = true
    statusText.value = ''
  } catch (e) {
    errMsg = (e && e.message) || '播放失败'
    console.error('[live] playCurrent failed:', errMsg)
    playing.value = false
    statusText.value = ''
  } finally {
    switchLock = false
  }
  if (ok) return
  // 失败只标记该源并提示用户手动换线，绝不自动切换：
  // 慢启动源（先十几KB/s 爬坡）不因超时被"烧掉"，由用户决定是否更换
  failedIds.value = new Set([...failedIds.value, src.id])
  if (errMsg.startsWith('移动端暂不支持')) {
    ui.toast(errMsg, 'error')
  } else if (errMsg.includes('timeout')) {
    ui.toast(`源${sourceIdx.value + 1}连接缓慢或无画面（30秒未出图），建议手动更换线路`, 'info', 8000)
  } else {
    ui.toast(`源${sourceIdx.value + 1}播放失败：${errMsg}，建议手动更换线路`, 'error', 6000)
  }
}

// P2-4: 断流处理——展示"信号中断"并按指数退避自动重连，重试次数封顶
function handleStreamDrop(reason) {
  if (dropGuard) return
  if (!currentChannel.value) return
  dropGuard = true
  playing.value = false
  destroyPlayer()
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    statusText.value = '信号中断，自动重连失败，请手动点击重连'
    return
  }
  statusText.value = '信号中断，正在自动重连…'
  const delay = Math.min(15000, 1000 * (2 ** reconnectAttempts))
  reconnectAttempts += 1
  reconnectTimer = setTimeout(() => { autoReconnect(reason) }, delay)
}

async function autoReconnect() {
  dropGuard = false
  await playCurrent()
  if (!playing.value && currentChannel.value) {
    // 本轮重连未成功，按退避继续下一轮（受最大重试次数限制）
    handleStreamDrop('reconnect failed')
  }
}

function clearReconnectTimers() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (stallTimer) { clearTimeout(stallTimer); stallTimer = null }
}

// P2-4: 起播成功后挂长期监听（video 元素级：ended / stalled / error）
function armLiveMonitors() {
  const video = videoEl.value
  if (!video) return
  video.addEventListener('ended', onLiveEnded)
  video.addEventListener('stalled', onLiveStalled)
  video.addEventListener('error', onLiveElemError)
}

function onLiveEnded() { handleStreamDrop('stream ended') }

function onLiveElemError() { handleStreamDrop('stream error') }

function onLiveStalled() {
  if (stallTimer) clearTimeout(stallTimer)
  stallTimer = setTimeout(() => {
    const video = videoEl.value
    // stalled 后长时间仍无有效缓冲数据，判定为断流
    if (video && video.readyState < 3 && playing.value) handleStreamDrop('stream stalled')
  }, STALL_GRACE_MS)
}

async function reconnectStream() {
  ui.toast('正在重新连接直播流…', 'info')
  await playCurrent()
}

async function ensureEngines() {
  if (!Hls) Hls = (await import('hls.js')).default
  if (!mpegts) mpegts = (await import('mpegts.js')).default
}

function openStream(url) {
  const video = videoEl.value
  if (!video) return Promise.reject(new Error('no video element'))
  return ensureEngines().then(() => new Promise((resolve, reject) => {
    destroyPlayer()
    // P2-3: 每次起播重置 hls.js fatal 恢复计数
    hlsNetRetries = 0
    hlsMediaRetries = 0

    let settled = false
    let timer = null
    const cleanup = () => {
      if (timer) { clearTimeout(timer); timer = null }
      video.onplaying = null
      video.oncanplay = null
      video.onerror = null
    }
    const ok = () => { if (!settled) { settled = true; cleanup(); armLiveMonitors(); resolve() } }
    const fail = (err) => { if (!settled) { settled = true; cleanup(); reject(err instanceof Error ? err : new Error(String(err || 'stream error'))) } }
    const armTimeout = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => fail(new Error('stream timeout')), PLAY_TIMEOUT_MS)
    }
    video.onplaying = ok
    video.onerror = () => fail(new Error('stream error'))

    const token = getToken()

    const baseUrl = String(url || '').split('?')[0]
    const isHls = /\.m3u8/i.test(baseUrl)

    if (Hls && Hls.isSupported() && isHls) {
      armTimeout()
      hls = new Hls({
        xhrSetup: (xhr) => {
          if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
        }
      })
      hls.loadSource(url)
      hls.attachMedia(video)
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().then(() => {}).catch(() => fail(new Error('play rejected')))
      })
      hls.on(Hls.Events.ERROR, (_e, data) => {
        if (!data || !data.fatal) return
        // P2-3: 按官方错误恢复矩阵有限重试，而不是一次抖动就烧源
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR && hlsNetRetries < HLS_MAX_RETRIES) {
          hlsNetRetries += 1
          armTimeout()
          hls.startLoad()
          return
        }
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR && hlsMediaRetries < HLS_MAX_RETRIES) {
          hlsMediaRetries += 1
          armTimeout()
          hls.recoverMediaError()
          return
        }
        fail(new Error('hls stream error'))
      })
    } else if (mpegts && mpegts.isSupported()) {
      // 通过服务端代理流转，解决浏览器无法直接访问内网/局域网直播源的问题
      // 后端已改用 async httpx 64KB chunk，性能接近直连
      const ch = currentChannel.value
      const src = ch?.sources?.[sourceIdx.value]
      const token = getToken()
      const rawStreamUrl = (ch && src)
        ? `/api/live/stream/${ch.id}/${src.id}`
        : `/api/live/stream?url=${encodeURIComponent(url)}`
      const streamUrl = rawStreamUrl.includes('?')
        ? `${rawStreamUrl}&token=${encodeURIComponent(token)}`
        : `${rawStreamUrl}?token=${encodeURIComponent(token)}`

      // enableWorker 时 mpegts.js 在 Web Worker 内 fetch，Worker 中不允许相对 URL
      // （Failed to parse URL），必须先展开为绝对地址
      const absoluteStreamUrl = new URL(streamUrl, window.location.origin).href

      armTimeout()
      try {
        mpegtsPlayer = mpegts.createPlayer({
          type: 'mpegts',
          isLive: true,
          url: absoluteStreamUrl,
          cors: true,
          withCredentials: true,
        }, {
          enableWorker: true,
          lazyLoad: false,
          liveBufferLatencyChasing: true,
          liveBufferLatencyMaxLatency: 1.5,
          liveBufferLatencyMinRemain: 0.2,
        })
        mpegtsPlayer.attachMediaElement(video)
        mpegtsPlayer.load()
        video.oncanplay = ok
        video.onplaying = ok
        mpegtsPlayer.play().catch(() => {})
        mpegtsPlayer.on(mpegts.Events.ERROR, (errorType, detail) => {
          const err = new Error(`mpegts error: ${errorType} - ${detail}`)
          if (!settled) fail(err)
          else handleStreamDrop(err.message)
        })
      } catch (err) {
        fail(err)
      }
    } else if (isHls) {
      // P2-7: 无 MSE 环境（iOS Safari 原生 HLS）——HLS 源改走服务端代理，
      // iOS 原生播放器可直接播代理地址；带 token 规避 401
      armTimeout()
      const chM = currentChannel.value
      const srcM = chM?.sources?.[sourceIdx.value]
      let playUrl = url
      if (chM && srcM) {
        const rawProxy = `/api/live/stream/${chM.id}/${srcM.id}`
        playUrl = rawProxy.includes('?')
          ? `${rawProxy}&token=${encodeURIComponent(token)}`
          : `${rawProxy}?token=${encodeURIComponent(token)}`
      }
      video.src = playUrl
      video.oncanplay = () => {
        video.oncanplay = null
        const tryPlay = (muted) => {
          if (muted) { video.muted = true; isMuted.value = true }
          video.play().then(() => {}).catch(() => {
            if (!muted) { tryPlay(true); return }
            fail(new Error('play rejected'))
          })
        }
        tryPlay(false)
      }
    } else {
      // P2-7: 无 MSE 且非 HLS（TS 等）——明确提示，不再烧源
      fail(new Error('移动端暂不支持该直播源格式（TS），请使用 HLS(m3u8) 源或桌面浏览器'))
    }
  }))
}

function destroyPlayer() {
  clearReconnectTimers()
  dropGuard = false
  const video = videoEl.value
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
  if (video) {
    video.onplaying = null
    video.oncanplay = null
    video.onerror = null
    video.removeEventListener('ended', onLiveEnded)
    video.removeEventListener('stalled', onLiveStalled)
    video.removeEventListener('error', onLiveElemError)
    try { video.pause() } catch { /* ignore */ }
    try { video.removeAttribute('src'); video.load() } catch { /* ignore */ }
  }
}

async function switchSource(i) {
  const ch = currentChannel.value
  if (!ch || i === sourceIdx.value) return
  sourceIdx.value = i
  try {
    await store.switchLiveSource(ch.id, ch.sources[i].id).catch(() => {})
  } catch { /* ignore */ }
  await nextTick()
  // 手动切换不做激进自动换源：失败只标记该源并提示，由用户自行选择其他线路，
  // 避免一次点击触发整条 fallback 链把源逐个试穿
  await playCurrent()
}

function togglePlay() {
  const video = videoEl.value
  if (!video) return
  if (video.paused) {
    video.play()
  } else {
    video.pause()
  }
}

function onVideoPlay() {
  playing.value = true
  statusText.value = ''
  // A1: 起播后开始自动隐藏控制条
  scheduleHideLiveControls()
}
function onVideoPause() {
  playing.value = false
  // A2: 暂停时控制条常显（主流习惯），避免暂停后找不到播放按钮
  clearTimeout(controlsHideTimer)
  controlsVisible.value = true
}

function toggleMute() {
  const video = videoEl.value
  if (!video) return
  video.muted = !video.muted
  isMuted.value = video.muted
}

function onVolumeInput(e) {
  const val = parseFloat(e.target.value)
  const video = videoEl.value
  if (!video) return
  video.volume = val
  volume.value = val
  if (val > 0 && video.muted) {
    video.muted = false
    isMuted.value = false
  }
}

function onVolumeChange() {
  const video = videoEl.value
  if (!video) return
  volume.value = video.volume
  isMuted.value = video.muted
}

function toggleFullscreen() {
  const box = playerBoxEl.value || videoEl.value
  if (!box) return
  if (!document.fullscreenElement) {
    if (box.requestFullscreen) box.requestFullscreen()
    else if (box.webkitRequestFullscreen) box.webkitRequestFullscreen()
  } else {
    if (document.exitFullscreen) document.exitFullscreen()
    else if (document.webkitExitFullscreen) document.webkitExitFullscreen()
  }
}

onMounted(() => {
  loadGroups()
  // A2: 键盘快捷键（组件内维护激活标志，keep-alive 下切页自动失效）
  document.addEventListener('keydown', onLiveKey)
})

// App.vue 的 keep-alive 名单包含 LiveView：切走页面时 onBeforeUnmount 不会触发，
// 必须在 onDeactivated 销毁播放器，否则直播流在后台持续拉取
onDeactivated(() => {
  isActivePage = false
  clearTimeout(controlsHideTimer)
  destroyPlayer()
  playing.value = false
  statusText.value = ''
})

// 回到直播页：播放器已在离开时销毁，按 mpegts.js 官方顺序释放后可重新初始化起播
onActivated(() => {
  isActivePage = true
  controlsVisible.value = true
  reconnectAttempts = 0
  if (currentChannel.value) {
    nextTick(() => { playCurrent() })
  }
})

onBeforeUnmount(() => {
  isActivePage = false
  document.removeEventListener('keydown', onLiveKey)
  clearTimeout(controlsHideTimer)
  destroyPlayer()
})
</script>

<style scoped>
.live-view { display: flex; justify-content: center; padding-bottom: 40px; }
.page-inner { width: 100%; max-width: 1440px; padding: 20px 24px 0; }
.page-title { margin: 0 0 16px; font-size: var(--text-2xl); color: var(--text-primary); }

.live-layout { display: flex; gap: 18px; align-items: flex-start; }
.group-side {
  width: 190px; flex: none; display: flex; flex-direction: column; gap: 4px;
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: var(--radius-md); padding: 10px;
  position: sticky; top: 70px; max-height: calc(100vh - 100px); overflow-y: auto;
}
.group-item {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 10px; border-radius: var(--radius-sm); border: none;
  background: none; color: var(--text-secondary); font-size: var(--text-base); cursor: pointer; text-align: left;
}
.group-item:hover { background: var(--bg-input); color: var(--text-primary); }
.group-item.active { background: var(--accent); color: var(--text-inverse); font-weight: 600; }
.group-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.group-count { font-size: var(--text-xs); opacity: 0.8; font-family: var(--font-mono); }
.group-empty { padding: 14px 8px; font-size: var(--text-sm); color: var(--text-muted); line-height: 1.6; }

.live-main { flex: 1; min-width: 0; }
.player-box {
  position: relative; width: 100%; aspect-ratio: 16/9;
  background: #000; border-radius: var(--radius-md); overflow: hidden; margin-bottom: 12px;
}
.live-video { width: 100%; height: 100%; object-fit: contain; display: block; }

.player-status-badge {
  position: absolute; top: 12px; left: 12px; padding: 5px 14px;
  border-radius: 99px; background: rgba(0,0,0,0.65); color: #fff; font-size: var(--text-sm);
  backdrop-filter: blur(4px); z-index: 5;
  /* A1: 纯状态展示不拦截点击，避免挡住下层 video 交互 */
  pointer-events: none;
}

.player-fallback {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  cursor: pointer; z-index: 4;
}
.play-btn {
  width: 64px; height: 64px; border-radius: 50%; border: none; cursor: pointer;
  background: rgba(255,255,255,0.18); color: #fff;
  display: flex; align-items: center; justify-content: center;
  backdrop-filter: blur(4px); transition: background var(--duration-fast);
}
.play-btn:hover { background: var(--accent); }

/* 直播专用定制控制栏 overlay */
.live-controls-overlay {
  position: absolute; bottom: 0; left: 0; right: 0;
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 14px; background: linear-gradient(to top, rgba(0,0,0,0.85), transparent);
  color: #fff; z-index: 10; transition: opacity 0.25s ease;
  opacity: 1;
}
/* A1: 控制条显隐统一由 JS 驱动（controlsVisible）。
   旧规则 `:fullscreen .player-box:hover .live-controls-overlay` 在 player-box 自身
   即全屏元素时永不匹配（:fullscreen 的后代选择器以视口为根），导致全屏时控制条永久消失 */
.live-controls-overlay.controls-hidden {
  opacity: 0; pointer-events: none;
}

.ctrl-left, .ctrl-right { display: flex; align-items: center; gap: 10px; }
.ctrl-btn {
  background: none; border: none; color: #fff; cursor: pointer;
  padding: 6px; border-radius: var(--radius-sm); display: flex; align-items: center; justify-content: center;
  opacity: 0.85; transition: opacity var(--duration-fast), background var(--duration-fast);
}
.ctrl-btn:hover { opacity: 1; background: rgba(255,255,255,0.15); }

.volume-group { display: flex; align-items: center; gap: 6px; }
.volume-slider {
  width: 70px; height: 4px; accent-color: var(--accent); cursor: pointer;
}

.live-indicator {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--text-xs); font-weight: 700; color: #ef4444; text-transform: uppercase;
  background: rgba(0,0,0,0.4); padding: 3px 8px; border-radius: 99px;
}
.live-indicator .dot {
  width: 6px; height: 6px; border-radius: 50%; background: #ef4444;
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.3; }
  100% { opacity: 1; }
}

.channel-head {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 14px;
}
.ch-info {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
.ch-name { font-size: var(--text-xl); font-weight: 600; color: var(--text-primary); }
.ch-meta { font-size: var(--text-sm); color: var(--text-muted); font-family: var(--font-mono); }
.source-list {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}
.source-label {
  font-size: var(--text-sm);
  color: var(--text-muted);
  font-weight: 500;
  flex-shrink: 0;
}
.source-chip {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 12px; border-radius: 99px; border: 1px solid var(--border-light);
  background: var(--bg-input); color: var(--text-secondary); font-size: var(--text-sm); cursor: pointer;
}
.source-chip:hover { border-color: var(--accent); color: var(--text-primary); }
.source-chip.active { background: var(--accent); color: var(--text-inverse); border-color: var(--accent); font-weight: 600; }
.source-chip.failed { opacity: 0.55; text-decoration: line-through; }
.source-chip.failed.active { text-decoration: none; }
.src-quality { font-size: var(--text-xs); opacity: 0.85; font-family: var(--font-mono); }

.channel-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px;
}
.channel-card {
  display: flex; align-items: center; gap: 10px; padding: 10px;
  border: 1px solid var(--border-light); border-radius: var(--radius-md);
  background: var(--bg-card); cursor: pointer; text-align: left;
}
.channel-card:hover { border-color: var(--accent); }
.channel-card.active { border-color: var(--accent); background: var(--bg-input); }
.ch-logo { width: 44px; height: 30px; object-fit: contain; border-radius: var(--radius-sm); flex: none; }
.ch-logo-ph {
  width: 44px; height: 30px; border-radius: var(--radius-sm); flex: none;
  background: linear-gradient(135deg, var(--recessed), var(--deep-shadow));
  display: flex; align-items: center; justify-content: center;
  font-size: var(--text-sm); font-weight: 700; color: var(--text-muted);
}
.ch-card-name { font-size: var(--text-base); color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.empty-inline { padding: 40px 0; text-align: center; color: var(--text-muted); }

@media (max-width: 900px) {
  .live-layout { flex-direction: column; }
  .group-side { width: 100%; position: static; max-height: none; flex-direction: row; flex-wrap: wrap; }
  .group-item { width: auto; }
}
@media (max-width: 640px) {
  .page-inner { padding: 14px 12px 0; }
  .channel-grid { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); }
  .live-controls-overlay { opacity: 1; padding: 6px 10px; }
  .volume-slider { width: 50px; }
}
</style>