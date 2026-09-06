# suenplayer

多项目媒体库与播放服务：影视库（影片 / 多季剧集）、IPTV 直播（多源自动切换）、下载任务、JSON 产物导入与自动更新。

后端 FastAPI 单文件统一版，前端 Vue 3 + Vite，支持 Docker 部署。

## 功能一览

- **媒体库**：影片 + 剧集/季/集三层结构，多项目数据隔离与按账号的项目可见性控制
- **JSON 导入**：2.1 版产物契约（分卷合并 `xxx-1.json` + `xxx-2.json`、`project` 字段定项目、
  季级元数据 `season_cover/season_overview`、`genres` 自动并入标签）；导入后自动重建两级分类树
- **自动更新**：APScheduler 定时扫描本地目录 / 远端地址（Git 仓库支持私有 token），增量导入
- **直播**：多源频道、TTFB 测速选线、失败自动换线（慢启动容错）、多观众同源复用（一路上游会话
  服务多设备，防 udpxy 并发限额）
- **播放**：HLS / MPEG-TS 全端覆盖，页面源通用解析（扫描流地址 + `/index.m3u8` 约定），
  手动换线、倍速、续看
- **封面缓存**：`/api/cache/<url>` 磁盘缓存 + 无损压缩（JPEG jpegtran / PNG optimize）+
  加载失败占位兜底
- **账号**：PBKDF2 + JWT（Cookie/Bearer 双通道），注册审批制，首登强制改密

## 快速开始

```bash
# 1) 后端
python3 -m pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080

# 2) 前端（首次需要构建，产物输出 static/dist 由后端自动托管）
cd static && npm install && npm run build

# 或 Docker
docker build -t suenplayer-backend .
docker run -d --name suenplayer -p 8080:8080 -v suenplayer_data:/app/data suenplayer-backend
```

访问 `http://<host>:8080/`。首次启动自动创建管理员 **admin / admin123**，登录后请立即改密。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `APP_TITLE` | `suenplayer` | 应用标题 / 站点名 |
| `COOKIE_SECURE` | `0` | 登录 Cookie Secure 标志。**HTTPS 生产环境置 `1`**；纯 HTTP 内网保持 `0`，否则浏览器不回传 Cookie（封面/媒体请求 401） |
| `COOKIE_SAMESITE` | `strict` | Cookie SameSite 策略 |
| `SUENMEDIA_DISABLE_SCHEDULER` | 空 | 置 `1` 关闭后台调度器（自动更新 / 巡检） |
| `DISABLE_SSL_VERIFY` | 空 | 置 `1` 关闭出站证书校验，仅调试用 |

## JSON 产物契约（v2.1）

```jsonc
{
  "schema_version": "2.1",
  "project": { "name": "影视仓", "slug": "movies" },   // 归属项目（slug 不存在则自动创建）
  "items": [
    {
      "type": "video | series",
      "bangou": "唯一番号（全局唯一，跨项目冲突将拒绝导入）",
      "title": "标题",
      "cover": "封面 URL", "backdrop": "横版背景图 URL",
      "region": "一级分类", "group_name": "二级分类",       // 导入后自动生成分类树
      "genres": ["类型标签（自动并入 tags）"],
      "cast": ["演员"], "overview": "简介", "rating": 8.5,
      "seasons": [                                         // 剧集：季级元数据各季独立
        {
          "season_number": 1, "season_title": "第一季",
          "season_cover": "本季封面", "season_overview": "本季简介",
          "episodes": [
            { "ep_number": 1, "ep_title": "第01集", "url": "https://.../index.m3u8",
              "alt_urls": [ { "source": "备用线路", "url": "..." } ] }
          ]
        }
      ]
    }
  ]
}
```

导入语义：同路径文件全量替换（自动清理旧数据并重建分类），增量扫描按番号 upsert。
集数播放地址自动合并多线路重复记录（同一视频的 `/index.m3u8` 与裸路径视为同集）。

## 目录结构

```
├── app.py            # 后端主程序（FastAPI 单文件统一版）
├── config.py         # 常量配置（版本、测速与调度参数）
├── quick.py          # 线路测速模块（TTFB / 速率 / 并发探测）
├── requirements.txt  # Python 依赖
├── Dockerfile
└── static/           # 前端（Vue 3 + Vite + Pinia + hls.js + mpegts.js）
    ├── src/          #   源码
    └── vite.config.js
```

运行时自动生成（不入库）：`data/db`（SQLite + JWT 密钥）、`data/cache`（封面缓存）、
`data/downloads`（下载任务文件）。
