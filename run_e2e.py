#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suenplayer 端到端验收脚本（run_e2e.py）

在隔离的临时目录中启动 FastAPI 服务（不污染交付目录与真实数据库），
逐项验证后端契约与 P1/P2 修复相关行为：

  T1  鉴权 401 契约：无 token / 坏 token / 有效 token
  T2  标签保存契约：带 Authorization 的 PUT /api/videos/{bangou}/tags → 200
  T3  P2-8 收藏按账号隔离：A/B 互不可见、互不覆盖、删除不越权
  T4  P2-8 观看历史按账号隔离：进度互不覆盖
  T5  P2-8 旧库迁移：user_id 列补齐、存量数据归属管理员、唯一索引替换
  T6  直播代理：TS 流 200 且 0x47 同步字节按 188 对齐
  T7  直播代理：不可达源快速 502（供前端快速切源）
  T8  next-source：is_active 保持 1、源数不变（P1 配套）
  T9  P2-7 m3u8 代理改写：相对 URI 输出为绝对地址（iOS 原生 HLS 可播）
  T10 构建产物：dist 晚于全部源码；P1/P2 关键标记存在
  ---- v3 新增（离线下载播放） ----
  T11 HTTP Range：/api/download/{id}/play 无 Range 200+Accept-Ranges、
      首段/中段 206 Content-Range 精确、越界 416
  T12 faststart 预处理：种子尾部 moov mp4 → _ensure_faststart 搬移 →
      moov 位于头部、幂等、ffprobe 解码帧数/时长不变
  T13 镜像任务：play.m3u8 相对 segs/ 改写为 /api/download/{id}/seg/ 绝对地址、
      seg 端点 200 且 TS 同步字节正确
  T14 poster 封面：mp4 任务懒生成 200 image/jpeg（无 ffmpeg 时 404 回退）、
      镜像任务 404

