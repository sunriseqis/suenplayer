<template>
  <div class="settings-view">
    <div class="page-inner">
      <h2 class="page-title">项目设置</h2>

      <div class="group-tabs">
        <button v-for="g in GROUPS" :key="g.key" class="gtab"
                :class="{ active: tab === g.key }" @click="tab = g.key">{{ g.label }}</button>
      </div>

      <section class="panel" v-if="tab === 'sources'">
        <div class="panel-header-line">
          <div>
            <h3>数据源管理</h3>
          </div>
          <div class="head-actions">
            <button class="btn btn-secondary sm" :disabled="busyAuto" @click="loadAuto">刷新列表</button>
            <button class="btn btn-primary sm" @click="toggleAutoForm">{{ showAutoForm ? '收起表单' : '新增数据源' }}</button>
          </div>
        </div>

        <form class="create-card" v-if="showAutoForm" @submit.prevent="saveAuto">
          <h4>{{ autoEditing ? '编辑数据源' : '新增数据源' }}</h4>
          <p class="form-hint">仅注册自动更新配置（后台定时拉取），不立即导入数据；保存后可选择立即同步以拉取并入库。</p>
          <div class="form-grid">
            <label class="field"><span>数据源名称</span><input v-model.trim="autoForm.name" placeholder="例如：安徽 IPTV 或 影视精选" required /></label>
            <label class="field"><span>源类型</span>
              <select v-model="autoForm.source_type">
                <option value="video">影视库（GitHub 仓库 / 目录 / 单文件）</option>
                <option value="live">直播源（电视频道 JSON）</option>
              </select>
            </label>
            <label class="field grow"><span>产物地址（http(s) 远端或服务器本地目录 / 文件）</span><input v-model.trim="autoForm.source_path" placeholder="https://... 或 /path/to/data.json" required /></label>
            <label class="field"><span>自动更新周期（分钟，留空不自动轮询）</span><input v-model.number="autoForm.update_interval" type="number" min="10" placeholder="60" /></label>
          </div>
          <div class="proxy-row">
            <label class="check-item inline-check">
              <input type="checkbox" v-model="autoForm.proxy_pull" />
              <span>拉取走代理</span>
            </label>
            <span class="proxy-hint">勾选后会在「代理配置」中自动创建一条该源的订阅代理条目</span>
          </div>
          <div class="panel-actions">
            <button class="btn btn-primary" type="submit" :disabled="busyAuto">{{ autoEditing ? '保存修改' : '保存并添加到数据源' }}</button>
            <button class="btn btn-secondary" type="button" @click="toggleAutoForm">取消</button>
          </div>
        </form>

        <div class="sources-table-wrap" v-if="autoConfigs.length">
          <table class="sources-table compact">
            <thead>
              <tr>
                <th class="col-name">数据源</th>
                <th class="col-count">数据量</th>
                <th class="col-count" title="最近一次同步状态">同步状态</th>
                <th class="col-ops">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in autoConfigs" :key="c.id">
                <td>
                  <div class="source-info-compact" :title="'完整地址：' + c.source_path">
                    <strong class="source-name">{{ c.name }}</strong>
                    <span class="type-tag sm" :class="c.source_type">{{ c.source_type === 'live' ? '直播' : '影视' }}</span>
                  </div>
                </td>
                <td class="tcell-center">
                  <span class="item-count-compact">{{ c.item_count != null ? (c.item_count + (c.source_type === 'live' ? ' 频道' : ' 条')) : '-' }}</span>
                </td>
                <td class="tcell-center">
                  <div class="status-indicator-wrap" :title="getStatusTooltip(c)">
                    <span class="status-dot" :class="statusKind(c)"></span>
                    <span class="status-text-compact">{{ statusLabel(c) }}</span>
                  </div>
                  <div class="sync-progress" v-if="statusKind(c) === 'running'">
                    <div class="sync-progress-bar"></div>
                  </div>
                </td>
                <td class="tcell-right">
                  <div class="icon-actions">
                    <button class="icon-btn sync" :disabled="busyAuto" @click="triggerAuto(c)" title="立即同步">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                    </button>
                    <button class="icon-btn edit" :disabled="busyAuto" @click="editAuto(c)" title="编辑配置">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <button class="icon-btn log" :class="{ active: logConfigId === c.id }" :disabled="busyAuto" @click="loadLogs(c)" title="查看同步日志">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                    </button>
                    <button class="icon-btn delete" :disabled="busyAuto" @click="confirmDeleteSource(c)" title="删除数据源">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>

          <div class="log-box" v-if="logConfigId">
            <div class="log-head">
              <span>配置日志 (ID: {{ logConfigId }})</span>
              <button class="btn ghost sm" @click="logConfigId = null">关闭</button>
            </div>
            <div class="log-line" v-for="(l, i) in logs" :key="i">{{ l }}</div>
            <div class="log-line" v-if="!logs.length">暂无日志</div>
          </div>
        </div>
        <div class="empty-inline" v-else-if="!showAutoForm">
          暂无被管理的数据源。点击右上角「新增数据源」添加配置，保存后可立即同步拉取产物。
        </div>
      </section>

      <section class="panel" v-if="tab === 'proxy'">
        <h3>代理配置</h3>
        <div class="form-row">
          <label class="field grow"><span>代理地址</span><input v-model.trim="proxyAddr" placeholder="http://127.0.0.1:7890 或 socks5://…" /></label>
          <label class="field target-field"><span>测试目标（可选）</span><input v-model.trim="proxyTestTarget" placeholder="默认: https://www.google.com/generate_204" /></label>
          <button class="btn btn-secondary self-end" :disabled="busyProxy" @click="testProxy">{{ testing ? '测试中…' : '测试连通' }}</button>
        </div>
        <div class="form-row">
          <label class="field grow"><span>Git 访问令牌（可选，拉取私有仓库时填写）</span><input v-model.trim="gitToken" type="password" autocomplete="off" placeholder="ghp_… / ghp_xxx，留空表示仅公开仓库" /></label>
          <label class="field target-field"><span>DoH 服务（DNS 防污染，可选）</span><input v-model.trim="dohUrl" placeholder="https://223.5.5.5/resolve" /></label>
        </div>
        <div class="form-row">
          <label class="field grow"><span>hosts 映射（每行「IP 域名」，仅作用于封面抓取，优先于 DoH）</span><textarea v-model.trim="hostsMap" rows="3" placeholder="185.13.109.141 image.jinyingimage.com&#10;37.77.87.202 img.lzipic.com"></textarea></label>
        </div>
        <div class="form-row save-row">
          <span class="save-hint">保存设置将同时提交上方全部字段（代理地址 / Git 令牌 / DoH / hosts）</span>
          <button class="btn btn-primary self-end" :disabled="busyProxy" @click="saveProxy">保存设置</button>
        </div>
        <div class="proxy-test-result" v-if="proxyTestResult" :class="{ ok: proxyTestResult.ok, fail: !proxyTestResult.ok }">
          {{ proxyTestResult.ok ? '连通正常' : ('测试失败：' + (proxyTestResult.error || '未知错误')) }}
        </div>

        <div class="proxy-entries-card">
          <h4>代理条目</h4>
          <div class="form-row entry-add-row">
            <label class="field"><span>类型</span>
              <select v-model="entryType">
                <option value="sub">订阅源</option>
                <option value="play">播放源</option>
              </select>
            </label>
            <label class="field grow"><span>条目内容</span>
              <template v-if="entryType === 'sub'">
                <select v-model="entryValue">
                  <option value="" disabled>选择在库的订阅源…</option>
                  <option v-for="c in candidateSubs" :key="c.id" :value="String(c.id)">{{ c.name }}</option>
                </select>
              </template>
              <template v-else>
                <input list="proxy-play-candidates" v-model.trim="entryValue" placeholder="选择或直接输入播放源/站点名/域名（如 porn87 或 cdn.domain.com）…" />
                <datalist id="proxy-play-candidates">
                  <option v-for="p in candidatePlays" :key="p" :value="p">{{ p }}</option>
                </datalist>
              </template>
            </label>
            <button class="btn btn-primary self-end" :disabled="!entryValue" @click="addEntry">添加条目</button>
          </div>
          <p class="proxy-hint" style="margin-top: 6px;">💡 提示：配置代理地址后，封面图片抓取已默认走代理通道，无需手动添加封面域名。</p>
          <div class="sources-table-wrap" v-if="ruleSubs.length || rulePlays.length">
            <table class="sources-table compact">
              <thead>
                <tr>
                  <th class="entry-col-type">类型</th>
                  <th>条目内容</th>
                  <th class="entry-col-ops">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in ruleSubs" :key="'sub-' + (s.id || s.name)">
                  <td><span class="type-tag sm sub">订阅源</span></td>
                  <td>{{ s.name || ('订阅源 #' + s.id) }}</td>
                  <td class="tcell-right"><button type="button" class="entry-remove" @click="removeSubEntry(s)">移除</button></td>
                </tr>
                <tr v-for="k in rulePlays" :key="'play-' + k">
                  <td><span class="type-tag sm play-tag">播放源</span></td>
                  <td>{{ k }}</td>
                  <td class="tcell-right"><button type="button" class="entry-remove" @click="removePlayEntry(k)">移除</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="entry-empty" v-else>暂无代理条目——默认全部直连</p>
        </div>
      </section>

      <section class="panel" v-if="tab === 'taxonomy'">
        <h3>规则中心</h3>

        <div class="collapse-block">
          <button class="collapse-head" @click="collapsed.cats = !collapsed.cats">
            <span>分类管理</span>
            <span class="collapse-icon">{{ collapsed.cats ? '▸' : '▾' }}</span>
          </button>
          <div class="collapse-body" v-if="!collapsed.cats">
            <div class="form-row">
              <label class="field"><span>新一级分类</span><input v-model.trim="newCat.name" placeholder="分类名" @keyup.enter="createCat" /></label>
              <label class="field"><span>所属项目</span>
                <select v-model="newCat.project_id">
                  <option v-for="p in store.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
                </select>
              </label>
              <button class="btn btn-primary self-end" :disabled="!newCat.name || busyCats" @click="createCat">创建分类</button>
            </div>
            <div class="sources-table-wrap" v-if="catTree.length">
              <table class="sources-table compact">
                <thead><tr><th>分类名称</th><th class="col-count">所属项目</th><th class="col-ops">操作</th></tr></thead>
                <tbody>
                  <tr v-for="c in catTree" :key="c.id">
                    <td>
                      <template v-if="renamingId === c.id">
                        <input class="rename-input" v-model.trim="renameValue" placeholder="分类名" @keyup.enter="doRenameCat(c)" @keyup.esc="cancelRename" />
                      </template>
                      <strong v-else>{{ c.name }}</strong>
                    </td>
                    <td class="tcell-center"><span class="cat-proj">{{ projectName(c.project_id) }}</span></td>
                    <td class="tcell-right">
                      <template v-if="renamingId === c.id">
                        <button class="btn primary sm" :disabled="!renameValue || busyCats" @click="doRenameCat(c)">保存</button>
                        <button class="btn ghost sm" @click="cancelRename">取消</button>
                      </template>
                      <template v-else>
                        <button class="btn ghost sm" @click="startRename(c)">重命名</button>
                        <button class="btn danger sm" :disabled="busyCats" @click="deleteCat(c)">删除</button>
                      </template>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="empty-inline" v-else>暂无分类</div>
          </div>
        </div>

        <div class="collapse-block">
          <button class="collapse-head" @click="collapsed.rules = !collapsed.rules">
            <span>规则中心</span>
            <span class="collapse-icon">{{ collapsed.rules ? '▸' : '▾' }}</span>
          </button>
          <div class="collapse-body" v-if="!collapsed.rules">
            <div class="sources-table-wrap" v-if="rules.length">
              <table class="sources-table compact">
                <thead><tr><th class="col-count">类型</th><th>规则描述</th><th class="col-count">所属项目</th><th class="col-ops">操作</th></tr></thead>
                <tbody>
                  <tr v-for="r in rules" :key="r.id">
                    <td class="tcell-center"><span class="type-tag sm" :class="r.rule_type">{{ r.rule_type === 'merge' ? '合并' : '转移' }}</span></td>
                    <td>{{ ruleDesc(r) }}</td>
                    <td class="tcell-center"><span class="cat-proj">{{ projectName(r.project_id) }}</span></td>
                    <td class="tcell-right"><button class="btn danger sm" :disabled="busyRules" @click="removeRule(r)">删除</button></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="empty-inline" v-else>暂无规则。在项目页使用"合并 / 批量转移"后会在这里累积。</div>
          </div>
        </div>
      </section>

      <section class="panel" v-if="tab === 'security'">
        <h3>账号安全</h3>
        <div class="form-grid">
          <label class="field"><span>修改用户名（当前：{{ store.currentUser?.username }}）</span>
            <input v-model.trim="sec.username" :placeholder="store.currentUser?.username" />
          </label>
          <button class="btn btn-primary self-end" :disabled="!sec.username || busySec" @click="doChangeUsername">更新用户名</button>
        </div>
        <div class="form-grid">
          <label class="field"><span>当前密码</span><input v-model="sec.oldPassword" type="password" /></label>
          <label class="field"><span>新密码（至少 6 位）</span><input v-model="sec.newPassword" type="password" /></label>
          <button class="btn btn-primary self-end" :disabled="!sec.oldPassword || !sec.newPassword || busySec" @click="doChangePassword">修改密码</button>
        </div>
        <div class="logout-row">
          <button class="btn danger" @click="doLogout">退出登录</button>
        </div>

        <!-- 权限管理（仅管理员） -->
        <div class="collapse-block" v-if="store.isAdmin" style="margin-top:18px;">
          <button class="collapse-head" @click="collapsed.admin = !collapsed.admin">
            <span>权限管理</span>
            <span class="collapse-icon">{{ collapsed.admin ? '▸' : '▾' }}</span>
          </button>
          <div class="collapse-body" v-if="!collapsed.admin">
            <div class="admin-subtabs">
              <button class="asub" :class="{ active: adminTab === 'pending' }" @click="adminTab = 'pending'; loadAdminData()">
                待审批 <span class="badge" v-if="pendingUsers.length">{{ pendingUsers.length }}</span>
              </button>
              <button class="asub" :class="{ active: adminTab === 'users' }" @click="adminTab = 'users'; loadAdminData()">账号列表</button>
              <button class="asub" :class="{ active: adminTab === 'projects' }" @click="adminTab = 'projects'; loadAdminData()">项目管理</button>
            </div>

            <!-- 待审批 -->
            <div v-if="adminTab === 'pending'">
              <div class="sources-table-wrap" v-if="pendingUsers.length">
                <table class="sources-table compact">
                  <thead><tr><th>账号</th><th class="col-count">申请时间</th><th class="col-ops">操作</th></tr></thead>
                  <tbody>
                    <tr v-for="u in pendingUsers" :key="u.id">
                      <td><strong>{{ u.display_name || u.username }}</strong> <span class="cat-proj">@{{ u.username }}</span></td>
                      <td class="tcell-center"><span class="cat-proj" v-if="u.created_at">{{ u.created_at?.slice(0, 10) }}</span></td>
                      <td class="tcell-right">
                        <button class="btn primary sm" :disabled="busyAdmin" @click="doApprove(u)">批准</button>
                        <button class="btn danger sm" :disabled="busyAdmin" @click="doReject(u)">拒绝</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="empty-inline" v-else>暂无待审批的注册申请</div>
            </div>

            <!-- 账号列表 -->
            <div v-if="adminTab === 'users'">
              <div class="section-head">
                <span>共 {{ users.length }} 个账号</span>
                <button class="btn btn-primary sm" @click="showCreateUser = !showCreateUser">{{ showCreateUser ? '收起' : '创建账号' }}</button>
              </div>
              <form class="create-card" v-if="showCreateUser" @submit.prevent="doCreateUser">
                <div class="form-row">
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
                <button class="btn btn-primary sm" type="submit" :disabled="busyAdmin" style="align-self:flex-end;">创建</button>
              </form>
              <div class="sources-table-wrap" v-if="users.length">
                <table class="sources-table compact">
                  <thead><tr><th>账号</th><th class="col-count">角色</th><th class="col-count">状态</th><th class="col-ops">操作</th></tr></thead>
                  <tbody>
                    <tr v-for="u in users" :key="u.id">
                      <td>
                        <strong>{{ u.display_name || u.username }}</strong>
                        <span class="cat-proj">@{{ u.username }}</span>
                        <div class="user-proj" v-if="u.role !== 'admin' && allProjects.length">
                          <span class="field-label">可见项目：</span>
                          <label v-for="p in allProjects" :key="p.id" class="check-item inline">
                            <input type="checkbox" :checked="(userProjMap[u.id] || []).includes(p.id)" @change="toggleUserProject(u, p.id, $event.target.checked)" /> {{ p.name }}
                          </label>
                        </div>
                      </td>
                      <td class="tcell-center"><span class="type-tag sm" :class="u.role">{{ u.role === 'admin' ? '管理员' : '普通用户' }}</span></td>
                      <td class="tcell-center"><span class="type-tag sm" v-if="!u.is_active" style="background:#ef4444;color:#fff;">已停用</span><span v-else class="cat-proj">正常</span></td>
                      <td class="tcell-right">
                        <button class="btn ghost sm" :disabled="busyAdmin" @click="toggleActive(u)">{{ u.is_active ? '停用' : '启用' }}</button>
                        <button class="btn danger sm" :disabled="busyAdmin || u.id === store.currentUser?.id" @click="doDeleteUser(u)">删除</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- 项目管理 -->
            <div v-if="adminTab === 'projects'">
              <div class="section-head">
                <span>共 {{ allProjects.length }} 个项目</span>
                <button class="btn btn-primary sm" @click="showNewProject = !showNewProject">{{ showNewProject ? '收起' : '新建项目' }}</button>
              </div>
              <form class="create-card" v-if="showNewProject" @submit.prevent="doCreateProject">
                <div class="form-row">
                  <label class="field"><span>项目名称</span><input v-model.trim="np.name" required placeholder="如：影视剧" /></label>
                  <label class="field"><span>标识 slug</span><input v-model.trim="np.slug" required placeholder="如：movies" /></label>
                  <label class="field"><span>描述</span><input v-model.trim="np.description" placeholder="可选" /></label>
                </div>
                <button class="btn btn-primary sm" type="submit" :disabled="busyAdmin" style="align-self:flex-end;">创建</button>
              </form>
              <div class="sources-table-wrap" v-if="allProjects.length">
                <table class="sources-table compact">
                  <thead><tr><th>项目名称</th><th class="col-count">slug</th><th class="col-count">数据量</th><th class="col-ops">操作</th></tr></thead>
                  <tbody>
                    <tr v-for="p in allProjects" :key="p.id">
                      <td><strong>{{ p.name }}</strong></td>
                      <td class="tcell-center"><span class="cat-proj">{{ p.slug }}</span></td>
                      <td class="tcell-center"><span class="cat-proj">视频 {{ p.video_count ?? 0 }} · 剧集 {{ p.series_count ?? 0 }}</span></td>
                      <td class="tcell-right">
                        <button class="btn ghost sm" :disabled="busyAdmin" @click="toggleProjectActive(p)">{{ p.is_active === false ? '启用' : '停用' }}</button>
                        <button class="btn danger sm" :disabled="busyAdmin" @click="doDeleteProject(p)">删除</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </section>

      <footer class="version-footer" v-if="store.appVersion">
        当前版本 v{{ store.appVersion }}
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../stores/app.js'
import { useUiStore } from '../stores/ui.js'

