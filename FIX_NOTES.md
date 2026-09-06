# suenplayer 完整修复包说明

本包合并了前一轮的 3 个直播缺陷修复与本轮的 4 个 P1 前端问题修复。
覆盖文件：app.py、static/src/views/LiveView.vue、static/src/views/Detail.vue、
static/src/stores/app.js、static/src/router/index.js、static/dist/（重新构建）。

## 一、直播缺陷修复（上一轮，本次合并交付）

1. nextTick 时序（LiveView.vue playCurrent）
   根因：首次起播时 video 元素尚未渲染，videoEl 为 null，必然瞬时失败。
   改法：等待 v-if="currentChannel" 的播放器 DOM 渲染完成后再取 videoEl。
2. Worker 相对 URL（LiveView.vue）
   根因：HTTP 局域网部署下 mpegts.js Worker 相对 URL 解析错误。
   改法：new URL(streamUrl, window.location.origin).href 转绝对 URL。
3. 自动切源 switchLock 死锁 + app.py next-source 逻辑
   根因：fallbackNext 递归 playCurrent 被未释放的锁挡回；后端切源会停用源
   并全量重新激活，导致故障源被再次选中。
   改法：switchLock 在 finally 中先释放；后端 fallback_live_source 保留
   is_active=1、fail_count+1/probe_status='timeout'、去掉重新激活分支；
   LiveView 增加 failedIds 记录失败源避免重复尝试。

## 二、P1 修复（本轮）

### P1-1 离开直播页播放器不销毁
文件：static/src/views/LiveView.vue（约 462-483 行生命周期区）
- 新增 onDeactivated：切走页面时调用 destroyPlayer()（mpegts.js 官方顺序
  pause → unload → detachMediaElement → destroy），并清 playing/statusText。
- 新增 onActivated：回到直播页时若有当前频道，nextTick 后 playCurrent() 重新起播。
- onBeforeUnmount 保留 destroyPlayer() 兜底。
说明：App.vue 的 keep-alive 名单含 LiveView，切走页面不会触发
onBeforeUnmount，必须依赖 onDeactivated 销毁，否则直播流后台持续拉取。

### P1-2 自动切源 switchLock 死锁
已由上一轮修复覆盖，本次核对确认无重复改动：
- LiveView.vue 的 switchLock 在 playCurrent 的 finally 中先释放，fallbackNext
  递归调用 playCurrent 不会被锁挡回；
- LiveView.vue 维护 failedIds（约 77-80、132、190、240、256 行），失败源不再
  重复尝试，与审查报告描述的 fallbackNext 递归场景一致。

### P1-3 token 过期全站静默空白
文件：static/src/stores/app.js
- jfetch 统一检查：r.ok 为假时抛带 status/data 的错误；r.status === 401 时
  调用 onAuthExpired()。
- onAuthExpired()：清本地登录态（logoutLocal），防重入（redirectingLogin
  标记），跳转 /login?redirect=<当前路径+查询>。
- store 新增 logoutLocal()（只清本地状态不调接口），并以 appStoreRef 回填
  供模块级函数使用。
- 12 个原先手动 fetch 的封装统一改走 jfetch：fetchVideos、fetchSeries、
  fetchVideo、fetchSeriesDetail、fetchEpisodeDetail、probePlay、switchPlayLine、
  fetchFreshUrl、fetchUrls、fetchCategoryTree、fetchStats、nextLiveSource。
文件：static/src/router/index.js
- 路由守卫修正：首次导航 checkAuth 后置 authChecked=true；此后每次导航若有
  token 但 store 未登录态（如 token 已过期被清）则重新 checkAuth，
  不再只跑一次。

### P1-4 详情页 saveTags 绕过 authFetch
文件：static/src/views/Detail.vue（约 415-428 行 saveTags）
- 原实现用裸 fetch（无 Authorization 头），HTTP 局域网部署下保存标签必 401。
- 改为走 store.setVideoTags（authFetch 链路），失败时 ui.toast 报错。

## 三、构建

- 前端已用 vite 重新构建（dist 构建时间晚于全部源码修改），dist 与 src 同步；
  API 契约未变，未改动无关功能。

## 四、自测结果

- run_e2e.py 全部通过：流代理 200 且字节连续（TS 同步字节 0x47 每 188 字节）、
  不可达源 0.46s 快速 502、next-source 后 is_active 保持 1、源数不变、
  分组频道列表正常。
