<template>
  <div class="admin-view">
    <div class="page-inner">
      <h2 class="page-title">权限管理</h2>

      <div class="tab-row">
        <button class="tab" :class="{ active: tab === 'pending' }" @click="tab = 'pending'">
          待审批账号 <span class="badge" v-if="pendingUsers.length">{{ pendingUsers.length }}</span>
        </button>
        <button class="tab" :class="{ active: tab === 'users' }" @click="tab = 'users'">账号列表</button>
        <button class="tab" :class="{ active: tab === 'projects' }" @click="tab = 'projects'">项目管理</button>
      </div>

      <!-- 待审批 -->
      <section v-if="tab === 'pending'">
        <div class="pending-list" v-if="pendingUsers.length">
          <div class="pending-row" v-for="u in pendingUsers" :key="u.id">
            <div class="pending-info">
              <span class="pending-name">{{ u.display_name || u.username }}</span>
              <span class="pending-user">@{{ u.username }}</span>
              <span class="pending-date" v-if="u.created_at">申请于 {{ u.created_at?.slice(0, 10) }}</span>
            </div>
            <div class="pending-actions">
              <button class="btn btn-primary sm" :disabled="busy" @click="doApprove(u)">批准</button>
              <button class="btn danger sm" :disabled="busy" @click="doReject(u)">拒绝</button>
            </div>
          </div>
        </div>
        <div class="empty-inline" v-else>暂无待审批的注册申请</div>
      </section>

      <!-- 账号列表 -->
      <section v-if="tab === 'users'">
        <div class="section-head">
          <span>共 {{ users.length }} 个账号</span>
          <button class="btn btn-primary sm" @click="showCreate = !showCreate">{{ showCreate ? '收起' : '创建账号' }}</button>
        </div>

        <form class="create-card" v-if="showCreate" @submit.prevent="doCreateUser">
          <div class="create-grid">
            <label class="field"><span>用户名</span><input v-model.trim="nu.username" required /></label>
            <label class="field"><span>密码</span><input v-model="nu.password" type="password" required /></label>
            <label class="field"><span>角色</span>
              <select v-model="nu.role">
                <option value="viewer">普通用户</option>
                <option value="admin">管理员</option>
              </select>
            </label>
          </div>
          <div class="proj-checks" v-if="allProjects.length">
            <span class="field-label">可见项目</span>
            <label v-for="p in allProjects" :key="p.id" class="check-item">
              <input type="checkbox" :value="p.id" v-model="nu.project_ids" /> {{ p.name }}
            </label>
          </div>
          <button class="btn btn-primary sm" type="submit" :disabled="busy">创建</button>
        </form>

        <div class="user-table" v-if="users.length">
          <div class="user-row" v-for="u in users" :key="u.id">
            <div class="user-main">
              <span class="user-name">{{ u.display_name || u.username }}</span>
              <span class="user-account">@{{ u.username }}</span>
              <span class="role-tag" :class="u.role">{{ u.role === 'admin' ? '管理员' : '普通用户' }}</span>
              <span class="state-tag" v-if="!u.is_active">已停用</span>
            </div>
            <div class="user-proj" v-if="u.role !== 'admin' && allProjects.length">
              <span class="field-label">可见项目：</span>
              <label v-for="p in allProjects" :key="p.id" class="check-item inline">
                <input type="checkbox"
                       :checked="(userProjMap[u.id] || []).includes(p.id)"
                       @change="toggleUserProject(u, p.id, $event.target.checked)" /> {{ p.name }}
              </label>
            </div>
            <div class="user-proj" v-else-if="u.role === 'admin'">
              <span class="field-label">管理员可见全部项目</span>
            </div>
            <div class="user-actions">
              <button class="btn ghost sm" :disabled="busy" @click="toggleActive(u)">{{ u.is_active ? '停用' : '启用' }}</button>
              <button class="btn danger sm" :disabled="busy || u.id === store.currentUser?.id" @click="doDeleteUser(u)">删除</button>
            </div>
          </div>
        </div>
      </section>

      <!-- 项目管理 -->
      <section v-if="tab === 'projects'">
        <div class="section-head">
          <span>共 {{ allProjects.length }} 个项目</span>
          <button class="btn btn-primary sm" @click="showNewProject = !showNewProject">{{ showNewProject ? '收起' : '新建项目' }}</button>
        </div>

        <form class="create-card" v-if="showNewProject" @submit.prevent="doCreateProject">
          <div class="create-grid">
            <label class="field"><span>项目名称</span><input v-model.trim="np.name" required placeholder="如：影视剧" /></label>
            <label class="field"><span>标识 slug</span><input v-model.trim="np.slug" required placeholder="如：movies" /></label>
            <label class="field"><span>描述</span><input v-model.trim="np.description" placeholder="可选" /></label>
          </div>
          <button class="btn btn-primary sm" type="submit" :disabled="busy">创建</button>
        </form>

        <div class="user-table" v-if="allProjects.length">
          <div class="user-row" v-for="p in allProjects" :key="p.id">
            <div class="user-main">
              <span class="user-name">{{ p.name }}</span>
              <span class="user-account">{{ p.slug }}</span>
              <span class="state-tag" v-if="p.is_active === false">已停用</span>
            </div>
            <div class="user-proj">
              <span class="field-label">视频 {{ p.video_count ?? 0 }} · 剧集 {{ p.series_count ?? 0 }}{{ p.description ? ' · ' + p.description : '' }}</span>
            </div>
            <div class="user-actions">
              <button class="btn ghost sm" :disabled="busy" @click="toggleProjectActive(p)">{{ p.is_active === false ? '启用' : '停用' }}</button>
              <button class="btn danger sm" :disabled="busy" @click="doDeleteProject(p)">删除</button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useAppStore } from '../stores/app.js'