defineOptions({ name: 'SettingsView' })

const store = useAppStore()
const ui = useUiStore()
const router = useRouter()

const GROUPS = [
  { key: 'sources', label: '数据源管理' },
  { key: 'proxy', label: '代理配置' },
  { key: 'taxonomy', label: '规则中心' },
  { key: 'security', label: '账号安全' }
]
const tab = ref('sources')
const busyAuto = ref(false)
const busyProxy = ref(false)
const busyCats = ref(false)
const busyRules = ref(false)
const busySec = ref(false)
const collapsed = reactive({ cats: false, rules: true, admin: true })
/* 同步中状态：key 为 config id，轮询检测完成后清除 */
const syncing = ref({})
const SYNC_POLL_INTERVAL = 2000
const SYNC_POLL_MAX = 60  // 最多轮询 120 秒

function startSyncPolling(id, name) {
  syncing.value = { ...syncing.value, [id]: true }
  let count = 0
  const tick = async () => {
    count++
    try {
      await loadAuto()
    } catch {}
    const cfg = autoConfigs.value.find(c => c.id === id)
    const done = !cfg || String(cfg.last_status || '').toLowerCase() !== 'running'
    if (done || count >= SYNC_POLL_MAX) {
      const cur = { ...syncing.value }
      delete cur[id]
      syncing.value = cur
      if (cfg && !done) {
        ui.toast(`「${name}」同步超时，请稍后查看日志`, 'error')
      } else if (cfg) {
        const kind = statusKind(cfg)
        if (kind === 'ok') ui.toast(`「${name}」同步完成`, 'success')
        else if (kind === 'partial') ui.toast(`「${name}」同步完成（部分报错）`, 'warn')
        else if (kind === 'fail') ui.toast(`「${name}」同步失败，请查看日志`, 'error')
      }
      return
    }
    setTimeout(tick, SYNC_POLL_INTERVAL)
  }
  setTimeout(tick, SYNC_POLL_INTERVAL)
}