- 401 契约实测：无 Authorization → 401“需要登录”；坏 token → 401
  “凭证无效或已过期”；有效 token → 200；标签 PUT 有效 token → 200。
- 浏览器级验证（headless Chromium）：坏 token 访问受保护页 → 跳转
  /login?redirect=...、本地 token 被清除、每次导航守卫生效；
  登录后浏览器页面内直接拉流 /api/live/stream/... → 200 且持续收到数据。

## 五、已知边界

- 沙箱无头 Chromium 中 mpegts.js 播放器加载器不起播（页面内直接 fetch 同一
  流地址可正常收到数据），因此“切走页面后 CDP 统计流字节归零”的完整浏览器
  播放验证未能在沙箱完成；P1-1 的销毁/重建代码已确认进入构建产物
  （onDeactivated/onActivated 回调与 destroyPlayer 销毁序列均在 LiveView chunk），
  请按下方部署验证步骤在真实环境确认。

## 六、部署验证步骤

1. 起服务：python app.py（或 uvicorn app:app），浏览器打开站点并登录。
2. 选频道点播：进入直播页，选一个频道，确认正常起播。
3. 切源观察失败标记：把频道当前源指向一个不可达地址（或断开上游），确认
   自动切源后失败源出现失败标记，且不会反复回到该源。
4. 切走页面确认后台无持续请求：在直播页播放中切到其他页面，打开浏览器
   DevTools Network 过滤 /api/live/stream，确认不再有持续的数据传输；
   切回直播页能重新起播。
5. 改坏 token 验证 401 提示：DevTools 控制台执行
   localStorage.setItem('suen_token','bad-token')，再点任意需要登录的操作，
   确认被跳转到登录页并清除无效 token。
6. 保存标签验证成功：进入任意影片详情页，编辑标签并保存，确认保存成功
   （局域网 HTTP 部署下同样有效）。

---

# v2：9 个 P2 问题修复（本轮新增）

本轮在 P1 修复基础上迭代，全部改动基于 P1 合并后的代码，P1 四项修复
（onDeactivated 销毁播放器、切源失败标记、401 跳登录、保存标签带凭证）均已保留并经构建产物核对未回退。

## 修复清单（文件 + 行号 + 改动说明）

### P2-1 PlayerModal.vue 非 HLS 分支匿名 error 监听器累积
- static/src/components/PlayerModal.vue:281 新增具名函数 onNonHlsError（设置播放错误提示并清除 loading）；
- :293（selectLine/retryProbe 清空 src 前）与 :326（loadVideo 开头）先 removeEventListener('error', onNonHlsError)，再在 :375 非 HLS 分支 addEventListener。同一函数引用可被浏览器去重，反复换线不再累积监听器。

### P2-2 PlayerModal.vue togglePlay 丢弃 play() 的 Promise
- PlayerModal.vue:534-545 togglePlay 改为 el.play().then 置 playing=true、.catch 置 playing=false 并清除 loading，UI 状态跟随真实播放结果，不再出现"点了播放却停在暂停图标"。

### P2-3 hls.js fatal 错误按官方恢复矩阵处理
- LiveView.vue:136-139、379-420 与 PlayerModal.vue:214-215、328-329、350-370：
  新增 hlsNetRetries/hlsMediaRetries 计数与 HLS_MAX_RETRIES=3；fatal NETWORK_ERROR 调 hls.startLoad() 重试、fatal MEDIA_ERROR 调 hls.recoverMediaError()，超过 3 次仍失败才进入原有的 fallbackNext 换源/报错流程。openStream 与 loadVideo 开头均重置计数。

### P2-4 起播成功后断流感知与自动重连
- LiveView.vue:287-341（handleStreamDrop/autoReconnect/clearReconnectTimers/armLiveMonitors/onLiveEnded/onLiveElemError/onLiveStalled）与 :526-535（监听器挂载）：
  ok() 起播成功后挂长期监听（mpegts ERROR、video ended/stalled/error）；stalled 按 STALL_GRACE_MS=8000 结合 readyState 判定真断流。判定断流后显示"信号中断"提示，按指数退避（1s×2^n，上限 15s，最多 MAX_RECONNECT_ATTEMPTS=6 次）自动 reconnectStream()，避免重试风暴；用户手动操作或重连成功即恢复。destroyPlayer 开头清空重连定时器并复位 dropGuard，与 P1 的 onDeactivated 销毁协同，切走页面不会留下幽灵重连。

