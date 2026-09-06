# suenplayer v2.1 部署说明

应用版本：APP_VERSION 2.1（单一代码内定义于 `config.py`）。本包为完整可部署产物：后端全部源码 + 前端全部源码与已构建 dist，前后端自洽，解包即可部署。

## 一、包内容结构

```
suenplayer_v2.1/
├── app.py                  # 后端主程序（FastAPI，单文件统一版）
├── app_v8.py               # 兼容 shim（供既有测试套件独立运行）
├── config.py               # 常量配置（APP_VERSION、测速与调度参数等）
├── quick.py                # 测速工具模块
├── requirements.txt        # Python 依赖（全部钉版）
├── Dockerfile              # Docker 构建文件
├── sample-video.json       # 视频导入样例 JSON
├── suentv-anhui*.json      # 测试夹具（test_v9.py 依赖）
├── test_*.py               # 全部测试文件（6 套）
└── static/                 # 前端
    ├── dist/               # 已构建前端产物（后端直接托管，开箱可用）
    ├── src/                # 前端源码（Vue 3 + Vite + Pinia）
    ├── index.html / package.json / vite.config.js
    └── ...
```

运行时自动生成（不在包内，也不应纳入版本控制）：`data/` 目录，含 `data/db/data.db`（SQLite 库）、`data/db/auth.json`（JWT 密钥与账号配置）、`data/db/settings.json`（站点设置）、`data/cache/`、`data/downloads/`。

## 二、环境要求

- Python 3.11（与 Dockerfile 的 `python:3.11-slim` 一致；3.10 实测可运行）
- 依赖见 `requirements.txt`（fastapi、starlette、uvicorn、requests、PyJWT、python-multipart、httpx、pytest、APScheduler，全部钉版）
- 生产推荐：HTTPS + 反向代理（Nginx / Caddy 等）

## 三、配置项（环境变量）

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `APP_TITLE` | `suenplayer` | 应用标题（FastAPI title 与站点名） |
| `COOKIE_SECURE` | `1` | 登录 Cookie 是否带 Secure 标志。生产必须保持 `1` 并使用 HTTPS |
| `COOKIE_SAMESITE` | `strict` | Cookie SameSite 策略 |
| `SUENMEDIA_DISABLE_SCHEDULER` | 空 | 置 `1` 关闭后台调度器（自动更新巡检等），供测试/调试使用 |
| `DISABLE_SSL_VERIFY` | 空 | 置 `1` 关闭出站请求证书校验。仅调试用，生产禁止开启 |

## 四、COOKIE_SECURE=1 + HTTPS 生产建议（重要）

登录态通过 `token` Cookie 下发，属性为 `HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=604800`（默认 `COOKIE_SECURE=1`）。Secure Cookie 在纯 HTTP 下浏览器不会回传，因此：

1. **生产环境**：保持默认 `COOKIE_SECURE=1`，并通过反向代理提供 HTTPS。建议同时在反代层终止 TLS 并转发至后端 8080 端口。
2. **本地或内网 HTTP 试运行**：登录会"看似成功但 Cookie 不生效"，此时可临时设置 `COOKIE_SECURE=0` 启动，验证完毕后务必改回 `1`。**公网环境禁止使用 `COOKIE_SECURE=0`。**
3. 上线 HTTPS 后建议完整走一遍冒烟链路（登录、项目列表、导入、最近更新）确认 Cookie 正常。

## 五、默认账号与首登强制改密

- 首次启动时自动创建默认管理员：**用户名 `admin`，密码 `admin123`**（启动日志有 WARN 提示）。
- 默认账号 `must_change_password=1`：登录接口返回该字段，前端据此弹出强制改密引导；未改密前每次登录都会重现引导。
- 改密成功后 `must_change_password` 置 0，再次登录不再引导。**首次部署后请立即完成改密。**
- 注册走审批制：用户注册后进入待审批状态，由管理员在管理后台批准后方可登录。

## 六、本地裸机部署

```bash
cd suenplayer_v2.1
python3 -m pip install -r requirements.txt

# 生产（HTTPS 反代后）
uvicorn app:app --host 0.0.0.0 --port 8080

# 本地 HTTP 试运行（仅限本机/内网调试）
COOKIE_SECURE=0 uvicorn app:app --host 0.0.0.0 --port 8080
```

启动后访问 `http://<host>:8080/` 即为前端页面（由后端托管 `static/dist`）。

## 七、Docker 构建与运行

```bash
cd suenplayer_v2.1
docker build -t suenplayer-backend .
docker run -d --name suenplayer \
  -p 8080:8080 \
  -v suenplayer_data:/app/data \
  suenplayer-backend
```

- 数据（SQLite 库、设置、下载文件）持久化在 `suenplayer_data` 卷，挂载到容器 `/app/data`。
- 容器以非 root 用户（uid 10001）运行。
- **注意**：本 Dockerfile 在打包环境中完成静态检查与语法验证，但打包环境无 Docker 守护进程、未实际执行过镜像构建。**首次部署时请人工执行一次 `docker build` 并完成冒烟验证**（登录 + 项目列表 + 导入）。

## 八、前端构建（可选）

包内已含构建好的 `static/dist`，直接部署无需重新构建。如需修改前端：

```bash
cd static
npm install
npm run build    # 产物输出到 static/dist，后端自动托管
```

前端技术栈：Vue 3 + Vite 5 + Pinia + vue-router + hls.js。

## 九、测试与验证

```bash
pip install -r requirements.txt
python3 -m pytest test_observations.py -q        # 观察项修复专项（13 例）
python3 test_auth_guard.py                        # 以下各套件按其设计方式独立运行
python3 test_backend_gaps.py
python3 test_new_features.py
python3 test_v8.py
python3 test_v9.py
```

测试会使用 `SUENMEDIA_DISABLE_SCHEDULER=1` 并在临时/本地目录生成运行数据，测试后请清理运行残留（`data/`、`__pycache__` 等）再打包或部署。

## 十、版本口径

- `config.APP_VERSION = "2.1"`，为版本号单一定义源，与 JSON 交付标准编号一致。
- 导入兼容 2.0 及更早的 JSON 字段结构。