const proxyRules = ref({ subs: [], plays: [] })
const entryType = ref('sub')
const entryValue = ref('')
const candidateSubs = ref([])
const candidatePlays = ref([])

/* 代理配置加载 */
async function loadProxyConfig() {
  try {
    const s = await store.fetchAdminSettings()
    proxyAddr.value = s.proxy || ''
    gitToken.value = s.token || ''
    dohUrl.value = s.doh_url || ''
    hostsMap.value = s.hosts_map || ''
    try {
      const pr = JSON.parse(s.proxy_rules || '{}')
      proxyRules.value = { subs: pr.subs || [], plays: pr.plays || [] }
    } catch { proxyRules.value = { subs: [], plays: [] } }
  } catch (e) {
    ui.toast(e.message || '设置加载失败（需要管理员身份）', 'error')
  }
}

/* 自动更新 / 数据源 */
const autoConfigs = ref([])
const showAutoForm = ref(false)
const autoEditing = ref(null)
const autoForm = reactive({
  name: '',
  source_type: 'video',
  source_path: '',
  update_interval: 60,
  proxy_pull: false,
})
const logs = ref([])
const logConfigId = ref(null)

async function loadAuto() {
  try {
    autoConfigs.value = await store.fetchAutoUpdates()
  } catch (e) {
    ui.toast(e.message || '数据源加载失败', 'error')
  }
}

