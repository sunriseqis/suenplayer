import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const API = '/api'

export function imgUrl(src) {
  if (!src) return ''
  if (src.startsWith('http')) return `${API}/cache/${encodeURIComponent(src)}`
  return src
}

export function authFetch(url, options = {}) {
  const token = localStorage.getItem('suen_token')
  const headers = new Headers(options.headers || {})
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  return fetch(url, { ...options, headers, credentials: 'include' })
}

async function jfetch(url, options = {}) {
  const r = await authFetch(url, options)
  let data = null
  try { data = await r.json() } catch { /* empty body */ }
  if (!r.ok) {
    // token 过期/无效（401）：清空本地登录态并跳转登录页，
    // 避免错误体 {"error":"凭证无效或已过期"} 被调用方当数据消费造成全站静默空白
    if (r.status === 401) onAuthExpired()
    const err = new Error((data && (data.error || data.detail)) || `请求失败（HTTP ${r.status}）`)
    err.status = r.status
    err.data = data
    throw err
  }
  return data
}

// ─── 全局 401 处理 ────────────────────────────────────────
// appStoreRef 在 store 首次实例化时回填（模块级函数无法直接拿 pinia 实例）
let appStoreRef = null
let redirectingLogin = false
function onAuthExpired() {
  if (appStoreRef) appStoreRef.logoutLocal()
  if (redirectingLogin) return
  if (typeof window === 'undefined') return
  if (window.location.pathname.startsWith('/login')) return
  redirectingLogin = true
  const redirect = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.assign(`/login?redirect=${redirect}`)
}

function jbody(method, payload) {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }
}