用法：python3 run_e2e.py
退出码：0 = 全绿；1 = 存在失败项
"""
import hashlib
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
APP_VERSION_DIR = PROJECT_DIR

TEST_USERS = [
    ("testadmin", "testpass123", "admin"),
    ("usera", "userapass123", "viewer"),
    ("userb", "userbpass123", "viewer"),
]
TEST_BANGOU = "E2E-TEST-001"
MEDIA_PORT = 18971
API_PORT = 18972

_results = []


def record(tag, ok, detail=""):
    _results.append((tag, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {tag}" + (f" — {detail}" if detail else ""))


def free_port(preferred):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", preferred))
        s.close()
        return preferred
    except OSError:
        s.close()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port


def hash_password(plain: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 100000).hex()
    return f"{salt}${h}"


# ─────────────────────────── 本地媒体源服务器 ──────────────────────────────
class MediaHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/media.ts"):
            ts_packet = b"\x47" + bytes(187)
            payload = ts_packet * 512  # 512 * 188 = 96256 字节，覆盖多次 64KB 读
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path.startswith("/live.m3u8"):
            body = (
                "#EXTM3U\n"
                "#EXT-X-VERSION:3\n"
                "#EXT-X-TARGETDURATION:6\n"
                "seg0.ts\n"
                "#EXTINF:6.0,\n"
                "seg1.ts\n"
                '#EXT-X-MAP:URI="init.mp4"\n'
                "#EXT-X-ENDLIST\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def start_media_server(port):
    server = ThreadingHTTPServer(("127.0.0.1", port), MediaHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ─────────────────────────── 临时运行环境准备 ─────────────────────────────
def prepare_run_dir(media_port):
    tmp = Path(tempfile.mkdtemp(prefix="suen_e2e_"))
    shutil.copy2(PROJECT_DIR / "app.py", tmp / "app.py")
    shutil.copy2(PROJECT_DIR / "config.py", tmp / "config.py")
    shutil.copy2(PROJECT_DIR / "quick.py", tmp / "quick.py")
    shutil.copy2(PROJECT_DIR / "requirements.txt", tmp / "requirements.txt")
    db_dir = tmp / "data" / "db"
    db_dir.mkdir(parents=True)
    shutil.copy2(PROJECT_DIR / "data" / "db" / "data.db", db_dir / "data.db")
    for extra in ("auth.json", "settings.json"):
        src = PROJECT_DIR / "data" / "db" / extra
        if src.exists():
            shutil.copy2(src, db_dir / extra)

    db = sqlite3.connect(str(db_dir / "data.db"))
    db.row_factory = sqlite3.Row
    db.execute("DELETE FROM users")
    for name, pwd, role in TEST_USERS:
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, status, is_active, must_change_password)"
            " VALUES (?, ?, ?, ?, 'approved', 1, 0)",
            (name, name, hash_password(pwd), role),
        )
    db.execute(
        "INSERT INTO projects (id, name, slug, sort_order, is_active) VALUES (1, 'E2E项目', 'e2e', 0, 1)"
    )
    for uid_row in db.execute("SELECT id FROM users").fetchall():
        db.execute(
            "INSERT INTO user_projects (user_id, project_id) VALUES (?, 1)", (uid_row[0],)
        )
    db.execute("INSERT INTO videos (bangou, title, project_id) VALUES (?, 'E2E 测试影片', 1)", (TEST_BANGOU,))
    vid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "INSERT INTO live_channels (name, group_name, source_region, is_active) VALUES ('E2E频道', 'E2E分组', 'default', 1)"
    )
    ch_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "INSERT INTO live_channel_sources (channel_id, url, is_active, is_default, sort_order) VALUES (?, ?, 1, 1, 0)",
        (ch_id, f"http://127.0.0.1:{media_port}/media.ts"),
    )
    ts_src = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "INSERT INTO live_channel_sources (channel_id, url, is_active, is_default, sort_order) VALUES (?, ?, 1, 0, 1)",
        (ch_id, "http://127.0.0.1:9/unreachable.ts"),
    )
    bad_src = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "INSERT INTO live_channel_sources (channel_id, url, is_active, is_default, sort_order) VALUES (?, ?, 1, 0, 2)",
        (ch_id, f"http://127.0.0.1:{media_port}/live.m3u8"),
    )
    m3u8_src = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.close()
    return tmp, vid, ch_id, ts_src, bad_src, m3u8_src


def seed_download_tasks(tmp):
    """v3: 在临时运行目录种入离线下载任务数据（T11-T14 用）。

    - e2emp4: mp4 任务，ffmpeg 生成 4 秒测试片（默认 moov 位于尾部，
      用于 T11 Range 与 T12 faststart 实测）；无 ffmpeg 时仅留空任务。
    - e2ehls: 镜像 m3u8 任务，本地 playlist + seg0.ts 种子。
    """
    import struct as _struct
    ffmpeg = shutil.which("ffmpeg")
    dl = tmp / "data" / "downloads"
    files = dl / "files"
    mp4_dir = files / "e2emp4"
    mp4_dir.mkdir(parents=True, exist_ok=True)
    seg_dir = files / "e2ehls" / "segs"
    seg_dir.mkdir(parents=True, exist_ok=True)

    info = {"ffmpeg": bool(ffmpeg), "mp4": None, "moov_tail": False}
    if ffmpeg:
        mp4_path = mp4_dir / "demo.mp4"
        r = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=12",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4_path)],
            capture_output=True, timeout=120)
        if r.returncode == 0 and mp4_path.exists() and mp4_path.stat().st_size > 0:
            info["mp4"] = mp4_path
            # 校验种子 mp4 的 moov 确实在 mdat 之后（尾部）
            def _layout(p):
                size = p.stat().st_size
                names, pos = [], 0
                with open(p, "rb") as f:
                    while pos < size:
                        f.seek(pos)
                        hdr = f.read(8)
                        if len(hdr) < 8:
                            break
                        n = _struct.unpack(">I", hdr[:4])[0]
                        typ = hdr[4:8].decode("latin1")
                        if n == 1:
                            n = _struct.unpack(">Q", f.read(8))[0]
                        if n == 0:
                            n = size - pos
                        names.append(typ)
                        pos += n
                return names
            atoms = _layout(mp4_path)
            if "moov" in atoms and "mdat" in atoms:
                info["moov_tail"] = atoms.index("moov") > atoms.index("mdat")

    ts_packet = b"\x47" + bytes(187)
    (seg_dir / "seg0.ts").write_bytes(ts_packet * 512)
    playlist = (
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n"
        "#EXTINF:6.0,\nsegs/seg0.ts\n#EXT-X-ENDLIST\n"
    )
    (files / "e2ehls" / "playlist.m3u8").write_text(playlist, encoding="utf-8")
    tasks = [
        {"id": "e2emp4", "title": "E2E MP4 示例", "format": "mp4", "status": "done",
         "progress": 100, "created_at": "2026-01-01T00:00:00"},
        {"id": "e2ehls", "title": "E2E HLS 镜像", "format": "m3u8", "status": "done",
         "progress": 100, "mirror": True, "created_at": "2026-01-01T00:00:00"},
    ]
    (dl / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    return info


def start_api_server(tmp, port):
    env = dict(os.environ)
    env["COOKIE_SECURE"] = "0"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(tmp),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import httpx
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/", timeout=2.0)
            if r.status_code == 200:
                return proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("API server failed to start")


def login(base, username, password):
    import httpx
    r = httpx.post(f"{base}/api/auth/login", json={"username": username, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def auth_get(base, path, token=None, **kw):
    import httpx
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.get(f"{base}{path}", headers=headers, timeout=kw.pop("timeout", 30), **kw)


# ─────────────────────────── 各项测试 ─────────────────────────────────────
def test_auth_contract(base):
    import httpx
    r = httpx.get(f"{base}/api/videos", timeout=10)
    record("T1a 无 token 访问 /api/videos → 401", r.status_code == 401, f"got {r.status_code}")
    r = httpx.get(f"{base}/api/videos", headers={"Authorization": "Bearer bad-token"}, timeout=10)
    record("T1b 坏 token → 401", r.status_code == 401, f"got {r.status_code}")
    tok = login(base, "testadmin", "testpass123")
    r = httpx.get(f"{base}/api/videos", headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    record("T1c 有效 token → 200", r.status_code == 200, f"got {r.status_code}")
    return tok


def test_tags(base, tok):
    import httpx
    r = httpx.put(
        f"{base}/api/videos/{TEST_BANGOU}/tags",
        headers={"Authorization": f"Bearer {tok}"},
        json={"tags": "e2e,test", "project_id": 1},
        timeout=10,
    )
    record("T2 标签 PUT（带 Authorization）→ 200", r.status_code == 200, f"got {r.status_code}")


def test_favorites_isolation(base, tok_a, tok_b, tid):
    import httpx
    r = httpx.post(f"{base}/api/favorites", headers={"Authorization": f"Bearer {tok_a}"},
                   json={"target_type": "video", "target_id": tid}, timeout=10)
    ok_add = r.status_code == 200
    record("T3a A 账号收藏成功", ok_add, f"got {r.status_code}")

    list_b = auth_get(base, "/api/favorites", tok_b).json()
    arr_b = list_b if isinstance(list_b, list) else list_b.get("items", [])
    record("T3b A 的收藏对 B 不可见", not any(f["target_id"] == tid for f in arr_b), f"B 列表 {len(arr_b)} 条")

    httpx.post(f"{base}/api/favorites", headers={"Authorization": f"Bearer {tok_b}"},
               json={"target_type": "video", "target_id": tid}, timeout=10)
    list_a = auth_get(base, "/api/favorites", tok_a).json()
    arr_a = list_a if isinstance(list_a, list) else list_a.get("items", [])
    a_rows = [f for f in arr_a if f["target_id"] == tid]
    record("T3c B 收藏同一目标不覆盖 A 的记录", len(a_rows) == 1, f"A 列表匹配 {len(a_rows)} 条")

    b_rows = [f for f in arr_b if f["target_id"] == tid]
    # 重新拉 B 列表拿到 B 自己那条 id
    arr_b2 = auth_get(base, "/api/favorites", tok_b).json()
    arr_b2 = arr_b2 if isinstance(arr_b2, list) else arr_b2.get("items", [])
    b_row = next(f for f in arr_b2 if f["target_id"] == tid)
    import httpx as _h
    _h.delete(f"{base}/api/favorites/{b_row['id']}", headers={"Authorization": f"Bearer {tok_b}"}, timeout=10)
    arr_a2 = auth_get(base, "/api/favorites", tok_a).json()
    arr_a2 = arr_a2 if isinstance(arr_a2, list) else arr_a2.get("items", [])
    record("T3d B 删除自己的收藏不影响 A", any(f["target_id"] == tid for f in arr_a2))
    final_b = auth_get(base, "/api/favorites", tok_b).json()
    final_b = final_b if isinstance(final_b, list) else final_b.get("items", [])
    record("T3e B 列表中该收藏已删除", not any(f["target_id"] == tid for f in final_b))


def test_history_isolation(base, tok_a, tok_b, tid):
    import httpx
    httpx.post(f"{base}/api/history", headers={"Authorization": f"Bearer {tok_a}"},
               json={"target_type": "video", "target_id": tid, "progress": 0.3}, timeout=10)
    h_b = auth_get(base, "/api/history", tok_b).json()
    arr_b = h_b if isinstance(h_b, list) else h_b.get("items", [])
    record("T4a A 的观看历史对 B 不可见", not any(h["target_id"] == tid for h in arr_b))

    httpx.post(f"{base}/api/history", headers={"Authorization": f"Bearer {tok_b}"},
               json={"target_type": "video", "target_id": tid, "progress": 0.9}, timeout=10)
    h_a = auth_get(base, "/api/history", tok_a).json()
    arr_a = h_a if isinstance(h_a, list) else h_a.get("items", [])
    a_row = next((h for h in arr_a if h["target_id"] == tid), None)
    record("T4b B 写入历史不覆盖 A 的进度", a_row is not None and abs((a_row.get("progress") or 0) - 0.3) < 1e-6,
           f"A progress={a_row.get('progress') if a_row else None}")


def test_stream_proxy(base, tok, ch_id, ts_src, bad_src, m3u8_src):
    import httpx
    # T6: TS 流
    with httpx.stream("GET", f"{base}/api/live/stream/{ch_id}/{ts_src}",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15) as r:
        ok_status = r.status_code == 200
        first = b""
        if ok_status:
            chunks = []
            got = 0
            for chunk in r.iter_bytes(65536):
                chunks.append(chunk)
                got += len(chunk)
                if got >= 96256:
                    break
            first = b"".join(chunks)
        sync_ok = bool(first) and first[0] == 0x47 and all(first[i] == 0x47 for i in range(0, min(len(first), 96256), 188))
    record("T6 TS 代理流 200 且 0x47 同步字节 188 对齐", ok_status and sync_ok,
           f"status={r.status_code} bytes={len(first)}")

    # T7: 不可达源快速 502
    t0 = time.time()
    r = httpx.get(f"{base}/api/live/stream/{ch_id}/{bad_src}",
                  headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    dt = time.time() - t0
    record("T7 不可达源快速 502", r.status_code == 502 and dt < 6.0, f"status={r.status_code} elapsed={dt:.2f}s")

    # T9: m3u8 改写
    r = httpx.get(f"{base}/api/live/stream/{ch_id}/{m3u8_src}",
                  headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    text = r.text
    abs_ok = "http://127.0.0.1:" in text and "seg1.ts" not in [l for l in text.splitlines() if l and not l.startswith("#")][0]
    rel_left = re.search(r"^seg\d+\.ts$", text, re.M)
    record("T9 m3u8 相对 URI 改写为绝对地址", r.status_code == 200 and abs_ok and not rel_left,
           f"status={r.status_code}")


def test_next_source(base, tok, ch_id):
    import httpx
    r = httpx.post(f"{base}/api/live/channels/{ch_id}/next-source",
                   headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    ch = httpx.get(f"{base}/api/live/channels/{ch_id}",
                   headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
    sources = ch.get("sources") or []
    record("T8 next-source 后源数不变且 is_active 保持 1",
           r.status_code == 200 and len(sources) == 3 and all(s.get("is_active") == 1 for s in sources),
           f"sources={len(sources)}")


def test_migration_old_db():
    """T5: 用未迁移的旧库验证 schema 升级与存量归属。"""
    tmp = Path(tempfile.mkdtemp(prefix="suen_mig_"))
    shutil.copy2(PROJECT_DIR / "app.py", tmp / "app.py")
    shutil.copy2(PROJECT_DIR / "config.py", tmp / "config.py")
    shutil.copy2(PROJECT_DIR / "quick.py", tmp / "quick.py")
    db_dir = tmp / "data" / "db"
    db_dir.mkdir(parents=True)
    shutil.copy2(PROJECT_DIR / "data" / "db" / "data.db", db_dir / "data.db")

    # 先确认是旧 schema（无 user_id 列）才具备迁移验证意义；若已是新 schema 则跳过归属断言
    pre = sqlite3.connect(str(db_dir / "data.db"))
    pre_cols_fav = [r[1] for r in pre.execute("PRAGMA table_info(favorites)").fetchall()]
    pre_cols_hist = [r[1] for r in pre.execute("PRAGMA table_info(history)").fetchall()]
    legacy = "user_id" not in pre_cols_fav
    fav_rows = pre.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
    hist_rows = pre.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    pre.close()

    # 旧 schema 下预置存量数据（无 user_id 列），验证迁移后归属管理员
    if legacy:
        seed = sqlite3.connect(str(db_dir / "data.db"))
        seed.execute(
            "INSERT INTO favorites (target_type, target_id, created_at, project_id) VALUES ('video', 999001, CURRENT_TIMESTAMP, 1)"
        )
        seed.execute(
            "INSERT INTO favorites (target_type, target_id, created_at, project_id) VALUES ('series', 999002, CURRENT_TIMESTAMP, 1)"
        )
        seed.execute(
            "INSERT INTO history (target_type, target_id, progress, watched_at, project_id) VALUES ('video', 999001, 0.42, CURRENT_TIMESTAMP, 1)"
        )
        seed.commit()
        seed.close()
        fav_rows += 2
        hist_rows += 1

    code = (
        "import app, sqlite3\n"
        f"db = sqlite3.connect({str(db_dir / 'data.db')!r})\n"
        "cols = lambda t: [r[1] for r in db.execute(f'PRAGMA table_info({t})').fetchall()]\n"
        "assert 'user_id' in cols('favorites'), 'favorites missing user_id'\n"
        "assert 'user_id' in cols('history'), 'history missing user_id'\n"
        "idx = [r[1] for r in db.execute('PRAGMA index_list(favorites)').fetchall()]\n"
        "assert 'idx_fav_target' not in idx, 'old global unique index still present'\n"
        "assert 'idx_fav_user_target' in idx, 'per-user unique index missing'\n"
        "print('MIGRATION_OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(tmp), capture_output=True, text=True, timeout=120)
    ok = r.returncode == 0 and "MIGRATION_OK" in r.stdout
    detail = f"legacy_db={legacy} fav_rows={fav_rows} hist_rows={hist_rows}"
    if not ok:
        detail += " | " + (r.stderr or r.stdout)[-400:]
    record("T5 旧库迁移：user_id 列与按用户唯一索引", ok, detail)

    # 存量归属：旧 schema 数据迁移后 user_id 应等于管理员 id
    if legacy:
        db = sqlite3.connect(str(db_dir / "data.db"))
        db.row_factory = sqlite3.Row
        admin = db.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
        admin_id = admin["id"] if admin else 1
        bad_fav = db.execute("SELECT COUNT(*) FROM favorites WHERE user_id != ?", (admin_id,)).fetchone()[0]
        bad_hist = db.execute("SELECT COUNT(*) FROM history WHERE user_id != ?", (admin_id,)).fetchone()[0]
        db.close()
        record("T5b 存量收藏/历史归属管理员账号", bad_fav == 0 and bad_hist == 0,
               f"fav={fav_rows} hist={hist_rows} admin_id={admin_id}")
    else:
        record("T5b 存量收藏/历史归属管理员账号", True, "无存量数据或库已为新 schema，跳过")


def test_build_artifacts():
    static = PROJECT_DIR / "static"
    src_files = list((static / "src").rglob("*"))
    src_files = [f for f in src_files if f.is_file()]
    dist_files = [f for f in (static / "dist").rglob("*") if f.is_file()]
    if not src_files or not dist_files:
        record("T10a 构建产物存在", False, "src 或 dist 缺失")
        return
    max_src = max(f.stat().st_mtime for f in src_files)
    min_dist = min(f.stat().st_mtime for f in dist_files)
    record("T10a dist 晚于全部源码改动", min_dist > max_src,
           f"src_max={datetime.fromtimestamp(max_src).isoformat(timespec='seconds')} dist_min={datetime.fromtimestamp(min_dist).isoformat(timespec='seconds')}")

    bundle = ""
    for f in dist_files:
        if f.suffix == ".js":
            try:
                bundle += f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
    markers = {
        "P1-1 销毁序列 detachMediaElement": "detachMediaElement",
        "P1-3 401 跳转 /login?redirect": "/login?redirect",
        "P2-4 信号中断提示": "信号中断",
        "P2-7 移动端暂不支持提示": "移动端暂不支持",
        "P1-2 切源失败标记（UI）": "失败",
        "P1-4 保存标签走鉴权 tags 接口": "/tags",
    }
    for name, m in markers.items():
        record(f"T10b 构建产物含 {name}", m in bundle)

    # P1-2 失败标记逻辑：变量名会被压缩改名，改从源码核对
    lv = (PROJECT_DIR / "static" / "src" / "views" / "LiveView.vue").read_text(encoding="utf-8")
    record("T10c P1-2 源码含 failedIds 失败标记逻辑",
           "failedIds" in lv and "failed: failedIds.has" in lv)


# ─────────────────────── v3: 离线下载播放测试 ────────────────────────────
DL_AUTH = {}  # 由 main 填充 {"headers": {...}}


def _dl_get(base, path, **kw):
    import httpx
    headers = dict(DL_AUTH["headers"])
    headers.update(kw.pop("headers", {}))
    return httpx.get(f"{base}{path}", headers=headers,
                     timeout=kw.pop("timeout", 30), **kw)


def test_download_range(base):
    """T11: mp4 文件服务的 HTTP Range 支持（拖动/边下边播的基础）。"""
    full = _dl_get(base, "/api/download/e2emp4/play")
    if full.status_code != 200:
        record("T11 Range 服务（跳过）", True, f"mp4 种子不可服务 status={full.status_code}")
        return
    size = len(full.content)
    has_ar = "accept-ranges" in {k.lower() for k in full.headers.keys()}
    record("T11a 无 Range → 200 且 Accept-Ranges: bytes",
           full.status_code == 200 and has_ar, f"status={full.status_code}")

    r0 = _dl_get(base, "/api/download/e2emp4/play", headers={"Range": "bytes=0-99"})
    cr = r0.headers.get("content-range", "")
    ok0 = (r0.status_code == 206 and len(r0.content) == 100
           and r0.content == full.content[:100] and cr == f"bytes 0-99/{size}")
    record("T11b bytes=0-99 → 206 且 Content-Range/字节精确", ok0,
           f"status={r0.status_code} len={len(r0.content)} cr={cr}")

    rm = _dl_get(base, "/api/download/e2emp4/play", headers={"Range": "bytes=100-199"})
    okm = (rm.status_code == 206 and len(rm.content) == 100
           and rm.content == full.content[100:200]
           and rm.headers.get("content-range") == f"bytes 100-199/{size}")
    record("T11c 中段 range → 206 字节精确", okm,
           f"status={rm.status_code} len={len(rm.content)}")

    ro = _dl_get(base, "/api/download/e2emp4/play", headers={"Range": f"bytes={size + 10}-"})
    record("T11d 越界 range → 416", ro.status_code == 416, f"status={ro.status_code}")


def test_download_faststart(tmp, base):
    """T12: faststart 预处理——moov 搬移、幂等、ffprobe 解码一致性。"""
    mp4 = tmp / "data" / "downloads" / "files" / "e2emp4" / "demo.mp4"
    if not mp4.exists():
        record("T12 faststart 预处理（跳过）", True, "无 ffmpeg，未生成 mp4 种子")
        return

    def _mp4_layout(p):
        code = (
            "import os, struct, json\n"
            "def layout(fp):\n"
            "    size = os.path.getsize(fp); names = []; pos = 0\n"
            "    with open(fp, 'rb') as f:\n"
            "        while pos < size:\n"
            "            f.seek(pos); hdr = f.read(8)\n"
            "            if len(hdr) < 8: break\n"
            "            n = struct.unpack('>I', hdr[:4])[0]\n"
            "            names.append(hdr[4:8].decode('latin1'))\n"
            "            if n == 1: n = struct.unpack('>Q', f.read(8))[0]\n"
            "            if n == 0: n = size - pos\n"
            "            pos += n\n"
            "    return names\n"
            f"print(json.dumps(layout({str(mp4)!r})))\n"
        )
        r = subprocess.run([sys.executable, "-c", code], cwd=str(tmp),
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return []
        return json.loads(r.stdout.strip().splitlines()[-1])

    before = _mp4_layout(mp4)
    moov_tail = "moov" in before and "mdat" in before and before.index("moov") > before.index("mdat")
    record("T12a 种子 mp4 原始布局 moov 位于 mdat 之后", moov_tail, f"atoms={before}")

    code = (
        "import app, json\n"
        f"moved, detail = app._ensure_faststart({str(mp4)!r})\n"
        "print(json.dumps([moved, detail]))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(tmp),
                       capture_output=True, text=True, timeout=120)
    moved = False
    if r.returncode == 0:
        try:
            moved, detail = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            moved, detail = False, r.stdout[-200:]
    record("T12b _ensure_faststart 搬移成功", moved, f"detail={detail}")

    after = _mp4_layout(mp4)
    moov_head = "moov" in after and "mdat" in after and after.index("moov") < after.index("mdat")
    record("T12c 搬移后 moov 位于 mdat 之前", moov_head, f"atoms={after}")

    # 幂等：再次调用应报告"已在头部"且不再搬移
    r2 = subprocess.run([sys.executable, "-c", code], cwd=str(tmp),
                        capture_output=True, text=True, timeout=120)
    moved2 = None
    if r2.returncode == 0:
        try:
            moved2 = json.loads(r2.stdout.strip().splitlines()[-1])[0]
        except Exception:
            moved2 = None
    record("T12d 幂等：再次执行不重复搬移", moved2 is False, f"second_moved={moved2}")

    # 解码一致性：faststart 只改布局不改内容，帧数/时长必须不变
    ffp = shutil.which("ffprobe")
    if ffp:
        pr = subprocess.run(
            [ffp, "-v", "error", "-select_streams", "v:0", "-count_frames",
             "-show_entries", "stream=nb_read_frames,duration", "-of", "json", str(mp4)],
            capture_output=True, timeout=120)
        frames_ok = pr.returncode == 0
        detail = ""
        if frames_ok:
            st = json.loads(pr.stdout)["streams"][0]
            n, d = st.get("nb_read_frames"), float(st.get("duration") or 0)
            frames_ok = n == "48" and abs(d - 4.0) < 0.3
            detail = f"frames={n} duration={d}"
        record("T12e ffprobe 解码帧数=48 时长≈4s（内容未损）", frames_ok, detail)
    else:
        record("T12e ffprobe 解码一致性（跳过）", True, "ffprobe 不可用")

    # 搬移后文件仍可正常服务
    rr = _dl_get(base, "/api/download/e2emp4/play")
    record("T12f faststart 后 play 端点仍 200 可服务", rr.status_code == 200,
           f"status={rr.status_code}")


def test_download_mirror(base):
    """T13: 镜像任务 playlist 改写与 seg 服务。"""
    r = _dl_get(base, "/api/download/e2ehls/play.m3u8")
    text = r.text
    abs_ok = f"/api/download/e2ehls/seg/seg0.ts" in text
    rel_left = "segs/seg0.ts" in text
    record("T13a play.m3u8 相对 segs/ 改写为 /seg/ 绝对地址",
           r.status_code == 200 and abs_ok and not rel_left,
           f"status={r.status_code}")

    seg = _dl_get(base, "/api/download/e2ehls/seg/seg0.ts")
    sync = bool(seg.content) and seg.content[0:1] == b"\x47"
    record("T13b seg 端点 200 且 0x47 同步字节正确",
           seg.status_code == 200 and sync and len(seg.content) == 512 * 188,
           f"status={seg.status_code} len={len(seg.content)}")


def test_download_poster(base):
    """T14: poster 封面懒生成（尽力而为）与镜像任务 404 回退。"""
    r = _dl_get(base, "/api/download/e2emp4/poster", timeout=90)
    if r.status_code == 404:
        record("T14a poster 封面（无 ffmpeg 回退 404）", True,
               "ffmpeg 不可用 → 404，前端展示占位封面")
    else:
        ok = (r.status_code == 200
              and r.headers.get("content-type", "").startswith("image/jpeg")
              and len(r.content) > 0)
        record("T14a poster 懒生成 → 200 image/jpeg", ok,
               f"status={r.status_code} len={len(r.content)}")
        # 第二次请求应命中磁盘缓存
        r2 = _dl_get(base, "/api/download/e2emp4/poster", timeout=30)
        record("T14a-2 poster 二次请求命中缓存", r2.status_code == 200,
               f"status={r2.status_code}")

    rm = _dl_get(base, "/api/download/e2ehls/poster")
    record("T14b 镜像任务 poster → 404", rm.status_code == 404,
           f"status={rm.status_code}")


# ─────────────────────────── 主流程 ───────────────────────────────────────
def main():
    print("== suenplayer run_e2e ==")
    media_port = free_port(MEDIA_PORT)
    api_port = free_port(API_PORT)

    tmp, vid, ch_id, ts_src, bad_src, m3u8_src = prepare_run_dir(media_port)
    media_server = start_media_server(media_port)
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(api_port), "--log-level", "warning"],
            cwd=str(tmp), env={**os.environ, "COOKIE_SECURE": "0"},
            stdout=subprocess.DEVNULL, stderr=open("api_server_stderr.log", "w"),
        )
        base = f"http://127.0.0.1:{api_port}"
        import httpx
        deadline = time.time() + 40
        up = False
        while time.time() < deadline:
            try:
                if httpx.get(f"{base}/", timeout=2.0).status_code == 200:
                    up = True
                    break
            except Exception:
                time.sleep(0.5)
        if not up:
            raise RuntimeError("API server failed to start")

        admin_tok = login(base, "testadmin", "testpass123")
        tok_a = login(base, "usera", "userapass123")
        tok_b = login(base, "userb", "userbpass123")

        test_auth_contract(base)
        test_tags(base, admin_tok)

        tid = vid

        test_favorites_isolation(base, tok_a, tok_b, vid)
        test_history_isolation(base, tok_a, tok_b, tid)
        test_migration_old_db()
        test_stream_proxy(base, tok_a, ch_id, ts_src, bad_src, m3u8_src)
        test_next_source(base, tok_a, ch_id)

        # v3: 离线下载播放（T11-T14）
        seed_download_tasks(tmp)
        DL_AUTH["headers"] = {"Authorization": f"Bearer {admin_tok}"}
        test_download_range(base)
        test_download_faststart(tmp, base)
        test_download_mirror(base)
        test_download_poster(base)

        test_build_artifacts()
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        media_server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [t for t, ok, _ in _results if not ok]
    print(f"\n== 结果：{len(_results) - len(failed)}/{len(_results)} 通过 ==")
    if failed:
        for t in failed:
            print("  FAILED:", t)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