function toggleAutoForm() {
  if (showAutoForm.value) { showAutoForm.value = false; autoEditing.value = null; return }
  Object.assign(autoForm, {
    name: '',
    source_type: 'video',
    source_path: '',
    update_interval: 60,
    proxy_pull: false,
  })
  showAutoForm.value = true
}

async function saveAuto() {
  if (!autoForm.name || !autoForm.source_path) { ui.toast('请填写名称与产物地址', 'error'); return }
  busyAuto.value = true
  try {
    const payload = {
      name: autoForm.name,
      source_type: autoForm.source_type,
      source_path: autoForm.source_path,
      update_interval: autoForm.update_interval,
      proxy_pull: autoForm.proxy_pull ? 1 : 0,
    }
    if (autoEditing.value) {
      await store.updateAutoUpdate(autoEditing.value.id, payload)
      ui.toast('配置已更新', 'success')
    } else {
      const resp = await store.createAutoUpdate(payload)
      ui.toast('数据源已创建', 'success')
      const newId = resp?.config?.id
      if (newId) {
        const choice = await ui.confirm(`数据源「${autoForm.name}」已创建。是否立即同步？\n立即同步会在后台拉取并导入数据，完成后可在首页查看。`, {
          title: '立即同步',
          actions: [
            { label: '稍后再说', value: 'later' },
            { label: '立即同步', value: 'sync' },
          ],
        })
        if (choice === 'sync') {
          await store.triggerAutoUpdate(newId)
          ui.toast('已触发同步', 'success')
          startSyncPolling(newId, autoForm.name)
        }
      }
    }
    showAutoForm.value = false
    autoEditing.value = null
    await loadAuto()
    await loadProxyConfig()  // 源拉取代理会联动代理条目，同步刷新
  } catch (e) {
    ui.toast(e.message || '保存失败', 'error')
  }
  busyAuto.value = false
}

function editAuto(c) {
  autoEditing.value = c
  Object.assign(autoForm, {
    name: c.name,
    source_type: c.source_type,
    source_path: c.source_path,
    update_interval: c.update_interval,
    proxy_pull: c.proxy_pull != null ? !!c.proxy_pull : !!c.use_proxy,
  })
  showAutoForm.value = true
}

async function triggerAuto(c) {
  busyAuto.value = true
  try {
    await store.triggerAutoUpdate(c.id)
    ui.toast(`「${c.name}」已触发同步`, 'success')
    startSyncPolling(c.id, c.name)
  } catch (e) {
    ui.toast(e.message || '触发失败', 'error')
  }
  busyAuto.value = false
}

const ruleSubs = computed(() => proxyRules.value.subs.map(s => ({
  ...s,
  name: s.name || (autoConfigs.value.find(c => String(c.id) === String(s.id))?.name) || ''
})))
const rulePlays = computed(() => proxyRules.value.plays)

async function loadProxyCandidates() {
  try {
    const r = await store.fetchProxyCandidates()
    candidateSubs.value = r.subs || []
    candidatePlays.value = r.plays || []
  } catch {}
}

function addEntry() {
  if (!entryValue.value) return
  if (entryType.value === 'sub') {
    if (proxyRules.value.subs.some(s => String(s.id) === entryValue.value)) {
      ui.toast('该订阅源条目已存在', 'info'); return
    }
    const c = candidateSubs.value.find(x => String(x.id) === entryValue.value)
    proxyRules.value.subs.push({ id: entryValue.value, name: c?.name || '' })
  } else {
    if (proxyRules.value.plays.some(x => x === entryValue.value)) {
      ui.toast('该播放源条目已存在', 'info'); return
    }
    proxyRules.value.plays.push(entryValue.value)
  }
  entryValue.value = ''
  saveProxy()
}
function removeSubEntry(s) {
  proxyRules.value.subs = proxyRules.value.subs.filter(x => String(x.id) !== String(s.id))
  saveProxy()
}
function removePlayEntry(k) {
  proxyRules.value.plays = proxyRules.value.plays.filter(x => x !== k)
  saveProxy()
}

function statusLabel(c) {
  const kind = statusKind(c)
  if (kind === 'running') return '同步中'
  if (kind === 'ok') return '正常'
  if (kind === 'fail') return '失败'
  if (kind === 'partial') return '部分'
  return '待运行'
}

function getStatusTooltip(c) {
  const time = c.last_run_at ? `最后同步: ${formatTime(c.last_run_at)}` : '尚未运行'
  const cycle = c.update_interval ? `自动更新: 每 ${c.update_interval} 分钟` : '无自动轮询'
  const detail = formatLastResult(c) || '无详细信息'
  return `状态: ${statusLabel(c)}\n${time}\n${cycle}\n详情: ${detail}`
}