### P2-5 selectGroup 竞态
- LiveView.vue:149（groupSeq）、199-210：进入时 const mySeq = ++groupSeq，每个 await 之后、写 channels/loading 之前校验 mySeq === groupSeq，过期响应直接丢弃。快速切换分组不再出现高亮与列表错位。

### P2-6 Detail.vue loadDetail 竞态
- Detail.vue:274-328：新增 let loadSeq 与 const seq = ++loadSeq；每个 await 后及最终写 state 前校验 seq === loadSeq，过期响应不写 state、不关 loading。快速切换路由不再出现内容串页。

### P2-7 移动端 / iOS 直播链路
- LiveView.vue:155-161（hasMseSupport/isNoMseEnv）、402-505（openStream 无 MSE 分支重构）、:268（移动端提示）：
  无 MSE 环境（iOS Safari 等）下，HLS 源改走 /api/live/stream/{ch}/{src}?token= 代理地址（iOS 原生 HLS 可直接播放），静音自动重试一次；TS 源直接给出"移动端暂不支持该直播源格式（TS），请使用 HLS(m3u8) 源或桌面浏览器"提示并标记该源，仅当后续还有 HLS 源才继续换源，不再烧完所有源后笼统报"全部失败"。
- 配套后端 app.py:1843-1930：live_stream_proxy 对 m3u8 播放列表（按 Content-Type 或 .m3u8 路径识别）做相对 URI 绝对化改写（分片行 urllib.parse.urljoin，#EXT-X-KEY/#EXT-X-MAP 的 URI= 属性同步改写），返回 application/vnd.apple.mpegurl，保证 iOS 原生播放器经代理不断链。
- 与 P1 协同：onDeactivated 销毁与失败标记逻辑不变，重连定时器统一由 destroyPlayer 清理。

### P2-8 收藏与观看历史按账号隔离（含旧库迁移）
- app.py:565-575 新增 _admin_user_id()（取 role='admin' 的最小 id，兜底 1）；
- app.py:855-905（建表/迁移）：
  - 新库：favorites/history 建表语句直接含 user_id INTEGER NOT NULL DEFAULT 1；
  - 旧库：PRAGMA table_info 检测无 user_id 列时 ALTER TABLE ADD COLUMN user_id（默认值取管理员 id，实现存量共享数据归属管理员账号，零数据丢失、低风险）；列已存在时把 user_id IS NULL 或 0 的行归属管理员；
  - 索引：DROP INDEX idx_fav_target（旧的全局唯一索引，是 INSERT OR REPLACE 跨账号互踩的根因），新建 UNIQUE INDEX idx_fav_user_target(user_id, target_type, target_id) 与 idx_history_user(user_id)。
- 读过滤：GET /api/favorites（:2735）与 GET /api/history（:2793）查询条件加 f.user_id = ?（当前登录用户 uid，来自 require_auth 的 JWT payload）；
- 写隔离：POST /api/favorites（:2775）INSERT OR REPLACE 的唯一键含 user_id，B 账号收藏同一目标不再顶掉 A 账号的记录；POST /api/history 的 DELETE+INSERT 均按 user_id；
- 删除防越权：DELETE /api/favorites/{id}（:2782）、DELETE /api/history/{id}（:2866）、history batch-delete（:2875）均加 AND user_id = ?，只能删除自己的记录。

### P2-9 Downloads.vue 每秒无条件轮询
- Downloads.vue:104-141：新增 refreshInFlight 防重入；轮询改为按任务状态分频——有 pending/running 任务时 ACTIVE_POLL_MS=1000，无活跃任务时 IDLE_POLL_MS=8000（8 秒），由 schedulePoll(hasActive) 统一调度；onMounted 只调一次 refresh。

## 端到端自测（run_e2e.py，25/25 通过）

- T1 鉴权契约（无 token/坏 token 401、有效 token 200）；
- T2 标签保存（P1-4 回归）；
- T3 收藏隔离：A 收藏后 B 不可见；B 收藏同一目标不覆盖 A（各留 1 条）；B 删除自己的不影响 A；
- T4 历史隔离：互不可见、进度互不覆盖；
- T5/T5b 旧库迁移：以未迁移 schema 的库副本预置存量收藏 2 条、历史 1 条，启动后 user_id 列与按用户唯一索引就位，存量记录全部归属管理员账号（admin_id=1）；
- T6 TS 代理流 188 字节对齐（0x47 同步字节）；T7 不可达源快速 502（0.10s）；T8 自动换源后源清单与 is_active 保持；T9 m3u8 相对 URI 改写为绝对地址；
- T10 构建产物核对：dist 晚于全部源码改动；产物含 P1-1 销毁序列（detachMediaElement）、P1-3 401 跳转（/login?redirect）、P1-2 失败标记、P1-4 tags 接口、P2-4"信号中断"、P2-7"移动端暂不支持"。