import { useUiStore } from '../stores/ui.js'

defineOptions({ name: 'AdminView' })

const store = useAppStore()
const ui = useUiStore()

const tab = ref('pending')
const pendingUsers = ref([])
const users = ref([])
const allProjects = ref([])
const userProjMap = ref({})
const showCreate = ref(false)
const showNewProject = ref(false)
const busy = ref(false)

const nu = reactive({ username: '', password: '', role: 'viewer', project_ids: [] })
const np = reactive({ name: '', slug: '', description: '' })

async function loadAll() {
  busy.value = true
  try {
    const [pu, us, ps] = await Promise.all([
      store.fetchPendingUsers(),
      store.fetchAdminUsers(),
      store.fetchAdminProjects()
    ])
    pendingUsers.value = Array.isArray(pu) ? pu : (pu.users || [])
    users.value = Array.isArray(us) ? us : (us.users || [])
    allProjects.value = Array.isArray(ps) ? ps : (ps.projects || [])
    // 拉每个账号的项目可见性
    const entries = await Promise.all(
      users.value
        .filter(u => u.role !== 'admin')
        .map(async u => [u.id, await store.fetchUserProjects(u.id).catch(() => [])])
    )
    userProjMap.value = Object.fromEntries(entries)
  } catch (e) {
    ui.toast(e.message || '数据加载失败', 'error')
  }
  busy.value = false
}

async function doApprove(u) {
  busy.value = true
  try {
    await store.approveUser(u.id)
    ui.toast(`已批准 @${u.username}，该账号现在可以登录`, 'success')
    await loadAll()
    await store.fetchProjects()
  } catch (e) {
    ui.toast(e.message || '批准失败', 'error')
  }
  busy.value = false
}

async function doReject(u) {
  const ok = await ui.confirm(`确定拒绝 @${u.username} 的注册申请？拒绝后该账号将无法登录。`, { danger: true })
  if (!ok) return
  busy.value = true
  try {
    await store.rejectUser(u.id)
    ui.toast(`已拒绝 @${u.username}`, 'success')
    await loadAll()
  } catch (e) {
    ui.toast(e.message || '拒绝失败', 'error')
  }
  busy.value = false
}

async function doCreateUser() {
  if (!nu.username || !nu.password) { ui.toast('请填写用户名和密码', 'error'); return }
  busy.value = true
  try {
    await store.createAdminUser({ ...nu })
    ui.toast('账号已创建', 'success')
    Object.assign(nu, { username: '', password: '', role: 'viewer', project_ids: [] })
    showCreate.value = false
    await loadAll()
  } catch (e) {
    ui.toast(e.message || '创建失败', 'error')
  }
  busy.value = false
}

async function toggleUserProject(u, projectId, checked) {
  const current = [...(userProjMap.value[u.id] || [])]
  const next = checked ? [...new Set([...current, projectId])] : current.filter(id => id !== projectId)
  userProjMap.value = { ...userProjMap.value, [u.id]: next }
  try {
    await store.assignUserProjects(u.id, next)
    ui.toast(`@${u.username} 的项目可见性已更新`, 'success')
    await store.fetchProjects()
  } catch (e) {
    userProjMap.value = { ...userProjMap.value, [u.id]: current }
    ui.toast(e.message || '保存失败', 'error')
  }
}

async function toggleActive(u) {
  busy.value = true
  try {
    await store.updateAdminUser(u.id, { is_active: !u.is_active })
    ui.toast(`账号已${u.is_active ? '停用' : '启用'}`, 'success')
    await loadAll()
  } catch (e) {
    ui.toast(e.message || '操作失败', 'error')
  }
  busy.value = false
}

async function doDeleteUser(u) {
  const ok = await ui.confirm(`确定删除账号 @${u.username}？该操作不可恢复。`, { danger: true })
  if (!ok) return
  busy.value = true
  try {
    await store.deleteAdminUser(u.id)
    ui.toast('账号已删除', 'success')
    await loadAll()
  } catch (e) {
    ui.toast(e.message || '删除失败', 'error')
  }
  busy.value = false
}