async function confirmDeleteSource(c) {
  const dataKind = c.source_type === 'live' ? '频道数据' : '视频数据'
  const choice = await ui.confirm(`确定删除数据源「${c.name}」？选择「删除并清理数据」会同时清理已导入的${dataKind}；选择「仅删除配置」则保留已入库数据。`, {
    title: '删除数据源',
    actions: [
      { label: '取消', value: 'cancel' },
      { label: '仅删除配置', value: 'config' },
      { label: '删除并清理数据', value: 'purge', danger: true },
    ],
  })
  if (choice === 'purge') await doDelete(c.id, true)
  else if (choice === 'config') await doDelete(c.id, false)
}

async function doDelete(id, purgeData) {
  busyAuto.value = true
  try {
    await store.deleteAutoUpdate(id, purgeData)
    ui.toast(purgeData ? '数据源及关联数据已全部清理' : '数据源配置已删除', 'success')
    await loadAuto()
    await loadProxyConfig()
    store.fetchStats().catch(() => {})
  } catch (e) {
    ui.toast(e.message || '删除失败', 'error')
  }
  busyAuto.value = false
}

function formatTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

/* 同步状态口径：后端 import 写 success（历史数据可能为 ok），
   定时/手动更新写 success / partial / failed，新建为 pending。
   ok 与 success 都视为正常，避免“导入成功却显示失败”。 */
function statusKind(c) {
  const s = String(c?.last_status || '').toLowerCase()
  if (s === 'running') return 'running'
  if (s === 'ok' || s === 'success') return 'ok'
  if (s === 'partial') return 'partial'
  if (s === 'failed' || s === 'fail' || s === 'error') return 'fail'
  return 'pending'
}

/* last_result 可能是导入时的人类可读摘要，也可能是自动更新写入的
   JSON（{scanned, videos_added, videos_updated, live_channels, live_sources, errors}），
   后者格式化为一行摘要，避免直接展示原始 JSON。 */
function formatLastResult(c) {
  const raw = c?.last_result
  if (raw == null || raw === '') return ''
  if (typeof raw !== 'string') return String(raw)
  const t = raw.trim()
  if (!(t.startsWith('{') && t.endsWith('}'))) return raw
  try {
    const o = JSON.parse(t)
    if (o && typeof o === 'object' && ('live_channels' in o || 'videos_added' in o || 'scanned' in o)) {
      const parts = []
      if (o.videos_added) parts.push(`新增 ${o.videos_added}`)
      if (o.videos_updated) parts.push(`更新 ${o.videos_updated}`)
      if (o.live_channels) parts.push(`频道 ${o.live_channels}`)
      if (o.live_sources) parts.push(`源 ${o.live_sources}`)
      const errs = Array.isArray(o.errors) ? o.errors.filter(Boolean) : []
      if (errs.length) parts.push(`报错 ${errs.length}（${String(errs[0]).slice(0, 40)}）`)
      return parts.length ? parts.join(' · ') : '同步完成，无新增'
    }
  } catch { /* 非标准 JSON 则原样展示 */ }
  return raw
}

async function loadLogs(c) {
  logConfigId.value = logConfigId.value === c.id ? null : c.id
  if (logConfigId.value !== c.id) return
  try {
    logs.value = await store.fetchAutoUpdateLogs(c.id)
  } catch { logs.value = [] }
}

/* 代理 */
const proxyAddr = ref('')
const gitToken = ref('')
const dohUrl = ref('')
const hostsMap = ref('')
const proxyTestTarget = ref('')
const testing = ref(false)
const proxyTestResult = ref(null)

async function saveProxy() {
  busyProxy.value = true
  try {
    await store.putAdminSettings({
      proxy: proxyAddr.value,
      token: gitToken.value,
      doh_url: dohUrl.value,
      hosts_map: hostsMap.value,
      proxy_rules: JSON.stringify(proxyRules.value),
    })
    ui.toast('代理设置已保存', 'success')
  } catch (e) {
    ui.toast(e.message || '保存失败', 'error')
  }
  busyProxy.value = false
}