## 已知边界与未验证项

- 浏览器级验证（连续换线 5 次监听器计数、真实断流出现"信号中断"、分组/详情快速切换）在沙箱无头环境中无法完全执行，已用逻辑核对 + 产物标记检查 + 端到端 API 测试替代覆盖，建议在真实浏览器按上文步骤抽验；
- P2-4 断流重连的退避参数（最多 6 次、上限 15s）为保守默认值，可按网络环境调整；
- P2-8 存量数据归属方案为"归属管理员账号"，若此前确有某账号独享某条收藏需拆分，可后续手工 UPDATE favorites/history SET user_id=<目标用户> WHERE id=<记录id>；
- run_e2e.py 中 T5 依赖项目自带的旧 schema 库副本，若将来基线库已内置 user_id 列，T5b 会以"库已为新 schema"跳过归属断言。



---

# v3 修复说明（播放组件优化升级 + 离线下载外网快速预览）

基线：完整修复包 v2（P1×4 + P2×9 全部保留，未回退）。
v3 新增改动覆盖：app.py、static/src/components/PlayerModal.vue、
static/src/views/LiveView.vue、static/src/views/Downloads.vue、run_e2e.py、
static/dist/（重新构建）。

## A1 控件层级审查与收敛

结论：全项目两处播放器均未启用 video 原生 controls（无叠加的原生控件条），
控件体系为单层自定义控件；本轮发现并修复 1 处层级冲突 + 1 处遮挡问题。

改动前后对照：

| 位置 | 改动前 | 改动后 |
| --- | --- | --- |
| PlayerModal（在线/离线共用） | 测速选线面板 / 错误提示 / 控制条三层互斥显示，层级清晰；hls 与原生两套引擎分散销毁（onBeforeUnmount 只销毁 hls） | 不变（本就单层）；destroyEngine 统一销毁 hls.js + mpegts.js 两套引擎，杜绝引擎泄漏叠加（PlayerModal.vue:245-259, 591） |
| PlayerModal 离线入口 | Downloads.vue 传 :video/:localUrl，但组件未声明这两个 props，点播放以 targetId=undefined 走测速选线必然失败（阻断级） | localUrl 成为正式 prop，本地模式跳过测速选线直接起播；同一套单层控件复用（PlayerModal.vue:174-177, 552-560） |
| LiveView 全屏控制条 | CSS 规则 `:fullscreen .player-box:hover .live-controls-overlay` 在 player-box 自身为全屏元素时永不匹配（:fullscreen 后代选择器以视口为根），全屏时控制条永久消失 | 删除该 CSS 规则，改 JS 驱动显隐（controlsVisible + .controls-hidden class，4s 自动隐藏、mousemove/click 唤醒、暂停时常显），全屏/窗口行为一致（LiveView.vue:130-163, 780-793） |
| LiveView 状态徽章 | 悬浮在 video 上方（z-5）可拦截点击 | pointer-events: none，纯展示不挡交互（LiveView.vue:767） |
| LiveView 未播放兜底按钮 | 大播放按钮（z-4）与控制条（z-10）同时可见但职责不重叠 | 保持现状（按钮仅在"未连通且无状态文本"时出现，与控制条无重叠），未做多余改动 |

## A2 交互逻辑对主流对齐（旧 → 新清单）

PlayerModal（点播/离线共用）：

| # | 旧交互 | 新交互 | 位置 |
| --- | --- | --- | --- |
| 1 | 键盘仅空格/左右键 | 新增 ArrowUp/ArrowDown 音量 ±0.1、F 全屏、M 静音（输入焦点守卫保持） | PlayerModal.vue:789-800 |
| 2 | 桌面双击无响应（触屏双击手势快进保留） | 桌面双击切换全屏；触屏设备维持原手势不推翻 | PlayerModal.vue:67, 813-816 |
| 3 | 音量调整入口分散（滚轮/滑杆） | 统一 adjustVolume() 步进入口并同步静音图标 | PlayerModal.vue:803-810 |
| 4 | 切线/重试只销毁 hls | destroyEngine() 统一销毁 hls/mpegts 并复位 video 元素 | PlayerModal.vue:245-267 |

