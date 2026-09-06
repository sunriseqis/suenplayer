<template>
  <div class="settings-view">
    <div class="page-inner">
      <h2 class="page-title">项目设置</h2>

      <!-- B1: 分组标签页 -->
      <div class="group-tabs">
        <button v-for="g in GROUPS" :key="g.key" class="gtab"
                :class="{ active: tab === g.key }" @click="tab = g.key">{{ g.label }}</button>
      </div>

      <!-- ============ 数据源管理 ============ -->
      <section class="panel" v-if="tab === 'sources'">
        <div class="panel-header-line">
          <div>
            <h3>数据源管理</h3>
            <p class="panel-sub">管理已导入与已配置的全部影视产物和直播源（共 {{ autoConfigs.length }} 个）。支持按源独立切换「是否启用代理」、一键同步更新，以及删除时联动清理关联数据。</p>
          </div>
          <div class="head-actions">
            <button class="btn secondary sm" :disabled="busy" @click="loadAuto">刷新列表</button>
            <button class="btn primary sm" @click="toggleAutoForm">{{ showAutoForm ? '收起表单' : (autoEditing ? '取消编辑' : '新增数据源') }}</button>
          </div>
        </div>

        <!-- 新增/编辑数据源表单 -->
        <form class="create-card" v-if="showAutoForm" @submit.prevent="saveAuto">
          <h4>{{ autoEditing ? '编辑数据源' : '新增数据源' }}</h4>
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
            <label class="field check-field"><span>源拉取代理</span>
              <label class="check-item"><input type="checkbox" v-model="autoForm.proxy_pull" /> 拉取/更新元数据时走代理</label>
            </label>
            <label class="field check-field"><span>流播放代理</span>
              <label class="check-item"><input type="checkbox" v-model="autoForm.proxy_play" /> 视频/直播播放中转时走代理</label>
            </label>
          </div>
          <div class="panel-actions">
            <button class="btn primary" type="submit" :disabled="busy">{{ autoEditing ? '保存修改' : '保存并添加到数据源' }}</button>
            <button class="btn secondary" type="button" @click="toggleAutoForm">取消</button>
          </div>
        </form>

        <!-- 数据源表格（紧凑视图：不换行、无横向溢出） -->
        <div class="sources-table-wrap" v-if="autoConfigs.length">
          <table class="sources-table compact">
            <thead>
              <tr>
                <th style="min-width: 130px;">数据源</th>
                <th style="width: 75px; text-align: center;">数据量</th>
                <th style="width: 75px; text-align: center;" title="拉取/更新元数据时是否走代理">拉取代理</th>
                <th style="width: 75px; text-align: center;" title="视频/直播播放中转时是否走代理">播放代理</th>
                <th style="width: 75px; text-align: center;" title="最近一次同步状态">同步状态</th>
                <th style="width: 125px; text-align: right;">操作</th>
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
                <td style="text-align: center;">
                  <span class="item-count-compact">{{ c.item_count != null ? (c.item_count + (c.source_type === 'live' ? ' 频道' : ' 条')) : '-' }}</span>
                </td>
                <td style="text-align: center;">
                  <button type="button" class="proxy-badge-btn" :class="{ active: isPullProxied(c) }"
                          @click="toggleSourceProxyPull(c)" :disabled="busy"
                          :title="'点击切换源拉取代理（当前：' + (isPullProxied(c) ? '走代理' : '直连') + '）'">
                    {{ isPullProxied(c) ? '代理' : '直连' }}
                  </button>
                </td>
                <td style="text-align: center;">
                  <button type="button" class="proxy-badge-btn play" :class="{ active: isPlayProxied(c) }"
                          @click="toggleSourceProxyPlay(c)" :disabled="busy"
                          :title="'点击切换播放代理（当前：' + (isPlayProxied(c) ? '走代理' : '直连') + '）'">
                    {{ isPlayProxied(c) ? '代理' : '直连' }}
                  </button>
                </td>
                <td style="text-align: center;">
                  <div class="status-indicator-wrap" :title="getStatusTooltip(c)">
                    <span class="status-dot" :class="statusKind(c)"></span>
                    <span class="status-text-compact">{{ statusLabel(c) }}</span>
                  </div>
                </td>
                <td style="text-align: right;">
                  <div class="icon-actions">
                    <button class="icon-btn sync" :disabled="busy" @click="triggerAuto(c)" title="立即同步">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                    </button>
                    <button class="icon-btn edit" :disabled="busy" @click="editAuto(c)" title="编辑配置">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <button class="icon-btn log" :class="{ active: logConfigId === c.id }" :disabled="busy" @click="loadLogs(c)" title="查看同步日志">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                    </button>
                    <button class="icon-btn delete" :disabled="busy" @click="confirmDeleteSource(c)" title="删除数据源">
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
          暂无被管理的数据源。可在「导入工作台」导入产物（导入后将自动加入本列表），或点击右上角「新增数据源」直接添加。
        </div>
      </section>

      <!-- ============ 导入工作台 ============ -->
      <section class="panel" v-if="tab === 'import'">
        <h3>导入工作台</h3>
        <p class="panel-sub">产物托管在 GitHub（git 仓库路径）、直播项目托管在服务器（直链地址）。粘贴远端地址后先拉取预览（只读分析，不写库不导入），确认文件清单、分卷归并、项目归属与直播频道预估无误后再执行导入。导入成功后将自动登记至「数据源管理」。</p>

        <div class="import-form">
          <label class="field">
            <span>远端地址（git 仓库路径 / GitHub 目录 / GitHub 单文件 / 直链 JSON）</span>
            <input v-model.trim="imp.url" placeholder="https://github.com/user/repo 或 https://example.com/data.json" @input="detectType" />
          </label>
          <div class="type-line" v-if="imp.url">
            识别类型：<strong>{{ typeLabel }}</strong>
          </div>
          <div class="form-row">
            <label class="field grow"><span>数据路径（可选，留空自动深度探测）</span><input v-model.trim="imp.data_path" /></label>
            <label class="field check-field"><span>该源走代理</span>
              <select v-model="imp.use_proxy">
                <option value="">跟随全局代理</option>
                <option value="1">强制走代理</option>
                <option value="0">不走代理</option>
              </select>
            </label>
          </div>
          <div class="panel-actions">
            <button class="btn secondary" :disabled="!imp.url || previewBusy || busy" @click="runPreview">{{ previewBusy ? '预览拉取中…' : '拉取预览' }}</button>
            <button class="btn primary" :disabled="!preview || busy || previewBusy" @click="runImport">{{ busy ? '导入中…' : '确认无误，执行导入' }}</button>
          </div>
          <p class="preview-hint" v-if="preview">预览为只读分析结果，不写入任何数据；确认清单无误后再执行导入。</p>
          <div class="preview-error" v-if="previewError">{{ previewError }}</div>
        </div>

        <!-- 预览结果 -->
        <div class="preview-result" v-if="preview">
          <h4>预览结果</h4>
          <div class="pv-meta">
            <span>地址类型：<strong>{{ addressTypeLabel(preview.address_type) }}</strong></span>
            <span v-if="preview.fetch_method">拉取方式：<strong>{{ preview.fetch_method }}</strong></span>
            <span>扫描文件：<strong>{{ preview.scanned || 0 }}</strong></span>
          </div>

          <!-- 分卷归并 -->
          <div class="pv-section" v-if="preview.groups && preview.groups.length">
            <div class="pv-title">分卷归并（{{ preview.groups.length }} 组）</div>
            <div class="pv-group" v-for="g in preview.groups" :key="g.base_name">
              <div class="pv-group-head">
                <strong>{{ (g.project && g.project.name) || g.base_name }}</strong>
                <span class="pv-tag">{{ g.volume_count > 1 ? (g.volume_count + ' 卷归并') : '单卷' }}</span>
                <span class="pv-tag">{{ g.items }} 条</span>
                <span class="pv-tag" :class="{ ok: g.project && g.project.exists }">
                  {{ g.project && g.project.exists ? ('沿用已有项目 ' + (g.project.slug || '')) : '将新建项目' }}
                </span>
              </div>
              <div class="pv-files" v-if="g.volumes && g.volumes.length">{{ g.volumes.join('、') }}</div>
            </div>
          </div>

          <!-- 文件清单 -->
          <div class="pv-section" v-if="preview.files && preview.files.length">
            <div class="pv-title">文件清单（{{ preview.files.length }}）</div>
            <div class="pv-file" v-for="f in preview.files" :key="f.name">
              <span class="pv-file-name">{{ f.name }}</span>
              <span class="pv-tag" :class="f.type">{{ fileKind(f) }}</span>
              <span class="pv-tag" v-if="f.type === 'video'">{{ f.items }} 条</span>
              <span class="pv-tag" v-if="f.type === 'live' && f.channels != null">频道 {{ f.channels }} · 源 {{ f.sources }}</span>
              <span class="pv-tag" v-if="f.volume_group">分卷 {{ f.volume_group }}</span>
              <span class="pv-tag" v-if="f.project">{{ f.project.exists ? '已有项目' : '新建项目' }} · {{ f.project.name }}</span>
              <span class="pv-file-err" v-if="f.error">{{ f.error }}</span>
            </div>
          </div>

          <!-- 直播频道预估 -->
          <div class="pv-section" v-if="preview.live && preview.live.file_count">
            <div class="pv-title">直播源预估</div>
            <div class="pv-group-head">
              <span class="pv-tag live">直播文件 {{ preview.live.file_count }}</span>
              <span class="pv-tag live">频道 {{ preview.live.channels }}</span>
              <span class="pv-tag live">源 {{ preview.live.sources }}</span>
            </div>
          </div>

          <!-- 报错（原样展示） -->
          <div class="pv-section" v-if="preview.errors && preview.errors.length">
            <div class="pv-title pv-err-title">报错（{{ preview.errors.length }}）</div>
            <div class="pv-err-line" v-for="(e, i) in preview.errors" :key="i">{{ typeof e === 'string' ? e : ((e.file || e.name || '') + '：' + (e.error || e.message || JSON.stringify(e))) }}</div>
          </div>
        </div>

        <!-- 三级结果反馈 -->
        <div class="import-result" v-if="importResult">
          <h4>导入结果</h4>
          <div class="res-stats">
            <div class="res-item"><span class="res-num ok">{{ importResult.videos_added || 0 }}</span><span>新增视频</span></div>
            <div class="res-item"><span class="res-num">{{ importResult.videos_updated || 0 }}</span><span>更新视频</span></div>
            <div class="res-item"><span class="res-num">{{ importResult.live_channels || 0 }}</span><span>直播频道</span></div>
            <div class="res-item"><span class="res-num">{{ importResult.live_sources || 0 }}</span><span>直播源</span></div>
            <div class="res-item" v-if="importResult.scanned"><span class="res-num">{{ importResult.scanned }}</span><span>扫描文件数</span></div>
          </div>
          <div class="res-errors" v-if="importResult.errors?.length">
            <div class="res-err-title">必填缺失 / 报错（{{ importResult.errors.length }}）</div>
            <div class="res-err-item" v-for="(e, i) in importResult.errors.slice(0, 10)" :key="i">{{ e }}</div>
          </div>
          <div class="res-warn" v-if="importResult.method">
            <div class="res-err-title">降级信息</div>
            <div class="res-err-item">拉取方式：{{ importResult.method }}（推荐字段缺失时已按三级策略降级处理，不影响导入）</div>
          </div>
          <div class="panel-actions">
            <button class="btn secondary" @click="tab = 'sources'">前往「数据源管理」查看并管理</button>
          </div>
        </div>

        <!-- 本地路径导入直播源（服务器本地文件） -->
        <div class="local-live">
          <h4>服务器本地直播 JSON 导入</h4>
          <div class="form-row">
            <label class="field grow"><span>服务器上的文件路径</span><input v-model.trim="livePath" placeholder="/data/live.json" /></label>
            <button class="btn primary self-end" :disabled="!livePath || busy" @click="importLive">导入直播源</button>
          </div>
        </div>
      </section>

      <!-- ============ 代理 ============ -->
      <section class="panel" v-if="tab === 'proxy'">
        <h3>代理配置</h3>
        <p class="panel-sub">全局代理服务与双通道开关配置。支持为「源拉取」（Git 克隆、远端元数据抓取）与「流媒体播放」（点播视频代理、直播流代理中转）分别设定默认策略与分源开关。</p>
        <div class="form-row">
          <label class="field grow"><span>代理地址</span><input v-model.trim="proxyAddr" placeholder="http://127.0.0.1:7890 或 socks5://…" /></label>
          <label class="field target-field"><span>测试目标（可选）</span><input v-model.trim="proxyTestTarget" placeholder="默认: https://www.google.com/generate_204" /></label>
          <button class="btn primary self-end" :disabled="busy" @click="saveProxy">保存设置</button>
          <button class="btn secondary self-end" :disabled="busy" @click="testProxy">{{ testing ? '测试中…' : '测试连通' }}</button>
        </div>
        <div class="form-row">
          <label class="field grow"><span>Git 访问令牌（可选，拉取私有仓库时填写）</span><input v-model.trim="gitToken" type="password" autocomplete="off" placeholder="ghp_… / ghp_xxx，留空表示仅公开仓库" /></label>
          <label class="field target-field"><span>DoH 服务（DNS 防污染，可选）</span><input v-model.trim="dohUrl" placeholder="https://223.5.5.5/resolve" /></label>
        </div>
        <div class="form-row">
          <label class="field grow"><span>hosts 映射（每行「IP 域名」，仅作用于封面抓取，优先于 DoH）</span><textarea v-model.trim="hostsMap" rows="3" placeholder="185.13.109.141 image.jinyingimage.com&#10;37.77.87.202 img.lzipic.com"></textarea></label>
        </div>
        <div class="proxy-test-result" v-if="proxyTestResult" :class="{ ok: proxyTestResult.ok, fail: !proxyTestResult.ok }">
          {{ proxyTestResult.ok ? '连通正常' : ('测试失败：' + (proxyTestResult.error || '未知错误')) }}
        </div>

        <!-- 全局默认开关 -->
        <div class="proxy-defaults-card">
          <h4>全局默认策略</h4>
          <div class="form-row defaults-row">
            <label class="check-item">
              <input type="checkbox" v-model="proxyPullDefault" @change="saveProxy" />
              <span>源拉取默认走代理（未单独指定的数据源拉取 Git / JSON 时生效）</span>
            </label>
            <label class="check-item">
              <input type="checkbox" v-model="proxyPlayDefault" @change="saveProxy" />
              <span>播放默认走代理（未单独指定的视频 / 直播流播放时生效）</span>
            </label>
          </div>
        </div>

        <div class="proxy-sources" v-if="autoConfigs.length">
          <h4>按源独立控制（覆盖全局默认）</h4>
          <div class="sources-table-wrap">
            <table class="sources-table compact">
              <thead>
                <tr>
                  <th style="min-width: 140px;">数据源名称</th>
                  <th style="width: 70px; text-align: center;">类别</th>
                  <th style="width: 90px; text-align: center;">源拉取代理</th>
                  <th style="width: 90px; text-align: center;">播放代理</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in autoConfigs" :key="c.id">
                  <td>
                    <strong class="source-name" :title="'完整地址：' + c.source_path">{{ c.name }}</strong>
                  </td>
                  <td style="text-align: center;">
                    <span class="type-tag sm" :class="c.source_type">{{ c.source_type === 'live' ? '直播' : '影视' }}</span>
                  </td>
                  <td style="text-align: center;">
                    <button type="button" class="proxy-badge-btn" :class="{ active: isPullProxied(c) }"
                            @click="toggleSourceProxyPull(c)" :disabled="busy">
                      {{ isPullProxied(c) ? '走代理' : '直连' }}
                    </button>
                  </td>
                  <td style="text-align: center;">
                    <button type="button" class="proxy-badge-btn play" :class="{ active: isPlayProxied(c) }"
                            @click="toggleSourceProxyPlay(c)" :disabled="busy">
                      {{ isPlayProxied(c) ? '走代理' : '直连' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- ============ 分类管理 ============ -->
      <section class="panel" v-if="tab === 'cats'">
        <h3>分类管理</h3>
        <p class="panel-sub">维护各项目的一级 / 二级分类。拖拽与箭头排序在项目页内操作（自动保存）。</p>
        <div class="form-row">
          <label class="field"><span>新一级分类</span><input v-model.trim="newCat.name" placeholder="分类名" /></label>
          <label class="field"><span>所属项目</span>
            <select v-model="newCat.project_id">
              <option v-for="p in store.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
          <button class="btn primary self-end" :disabled="!newCat.name || busy" @click="createCat">创建</button>
        </div>
        <div class="cat-admin-list" v-if="catTree.length">
          <div class="cat-admin-row" v-for="c in catTree" :key="c.id">
            <div class="cat-admin-main">
              <strong>{{ c.name }}</strong>
              <span class="cat-proj">{{ projectName(c.project_id) }}</span>
            </div>
            <div class="cat-admin-actions">
              <button class="btn ghost sm" @click="renameCat(c)">重命名</button>
              <button class="btn danger sm" @click="deleteCat(c)">删除</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 规则中心 ============ -->
      <section class="panel" v-if="tab === 'rules'">
        <h3>规则中心</h3>
        <p class="panel-sub">合并 / 转移规则按项目累积存储，每次导入后自动重放；删除规则后，下一次导入将不再应用该规则。</p>
        <div class="rule-list" v-if="rules.length">
          <div class="rule-row" v-for="r in rules" :key="r.id">
            <div class="rule-main">
              <span class="type-tag" :class="r.rule_type">{{ r.rule_type === 'merge' ? '合并' : '转移' }}</span>
              <span class="rule-desc">{{ ruleDesc(r) }}</span>
              <span class="cat-proj">{{ projectName(r.project_id) }}</span>
            </div>
            <button class="btn danger sm" :disabled="busy" @click="removeRule(r)">删除规则</button>
          </div>
        </div>
        <div class="empty-inline" v-else>暂无规则。在项目页使用"合并 / 批量转移"后会在这里累积。</div>
      </section>

      <!-- ============ 账号安全 ============ -->
      <section class="panel" v-if="tab === 'security'">
        <h3>账号安全</h3>
        <div class="form-grid">
          <label class="field"><span>修改用户名（当前：{{ store.currentUser?.username }}）</span>
            <input v-model.trim="sec.username" :placeholder="store.currentUser?.username" />
          </label>
          <button class="btn primary self-end" :disabled="!sec.username || busy" @click="doChangeUsername">更新用户名</button>
        </div>
        <div class="form-grid">
          <label class="field"><span>当前密码</span><input v-model="sec.oldPassword" type="password" /></label>
          <label class="field"><span>新密码（至少 6 位）</span><input v-model="sec.newPassword" type="password" /></label>
          <button class="btn primary self-end" :disabled="!sec.oldPassword || !sec.newPassword || busy" @click="doChangePassword">修改密码</button>
        </div>
        <div class="panel-actions">
          <button class="btn danger" @click="doLogout">退出登录</button>
        </div>
      </section>

      <!-- 版本号：唯一来源为后端 APP_VERSION（/api/stats），前端不自造 -->
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
  { key: 'import', label: '导入工作台' },
  { key: 'proxy', label: '代理配置' },
  { key: 'cats', label: '分类管理' },
  { key: 'rules', label: '规则中心' },
  { key: 'security', label: '账号安全' }
]
const tab = ref('sources')
const busy = ref(false)

const proxyPullDefault = ref(false)
const proxyPlayDefault = ref(false)

/* 代理配置加载 */
async function loadProxyConfig() {
  try {
    const s = await store.fetchAdminSettings()
    proxyAddr.value = s.proxy || ''
    gitToken.value = s.token || ''
    dohUrl.value = s.doh_url || ''
    hostsMap.value = s.hosts_map || ''
    proxyPullDefault.value = !!s.proxy_pull_default
    proxyPlayDefault.value = !!s.proxy_play_default
    const ps = s.proxy_sources || {}
    const map = {}
    for (const [k, v] of Object.entries(ps)) {
      if (v && typeof v === 'object') {
        map[k] = { pull: !!v.pull, play: !!v.play }
      } else {
        map[k] = { pull: !!v, play: false }
      }
    }
    proxySources.value = map
  } catch (e) {
    ui.toast(e.message || '设置加载失败（需要管理员身份）', 'error')
  }
}

/* 导入工作台 */
const imp = reactive({ url: '', data_path: '', use_proxy: '' })
const importResult = ref(null)
const livePath = ref('')
const preview = ref(null)
const previewBusy = ref(false)
const previewError = ref('')

const ADDRESS_TYPE_LABELS = {
  github_tree: 'GitHub 目录',
  github_blob: 'GitHub 单文件',
  direct_json_url: '直链 JSON',
  github_repo: 'GitHub 仓库',
  git_repo: 'git 仓库'
}
function addressTypeLabel(t) { return ADDRESS_TYPE_LABELS[t] || (t || '未知') }
function fileKind(f) {
  if (f.type === 'video') return '视频 JSON'
  if (f.type === 'live') return '直播 JSON'
  return '解析失败'
}

async function runPreview() {
  previewBusy.value = true
  previewError.value = ''
  preview.value = null
  try {
    const payload = { url: imp.url, data_path: imp.data_path }
    if (imp.use_proxy !== '') payload.use_proxy = imp.use_proxy === '1'
    preview.value = await store.importRemotePreview(payload)
  } catch (e) {
    previewError.value = e.message || '预览拉取失败，请检查地址后重试'
  }
  previewBusy.value = false
}

const TYPE_RULES = [
  { key: 'github_dir', label: 'GitHub 网页目录', test: u => /github\.com\/[^/]+\/[^/]+\/tree\//.test(u) },
  { key: 'github_file', label: 'GitHub 单文件', test: u => /github\.com\/[^/]+\/[^/]+\/blob\//.test(u) },
  { key: 'github_repo', label: '标准 GitHub 仓库', test: u => /^https?:\/\/github\.com\/[^/]+\/[^/]+\/?$/.test(u) },
  { key: 'git_repo', label: '普通 git 仓库', test: u => /^https?:\/\/.+\.git$/.test(u) || /^git@/.test(u) },
  { key: 'direct_json', label: '直链 JSON', test: u => /^https?:\/\//.test(u) }
]
const typeLabel = computed(() => {
  for (const r of TYPE_RULES) if (r.test(imp.url)) return r.label
  return '无法识别（请检查地址）'
})

function detectType() { /* 计算属性即时识别 */ }

// 地址或参数变化后，旧预览结果作废，需重新拉取
watch(() => imp.url, () => { preview.value = null; previewError.value = '' })
watch(() => imp.data_path, () => { preview.value = null; previewError.value = '' })
watch(() => imp.use_proxy, () => { preview.value = null; previewError.value = '' })

async function runImport() {
  if (!preview.value) { ui.toast('请先拉取预览并确认清单后再导入', 'error'); return }
  const ok = await ui.confirm(`确认按预览清单从「${imp.url}」执行导入？`, { title: '执行导入' })
  if (!ok) return
  busy.value = true
  try {
    const payload = { url: imp.url, data_path: imp.data_path }
    if (imp.use_proxy !== '') payload.use_proxy = imp.use_proxy === '1'
    const d = await store.importRemote(payload)
    importResult.value = d
    if (d.ok) {
      ui.toast(`导入完成：新增 ${d.videos_added || 0}、更新 ${d.videos_updated || 0}、直播频道 ${d.live_channels || 0}`, 'success', 5000)
      store.fetchStats().catch(() => {})
    } else {
      ui.toast('导入完成但有报错，请查看结果明细', 'error', 5000)
    }
  } catch (e) {
    ui.toast(e.message || '导入失败', 'error', 5000)
  }
  busy.value = false
}

async function importLive() {
  busy.value = true
  try {
    await store.importLiveAdmin(livePath.value)
    ui.toast('直播源导入完成', 'success')
  } catch (e) {
    ui.toast(e.message || '直播源导入失败', 'error', 5000)
  }
  busy.value = false
}

function goAutoUpdate() {
  autoForm.name = '导入源自动更新'
  autoForm.source_type = 'video'
  autoForm.source_path = imp.url
  autoForm.use_proxy = imp.use_proxy === '1'
  showAutoForm.value = true
  tab.value = 'sources'
  ui.toast('已带入导入地址，确认周期后保存即可', 'info')
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
  proxy_play: false,
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
  if (showAutoForm.value && !autoEditing.value) { showAutoForm.value = false; return }
  if (autoEditing.value) { autoEditing.value = null; showAutoForm.value = false; return }
  Object.assign(autoForm, {
    name: '',
    source_type: 'video',
    source_path: '',
    update_interval: 60,
    proxy_pull: false,
    proxy_play: false,
  })
  showAutoForm.value = true
}

async function saveAuto() {
  if (!autoForm.name || !autoForm.source_path) { ui.toast('请填写名称与产物地址', 'error'); return }
  busy.value = true
  try {
    const payload = {
      name: autoForm.name,
      source_type: autoForm.source_type,
      source_path: autoForm.source_path,
      update_interval: autoForm.update_interval,
      proxy_pull: autoForm.proxy_pull ? 1 : 0,
      proxy_play: autoForm.proxy_play ? 1 : 0,
      use_proxy: autoForm.proxy_pull ? 1 : 0,
    }
    if (autoEditing.value) {
      await store.updateAutoUpdate(autoEditing.value.id, payload)
      ui.toast('配置已更新', 'success')
    } else {
      await store.createAutoUpdate(payload)
      ui.toast('数据源已创建', 'success')
    }
    showAutoForm.value = false
    autoEditing.value = null
    await loadAuto()
  } catch (e) {
    ui.toast(e.message || '保存失败', 'error')
  }
  busy.value = false
}

function editAuto(c) {
  autoEditing.value = c
  Object.assign(autoForm, {
    name: c.name,
    source_type: c.source_type,
    source_path: c.source_path,
    update_interval: c.update_interval,
    proxy_pull: c.proxy_pull != null ? !!c.proxy_pull : !!c.use_proxy,
    proxy_play: !!c.proxy_play,
  })
  showAutoForm.value = true
}

async function triggerAuto(c) {
  busy.value = true
  try {
    await store.triggerAutoUpdate(c.id)
    ui.toast(`「${c.name}」已触发同步，正在后台执行`, 'success')
    setTimeout(() => { loadAuto() }, 1500)
  } catch (e) {
    ui.toast(e.message || '触发失败', 'error')
  }
  busy.value = false
}

function isPullProxied(c) {
  if (c.proxy_pull != null) return !!c.proxy_pull
  if (c.use_proxy != null) return !!c.use_proxy
  return !!proxyPullDefault.value
}

function isPlayProxied(c) {
  if (c.proxy_play != null) return !!c.proxy_play
  return !!proxyPlayDefault.value
}

async function toggleSourceProxyPull(c) {
  const currentVal = c.proxy_pull != null ? c.proxy_pull : (c.use_proxy ? 1 : 0)
  const newVal = currentVal ? 0 : 1
  try {
    await store.updateAutoUpdate(c.id, { proxy_pull: newVal, use_proxy: newVal })
    c.proxy_pull = newVal
    c.use_proxy = newVal
    ui.toast(`已将「${c.name}」源拉取切换为${newVal ? '走代理' : '直连'}`, 'success')
  } catch (e) {
    ui.toast(e.message || '修改代理设置失败', 'error')
  }
}

async function toggleSourceProxyPlay(c) {
  const currentVal = c.proxy_play ? 1 : 0
  const newVal = currentVal ? 0 : 1
  try {
    await store.updateAutoUpdate(c.id, { proxy_play: newVal })
    c.proxy_play = newVal
    ui.toast(`已将「${c.name}」播放切换为${newVal ? '走代理' : '直连'}`, 'success')
  } catch (e) {
    ui.toast(e.message || '修改播放代理设置失败', 'error')
  }
}

function statusLabel(c) {
  const kind = statusKind(c)
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
  const msg = c.source_type === 'live'
    ? `确定删除数据源「${c.name}」？\n点击「确定」将删除该源并同时清理已导入的频道数据；点击「取消」可选择仅删除源配置。`
    : `确定删除数据源「${c.name}」？\n点击「确定」将删除该源并同时清理已导入的视频数据；点击「取消」可选择仅删除源配置。`
  const purge = await ui.confirm(msg, { title: '删除数据源' })
  if (purge) {
    await doDelete(c.id, true)
    return
  }
  const onlyConfig = await ui.confirm(`是否仅删除数据源配置「${c.name}」（保留已入库数据）？`, { title: '仅删除源配置' })
  if (onlyConfig) {
    await doDelete(c.id, false)
  }
}

async function doDelete(id, purgeData) {
  busy.value = true
  try {
    await store.deleteAutoUpdate(id, purgeData)
    ui.toast(purgeData ? '数据源及关联数据已全部清理' : '数据源配置已删除', 'success')
    await loadAuto()
    store.fetchStats().catch(() => {})
  } catch (e) {
    ui.toast(e.message || '删除失败', 'error')
  }
  busy.value = false
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
const proxySources = ref({})
const testing = ref(false)
const proxyTestResult = ref(null)

async function saveProxy() {
  busy.value = true
  try {
    await store.putAdminSettings({
      proxy: proxyAddr.value,
      token: gitToken.value,
      doh_url: dohUrl.value,
      hosts_map: hostsMap.value,
      proxy_pull_default: proxyPullDefault.value ? 1 : 0,
      proxy_play_default: proxyPlayDefault.value ? 1 : 0,
    })
    ui.toast('代理设置已保存', 'success')
  } catch (e) {
    ui.toast(e.message || '保存失败', 'error')
  }
  busy.value = false
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

async function saveProxySources() {
  try {
    await store.putAdminSettings({ proxy_sources: { ...proxySources.value } })
    ui.toast('按源代理设置已保存', 'success')
  } catch (e) {
    ui.toast(e.message || '保存失败', 'error')
  }
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
  busy.value = true
  try {
    await store.createCategory(newCat.name, null, newCat.project_id)
    ui.toast('一级分类已创建', 'success')
    newCat.name = ''
    await loadCats()
  } catch (e) {
    ui.toast(e.message || '创建失败', 'error')
  }
  busy.value = false
}

async function renameCat(c) {
  // 分类重命名在项目页通过拖拽/箭头与规则流程覆盖；此处仅提示
  ui.toast('分类名称由导入 JSON 决定，可在项目页整理工具中调整归属', 'info')
}

async function deleteCat(c) {
  const ok = await ui.confirm(`确定删除分类「${c.name}」？`, { danger: true })
  if (!ok) return
  busy.value = true
  try {
    await store.deleteCategory(c.id)
    ui.toast('分类已删除', 'success')
    await loadCats()
  } catch (e) {
    ui.toast(e.message || '删除失败', 'error')
  }
  busy.value = false
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
  busy.value = true
  try {
    await store.deleteRule(r.id)
    ui.toast('规则已删除', 'success')
    await loadRules()
  } catch (e) {
    ui.toast(e.message || '删除失败', 'error')
  }
  busy.value = false
}

/* 账号安全 */
const sec = reactive({ username: '', oldPassword: '', newPassword: '' })

async function doChangeUsername() {
  busy.value = true
  try {
    await store.changeUsername(sec.username)
    ui.toast('用户名已更新，下次登录请使用新用户名', 'success', 5000)
    sec.username = ''
  } catch (e) {
    ui.toast(e.message || '修改失败', 'error')
  }
  busy.value = false
}

async function doChangePassword() {
  if (sec.newPassword.length < 6) { ui.toast('新密码至少 6 位', 'error'); return }
  busy.value = true
  try {
    await store.changePassword(sec.oldPassword, sec.newPassword)
    ui.toast('密码已修改', 'success')
    sec.oldPassword = ''
    sec.newPassword = ''
  } catch (e) {
    ui.toast(e.message || '修改失败', 'error')
  }
  busy.value = false
}

async function doLogout() {
  await store.logout()
  router.push('/login')
}

watch(tab, (t) => {
  if (t === 'sources' || t === 'proxy') loadAuto()
  if (t === 'cats') loadCats()
  if (t === 'rules') loadRules()
})

onMounted(async () => {
  await loadProxyConfig()
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
.panel-sub { margin: 0 0 16px; font-size: var(--text-base); line-height: 1.7; color: var(--text-secondary); }

.form-grid { display: flex; flex-direction: column; gap: 12px; margin-bottom: 14px; }
.form-row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 12px; }
.field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 180px; }
.field.grow { flex: 2; }
.target-field { min-width: 240px; flex: 1.5; }
.field span { font-size: var(--text-base); font-weight: 500; color: var(--text-secondary); }
.field input, .field select {
  height: 38px; padding: 0 12px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary); font-size: var(--text-base);
  box-sizing: border-box; width: 100%;
  transition: border-color var(--duration-fast), box-shadow var(--duration-fast);
}
.field input:focus, .field select:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(255, 71, 87, 0.18);
}
.field input::placeholder {
  color: var(--text-muted);
  font-size: var(--text-sm);
  opacity: 0.85;
}
.check-field select { min-width: 150px; }
.check-item { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-base); color: var(--text-secondary); cursor: pointer; height: 38px; }
.self-end { align-self: flex-end; margin-bottom: 12px; }

.panel-actions { display: flex; gap: 10px; margin-top: 10px; }

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

.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-size: 13px; color: var(--text-muted); }
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
.source-info-compact { display: flex; align-items: center; gap: 6px; cursor: help; }
.source-name { font-weight: 600; color: var(--text-primary); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13.5px; }
.type-tag.sm { padding: 1px 5px; font-size: 10.5px; border-radius: 4px; }
.item-count-compact { font-size: 12px; color: var(--text-secondary); font-family: var(--font-mono); }

.proxy-badge-btn {
  display: inline-block; padding: 2px 8px; font-size: 11px; font-weight: 600;
  border-radius: 99px; border: 1px solid var(--border-light); background: var(--bg-card);
  color: var(--text-muted); cursor: pointer; transition: all 0.15s ease;
}
.proxy-badge-btn:hover { border-color: var(--accent); color: var(--accent); }
.proxy-badge-btn.active { background: rgba(59, 130, 246, 0.15); border-color: rgba(59, 130, 246, 0.4); color: #3b82f6; }
.proxy-badge-btn.play.active { background: rgba(168, 85, 247, 0.15); border-color: rgba(168, 85, 247, 0.4); color: #a855f7; }

.status-indicator-wrap { display: inline-flex; align-items: center; gap: 5px; cursor: help; user-select: none; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: var(--text-muted); }
.status-dot.ok { background: #22c55e; box-shadow: 0 0 5px rgba(34, 197, 94, 0.5); }
.status-dot.fail { background: #ef4444; box-shadow: 0 0 5px rgba(239, 68, 68, 0.5); }
.status-dot.partial { background: #f59e0b; box-shadow: 0 0 5px rgba(245, 158, 11, 0.5); }
.status-dot.pending { background: #94a3b8; }
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

.proxy-defaults-card { margin: 16px 0; padding: 12px 14px; background: var(--bg-card); border: 1px solid var(--border-light); border-radius: var(--radius-md); }
.proxy-defaults-card h4 { margin: 0 0 8px; font-size: 13.5px; color: var(--text-primary); }
.defaults-row { display: flex; gap: 20px; flex-wrap: wrap; }

.source-title { display: flex; align-items: center; gap: 8px; }
.source-path-cell { max-width: 280px; }
.source-path { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-mono); font-size: 12.5px; color: var(--text-secondary); }
.item-count-badge { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 12px; font-weight: 600; background: var(--bg-input); color: var(--text-primary); font-family: var(--font-mono); }

.proxy-toggle { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; font-size: 12.5px; user-select: none; }
.proxy-toggle input { cursor: pointer; }
.toggle-text { color: var(--text-muted); font-size: 12px; }
.toggle-text.proxied { color: var(--accent); font-weight: 600; }

.status-cell { display: flex; flex-direction: column; gap: 3px; font-size: 12px; }
.status-cell .run-time { font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); }
.status-cell .last-res { font-size: 11.5px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 170px; }

.action-btns { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }
.action-btns .btn { white-space: nowrap; flex: none; }
.log-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-weight: 600; font-size: 12px; color: var(--text-secondary); }

.create-card { display: flex; flex-direction: column; gap: 12px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px; margin-bottom: 14px; background: var(--bg-card); }
.config-list, .rule-list, .cat-admin-list { display: flex; flex-direction: column; gap: 10px; }
.config-row, .rule-row, .cat-admin-row {
  background: var(--bg-input); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 12px 14px;
  display: flex; flex-direction: column; gap: 8px;
}
.config-main, .rule-main, .cat-admin-main { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.config-name { font-size: 14px; font-weight: 600; color: var(--text-primary); display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.config-meta { font-size: 13px; color: var(--text-secondary); font-family: var(--font-mono); line-height: 1.6; }
.rule-desc { font-size: 13px; color: var(--text-secondary); font-family: var(--font-mono); }
.type-tag { padding: 2px 8px; border-radius: var(--radius-sm); font-size: 11px; font-weight: 600; background: var(--bg-card); color: var(--text-secondary); border: 1px solid var(--border-light); }
.type-tag.live { color: var(--accent); }
.state-tag { padding: 2px 8px; border-radius: var(--radius-sm); font-size: 11px; font-weight: 600; background: var(--error); color: #fff; white-space: nowrap; }
.state-tag.ok { background: var(--success); }
.state-tag.warn { background: var(--warning, #f59e0b); }
.config-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.log-box { background: var(--bg-input); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 12px; max-height: 200px; overflow-y: auto; }
.log-line { font-size: 12.5px; color: var(--text-primary); font-family: var(--font-mono); line-height: 1.7; word-break: break-all; }
.cat-proj { font-size: 11.5px; color: var(--text-muted); }
.cat-admin-actions { display: flex; gap: 8px; }
.empty-inline { padding: 24px 0; text-align: center; color: var(--text-muted); font-size: 13px; }

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
.proxy-sources h4 { margin: 16px 0 8px; }
.ps-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px dashed var(--border-light); gap: 10px; flex-wrap: wrap; }
.ps-name { font-size: 13px; color: var(--text-primary); }

.local-live { border-top: 1px solid var(--border-light); margin-top: 18px; padding-top: 6px; }

.version-footer { text-align: center; padding: 18px 0 8px; font-size: 12px; color: var(--text-muted); font-family: var(--font-mono); }

@media (max-width: 640px) {
  .page-inner { padding: 14px 12px; }
  .self-end { align-self: auto; margin-bottom: 0; }
}
</style>