async function testProxy() {
  testing.value = true
  proxyTestResult.value = null
  try {
    const payload = { proxy: proxyAddr.value }
    if (proxyTestTarget.value) payload.target = proxyTestTarget.value
    const r = await fetch('/api/proxy/test', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    proxyTestResult.value = await r.json()
  } catch (e) {
    proxyTestResult.value = { ok: false, error: e.message || '网络错误' }
  }
  testing.value = false
}


/* 分类管理 */
const catTree = ref([])
const newCat = reactive({ name: '', project_id: null })

function projectName(pid) {
  return store.projects.find(p => p.id === pid)?.name || `项目 ${pid}`
}

async function loadCats() {
  try {
    const d = await store.fetchCategoryTree()
    catTree.value = d.categories || []
  } catch { catTree.value = [] }
}

async function createCat() {
  busyCats.value = true
  try {
    await store.createCategory(newCat.name, null, newCat.project_id)
    ui.toast('一级分类已创建', 'success')
    newCat.name = ''
    await loadCats()
  } catch (e) {
    ui.toast(e.message || '创建失败', 'error')
  }
  busyCats.value = false
}

const renamingId = ref(null)
const renameValue = ref('')

function startRename(c) {
  renamingId.value = c.id
  renameValue.value = c.name
}

function cancelRename() {
  renamingId.value = null
  renameValue.value = ''
}

async function doRenameCat(c) {
  const name = renameValue.value.trim()
  if (!name) { ui.toast('分类名不能为空', 'error'); return }
  if (name === c.name) { cancelRename(); return }
  busyCats.value = true
  try {
    await store.updateCategory(c.id, name)
    ui.toast('分类已重命名', 'success')
    cancelRename()
    await loadCats()
  } catch (e) {
    ui.toast(e.message || '重命名失败', 'error')
  }
  busyCats.value = false
}

async function deleteCat(c) {
  const ok = await ui.confirm(`确定删除分类「${c.name}」？`, { danger: true })
  if (!ok) return
  busyCats.value = true
  try {
    await store.deleteCategory(c.id)
    ui.toast('分类已删除', 'success')
    await loadCats()
  } catch (e) {
    ui.toast(e.message || '删除失败', 'error')
  }
  busyCats.value = false
}

/* 规则中心 */
const rules = ref([])

function ruleDesc(r) {
  try {
    const p = typeof r.payload === 'string' ? JSON.parse(r.payload) : (r.payload || {})
    if (r.rule_type === 'merge') {
      const dups = (p.duplicates || []).join(', ')
      return `合并 ${dups || '(空)'} 到 ${p.keeper || '(空)'}`
    }
    return `${(p.bangous || []).length} 个条目转移到 ${p.region || ''} / ${p.group || ''}`
  } catch {
    return r.payload ? String(r.payload).slice(0, 80) : '(无明细)'
  }
}

async function loadRules() {
  try {
    rules.value = await store.fetchRules()
  } catch { rules.value = [] }
}

async function removeRule(r) {
  const ok = await ui.confirm('确定删除该规则？删除后下次导入不再应用。', { danger: true })
  if (!ok) return
  busyRules.value = true
  try {
    await store.deleteRule(r.id)
    ui.toast('规则已删除', 'success')
    await loadRules()
  } catch (e) {
    ui.toast(e.message || '删除失败', 'error')
  }
  busyRules.value = false
}

/* 账号安全 */
const sec = reactive({ username: '', oldPassword: '', newPassword: '' })

async function doChangeUsername() {
  busySec.value = true
  try {
    await store.changeUsername(sec.username)
    ui.toast('用户名已更新，下次登录请使用新用户名', 'success', 5000)
    sec.username = ''
  } catch (e) {
    ui.toast(e.message || '修改失败', 'error')
  }
  busySec.value = false
}

async function doChangePassword() {
  if (sec.newPassword.length < 6) { ui.toast('新密码至少 6 位', 'error'); return }
  busySec.value = true
  try {
    await store.changePassword(sec.oldPassword, sec.newPassword)
    ui.toast('密码已修改', 'success')
    sec.oldPassword = ''
    sec.newPassword = ''
  } catch (e) {
    ui.toast(e.message || '修改失败', 'error')
  }
  busySec.value = false
}

async function doLogout() {
  await store.logout()
  router.push('/login')
}

/* 权限管理（仅管理员） */
const adminTab = ref('pending')
const pendingUsers = ref([])
const users = ref([])
const allProjects = ref([])
const userProjMap = ref({})
const showCreateUser = ref(false)
const showNewProject = ref(false)
const busyAdmin = ref(false)
const nu = reactive({ username: '', password: '', role: 'viewer', project_ids: [] })
const np = reactive({ name: '', slug: '', description: '' })

async function loadAdminData() {
  if (!store.isAdmin) return
  busyAdmin.value = true
  try {
    const [pu, us, ps] = await Promise.all([
      store.fetchPendingUsers(),
      store.fetchAdminUsers(),
      store.fetchAdminProjects()
    ])
    pendingUsers.value = Array.isArray(pu) ? pu : (pu.users || [])
    users.value = Array.isArray(us) ? us : (us.users || [])
    allProjects.value = Array.isArray(ps) ? ps : (ps.projects || [])
    const entries = await Promise.all(
      users.value.filter(u => u.role !== 'admin').map(async u => [u.id, await store.fetchUserProjects(u.id).catch(() => [])])
    )
    userProjMap.value = Object.fromEntries(entries)
  } catch (e) {
    ui.toast(e.message || '权限数据加载失败', 'error')
  }
  busyAdmin.value = false
}

async function doApprove(u) {
  busyAdmin.value = true
  try { await store.approveUser(u.id); ui.toast(`已批准 @${u.username}`, 'success'); await loadAdminData(); await store.fetchProjects() }
  catch (e) { ui.toast(e.message || '批准失败', 'error') }
  busyAdmin.value = false
}
async function doReject(u) {
  const ok = await ui.confirm(`确定拒绝 @${u.username} 的注册申请？`, { danger: true })
  if (!ok) return
  busyAdmin.value = true
  try { await store.rejectUser(u.id); ui.toast(`已拒绝 @${u.username}`, 'success'); await loadAdminData() }
  catch (e) { ui.toast(e.message || '拒绝失败', 'error') }
  busyAdmin.value = false
}
async function doCreateUser() {
  if (!nu.username || !nu.password) { ui.toast('请填写用户名和密码', 'error'); return }
  busyAdmin.value = true
  try {
    await store.createAdminUser({ ...nu })
    ui.toast('账号已创建', 'success')
    Object.assign(nu, { username: '', password: '', role: 'viewer', project_ids: [] })
    showCreateUser.value = false
    await loadAdminData()
  } catch (e) { ui.toast(e.message || '创建失败', 'error') }
  busyAdmin.value = false
}
async function toggleUserProject(u, projectId, checked) {
  const current = [...(userProjMap.value[u.id] || [])]
  const next = checked ? [...new Set([...current, projectId])] : current.filter(id => id !== projectId)
  userProjMap.value = { ...userProjMap.value, [u.id]: next }
  try { await store.assignUserProjects(u.id, next); ui.toast(`@${u.username} 项目可见性已更新`, 'success'); await store.fetchProjects() }
  catch (e) { userProjMap.value = { ...userProjMap.value, [u.id]: current }; ui.toast(e.message || '保存失败', 'error') }
}
async function toggleActive(u) {
  busyAdmin.value = true
  try { await store.updateAdminUser(u.id, { is_active: !u.is_active }); ui.toast(`账号已${u.is_active ? '停用' : '启用'}`, 'success'); await loadAdminData() }
  catch (e) { ui.toast(e.message || '操作失败', 'error') }
  busyAdmin.value = false
}
async function doDeleteUser(u) {
  const ok = await ui.confirm(`确定删除账号 @${u.username}？该操作不可恢复。`, { danger: true })
  if (!ok) return
  busyAdmin.value = true
  try { await store.deleteAdminUser(u.id); ui.toast('账号已删除', 'success'); await loadAdminData() }
  catch (e) { ui.toast(e.message || '删除失败', 'error') }
  busyAdmin.value = false
}
async function doCreateProject() {
  if (!np.name || !np.slug) { ui.toast('请填写项目名称和 slug', 'error'); return }
  busyAdmin.value = true
  try {
    await store.createProject({ ...np })
    ui.toast('项目已创建', 'success')
    Object.assign(np, { name: '', slug: '', description: '' })
    showNewProject.value = false
    await loadAdminData(); await store.fetchProjects()
  } catch (e) { ui.toast(e.message || '创建失败', 'error') }
  busyAdmin.value = false
}
async function toggleProjectActive(p) {
  busyAdmin.value = true
  try { await store.updateProject(p.id, { is_active: p.is_active === false }); ui.toast(`项目已${p.is_active === false ? '启用' : '停用'}`, 'success'); await loadAdminData(); await store.fetchProjects() }
  catch (e) { ui.toast(e.message || '操作失败', 'error') }
  busyAdmin.value = false
}
async function doDeleteProject(p) {
  const ok = await ui.confirm(`确定删除项目「${p.name}」？`, { danger: true })
  if (!ok) return
  busyAdmin.value = true
  try { await store.deleteProject(p.id); ui.toast('项目已删除', 'success'); await loadAdminData(); await store.fetchProjects() }
  catch (e) { ui.toast(e.message || '删除失败', 'error') }
  busyAdmin.value = false
}

watch(tab, (t) => {
  if (t === 'sources' || t === 'proxy') loadAuto()
  if (t === 'taxonomy') { loadCats(); loadRules() }
  if (t === 'security' && store.isAdmin) loadAdminData()
})

onMounted(async () => {
  await loadProxyConfig()
  await loadProxyCandidates()
  loadAuto()
  if (!store.appVersion) store.fetchStats().catch(() => {})
})
</script>

<style scoped>
.settings-view { display: flex; justify-content: center; padding-bottom: 20px; }
.page-inner { width: 100%; max-width: 980px; padding: 20px 24px; }
.page-title { margin: 0 0 16px; font-size: var(--text-2xl); color: var(--text-primary); }

.group-tabs { display: flex; gap: 6px; margin-bottom: 18px; flex-wrap: wrap; }
.gtab {
  padding: 8px 16px; border-radius: 99px; border: 1px solid var(--border-light);
  background: var(--bg-input); color: var(--text-secondary); font-size: 13.5px; cursor: pointer;
}
.gtab.active { background: var(--accent); color: var(--text-inverse); border-color: var(--accent); font-weight: 600; }

.panel {
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: var(--radius-md); padding: 20px;
}
.panel h3 { margin: 0 0 6px; font-size: var(--text-xl); color: var(--text-primary); }
.panel h4 { margin: 18px 0 8px; font-size: var(--text-lg); color: var(--text-primary); }

.form-grid { display: flex; flex-direction: column; gap: 12px; margin-bottom: 14px; }
.form-row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 12px; }
.form-row .btn { height: 34px; padding: 0 16px; flex-shrink: 0; }
.save-hint { font-size: 12px; color: var(--text-muted); align-self: flex-end; margin-bottom: 12px; }
.field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 180px; }
.field.grow { flex: 2; }
.target-field { min-width: 240px; flex: 1.5; }
.field span { font-size: var(--text-base); font-weight: 500; color: var(--text-secondary); }
.field input, .field select, .field textarea {
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary); font-size: var(--text-base);
  box-sizing: border-box; width: 100%;
  transition: border-color var(--duration-fast), box-shadow var(--duration-fast);
}
.field input, .field select {
  height: 38px; padding: 0 12px;
}
.field textarea {
  height: auto; min-height: 84px; padding: 10px 12px;
  line-height: 1.55; resize: vertical;
  font-family: var(--font-mono); font-size: var(--text-sm);
}
.field input:focus, .field select:focus, .field textarea:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(255, 71, 87, 0.18);
}
.field input::placeholder, .field textarea::placeholder {
  color: var(--text-muted);
  font-size: var(--text-sm);
  opacity: 0.85;
}
.check-item { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-base); color: var(--text-secondary); cursor: pointer; height: 38px; }
.check-item.inline-check { height: auto; font-size: var(--text-base); color: var(--text-primary); font-weight: 500; }
.form-hint { margin: 0 0 2px; font-size: 12px; color: var(--text-muted); line-height: 1.5; }
.proxy-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 8px 0 2px; }
.proxy-hint { font-size: 12px; color: var(--text-muted); }
.panel-actions { display: flex; gap: 10px; margin-top: 10px; justify-content: flex-end; }
.self-end { align-self: flex-end; }
.save-row .save-hint { flex: 1; }
.logout-row { margin-top: 6px; }