LiveView（直播）：

| # | 旧交互 | 新交互 | 位置 |
| --- | --- | --- | --- |
| 5 | video 单击无任何响应 | 桌面单击播放/暂停；触屏单击切换控制条显隐（避免误触暂停） | LiveView.vue:22-24, 165-178 |
| 6 | video 双击无响应 | 桌面双击切换全屏 | LiveView.vue:24, 180-184 |
| 7 | 无键盘快捷键 | 空格播放/暂停、F 全屏、M 静音、上下键音量 ±0.05；输入框聚焦不拦截；keep-alive 切页后按键不串扰 | LiveView.vue:186-210, 698-701 |
| 8 | 控制条常驻（全屏时反而永久消失） | 播放中 4s 无操作自动隐藏，鼠标移动/单击唤醒，暂停时常显（主流习惯） | LiveView.vue:142-163, 647-658 |

克制原则：单击播放/暂停、空格、左右键 10s 快进快退、进度条拖拽、倍速、静音、
记忆播放位置（initialProgress 续看提示）、全屏/退出全屏等既有核心操作全部保持
原行为，仅补齐缺失项，未推翻任何用户已熟悉的操作。

## A3 多格式兼容

前端按扩展名统一格式路由（PlayerModal.vue:391-452）：m3u8 → hls.js；
ts → mpegts.js（isLive:false 点播分支，与直播同一底层库）；其余 → 原生 video。
路由前先查不支持格式表（PlayerModal.vue:229-234），命中直接给出
"暂不支持 XX 格式…建议转码为 MP4（H.264/AAC）"提示，不再静默黑屏。
错误出口统一：hls fatal 恢复矩阵 → playError；mpegts ERROR → playError；
原生 error 事件按错误码映射为可读文案（1 中止 / 2 网络 / 3 解码不支持 / 4 格式或地址）。

| 格式 | 结论 | 说明 |
| --- | --- | --- |
| mp4（H.264/AAC） | 可播（native + Range） | T11 实测 Range 四项通过；faststart 预处理保证秒开（见 B） |
| mp4（moov 在尾部） | 可播，自动预处理 | 下载完成即触发 _ensure_faststart 原位搬移（app.py:6893-6899），T12 实测 |
| m3u8（HLS 直播/点播） | 可播（hls.js / iOS 原生回退） | T9 + T13 实测改写与分片服务；P2-3 恢复矩阵保留 |
| mpegts TS（直播） | 可播（mpegts.js isLive:true） | T6 回归通过，188 字节对齐 |
| mpegts TS（离线下载） | 可播（mpegts.js isLive:false，v3 新增） | 端点行为经 e2e 种子验证；浏览器端软解与直播共用同一引擎路径 |
| webm / mkv（WebM/VP9 或 Chrome 可解的 mkv） | 降级为原生播放 | 浏览器支持有限（mkv 各浏览器差异大），失败时走统一错误文案（解码不支持） |
| avi / wmv / flv / rmvb / rm / mpg / mpeg / vob / 3gp / asf | 不可播 → 明确友好提示 | 命中 UNSUPPORTED_FORMAT_NAMES 早退，提示转码建议，无静默黑屏 |

## B 离线下载内容的外网快速预览

- B1 播放入口修复（阻断级）：Downloads.vue 传给 PlayerModal 的 :video/:localUrl
  原本组件未声明，点播放必然失败。现 localUrl 为正式 prop，本地模式跳过测速选线
  直接按格式起播（PlayerModal.vue:174-177, 552-560; Downloads.vue:93）。
- B2 后端：
  - HTTP Range 已支持（v2 遗产，v3 加测试锁定）：_serve_file_with_range
    （app.py:6348）支持任意区间/后缀区间/416；T11 四项实测通过。拖动与边下边播可用的基础。
  - faststart 预处理（v3 新增，app.py:6670-6812, 6893-6899）：纯 Python 实现
    qt-faststart 算法（_iter_mp4_top_atoms / _mp4_atom_layout / _patch_stco_in_buffer /
    _mp4_faststart），mp4 下载完成后自动把 moov 搬到 mdat 之前并修正全部 chunk 偏移，
    原子替换、幂等、校验后落盘，失败仅记录日志不影响任务成功。无 ffmpeg 依赖，部署环境可用。
  - 封面懒生成（v3 新增，app.py:7143-7191）：GET /api/download/{id}/poster，
    首次请求用 ffmpeg 抽帧（默认第 3 秒回退第 0 秒，480 宽 JPEG）落盘缓存；
    无 ffmpeg / 镜像任务 → 404，前端回退内联 SVG 占位（Downloads.vue:34-40, 111）。
  - 镜像任务 playlist 改写（v2 遗产，T13 锁定）：相对 segs/ 引用改写为
    /api/download/{id}/seg/ 绝对地址，hls.js 逐片拉取、可拖动。
  - 前端预取元数据：video 元素 preload="metadata"（PlayerModal.vue:72），
    列表页封面 loading="lazy" 懒加载。