async function doCreateProject() {
  if (!np.name || !np.slug) { ui.toast('请填写项目名称和 slug', 'error'); return }
  busy.value = true
  try {
    await store.createProject({ ...np })
    ui.toast('项目已创建', 'success')
    Object.assign(np, { name: '', slug: '', description: '' })
    showNewProject.value = false
    await loadAll()
    await store.fetchProjects()
  } catch (e) {
    ui.toast(e.message || '创建失败', 'error')
  }
  busy.value = false
}

async function toggleProjectActive(p) {
  busy.value = true
  try {
    await store.updateProject(p.id, { is_active: p.is_active === false })
    ui.toast(`项目已${p.is_active === false ? '启用' : '停用'}`, 'success')
    await loadAll()
    await store.fetchProjects()
  } catch (e) {
    ui.toast(e.message || '操作失败', 'error')
  }
  busy.value = false
}

async function doDeleteProject(p) {
  const ok = await ui.confirm(`确定删除项目「${p.name}」？项目下的分类配置将被移除。`, { danger: true })
  if (!ok) return
  busy.value = true
  try {
    await store.deleteProject(p.id)
    ui.toast('项目已删除', 'success')
    await loadAll()
    await store.fetchProjects()
  } catch (e) {
    ui.toast(e.message || '删除失败', 'error')
  }
  busy.value = false
}

onMounted(loadAll)
</script>

<style scoped>
.admin-view { display: flex; justify-content: center; padding-bottom: 40px; }
.page-inner { width: 100%; max-width: 1100px; padding: 20px 24px 0; }
.page-title { margin: 0 0 16px; font-size: var(--text-2xl); color: var(--text-primary); }

.tab-row { display: flex; gap: 8px; margin-bottom: 18px; }
.tab {
  padding: 8px 18px; border-radius: 99px; border: 1px solid var(--border-light);
  background: var(--bg-input); color: var(--text-secondary); font-size: 13.5px; cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px;
}
.tab.active { background: var(--accent); color: var(--text-inverse); border-color: var(--accent); font-weight: 600; }
.badge {
  min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px;
  background: var(--error); color: #fff; font-size: 11px; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center;
}

.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-size: 13px; color: var(--text-muted); }

.pending-list, .user-table { display: flex; flex-direction: column; gap: 10px; }
.pending-row, .user-row {
  display: flex; flex-direction: column; gap: 8px;
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: var(--radius-md); padding: 14px 16px;
}
.pending-info, .user-main { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pending-name, .user-name { font-size: 14.5px; font-weight: 600; color: var(--text-primary); }
.pending-user, .user-account { font-size: 12.5px; color: var(--text-muted); font-family: var(--font-mono); }
.pending-date { font-size: 12px; color: var(--text-muted); }
.role-tag {
  padding: 2px 8px; border-radius: var(--radius-sm); font-size: 11px; font-weight: 600;
  background: var(--bg-input); color: var(--text-secondary);
}
.role-tag.admin { background: var(--accent); color: var(--text-inverse); }
.state-tag {
  padding: 2px 8px; border-radius: var(--radius-sm); font-size: 11px; font-weight: 600;
  background: var(--error); color: #fff;
}
.pending-actions, .user-actions { display: flex; gap: 8px; }
.user-proj { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.field-label { font-size: 12px; color: var(--text-muted); }
.check-item { display: inline-flex; align-items: center; gap: 5px; font-size: 13px; color: var(--text-secondary); cursor: pointer; }
.check-item.inline { padding: 2px 0; }

.create-card {
  display: flex; flex-direction: column; gap: 12px;
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: var(--radius-md); padding: 16px; margin-bottom: 14px;
}
.create-grid { display: flex; gap: 12px; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 160px; }
.field span { font-size: 12.5px; font-weight: 500; color: var(--text-secondary); }
.field input, .field select {
  height: 38px; padding: 0 12px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary); font-size: 14px;
  box-sizing: border-box; width: 100%;
  transition: border-color var(--duration-fast), box-shadow var(--duration-fast);
}
.field input:focus, .field select:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(255, 71, 87, 0.18);
}
.field input::placeholder {
  color: var(--text-muted);
  font-size: 13.5px;
  opacity: 0.85;
}
.proj-checks { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

.empty-inline { padding: 40px 0; text-align: center; color: var(--text-muted); }

.btn { border: none; border-radius: var(--radius-sm); cursor: pointer; font-size: 12.5px; }
.btn.sm { height: 32px; padding: 0 16px; }
.btn.primary { background: var(--accent); color: #fff; }
.btn.ghost { background: var(--bg-input); color: var(--text-secondary); }
.btn.danger { background: var(--error); color: #fff; }
.btn:disabled { opacity: 0.55; cursor: default; }

@media (max-width: 640px) {
  .page-inner { padding: 14px 12px 0; }
}
</style>