.btn { border: none; border-radius: var(--radius-sm); cursor: pointer; font-size: var(--text-base); height: 38px; padding: 0 20px; }
.btn.sm { height: 32px; padding: 0 14px; font-size: var(--text-sm); }
.btn.primary { background: var(--accent); color: #fff; }
.btn.secondary { background: var(--bg-input); border: 1px solid var(--border-light); color: var(--text-primary); }
.btn.ghost { background: var(--bg-input); color: var(--text-secondary); }
.btn.danger { background: var(--error); color: #fff; }
.btn:disabled { opacity: 0.55; cursor: default; }

.preview-hint { margin: 2px 0 0; font-size: var(--text-xs); color: var(--text-muted); }
.preview-error {
  margin-top: 10px; font-size: var(--text-base); color: var(--error);
  background: var(--bg-input); border: 1px dashed var(--border);
  border-radius: var(--radius-md); padding: 10px 12px;
}

.preview-result { border-top: 1px solid var(--border-light); margin-top: 18px; padding-top: 14px; }
.pv-meta { display: flex; gap: 18px; flex-wrap: wrap; font-size: var(--text-base); color: var(--text-secondary); margin-bottom: 12px; }
.pv-meta strong { color: var(--text-primary); font-family: var(--font-mono); }
.pv-section { margin-top: 14px; }
.pv-title { font-size: var(--text-sm); font-weight: 600; color: var(--text-muted); margin-bottom: 8px; }
.pv-err-title { color: var(--error); }
.pv-group, .pv-file {
  background: var(--bg-input); border: 1px solid var(--border-light);
  border-radius: var(--radius-sm); padding: 8px 12px; margin-bottom: 6px;
  display: flex; flex-direction: column; gap: 6px;
}
.pv-file { flex-direction: row; align-items: center; flex-wrap: wrap; gap: 8px; }
.pv-group-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pv-group-head strong { font-size: var(--text-md); color: var(--text-primary); }
.pv-tag {
  padding: 2px 8px; border-radius: var(--radius-sm); font-size: var(--text-xs); font-weight: 600;
  background: var(--bg-card); color: var(--text-secondary); border: 1px solid var(--border-light);
}
.pv-tag.ok { background: var(--success); color: #fff; border-color: var(--success); }
.pv-tag.live { color: var(--accent); }
.pv-tag.error { color: var(--error); border-color: var(--error); }
.pv-files { font-size: var(--text-sm); color: var(--text-muted); font-family: var(--font-mono); word-break: break-all; }
.pv-file-name { font-size: var(--text-base); color: var(--text-primary); font-family: var(--font-mono); word-break: break-all; }
.pv-file-err { font-size: var(--text-xs); color: var(--error); }
.pv-err-line { font-size: var(--text-sm); color: var(--text-secondary); font-family: var(--font-mono); padding: 3px 0; word-break: break-all; }

.type-line { font-size: var(--text-base); color: var(--text-secondary); margin-bottom: 12px; }
.type-line strong { color: var(--accent); }

.import-result { border-top: 1px solid var(--border-light); margin-top: 18px; padding-top: 14px; }
.res-stats { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 12px; }
.res-item { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--text-muted); }
.res-num { font-size: 22px; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono); }
.res-num.ok { color: var(--success); }
.res-err-title { font-size: 12px; color: var(--error); font-weight: 600; margin-bottom: 6px; }
.res-err-item { font-size: 12px; color: var(--text-secondary); padding: 3px 0; font-family: var(--font-mono); }
.res-warn .res-err-title { color: var(--warning, var(--accent)); }

.panel-header-line { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 12px; }
.head-actions { display: flex; gap: 8px; flex-shrink: 0; flex-wrap: wrap; justify-content: flex-end; }
.head-actions .btn { white-space: nowrap; flex: none; }

.sources-table-wrap { overflow-x: auto; margin-top: 14px; border: 1px solid var(--border-light); border-radius: var(--radius-md); }
.sources-table { width: 100%; min-width: 860px; border-collapse: collapse; font-size: 13.5px; }
.sources-table th { background: var(--bg-input); color: var(--text-secondary); font-weight: 600; padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border-light); }
.sources-table td { padding: 12px; border-bottom: 1px solid var(--border-light); color: var(--text-primary); vertical-align: middle; }
.sources-table tr:last-child td { border-bottom: none; }
.sources-table tr:hover td { background: var(--bg-hover, rgba(255, 255, 255, 0.02)); }