- B3 弱网量化实测（沙箱模拟：每请求 200ms 延迟 + 2Mbps 限速，2.7MB/30s 720p 测试片）：

| 指标 | moov 在尾部 | faststart（moov 在头部） |
| --- | --- | --- |
| 元数据就绪耗时 | 0.60s（2 次请求、89899 字节） | 0.40s（1 次请求、65536 字节） |
| seek（50% 处 256KB，206） | 1.15s | 1.15s |
| 传输字节数 | 尾部多一次长距 Range 往返 | 首块即含 moov |

  解读：faststart 省掉 1 个 RTT 与约 27% 元数据字节，弱网下元数据就绪快约 33%；
  请求次数从 2 降为 1 在真实公网高 RTT（如 200ms+ 抖动）下收益放大。
  seek 响应两侧一致（均走 Range），说明 Range 服务本身已是拖动可用的充分条件；
  若无 Range（旧式整文件服务），尾部 moov 文件必须下载完整文件才能起播——
  这正是 faststart + Range 组合要消除的最坏情况。测量脚本与原始数据：
  artifacts/measure_weaknet.py、artifacts/b3_weaknet_result.json（网络层代理指标，
  非真实浏览器解码首帧，见"未验证项"）。

## v3 端到端自测（run_e2e.py 新增项）

- T11 Range：无 Range 200+Accept-Ranges；bytes=0-99 / 中段 → 206 且 Content-Range
  与字节逐位精确；越界 → 416。
- T12 faststart：种子 mp4 原始布局 moov 在尾部 → _ensure_faststart 搬移成功 →
  moov 在 mdat 之前；幂等（二次执行不搬移）；ffprobe 解码帧数 48 / 时长 4.0s 不变；
  搬移后 play 端点仍 200。
- T13 镜像：play.m3u8 相对 segs/ 全部改写为 /seg/ 绝对地址；seg 端点 200 且
  512×188 字节 0x47 对齐。
- T14 poster：mp4 任务懒生成 200 image/jpeg + 二次请求命中缓存（无 ffmpeg 环境
  404 回退占位）；镜像任务 404。
- 原有 T1-T10 全部保留执行（P1×4 + P2×9 回归）。

## 部署与用户侧验证步骤

1. 解压修复包 v3 覆盖部署目录，重启服务（app.py 单文件部署不变）。
2. 播放组件：打开任意在线视频点播 → 单击暂停/播放、双击全屏、空格/左右键/上下键/F/M
   快捷键、进度条拖拽；直播页同样核对单击/双击/快捷键，进入全屏确认控制条 4 秒后
   隐藏、移动鼠标唤醒（v2 及之前全屏时控制条永久消失，v3 修复）。
3. 离线下载：新建 mp4 下载任务 → 完成后下载日志应出现 "faststart:" 记录；
   下载页任务卡应显示封面缩略图；点"播放"直接起播（不再走测速选线），拖动进度条应即时响应。
4. 外网访问本地服务器：公网环境打开应用 → 下载列表封面应先于点开就显示；
   点开离线内容确认首帧时间与拖动体验。
5. 兼容回归：直播频道逐个起播确认 P1/P2 行为不回退（换源、信号中断重连、
   移动端提示等）。

## v3 已知边界与未验证项

- 真实浏览器解码首帧与真实公网访问（真实 RTT/丢包/运营商链路）无法在沙箱复现；
  B3 数据为网络层代理指标（限速+延迟模型），建议按"部署与用户侧验证步骤"第 4 步实测。
- mpegts.js 点播分支（isLive:false）在沙箱只验证了端点与路由逻辑；真实 TS 文件
  的浏览器端软解建议用一个已下载的 TS 任务点开确认。
- 封面生成为尽力而为：部署环境无 ffmpeg 时列表页显示占位图标，不影响播放。
- mkv/webm 的浏览器解码差异较大，统一走原生分支；解码失败时展示明确错误文案而非黑屏。