export const useAppStore = defineStore('app', () => {
  const settings = ref({ proxy: '', proxy_sources: {}, site_name: 'suenplayer' })
  const _loggedIn = ref(false)
  const isLoggedIn = computed(() => _loggedIn.value)
  const siteName = computed(() => settings.value?.site_name || 'suenplayer')

  // ─── 当前用户与权限 ─────────────────────────────────────
  const currentUser = ref(null) // { id, username, display_name, role }
  const isAdmin = computed(() => currentUser.value?.role === 'admin')
  const projects = ref([]) // 当前账号可见项目
  const activeProjects = computed(() => projects.value.filter(p => (p.item_count ?? 1) > 0))
  const liveCount = ref(0)
  const hasLive = computed(() => liveCount.value > 0)
  const appVersion = ref('') // 读后端 APP_VERSION（stats 接口），前端不自造
  const mustChangePassword = ref(false)

  async function fetchLiveCount() {
    try {
      const d = await jfetch(`${API}/live/count`)
      liveCount.value = typeof d?.count === 'number' ? d.count : 0
    } catch {
      liveCount.value = 0
    }
    return liveCount.value
  }

  async function checkAuth() {
    try {
      const token = localStorage.getItem('suen_token')
      const headers = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`
      const r = await fetch(`${API}/auth/verify`, {
        headers,
        credentials: 'include'
      })
      const data = await r.json()
      _loggedIn.value = !!data.ok
      if (data.ok) {
        try { currentUser.value = await jfetch(`${API}/auth/me`) } catch { currentUser.value = null }
        mustChangePassword.value = !!(currentUser.value && currentUser.value.must_change_password)
        await Promise.all([fetchProjects(), fetchLiveCount()])
      } else {
        currentUser.value = null
        localStorage.removeItem('suen_token')
      }
    } catch {
      _loggedIn.value = false
      currentUser.value = null
    }
  }

  async function login(username, password) {
    const r = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    })
    const data = await r.json().catch(() => ({}))
    if (r.ok && data.token) {
      localStorage.setItem('suen_token', data.token)
      _loggedIn.value = true
      try { currentUser.value = await jfetch(`${API}/auth/me`) } catch { currentUser.value = data.user || null }
      mustChangePassword.value = !!(currentUser.value && currentUser.value.must_change_password)
      await Promise.all([fetchProjects(), fetchLiveCount()])
      return { ok: true }
    }
    if (data.status === 'pending') return { ok: false, pending: true, error: data.error || '账号待管理员批准' }
    if (data.status === 'rejected') return { ok: false, rejected: true, error: data.error || '账号已被管理员拒绝' }
    return { ok: false, error: data.error || '登录失败' }
  }

  async function register(username, password, displayName = '') {
    const r = await fetch(`${API}/auth/register`, jbody('POST', { username, password, display_name: displayName }))
    const data = await r.json().catch(() => ({}))
    if (r.ok) return { ok: true, message: data.message || '已提交，等待管理员批准' }
    return { ok: false, error: data.error || '注册失败' }
  }

  async function logout() {
    try { await authFetch(`${API}/auth/logout`, { method: 'POST' }) } catch { /* ignore */ }
    localStorage.removeItem('suen_token')
    _loggedIn.value = false
    currentUser.value = null
    projects.value = []
    liveCount.value = 0
    mustChangePassword.value = false
  }

  // 仅清理本地登录态（不发请求）。供全局 401 处理调用，也回填模块级 appStoreRef
  function logoutLocal() {
    localStorage.removeItem('suen_token')
    _loggedIn.value = false
    currentUser.value = null
    projects.value = []
    liveCount.value = 0
    mustChangePassword.value = false
  }
  appStoreRef = { logoutLocal }

  async function changeUsername(newUsername) {
    const d = await jfetch(`${API}/auth/username`, jbody('POST', { new_username: newUsername }))
    if (currentUser.value) currentUser.value.username = d.username || newUsername
    return d
  }

  async function changePassword(oldPassword, newPassword) {
    return jfetch(`${API}/auth/password`, jbody('POST', { old_password: oldPassword, new_password: newPassword }))
  }

  function completeOnboarding() {
    mustChangePassword.value = false
    if (currentUser.value) currentUser.value.must_change_password = false
  }

  // ─── 项目（可见性由后端按账号过滤） ─────────────────────
  async function fetchProjects() {
    try {
      const d = await jfetch(`${API}/projects`)
      projects.value = Array.isArray(d) ? d : []
    } catch { projects.value = [] }
    return projects.value
  }

  // ─── 最近更新 ───────────────────────────────────────────
  async function fetchRecentUpdates(page = 1, limit = 60, project = '') {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) })
    // 后端支持 project 过滤（项目名称或 slug），由服务端完成过滤与鉴权
    if (project) params.set('project', project)
    return jfetch(`${API}/recent-updates?${params.toString()}`)
  }

  // ─── Videos & Series ───────────────────────────────────
  // 以下封装统一走 jfetch（检查 r.ok、401 触发全局登出），不再把错误体当数据返回
  async function fetchVideos(params = {}) {
    const q = new URLSearchParams(params).toString()
    return jfetch(`${API}/videos?${q}`)
  }

  async function fetchSeries(params = {}) {
    const q = new URLSearchParams(params).toString()
    return jfetch(`${API}/series?${q}`)
  }

  async function fetchVideo(bangou) {
    return jfetch(`${API}/videos/${bangou}`)
  }

  async function fetchSeriesDetail(seriesId) {
    return jfetch(`${API}/series/${seriesId}`)
  }

  async function fetchEpisodeDetail(episodeId) {
    return jfetch(`${API}/episodes/${episodeId}`)
  }

  // ─── Play & Probe ──────────────────────────────────────
  async function probePlay(targetId, targetType = 'video') {
    return jfetch(`${API}/play/probe?target_id=${targetId}&target_type=${targetType}`)
  }

  async function switchPlayLine(targetId, targetType, url) {
    return jfetch(`${API}/play/switch`, jbody('POST', { target_id: targetId, target_type: targetType, url }))
  }

  async function fetchFreshUrl(url) {
    return jfetch(`${API}/fresh-url?url=${encodeURIComponent(url)}`)
  }

  async function createDownload(payload) {
    return jfetch(`${API}/download`, jbody('POST', payload))
  }

  async function fetchUrls(targetId, targetType = 'video') {
    return jfetch(`${API}/urls?target_id=${targetId}&target_type=${targetType}`)
  }

  async function getPlayUrl(video) {
    if (!video) return ''
    if (video.url) return video.url
    const urls = await fetchUrls(video.target_id || video.id, video.target_type || 'video')
    const arr = Array.isArray(urls) ? urls : []
    const stream = arr.find(u => u.url_type === 'stream') || arr[0]
    return stream?.url || ''
  }

  // ─── 直播（IPTV，独立于影视库） ─────────────────────────
  async function fetchLiveGroups() {
    const d = await jfetch(`${API}/live/groups`)
    return d.groups || []
  }

  async function fetchLiveChannels(group = '', region = '') {
    const q = new URLSearchParams({ ...(group ? { group } : {}), ...(region ? { region } : {}) }).toString()
    const d = await jfetch(`${API}/live/channels${q ? '?' + q : ''}`)
    return d.channels || []
  }

  async function fetchLiveChannel(channelId) {
    return jfetch(`${API}/live/channels/${channelId}`)
  }

  async function switchLiveSource(channelId, sourceId) {
    const d = await jfetch(`${API}/live/channels/${channelId}/switch`, jbody('POST', { source_id: sourceId }))
    return d.channel
  }

  async function nextLiveSource(channelId) {
    return jfetch(`${API}/live/channels/${channelId}/next-source`, { method: 'POST' })
  }

  // ─── Categories ────────────────────────────────────────
  async function fetchCategoryTree() {
    return jfetch(`${API}/categories`)
  }

  async function createCategory(name, parentId = null, projectId = null) {
    const payload = { name, parent_id: parentId }
    if (projectId) payload.project_id = projectId
    const r = await authFetch(`${API}/categories`, jbody('POST', payload))
    return r.json()
  }

  async function updateCategory(id, name) {
    const r = await authFetch(`${API}/categories/${id}`, jbody('PATCH', { name }))
    return r.json()
  }

  async function deleteCategory(id) {
    const r = await authFetch(`${API}/categories/${id}`, { method: 'DELETE' })
    return r.json()
  }

  async function reorderCategories(orders) {
    const r = await authFetch(`${API}/categories/reorder`, jbody('PATCH', { orders }))
    return r.json()
  }

  async function normalizeCategoryOrder() {
    const r = await authFetch(`${API}/categories/reorder/normalize`, { method: 'POST' })
    return r.json()
  }

  // ─── Favorites ─────────────────────────────────────────
  async function fetchFavorites() {
    const r = await authFetch(`${API}/favorites`)
    return r.json()
  }

  async function addFavorite(targetType, targetId) {
    const r = await authFetch(`${API}/favorites`, jbody('POST', { target_type: targetType, target_id: targetId }))
    return r.json()
  }

  async function removeFavorite(favId) {
    const r = await authFetch(`${API}/favorites/${favId}`, { method: 'DELETE' })
    return r.json()
  }

  async function checkFav(targetType, targetId) {
    try {
      const list = await fetchFavorites()
      const arr = Array.isArray(list) ? list : (list.items || [])
      return arr.some(f => f.target_type === targetType && f.target_id === targetId)
    } catch { return false }
  }

  async function toggleFav(targetType, targetId) {
    const exists = await checkFav(targetType, targetId)
    if (exists) {
      const list = await fetchFavorites()
      const arr = Array.isArray(list) ? list : (list.items || [])
      const found = arr.find(f => f.target_type === targetType && f.target_id === targetId)
      if (found) await removeFavorite(found.id)
      return false
    }
    await addFavorite(targetType, targetId)
    return true
  }

  // ─── History ───────────────────────────────────────────
  async function fetchHistory() {
    const r = await authFetch(`${API}/history`)
    return r.json()
  }

  async function addHistory(targetType, targetId, progress = 0) {
    await authFetch(`${API}/history`, jbody('POST', { target_type: targetType, target_id: targetId, progress }))
  }

  async function clearHistory() {
    await authFetch(`${API}/history`, { method: 'DELETE' })
  }

  async function deleteHistoryItem(id) {
    await authFetch(`${API}/history/${id}`, { method: 'DELETE' })
  }

  async function batchDeleteHistory(ids) {
    await authFetch(`${API}/history/batch-delete`, jbody('POST', { ids }))
  }

  // ─── 统计 / 版本 ────────────────────────────────────────
  async function fetchStats() {
    const d = await jfetch(`${API}/stats`)
    if (d?.app_version) appVersion.value = d.app_version
    return d
  }

  // ─── 整理工具链（合并/转移/去重/元数据覆盖/规则） ────────
  async function mergeVideos(payload) {
    return jfetch(`${API}/videos/merge`, jbody('POST', payload))
  }

  async function transferVideos(payload) {
    return jfetch(`${API}/videos/transfer`, jbody('POST', payload))
  }

  async function setDedup(bangou, payload) {
    return jfetch(`${API}/videos/${encodeURIComponent(bangou)}/dedup`, jbody('PUT', payload))
  }

  async function removeDedup(bangou, projectId = null) {
    const q = projectId ? `?project_id=${projectId}` : ''
    return jfetch(`${API}/videos/${encodeURIComponent(bangou)}/dedup${q}`, { method: 'DELETE' })
  }

  async function dedupInfo(bangou, projectId) {
    return jfetch(`${API}/videos/${encodeURIComponent(bangou)}/dedup-info?project_id=${projectId}`)
  }

  async function fetchOverrides(projectId = 1) {
    return jfetch(`${API}/videos/overrides?project_id=${projectId}`)
  }

  async function putOverrides(payload) {
    return jfetch(`${API}/videos/overrides`, jbody('PUT', payload))
  }

  async function setVideoTags(bangou, tags, projectId) {
    return jfetch(`${API}/videos/${encodeURIComponent(bangou)}/tags`, jbody('PUT', { tags, project_id: projectId }))
  }

  async function setVideoCategory(bangou, region, group, projectId) {
    return jfetch(`${API}/videos/${encodeURIComponent(bangou)}/category`, jbody('PUT', { region, group, project_id: projectId }))
  }

  async function fetchRules(projectId = null) {
    const q = projectId ? `?project_id=${projectId}` : ''
    const d = await jfetch(`${API}/rules${q}`)
    return d.rules || []
  }

  async function deleteRule(id) {
    return jfetch(`${API}/rules/${id}`, { method: 'DELETE' })
  }

  // ─── 管理端：账号 / 审批 / 权限 / 项目 ──────────────────
  async function fetchAdminUsers() {
    return jfetch(`${API}/admin/users`)
  }

  async function createAdminUser(payload) {
    return jfetch(`${API}/admin/users`, jbody('POST', payload))
  }

  async function updateAdminUser(userId, payload) {
    return jfetch(`${API}/admin/users/${userId}`, jbody('PATCH', payload))
  }

  async function deleteAdminUser(userId) {
    return jfetch(`${API}/admin/users/${userId}`, { method: 'DELETE' })
  }

  async function fetchPendingUsers() {
    const d = await jfetch(`${API}/admin/pending-users`)
    return d.users || []
  }

  async function approveUser(userId) {
    return jfetch(`${API}/admin/users/${userId}/approve`, { method: 'POST' })
  }

  async function rejectUser(userId) {
    return jfetch(`${API}/admin/users/${userId}/reject`, { method: 'POST' })
  }

  async function fetchUserProjects(userId) {
    const d = await jfetch(`${API}/admin/users/${userId}/projects`)
    return d.projects || []
  }

  async function assignUserProjects(userId, projectIds) {
    return jfetch(`${API}/admin/users/${userId}/projects`, jbody('POST', { project_ids: projectIds }))
  }

  async function fetchAdminProjects() {
    return jfetch(`${API}/admin/projects`)
  }

  async function createProject(payload) {
    return jfetch(`${API}/admin/projects`, jbody('POST', payload))
  }

  async function updateProject(projectId, payload) {
    return jfetch(`${API}/admin/projects/${projectId}`, jbody('PATCH', payload))
  }

  async function deleteProject(projectId) {
    return jfetch(`${API}/admin/projects/${projectId}`, { method: 'DELETE' })
  }

  // ─── 管理端：自动更新 ───────────────────────────────────
  async function fetchProxyCandidates() {
    return jfetch(`${API}/admin/proxy-candidates`)
  }

  async function fetchAutoUpdates() {
    const d = await jfetch(`${API}/admin/auto-update`)
    return d.configs || []
  }

  async function createAutoUpdate(payload) {
    return jfetch(`${API}/admin/auto-update`, jbody('POST', payload))
  }

  async function updateAutoUpdate(configId, payload) {
    return jfetch(`${API}/admin/auto-update/${configId}`, jbody('PATCH', payload))
  }

  async function deleteAutoUpdate(configId, purgeData = false) {
    const q = purgeData ? '?purge_data=true' : ''
    return jfetch(`${API}/admin/auto-update/${configId}${q}`, { method: 'DELETE' })
  }

  async function triggerAutoUpdate(configId) {
    return jfetch(`${API}/admin/auto-update/${configId}/trigger`, { method: 'POST' })
  }

  async function fetchAutoUpdateLogs(configId, limit = 20) {
    const d = await jfetch(`${API}/admin/auto-update/${configId}/logs?limit=${limit}`)
    return d.logs || []
  }

  // ─── 管理端：设置 / 导入 / 直播源 ───────────────────────
  async function fetchAdminSettings() {
    return jfetch(`${API}/admin/settings`)
  }

  async function putAdminSettings(payload) {
    const d = await jfetch(`${API}/admin/settings`, jbody('PUT', payload))
    if (d?.settings) settings.value = d.settings
    return d
  }

  async function importRemote(payload) {
    const res = await jfetch(`${API}/import/remote`, jbody('POST', payload))
    await Promise.all([fetchProjects(), fetchLiveCount()]).catch(() => {})
    return res
  }

  // 导入拉取预览（admin，只读分析，不写库不导入）
  async function importRemotePreview(payload) {
    return jfetch(`${API}/import/remote/preview`, jbody('POST', payload))
  }

  async function importLiveAdmin(path) {
    const res = await jfetch(`${API}/admin/live/import`, jbody('POST', { path }))
    await fetchLiveCount().catch(() => {})
    return res
  }

  // ─── 下载 ──────────────────────────────────────────────
  async function downloadApi(url, options = {}) {
    return authFetch(url, options)
  }

  // ─── 多选状态（项目页整理工具） ─────────────────────────
  const editMode = ref(false)
  const selected = ref([])
  const selectedSet = computed(() => new Set(selected.value.map(v => v.bangou)))

  function isSelected(bangou) { return selectedSet.value.has(bangou) }
  function toggleSelect(v) {
    const i = selected.value.findIndex(x => x.bangou === v.bangou)
    if (i >= 0) selected.value.splice(i, 1)
    else selected.value.push({
      bangou: v.bangou, title: v.title, cover: v.cover, url: v.url,
      region: v.region, group: v.group, site: v.site, date: v.date
    })
  }
  function clearSelection() { selected.value = [] }
  function toggleEdit() {
    editMode.value = !editMode.value
    if (!editMode.value) clearSelection()
  }

  return {
    settings, siteName,
    isLoggedIn, currentUser, isAdmin, projects, activeProjects, liveCount, hasLive, appVersion, mustChangePassword,
    checkAuth, login, register, logout, changeUsername, changePassword, completeOnboarding,
    fetchProjects, fetchLiveCount, fetchRecentUpdates,
    fetchVideos, fetchSeries, fetchVideo, fetchSeriesDetail, fetchEpisodeDetail,
    probePlay, switchPlayLine, fetchFreshUrl, fetchUrls, getPlayUrl, createDownload,
    fetchLiveGroups, fetchLiveChannels, fetchLiveChannel, switchLiveSource, nextLiveSource,
    fetchCategoryTree, createCategory, updateCategory, deleteCategory, reorderCategories, normalizeCategoryOrder,
    fetchFavorites, addFavorite, removeFavorite, checkFav, toggleFav,
    fetchHistory, addHistory, clearHistory, deleteHistoryItem, batchDeleteHistory,
    fetchStats,
    mergeVideos, transferVideos, setDedup, removeDedup, dedupInfo,
    fetchOverrides, putOverrides, setVideoTags, setVideoCategory, fetchRules, deleteRule,
    fetchAdminUsers, createAdminUser, updateAdminUser, deleteAdminUser,
    fetchPendingUsers, approveUser, rejectUser, fetchUserProjects, assignUserProjects,
    fetchAdminProjects, createProject, updateProject, deleteProject,
    fetchAutoUpdates, fetchProxyCandidates, createAutoUpdate, updateAutoUpdate, deleteAutoUpdate, triggerAutoUpdate, fetchAutoUpdateLogs,
    fetchAdminSettings, putAdminSettings, importRemote, importRemotePreview, importLiveAdmin,
    downloadApi,
    editMode, selected, selectedSet, isSelected, toggleSelect, clearSelection, toggleEdit
  }
})