.sources-table.compact { min-width: 100%; table-layout: auto; }
.sources-table.compact th, .sources-table.compact td { padding: 8px 10px; font-size: 13px; }
/* 表格列工具类（替代模板内联样式） */
.col-name { min-width: 130px; }
.col-count { width: 75px; text-align: center; }
.col-ops { width: 125px; text-align: right; }
.entry-col-type { width: 90px; }
.entry-col-ops { width: 70px; text-align: right; }
.tcell-center { text-align: center; }
.tcell-right { text-align: right; }
.source-info-compact { display: flex; align-items: center; gap: 6px; cursor: help; }
.source-name { font-weight: 600; color: var(--text-primary); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13.5px; }
.type-tag.sm { padding: 1px 5px; font-size: 10.5px; border-radius: 4px; }
.item-count-compact { font-size: 12px; color: var(--text-secondary); font-family: var(--font-mono); }


.status-indicator-wrap { display: inline-flex; align-items: center; gap: 5px; cursor: help; user-select: none; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: var(--text-muted); }
.status-dot.ok { background: #22c55e; box-shadow: 0 0 5px rgba(34, 197, 94, 0.5); }
.status-dot.fail { background: #ef4444; box-shadow: 0 0 5px rgba(239, 68, 68, 0.5); }
.status-dot.partial { background: #f59e0b; box-shadow: 0 0 5px rgba(245, 158, 11, 0.5); }
.status-dot.pending { background: #94a3b8; }
.status-dot.running { background: #3b82f6; animation: pulse-dot 1.2s ease-in-out infinite; }
@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.sync-progress { width: 60px; height: 4px; background: var(--border); border-radius: 2px; margin: 4px auto 0; overflow: hidden; }
.sync-progress-bar { width: 40%; height: 100%; background: #3b82f6; border-radius: 2px; animation: sync-slide 1.2s ease-in-out infinite; }
@keyframes sync-slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(250%); } }
.status-text-compact { font-size: 11.5px; color: var(--text-secondary); }

.icon-actions { display: inline-flex; align-items: center; gap: 4px; justify-content: flex-end; }
.icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 26px; height: 26px; padding: 0; border-radius: var(--radius-sm);
  border: 1px solid var(--border-light); background: var(--bg-card); color: var(--text-secondary);
  cursor: pointer; transition: all 0.15s ease;
}
.icon-btn:hover:not(:disabled) { background: var(--bg-hover, var(--bg-input)); color: var(--text-primary); border-color: var(--border); }
.icon-btn.sync:hover:not(:disabled) { color: #3b82f6; border-color: #3b82f6; }
.icon-btn.edit:hover:not(:disabled) { color: #f59e0b; border-color: #f59e0b; }
.icon-btn.log.active, .icon-btn.log:hover:not(:disabled) { color: #8b5cf6; border-color: #8b5cf6; }
.icon-btn.delete:hover:not(:disabled) { color: #ef4444; border-color: #ef4444; }
.icon-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.log-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-weight: 600; font-size: 12px; color: var(--text-secondary); }

.create-card { display: flex; flex-direction: column; gap: 12px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px; margin-bottom: 14px; background: var(--bg-card); }
.collapse-block { border: 1px solid var(--border); border-radius: var(--radius-md); margin-bottom: 12px; overflow: hidden; background: var(--bg-card); }
.collapse-head { width: 100%; display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: var(--bg-input); border: none; cursor: pointer; font-size: var(--text-base); font-weight: 600; color: var(--text-primary); text-align: left; }
.collapse-head:hover { background: var(--bg-hover); }
.collapse-icon { font-size: 12px; color: var(--text-muted); }
.collapse-body { padding: 14px 16px; border-top: 1px solid var(--border); }
.admin-subtabs { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
.asub { padding: 6px 14px; border-radius: 99px; border: 1px solid var(--border); background: var(--bg-input); color: var(--text-secondary); font-size: 12.5px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.asub.active { background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 600; }
.asub .badge { min-width: 16px; height: 16px; padding: 0 4px; border-radius: 8px; background: #ef4444; color: #fff; font-size: 10px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; }
.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-size: 12.5px; color: var(--text-muted); }
.proj-checks { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 4px 0; }
.field-label { font-size: 12px; color: var(--text-muted); }
.user-proj { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.type-tag { padding: 2px 8px; border-radius: var(--radius-sm); font-size: 11px; font-weight: 600; background: var(--bg-card); color: var(--text-secondary); border: 1px solid var(--border-light); }
.type-tag.live { color: var(--accent); }
.log-box { background: var(--bg-input); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 12px; max-height: 200px; overflow-y: auto; }
.log-line { font-size: 12.5px; color: var(--text-primary); font-family: var(--font-mono); line-height: 1.7; word-break: break-all; }
.cat-proj { font-size: 11.5px; color: var(--text-muted); }
.rename-input {
  height: 32px; padding: 0 10px; max-width: 240px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary); font-size: var(--text-sm);
}
.rename-input:focus { outline: none; border-color: var(--accent); }
.empty-inline { padding: 24px 0; text-align: center; color: var(--text-muted); font-size: 13px; }
.entry-empty { padding: 12px 0; font-size: var(--text-sm); color: var(--text-muted); }

.proxy-test-result {
  margin: 12px 0; padding: 10px 14px; border-radius: var(--radius-sm);
  font-size: 13.5px; font-weight: 500; line-height: 1.5;
}
.proxy-test-result.ok {
  background: rgba(34, 197, 94, 0.12); color: #16a34a;
  border: 1px solid rgba(34, 197, 94, 0.35);
}
.proxy-test-result.fail {
  background: rgba(239, 68, 68, 0.12); color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.35);
}
[data-theme="dark"] .proxy-test-result.ok {
  color: #4ade80; background: rgba(74, 222, 128, 0.15); border-color: rgba(74, 222, 128, 0.35);
}
[data-theme="dark"] .proxy-test-result.fail {
  color: #f87171; background: rgba(248, 113, 113, 0.15); border-color: rgba(248, 113, 113, 0.35);
}

.version-footer { text-align: center; padding: 18px 0 8px; font-size: 12px; color: var(--text-muted); font-family: var(--font-mono); }

@media (max-width: 640px) {
  .page-inner { padding: 14px 12px; }
}
.proxy-entries-card { margin-top: var(--space-4); }
.proxy-entries-card h4 { margin-bottom: 4px; }
.entry-add-row select { height: 34px; padding: 0 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-light); background: var(--bg-input); color: var(--text-primary); }
.type-tag.sub { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
.type-tag.play-tag { background: rgba(168, 85, 247, 0.15); color: #a855f7; }
.entry-remove {
  padding: 3px 10px; border-radius: var(--radius-sm); border: 1px solid var(--border-light);
  background: var(--bg-input); color: var(--text-secondary); font-size: var(--text-xs); cursor: pointer;
}
.entry-remove:hover { border-color: var(--error); color: var(--error); }
</style>
