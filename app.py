"""
suenplayer backend (single unified version, see config.APP_VERSION)

Feature map:
- Media library: flat videos plus series/seasons/episodes three-layer
  structure, multi-project data isolation, JSON import with volume merging
  (xxx-1.json + xxx-2.json) and project-field priority
- Organize toolchain: merge with rule memory, category transfer with rule
  memory, dedup markers, metadata overrides, manual tags/category edits,
  organize rule management; rules carry a project dimension and are
  re-applied after every import (manual full-replace, incremental scan and
  scheduled auto-update alike), so manual organize results survive re-import
- Speed test: probe/scoring via quick.py, fallback chain, health patrol
- Live streaming: live_channels / live_channel_sources tables, single-source
  and multi-source live JSON recognition and import (full replace per
  region), group/channel list/detail APIs, multi-source switching (default
  best source by speed/delay ordering, manual switch, failure fallback to
  next source), TTFB-based probe and patrol job
- Auto update: auto_update_configs / auto_update_logs tables, in-process
  APScheduler scanning, local directory scan and remote address fetch
  (five address shapes supported, optional proxy, SSRF-guarded, admin only),
  video incremental import (new items enter recent updates), live full
  refresh, exponential backoff retry, manual trigger API
- Download: full task chain — create (mp4 streaming or HLS mirroring),
  cancel, retry, local file playback with HTTP Range, HLS playlist +
  segment serving for progressive playback
- Auth: multi-account with users table (PBKDF2 hashes), JWT cookie/bearer
  sessions, self-registration with admin approval, default admin bootstrap
  on first start, self-service username/password change; every /api/*
  endpoint except /api/auth/* requires a logged-in session
"""

from contextlib import contextmanager
import os, json, sqlite3, ipaddress, struct, subprocess, re, urllib.parse, hashlib, shutil, secrets, asyncio, uuid, threading, time, tarfile, socket, tempfile, sys, logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Body, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse, Response, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from starlette.middleware.gzip import GZipResponder
from starlette.datastructures import Headers
from starlette.concurrency import run_in_threadpool
import jwt

import config
import config as config_module
import quick

MIME_TYPES = {
    ".js": "application/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".json": "application/json",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}

_SKIP_GZIP_PREFIXES = (
    "video/", "audio/", "image/", "application/octet-stream",
    "application/vnd.apple.mpegurl", "application/x-mpegurl",
    "application/zip", "application/pdf", "application/gzip",
    "font/", "application/vnd.android.package-archive",
)

_REQUESTS_VERIFY = os.environ.get("DISABLE_SSL_VERIFY", "").lower() not in ("1", "true", "yes")


# -- SSRF Protection --

def _is_ip_private(ip) -> bool:
    if ip.version == 4:
        return (ip.is_private or ip.is_loopback or ip.is_link_local or
                ip.is_reserved or ip.is_multicast or ip.is_unspecified)
    else:
        if getattr(ip, "ipv4_mapped", None) is not None:
            return _is_ip_private(ip.ipv4_mapped)
        return (ip.is_loopback or ip.is_link_local or ip.is_multicast or
                ip.is_unspecified or (ip in ipaddress.ip_network("fc00::/7")))


_ALLOW_PRIVATE_URLS = os.environ.get("ALLOW_PRIVATE_URLS", "0").lower() in ("1", "true", "yes")


def _is_private_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        if not host:
            return True
        host_lower = host.lower()
        if host_lower in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return True
        if host_lower == "169.254.169.254":
            return True
        if host.isdigit():
            return True
        if host_lower.startswith("0x"):
            return True
        if "." in host:
            for seg in host.split("."):
                if len(seg) > 1 and seg.startswith("0") and seg.isdigit():
                    return True
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_loopback or str(ip) in ("127.0.0.1", "::1", "0.0.0.0", "169.254.169.254"):
                return True
            if _ALLOW_PRIVATE_URLS:
                return False
            return _is_ip_private(ip)
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                resolved_ip = ipaddress.ip_address(info[4][0])
                if resolved_ip.is_loopback or str(resolved_ip) in ("127.0.0.1", "::1", "0.0.0.0", "169.254.169.254"):
                    return True
                if not _ALLOW_PRIVATE_URLS and _is_ip_private(resolved_ip):
                    return True
        except (OSError, ValueError):
            pass
        return False
    except ValueError:
        return False


# -- Media-Aware GZip Middleware --

class _MediaAwareGZipResponder(GZipResponder):
    async def send_with_gzip(self, message: dict) -> None:
        if message["type"] == "http.response.start":
            headers = Headers(raw=message["headers"])
            ct = (headers.get("content-type") or "").split(";")[0].strip().lower()
            self._skip = any(ct.startswith(p) for p in _SKIP_GZIP_PREFIXES)
            self._skip = self._skip or ct == "" and not headers.get("content-type")
        if getattr(self, "_skip", False):
            if not self.started:
                self.started = True
            await self.send(message)
            return
        await super().send_with_gzip(message)


class MediaAwareGZipMiddleware:
    def __init__(self, app, minimum_size: int = 1024, compresslevel: int = 9):
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            if "gzip" in headers.get("Accept-Encoding", ""):
                responder = _MediaAwareGZipResponder(
                    self.app, self.minimum_size, compresslevel=self.compresslevel)
                await responder(scope, receive, send)
                return
        await self.app(scope, receive, send)


# -- App & Paths --

app = FastAPI(title=os.environ.get("APP_TITLE", "suenplayer"), version=config.APP_VERSION)
app.add_middleware(MediaAwareGZipMiddleware, minimum_size=1024)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DIST_DIR = STATIC_DIR / "dist"
if DIST_DIR.exists():
    STATIC_DIR = DIST_DIR
DATA_DIR = BASE_DIR / "data"
DB_DIR = DATA_DIR / "db"
CACHE_DIR = DATA_DIR / "cache"
DOWNLOAD_DIR = DATA_DIR / "downloads"
DOWNLOAD_FILES_DIR = DOWNLOAD_DIR / "files"
DOWNLOAD_TASKS_FILE = DOWNLOAD_DIR / "tasks.json"

for d in [DB_DIR, CACHE_DIR, DOWNLOAD_FILES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = DB_DIR / "settings.json"
DB_FILE = DB_DIR / "data.db"
AUTH_FILE = DB_DIR / "auth.json"


# -- Auth (multi-account with users table) --

SECURITY = HTTPBearer(auto_error=False)


def _auth_config():
    if AUTH_FILE.exists():
        with open(AUTH_FILE) as f:
            return json.load(f)
    return {}


def _save_auth_config(cfg):
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AUTH_FILE, "w") as f:
        json.dump(cfg, f)
    os.chmod(AUTH_FILE, 0o600)


def _ensure_jwt_secret():
    cfg = _auth_config()
    if "jwt_secret" not in cfg:
        cfg["jwt_secret"] = secrets.token_urlsafe(48)
        _save_auth_config(cfg)
    return cfg["jwt_secret"]


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}${h.hex()}"


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        salt, h = hashed.split("$", 1)
        h2 = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 100000).hex()
        return h == h2
    except (ValueError, AttributeError):
        return False


def _create_token(username: str, user_id: int, role: str, expires_days: int = 7) -> str:
    secret = _ensure_jwt_secret()
    payload = {
        "sub": username,
        "uid": user_id,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=expires_days),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _decode_token(token: str) -> dict | None:
    secret = _ensure_jwt_secret()
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.PyJWTError:
        return None


def _get_token_from_request(request: Request) -> str:
    cookie_token = request.cookies.get("token", "")
    if cookie_token:
        return cookie_token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    query_token = request.query_params.get("token", "")
    if query_token:
        return query_token
    return ""


# 默认不设 Secure 标志：本应用常见部署为局域网纯 HTTP，浏览器不会保存
# 带 Secure 的 cookie，导致 <img>/媒体类请求全部 401。HTTPS 部署请显式
# 设置环境变量 COOKIE_SECURE=1。
_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0").lower() not in ("0", "false", "no")
_COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "strict").lower()


def _set_auth_cookie(response: Response, token: str):
    secure_flag = "; Secure" if _COOKIE_SECURE else ""
    samesite_flag = f"; SameSite={_COOKIE_SAMESITE.capitalize()}"
    response.headers["Set-Cookie"] = (
        f"token={token}; HttpOnly{secure_flag}{samesite_flag}; Path=/; Max-Age=604800"
    )


async def require_auth(request: Request):
    token = _get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="需要登录")
    payload = _decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="凭证无效或已过期")
    return payload


async def require_admin(request: Request):
    payload = await require_auth(request)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return payload


# -- Project visibility helpers --

def _get_user_visible_projects(user_payload: dict) -> list[int]:
    role = user_payload.get("role", "viewer")
    if role == "admin":
        with get_db() as db:
            rows = db.execute("SELECT id FROM projects WHERE is_active = 1").fetchall()
            return [r["id"] for r in rows]
    user_id = user_payload.get("uid")
    with get_db() as db:
        rows = db.execute(
            "SELECT project_id FROM user_projects WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [r["project_id"] for r in rows]


def _project_filter_clause(visible_projects: list[int], table_alias: str = "") -> tuple[str, list[int]]:
    if not visible_projects:
        return "1=0", []
    alias = f"{table_alias}." if table_alias else ""
    placeholders = ",".join("?" for _ in visible_projects)
    return f"{alias}project_id IN ({placeholders})", visible_projects


LOGIN_ATTEMPTS: dict[str, list[datetime]] = {}

# Every /api/* endpoint except /api/auth/* is protected: an anonymous
# caller must never see any content. Playback flows work because the
# session cookie travels with every media request.
# 列表接口排序白名单（前端浏览页 sortBy 直传 sort 参数）
_LIST_SORTS = {
    "date": "date DESC",
    "popularity": "COALESCE(popularity, 0) DESC, COALESCE(view_count, 0) DESC, date DESC",
    "hot": "COALESCE(view_count, 0) DESC, COALESCE(popularity, 0) DESC, date DESC",
    "rating": "COALESCE(rating, 0) DESC, COALESCE(vote_count, 0) DESC, date DESC",
    "trending": "CASE WHEN trending_rank IS NULL THEN 1 ELSE 0 END ASC, trending_rank ASC, date DESC",
}


PUBLIC_API_PREFIXES = (
    "/api/auth/",
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    if path.startswith("/api/auth/"):
        return await call_next(request)
    # Protected endpoints require valid token
    token = _get_token_from_request(request)
    if not token:
        return JSONResponse({"error": "需要登录"}, status_code=401)
    payload = _decode_token(token)
    if not payload:
        return JSONResponse({"error": "凭证无效或已过期"}, status_code=401)
    request.state.user = payload
    return await call_next(request)



# -- Auth Endpoints --

@app.post("/api/auth/login")
async def auth_login(data: dict = Body(...), request: Request = None):
    username = str(data.get("username", "")).strip().lower()
    password = data.get("password", "")
    if not username or not password:
        return JSONResponse({"error": "用户名和密码必填"}, status_code=400)

    client_ip = request.client.host if request and request.client else "unknown"
    now = datetime.now(timezone.utc)
    attempts = LOGIN_ATTEMPTS.get(client_ip, [])
    attempts = [t for t in attempts if t > now - timedelta(minutes=5)]
    if len(attempts) >= 10:
        return JSONResponse({"error": "尝试次数过多，请5分钟后重试"}, status_code=429)

    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
        ).fetchone()

    if not user or not _verify_password(password, user["password_hash"]):
        attempts.append(now)
        LOGIN_ATTEMPTS[client_ip] = attempts
        return JSONResponse({"error": "用户名或密码错误"}, status_code=401)

    status = (user["status"] or "approved") if "status" in user.keys() else "approved"
    if status == "pending":
        return JSONResponse({"error": "账号待管理员批准", "status": "pending"}, status_code=403)
    if status == "rejected":
        return JSONResponse({"error": "账号已被管理员拒绝", "status": "rejected"}, status_code=403)

    attempts.clear()
    LOGIN_ATTEMPTS[client_ip] = attempts
    token = _create_token(user["username"], user["id"], user["role"])
    must_change = bool(user["must_change_password"]) if "must_change_password" in user.keys() else False
    resp = JSONResponse({
        "token": token,
        "user": {
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "must_change_password": must_change,
        }
    })
    _set_auth_cookie(resp, token)
    return resp


@app.get("/api/auth/verify")
async def auth_verify(request: Request):
    token = _get_token_from_request(request)
    if not token:
        return {"ok": False, "enabled": True}
    payload = _decode_token(token)
    return {"ok": payload is not None, "enabled": True}


@app.get("/api/auth/me")
async def auth_me(request: Request):
    payload = await require_auth(request)
    with get_db() as db:
        user = db.execute(
            "SELECT id, username, display_name, role, is_active, must_change_password FROM users WHERE id = ?",
            (payload.get("uid"),)
        ).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "must_change_password": bool(user["must_change_password"]),
    }


@app.post("/api/auth/logout")
async def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.headers["Set-Cookie"] = "token=; HttpOnly; Path=/; Max-Age=0"
    return resp


@app.post("/api/auth/password")
async def auth_change_password(data: dict = Body(...), user_payload=Depends(require_auth)):
    old = data.get("old_password", "")
    new = data.get("new_password", "")
    if not new or len(new) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6位")
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_payload.get("uid"),)).fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        if not _verify_password(old, user["password_hash"]):
            raise HTTPException(status_code=401, detail="原密码错误")
        db.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0, updated_at = ? WHERE id = ?",
            (_hash_password(new), datetime.now(timezone.utc).isoformat(), user["id"])
        )
        db.commit()
    return {"ok": True}


# -- Self registration & admin approval --

@app.post("/api/auth/register")
async def auth_register(data: dict = Body(...)):
    """Open registration: the new account lands in 'pending' state and
    cannot log in until an admin approves it."""
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    display_name = str(data.get("display_name", "")).strip()
    if len(username) < 3 or not re.fullmatch(r"[a-z0-9_.-]+", username):
        return JSONResponse({"error": "用户名至少3位，仅允许小写字母/数字/._-"}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"error": "密码至少6位"}, status_code=400)
    with get_db() as db:
        dup = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if dup:
            return JSONResponse({"error": "用户名已存在"}, status_code=400)
        now_iso = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT INTO users (username, display_name, password_hash, role, status, is_active)
               VALUES (?, ?, ?, 'viewer', 'pending', 1)""",
            (username, display_name or username, _hash_password(password)),
        )
        db.commit()
    return {"ok": True, "status": "pending", "message": "注册成功，账号待管理员批准"}


@app.post("/api/auth/username")
async def auth_change_username(data: dict = Body(...), user_payload=Depends(require_auth)):
    """Self-service username change. A fresh session token is issued
    because the old one carries the previous username."""
    new_username = str(data.get("new_username", "")).strip().lower()
    if len(new_username) < 3 or not re.fullmatch(r"[a-z0-9_.-]+", new_username):
        raise HTTPException(status_code=400, detail="用户名至少3位，仅允许小写字母/数字/._-")
    uid = user_payload.get("uid")
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        if new_username != user["username"]:
            dup = db.execute("SELECT id FROM users WHERE username = ?", (new_username,)).fetchone()
            if dup:
                raise HTTPException(status_code=400, detail="用户名已存在")
            db.execute(
                "UPDATE users SET username = ?, updated_at = ? WHERE id = ?",
                (new_username, datetime.now(timezone.utc).isoformat(), uid),
            )
            db.commit()
    token = _create_token(new_username, uid, user_payload.get("role", "viewer"))
    resp = JSONResponse({"ok": True, "username": new_username, "token": token})
    _set_auth_cookie(resp, token)
    return resp


def _get_status(row, default="approved"):
    try:
        return row["status"] or default
    except (IndexError, KeyError):
        return default


@app.get("/api/admin/pending-users")
async def admin_pending_users(user_payload=Depends(require_admin)):
    """Accounts waiting for approval."""
    with get_db() as db:
        rows = db.execute(
            "SELECT id, username, display_name, role, status, created_at FROM users WHERE status = 'pending' ORDER BY id"
        ).fetchall()
        return {"users": [_row_to_dict(r) for r in rows]}


@app.post("/api/admin/users/{user_id:int}/approve")
async def admin_approve_user(user_id: int, user_payload=Depends(require_admin)):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if _get_status(user) != "pending":
            raise HTTPException(status_code=400, detail="该账号不在待审批状态")
        db.execute("UPDATE users SET status = 'approved', updated_at = ? WHERE id = ?",
                   (datetime.now(timezone.utc).isoformat(), user_id))
        db.commit()
    return {"ok": True, "status": "approved"}


@app.post("/api/admin/users/{user_id:int}/reject")
async def admin_reject_user(user_id: int, user_payload=Depends(require_admin)):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if _get_status(user) != "pending":
            raise HTTPException(status_code=400, detail="该账号不在待审批状态")
        db.execute("UPDATE users SET status = 'rejected', updated_at = ? WHERE id = ?",
                   (datetime.now(timezone.utc).isoformat(), user_id))
        db.commit()
    return {"ok": True, "status": "rejected"}


# -- SQLite Schema --

def _table_has_column(db, table: str, column: str) -> bool:
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def _admin_user_id(db) -> int:
    """管理员账号 id。旧库共享的收藏/观看历史存量数据统一归属到管理员账号。"""
    row = db.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else 1


def _init_db_schema():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_FILE))
    db.row_factory = sqlite3.Row

    # WAL 模式：读不阻塞写、写不阻塞读，避免长事务（如全量导入）在
    # delete 日志模式的 PENDING/EXCLUSIVE 阶段把所有读请求一起堵死。
    # 幂等：已是 WAL 时为 no-op；对全新数据卷首次启动即生效。
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=15000")
    db.commit()

    # 1. projects table
    db.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE,
            description TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_projects_slug ON projects(slug)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_projects_active ON projects(is_active)")

    # 2. users table
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            status TEXT NOT NULL DEFAULT 'approved',
            is_active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
    if not _table_has_column(db, "users", "status"):
        db.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'")
    db.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
    if not _table_has_column(db, "users", "must_change_password"):
        db.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")

    # 3. user_projects table
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, project_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_up_user ON user_projects(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_up_project ON user_projects(project_id)")

    # 4. videos table
    db.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bangou TEXT UNIQUE,
            title TEXT NOT NULL,
            cover TEXT,
            url TEXT,
            region TEXT,
            group_name TEXT,
            date TEXT,
            site TEXT,
            tags TEXT DEFAULT '',
            overview TEXT,
            original_title TEXT,
            backdrop TEXT,
            rating REAL,
            rating_source TEXT,
            vote_count INTEGER,
            year TEXT,
            first_air_date TEXT,
            runtime INTEGER,
            status TEXT,
            original_language TEXT,
            homepage TEXT,
            certification TEXT,
            country TEXT,
            studio TEXT,
            logo TEXT,
            popularity REAL,
            view_count INTEGER,
            trending_rank INTEGER,
            cast TEXT,
            director TEXT,
            cast_structured TEXT,
            director_structured TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            first_imported_at TIMESTAMP,
            import_batch_id TEXT,
            project_id INTEGER NOT NULL DEFAULT 1
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_videos_bangou ON videos(bangou)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_videos_region ON videos(region)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_videos_first_imported ON videos(first_imported_at DESC)")
    if not _table_has_column(db, "videos", "project_id"):
        db.execute("ALTER TABLE videos ADD COLUMN project_id INTEGER NOT NULL DEFAULT 1")
    db.execute("CREATE INDEX IF NOT EXISTS idx_videos_project ON videos(project_id)")

    # 5. series table
    db.execute("""
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bangou TEXT UNIQUE,
            title TEXT NOT NULL,
            original_title TEXT,
            cover TEXT,
            region TEXT,
            group_name TEXT,
            date TEXT,
            site TEXT,
            tags TEXT DEFAULT '',
            overview TEXT,
            backdrop TEXT,
            rating REAL,
            rating_source TEXT,
            vote_count INTEGER,
            year TEXT,
            first_air_date TEXT,
            runtime INTEGER,
            status TEXT,
            original_language TEXT,
            homepage TEXT,
            certification TEXT,
            country TEXT,
            studio TEXT,
            logo TEXT,
            popularity REAL,
            view_count INTEGER,
            trending_rank INTEGER,
            number_of_seasons INTEGER,
            number_of_episodes INTEGER,
            cast TEXT,
            director TEXT,
            cast_structured TEXT,
            director_structured TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            first_imported_at TIMESTAMP,
            import_batch_id TEXT,
            project_id INTEGER NOT NULL DEFAULT 1
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_series_bangou ON series(bangou)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_series_region ON series(region)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_series_first_imported ON series(first_imported_at DESC)")
    if not _table_has_column(db, "series", "project_id"):
        db.execute("ALTER TABLE series ADD COLUMN project_id INTEGER NOT NULL DEFAULT 1")
    db.execute("CREATE INDEX IF NOT EXISTS idx_series_project ON series(project_id)")

    # 6. seasons
    db.execute("""
        CREATE TABLE IF NOT EXISTS seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER NOT NULL,
            season_number INTEGER NOT NULL,
            season_title TEXT,
            season_cover TEXT,
            season_overview TEXT,
            season_date TEXT,
            episode_count INTEGER,
            sort_order REAL NOT NULL DEFAULT 1000,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_seasons_series ON seasons(series_id)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_seasons_number ON seasons(series_id, season_number)")

    # 7. episodes
    db.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id INTEGER NOT NULL,
            ep_id TEXT,
            ep_number INTEGER,
            ep_title TEXT,
            air_date TEXT,
            duration INTEGER,
            ep_overview TEXT,
            ep_rating REAL,
            ep_rating_source TEXT,
            ep_still TEXT,
            sort_order REAL NOT NULL DEFAULT 1000,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(season_id)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_number ON episodes(season_id, ep_number)")

    # 8. urls
    db.execute("""
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            url TEXT NOT NULL,
            url_hash TEXT NOT NULL,
            source TEXT,
            label TEXT,
            resolution TEXT,
            bandwidth INTEGER,
            url_type TEXT DEFAULT 'stream',
            priority INTEGER DEFAULT 99,
            is_active INTEGER DEFAULT 1,
            is_primary INTEGER DEFAULT 0,
            is_backup INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            project_id INTEGER NOT NULL DEFAULT 1
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_urls_target ON urls(target_type, target_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_urls_hash ON urls(url_hash)")
    if not _table_has_column(db, "urls", "project_id"):
        db.execute("ALTER TABLE urls ADD COLUMN project_id INTEGER NOT NULL DEFAULT 1")
    db.execute("CREATE INDEX IF NOT EXISTS idx_urls_project ON urls(project_id)")

    # urls migration: add url_type if missing
    try:
        db.execute("SELECT url_type FROM urls LIMIT 1")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE urls ADD COLUMN url_type TEXT DEFAULT 'stream'")

    # 9. url_probes
    db.execute("""
        CREATE TABLE IF NOT EXISTS url_probes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            url_hash TEXT NOT NULL,
            latency_ms REAL,
            rate_mbps REAL,
            resolution TEXT,
            total_score REAL,
            consecutive_success INTEGER DEFAULT 0,
            is_success INTEGER DEFAULT 0,
            probed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_probes_hash ON url_probes(url_hash, probed_at DESC)")

    # 10. categories
    db.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            parent_id INTEGER,
            level INTEGER NOT NULL DEFAULT 1,
            sort_order REAL NOT NULL DEFAULT 1000,
            is_user_defined INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            project_id INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_categories_sort ON categories(sort_order)")
    if not _table_has_column(db, "categories", "project_id"):
        db.execute("ALTER TABLE categories ADD COLUMN project_id INTEGER NOT NULL DEFAULT 1")
    db.execute("CREATE INDEX IF NOT EXISTS idx_categories_project ON categories(project_id)")

    # 11. suspense
    db.execute("""
        CREATE TABLE IF NOT EXISTS suspense (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            reason TEXT,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            project_id INTEGER NOT NULL DEFAULT 1
        )
    """)
    if not _table_has_column(db, "suspense", "project_id"):
        db.execute("ALTER TABLE suspense ADD COLUMN project_id INTEGER NOT NULL DEFAULT 1")

    # 12. favorites (P2-8: 增加 user_id 列，收藏按账号隔离)
    db.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL DEFAULT 'video',
            target_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            project_id INTEGER NOT NULL DEFAULT 1,
            user_id INTEGER NOT NULL DEFAULT 1
        )
    """)
    if not _table_has_column(db, "favorites", "project_id"):
        db.execute("ALTER TABLE favorites ADD COLUMN project_id INTEGER NOT NULL DEFAULT 1")
    # P2-8 旧库迁移：补 user_id 列，存量共享数据归属到管理员账号
    if not _table_has_column(db, "favorites", "user_id"):
        _fav_admin = _admin_user_id(db)
        db.execute(f"ALTER TABLE favorites ADD COLUMN user_id INTEGER NOT NULL DEFAULT {_fav_admin}")
    else:
        db.execute("UPDATE favorites SET user_id = ? WHERE user_id IS NULL OR user_id = 0", (_admin_user_id(db),))
    # 旧的全局唯一索引会阻止多账号收藏同一目标（INSERT OR REPLACE 互踩根因），替换为按用户唯一
    db.execute("DROP INDEX IF EXISTS idx_fav_target")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_fav_user_target ON favorites(user_id, target_type, target_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_favorites_project ON favorites(project_id)")

    # 13. history (P2-8: 增加 user_id 列，观看历史按账号隔离)
    db.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL DEFAULT 'video',
            target_id INTEGER NOT NULL,
            progress REAL DEFAULT 0,
            watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            project_id INTEGER NOT NULL DEFAULT 1,
            user_id INTEGER NOT NULL DEFAULT 1
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_history_watched ON history(watched_at DESC)")
    if not _table_has_column(db, "history", "project_id"):
        db.execute("ALTER TABLE history ADD COLUMN project_id INTEGER NOT NULL DEFAULT 1")
    # P2-8 旧库迁移：补 user_id 列，存量共享数据归属到管理员账号
    if not _table_has_column(db, "history", "user_id"):
        _hist_admin = _admin_user_id(db)
        db.execute(f"ALTER TABLE history ADD COLUMN user_id INTEGER NOT NULL DEFAULT {_hist_admin}")
    else:
        db.execute("UPDATE history SET user_id = ? WHERE user_id IS NULL OR user_id = 0", (_admin_user_id(db),))
    db.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON history(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_history_project ON history(project_id)")

    # 14. live_channels (design doc DDL extended with multi-source fields)
    db.execute("""
        CREATE TABLE IF NOT EXISTS live_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            tvg_id TEXT,
            group_name TEXT NOT NULL DEFAULT '未分组',
            logo_url TEXT,
            stream_url TEXT,
            source_region TEXT NOT NULL DEFAULT 'default',
            source_generator TEXT,
            speed_mbps REAL,
            delay_ms REAL,
            current_source_id INTEGER,
            last_probe_speed REAL,
            last_probe_delay REAL,
            last_probe_at TIMESTAMP,
            probe_status TEXT DEFAULT 'unknown',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_live_group ON live_channels(group_name)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_live_region ON live_channels(source_region)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_live_active ON live_channels(is_active)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_live_sort ON live_channels(group_name, sort_order)")

    # 15. live_channel_sources (multi-source extension)
    db.execute("""
        CREATE TABLE IF NOT EXISTS live_channel_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            node_ip TEXT,
            isp TEXT,
            speed_mbps REAL,
            delay_ms REAL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_default INTEGER NOT NULL DEFAULT 0,
            last_probe_speed REAL,
            last_probe_delay REAL,
            last_probe_at TIMESTAMP,
            probe_status TEXT DEFAULT 'unknown',
            fail_count INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES live_channels(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_live_sources_channel ON live_channel_sources(channel_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_live_sources_default ON live_channel_sources(channel_id, is_default)")

    # 16. auto_update_configs (per design doc DDL; use_proxy added for
    #     per-source proxy pulling)
    db.execute("""
        CREATE TABLE IF NOT EXISTS auto_update_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_path TEXT NOT NULL,
            is_remote INTEGER NOT NULL DEFAULT 0,
            use_proxy INTEGER NOT NULL DEFAULT 0,
            update_interval INTEGER NOT NULL DEFAULT 3600,
            last_run_at TIMESTAMP,
            next_run_at TIMESTAMP,
            last_status TEXT DEFAULT 'pending',
            last_result TEXT,
            fail_count INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_auc_active ON auto_update_configs(is_active)")
    if not _table_has_column(db, "auto_update_configs", "use_proxy"):
        db.execute("ALTER TABLE auto_update_configs ADD COLUMN use_proxy INTEGER NOT NULL DEFAULT 0")
    # Dual-proxy channels (pull vs play), tri-state NULL/0/1 where NULL
    # means "follow" (legacy use_proxy, then global default). Older dev
    # DBs may carry NOT NULL variants of these columns; normalize them to
    # nullable so the follow state is representable (values were all
    # defaults, and NULL falls back to legacy use_proxy at read time).
    for _col in ("proxy_pull", "proxy_play"):
        if _table_has_column(db, "auto_update_configs", _col):
            try:
                db.execute(f"ALTER TABLE auto_update_configs DROP COLUMN {_col}")
            except Exception:
                pass
        if not _table_has_column(db, "auto_update_configs", _col):
            db.execute(f"ALTER TABLE auto_update_configs ADD COLUMN {_col} INTEGER DEFAULT NULL")

    # 17. auto_update_logs (execution history; supports design checklist item)
    db.execute("""
        CREATE TABLE IF NOT EXISTS auto_update_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id INTEGER NOT NULL,
            run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL,
            message TEXT,
            videos_added INTEGER DEFAULT 0,
            videos_updated INTEGER DEFAULT 0,
            live_channels INTEGER DEFAULT 0,
            live_sources INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            FOREIGN KEY (config_id) REFERENCES auto_update_configs(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_auto_logs_config ON auto_update_logs(config_id, run_at DESC)")

    # 18. organize_rules (merge/transfer rules with project dimension;
    #     replayed after every import so manual organize survives re-import)
    db.execute("""
        CREATE TABLE IF NOT EXISTS organize_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            rule_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_organize_rules_project ON organize_rules(project_id, id)")

    # 19. video_overrides (per-bangou manual overrides + merge-away marks)
    db.execute("""
        CREATE TABLE IF NOT EXISTS video_overrides (
            bangou TEXT NOT NULL,
            project_id INTEGER NOT NULL,
            title TEXT,
            cover TEXT,
            url TEXT,
            region TEXT,
            group_name TEXT,
            tags TEXT,
            redirect_to TEXT,
            merged_away INTEGER NOT NULL DEFAULT 0,
            dedup INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP,
            PRIMARY KEY (bangou, project_id)
        )
    """)

    if not _table_has_column(db, "live_channels", "config_id"):
        db.execute("ALTER TABLE live_channels ADD COLUMN config_id INTEGER DEFAULT NULL")
    db.execute("CREATE INDEX IF NOT EXISTS idx_live_config ON live_channels(config_id)")

    if not _table_has_column(db, "videos", "config_id"):
        db.execute("ALTER TABLE videos ADD COLUMN config_id INTEGER DEFAULT NULL")
    db.execute("CREATE INDEX IF NOT EXISTS idx_videos_config ON videos(config_id)")

    if not _table_has_column(db, "series", "config_id"):
        db.execute("ALTER TABLE series ADD COLUMN config_id INTEGER DEFAULT NULL")
    db.execute("CREATE INDEX IF NOT EXISTS idx_series_config ON series(config_id)")

    try:
        cnt_configs = db.execute("SELECT COUNT(*) FROM auto_update_configs").fetchone()[0]
        if cnt_configs == 0:
            regions = db.execute("SELECT DISTINCT source_region FROM live_channels WHERE source_region != ''").fetchall()
            for r in regions:
                region_val = r["source_region"]
                name_val = f"直播源 - {region_val}"
                path_val = "http://192.168.89.10:8904/m3u/suentv-anhui.json" if region_val == "anhui" else f"live-{region_val}.json"
                cur = db.execute(
                    """INSERT INTO auto_update_configs
                       (name, source_type, source_path, is_remote, use_proxy, update_interval,
                        last_run_at, next_run_at, last_status, last_result, fail_count, is_active, created_at, updated_at)
                       VALUES (?, 'live', ?, 1, 0, 3600, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'success', '已导入', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    (name_val, path_val),
                )
                new_cid = cur.lastrowid
                db.execute("UPDATE live_channels SET config_id = ? WHERE source_region = ? AND (config_id IS NULL OR config_id = 0)", (new_cid, region_val))
    except Exception:
        pass

    # Status vocabulary unification: import paths historically wrote "ok"
    # while run_auto_update writes success/partial/failed. Normalize legacy
    # "ok" rows so the UI (which treats success as healthy) stays correct.
    try:
        db.execute("UPDATE auto_update_configs SET last_status = 'success' WHERE last_status = 'ok'")
    except Exception:
        pass

    db.commit()
    db.close()


# -- Bootstrap default data --

def _bootstrap_default_data():
    with get_db() as db:
        has_projects = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if has_projects == 0:
            db.execute(
                "INSERT INTO projects (name, slug, description, sort_order) VALUES (?, ?, ?, ?)",
                ("默认项目", "default", "系统自动创建的默认项目", 0)
            )

        has_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if has_users == 0:
            default_password = "admin123"
            default_password_hash = _hash_password(default_password)
            legacy_hash = ""
            if AUTH_FILE.exists():
                try:
                    with open(AUTH_FILE) as f:
                        old_auth = json.load(f)
                    if old_auth.get("hash"):
                        legacy_hash = old_auth["hash"]
                        default_password_hash = legacy_hash
                except Exception:
                    pass

            db.execute(
                "INSERT INTO users (username, display_name, password_hash, role, must_change_password) VALUES (?, ?, ?, ?, 1)",
                ("admin", "管理员", default_password_hash, "admin")
            )
            db.commit()
            if legacy_hash:
                print("[WARN] 首次启动: 已创建默认管理员账号 admin（沿用既有凭据哈希），请登录后立即修改密码")
            else:
                print("[WARN] 首次启动: 已创建默认管理员账号 admin / admin123，请登录后立即修改密码")


@contextmanager
def get_db():
    # busy_timeout: WAL 模式下写锁短暂冲突时等待而非立即抛 database is locked
    db = sqlite3.connect(str(DB_FILE), timeout=15)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()



# -- Helpers --

def _row_to_dict(row):
    d = dict(row)
    if "group_name" in d and "group" not in d:
        d["group"] = d.pop("group_name")
    return d


def _json_loads(val):
    if not val:
        return []
    try:
        return json.loads(val)
    except Exception:
        return []


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _ensure_bangou(item: dict) -> str:
    bangou = str(item.get("bangou") or "").strip()
    if bangou:
        return bangou
    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or "").strip()
    seed = title + url
    if seed:
        return hashlib.md5(seed.encode()).hexdigest()[:12]
    return uuid.uuid4().hex[:12]


def _parse_tags(raw):
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    if isinstance(raw, str):
        return [t.strip() for t in re.split(r"[,/|; ]+", raw) if t.strip()]
    return []


# URL 类型探测的同主机结果缓存：批量导入时同一域名动辄数百条 URL，
# 逐条网络探测既慢又容易把服务拖垮，每个主机只探测一次
_url_type_cache: dict = {}
_url_type_cache_lock = threading.Lock()


def _detect_url_type(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return "stream"
    # 常见流媒体直链按扩展名直接判定，批量导入时不再逐条发起网络探测
    if re.search(r"\.(m3u8|mpd|mp4|ts|flv|mkv|webm|avi|mov)(\?|#|$)", url, re.I):
        return "stream"
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    with _url_type_cache_lock:
        if host in _url_type_cache:
            return _url_type_cache[host]
    result = "stream"
    try:
        settings = load_settings()
        proxy = settings.get("proxy", "")
        proxies = {"http": proxy, "https": proxy} if proxy and _site_proxy_enabled(url, settings) else None
        # 批量导入场景：连接超时收紧到 2 秒且不重试，探测失败按 stream 兜底
        r = requests.head(
            url, proxies=proxies, timeout=(2.0, 2.0),
            allow_redirects=True, verify=_REQUESTS_VERIFY,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        ct = r.headers.get("Content-Type", "").lower()
        if "text/html" in ct:
            result = "page"
    except Exception:
        pass
    with _url_type_cache_lock:
        _url_type_cache[host] = result
    return result


def _resolve_url_type(url: str, explicit_type: str = "") -> str:
    explicit = str(explicit_type or "").strip().lower()
    if explicit in ("page", "stream"):
        return explicit
    return _detect_url_type(url)


def _insert_urls(db, target_id: int, target_type: str, item: dict, project_id: int):
    urls_to_insert = []
    seen = set()

    def _make_url_record(url_val: str, source: str, label: str, res: str, bw, priority: int, explicit_ut: str = ""):
        ut = _resolve_url_type(url_val, explicit_ut)
        return (target_id, target_type, url_val, _url_hash(url_val), source, label, res, bw, ut, priority, project_id)

    main_url = str(item.get("url") or "").strip()
    if main_url and main_url.startswith(("http://", "https://")):
        explicit_ut = str(item.get("url_type") or "").strip()
        urls_to_insert.append(_make_url_record(main_url, "主源", "", "", None, 1, explicit_ut))
        seen.add(main_url)

    for q in item.get("qualities") or []:
        if not isinstance(q, dict):
            continue
        label = str(q.get("label") or "").strip()
        qurl = str(q.get("url") or "").strip()
        if not label or not qurl:
            continue
        if qurl in seen:
            continue
        if not qurl.startswith(("http://", "https://")):
            continue
        res = str(q.get("resolution") or "").strip()
        bw = q.get("bandwidth")
        bw = int(bw) if isinstance(bw, (int, float)) else None
        explicit_ut = str(q.get("url_type") or "").strip()
        urls_to_insert.append(_make_url_record(qurl, "清晰度", label, res, bw, 10, explicit_ut))
        seen.add(qurl)

    for a in item.get("alt_urls") or []:
        if not isinstance(a, dict):
            continue
        source = str(a.get("source") or "").strip()
        aurl = str(a.get("url") or "").strip()
        if not source or not aurl:
            continue
        if aurl in seen:
            continue
        if not aurl.startswith(("http://", "https://")):
            continue
        label = str(a.get("label") or "").strip()
        res = str(a.get("resolution") or "").strip()
        explicit_ut = str(a.get("url_type") or "").strip()
        urls_to_insert.append(_make_url_record(aurl, source, label, res, None, 20, explicit_ut))
        seen.add(aurl)

    if urls_to_insert:
        db.executemany(
            """INSERT INTO urls
            (target_id, target_type, url, url_hash, source, label, resolution, bandwidth, url_type, priority, project_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            urls_to_insert,
        )


# -- Organize Toolchain Core --
# Merge / transfer / dedup / metadata overrides with rule memory. Rules and
# overrides live in their own tables keyed by project; _apply_organize_rules
# is called at the end of every import (manual full-replace, incremental
# scan, scheduled auto-update) so manual organize results are re-applied on
# top of fresh JSON data instead of being overwritten by it.

_ORGANIZE_FIELDS = ("title", "cover", "url", "region", "group_name", "tags")


def _find_media_row(db, project_id: int, bangou: str):
    """Locate a video or series row by bangou within a project.
    Returns (table_name, row) or (None, None)."""
    for tbl in ("videos", "series"):
        row = db.execute(
            f"SELECT * FROM {tbl} WHERE bangou = ? AND project_id = ?", (bangou, project_id)
        ).fetchone()
        if row:
            return tbl, row
    return None, None


def _redirect_user_refs(db, project_id: int, src_type: str, src_id: int,
                        dst_type: str, dst_id: int):
    """Re-point favorites/history entries from a merged-away item to the
    keeper so watch history / favorites never break across a merge.
    Refs that would collide with an existing keeper ref are dropped
    (favorites has a UNIQUE(target_type, target_id) index)."""
    for tbl in ("favorites", "history"):
        db.execute(
            f"""DELETE FROM {tbl} WHERE project_id = ? AND target_type = ? AND target_id = ?
                AND id NOT IN (
                    SELECT MIN(id) FROM {tbl}
                    WHERE project_id = ? AND target_type = ? AND target_id = ?
                )""",
            (project_id, src_type, src_id, project_id, dst_type, dst_id),
        )
        db.execute(
            f"""UPDATE {tbl} SET target_type = ?, target_id = ?
                WHERE project_id = ? AND target_type = ? AND target_id = ?""",
            (dst_type, dst_id, project_id, src_type, src_id),
        )


def _drop_user_refs(db, project_id: int, target_type: str, target_id: int):
    for tbl in ("favorites", "history"):
        db.execute(
            f"DELETE FROM {tbl} WHERE project_id = ? AND target_type = ? AND target_id = ?",
            (project_id, target_type, target_id),
        )


def _remove_media_row(db, project_id: int, bangou: str, redirect_to: str = ""):
    """Delete a video/series row (with urls / seasons / episodes) and
    re-point or drop its user refs."""
    for tbl in ("videos", "series"):
        rows = db.execute(
            f"SELECT id FROM {tbl} WHERE bangou = ? AND project_id = ?", (bangou, project_id)
        ).fetchall()
        for row in rows:
            ttype = "video" if tbl == "videos" else "series"
            if redirect_to and redirect_to != bangou:
                ktbl, krow = _find_media_row(db, project_id, redirect_to)
                if krow is not None:
                    ktype = "video" if ktbl == "videos" else "series"
                    _redirect_user_refs(db, project_id, ttype, row["id"], ktype, krow["id"])
            _drop_user_refs(db, project_id, ttype, row["id"])
            if tbl == "series":
                db.execute(
                    "DELETE FROM episodes WHERE season_id IN (SELECT id FROM seasons WHERE series_id = ?)",
                    (row["id"],),
                )
                db.execute("DELETE FROM seasons WHERE series_id = ?", (row["id"],))
            db.execute(
                "DELETE FROM urls WHERE target_type = ? AND target_id = ?", (ttype, row["id"])
            )
            db.execute(f"DELETE FROM {tbl} WHERE id = ?", (row["id"],))


def _update_media_fields(db, project_id: int, bangou: str, fields: dict):
    """Apply field values to the video/series row. 'url' also refreshes the
    primary (priority=1) record in the urls table."""
    if not fields:
        return
    tbl, row = _find_media_row(db, project_id, bangou)
    if row is None:
        return
    sets, params = [], []
    for f in _ORGANIZE_FIELDS:
        if f in fields and fields[f] is not None:
            sets.append(f"{f} = ?")
            params.append(fields[f])
    if not sets:
        return
    params.append(row["id"])
    db.execute(f"UPDATE {tbl} SET {', '.join(sets)} WHERE id = ?", params)
    if fields.get("url"):
        ttype = "video" if tbl == "videos" else "series"
        primary = db.execute(
            "SELECT id FROM urls WHERE target_type = ? AND target_id = ? ORDER BY priority LIMIT 1",
            (ttype, row["id"]),
        ).fetchone()
        if primary:
            db.execute(
                "UPDATE urls SET url = ?, url_hash = ? WHERE id = ?",
                (fields["url"], _url_hash(fields["url"]), primary["id"]),
            )
        else:
            db.execute(
                """INSERT INTO urls
                (target_id, target_type, url, url_hash, source, label, url_type, priority, project_id)
                VALUES (?, ?, ?, ?, '手动覆盖', '', 'stream', 1, ?)""",
                (row["id"], ttype, fields["url"], _url_hash(fields["url"]), project_id),
            )


def _upsert_override(db, project_id: int, bangou: str, **fields):
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = db.execute(
        "SELECT * FROM video_overrides WHERE bangou = ? AND project_id = ?",
        (bangou, project_id),
    ).fetchone()
    if existing:
        sets, params = [], []
        for f in _ORGANIZE_FIELDS:
            if f in fields:
                sets.append(f"{f} = ?")
                params.append(fields[f])
        if "redirect_to" in fields:
            sets.append("redirect_to = ?")
            params.append(fields["redirect_to"])
        if "merged_away" in fields:
            sets.append("merged_away = ?")
            params.append(1 if fields["merged_away"] else 0)
        if sets:
            sets.append("updated_at = ?")
            params.append(now_iso)
            params.append(existing["bangou"])
            params.append(project_id)
            db.execute(
                f"UPDATE video_overrides SET {', '.join(sets)} WHERE bangou = ? AND project_id = ?",
                params,
            )
        else:
            db.execute(
                "UPDATE video_overrides SET updated_at = ? WHERE bangou = ? AND project_id = ?",
                (now_iso, bangou, project_id),
            )
    else:
        db.execute(
            """INSERT INTO video_overrides
            (bangou, project_id, title, cover, url, region, group_name, tags,
             redirect_to, merged_away, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                bangou, project_id,
                fields.get("title"), fields.get("cover"), fields.get("url"),
                fields.get("region"), fields.get("group_name"), fields.get("tags"),
                fields.get("redirect_to"), 1 if fields.get("merged_away") else 0,
                now_iso,
            ),
        )


def _snapshot_user_refs(db, project_id: int) -> list[tuple]:
    """Capture user refs by stable identity (bangou / ep_id) before a
    full-replace import wipes and recreates rows."""
    snap = []
    for tbl in ("favorites", "history"):
        try:
            rows = db.execute(
                f"SELECT id, target_type, target_id FROM {tbl} WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for r in rows:
            key = None
            if r["target_type"] in ("video", "series"):
                src_tbl = "videos" if r["target_type"] == "video" else "series"
                row = db.execute(
                    f"SELECT bangou FROM {src_tbl} WHERE id = ?", (r["target_id"],)
                ).fetchone()
                key = ("bangou", row["bangou"]) if row else None
            elif r["target_type"] == "episode":
                row = db.execute(
                    "SELECT ep_id FROM episodes WHERE id = ?", (r["target_id"],)
                ).fetchone()
                key = ("ep_id", row["ep_id"]) if row and row["ep_id"] else None
            if key:
                snap.append((tbl, r["target_type"], r["target_id"], key[0], key[1]))
    return snap


def _remap_user_refs(db, project_id: int, snap: list[tuple]):
    """Re-link user refs to the freshly imported rows; drop entries whose
    target no longer exists (e.g. removed by merge rules)."""
    for tbl, ttype, _old_id, kind, kval in snap:
        new_type, new_id = None, None
        if kind == "bangou":
            src_tbl = "videos" if ttype == "video" else "series"
            row = db.execute(
                f"SELECT id FROM {src_tbl} WHERE bangou = ? AND project_id = ?",
                (kval, project_id),
            ).fetchone()
            if row:
                new_type, new_id = ttype, row["id"]
        elif kind == "ep_id":
            row = db.execute(
                """SELECT e.id FROM episodes e
                   JOIN seasons s ON e.season_id = s.id
                   JOIN series se ON s.series_id = se.id
                   WHERE e.ep_id = ? AND se.project_id = ?""",
                (kval, project_id),
            ).fetchone()
            if row:
                new_type, new_id = "episode", row["id"]
        if new_id is None:
            db.execute(
                f"DELETE FROM {tbl} WHERE project_id = ? AND target_type = ? AND target_id = ?",
                (project_id, ttype, _old_id),
            )
        else:
            db.execute(
                f"""UPDATE {tbl} SET target_type = ?, target_id = ?
                    WHERE project_id = ? AND target_type = ? AND target_id = ?""",
                (new_type, new_id, project_id, ttype, _old_id),
            )


def _copy_merge_fields(db, project_id: int, keeper: str, dup_bangou: str, fields: dict) -> dict:
    """Copy title/cover/url values from the duplicate's row into the keeper
    (fields semantics: field -> source bangou). Returns the resolved
    values so callers can persist them as keeper overrides."""
    resolved = {}
    for f in ("title", "cover", "url"):
        src = fields.get(f)
        if not src or src == keeper:
            continue
        _stbl, srow = _find_media_row(db, project_id, src)
        if srow is not None and srow[f]:
            resolved[f] = srow[f]
    if resolved:
        _update_media_fields(db, project_id, keeper, resolved)
    return resolved


def _apply_organize_rules(db, project_id: int):
    """Replay merge/transfer rules (oldest first, newest wins), then field
    overrides, then enforce merged-away marks. Called after every import."""
    # 1) rules
    rules = db.execute(
        "SELECT * FROM organize_rules WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()
    for rule in rules:
        try:
            payload = json.loads(rule["payload"])
        except (ValueError, TypeError):
            continue
        if rule["rule_type"] == "merge":
            keeper = payload.get("keeper") or ""
            dups = [b for b in (payload.get("duplicates") or []) if b and b != keeper]
            fields = payload.get("fields") or {}
            _ktbl, krow = _find_media_row(db, project_id, keeper)
            if krow is None:
                continue  # conservative: keeper absent, nothing to merge into
            resolved_all: dict = {}
            for dup in dups:
                resolved = _copy_merge_fields(db, project_id, keeper, dup, fields)
                for k, v in resolved.items():
                    resolved_all[k] = v
            if resolved_all:
                _upsert_override(db, project_id, keeper, **resolved_all)
            for dup in dups:
                _remove_media_row(db, project_id, dup, redirect_to=keeper)
                _upsert_override(db, project_id, dup, merged_away=1, redirect_to=keeper)
        elif rule["rule_type"] == "transfer":
            bangous = payload.get("duplicates") or payload.get("bangous") or []
            region = payload.get("region") or None
            group_name = payload.get("group_name") or None
            for b in bangous:
                fields = {}
                if region:
                    fields["region"] = region
                if group_name:
                    fields["group_name"] = group_name
                if fields:
                    _update_media_fields(db, project_id, b, fields)
                    _upsert_override(db, project_id, b, **fields)

    # 2) field overrides (non-merged-away)
    ovs = db.execute(
        "SELECT * FROM video_overrides WHERE project_id = ? AND merged_away = 0",
        (project_id,),
    ).fetchall()
    for ov in ovs:
        fields = {f: ov[f] for f in _ORGANIZE_FIELDS if ov[f] is not None}
        if fields:
            _update_media_fields(db, project_id, ov["bangou"], fields)

    # 3) merged-away marks: keep duplicates out even if a fresh import
    #    brought them back
    away = db.execute(
        "SELECT bangou, redirect_to FROM video_overrides WHERE project_id = ? AND merged_away = 1",
        (project_id,),
    ).fetchall()
    for ov in away:
        _remove_media_row(db, project_id, ov["bangou"], redirect_to=ov["redirect_to"] or "")


# -- Settings --

def get_video_sites():
    sites = set()
    with get_db() as db:
        for tbl in ("videos", "series"):
            try:
                rows = db.execute(f"SELECT DISTINCT site FROM {tbl} WHERE site != ''").fetchall()
                sites.update(r["site"] for r in rows)
            except Exception:
                pass
        vj = get_videos_file()
        if vj and vj.exists():
            try:
                with open(vj, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    items = data if isinstance(data, list) else (data.get("items") or data.get("videos") or data.get("movies") or data.get("list") or [])
                    for v in items:
                        site_name = v.get("site") or v.get("source") or v.get("from")
                        if site_name:
                            sites.add(str(site_name))
            except Exception:
                pass
        return sorted(sites)


def load_settings():
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
    else:
        data = {"repo_url": "", "token": "", "proxy": "", "site_name": "suenplayer", "workflow_file": "harvest.yml", "data_path": ""}
    if "site_name" not in data or not data["site_name"]:
        data["site_name"] = os.environ.get("APP_TITLE", "suenplayer")
    if "workflow_file" not in data or not data["workflow_file"]:
        data["workflow_file"] = "harvest.yml"
    if "data_path" not in data:
        data["data_path"] = ""
    if "proxy_sources" not in data:
        data["proxy_sources"] = {}
    # Dual-proxy global defaults: tri-state resolution for per-source NULL
    # ("follow"). Stored as 0/1 ints.
    if "proxy_pull_default" not in data:
        data["proxy_pull_default"] = 0
    # 旧版分散代理配置一次性迁移为 proxy_rules 条目（不再使用全局默认）
    if "proxy_rules" not in data:
        subs, plays = [], []
        for cid, v in (data.get("proxy_sources") or {}).items():
            wanted = (isinstance(v, dict) and (v.get("pull") or v.get("play"))) or v == 1 or v is True
            if wanted:
                subs.append({"id": str(cid), "name": ""})
        for line in (data.get("proxy_sites") or "").splitlines():
            if line.strip():
                plays.append(line.strip())
        if subs or plays:
            data["proxy_rules"] = json.dumps({"subs": subs, "plays": plays}, ensure_ascii=False)
    if "proxy_play_default" not in data:
        data["proxy_play_default"] = 0
    # Admin-curated intranet allowlist (comma/semicolon/newline separated
    # hostnames, IPs or CIDRs, e.g. "192.168.89.10, 10.0.0.0/8"). Entries
    # here bypass the SSRF private-address block for admin-configured
    # source addresses (pull + remote import), so LAN IPTV/NAS sources work.
    if "private_allowlist" not in data:
        data["private_allowlist"] = ""
    defaults = {"git": True}
    for k, v in defaults.items():
        if k not in data["proxy_sources"]:
            data["proxy_sources"][k] = v
    for site in get_video_sites():
        if site not in data["proxy_sources"]:
            data["proxy_sources"][site] = True
    real_sites = set(get_video_sites())
    for key in list(data["proxy_sources"].keys()):
        if key != "git" and key not in real_sites and key not in defaults:
            del data["proxy_sources"][key]
    return data


def save_settings(data):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if "proxy_sources" not in data:
        data["proxy_sources"] = {"git": True}
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(SETTINGS_FILE, 0o600)


# -- Version Management --

GIT_DIR = DATA_DIR / "git"
LATEST_DIR = GIT_DIR / "latest"


def _version_entry(d: Path):
    size = 0
    try:
        for f in d.rglob("*"):
            if len(f.relative_to(d).parts) <= 3 and f.is_file():
                size += f.stat().st_size
    except Exception:
        pass
    return {"name": d.name, "time": d.name[2:].replace("_", " ") if d.name.startswith("v_") else "", "size": size}


def list_versions():
    versions = []
    if GIT_DIR.exists():
        for d in sorted(GIT_DIR.iterdir()):
            if d.is_dir() and (d / "json/all/videos.json").exists():
                versions.append(_version_entry(d))
    versions.sort(key=lambda x: x["name"], reverse=True)
    return versions


def prune_versions(max_keep=3):
    versions = list_versions()
    for v in versions[max_keep:]:
        p = GIT_DIR / v["name"]
        if v["name"] != "latest":
            shutil.rmtree(p, ignore_errors=True)


@app.get("/api/versions")
async def get_versions():
    return list_versions()


@app.post("/api/versions/restore/{name}")
async def restore_version(name: str):
    src = GIT_DIR / name
    if not src.exists() or not (src / "json/all/videos.json").exists():
        return JSONResponse({"error": "版本不存在"}, status_code=404)
    dst = LATEST_DIR
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    import_videos_to_db()
    return {"ok": True, "name": name}


@app.delete("/api/versions/{name}")
async def delete_version(name: str):
    if name == "latest":
        return JSONResponse({"error": "不能删除当前版本"}, status_code=400)
    src = GIT_DIR / name
    if not src.exists():
        return JSONResponse({"error": "版本不存在"}, status_code=404)
    shutil.rmtree(src, ignore_errors=True)
    return {"ok": True}


# -- Video File Discovery --

def get_videos_file(preferred_path: str = ""):
    if preferred_path:
        p = Path(preferred_path)
        if p.exists():
            return p
    candidates = [
        LATEST_DIR / "product/videos.json",
        BASE_DIR / "product/videos.json",
        LATEST_DIR / "json/all/videos.json",
        BASE_DIR / "videos.json",
        DATA_DIR / "videos.json",
        DOWNLOAD_FILES_DIR / "videos.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None



# -- DNS 防污染（封面抓取用）--
# hosts_map: 每行「IP 域名」（兼容 hosts 格式），命中域名的请求按 IP 直连、
#            SNI/证书校验仍按真实域名（_PinnedHostAdapter）；
# doh_url:   未命中映射时经国内 DoH（如 https://223.5.5.5/resolve）解析。
# 两者都不配置则走系统 DNS。仅在封面缓存抓取路径生效。

_doh_cache: dict = {}
_hosts_map_cache: dict = {}

from requests.adapters import HTTPAdapter


class _PinnedHostAdapter(HTTPAdapter):
    """连接 URL 中的 IP，TLS SNI 与证书校验按 pinned 的真实域名进行。"""

    def __init__(self, hostname, **kwargs):
        self._pinned_hostname = hostname
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["server_hostname"] = self._pinned_hostname
        super().init_poolmanager(*args, **kwargs)


def _parse_hosts_map(text: str) -> dict:
    mapping = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        a, b = parts[0].strip(), parts[1].strip()
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", a):
            mapping[b.lower()] = a
        elif re.match(r"^\d{1,3}(\.\d{1,3}){3}$", b):
            mapping[a.lower()] = b
    return mapping


def _get_hosts_map(settings: dict) -> dict:
    text = settings.get("hosts_map", "")
    key = hash(text)
    now = time.time()
    hit = _hosts_map_cache.get("v")
    if hit and hit[0] == key:
        return hit[1]
    mapping = _parse_hosts_map(text)
    _hosts_map_cache["v"] = (key, mapping)
    return mapping


def _doh_resolve(host: str, doh_url: str) -> str | None:
    if not doh_url or not host:
        return None
    now = time.time()
    hit = _doh_cache.get(host)
    if hit and hit[1] > now:
        return hit[0]
    try:
        r = requests.get(doh_url, params={"name": host, "type": "A"},
                         timeout=5, verify=_REQUESTS_VERIFY,
                         headers={"Accept": "application/dns-json"})
        answers = [a["data"] for a in r.json().get("Answer", []) if a.get("type") == 1]
        if answers:
            _doh_cache[host] = (answers[0], now + 600)
            return answers[0]
    except Exception:
        pass
    return None


def _site_proxy_enabled(url: str, settings: dict) -> bool:
    """播放源条目：命中关键词（站点名/域名片段）的 URL 服务端请求走代理。
    未命中 = 直连（本应用不再有全局默认走代理）。"""
    plays = _proxy_rules(settings).get("plays") or []
    if not plays or not url:
        return False
    u = url.lower()
    return any(str(k).lower() in u for k in plays)


def _apply_dns_override(url: str, headers: dict, settings: dict):
    """返回 (请求URL, 请求头, 钉扎域名或 None)。无覆盖时原样返回。"""
    from urllib.parse import urlparse as _urlparse
    pu = _urlparse(url)
    host = (pu.hostname or "").lower()
    if not host or not pu.scheme == "https":
        return url, headers, None
    ip = _get_hosts_map(settings).get(host)
    source = "hosts" if ip else None
    if not ip:
        ip = _doh_resolve(host, settings.get("doh_url", "").strip())
        source = "doh" if ip else None
    if not ip:
        return url, headers, None
    netloc = f"{ip}:{pu.port}" if pu.port else ip
    new_url = pu._replace(netloc=netloc).geturl()
    new_headers = dict(headers)
    new_headers["Host"] = host
    return new_url, new_headers, host


# -- Image Cache --

def _optimize_image_bytes(data: bytes, ext: str) -> bytes:
    """Lossless optimization before writing to disk cache.

    JPEG: jpegtran (recompresses the encoded DCT data directly, so pixels are
    bit-identical; Pillow re-encoding is NOT lossless for JPEG). PNG: Pillow
    zlib optimize. Any failure or size regression returns original bytes.
    """
    ext = ext.lower().lstrip(".")
    if ext in ("jpg", "jpeg"):
        try:
            r = subprocess.run(
                ["jpegtran", "-copy", "all", "-optimize", "-progressive"],
                input=data, capture_output=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout and len(r.stdout) < len(data):
                return r.stdout
        except Exception:
            pass
        return data
    if ext != "png":
        return data
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
        out = io.BytesIO()
        im.save(out, "PNG", optimize=True)
        optimized = out.getvalue()
        return optimized if len(optimized) < len(data) else data
    except Exception:
        return data


@app.get("/api/cache/{url:path}")
async def image_cache(url: str):
    if not url.startswith("http"):
        return JSONResponse({"error": "invalid url"}, status_code=400)
    # DNS 覆盖（hosts 映射 / DoH）先于私有地址检查：被污染域名系统解析可能
    # 指向私有/保留地址，若管理员已显式映射则信任映射、跳过该检查
    _settings0 = load_settings()
    _check_url, _, _pinned0 = _apply_dns_override(url, {}, _settings0)
    if not _pinned0 and _is_private_url(_check_url):
        return JSONResponse({"error": "private url not allowed"}, status_code=400)
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    ext = Path(url.split("?")[0]).suffix or ".jpg"
    cache_path = CACHE_DIR / f"{key}{ext}"
    if cache_path.exists():
        return Response(cache_path.read_bytes(), media_type=f"image/{ext.lstrip('.')}")

    settings = load_settings()
    proxy_url = settings.get("proxy", "")
    try:
        parts = url.split("//", 1)[1]
        host = parts.split("/", 1)[0]
        scheme = url.split("//", 1)[0] + "//"
        referer = f"{scheme}{host}/"
    except ValueError:
        referer = ""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    }

    async def try_fetch():
        proxies = None
        if proxy_url and _site_proxy_enabled(url, _settings0):
            proxies = {"http": proxy_url, "https": proxy_url}
        req_url, req_headers, pinned = _apply_dns_override(url, headers, _settings0)

        def _fetch():
            if pinned:
                sess = requests.Session()
                sess.mount(f"https://", _PinnedHostAdapter(pinned))
                return sess.get(req_url, headers=req_headers, timeout=(5, 12), verify=_REQUESTS_VERIFY)
            return _requests_get_safe_redirects(req_url, headers=req_headers, proxies=proxies, timeout=(5, 12), verify=_REQUESTS_VERIFY)

        try:
            r = await asyncio.to_thread(_fetch)
            if r.status_code == 200 and r.content:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                content = await asyncio.to_thread(_optimize_image_bytes, r.content, ext)
                await asyncio.to_thread(cache_path.write_bytes, content)
                return Response(content, media_type=f"image/{ext.lstrip('.')}")
        except Exception as e:
            print(f"[cache] {url.split('/')[-1][:30]} failed: {e}", flush=True)
        return None

    for attempt in range(3):
        resp = await try_fetch()
        if resp:
            return resp
        if attempt < 2:
            await asyncio.sleep(3)

    return JSONResponse({"error": "fetch failed"}, status_code=404)


# -- Fresh URL --

_FRESH_URL_EXTRACTORS = {
    "rusvideos": {
        "matcher": lambda url: "/rolik/" in url,
        "transform": lambda url: url.replace("/rolik/", "/embeded/"),
        "extract": lambda text: (
            (m.group(0) and "https://rusvideos.net" + m.group(1))
            if (m := re.search(r'file["\']?\s*:\s*["\'](/videorolik/[^"\']+)["\']', text))
            else ""
        ),
    }
}


def _resolve_fresh_url(url: str) -> dict:
    settings = load_settings()
    proxy = settings.get("proxy", "") if _site_proxy_enabled(url, settings) else ""
    for name, extractor in _FRESH_URL_EXTRACTORS.items():
        if extractor["matcher"](url):
            embed_url = extractor["transform"](url)
            proxies = {"http": proxy, "https": proxy} if proxy else None
            try:
                r = requests.get(
                    embed_url, proxies=proxies, timeout=10,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Referer": "https://rusvideos.com/",
                    },
                )
                r.encoding = "utf-8"
                video_url = extractor["extract"](r.text)
                if video_url:
                    return {"url": video_url}
            except Exception as e:
                return {"error": str(e)}
            return {"error": "video url not found"}

    # 通用兜底（不认识的站点也能解析）：
    # 1) 抓取页面源码，扫描其中出现的 m3u8/mp4 流地址
    # 2) 扫不到时尝试「页面地址 + /index.m3u8」约定（常见播放页模式）
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = requests.get(
            url, proxies=proxies, timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": url.rsplit("/", 2)[0] + "/",
            },
        )
        r.encoding = r.apparent_encoding or "utf-8"
        candidates = re.findall(
            r'https?://[^\s"\'<>]+?\.(?:m3u8|mp4)(?:\?[^\s"\'<>]*)?', r.text, re.I
        )
        candidates.sort(key=lambda u: 0 if ".m3u8" in u.lower() else 1)
        if candidates:
            return {"url": candidates[0]}
        if re.search(r"/play/[^/]+/?$", url):
            return {"url": url.rstrip("/") + "/index.m3u8"}
    except Exception as e:
        return {"error": str(e)}
    return {"error": "video url not found"}


@app.get("/api/fresh-url")
def get_fresh_url(url: str):
    result = _resolve_fresh_url(url)
    if "error" in result:
        status = 502 if result["error"] == "video url not found" else (400 if result["error"] == "unsupported url pattern" else 502)
        return JSONResponse(result, status_code=status)
    return result


# -- Video Proxy --

def _proxy_headers():
    return {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _requests_get_safe_redirects(url: str, max_redirects: int = 5, allow_private: bool = False, **kwargs):
    current_url = url
    for _ in range(max_redirects):
        resp = requests.get(current_url, allow_redirects=False, **kwargs)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                raise requests.exceptions.RequestException("重定向缺少 Location")
            current_url = urllib.parse.urljoin(current_url, location)
            if not allow_private and _is_private_url(current_url):
                raise requests.exceptions.RequestException("重定向到私有地址被拒绝")
            continue
        return resp
    raise requests.exceptions.RequestException("重定向次数超过限制")


@app.get("/api/proxy")
def proxy_content(url: str = "", request: Request = None):
    if not url:
        return JSONResponse({"error": "no url"}, status_code=400)
    if _is_private_url(url):
        return JSONResponse({"error": "private url not allowed"}, status_code=400)
    settings = load_settings()
    proxy = settings.get("proxy", "")
    if not proxy:
        return RedirectResponse(url=url, status_code=302)

    proxies = {"http": proxy, "https": proxy}
    headers = _proxy_headers()
    try:
        parts = urllib.parse.urlsplit(url)
        target_origin = f"{parts.scheme}://{parts.netloc}/"
    except ValueError:
        target_origin = ""
    if target_origin:
        headers["Referer"] = target_origin
    range_header = request.headers.get("range") if request else None
    if range_header:
        headers["Range"] = range_header

    try:
        resp = _requests_get_safe_redirects(url, proxies=proxies, headers=headers, timeout=60, stream=True, verify=_REQUESTS_VERIFY)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        is_m3u8 = "mpegurl" in ct or ".m3u8" in url

        if not is_m3u8:
            resp_headers = {}
            for h in ("content-length", "content-range", "accept-ranges"):
                if h in resp.headers:
                    resp_headers[h] = resp.headers[h]
            status = 206 if range_header else 200
            return StreamingResponse(
                resp.iter_content(chunk_size=65536),
                status_code=status,
                headers=resp_headers,
                media_type=ct or "application/octet-stream"
            )

        content = resp.text
        def _proxied(target):
            return f'/api/proxy?url={urllib.parse.quote(urllib.parse.urljoin(url, target), safe="")}'
        lines = []
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                lines.append(line)
                continue
            if stripped.startswith(("#EXT-X-KEY:", "#EXT-X-MAP:")) and 'URI="' in stripped:
                line = re.sub(r'URI="([^"]+)"', lambda m: f'URI="{_proxied(m.group(1))}"', line)
                lines.append(line)
            elif stripped.startswith("#"):
                lines.append(line)
            else:
                lines.append(_proxied(stripped))
        return Response("\n".join(lines).encode(), media_type="application/vnd.apple.mpegurl")

    except requests.RequestException as e:
        return JSONResponse({"error": str(e)}, status_code=502)



# -- API: Videos & Series (with project filtering) --

def _get_visible_projects_from_request(request: Request) -> list[int]:
    token = _get_token_from_request(request)
    payload = _decode_token(token) if token else None
    if payload:
        return _get_user_visible_projects(payload)
    # Defense in depth: an anonymous caller must never fall back to the
    # full project list. The auth middleware already rejects anonymous
    # /api/* requests with 401; if this helper is ever reached without a
    # valid token it must answer with an empty (deny-all) scope.
    return []


@app.get("/api/videos")
async def get_videos(
    q: str = "", region: str = "", group: str = "",
    tags: str = "", bangou: str = "", site: str = "",
    actor: str = "",
    page: int = 1, limit: int = 60,
    request: Request = None
):
    limit = min(limit, 200)
    visible_projects = _get_visible_projects_from_request(request)
    if not visible_projects:
        return {"total": 0, "page": 1, "items": []}

    with get_db() as db:
        conditions = ["1=1"]
        params = []
        proj_clause, proj_params = _project_filter_clause(visible_projects)
        conditions.append(proj_clause)
        params.extend(proj_params)

        if q:
            like = f"%{q}%"
            conditions.append("(title LIKE ? OR bangou LIKE ?)")
            params.extend([like, like])
        if region:
            conditions.append("region = ?")
            params.append(region)
        if group:
            conditions.append("group_name = ?")
            params.append(group)
        if tags:
            tag_conds = []
            for t in tags.split(","):
                t = t.strip()
                if t:
                    tag_conds.append("tags LIKE ?")
                    params.append(f"%{t}%")
            if tag_conds:
                conditions.append("(" + " OR ".join(tag_conds) + ")")
        if site:
            site_conds = []
            for s in site.split(","):
                s = s.strip()
                if s:
                    site_conds.append("site = ?")
                    params.append(s)
            if site_conds:
                conditions.append("(" + " OR ".join(site_conds) + ")")
        if bangou:
            conditions.append("bangou LIKE ?")
            params.append(f"%{bangou}%")
        if actor:
            like = f"%{actor}%"
            conditions.append('("cast" LIKE ? OR "cast_structured" LIKE ?)')
            params.extend([like, like])
        where = " WHERE " + " AND ".join(conditions)
        total = db.execute(f"SELECT COUNT(*) FROM videos{where}", params).fetchone()[0]
        offset = (page - 1) * limit
        sort_key = (request.query_params.get("sort") or "date").strip().lower()
        order_by = _LIST_SORTS.get(sort_key, "date DESC")
        rows = db.execute(
            f"SELECT * FROM videos{where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        items = []
        for r in rows:
            d = _row_to_dict(r)
            d["type"] = "video"
            items.append(d)
        return {"total": total, "page": page, "items": items}


@app.get("/api/series")
async def get_series(
    q: str = "", region: str = "", group: str = "",
    tags: str = "", bangou: str = "", site: str = "",
    actor: str = "",
    page: int = 1, limit: int = 60,
    request: Request = None
):
    limit = min(limit, 200)
    visible_projects = _get_visible_projects_from_request(request)
    if not visible_projects:
        return {"total": 0, "page": 1, "items": []}

    with get_db() as db:
        conditions = ["1=1"]
        params = []
        proj_clause, proj_params = _project_filter_clause(visible_projects)
        conditions.append(proj_clause)
        params.extend(proj_params)

        if q:
            like = f"%{q}%"
            conditions.append("(title LIKE ? OR bangou LIKE ?)")
            params.extend([like, like])
        if region:
            conditions.append("region = ?")
            params.append(region)
        if group:
            conditions.append("group_name = ?")
            params.append(group)
        if tags:
            tag_conds = []
            for t in tags.split(","):
                t = t.strip()
                if t:
                    tag_conds.append("tags LIKE ?")
                    params.append(f"%{t}%")
            if tag_conds:
                conditions.append("(" + " OR ".join(tag_conds) + ")")
        if site:
            site_conds = []
            for s in site.split(","):
                s = s.strip()
                if s:
                    site_conds.append("site = ?")
                    params.append(s)
            if site_conds:
                conditions.append("(" + " OR ".join(site_conds) + ")")
        if bangou:
            conditions.append("bangou LIKE ?")
            params.append(f"%{bangou}%")
        if actor:
            like = f"%{actor}%"
            conditions.append('("cast" LIKE ? OR "cast_structured" LIKE ?)')
            params.extend([like, like])
        where = " WHERE " + " AND ".join(conditions)
        total = db.execute(f"SELECT COUNT(*) FROM series{where}", params).fetchone()[0]
        offset = (page - 1) * limit
        sort_key = (request.query_params.get("sort") or "date").strip().lower()
        order_by = _LIST_SORTS.get(sort_key, "date DESC")
        rows = db.execute(
            f"SELECT * FROM series{where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        items = []
        for r in rows:
            d = _row_to_dict(r)
            d["type"] = "series"
            items.append(d)
        return {"total": total, "page": page, "items": items}


@app.get("/api/actor")
async def get_actor(
    name: str = "",
    page: int = 1, limit: int = 60,
    request: Request = None
):
    if not name:
        return JSONResponse({"error": "name parameter required"}, status_code=400)
    limit = min(limit, 200)
    videos_resp = await get_videos(actor=name, page=page, limit=limit, request=request)
    series_resp = await get_series(actor=name, page=page, limit=limit, request=request)
    return {
        "actor": name,
        "videos": videos_resp,
        "series": series_resp,
    }


# -- API: Organize Toolchain (merge / transfer / dedup / overrides / rules) --
# All operations take an explicit project_id; rules only apply to imports
# of the same project.

def _organize_project_id(data: dict) -> int:
    try:
        pid = int(data.get("project_id") or 1)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="project_id 必须是整数")
    with get_db() as db:
        row = db.execute("SELECT id FROM projects WHERE id = ?", (pid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="项目不存在")
    return pid


@app.post("/api/videos/merge")
async def api_merge_videos(data: dict = Body(...), _=Depends(require_auth)):
    """Merge duplicate entries into a keeper and write a merge rule
    (highest priority, newest wins). The rule is re-applied on every
    import of this project, so re-imported duplicates never revive."""
    bangous = data.get("bangous") or []
    keeper = str(data.get("keeper") or "").strip()
    fields = data.get("fields") or {}
    if len(bangous) < 2 or not keeper or keeper not in bangous:
        return JSONResponse({"error": "请至少选择2个视频，并指定保留对象"}, status_code=400)
    project_id = _organize_project_id(data)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        _ktbl, krow = _find_media_row(db, project_id, keeper)
        if krow is None:
            return JSONResponse({"error": "保留对象不存在"}, status_code=404)
        cursor = db.execute(
            "INSERT INTO organize_rules (project_id, rule_type, payload, created_at) VALUES (?, 'merge', ?, ?)",
            (project_id, json.dumps({
                "keeper": keeper,
                "duplicates": [b for b in bangous if b != keeper],
                "fields": fields,
            }, ensure_ascii=False), now_iso),
        )
        rule_id = cursor.lastrowid
        _apply_organize_rules(db, project_id)
        db.commit()
    rule = {"id": rule_id, "type": "merge", "bangous": bangous, "keeper": keeper, "fields": fields}
    return {"ok": True, "rule": rule}


@app.post("/api/videos/transfer")
async def api_transfer_videos(data: dict = Body(...), _=Depends(require_auth)):
    """Move entries to a target region/group and write a transfer rule
    that is re-applied on every import of this project."""
    bangous = data.get("bangous") or []
    region = str(data.get("region") or "").strip()
    group = str(data.get("group") or data.get("group_name") or "").strip()
    if not bangous or not region or not group:
        return JSONResponse({"error": "请选择目标分类"}, status_code=400)
    project_id = _organize_project_id(data)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        cursor = db.execute(
            "INSERT INTO organize_rules (project_id, rule_type, payload, created_at) VALUES (?, 'transfer', ?, ?)",
            (project_id, json.dumps({
                "bangous": bangous, "region": region, "group_name": group,
            }, ensure_ascii=False), now_iso),
        )
        rule_id = cursor.lastrowid
        _apply_organize_rules(db, project_id)
        db.commit()
    rule = {"id": rule_id, "type": "transfer", "bangous": bangous, "region": region, "group": group}
    return {"ok": True, "rule": rule}


@app.put("/api/videos/{bangou}/dedup")
async def dedup_videos(bangou: str, data: dict = Body(...), _=Depends(require_auth)):
    """Dedup helper: mark `removed` bangous as merged away into `bangou`
    and optionally copy field values from them. Marks are persisted so
    re-imported duplicates are removed again (without creating a rule)."""
    removed = data.get("removed") or []
    fields = data.get("fields") or {}
    project_id = _organize_project_id(data)
    with get_db() as db:
        _ktbl, krow = _find_media_row(db, project_id, bangou)
        if krow is None:
            return JSONResponse({"error": "条目不存在"}, status_code=404)
        redirects = {}
        for r in removed:
            r = str(r).strip()
            if not r or r == bangou:
                continue
            _stbl, srow = _find_media_row(db, project_id, r)
            if srow is None:
                continue
            resolved = _copy_merge_fields(db, project_id, bangou, r, fields)
            if resolved:
                _upsert_override(db, project_id, bangou, **resolved)
            _remove_media_row(db, project_id, r, redirect_to=bangou)
            _upsert_override(db, project_id, r, merged_away=1, redirect_to=bangou)
            redirects[r] = bangou
        db.commit()
    return {"ok": True, "redirects": redirects}


@app.get("/api/videos/{bangou}/dedup-info")
async def dedup_info(bangou: str, project_id: int = 1, _=Depends(require_auth)):
    """Report merge/dedup status of one bangou within a project."""
    result = {"bangou": bangou, "project_id": project_id, "is_merged_away": False}
    with get_db() as db:
        ov = db.execute(
            "SELECT * FROM video_overrides WHERE bangou = ? AND project_id = ?",
            (bangou, project_id),
        ).fetchone()
        if ov is not None:
            if ov["merged_away"]:
                result["is_merged_away"] = True
                result["merged_into"] = ov["redirect_to"]
            overridden = {k: ov[k] for k in _ORGANIZE_FIELDS if ov[k] is not None}
            if overridden:
                result["overrides"] = overridden
        merged_from = [
            r["bangou"] for r in db.execute(
                """SELECT bangou FROM video_overrides
                   WHERE project_id = ? AND redirect_to = ? AND merged_away = 1""",
                (project_id, bangou),
            ).fetchall()
        ]
        if merged_from:
            result["merged_from"] = merged_from
    return result


@app.delete("/api/videos/{bangou}/dedup")
async def remove_dedup(bangou: str, project_id: int = None,
                       data: dict = Body(default={}), _=Depends(require_auth)):
    """Remove dedup/merge-away marks for a bangou (and marks pointing at
    it). Affected entries come back on the next import of this project.
    project_id is accepted as query param or JSON body field."""
    if project_id is None:
        project_id = _organize_project_id(data)
    with get_db() as db:
        db.execute(
            """UPDATE video_overrides
               SET merged_away = 0, redirect_to = NULL, updated_at = ?
               WHERE project_id = ? AND bangou = ?""",
            (datetime.now(timezone.utc).isoformat(), project_id, bangou),
        )
        db.execute(
            """UPDATE video_overrides
               SET merged_away = 0, redirect_to = NULL, updated_at = ?
               WHERE project_id = ? AND redirect_to = ? AND merged_away = 1""",
            (datetime.now(timezone.utc).isoformat(), project_id, bangou),
        )
        db.commit()
    return {"ok": True}


@app.get("/api/videos/overrides")
async def get_overrides(project_id: int = 1, _=Depends(require_auth)):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM video_overrides WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        ).fetchall()
        return {"overrides": [_row_to_dict(r) for r in rows]}


@app.put("/api/videos/overrides")
async def put_overrides(data: dict = Body(...), _=Depends(require_auth)):
    """Manual metadata override for one bangou; applied immediately and
    re-applied after every import of this project."""
    bangou = str(data.get("bangou") or "").strip()
    if not bangou:
        return JSONResponse({"error": "bangou 必填"}, status_code=400)
    project_id = _organize_project_id(data)
    fields = {k: data.get(k) for k in _ORGANIZE_FIELDS if data.get(k) is not None}
    if not fields:
        return JSONResponse({"error": "至少提供一个覆盖字段"}, status_code=400)
    if "tags" in fields and isinstance(fields["tags"], list):
        fields["tags"] = ",".join(_parse_tags(fields["tags"]))
    with get_db() as db:
        _ktbl, krow = _find_media_row(db, project_id, bangou)
        if krow is None:
            return JSONResponse({"error": "条目不存在"}, status_code=404)
        _update_media_fields(db, project_id, bangou, fields)
        _upsert_override(db, project_id, bangou, **fields)
        db.commit()
    return {"ok": True}


@app.put("/api/videos/{bangou}/tags")
async def set_video_tags(bangou: str, data: dict = Body(...), _=Depends(require_auth)):
    """Manual tag edit; persisted as an override so re-import keeps it."""
    project_id = _organize_project_id(data)
    tags = data.get("tags", [])
    tag_str = ",".join(_parse_tags(tags))
    with get_db() as db:
        _ktbl, krow = _find_media_row(db, project_id, bangou)
        if krow is None:
            return JSONResponse({"error": "条目不存在"}, status_code=404)
        _update_media_fields(db, project_id, bangou, {"tags": tag_str})
        _upsert_override(db, project_id, bangou, tags=tag_str)
        db.commit()
    return {"ok": True, "tags": tag_str}


@app.put("/api/videos/{bangou}/category")
async def set_video_category(bangou: str, data: dict = Body(...), _=Depends(require_auth)):
    """Manual region/group edit; persisted as an override so re-import
    keeps it."""
    region = str(data.get("region") or "").strip()
    group = str(data.get("group") or data.get("group_name") or "").strip()
    if not region and not group:
        return JSONResponse({"error": "请提供 region 或 group"}, status_code=400)
    project_id = _organize_project_id(data)
    fields = {}
    if region:
        fields["region"] = region
    if group:
        fields["group_name"] = group
    with get_db() as db:
        _ktbl, krow = _find_media_row(db, project_id, bangou)
        if krow is None:
            return JSONResponse({"error": "条目不存在"}, status_code=404)
        _update_media_fields(db, project_id, bangou, fields)
        _upsert_override(db, project_id, bangou, **fields)
        db.commit()
    return {"ok": True}


@app.get("/api/rules")
async def api_get_rules(project_id: int = None, _=Depends(require_auth)):
    """List accumulated organize rules (optionally filtered by project)."""
    with get_db() as db:
        if project_id is None:
            rows = db.execute("SELECT * FROM organize_rules ORDER BY id").fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM organize_rules WHERE project_id = ? ORDER BY id", (project_id,)
            ).fetchall()
        out = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except (ValueError, TypeError):
                payload = {}
            out.append({
                "id": r["id"],
                "project_id": r["project_id"],
                "type": r["rule_type"],
                **payload,
                "created_at": r["created_at"],
            })
        return {"rules": out}


@app.delete("/api/rules/{rule_id:int}")
async def api_delete_rule(rule_id: int, _=Depends(require_auth)):
    """Delete a rule. Merge-away marks created by that rule are lifted so
    the affected duplicates return on the next import."""
    with get_db() as db:
        rule = db.execute("SELECT * FROM organize_rules WHERE id = ?", (rule_id,)).fetchone()
        if not rule:
            return JSONResponse({"error": "规则不存在"}, status_code=404)
        if rule["rule_type"] == "merge":
            try:
                payload = json.loads(rule["payload"])
            except (ValueError, TypeError):
                payload = {}
            keeper = payload.get("keeper") or ""
            for dup in payload.get("duplicates") or []:
                db.execute(
                    """UPDATE video_overrides
                       SET merged_away = 0, redirect_to = NULL, updated_at = ?
                       WHERE project_id = ? AND bangou = ? AND redirect_to = ?""",
                    (datetime.now(timezone.utc).isoformat(), rule["project_id"], dup, keeper),
                )
        db.execute("DELETE FROM organize_rules WHERE id = ?", (rule_id,))
        db.commit()
    return {"ok": True}


@app.get("/api/videos/{bangou:path}")
async def video_detail(bangou: str, request: Request = None):
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        row = db.execute("SELECT * FROM videos WHERE bangou = ?", (bangou,)).fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        if row["project_id"] not in visible_projects:
            return JSONResponse({"error": "not found"}, status_code=404)
        d = _row_to_dict(row)
        d["type"] = "video"
        urls = db.execute(
            "SELECT id, url, source, label, resolution, bandwidth, url_type, priority, is_active FROM urls WHERE target_type = 'video' AND target_id = ? ORDER BY priority",
            (d["id"],)
        ).fetchall()
        d["urls"] = [dict(u) for u in urls]
        return d


@app.get("/api/series/{series_id:int}")
async def series_detail(series_id: int, request: Request = None):
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        row = db.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        if row["project_id"] not in visible_projects:
            return JSONResponse({"error": "not found"}, status_code=404)
        d = _row_to_dict(row)
        d["type"] = "series"
        seasons = db.execute(
            "SELECT * FROM seasons WHERE series_id = ? ORDER BY season_number",
            (series_id,)
        ).fetchall()
        d["seasons"] = []
        for s in seasons:
            sd = dict(s)
            eps = db.execute(
                "SELECT * FROM episodes WHERE season_id = ? ORDER BY ep_number",
                (s["id"],)
            ).fetchall()
            sd["episodes"] = [dict(e) for e in eps]
            d["seasons"].append(sd)
        urls = db.execute(
            "SELECT id, url, source, label, resolution, bandwidth, url_type, priority, is_active FROM urls WHERE target_type = 'series' AND target_id = ? ORDER BY priority",
            (series_id,)
        ).fetchall()
        d["urls"] = [dict(u) for u in urls]
        return d


@app.get("/api/seasons/{season_id:int}")
async def season_detail(season_id: int, request: Request = None):
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        row = db.execute("SELECT * FROM seasons WHERE id = ?", (season_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        series = db.execute("SELECT project_id FROM series WHERE id = ?", (row["series_id"],)).fetchone()
        if not series or series["project_id"] not in visible_projects:
            return JSONResponse({"error": "not found"}, status_code=404)
        d = dict(row)
        eps = db.execute(
            "SELECT * FROM episodes WHERE season_id = ? ORDER BY ep_number",
            (season_id,)
        ).fetchall()
        d["episodes"] = [dict(e) for e in eps]
        return d


@app.get("/api/episodes/{episode_id:int}")
async def episode_detail(episode_id: int, request: Request = None):
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        row = db.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        season = db.execute("SELECT series_id FROM seasons WHERE id = ?", (row["season_id"],)).fetchone()
        if not season:
            return JSONResponse({"error": "not found"}, status_code=404)
        series = db.execute("SELECT project_id FROM series WHERE id = ?", (season["series_id"],)).fetchone()
        if not series or series["project_id"] not in visible_projects:
            return JSONResponse({"error": "not found"}, status_code=404)
        d = dict(row)
        urls = db.execute(
            "SELECT id, url, source, label, resolution, bandwidth, url_type, priority, is_active FROM urls WHERE target_type = 'episode' AND target_id = ? ORDER BY priority",
            (episode_id,)
        ).fetchall()
        d["urls"] = [dict(u) for u in urls]
        season_row = db.execute("SELECT * FROM seasons WHERE id = ?", (d["season_id"],)).fetchone()
        if season_row:
            d["season"] = dict(season_row)
            series_row = db.execute("SELECT id, title, bangou FROM series WHERE id = ?", (season_row["series_id"],)).fetchone()
            if series_row:
                d["series"] = dict(series_row)
        return d


@app.get("/api/filters")
def get_filters(tags: str = "", site: str = "", request: Request = None):
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        results = {"tags": [], "sites": []}
        for tbl in ("videos", "series"):
            conditions = []
            params = []
            proj_clause, proj_params = _project_filter_clause(visible_projects)
            conditions.append(proj_clause)
            params.extend(proj_params)
            if site:
                site_conds = []
                for s in site.split(","):
                    s = s.strip()
                    if s:
                        site_conds.append("site = ?")
                        params.append(s)
                if site_conds:
                    conditions.append("(" + " OR ".join(site_conds) + ")")
            if tags:
                for t in tags.split(","):
                    t = t.strip()
                    if t:
                        conditions.append("tags LIKE ?")
                        params.append(f"%{t}%")
            wh = " WHERE " + " AND ".join(conditions)
            rows = db.execute(f"SELECT DISTINCT tags FROM {tbl}{wh} LIMIT 1000", params).fetchall()
            for (tags_str,) in rows:
                for t in (tags_str or "").split(","):
                    t = t.strip()
                    if t:
                        results["tags"].append(t)
            site_rows = db.execute(f"SELECT DISTINCT site FROM {tbl}{wh} LIMIT 1000", params).fetchall()
            for r in site_rows:
                if r[0]:
                    results["sites"].append(r[0])
        results["tags"] = sorted(set(results["tags"]))
        results["sites"] = sorted(set(results["sites"]))
        return results


@app.get("/api/videos/random")
async def random_video(limit: int = 1, request: Request = None):
    limit = min(limit, 100)
    visible_projects = _get_visible_projects_from_request(request)
    if not visible_projects:
        return {"error": "no videos"}
    with get_db() as db:
        proj_clause, proj_params = _project_filter_clause(visible_projects)
        total = db.execute(f"SELECT COUNT(*) FROM videos WHERE {proj_clause}", proj_params).fetchone()[0]
        if total == 0:
            return {"error": "no videos"}
        if limit <= 1:
            offset = secrets.randbelow(total)
            row = db.execute(f"SELECT * FROM videos WHERE {proj_clause} LIMIT 1 OFFSET ?", proj_params + [offset]).fetchone()
            return _row_to_dict(row) if row else {"error": "no videos"}
        offsets = sorted(secrets.randbelow(total) for _ in range(min(limit, total)))
        seen = set()
        out = []
        for off in offsets:
            if off in seen:
                continue
            seen.add(off)
            row = db.execute(f"SELECT * FROM videos WHERE {proj_clause} LIMIT 1 OFFSET ?", proj_params + [off]).fetchone()
            if row:
                out.append(_row_to_dict(row))
        return out


@app.get("/api/stats")
async def get_stats(request: Request = None):
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        proj_clause_v, proj_params_v = _project_filter_clause(visible_projects)
        video_total = db.execute(f"SELECT COUNT(*) FROM videos WHERE {proj_clause_v}", proj_params_v).fetchone()[0]
        proj_clause_s, proj_params_s = _project_filter_clause(visible_projects)
        series_total = db.execute(f"SELECT COUNT(*) FROM series WHERE {proj_clause_s}", proj_params_s).fetchone()[0]
        url_total = db.execute("SELECT COUNT(*) FROM urls").fetchone()[0]
        region_rows_v = db.execute(f"SELECT region, COUNT(*) as cnt FROM videos WHERE region != '' AND {proj_clause_v} GROUP BY region", proj_params_v).fetchall()
        region_rows_s = db.execute(f"SELECT region, COUNT(*) as cnt FROM series WHERE region != '' AND {proj_clause_s} GROUP BY region", proj_params_s).fetchall()
        regions = {}
        for r in region_rows_v:
            regions[r["region"]] = regions.get(r["region"], 0) + r["cnt"]
        for r in region_rows_s:
            regions[r["region"]] = regions.get(r["region"], 0) + r["cnt"]
        site_rows_v = db.execute(f"SELECT site, COUNT(*) as cnt FROM videos WHERE {proj_clause_v} GROUP BY site", proj_params_v).fetchall()
        site_rows_s = db.execute(f"SELECT site, COUNT(*) as cnt FROM series WHERE {proj_clause_s} GROUP BY site", proj_params_s).fetchall()
        sites = {}
        for r in site_rows_v:
            sites[r["site"] or "unknown"] = sites.get(r["site"] or "unknown", 0) + r["cnt"]
        for r in site_rows_s:
            sites[r["site"] or "unknown"] = sites.get(r["site"] or "unknown", 0) + r["cnt"]
        last_commit = ""
        for git_target in [LATEST_DIR, BASE_DIR, BASE_DIR.parent]:
            if (git_target / ".git").exists() or git_target == BASE_DIR:
                try:
                    r = subprocess.run(["git", "-C", str(git_target), "log", "-1", "--format=%ci"],
                                       capture_output=True, text=True, timeout=5)
                    if r.returncode == 0 and r.stdout.strip():
                        last_commit = r.stdout.strip()
                        break
                except Exception:
                    pass
        return {
            "app_version": config.APP_VERSION,
            "total_videos": video_total,
            "total_series": series_total,
            "total_urls": url_total,
            "regions": regions,
            "by_site": sites,
            "last_commit": last_commit,
        }


@app.get("/api/playlist")
async def export_playlist(q: str = "", region: str = "", group: str = "", request: Request = None):
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        lines = ["#EXTM3U"]
        for tbl in ("videos", "series"):
            conditions = []
            params = []
            proj_clause, proj_params = _project_filter_clause(visible_projects)
            conditions.append(proj_clause)
            params.extend(proj_params)
            if q:
                like = f"%{q}%"
                conditions.append("(title LIKE ? OR bangou LIKE ?)")
                params.extend([like, like])
            if region:
                conditions.append("region = ?")
                params.append(region)
            if group:
                conditions.append("group_name = ?")
                params.append(group)
            where = " WHERE " + " AND ".join(conditions)
            rows = db.execute(f"SELECT * FROM {tbl}{where} ORDER BY date DESC LIMIT 5000", params).fetchall()
            for r in rows:
                t = r["title"] or ""
                url = r["url"] or ""
                date = r["date"] or ""
                cover = r["cover"] or ""
                lines.append(f'#EXTINF:-1 tvg-logo="{cover}",{t} [{date}]')
                lines.append(url)
        return PlainTextResponse("\n".join(lines), media_type="text/plain")



# -- API: Categories (with project filtering) --

@app.get("/api/categories")
async def get_categories(request: Request = None):
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        proj_clause, proj_params = _project_filter_clause(visible_projects)
        rows = db.execute(
            f"SELECT * FROM categories WHERE {proj_clause} ORDER BY level, sort_order",
            proj_params
        ).fetchall()
        parents = {}
        children = {}
        for r in rows:
            d = dict(r)
            if d["level"] == 1:
                parents[d["id"]] = d
                d["children"] = []
            else:
                children.setdefault(d.get("parent_id"), []).append(d)
        for pid, chs in children.items():
            if pid in parents:
                parents[pid]["children"].extend(chs)
                parents[pid]["children"].sort(key=lambda x: x["sort_order"])
        result = sorted(parents.values(), key=lambda x: x["sort_order"])
        return {"categories": result}


@app.post("/api/categories")
async def create_category(data: dict = Body(...), user_payload=Depends(require_auth)):
    name = str(data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    parent_id = data.get("parent_id")
    level = 2 if parent_id else 1
    project_id = data.get("project_id", 1)
    with get_db() as db:
        if parent_id:
            max_row = db.execute(
                "SELECT MAX(sort_order) as mo FROM categories WHERE parent_id = ?",
                (parent_id,)
            ).fetchone()
        else:
            max_row = db.execute(
                "SELECT MAX(sort_order) as mo FROM categories WHERE level = 1"
            ).fetchone()
        sort_order = (max_row["mo"] or 0) + 1000
        cur = db.execute(
            "INSERT INTO categories (name, parent_id, level, sort_order, project_id) VALUES (?, ?, ?, ?, ?)",
            (name, parent_id, level, sort_order, project_id),
        )
        db.commit()
        return {"id": cur.lastrowid, "name": name, "parent_id": parent_id, "level": level, "sort_order": sort_order, "project_id": project_id}


@app.patch("/api/categories/{cat_id:int}")
async def update_category(cat_id: int, data: dict = Body(...), user_payload=Depends(require_auth)):
    name = data.get("name")
    with get_db() as db:
        row = db.execute("SELECT * FROM categories WHERE id = ?", (cat_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        if name is not None:
            db.execute("UPDATE categories SET name = ? WHERE id = ?", (str(name).strip(), cat_id))
        db.commit()
        return {"ok": True}


@app.delete("/api/categories/{cat_id:int}")
async def delete_category(cat_id: int, user_payload=Depends(require_auth)):
    with get_db() as db:
        child = db.execute("SELECT id FROM categories WHERE parent_id = ? LIMIT 1", (cat_id,)).fetchone()
        if child:
            return JSONResponse({"error": "请先删除子分类"}, status_code=400)
        db.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
        db.commit()
        return {"ok": True}


@app.patch("/api/categories/reorder")
async def reorder_categories(data: dict = Body(...), user_payload=Depends(require_auth)):
    orders = data.get("orders", [])
    if not orders:
        return JSONResponse({"error": "orders required"}, status_code=400)
    with get_db() as db:
        for o in orders:
            cat_id = o.get("id")
            so = o.get("sort_order")
            if cat_id is not None and so is not None:
                db.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (so, cat_id))
        db.commit()
        return {"ok": True}


@app.post("/api/categories/reorder/normalize")
async def normalize_category_order(user_payload=Depends(require_auth)):
    with get_db() as db:
        parents = db.execute("SELECT id FROM categories WHERE level = 1 ORDER BY sort_order").fetchall()
        for idx, p in enumerate(parents, start=1):
            db.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (idx * 1000, p["id"]))
            children = db.execute(
                "SELECT id FROM categories WHERE parent_id = ? ORDER BY sort_order",
                (p["id"],)
            ).fetchall()
            for cidx, c in enumerate(children, start=1):
                db.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (idx * 1000 + cidx, c["id"]))
        db.commit()
        return {"ok": True}


# -- API: Favorites (with project filtering) --

@app.get("/api/favorites")
async def get_favorites(request: Request = None, user_payload=Depends(require_auth)):
    visible_projects = _get_visible_projects_from_request(request)
    # P2-8: 收藏按当前登录用户隔离
    uid = user_payload.get("uid")
    with get_db() as db:
        proj_clause_v, proj_params_v = _project_filter_clause(visible_projects, "v")
        proj_clause_s, proj_params_s = _project_filter_clause(visible_projects, "s")
        rows = db.execute(
            f"""SELECT f.*,
                COALESCE(v.title, s.title) as title,
                COALESCE(v.cover, s.cover) as cover,
                COALESCE(v.bangou, s.bangou) as bangou
            FROM favorites f
            LEFT JOIN videos v ON f.target_type = 'video' AND f.target_id = v.id
            LEFT JOIN series s ON f.target_type = 'series' AND f.target_id = s.id
            WHERE f.user_id = ? AND ((f.target_type = 'video' AND {proj_clause_v}) OR (f.target_type = 'series' AND {proj_clause_s}))
            ORDER BY f.created_at DESC""",
            [uid] + proj_params_v + proj_params_s
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


@app.post("/api/favorites")
async def add_favorite(data: dict = Body(...), user_payload=Depends(require_auth)):
    target_type = data.get("target_type", "video")
    target_id = data.get("target_id")
    if not target_id:
        return JSONResponse({"error": "target_id required"}, status_code=400)
    with get_db() as db:
        # Validate target exists and determine project_id
        if target_type == "video":
            target_row = db.execute("SELECT project_id FROM videos WHERE id = ?", (target_id,)).fetchone()
        else:
            target_row = db.execute("SELECT project_id FROM series WHERE id = ?", (target_id,)).fetchone()
        if not target_row:
            return JSONResponse({"error": "target not found"}, status_code=404)
        project_id = target_row["project_id"]
        # P2-8: 唯一键含 user_id，INSERT OR REPLACE 不再跨账号互踩
        db.execute(
            "INSERT OR REPLACE INTO favorites (target_type, target_id, created_at, project_id, user_id) VALUES (?, ?, ?, ?, ?)",
            (target_type, target_id, datetime.now().isoformat(), project_id, user_payload.get("uid")),
        )
        db.commit()
        return {"ok": True}


@app.delete("/api/favorites/{fav_id:int}")
async def remove_favorite(fav_id: int, user_payload=Depends(require_auth)):
    with get_db() as db:
        # P2-8: 只能删除自己账号的收藏
        db.execute("DELETE FROM favorites WHERE id = ? AND user_id = ?", (fav_id, user_payload.get("uid")))
        db.commit()
        return {"ok": True}


# -- API: History (with project filtering) --

@app.get("/api/history")
async def get_history(request: Request = None, user_payload=Depends(require_auth)):
    visible_projects = _get_visible_projects_from_request(request)
    # P2-8: 观看历史按当前登录用户隔离
    uid = user_payload.get("uid")
    with get_db() as db:
        proj_clause_v, proj_params_v = _project_filter_clause(visible_projects, "v")
        proj_clause_s, proj_params_s = _project_filter_clause(visible_projects, "s")
        proj_clause_e, proj_params_e = _project_filter_clause(visible_projects, "e")
        # Episodes project check goes through seasons->series, use history.project_id for simplicity
        rows = db.execute(
            f"""SELECT h.*,
                COALESCE(v.title, s.title, ep.ep_title) as title,
                COALESCE(v.cover, s.cover) as cover,
                COALESCE(v.bangou, s.bangou) as bangou
            FROM history h
            LEFT JOIN videos v ON h.target_type = 'video' AND h.target_id = v.id
            LEFT JOIN series s ON h.target_type = 'series' AND h.target_id = s.id
            LEFT JOIN episodes ep ON h.target_type = 'episode' AND h.target_id = ep.id
            WHERE h.user_id = ? AND ((h.target_type = 'video' AND {proj_clause_v})
               OR (h.target_type = 'series' AND {proj_clause_s})
               OR (h.target_type = 'episode'))
            ORDER BY h.watched_at DESC LIMIT 200""",
            [uid] + proj_params_v + proj_params_s
        ).fetchall()
        # Post-filter episode entries by checking their series project
        result = []
        for r in rows:
            d = dict(r)
            if d.get("target_type") == "episode" and d.get("target_id"):
                ep_check = db.execute(
                    """SELECT se.series_id FROM episodes e
                       JOIN seasons se ON e.season_id = se.id
                       WHERE e.id = ?""", (d["target_id"],)
                ).fetchone()
                if ep_check:
                    series_proj = db.execute("SELECT project_id FROM series WHERE id = ?", (ep_check["series_id"],)).fetchone()
                    if not series_proj or series_proj["project_id"] not in visible_projects:
                        continue
            result.append(_row_to_dict(r))
        return result


@app.post("/api/history")
async def add_history(data: dict = Body(...), user_payload=Depends(require_auth)):
    target_type = data.get("target_type", "video")
    target_id = data.get("target_id")
    progress = data.get("progress", 0)
    if not target_id:
        return JSONResponse({"error": "target_id required"}, status_code=400)
    with get_db() as db:
        # Determine project_id
        project_id = 1
        if target_type == "video":
            row = db.execute("SELECT project_id FROM videos WHERE id = ?", (target_id,)).fetchone()
        elif target_type == "series":
            row = db.execute("SELECT project_id FROM series WHERE id = ?", (target_id,)).fetchone()
        else:
            row = None
        if row:
            project_id = row["project_id"]
        db.execute(
            "DELETE FROM history WHERE target_type = ? AND target_id = ? AND user_id = ?",
            (target_type, target_id, user_payload.get("uid")),
        )
        db.execute(
            "INSERT INTO history (target_type, target_id, progress, watched_at, project_id, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            (target_type, target_id, progress, datetime.now().isoformat(), project_id, user_payload.get("uid")),
        )
        db.commit()
        return {"ok": True}


@app.delete("/api/history/{item_id:int}")
async def delete_history_item(item_id: int, user_payload=Depends(require_auth)):
    with get_db() as db:
        # P2-8: 只能删除自己账号的历史
        db.execute("DELETE FROM history WHERE id = ? AND user_id = ?", (item_id, user_payload.get("uid")))
        db.commit()
        return {"ok": True}


@app.post("/api/history/batch-delete")
async def batch_delete_history(data: dict = Body(...), user_payload=Depends(require_auth)):
    ids = data.get("ids", [])
    if not ids:
        return {"ok": False, "error": "no ids"}
    if not all(isinstance(i, int) for i in ids):
        return JSONResponse({"ok": False, "error": "invalid id type"}, status_code=400)
    with get_db() as db:
        placeholders = ",".join("?" for _ in ids)
        db.execute(
            f"DELETE FROM history WHERE id IN ({placeholders}) AND user_id = ?",
            ids + [user_payload.get("uid")],
        )
        db.commit()
        return {"ok": True}


# -- API: Import (multi-volume + multi-project) --

def _resolve_project_for_json(db, project_info: dict | None, base_name: str) -> int:
    slug = (project_info.get("slug") if project_info else None) or base_name
    name = (project_info.get("name") if project_info else None) or base_name
    existing = db.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
    if existing:
        return existing["id"]
    cursor = db.execute(
        "INSERT INTO projects (name, slug, sort_order) VALUES (?, ?, ?)",
        (name, slug, 0)
    )
    return cursor.lastrowid


def _scan_json_files(dir_path: str):
    p = Path(dir_path)
    if not p.exists() or not p.is_dir():
        return []
    files = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() == ".json"]
    return sorted(files, key=lambda f: f.name)


def _group_volumes(files: list[Path]) -> dict[str, list[tuple[int, Path]]]:
    """Group files by base name, detecting volumes like xxx-1.json, xxx-2.json."""
    pattern = re.compile(r'^(.*)-(\d+)\.json$', re.IGNORECASE)
    groups: dict[str, list[tuple[int, Path]]] = {}
    singles: list[Path] = []
    for f in files:
        m = pattern.match(f.name)
        if m:
            base = m.group(1)
            vol = int(m.group(2))
            groups.setdefault(base, []).append((vol, f))
        else:
            singles.append(f)
    for base in groups:
        groups[base].sort(key=lambda x: x[0])
    for f in singles:
        base = f.stem
        groups.setdefault(base, []).append((0, f))
    return groups


def _merge_json_volumes(files: list[tuple[int, Path]]) -> tuple[dict, str]:
    """Merge volume files. Returns (merged_data, base_name)."""
    if not files:
        return {}, ""
    # Sort by volume number (0 = no volume)
    files.sort(key=lambda x: x[0])
    base_name = files[0][1].stem
    if files[0][0] != 0:
        # Has volume numbers
        m = re.match(r'^(.*)-\d+$', base_name, re.IGNORECASE)
        if m:
            base_name = m.group(1)

    all_items = []
    project_info = None
    schema_version = None
    meta_source = None
    meta_generator = None
    meta_generated_at = None

    for vol, fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            continue
        sv = data.get("schema_version", "")
        if schema_version is None:
            schema_version = sv
        elif sv and sv != schema_version:
            raise ValueError(f"schema_version mismatch in {fpath.name}: {sv} vs {schema_version}")
        # project field from JSON
        proj = data.get("project")
        if proj and isinstance(proj, dict):
            if project_info is None:
                project_info = proj
            elif proj != project_info:
                raise ValueError(f"project field mismatch in {fpath.name}")
        if meta_source is None:
            meta_source = data.get("source")
        if meta_generator is None:
            meta_generator = data.get("generator")
        if meta_generated_at is None:
            meta_generated_at = data.get("generated_at")
        items = data.get("items")
        if items and isinstance(items, list):
            all_items.extend(items)

    merged = {
        "schema_version": schema_version or "2.1",
        "items": all_items,
    }
    if project_info:
        merged["project"] = project_info
    if meta_source:
        merged["source"] = meta_source
    if meta_generator:
        merged["generator"] = meta_generator
    if meta_generated_at:
        merged["generated_at"] = meta_generated_at
    return merged, base_name


class BangouConflictError(Exception):
    """Raised when an import would violate the global unique bangou
    constraint because the item already exists in another project."""

    def __init__(self, bangou: str, owner_project_id: int, owner_project_name: str, item_type: str):
        super().__init__(bangou)
        self.bangou = bangou
        self.owner_project_id = owner_project_id
        self.owner_project_name = owner_project_name
        self.item_type = item_type

    def __str__(self):
        return f"番号 {self.bangou} 已存在于项目「{self.owner_project_name}」"


def _raise_bangou_conflict(db, bangou: str, owner_project_id: int, item_type: str):
    """Raise BangouConflictError for a bangou already owned by another project."""
    row = db.execute(
        "SELECT name FROM projects WHERE id = ?", (owner_project_id,)
    ).fetchone()
    owner_name = row["name"] if row else str(owner_project_id)
    raise BangouConflictError(bangou, owner_project_id, owner_name, item_type)


def _rebuild_auto_categories(db, project_id: int) -> None:
    """按项目内数据的 region/group_name 全量重建两级分类树。

    产物侧负责分类语义（region=一级，group_name=二级），导入后分类 tab
    自动就位；项目内旧分类整树重建，排序按各级条目数量降序。
    """
    counts: dict = {}
    for (region, group) in db.execute(
        "SELECT region, group_name FROM videos WHERE project_id = ?", (project_id,)
    ):
        key = ((region or "").strip() or "通用", (group or "").strip() or "默认")
        counts[key] = counts.get(key, 0) + 1
    for (region, group) in db.execute(
        "SELECT region, group_name FROM series WHERE project_id = ?", (project_id,)
    ):
        key = ((region or "").strip() or "通用", (group or "").strip() or "默认")
        counts[key] = counts.get(key, 0) + 1

    # 快照既有排序：重建后同名分类沿用用户整理过的顺序，新增分类追加在后
    rows = db.execute(
        "SELECT id, name, parent_id, level, sort_order FROM categories WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    id2name = {r["id"]: r["name"] for r in rows}
    l1_order = {r["name"]: r["sort_order"] for r in rows if r["level"] == 1}
    l2_order = {(id2name.get(r["parent_id"]), r["name"]): r["sort_order"]
                for r in rows if r["level"] == 2}

    db.execute("DELETE FROM categories WHERE project_id = ?", (project_id,))
    if not counts:
        return

    next_order = (max([*l1_order.values(), *l2_order.values()]) + 1) if (l1_order or l2_order) else 1

    regions = sorted(
        {r for r, _ in counts},
        key=lambda r: (-sum(c for (rr, _g), c in counts.items() if rr == r), r),
    )
    for region in regions:
        order = l1_order.get(region)
        if order is None:
            order = next_order
            next_order += 1
        cur = db.execute(
            "INSERT INTO categories (name, parent_id, level, sort_order, is_user_defined, project_id)"
            " VALUES (?, NULL, 1, ?, 0, ?)",
            (region, order, project_id),
        )
        parent_id = cur.lastrowid
        for group in sorted(
            {g for (r, g) in counts if r == region},
            key=lambda g: -counts[(region, g)],
        ):
            o2 = l2_order.get((region, group))
            if o2 is None:
                o2 = next_order
                next_order += 1
            db.execute(
                "INSERT INTO categories (name, parent_id, level, sort_order, is_user_defined, project_id)"
                " VALUES (?, ?, 2, ?, 0, ?)",
                (group, parent_id, o2, project_id),
            )


def _normalize_episode_url(url: str) -> str:
    """归一化集数播放地址：同一资源站常见 /index.m3u8 与裸路径两种写法指向
    同一视频，剥掉后缀/末尾斜杠后用于识别重复集数（主机名保留，跨站不合并）。"""
    u = (url or "").strip()
    if not u:
        return ""
    u = re.sub(r"/index\.m3u8$", "", u, flags=re.I)
    u = u.rstrip("/")
    return u.lower()


def _dedupe_season_episodes(season_eps: list) -> list:
    """合并多线路拍平产生的重复集数记录。

    部分聚合器导出时把「线路 × 集数」拍平成逐条记录（同一集的不同线路
    各占一条、ep_number 顺序编号），导致前端出现大量重复的第1集/第2集。
    这里按归一化 URL 聚合：每组保留一条主记录（优先 .m3u8 直链形式），
    其余形式与各记录的 alt_urls/qualities 合并进 alt_urls（按归一化地址
    去重），ep_number 按首次出现顺序重排为 1..N。
    """
    if not isinstance(season_eps, list) or not season_eps:
        return season_eps
    eps = [e for e in season_eps if isinstance(e, dict) and str(e.get("url") or "").strip()]
    if not eps:
        return eps

    groups: dict = {}
    order: list = []
    for ep in eps:
        url = str(ep.get("url") or "").strip()
        key = _normalize_episode_url(url) or "raw:" + url
        is_m3u8 = url.lower().endswith(".m3u8") or str(ep.get("url_type") or "").lower() == "m3u8"
        g = groups.get(key)
        if g is None:
            groups[key] = {"best": ep, "best_m3u8": is_m3u8, "alts": {}}
            order.append(key)
            g = groups[key]
        elif is_m3u8 and not g["best_m3u8"]:
            # 主记录换成 .m3u8 直链形式，原主记录降级为一条线路
            old = g["best"]
            old_url = str(old.get("url") or "").strip()
            old_key = _normalize_episode_url(old_url)
            if old_url and old_key != key:
                g["alts"].setdefault(old_key, old)
            g["best"] = ep
            g["best_m3u8"] = True
        # 该记录自带的 alt_urls 全部并入候选（按归一化地址去重）
        for alt in list(ep.get("alt_urls") or []):
            if not isinstance(alt, dict):
                continue
            aurl = str(alt.get("url") or "").strip()
            akey = _normalize_episode_url(aurl)
            if not aurl or akey == key:
                continue
            if akey not in g["alts"]:
                g["alts"][akey] = alt
        for q in ep.get("qualities") or []:
            if isinstance(q, dict) and str(q.get("url") or "").strip():
                g["alts"].setdefault("q:" + str(q.get("url")), q)

    merged = []
    for idx, key in enumerate(order, start=1):
        g = groups[key]
        ep = dict(g["best"])
        ep["ep_number"] = idx
        alts = [dict(a) for a in g["alts"].values()]
        if alts:
            ep["alt_urls"] = alts
        merged.append(ep)
    return merged


def _import_items_to_project(db, items: list[dict], project_id: int) -> dict:
    """Import items into a specific project. Returns stats."""
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    now_iso = datetime.now().isoformat()
    new_videos = 0
    new_series = 0
    updated_videos = 0
    updated_series = 0
    logs = []

    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            logs.append("skip: missing title")
            continue
        item_type = str(item.get("type") or "").strip()
        has_seasons = bool(item.get("seasons"))
        has_episodes = bool(item.get("episodes"))

        if item_type == "series" or has_seasons or has_episodes:
            if not has_seasons and not has_episodes:
                logs.append(f"skip: series {title} missing seasons/episodes")
                continue
            bangou = _ensure_bangou(item)
            existing = db.execute(
                "SELECT id, first_imported_at, import_batch_id, project_id FROM series WHERE bangou = ?",
                (bangou,)
            ).fetchone()
            if existing and existing["project_id"] != project_id:
                # Global unique bangou: the item is owned by another project.
                # Raise a controlled conflict instead of hitting the UNIQUE
                # constraint with an IntegrityError further down.
                _raise_bangou_conflict(db, bangou, existing["project_id"], "series")

            series_values = (
                title,
                str(item.get("original_title") or "").strip() or None,
                str(item.get("cover") or "").strip() or None,
                str(item.get("region") or "").strip() or "通用",
                str(item.get("group_name") or "").strip() or "默认",
                str(item.get("date") or "").strip() or None,
                str(item.get("site") or "").strip() or None,
                ",".join(dict.fromkeys(_parse_tags(item.get("tags")) + [str(g).strip() for g in (item.get("genres") or []) if str(g).strip()])),
                str(item.get("overview") or "").strip() or None,
                str(item.get("backdrop") or "").strip() or None,
                item.get("rating") if isinstance(item.get("rating"), (int, float)) else None,
                str(item.get("rating_source") or "").strip() or None,
                item.get("vote_count") if isinstance(item.get("vote_count"), int) else None,
                str(item.get("year") or "").strip() or None,
                str(item.get("first_air_date") or "").strip() or None,
                item.get("runtime") if isinstance(item.get("runtime"), int) else None,
                str(item.get("status") or "").strip() or None,
                str(item.get("original_language") or "").strip() or None,
                str(item.get("homepage") or "").strip() or None,
                str(item.get("certification") or "").strip() or None,
                str(item.get("country") or "").strip() or None,
                str(item.get("studio") or "").strip() or None,
                str(item.get("logo") or "").strip() or None,
                item.get("popularity") if isinstance(item.get("popularity"), (int, float)) else None,
                item.get("view_count") if isinstance(item.get("view_count"), int) else None,
                item.get("trending_rank") if isinstance(item.get("trending_rank"), int) else None,
                item.get("number_of_seasons") if isinstance(item.get("number_of_seasons"), int) else None,
                item.get("number_of_episodes") if isinstance(item.get("number_of_episodes"), int) else None,
                json.dumps(_parse_tags(item.get("cast")), ensure_ascii=False) if item.get("cast") else None,
                json.dumps(_parse_tags(item.get("director")), ensure_ascii=False) if item.get("director") else None,
                json.dumps(item.get("cast_structured"), ensure_ascii=False) if item.get("cast_structured") else None,
                json.dumps(item.get("director_structured"), ensure_ascii=False) if item.get("director_structured") else None,
            )

            if existing:
                series_id = existing["id"]
                db.execute(
                    """UPDATE series SET
                    title = ?, original_title = ?, cover = ?, region = ?, group_name = ?,
                    date = ?, site = ?, tags = ?, overview = ?, backdrop = ?, rating = ?,
                    rating_source = ?, vote_count = ?, year = ?, first_air_date = ?,
                    runtime = ?, status = ?, original_language = ?, homepage = ?,
                    certification = ?, country = ?, studio = ?, logo = ?, popularity = ?,
                    view_count = ?, trending_rank = ?, number_of_seasons = ?,
                    number_of_episodes = ?, cast = ?, director = ?, cast_structured = ?,
                    director_structured = ?, project_id = ?
                    WHERE id = ?""",
                    series_values + (project_id, series_id),
                )
                db.execute("DELETE FROM episodes WHERE season_id IN (SELECT id FROM seasons WHERE series_id = ?)", (series_id,))
                db.execute("DELETE FROM seasons WHERE series_id = ?", (series_id,))
                db.execute("DELETE FROM urls WHERE target_type = 'series' AND target_id = ?", (series_id,))
                updated_series += 1
            else:
                cursor = db.execute(
                    """INSERT INTO series
                    (title, original_title, cover, region, group_name, date, site, tags,
                     overview, backdrop, rating, rating_source, vote_count, year, first_air_date,
                     runtime, status, original_language, homepage, certification, country, studio,
                     logo, popularity, view_count, trending_rank, number_of_seasons, number_of_episodes,
                     cast, director, cast_structured, director_structured,
                     bangou, first_imported_at, import_batch_id, project_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    series_values + (bangou, now_iso, batch_id, project_id),
                )
                series_id = cursor.lastrowid
                new_series += 1

            _insert_urls(db, series_id, "series", item, project_id)

            seasons = item.get("seasons") or []
            if not seasons and has_episodes:
                seasons = [{"season_number": 1, "episodes": item.get("episodes", [])}]

            for season in seasons:
                if not isinstance(season, dict):
                    continue
                season_number = season.get("season_number")
                if not isinstance(season_number, int):
                    continue
                season_eps = _dedupe_season_episodes(season.get("episodes") or [])
                if not season_eps:
                    continue
                cur_s = db.execute(
                    """INSERT INTO seasons
                    (series_id, season_number, season_title, season_cover, season_overview, season_date, episode_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        series_id, season_number,
                        str(season.get("season_title") or "").strip() or f"第 {season_number} 季",
                        str(season.get("season_cover") or "").strip() or None,
                        str(season.get("season_overview") or "").strip() or None,
                        str(season.get("season_date") or "").strip() or None,
                        len(season_eps) if isinstance(season_eps, list) else None,
                    ),
                )
                season_id = cur_s.lastrowid
                for ep in season_eps:
                    if not isinstance(ep, dict):
                        continue
                    ep_url = str(ep.get("url") or "").strip()
                    if not ep_url:
                        continue
                    ep_id = str(ep.get("ep_id") or "").strip()
                    if not ep_id:
                        ep_id = f"{bangou}_{season_number}_{ep.get('ep_number', 0)}"
                    cur_e = db.execute(
                        """INSERT INTO episodes
                        (season_id, ep_id, ep_number, ep_title, air_date, duration, ep_overview,
                         ep_rating, ep_rating_source, ep_still)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            season_id, ep_id,
                            ep.get("ep_number") if isinstance(ep.get("ep_number"), int) else None,
                            str(ep.get("ep_title") or "").strip() or None,
                            str(ep.get("air_date") or "").strip() or None,
                            ep.get("duration") if isinstance(ep.get("duration"), int) else None,
                            str(ep.get("ep_overview") or "").strip() or None,
                            ep.get("ep_rating") if isinstance(ep.get("ep_rating"), (int, float)) else None,
                            str(ep.get("ep_rating_source") or "").strip() or None,
                            str(ep.get("ep_still") or "").strip() or None,
                        ),
                    )
                    episode_id = cur_e.lastrowid
                    _insert_urls(db, episode_id, "episode", ep, project_id)
        else:
            # Single video
            bangou = _ensure_bangou(item)
            existing = db.execute(
                "SELECT id, first_imported_at, import_batch_id, project_id FROM videos WHERE bangou = ?",
                (bangou,)
            ).fetchone()
            if existing and existing["project_id"] != project_id:
                # Global unique bangou: the item is owned by another project.
                # Raise a controlled conflict instead of hitting the UNIQUE
                # constraint with an IntegrityError further down.
                _raise_bangou_conflict(db, bangou, existing["project_id"], "video")

            video_values = (
                title,
                str(item.get("cover") or "").strip() or None,
                str(item.get("region") or "").strip() or "通用",
                str(item.get("group_name") or "").strip() or "默认",
                str(item.get("date") or "").strip() or None,
                str(item.get("site") or "").strip() or None,
                ",".join(dict.fromkeys(_parse_tags(item.get("tags")) + [str(g).strip() for g in (item.get("genres") or []) if str(g).strip()])),
                str(item.get("overview") or "").strip() or None,
                str(item.get("original_title") or "").strip() or None,
                str(item.get("backdrop") or "").strip() or None,
                item.get("rating") if isinstance(item.get("rating"), (int, float)) else None,
                str(item.get("rating_source") or "").strip() or None,
                item.get("vote_count") if isinstance(item.get("vote_count"), int) else None,
                str(item.get("year") or "").strip() or None,
                str(item.get("first_air_date") or "").strip() or None,
                item.get("runtime") if isinstance(item.get("runtime"), int) else None,
                str(item.get("status") or "").strip() or None,
                str(item.get("original_language") or "").strip() or None,
                str(item.get("homepage") or "").strip() or None,
                str(item.get("certification") or "").strip() or None,
                str(item.get("country") or "").strip() or None,
                str(item.get("studio") or "").strip() or None,
                str(item.get("logo") or "").strip() or None,
                item.get("popularity") if isinstance(item.get("popularity"), (int, float)) else None,
                item.get("view_count") if isinstance(item.get("view_count"), int) else None,
                item.get("trending_rank") if isinstance(item.get("trending_rank"), int) else None,
                json.dumps(_parse_tags(item.get("cast")), ensure_ascii=False) if item.get("cast") else None,
                json.dumps(_parse_tags(item.get("director")), ensure_ascii=False) if item.get("director") else None,
                json.dumps(item.get("cast_structured"), ensure_ascii=False) if item.get("cast_structured") else None,
                json.dumps(item.get("director_structured"), ensure_ascii=False) if item.get("director_structured") else None,
            )

            if existing:
                video_id = existing["id"]
                db.execute(
                    """UPDATE videos SET
                    title = ?, cover = ?, region = ?, group_name = ?, date = ?, site = ?, tags = ?,
                    overview = ?, original_title = ?, backdrop = ?, rating = ?, rating_source = ?,
                    vote_count = ?, year = ?, first_air_date = ?, runtime = ?, status = ?,
                    original_language = ?, homepage = ?, certification = ?, country = ?, studio = ?,
                    logo = ?, popularity = ?, view_count = ?, trending_rank = ?, cast = ?, director = ?,
                    cast_structured = ?, director_structured = ?, project_id = ?
                    WHERE id = ?""",
                    video_values + (project_id, video_id),
                )
                db.execute("DELETE FROM urls WHERE target_type = 'video' AND target_id = ?", (video_id,))
                updated_videos += 1
            else:
                cursor = db.execute(
                    """INSERT INTO videos
                    (title, cover, region, group_name, date, site, tags, overview, original_title,
                     backdrop, rating, rating_source, vote_count, year, first_air_date, runtime,
                     status, original_language, homepage, certification, country, studio, logo,
                     popularity, view_count, trending_rank, cast, director, cast_structured,
                     director_structured, bangou, first_imported_at, import_batch_id, project_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    video_values + (bangou, now_iso, batch_id, project_id),
                )
                video_id = cursor.lastrowid
                new_videos += 1

            _insert_urls(db, video_id, "video", item, project_id)

    # Re-apply manual organize results on top of the fresh JSON data so
    # merge/dedup/transfer/override edits survive re-import (this runs for
    # manual full-replace imports, incremental scans and scheduled
    # auto-update alike).
    _apply_organize_rules(db, project_id)

    # 分类树跟随数据：按导入结果的 region/group_name 重建自动分类，
    # 用户手建（is_user_defined=1）的分类原样保留
    _rebuild_auto_categories(db, project_id)

    return {
        "batch_id": batch_id,
        "new_videos": new_videos,
        "new_series": new_series,
        "updated_videos": updated_videos,
        "updated_series": updated_series,
        "logs": logs,
    }


def import_directory_unified(dir_path: str = "", explicit_project_id: int = None, incremental: bool = False) -> list[dict]:
    """Scan directory, auto-detect JSON type per file (video/live) and import.

    Video JSONs: volume grouping (xxx-1/xxx-2) + project field priority,
    then full-replace import (manual behavior) or
    incremental import (auto-update mode, design 3.3.3).
    Live JSONs: full replace per source_region (design 2.3.1).
    """
    if not dir_path:
        dir_path = DATA_DIR / "json"
    files = _scan_json_files(dir_path)
    if not files:
        # Fallback to single-file discovery
        vf = get_videos_file()
        if vf and vf.exists():
            files = [vf]
        else:
            return [{"error": "no json files found"}]

    video_files: list[Path] = []
    live_entries: list[tuple[Path, dict]] = []
    results: list[dict] = []

    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            results.append({"base": f.stem, "error": f"JSON 解析失败: {e}"})
            continue
        json_type = detect_json_type(data)
        if json_type == "video":
            video_files.append(f)
        elif json_type == "live":
            live_entries.append((f, data))
        else:
            results.append({"base": f.stem, "error": "无法识别的 JSON 格式"})

    groups = _group_volumes(video_files)
    with get_db() as db:
        for base_name, file_list in groups.items():
            try:
                merged, derived_base = _merge_json_volumes(file_list)
            except ValueError as e:
                results.append({"base": base_name, "type": "video", "error": str(e)})
                continue
            items = merged.get("items", [])
            if not items:
                results.append({"base": base_name, "type": "video", "error": "no items"})
                continue

            project_info = merged.get("project")
            if explicit_project_id:
                project_id = explicit_project_id
            else:
                project_id = _resolve_project_for_json(db, project_info, derived_base)

            ref_snapshot = []
            if not incremental:
                # Manual import: full replace per project. User refs
                # (favorites/history) are snapshotted by stable identity and
                # re-linked after import instead of being wiped, so a manual
                # re-import never loses them.
                ref_snapshot = _snapshot_user_refs(db, project_id)
                db.execute("DELETE FROM videos WHERE project_id = ?", (project_id,))
                db.execute("DELETE FROM series WHERE project_id = ?", (project_id,))
                db.execute("""DELETE FROM episodes WHERE season_id IN (
                    SELECT s.id FROM seasons s JOIN series se ON s.series_id = se.id WHERE se.project_id = ?
                )""", (project_id,))
                db.execute("""DELETE FROM seasons WHERE series_id IN (
                    SELECT id FROM series WHERE project_id = ?
                )""", (project_id,))
                db.execute("DELETE FROM urls WHERE project_id = ?", (project_id,))
                db.execute("DELETE FROM categories WHERE project_id = ?", (project_id,))
                db.execute("DELETE FROM suspense WHERE project_id = ?", (project_id,))

            # Incremental mode: no pre-clear; _import_items_to_project upserts
            # by (bangou, project_id) and preserves first_imported_at on update,
            # so only genuinely new items enter recent updates.
            stats = _import_items_to_project(db, items, project_id)
            if ref_snapshot:
                _remap_user_refs(db, project_id, ref_snapshot)
            db.commit()
            results.append({
                "base": base_name,
                "type": "video",
                "project_id": project_id,
                **stats,
            })

    # Live imports run after the video db handle is closed (separate tx)
    for f, data in live_entries:
        results.append(import_live_json(data, f.stem))

    return results


def import_videos_from_directory(dir_path: str = "", explicit_project_id: int = None) -> list[dict]:
    """Backward-compatible wrapper: manual directory import (full replace)."""
    results = import_directory_unified(dir_path, explicit_project_id, incremental=False)
    # Callers expect video-only results semantics; live entries are extra
    # keys-carrying dicts which are safe to return as-is.
    return results


def import_video_file_full(path: str, explicit_project_id: int = None) -> dict:
    """Import a single video JSON file with full-replace semantics."""
    p = Path(path)
    with get_db() as db:
        merged, base_name = _merge_json_volumes([(0, p)])
        project_info = merged.get("project")
        if explicit_project_id:
            project_id = explicit_project_id
        else:
            project_id = _resolve_project_for_json(db, project_info, base_name)
        items = merged.get("items", [])
        if not items:
            return {"base": base_name, "type": "video", "error": "no items"}
        ref_snapshot = _snapshot_user_refs(db, project_id)
        db.execute("DELETE FROM videos WHERE project_id = ?", (project_id,))
        # 删除顺序必须先 episodes/seasons 再 series：子查询靠 series 反查，
        # 先删 series 会让 episodes/seasons 的删除匹配不到任何行（孤儿累积）
        db.execute("""DELETE FROM episodes WHERE season_id IN (
            SELECT s.id FROM seasons s JOIN series se ON s.series_id = se.id WHERE se.project_id = ?
        )""", (project_id,))
        db.execute("""DELETE FROM seasons WHERE series_id IN (
            SELECT id FROM series WHERE project_id = ?
        )""", (project_id,))
        db.execute("DELETE FROM series WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM urls WHERE project_id = ?", (project_id,))
        stats = _import_items_to_project(db, items, project_id)
        _remap_user_refs(db, project_id, ref_snapshot)
        db.commit()
        return {"base": base_name, "type": "video", "project_id": project_id, **stats}


def import_single_file_unified(path: str, explicit_project_id: int = None, incremental: bool = False) -> dict:
    """Import a single JSON file, auto-detecting video vs live."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return {"base": p.stem, "error": "文件不存在"}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        return {"base": p.stem, "error": f"JSON 解析失败: {e}"}

    json_type = detect_json_type(data)
    if json_type == "live":
        return import_live_json(data, p.stem)
    if json_type == "video":
        if incremental:
            with get_db() as db:
                merged, base_name = _merge_json_volumes([(0, p)])
                project_info = merged.get("project")
                if explicit_project_id:
                    project_id = explicit_project_id
                else:
                    project_id = _resolve_project_for_json(db, project_info, base_name)
                items = merged.get("items", [])
                if not items:
                    return {"base": base_name, "type": "video", "error": "no items"}
                stats = _import_items_to_project(db, items, project_id)
                db.commit()
                return {"base": base_name, "type": "video", "project_id": project_id, **stats}
        return import_video_file_full(path, explicit_project_id)
    return {"base": p.stem, "error": "无法识别的 JSON 格式"}


def import_videos_to_db(preferred_path: str = "") -> dict | None:
    """Backward-compatible single-file import (video JSON assumed)."""
    if preferred_path:
        p = Path(preferred_path)
        if p.exists() and p.is_file():
            result = import_video_file_full(str(p))
            if "error" not in result:
                return result
            return None
    # Try directory import
    results = import_videos_from_directory()
    if results:
        return results[0]
    return None


# -- Live JSON recognition & import --

def detect_json_type(data) -> str:
    """Return 'video' | 'live' | 'unknown' (design 2.2.1).

    Video: an items list is enough — older JSON formats (2.0 and earlier)
    carry no schema_version and must still import (low-version
    compatibility). Live: channels (non-empty list) whose entries have
    name + (url | urls); fallback auxiliary feature: generator (str) +
    region present.
    The url-or-urls extension covers the multi-source live format
    (urls array) which the single-source rule in design v1.0 misses.
    """
    if not isinstance(data, dict):
        return "unknown"
    if isinstance(data.get("items"), list):
        return "video"
    channels = data.get("channels")
    if isinstance(channels, list) and len(channels) > 0:
        first = channels[0]
        if isinstance(first, dict) and "name" in first and ("url" in first or "urls" in first):
            return "live"
    if isinstance(data.get("generator"), str) and "region" in data:
        return "live"
    return "unknown"


def _num_or_none(val):
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    return None


def _str_or_none(val):
    s = str(val or "").strip()
    return s or None


def _normalize_live_sources(channel: dict) -> list[dict]:
    """Normalize a channel dict to a list of source dicts.

    Single-source format: channel-level url (string).
    Multi-source format: channel-level urls (array of
    {url, speed_mbps, delay_ms, node_ip, isp}).
    Returns de-duplicated list preserving original order.
    """
    sources: list[dict] = []
    if isinstance(channel.get("urls"), list):
        for s in channel["urls"]:
            if not isinstance(s, dict):
                continue
            url = str(s.get("url") or "").strip()
            if not url:
                continue
            sources.append({
                "url": url,
                "speed_mbps": _num_or_none(s.get("speed_mbps")),
                "delay_ms": _num_or_none(s.get("delay_ms")),
                "node_ip": _str_or_none(s.get("node_ip")),
                "isp": _str_or_none(s.get("isp")),
            })
    else:
        url = str(channel.get("url") or "").strip()
        if url:
            sources.append({
                "url": url,
                "speed_mbps": _num_or_none(channel.get("speed_mbps")),
                "delay_ms": _num_or_none(channel.get("delay_ms")),
                "node_ip": _str_or_none(channel.get("node_ip")),
                "isp": _str_or_none(channel.get("isp")),
            })
    seen: set[str] = set()
    out: list[dict] = []
    for s in sources:
        if s["url"] in seen:
            continue
        seen.add(s["url"])
        out.append(s)
    return out


def _rank_live_source_key(item):
    """Sort key over (position, source): higher speed first, then lower
    delay, then original position. Sources without speed rank after those
    with speed; sources without delay rank after those with delay."""
    pos, s = item
    speed = s.get("speed_mbps")
    delay = s.get("delay_ms")
    return (
        0 if speed is not None else 1,
        -speed if speed is not None else 0.0,
        0 if delay is not None else 1,
        delay if delay is not None else 0.0,
        pos,
    )


def _pick_default_source(sources: list[dict]) -> int:
    """Return the position of the default (best) source.

    Strategy: speed_mbps DESC primary, delay_ms ASC secondary, original
    position ASC as tiebreaker. Note urls[0] is NOT assumed to be the
    best source (verified against the multi-source sample where 12 of 73
    channels have a faster source than urls[0]).
    """
    ranked = sorted(enumerate(sources), key=_rank_live_source_key)
    return ranked[0][0]


def import_live_json(data: dict, file_label: str = "") -> dict:
    """Import a live JSON. Full replace per source_region (design 2.3.1).

    Single-source and multi-source formats are both handled: every
    channel's URLs are stored in live_channel_sources (single-source
    channels get exactly one source row), and live_channels keeps the
    current playback source denormalized.
    """
    base = file_label or "live"
    if not isinstance(data, dict):
        return {"base": base, "type": "live", "error": "channels 数组为空"}
    channels = data.get("channels")
    if not isinstance(channels, list) or len(channels) == 0:
        return {"base": base, "type": "live", "error": "channels 数组为空"}

    region = str(data.get("region") or "").strip() or config.LIVE_DEFAULT_REGION
    generator = str(data.get("generator") or "").strip() or config.LIVE_DEFAULT_GENERATOR
    now_iso = datetime.now().isoformat()
    imported = 0
    skipped = 0
    total_sources = 0

    with get_db() as db:
        # Full replace: clear old channels (and their sources) for this region
        old_ids = [r["id"] for r in db.execute(
            "SELECT id FROM live_channels WHERE source_region = ?", (region,)
        ).fetchall()]
        for old_id in old_ids:
            db.execute("DELETE FROM live_channel_sources WHERE channel_id = ?", (old_id,))
        db.execute("DELETE FROM live_channels WHERE source_region = ?", (region,))

        for idx, ch in enumerate(channels):
            if not isinstance(ch, dict):
                skipped += 1
                continue
            name = str(ch.get("name") or "").strip()
            if not name:
                skipped += 1
                continue
            sources = _normalize_live_sources(ch)
            if not sources:
                skipped += 1
                continue

            default_pos = _pick_default_source(sources)
            default_src = sources[default_pos]

            cur = db.execute(
                """INSERT INTO live_channels
                (name, tvg_id, group_name, logo_url, stream_url, source_region,
                 source_generator, speed_mbps, delay_ms, current_source_id,
                 last_probe_speed, last_probe_delay, last_probe_at, probe_status,
                 sort_order, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    name,
                    _str_or_none(ch.get("tvg_id")),
                    _str_or_none(ch.get("group")) or config.LIVE_DEFAULT_GROUP,
                    _str_or_none(ch.get("logo")),
                    default_src["url"],
                    region,
                    generator,
                    default_src["speed_mbps"],
                    default_src["delay_ms"],
                    default_src["speed_mbps"],
                    default_src["delay_ms"],
                    now_iso,
                    "ok",
                    idx,
                    now_iso,
                    now_iso,
                ),
            )
            channel_id = cur.lastrowid

            default_source_id = None
            for pos, s in enumerate(sources):
                cur_s = db.execute(
                    """INSERT INTO live_channel_sources
                    (channel_id, url, node_ip, isp, speed_mbps, delay_ms,
                     sort_order, is_default, probe_status, fail_count, is_active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?)""",
                    (
                        channel_id,
                        s["url"],
                        s["node_ip"],
                        s["isp"],
                        s["speed_mbps"],
                        s["delay_ms"],
                        pos,
                        1 if pos == default_pos else 0,
                        "unknown",
                        now_iso,
                    ),
                )
                if pos == default_pos:
                    default_source_id = cur_s.lastrowid

            db.execute(
                "UPDATE live_channels SET current_source_id = ? WHERE id = ?",
                (default_source_id, channel_id),
            )
            imported += 1
            total_sources += len(sources)

        db.commit()

    return {
        "base": base,
        "type": "live",
        "region": region,
        "generator": generator,
        "channels": imported,
        "sources": total_sources,
        "skipped": skipped,
    }


# -- Live probe (independent of url_probes; design 2.5.2) --

def probe_live_url(url: str, proxies: dict | None = None) -> dict:
    """Probe a live stream: measure TTFB and read the first chunk to
    confirm the stream is alive. Returns {ok, status, delay_ms} where
    status is 'ok' | 'slow' | 'timeout'."""
    start = time.monotonic()
    try:
        with requests.get(
            url,
            stream=True,
            timeout=(config.LIVE_PROBE_TIMEOUT, config.LIVE_PROBE_TIMEOUT),
            allow_redirects=True,
            verify=False,
            proxies=proxies,
            headers={"User-Agent": config.DEFAULT_UA},
        ) as resp:
            ttfb_ms = int((time.monotonic() - start) * 1000)
            if resp.status_code >= 400:
                return {"ok": False, "status": "timeout", "delay_ms": 99999}
            chunk = next(resp.iter_content(config.LIVE_PROBE_FIRST_BYTES), b"")
            if not chunk:
                return {"ok": False, "status": "timeout", "delay_ms": 99999}
            status = "ok" if ttfb_ms < config.LIVE_PROBE_OK_DELAY_MS else "slow"
            return {"ok": True, "status": status, "delay_ms": ttfb_ms}
    except Exception:
        return {"ok": False, "status": "timeout", "delay_ms": 99999}


def _apply_live_probe_result(db, source_id: int, result: dict, now_iso: str):
    db.execute(
        """UPDATE live_channel_sources
        SET last_probe_speed = NULL, last_probe_delay = ?, last_probe_at = ?,
            probe_status = ?, fail_count = CASE WHEN ? = 1 THEN fail_count + 1 ELSE 0 END
        WHERE id = ?""",
        (result["delay_ms"], now_iso, result["status"], 0 if result["ok"] else 1, source_id),
    )


def probe_live_channel(channel_id: int) -> dict:
    """Probe every source of a channel (multi-source: per-source probe),
    update source rows, then refresh the channel aggregate from its
    current source."""
    from concurrent.futures import ThreadPoolExecutor

    with get_db() as db:
        channel = db.execute(
            "SELECT * FROM live_channels WHERE id = ?", (channel_id,)
        ).fetchone()
        if not channel:
            return {"error": "频道不存在"}
        sources = db.execute(
            "SELECT * FROM live_channel_sources WHERE channel_id = ? AND is_active = 1 ORDER BY sort_order",
            (channel_id,),
        ).fetchall()
        # Sources flagged to play through a proxy must be probed through it
        # as well; probing them directly would report failure even though
        # playback (which honors proxy_play) would succeed.
        probe_proxies = None
        try:
            cfg_id = channel["config_id"] if "config_id" in channel.keys() else None
        except Exception:
            cfg_id = None
        if cfg_id:
            cfg = db.execute(
                "SELECT use_proxy, proxy_pull, proxy_play FROM auto_update_configs WHERE id = ?", (cfg_id,)
            ).fetchone()
            if cfg and _proxy_play_enabled(dict(cfg)):
                probe_proxies = _play_proxies({"proxy_play": 1})
    if not sources:
        return {"error": "该频道没有可用源"}

    now_iso = datetime.now().isoformat()
    with ThreadPoolExecutor(max_workers=min(8, len(sources))) as pool:
        results = list(pool.map(lambda s: (s["id"], s["url"], probe_live_url(s["url"], probe_proxies)), sources))

    with get_db() as db:
        for source_id, _url, result in results:
            _apply_live_probe_result(db, source_id, result, now_iso)
        db.commit()
        # refresh channel aggregate from current source
        db.execute(
            """UPDATE live_channels SET
            last_probe_delay = (SELECT last_probe_delay FROM live_channel_sources WHERE id = live_channels.current_source_id),
            last_probe_at = ?,
            probe_status = COALESCE((SELECT probe_status FROM live_channel_sources WHERE id = live_channels.current_source_id), 'unknown'),
            updated_at = ?
            WHERE id = ?""",
            (now_iso, now_iso, channel_id),
        )
        db.commit()

    ok_count = sum(1 for _, _, r in results if r["ok"])
    return {
        "channel_id": channel_id,
        "probed": len(results),
        "ok": ok_count,
        "failed": len(results) - ok_count,
        "results": [
            {"source_id": sid, "url": url, "status": r["status"], "delay_ms": r["delay_ms"]}
            for sid, url, r in results
        ],
    }


@app.post("/api/import/json")
async def api_import_json(data: dict = Body(...), user_payload=Depends(require_admin)):
    path = data.get("path", "")
    explicit_project_id = data.get("project_id")
    try:
        if path:
            p = Path(path)
            if p.is_dir():
                results = await asyncio.to_thread(
                    import_directory_unified, str(p), explicit_project_id, False)
            else:
                results = [await asyncio.to_thread(
                    import_single_file_unified, str(p), explicit_project_id, False)]
        else:
            results = await asyncio.to_thread(
                import_directory_unified, "", explicit_project_id, False)
    except BangouConflictError as e:
        # Cross-project duplicate bangou (videos.bangou / series.bangou are
        # globally unique). The failed group's transaction is rolled back by
        # the closing db handle, so no partial data is left behind.
        raise HTTPException(
            status_code=409,
            detail=f"番号 {e.bangou} 已存在于项目「{e.owner_project_name}」，无法重复导入",
        )
    return {"ok": True, "results": results}


# -- API: Live (login required per design 2.8; not project-filtered) --

@app.get("/api/live/count")
async def get_live_count(user_payload=Depends(require_auth)):
    """Return total active live channel count."""
    with get_db() as db:
        cnt = db.execute("SELECT COUNT(*) FROM live_channels WHERE is_active = 1").fetchone()[0]
        return {"count": cnt}


@app.get("/api/live/groups")
async def get_live_groups(user_payload=Depends(require_auth)):
    """Return all live groups with channel counts (design 2.4.2)."""
    with get_db() as db:
        rows = db.execute("""
            SELECT group_name, COUNT(*) AS count, MIN(sort_order) AS min_sort
            FROM live_channels
            WHERE is_active = 1
            GROUP BY group_name
            ORDER BY min_sort, group_name
        """).fetchall()
        return {"groups": [{"name": r["group_name"], "count": r["count"]} for r in rows]}


@app.get("/api/live/channels")
async def get_live_channels(
    group: str = "", region: str = "",
    user_payload=Depends(require_auth),
):
    """Return the channel list, filterable by group and region (design 2.4.3)."""
    conditions = ["c.is_active = 1"]
    params: list = []
    if group:
        conditions.append("c.group_name = ?")
        params.append(group)
    if region:
        conditions.append("c.source_region = ?")
        params.append(region)
    where = " AND ".join(conditions)
    with get_db() as db:
        rows = db.execute(f"""
            SELECT c.*,
                   (SELECT COUNT(*) FROM live_channel_sources s
                    WHERE s.channel_id = c.id AND s.is_active = 1) AS source_count
            FROM live_channels c
            WHERE {where}
            ORDER BY c.group_name, c.sort_order, c.id
        """, params).fetchall()
        return {"channels": [_row_to_dict(r) for r in rows]}


@app.get("/api/live/channels/{channel_id:int}")
async def get_live_channel_detail(channel_id: int, user_payload=Depends(require_auth)):
    """Return one channel with its full source list (multi-source)."""
    with get_db() as db:
        channel = db.execute(
            "SELECT * FROM live_channels WHERE id = ?", (channel_id,)
        ).fetchone()
        if not channel:
            raise HTTPException(status_code=404, detail="频道不存在")
        sources = db.execute("""
            SELECT * FROM live_channel_sources
            WHERE channel_id = ? AND is_active = 1
            ORDER BY is_default DESC, speed_mbps DESC, delay_ms ASC, sort_order
        """, (channel_id,)).fetchall()
    result = _row_to_dict(channel)
    result["sources"] = [_row_to_dict(s) for s in sources]
    return result


@app.post("/api/live/channels/{channel_id:int}/switch")
async def switch_live_source(
    channel_id: int, data: dict = Body(...), user_payload=Depends(require_auth),
):
    """Manual switch to a specific source of the channel."""
    source_id = data.get("source_id")
    if not isinstance(source_id, int):
        raise HTTPException(status_code=400, detail="source_id 必填")
    with get_db() as db:
        channel = db.execute(
            "SELECT * FROM live_channels WHERE id = ?", (channel_id,)
        ).fetchone()
        if not channel:
            raise HTTPException(status_code=404, detail="频道不存在")
        source = db.execute(
            "SELECT * FROM live_channel_sources WHERE id = ? AND channel_id = ? AND is_active = 1",
            (source_id, channel_id),
        ).fetchone()
        if not source:
            raise HTTPException(status_code=404, detail="源不存在")
        now_iso = datetime.now().isoformat()
        db.execute(
            "UPDATE live_channel_sources SET is_default = 0 WHERE channel_id = ?",
            (channel_id,),
        )
        db.execute(
            "UPDATE live_channel_sources SET is_default = 1 WHERE id = ?",
            (source_id,),
        )
        db.execute(
            """UPDATE live_channels SET current_source_id = ?, stream_url = ?,
               speed_mbps = ?, delay_ms = ?, updated_at = ? WHERE id = ?""",
            (source_id, source["url"], source["speed_mbps"], source["delay_ms"], now_iso, channel_id),
        )
        db.commit()
        updated = db.execute(
            "SELECT * FROM live_channels WHERE id = ?", (channel_id,)
        ).fetchone()
    return {"ok": True, "channel": _row_to_dict(updated)}


@app.post("/api/live/channels/{channel_id:int}/next-source")
async def fallback_live_source(channel_id: int, user_payload=Depends(require_auth)):
    """Failure fallback: record the failure on the current source
    (fail_count + 1, probe_status='timeout') and switch to the next best
    source using the default selection strategy (speed DESC, delay ASC,
    position ASC).

    The failed source is deliberately KEPT active (is_active stays 1) so it
    never disappears from the channel's source list; the UI shows its failure
    state instead of removing the entry. A deactivated source used to vanish
    from GET /api/live/channels/{id} (which filters is_active=1) and only
    came back after every source was exhausted — that behaviour is removed."""
    with get_db() as db:
        channel = db.execute(
            "SELECT * FROM live_channels WHERE id = ?", (channel_id,)
        ).fetchone()
        if not channel:
            raise HTTPException(status_code=404, detail="频道不存在")
        sources = db.execute(
            "SELECT * FROM live_channel_sources WHERE channel_id = ? AND is_active = 1",
            (channel_id,),
        ).fetchall()
        if not sources:
            raise HTTPException(status_code=404, detail="该频道没有可用源")

        current_id = channel["current_source_id"]
        if current_id:
            db.execute(
                """UPDATE live_channel_sources
                   SET fail_count = fail_count + 1, probe_status = 'timeout'
                   WHERE id = ?""",
                (current_id,),
            )
            remaining = [s for s in sources if s["id"] != current_id]
        else:
            remaining = list(sources)

        if not remaining:
            # Only one source exists (or the current source is unknown):
            # nothing else to switch to, keep the current selection.
            remaining = [s for s in sources if s["id"] == current_id] or list(sources)

        def _fallback_key(s):
            speed = s["speed_mbps"]
            delay = s["delay_ms"]
            return (
                0 if speed is not None else 1,
                -speed if speed is not None else 0.0,
                0 if delay is not None else 1,
                delay if delay is not None else 0.0,
                s["sort_order"],
            )

        best = sorted(remaining, key=_fallback_key)[0]
        now_iso = datetime.now().isoformat()
        db.execute(
            "UPDATE live_channel_sources SET is_default = 0 WHERE channel_id = ?",
            (channel_id,),
        )
        db.execute(
            "UPDATE live_channel_sources SET is_default = 1, is_active = 1 WHERE id = ?",
            (best["id"],),
        )
        db.execute(
            """UPDATE live_channels SET current_source_id = ?, stream_url = ?,
               speed_mbps = ?, delay_ms = ?, probe_status = 'unknown', updated_at = ?
               WHERE id = ?""",
            (best["id"], best["url"], best["speed_mbps"], best["delay_ms"], now_iso, channel_id),
        )
        db.commit()

    return {
        "ok": True,
        "switched_to": {
            "source_id": best["id"],
            "url": best["url"],
            "speed_mbps": best["speed_mbps"],
            "delay_ms": best["delay_ms"],
        },
    }


# ── 直播流同源复用（Hub）────────────────────────────────────────────────
# 同一个上游地址只维持一条 udpxy/源站会话，多设备/多标签页共享同一路数据，
# 避免多观众 + 自动换源 + 巡检任务叠加触发 udpxy 并发会话上限（典型 -c 3）。
# 慢速订阅者队列满时丢旧块，只影响其自身画面，不阻塞其他订阅者。

_live_hubs: dict = {}
_live_hubs_lock = asyncio.Lock()

class _LiveHub:
    __slots__ = ("client", "resp", "subs", "cleaner", "dead", "content_type")
    def __init__(self):
        self.client = None
        self.resp = None
        self.subs = {}            # sid -> asyncio.Queue(maxsize=96)
        self.cleaner = None
        self.dead = False
        self.content_type = "video/mp2t"

async def _open_live_upstream(target_url: str, should_use_proxy: bool, headers: dict):
    """Open one upstream live session. Raises HTTPException(502) on failure."""
    import httpx as _httpx_mod
    proxy_url: str | None = None
    if should_use_proxy:
        proxy_url = (_play_proxies({"proxy_play": 1} if should_use_proxy else {"proxy_play": 0}) or {}).get("https") \
            or (_play_proxies({"proxy_play": 1} if should_use_proxy else {"proxy_play": 0}) or {}).get("http") or None
    transport = _httpx_mod.AsyncHTTPTransport(
        verify=_REQUESTS_VERIFY,
        proxy=proxy_url if should_use_proxy else None,
    )
    client = _httpx_mod.AsyncClient(
        transport=transport,
        follow_redirects=True,
        trust_env=False,
        timeout=_httpx_mod.Timeout(connect=3.5, read=None, write=5.0, pool=5.0),
    )
    try:
        req = client.build_request("GET", target_url, headers=headers)
        resp = await client.send(req, stream=True)
        if resp.status_code >= 400:
            status_code = resp.status_code
            await resp.aclose()
            await client.aclose()
            raise HTTPException(status_code=502, detail=f"直播源连接失败: HTTP {status_code}")
        return client, resp
    except HTTPException:
        raise
    except Exception as e:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"直播源连接失败: {e}")

async def _live_hub_feeder(key: str, hub: "_LiveHub"):
    try:
        async for chunk in hub.resp.aiter_bytes(chunk_size=65536):
            if not chunk:
                continue
            for q in list(hub.subs.values()):
                if q.full():
                    try:
                        q.get_nowait()
                    except Exception:
                        pass
                try:
                    q.put_nowait(chunk)
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        hub.dead = True
        _live_hubs.pop(key, None)
        for q in list(hub.subs.values()):
            try:
                q.put_nowait(None)
            except Exception:
                pass

async def _live_hub_idle_close(key: str, delay: float = 2.0):
    await asyncio.sleep(delay)
    async with _live_hubs_lock:
        hub = _live_hubs.get(key)
        if hub is not None and not hub.subs:
            hub.dead = True
            _live_hubs.pop(key, None)
            try:
                await hub.resp.aclose()
            except Exception:
                pass
            try:
                await hub.client.aclose()
            except Exception:
                pass

async def _live_hub_join(key: str, target_url: str, should_use_proxy: bool, headers: dict):
    """Join the shared upstream session for one source (create if absent)."""
    async with _live_hubs_lock:
        hub = _live_hubs.get(key)
        if hub is not None and hub.dead:
            _live_hubs.pop(key, None)
            hub = None
        if hub is None:
            client, resp = await _open_live_upstream(target_url, should_use_proxy, headers)
            hub = _LiveHub()
            hub.client = client
            hub.resp = resp
            ct = resp.headers.get("content-type", "")
            if not ct or "octet-stream" in ct:
                ct = "video/mp2t"
            hub.content_type = ct
            asyncio.create_task(_live_hub_feeder(key, hub))
            _live_hubs[key] = hub
        else:
            if hub.cleaner is not None:
                hub.cleaner.cancel()
                hub.cleaner = None
        q = asyncio.Queue(maxsize=96)
        sid = id(q)
        hub.subs[sid] = q
    return hub, q, sid

def _live_hub_leave(key: str, hub: "_LiveHub", sid) -> None:
    hub.subs.pop(sid, None)
    if not hub.subs and not hub.dead and hub.cleaner is None:
        hub.cleaner = asyncio.create_task(_live_hub_idle_close(key))

async def _live_hub_stream(key: str, hub: "_LiveHub", sid, q: asyncio.Queue):
    try:
        while True:
            chunk = await q.get()
            if chunk is None:
                break
            yield chunk
    finally:
        _live_hub_leave(key, hub, sid)


@app.get("/api/live/stream")
@app.get("/api/live/stream/{channel_id:int}/{source_id:int}")
async def live_stream_proxy(
    request: Request,
    channel_id: int | None = None,
    source_id: int | None = None,
    url: str = "",
    use_proxy: int | None = None,
    user_payload=Depends(require_auth),
):
    """Proxy/relay live streams (especially MPEG-TS HTTP streams like udpxy/msps)
    to the browser with standard CORS headers, chunked streaming, and optional
    per-source proxying."""
    target_url = ""
    should_use_proxy = False
    # URLs read back from the database were imported by an admin, so they
    # are trusted playback targets (typically intranet udpxy/msps addresses
    # such as 192.168.x.x that the generic SSRF guard would reject).
    # Only the arbitrary ?url= form (any authenticated user can pass any
    # address) keeps the full private-address block.
    from_trusted_store = False

    if source_id is not None:
        with get_db() as db:
            src = db.execute(
                "SELECT * FROM live_channel_sources WHERE id = ?", (source_id,)
            ).fetchone()
            if not src:
                raise HTTPException(status_code=404, detail="直播源不存在")
            target_url = src["url"]
            from_trusted_store = True
            ch = db.execute(
                "SELECT config_id, source_region FROM live_channels WHERE id = ?", (src["channel_id"],)
            ).fetchone()
            if ch and ch["config_id"]:
                cfg = db.execute(
                    "SELECT use_proxy, proxy_pull, proxy_play FROM auto_update_configs WHERE id = ?", (ch["config_id"],)
                ).fetchone()
                # Play channel: per-source proxy_play (NULL = follow legacy
                # use_proxy, then global proxy_play_default).
                should_use_proxy = _proxy_play_enabled(dict(cfg) if cfg else None)
            else:
                should_use_proxy = _proxy_play_enabled(None)
    elif url:
        target_url = url
        should_use_proxy = _proxy_play_enabled(None)
    else:
        raise HTTPException(status_code=400, detail="缺少 url 或 source_id 参数")

    if use_proxy is not None:
        should_use_proxy = bool(use_proxy)

    if from_trusted_store:
        parsed = urllib.parse.urlparse(target_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HTTPException(status_code=400, detail="地址未通过安全校验: 仅允许 http/https 协议且主机名必填")
    else:
        # Arbitrary user-supplied URL: keep the full SSRF block (intranet
        # playback goes through the trusted source_id path above instead).
        ok, reason = validate_update_url(target_url)
        if not ok:
            raise HTTPException(status_code=400, detail=f"地址未通过安全校验: {reason}")

    proxies = _play_proxies({"proxy_play": 1} if should_use_proxy else {"proxy_play": 0})
    headers = _proxy_headers()
    if "range" in request.headers:
        headers["Range"] = request.headers["range"]

    # ── 同源复用分支（非 Range 请求）：多观众共享同一条上游会话 ─────────────
    if "range" not in request.headers:
        hub_key = f"{target_url}|{int(bool(should_use_proxy))}"
        hub, q, sid = await _live_hub_join(hub_key, target_url, should_use_proxy, headers)
        if "mpegurl" not in (hub.content_type or "").lower():
            return StreamingResponse(
                _live_hub_stream(hub_key, hub, sid, q),
                status_code=200,
                media_type=hub.content_type,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Connection": "keep-alive",
                },
            )
        # 上游是 m3u8 播放列表：退出 hub（需整体读文本做改写），走下方单路路径
        _live_hub_leave(hub_key, hub, sid)

    # ── async httpx 非阻塞流转 ──────────────────────────────────────────────
    # 禁用 OS 环境代理继承（trust_env=False），避免局域网/电信组播源被错误发往 HTTP 代理。
    # 仅在显式配置代理时挂载 proxy_url。
    # 先发起 upstream 连接，若超时或报错立刻返回 502，使前端能够快速切源，而不是挂起假死。
    client, upstream_resp = await _open_live_upstream(target_url, should_use_proxy, headers)

    _content_type = upstream_resp.headers.get("content-type", "")
    if not _content_type or "octet-stream" in _content_type:
        _content_type = "video/mp2t"

    # P2-7: 上游是 m3u8 播放列表时，把相对分片/子播放列表 URI 改写为绝对上游地址，
    # 使 iOS 原生 HLS（video.src 直播代理地址）能正确解析后续分片。
    _upstream_path = target_url.split("?")[0].lower()
    if "mpegurl" in _content_type.lower() or _upstream_path.endswith(".m3u8"):
        try:
            _playlist_text = (await upstream_resp.aread()).decode("utf-8", "replace")
        finally:
            await upstream_resp.aclose()
            await client.aclose()
        _base_url = target_url

        def _abs_uri(u: str) -> str:
            if not u or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
                return u
            return urllib.parse.urljoin(_base_url, u)

        _rewritten = []
        for _line in _playlist_text.splitlines():
            _t = _line.strip()
            if _t.startswith("#"):
                _line = re.sub(r'URI="([^"]*)"', lambda m: f'URI="{_abs_uri(m.group(1))}"', _line)
            elif _t:
                _line = _abs_uri(_t)
            _rewritten.append(_line)
        return Response(
            "\n".join(_rewritten) + "\n",
            status_code=200,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Connection": "keep-alive",
            },
        )

    async def async_stream_generator():
        try:
            # 64 KB chunks —— 极大降低 Python 调度与 I/O 上下文切换开销
            async for chunk in upstream_resp.aiter_bytes(chunk_size=65536):
                if chunk:
                    yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    resp_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        async_stream_generator(),
        status_code=200,
        media_type=_content_type,
        headers=resp_headers,
    )


@app.options("/api/live/stream")
@app.options("/api/live/stream/{channel_id:int}/{source_id:int}")
async def live_stream_options():
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )



@app.get("/api/live/logo")
async def live_logo_proxy(url: str, user_payload=Depends(require_auth)):
    """Proxy channel logo images through the server so the browser can display
    logos stored on private/intranet addresses (e.g. 192.168.x.x)."""
    if not url:
        raise HTTPException(status_code=400, detail="缺少 url 参数")
    import httpx as _hx
    try:
        async with _hx.AsyncClient(
            follow_redirects=True,
            trust_env=False,
            timeout=_hx.Timeout(5.0),
            transport=_hx.AsyncHTTPTransport(verify=False),
        ) as client:
            resp = await client.get(url, headers={"User-Agent": "suenplayer/1.0"})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Logo 获取失败: {e}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail="Logo 不可达")
    ct = resp.headers.get("content-type", "image/png")
    return Response(
        content=resp.content,
        media_type=ct,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.post("/api/admin/live/import")
async def admin_import_live(data: dict = Body(...), user_payload=Depends(require_admin)):
    """Import a live JSON file (admin only, design 2.8.3)."""
    path = data.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="path 必填")
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}")
    if detect_json_type(payload) != "live":
        raise HTTPException(status_code=400, detail="不是直播 JSON 格式")
    result = import_live_json(payload, p.stem)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    with get_db() as db:
        summary = f"频道: {result.get('channels', 0)}, 源: {result.get('sources', 0)}"
        cid = _register_or_update_auto_config(
            db, p.stem, "live", str(p), use_proxy=0, last_status="success", last_result=summary
        )
        db.execute(
            "UPDATE live_channels SET config_id = ? WHERE (config_id IS NULL OR config_id = 0) AND source_region = ?",
            (cid, payload.get("region") or p.stem),
        )
        db.commit()
    result["config_id"] = cid
    return {"ok": True, **result}


@app.post("/api/admin/live/channels/{channel_id:int}/probe")
async def admin_probe_live_channel(channel_id: int, user_payload=Depends(require_admin)):
    """Manually trigger a probe of every source of a channel (admin only)."""
    result = probe_live_channel(channel_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return {"ok": True, **result}


# -- API: Recent Updates (with project filtering) --

@app.get("/api/recent-updates")
async def get_recent_updates(
    page: int = 1, limit: int = 60, project: str = "",
    request: Request = None
):
    limit = min(limit, 200)
    offset = (page - 1) * limit
    visible_projects = _get_visible_projects_from_request(request)
    # Project permission is resolved before the zero-visible early exit so a
    # user without any visible project still gets 403 for an existing but
    # forbidden project instead of a silent empty page.
    if not visible_projects and not project:
        return {"total": 0, "page": page, "items": []}

    with get_db() as db:
        # project param: project name or slug first, numeric id as fallback.
        # Visibility is enforced against the caller's allowed projects;
        # an existing but forbidden project is a 403, an unknown one
        # yields an empty page.
        project_id_filter = None
        if project:
            row = db.execute(
                "SELECT id FROM projects WHERE name = ? OR slug = ?", (project, project)
            ).fetchone()
            if row is None and re.fullmatch(r"\d+", project):
                row = db.execute("SELECT id FROM projects WHERE id = ?", (int(project),)).fetchone()
            if row is None:
                return {"total": 0, "page": page, "items": []}
            if row["id"] not in visible_projects:
                raise HTTPException(status_code=403, detail="无权访问该项目")
            project_id_filter = row["id"]
        proj_clause_v, proj_params_v = _project_filter_clause(visible_projects)
        proj_clause_s, proj_params_s = _project_filter_clause(visible_projects)
        if project_id_filter is not None:
            proj_clause_v += " AND videos.project_id = ?"
            proj_params_v = proj_params_v + [project_id_filter]
            proj_clause_s += " AND series.project_id = ?"
            proj_params_s = proj_params_s + [project_id_filter]

        total_v = db.execute(
            f"SELECT COUNT(*) FROM videos WHERE first_imported_at IS NOT NULL AND {proj_clause_v}",
            proj_params_v
        ).fetchone()[0]
        total_s = db.execute(
            f"SELECT COUNT(*) FROM series WHERE first_imported_at IS NOT NULL AND {proj_clause_s}",
            proj_params_s
        ).fetchone()[0]
        total = total_v + total_s

        video_select_cols = (
            "videos.id, videos.bangou, videos.title, videos.cover, videos.region, "
            "videos.group_name, videos.date, videos.site, videos.tags, "
            "videos.overview, videos.original_title, videos.backdrop, videos.rating, "
            "videos.rating_source, videos.vote_count, videos.year, videos.first_air_date, "
            "videos.runtime, videos.status, videos.original_language, videos.homepage, "
            "videos.certification, videos.country, videos.studio, videos.logo, "
            "videos.popularity, videos.view_count, videos.trending_rank, "
            "videos.cast, videos.director, videos.cast_structured, videos.director_structured, "
            "videos.created_at, videos.first_imported_at, videos.import_batch_id, "
            "NULL AS number_of_seasons, NULL AS number_of_episodes, videos.project_id AS project_id"
        )
        series_select_cols = (
            "series.id, series.bangou, series.title, series.cover, series.region, "
            "series.group_name, series.date, series.site, series.tags, "
            "series.overview, series.original_title, series.backdrop, series.rating, "
            "series.rating_source, series.vote_count, series.year, series.first_air_date, "
            "series.runtime, series.status, series.original_language, series.homepage, "
            "series.certification, series.country, series.studio, series.logo, "
            "series.popularity, series.view_count, series.trending_rank, "
            "series.number_of_seasons, series.number_of_episodes, "
            "series.cast, series.director, series.cast_structured, series.director_structured, "
            "series.created_at, series.first_imported_at, series.import_batch_id, "
            "series.project_id AS project_id"
        )

        query = (
            "SELECT 'video' AS type, " + video_select_cols + " FROM videos "
            f"WHERE first_imported_at IS NOT NULL AND {proj_clause_v} "
            "UNION ALL "
            "SELECT 'series' AS type, " + series_select_cols + " FROM series "
            f"WHERE first_imported_at IS NOT NULL AND {proj_clause_s} "
            "ORDER BY first_imported_at DESC "
            "LIMIT ? OFFSET ?"
        )
        rows = db.execute(query, proj_params_v + proj_params_s + [limit, offset]).fetchall()

        project_names = {
            pr["id"]: pr["name"]
            for pr in db.execute("SELECT id, name FROM projects").fetchall()
        }
        items = []
        for r in rows:
            d = dict(r)
            if "group_name" in d and "group" not in d:
                d["group"] = d.pop("group_name")
            d["project"] = project_names.get(d.get("project_id"))
            items.append(d)

        return {"total": total, "page": page, "items": items}


# -- API: URLs --

@app.get("/api/urls")
async def get_urls(target_id: int, target_type: str = "video", request: Request = None):
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM urls WHERE target_id = ? AND target_type = ? ORDER BY priority",
            (target_id, target_type)
        ).fetchall()
        # Validate project visibility for each URL's target
        result = []
        for r in rows:
            d = dict(r)
            # Check target belongs to visible project
            if target_type == "video":
                proj_row = db.execute("SELECT project_id FROM videos WHERE id = ?", (target_id,)).fetchone()
            elif target_type == "series":
                proj_row = db.execute("SELECT project_id FROM series WHERE id = ?", (target_id,)).fetchone()
            elif target_type == "episode":
                proj_row = db.execute(
                    """SELECT se.project_id FROM episodes e
                       JOIN seasons s ON e.season_id = s.id
                       JOIN series se ON s.series_id = se.id
                       WHERE e.id = ?""", (target_id,)
                ).fetchone()
            else:
                proj_row = None
            if proj_row and proj_row["project_id"] in visible_projects:
                result.append(d)
        return result


# -- API: Suspense (with project filtering) --

@app.get("/api/suspense")
async def get_suspense(request: Request = None):
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        proj_clause, proj_params = _project_filter_clause(visible_projects)
        rows = db.execute(
            f"SELECT * FROM suspense WHERE {proj_clause} ORDER BY created_at DESC",
            proj_params
        ).fetchall()
        return [dict(r) for r in rows]


@app.delete("/api/suspense/{sid:int}")
async def delete_suspense(sid: int, user_payload=Depends(require_auth)):
    with get_db() as db:
        db.execute("DELETE FROM suspense WHERE id = ?", (sid,))
        db.commit()
        return {"ok": True}


# -- API: Play & Probe (with project validation) --

def _get_stability_score(db, url_hash: str) -> float:
    row = db.execute(
        "SELECT consecutive_success FROM url_probes WHERE url_hash = ? ORDER BY probed_at DESC LIMIT 1",
        (url_hash,)
    ).fetchone()
    if row and row["consecutive_success"]:
        return min(1.0, row["consecutive_success"] / config.STABILITY_FULL_SCORE)
    return 0.0


def _save_probe_result(db, result: quick.ProbeResult):
    prev = db.execute(
        "SELECT consecutive_success, is_success FROM url_probes WHERE url_hash = ? ORDER BY probed_at DESC LIMIT 1",
        (result.url_hash,)
    ).fetchone()
    if result.success:
        consecutive = (prev["consecutive_success"] if prev else 0) + 1
        is_success = 1
    else:
        consecutive = 0
        is_success = 0
    db.execute(
        """INSERT INTO url_probes
        (url, url_hash, latency_ms, rate_mbps, resolution, total_score, consecutive_success, is_success)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (result.url, result.url_hash, result.latency_ms, result.rate_mbps,
         result.resolution, result.total_score, consecutive, is_success),
    )


def _get_cached_probe(db, url_hash: str) -> Optional[quick.ProbeResult]:
    since = datetime.now(timezone.utc) - timedelta(seconds=config.PROBE_CACHE_TTL_SECONDS)
    row = db.execute(
        "SELECT * FROM url_probes WHERE url_hash = ? AND is_success = 1 AND probed_at > ? ORDER BY probed_at DESC LIMIT 1",
        (url_hash, since.isoformat())
    ).fetchone()
    if row:
        return quick.ProbeResult(
            url=row["url"],
            url_hash=row["url_hash"],
            success=True,
            latency_ms=row["latency_ms"] or 0,
            rate_mbps=row["rate_mbps"] or 0,
            resolution=row["resolution"] or "",
            total_score=row["total_score"] or 0,
        )
    return None


def _get_urls_for_target(db, target_id: int, target_type: str):
    rows = db.execute(
        "SELECT id, url, url_hash, source, label, resolution, url_type FROM urls WHERE target_id = ? AND target_type = ? AND is_active = 1",
        (target_id, target_type)
    ).fetchall()
    return [dict(r) for r in rows]


def _validate_target_project(db, target_id: int, target_type: str, visible_projects: list[int]) -> bool:
    if target_type == "video":
        row = db.execute("SELECT project_id FROM videos WHERE id = ?", (target_id,)).fetchone()
    elif target_type == "episode":
        row = db.execute(
            """SELECT se.project_id FROM episodes e
               JOIN seasons s ON e.season_id = s.id
               JOIN series se ON s.series_id = se.id
               WHERE e.id = ?""", (target_id,)
        ).fetchone()
    else:
        return False
    return row is not None and row["project_id"] in visible_projects


@app.get("/api/play/probe")
async def play_probe(target_id: int, target_type: str = "video", request: Request = None):
    if target_type not in ("video", "episode"):
        return JSONResponse({"error": "invalid target_type"}, status_code=400)
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        if not _validate_target_project(db, target_id, target_type, visible_projects):
            return JSONResponse({"error": "not found"}, status_code=404)

        urls = _get_urls_for_target(db, target_id, target_type)
        if not urls:
            tbl = "videos" if target_type == "video" else "episodes"
            id_col = "id"
            row = db.execute(f"SELECT url FROM {tbl} WHERE {id_col} = ?", (target_id,)).fetchone()
            if row and row["url"]:
                urls = [{"url": row["url"], "url_hash": _url_hash(row["url"]), "source": "主源", "label": "", "resolution": "", "url_type": "stream"}]
            else:
                return JSONResponse({"error": "no urls found"}, status_code=404)

        stream_urls = [u for u in urls if u.get("url_type") != "page"]
        page_urls = [u for u in urls if u.get("url_type") == "page"]

        stream_to_probe = []
        stream_cached = []
        for u in stream_urls:
            cached = _get_cached_probe(db, u["url_hash"])
            if cached:
                stream_cached.append(cached)
            else:
                stability = _get_stability_score(db, u["url_hash"])
                stream_to_probe.append((u["url"], u.get("resolution", ""), stability))

        stream_probed = []
        if stream_to_probe:
            stream_probed = quick.probe_urls_concurrent(stream_to_probe)
            for r in stream_probed:
                _save_probe_result(db, r)
            db.commit()

        stream_results = stream_cached + [r for r in stream_probed if r.success]

        page_results = []
        if page_urls:
            page_items = [(u["url"], "", 0.0) for u in page_urls]
            page_probed = quick.probe_pages_concurrent(page_items)
            page_results = [r for r in page_probed if r.success]

        all_results = stream_results + page_results

        if not all_results:
            first_hash = urls[0]["url_hash"]
            expired = db.execute(
                "SELECT * FROM url_probes WHERE url_hash = ? AND is_success = 1 ORDER BY probed_at DESC LIMIT 1",
                (first_hash,)
            ).fetchone()
            if expired:
                return {
                    "primary": {"url": expired["url"], "source": "缓存回退", "score": 0, "url_type": urls[0].get("url_type", "stream"), "proxied": _proxied_for(expired["url"])},
                    "backups": [],
                    "fallback": True,
                }
            return {
                "primary": {"url": urls[0]["url"], "source": urls[0].get("source", "默认"), "score": 0, "url_type": urls[0].get("url_type", "stream"), "proxied": _proxied_for(urls[0]["url"])},
                "backups": [],
                "fallback": True,
            }

        primary, backups, rest = quick.rank_lines(all_results)

        _settings_pl = load_settings()
        def _proxied_for(u: str) -> bool:
            return bool(_settings_pl.get("proxy", "")) and _site_proxy_enabled(u, _settings_pl)

        def _build_line(result: quick.ProbeResult):
            u = next((x for x in urls if x["url"] == result.url), {})
            proxied = _proxied_for(result.url)
            return {
                "url": result.url,
                "source": u.get("source", ""),
                "label": u.get("label", ""),
                "resolution": result.resolution or u.get("resolution", ""),
                "url_type": u.get("url_type", "stream"),
                "latency_ms": round(result.latency_ms, 1),
                "rate_mbps": round(result.rate_mbps, 2),
                "score": round(result.total_score, 3),
                "proxied": proxied,
            }

        return {
            "primary": _build_line(primary) if primary else None,
            "backups": [_build_line(b) for b in backups],
            "all": [_build_line(r) for r in all_results],
            "fallback": False,
        }


@app.post("/api/play/switch")
async def play_switch(data: dict = Body(...), request: Request = None):
    target_id = data.get("target_id")
    target_type = data.get("target_type", "video")
    url = data.get("url", "")
    if not target_id or not url:
        return JSONResponse({"error": "target_id and url required"}, status_code=400)
    visible_projects = _get_visible_projects_from_request(request)
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM urls WHERE target_id = ? AND target_type = ? AND url = ?",
            (target_id, target_type, url)
        ).fetchone()
        if not row:
            return JSONResponse({"error": "url not found for target"}, status_code=404)
        if not _validate_target_project(db, target_id, target_type, visible_projects):
            return JSONResponse({"error": "not found"}, status_code=404)

        result_url = row["url"]
        if row["url_type"] == "page":
            fresh = _resolve_fresh_url(row["url"])
            if "url" in fresh:
                result_url = fresh["url"]

        return {
            "url": result_url,
            "source": row["source"],
            "label": row["label"],
            "resolution": row["resolution"],
            "url_type": row["url_type"],
        }


# -- API: Projects --

@app.get("/api/projects")
async def list_projects(request: Request, has_content: bool = False):
    payload = await require_auth(request)
    visible = _get_user_visible_projects(payload)
    with get_db() as db:
        placeholders = ",".join("?" for _ in visible) if visible else "-1"
        rows = db.execute(
            f"""SELECT p.id, p.name, p.slug, p.description, p.sort_order, p.is_active,
                       (SELECT COUNT(*) FROM videos v WHERE v.project_id = p.id) +
                       (SELECT COUNT(*) FROM series s WHERE s.project_id = p.id) AS item_count
                FROM projects p WHERE p.id IN ({placeholders}) ORDER BY p.sort_order""",
            visible
        ).fetchall()
        res = [{"id": r["id"], "name": r["name"], "slug": r["slug"], "description": r["description"],
                "sort_order": r["sort_order"], "is_active": r["is_active"], "item_count": r["item_count"]}
               for r in rows]
        if has_content:
            res = [p for p in res if p["item_count"] > 0]
        return res


@app.get("/api/projects/{project_id:int}")
async def get_project(project_id: int, request: Request):
    payload = await require_auth(request)
    visible = _get_user_visible_projects(payload)
    if project_id not in visible:
        raise HTTPException(status_code=404, detail="not found")
    with get_db() as db:
        row = db.execute(
            "SELECT id, name, slug, description, sort_order, is_active FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return {"id": row["id"], "name": row["name"], "slug": row["slug"], "description": row["description"], "sort_order": row["sort_order"], "is_active": row["is_active"]}


# -- API: Admin --

@app.get("/api/admin/users")
async def admin_list_users(user_payload=Depends(require_admin)):
    with get_db() as db:
        rows = db.execute(
            "SELECT id, username, display_name, role, is_active, created_at FROM users ORDER BY id"
        ).fetchall()
        return [{"id": r["id"], "username": r["username"], "display_name": r["display_name"],
                 "role": r["role"], "is_active": r["is_active"], "created_at": r["created_at"]} for r in rows]


@app.post("/api/admin/users")
async def admin_create_user(data: dict = Body(...), user_payload=Depends(require_admin)):
    username = str(data.get("username") or "").strip().lower()
    password = str(data.get("password") or "").strip()
    display_name = str(data.get("display_name") or "").strip() or username
    role = data.get("role", "viewer")
    project_ids = data.get("project_ids", [])

    if not username or not password or len(password) < 6:
        return JSONResponse({"error": "用户名必填，密码至少6位"}, status_code=400)
    if role not in ("admin", "viewer"):
        return JSONResponse({"error": "role 必须是 admin 或 viewer"}, status_code=400)

    with get_db() as db:
        existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            return JSONResponse({"error": "用户名已存在"}, status_code=409)

        cur = db.execute(
            "INSERT INTO users (username, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, display_name, _hash_password(password), role)
        )
        user_id = cur.lastrowid

        if role == "viewer" and project_ids:
            for pid in project_ids:
                db.execute(
                    "INSERT OR IGNORE INTO user_projects (user_id, project_id) VALUES (?, ?)",
                    (user_id, pid)
                )
        db.commit()
        return {"id": user_id, "username": username, "role": role}


@app.patch("/api/admin/users/{user_id:int}")
async def admin_update_user(user_id: int, data: dict = Body(...), user_payload=Depends(require_admin)):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return JSONResponse({"error": "用户不存在"}, status_code=404)
        # Cannot modify self role to non-admin
        if user_id == user_payload.get("uid") and data.get("role") != "admin":
            return JSONResponse({"error": "不能取消自己的管理员权限"}, status_code=400)

        updates = []
        params = []
        if "display_name" in data:
            updates.append("display_name = ?")
            params.append(str(data["display_name"]).strip())
        if "password" in data:
            pw = str(data["password"]).strip()
            if len(pw) < 6:
                return JSONResponse({"error": "密码至少6位"}, status_code=400)
            updates.append("password_hash = ?")
            params.append(_hash_password(pw))
        if "role" in data:
            role = data["role"]
            if role not in ("admin", "viewer"):
                return JSONResponse({"error": "role 必须是 admin 或 viewer"}, status_code=400)
            updates.append("role = ?")
            params.append(role)
        if "is_active" in data:
            updates.append("is_active = ?")
            params.append(1 if data["is_active"] else 0)

        if updates:
            params.append(user_id)
            db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
            db.commit()
        return {"ok": True}


@app.delete("/api/admin/users/{user_id:int}")
async def admin_delete_user(user_id: int, user_payload=Depends(require_admin)):
    if user_id == user_payload.get("uid"):
        return JSONResponse({"error": "不能删除自己"}, status_code=400)
    with get_db() as db:
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.execute("DELETE FROM user_projects WHERE user_id = ?", (user_id,))
        db.commit()
        return {"ok": True}


@app.get("/api/admin/users/{user_id:int}/projects")
async def admin_get_user_projects(user_id: int, user_payload=Depends(require_admin)):
    with get_db() as db:
        user = db.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return JSONResponse({"error": "用户不存在"}, status_code=404)
        if user["role"] == "admin":
            return {"projects": []}  # Admin sees all, no explicit mappings needed
        rows = db.execute(
            "SELECT project_id FROM user_projects WHERE user_id = ?", (user_id,)
        ).fetchall()
        return {"projects": [r["project_id"] for r in rows]}


@app.post("/api/admin/users/{user_id:int}/projects")
async def admin_assign_user_projects(user_id: int, data: dict = Body(...), user_payload=Depends(require_admin)):
    project_ids = data.get("project_ids", [])
    with get_db() as db:
        user = db.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return JSONResponse({"error": "用户不存在"}, status_code=404)
        if user["role"] == "admin":
            return JSONResponse({"error": "不能为管理员分配项目"}, status_code=400)
        for pid in project_ids:
            db.execute(
                "INSERT OR IGNORE INTO user_projects (user_id, project_id) VALUES (?, ?)",
                (user_id, pid)
            )
        db.commit()
        return {"ok": True}


@app.delete("/api/admin/users/{user_id:int}/projects/{project_id:int}")
async def admin_remove_user_project(user_id: int, project_id: int, user_payload=Depends(require_admin)):
    with get_db() as db:
        db.execute("DELETE FROM user_projects WHERE user_id = ? AND project_id = ?", (user_id, project_id))
        db.commit()
        return {"ok": True}


@app.get("/api/admin/projects")
async def admin_list_projects(user_payload=Depends(require_admin)):
    with get_db() as db:
        rows = db.execute("SELECT * FROM projects ORDER BY sort_order").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["video_count"] = db.execute(
                "SELECT COUNT(*) FROM videos WHERE project_id = ?", (r["id"],)
            ).fetchone()[0]
            d["series_count"] = db.execute(
                "SELECT COUNT(*) FROM series WHERE project_id = ?", (r["id"],)
            ).fetchone()[0]
            result.append(d)
        return result


@app.post("/api/admin/projects")
async def admin_create_project(data: dict = Body(...), user_payload=Depends(require_admin)):
    name = str(data.get("name") or "").strip()
    slug = str(data.get("slug") or "").strip().lower()
    description = str(data.get("description") or "").strip()
    if not name or not slug:
        return JSONResponse({"error": "name and slug required"}, status_code=400)
    with get_db() as db:
        existing = db.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
        if existing:
            return JSONResponse({"error": "slug already exists"}, status_code=409)
        cur = db.execute(
            "INSERT INTO projects (name, slug, description, sort_order) VALUES (?, ?, ?, ?)",
            (name, slug, description, data.get("sort_order", 0))
        )
        db.commit()
        return {"id": cur.lastrowid, "name": name, "slug": slug}


@app.patch("/api/admin/projects/{project_id:int}")
async def admin_update_project(project_id: int, data: dict = Body(...), user_payload=Depends(require_admin)):
    with get_db() as db:
        proj = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj:
            return JSONResponse({"error": "project not found"}, status_code=404)
        updates = []
        params = []
        if "name" in data:
            updates.append("name = ?")
            params.append(str(data["name"]).strip())
        if "slug" in data:
            updates.append("slug = ?")
            params.append(str(data["slug"]).strip().lower())
        if "description" in data:
            updates.append("description = ?")
            params.append(str(data["description"]).strip())
        if "sort_order" in data:
            updates.append("sort_order = ?")
            params.append(int(data["sort_order"]))
        if "is_active" in data:
            updates.append("is_active = ?")
            params.append(1 if data["is_active"] else 0)
        if updates:
            params.append(project_id)
            db.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = ?", params)
            db.commit()
        return {"ok": True}


@app.delete("/api/admin/projects/{project_id:int}")
async def admin_delete_project(project_id: int, user_payload=Depends(require_admin)):
    with get_db() as db:
        # Cascade delete all data for this project
        db.execute("DELETE FROM videos WHERE project_id = ?", (project_id,))
        db.execute("""DELETE FROM episodes WHERE season_id IN (
            SELECT s.id FROM seasons s JOIN series se ON s.series_id = se.id WHERE se.project_id = ?
        )""", (project_id,))
        db.execute("""DELETE FROM seasons WHERE series_id IN (
            SELECT id FROM series WHERE project_id = ?
        )""", (project_id,))
        db.execute("DELETE FROM series WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM urls WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM categories WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM favorites WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM history WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM suspense WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM user_projects WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        db.commit()
        return {"ok": True}


# -- Admin Settings (global: data source, proxy) --

SETTING_KEYS = ("repo_url", "token", "proxy", "site_name", "workflow_file", "data_path", "private_allowlist", "doh_url", "hosts_map", "proxy_sites", "proxy_rules")
# Integer-boolean settings (stored as 0/1, never as "True"/"False" strings).
SETTING_BOOL_KEYS = ("proxy_pull_default", "proxy_play_default")


@app.get("/api/admin/settings")
async def admin_get_settings(user_payload=Depends(require_admin)):
    return load_settings()


@app.put("/api/admin/settings")
async def admin_put_settings(data: dict = Body(...), user_payload=Depends(require_admin)):
    current = load_settings()
    for key in SETTING_KEYS:
        if key in data:
            current[key] = str(data.get(key) or "").strip()
    for key in SETTING_BOOL_KEYS:
        if key in data:
            current[key] = 1 if data.get(key) else 0
    if "proxy_sources" in data and isinstance(data.get("proxy_sources"), dict):
        sources = dict(current.get("proxy_sources") or {})
        with get_db() as db:
            for k, v in data["proxy_sources"].items():
                try:
                    cid = int(k)
                    if isinstance(v, dict):
                        pull_val = 1 if v.get("pull") else 0
                        play_val = 1 if v.get("play") else 0
                        db.execute(
                            "UPDATE auto_update_configs SET proxy_pull = ?, proxy_play = ?, use_proxy = ? WHERE id = ?",
                            (pull_val, play_val, pull_val, cid)
                        )
                        sources[k] = {"pull": pull_val, "play": play_val}
                    else:
                        val = 1 if v else 0
                        db.execute(
                            "UPDATE auto_update_configs SET proxy_pull = ?, use_proxy = ? WHERE id = ?",
                            (val, val, cid)
                        )
                        sources[k] = val
                except (TypeError, ValueError):
                    pass
            db.commit()
        current["proxy_sources"] = sources
    save_settings(current)
    return {"ok": True, "settings": load_settings()}


@app.post("/api/proxy/test")
async def test_proxy(data: dict = Body(...), user_payload=Depends(require_admin)):
    """Proxy connectivity check. Accepts an explicit proxy address; when
    omitted the configured global proxy is tested. An optional target URL
    (default: the public generate_204 endpoint) is fetched through the
    proxy; the SSRF guard applies to the target as well."""
    proxy = str(data.get("proxy") or "").strip()
    if not proxy:
        proxy = load_settings().get("proxy", "")
    if not proxy:
        return {"ok": False, "error": "未配置代理地址"}
    target = str(data.get("target") or "").strip() or \
        "https://www.google.com/generate_204"
    if not target.lower().startswith(("http://", "https://")):
        return {"ok": False, "error": "target 必须是 http(s) 地址"}
    try:
        if _is_private_url(target):
            return {"ok": False, "error": "target 未通过安全校验"}
    except Exception:
        return {"ok": False, "error": "target 未通过安全校验"}
    proxies = {"http": proxy, "https": proxy}
    last_err = ""
    probe_targets = [target]
    if not (data.get("target") or "").strip() and target == "https://www.google.com/generate_204":
        probe_targets.append("https://cp.cloudflare.com/generate_204")
    for probe_url in probe_targets:
        try:
            r = requests.get(probe_url,
                             proxies=proxies, timeout=10, verify=_REQUESTS_VERIFY,
                             headers={"User-Agent": config.DEFAULT_UA})
            if r.status_code in (200, 204):
                return {"ok": True}
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
    return {"ok": False, "error": last_err}


def _register_or_update_auto_config(
    db,
    name: str,
    source_type: str,
    source_path: str,
    use_proxy: int = 0,
    last_status: str = "success",
    last_result: str = "",
    proxy_pull: int | None = None,
    proxy_play: int | None = None,
) -> int:
    """Ensure that an imported URL or local path is registered in auto_update_configs."""
    # Status vocabulary is shared with run_auto_update: success | partial |
    # failed | pending. Older rows may still carry the legacy value "ok",
    # which readers must treat as success.
    if last_status == "ok":
        last_status = "success"
    # Tri-state persistence: None = follow (legacy use_proxy, then global
    # default). The legacy use_proxy column mirrors the pull choice for
    # old readers.
    legacy_proxy = use_proxy
    if proxy_pull is not None:
        legacy_proxy = proxy_pull
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = db.execute(
        "SELECT id, name FROM auto_update_configs WHERE source_path = ?", (source_path,)
    ).fetchone()
    if existing:
        sets = "last_run_at = ?, last_status = ?, last_result = ?, updated_at = ?"
        params: list = [now_iso, last_status, last_result, now_iso]
        if proxy_pull is not None:
            sets += ", proxy_pull = ?, use_proxy = ?"
            params += [proxy_pull, legacy_proxy]
        if proxy_play is not None:
            sets += ", proxy_play = ?"
            params.append(proxy_play)
        params.append(existing["id"])
        db.execute(
            f"UPDATE auto_update_configs SET {sets} WHERE id = ?",
            params,
        )
        return existing["id"]

    is_remote = 1 if source_path.lower().startswith(("http://", "https://")) else 0
    base_name = name or ("直播源" if source_type == "live" else "影视库")
    cand_name = base_name
    idx = 2
    while db.execute("SELECT id FROM auto_update_configs WHERE name = ?", (cand_name,)).fetchone():
        cand_name = f"{base_name} ({idx})"
        idx += 1

    cur = db.execute(
        """INSERT INTO auto_update_configs
           (name, source_type, source_path, is_remote, use_proxy, proxy_pull, proxy_play,
            update_interval, last_run_at, next_run_at, last_status, last_result, fail_count, is_active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 3600, ?, ?, ?, ?, 0, 1, ?, ?)""",
        (cand_name, source_type, source_path, is_remote, legacy_proxy,
         proxy_pull, proxy_play, now_iso, now_iso, last_status, last_result, now_iso, now_iso),
    )
    return cur.lastrowid


def _tri_proxy_value(data: dict, *keys: str) -> int | None:
    """Parse a tri-state proxy switch from a request payload: 1/True → 1,
    0/False → 0, missing/"" → None (follow global default). Accepts legacy
    key aliases (e.g. use_proxy) as fallbacks."""
    for k in keys:
        if k in data and data.get(k) is not None and data.get(k) != "":
            return 1 if data.get(k) in (1, True, "1", "true", "True") else 0
    return None


@app.post("/api/import/remote")
async def api_import_remote(data: dict = Body(...), user_payload=Depends(require_admin)):
    """Manual remote import: parses any of the five product address shapes
    (plus HTML directory pages) and imports the fetched JSON files. Shares
    the address parser and proxy mechanism with scheduled auto-update."""
    url = str(data.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url 必填")
    ok, reason = validate_update_url(url, allow_private=True)
    if not ok:
        raise HTTPException(status_code=400, detail=f"地址未通过安全校验: {reason}")
    data_path = str(data.get("data_path") or "").strip()
    # Pull channel tri-state: explicit proxy_pull wins, legacy use_proxy
    # as fallback, None = follow global default.
    pull_tri = _tri_proxy_value(data, "proxy_pull", "use_proxy")
    proxies = _update_proxies({"proxy_pull": pull_tri})
    settings = load_settings()
    token = settings.get("token", "")
    if not data_path:
        data_path = settings.get("data_path", "")

    import_result: dict = {"scanned": 0, "videos_added": 0, "videos_updated": 0,
                           "live_channels": 0, "live_sources": 0, "errors": []}
    with tempfile.TemporaryDirectory() as tmp:
        fetched = await asyncio.to_thread(
            _fetch_remote_to_dir, url, Path(tmp), proxies,
            token=token, data_path=data_path)
        if not fetched.get("ok"):
            raise HTTPException(status_code=502, detail=f"获取失败: {fetched.get('error', '未知错误')}")
        import_result["scanned"] = fetched.get("files", 0)
        sub_result = await asyncio.to_thread(scan_local_update, {
            "source_path": str(tmp),
            "source_type": data.get("source_type") or None,
        })
        for key in ("videos_added", "videos_updated", "live_channels", "live_sources"):
            import_result[key] += sub_result.get(key, 0)
        if sub_result.get("batch_ids"):
            import_result.setdefault("batch_ids", []).extend(sub_result["batch_ids"])
        import_result["errors"].extend(sub_result.get("errors", []))
    import_result["method"] = fetched.get("method", "")
    import_result["ok"] = not import_result["errors"]

    if import_result["ok"]:
        summary = f"新增: {import_result['videos_added']}, 更新: {import_result['videos_updated']}, 频道: {import_result['live_channels']}, 源: {import_result['live_sources']}"
        stem = Path(urllib.parse.urlsplit(url).path).stem or "远端数据源"
        st = "live" if import_result["live_channels"] > 0 and import_result["videos_added"] == 0 else "video"
        with get_db() as db:
            cid = _register_or_update_auto_config(
                db, stem, st, url,
                use_proxy=pull_tri if pull_tri is not None else 0,
                last_status="success", last_result=summary,
                proxy_pull=pull_tri,
                proxy_play=_tri_proxy_value(data, "proxy_play"),
            )
            if st == "live":
                db.execute("UPDATE live_channels SET config_id = ? WHERE (config_id IS NULL OR config_id = 0)", (cid,))
            elif import_result.get("batch_ids"):
                for b in import_result["batch_ids"]:
                    db.execute("UPDATE videos SET config_id = ? WHERE import_batch_id = ? AND (config_id IS NULL OR config_id = 0)", (cid, b))
                    db.execute("UPDATE series SET config_id = ? WHERE import_batch_id = ? AND (config_id IS NULL OR config_id = 0)", (cid, b))
            db.commit()
        import_result["config_id"] = cid

    return import_result


@app.post("/api/import/remote/preview")
async def api_import_remote_preview(data: dict = Body(...), user_payload=Depends(require_admin)):
    """Dry-run preview for manual remote import (admin only).

    Inputs match POST /api/import/remote (url / data_path / use_proxy).
    The remote content is fetched into a temp directory and analyzed
    read-only: address type, discovered JSON files, volume grouping,
    per-group project resolution (JSON project field first, file-name
    rule as fallback) and a live-channel estimate. Nothing is written
    to the database and no import is triggered."""
    url = str(data.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url 必填")
    ok, reason = validate_update_url(url, allow_private=True)
    if not ok:
        raise HTTPException(status_code=400, detail=f"地址未通过安全校验: {reason}")
    data_path = str(data.get("data_path") or "").strip()
    proxies = _update_proxies(None if data.get("use_proxy") is None
                              else {"use_proxy": data.get("use_proxy")})
    settings = load_settings()
    token = settings.get("token", "")
    if not data_path:
        data_path = settings.get("data_path", "")

    address_type = parse_resource_target(url).get("type", "")
    with tempfile.TemporaryDirectory() as tmp:
        fetched = _fetch_remote_to_dir(url, Path(tmp), proxies,
                                       token=token, data_path=data_path)
        if not fetched.get("ok"):
            raise HTTPException(status_code=502, detail=f"获取失败: {fetched.get('error', '未知错误')}")
        preview = _preview_remote_import(Path(tmp))
        fetch_method = fetched.get("method", "")
    preview["url"] = url
    preview["address_type"] = address_type
    preview["fetch_method"] = fetch_method
    return preview


def _preview_remote_import(files_dir: Path) -> dict:
    """Read-only analysis of fetched JSON files for the preview endpoint.

    Never touches the database: project rows are looked up by slug only,
    never created. Volume grouping and project resolution mirror the
    execution path (scan_local_update) so the preview matches what an
    actual import would do."""
    files_meta: dict[str, dict] = {}
    video_files: list[Path] = []
    errors: list[str] = []

    for f in _scan_json_files(str(files_dir)):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            errors.append(f"{f.name}: JSON 解析失败: {e}")
            files_meta[f.name] = {"name": f.name, "type": "error",
                                  "error": f"JSON 解析失败: {e}"}
            continue
        json_type = detect_json_type(data)
        if json_type == "unknown":
            errors.append(f"{f.name}: 无法识别的 JSON 格式")
            files_meta[f.name] = {"name": f.name, "type": "error",
                                  "error": "无法识别的 JSON 格式"}
            continue
        if json_type == "video":
            video_files.append(f)
            files_meta[f.name] = {"name": f.name, "type": "video",
                                  "items": len(data.get("items") or []),
                                  "error": None}
        else:
            channels = data.get("channels") or []
            sources = sum(len(_normalize_live_sources(ch)) for ch in channels
                          if isinstance(ch, dict))
            files_meta[f.name] = {"name": f.name, "type": "live",
                                  "region": str(data.get("region") or ""),
                                  "channels": len(channels),
                                  "sources": sources, "error": None}

    with get_db() as db:
        groups = []
        for base_name, vol_list in _group_volumes(video_files).items():
            names = [p.name for _, p in vol_list]
            merged_items = sum(files_meta[p.name].get("items", 0) for _, p in vol_list)
            json_project = None
            for _, p in vol_list:
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        prj = json.load(fh).get("project")
                except Exception:
                    prj = None
                if isinstance(prj, dict) and prj:
                    json_project = prj
                    break
            if json_project:
                slug = str(json_project.get("slug") or base_name)
                name = str(json_project.get("name") or base_name)
                source = "json"
            else:
                slug = base_name
                name = base_name
                source = "filename_rule"
            existing = db.execute(
                "SELECT id, name FROM projects WHERE slug = ?", (slug,)
            ).fetchone()
            if existing:
                project = {"source": source, "slug": slug, "name": existing["name"],
                           "exists": True, "project_id": existing["id"]}
            else:
                project = {"source": source, "slug": slug, "name": name,
                           "exists": False, "project_id": None}
            for n in names:
                files_meta[n]["volume_group"] = base_name
                files_meta[n]["project"] = project
            groups.append({"base_name": base_name, "volume_count": len(names),
                           "volumes": names, "items": merged_items,
                           "project": project})

    live_metas = [m for m in files_meta.values() if m["type"] == "live"]
    return {
        "ok": not errors,
        "scanned": len(files_meta),
        "files": sorted(files_meta.values(), key=lambda m: m["name"]),
        "groups": groups,
        "live": {"file_count": len(live_metas),
                 "channels": sum(m.get("channels", 0) for m in live_metas),
                 "sources": sum(m.get("sources", 0) for m in live_metas)},
        "errors": errors,
    }


# -- Auto Update --

def _private_allowlist_entries() -> list[str]:
    """Parse the admin-curated intranet allowlist from settings."""
    try:
        raw = str(load_settings().get("private_allowlist") or "")
    except Exception:
        return []
    return [e.strip() for e in re.split(r"[,;\n]+", raw) if e.strip()]


def _host_in_private_allowlist(host: str | None) -> bool:
    """True when host matches an allowlist entry (exact hostname/IP or CIDR)."""
    if not host:
        return False
    host = host.lower()
    for entry in _private_allowlist_entries():
        el = entry.lower()
        try:
            if "/" in el:
                if ipaddress.ip_address(host) in ipaddress.ip_network(el, strict=False):
                    return True
                continue
        except ValueError:
            pass
        if host == el:
            return True
    return False


def validate_update_url(url: str, allow_private: bool = False) -> tuple[bool, str]:
    """SSRF validation for remote update addresses (design 3.1.3).

    Rules: http/https only; host must be present; private/loopback/
    reserved/multicast addresses (literal or DNS-resolved) are rejected
    via the shared SSRF private-address check — unless allow_private is
    set or the host matches the admin-curated private allowlist (LAN
    IPTV/NAS sources configured by an administrator).
    """
    if not isinstance(url, str) or not url.strip():
        return False, "URL 不能为空"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "仅允许 http/https 协议"
    if not parsed.hostname:
        return False, "URL 缺少主机名"
    if _is_private_url(url):
        if allow_private or _host_in_private_allowlist(parsed.hostname):
            return True, ""
        return False, "禁止访问内网/回环/保留地址"
    return True, ""


def _empty_update_result() -> dict:
    return {
        "scanned": 0,
        "videos_added": 0,
        "videos_updated": 0,
        "live_channels": 0,
        "live_sources": 0,
        "errors": [],
    }


# -- Remote address parsing (five shapes; shared by manual remote import
#    and auto-update fetch) --
#
# Shapes (port of the legacy parser, semantics unchanged):
# - github_tree:      https://github.com/owner/repo/tree/branch/path
# - github_blob:      https://github.com/owner/repo/blob/branch/path/file.json
# - direct_json_url:  any http(s) URL ending in .json
# - github_repo:      https://github.com/owner/repo(.git)
# - git_repo:         any other git repository URL

def parse_resource_target(raw_url: str) -> dict:
    raw_url = (raw_url or "").strip()
    if not raw_url:
        return {"type": "empty"}

    m = re.match(r'^(https?://[^/]+)/([^/]+)/([^/]+)/(tree|blob)/([^/]+)(?:/(.*))?$', raw_url)
    if m:
        scheme_host, owner, repo_name, kind, branch, subpath = m.groups()
        repo_name = repo_name.rstrip('.git')
        subpath = (subpath or '').strip('/')
        return {
            "type": "github_" + kind,
            "scheme_host": scheme_host,
            "owner": owner,
            "repo": repo_name,
            "branch": branch,
            "subpath": subpath,
            "clean_repo": f"{scheme_host}/{owner}/{repo_name}.git",
        }

    if re.match(r'^https?://.+/[^/]+\.json(?:\?.*)?$', raw_url, re.I):
        return {"type": "direct_json_url", "url": raw_url, "clean_repo": raw_url}

    m_gh = re.match(r'^(https?://[^/]+)/([^/]+)/([^/]+?)(?:\.git)?/?$', raw_url)
    if m_gh and 'github.com' in m_gh.group(1):
        scheme_host, owner, repo_name = m_gh.groups()
        return {
            "type": "github_repo",
            "scheme_host": scheme_host,
            "owner": owner,
            "repo": repo_name,
            "branch": "",
            "subpath": "",
            "clean_repo": f"{scheme_host}/{owner}/{repo_name}.git",
        }

    return {"type": "git_repo", "clean_repo": raw_url.rstrip('/')}


def parse_github_input_url(raw_url: str) -> tuple[str, str, str]:
    """Compat helper: returns (clean_repo_url, branch, subpath)."""
    t = parse_resource_target(raw_url)
    if t["type"] in ("github_tree", "github_blob"):
        return t["clean_repo"], t.get("branch", ""), t.get("subpath", "")
    if t["type"] == "github_repo":
        return t["clean_repo"], "", ""
    return t.get("clean_repo", raw_url), "", ""


def _rglob_depth_limited(root: Path, pattern: str, max_depth: int = 4):
    """Depth-limited recursive glob; skips dependency/VCS directories."""
    if max_depth <= 0:
        return
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for item in entries:
        if item.is_dir():
            if item.name not in (".git", "node_modules", "dist", "cache", "downloads", "bin", "db"):
                yield from _rglob_depth_limited(item, pattern, max_depth - 1)
        elif item.match(pattern):
            yield item


def _probe_media_json_in_dir(root: Path, preferred_path: str = "") -> list[Path]:
    """Find media JSON files under root.

    1. If preferred_path is set (file or directory), take it when valid.
    2. Otherwise depth-limited recursive scan; every JSON that detect_json_type
       recognizes (video or live) is collected, sorted by detected item count.
    Returns [] when nothing valid is found.
    """
    found: dict[Path, int] = {}

    def _check(p: Path):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return
        if detect_json_type(data) != "unknown":
            n = len(data.get("items", [])) if isinstance(data, dict) else (
                len(data) if isinstance(data, list) else 0)
            found[p] = max(n, 1)

    pref = (preferred_path or "").strip().lstrip("/")
    if pref:
        target = root / pref
        if target.is_file():
            _check(target)
        elif target.is_dir():
            for f in sorted(target.glob("**/*.json")):
                _check(f)
        if found:
            return sorted(found, key=lambda p: -found[p])

    for cand in _rglob_depth_limited(root, "*.json", max_depth=4):
        parts = cand.parts
        if any(x in parts for x in (".git", "node_modules", "dist", "cache", "bin", "db")):
            continue
        _check(cand)
    return sorted(found, key=lambda p: -found[p])


def _proxy_rules(settings: dict | None = None) -> dict:
    """代理条目（两层）：subs=订阅源条目（同步/其直播播放走代理），
    plays=播放源条目（URL 关键词，命中的服务端请求走代理）。
    旧版 proxy_sources / proxy_sites 在 load_settings 中一次性迁移。"""
    s = settings if settings is not None else load_settings()
    raw = s.get("proxy_rules") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {"subs": data.get("subs") or [], "plays": data.get("plays") or []}


def _sub_proxy_enabled(config: dict | None, settings: dict) -> bool:
    """订阅源条目匹配：按配置 id（优先）或名称包含。"""
    rules = _proxy_rules(settings)
    subs = rules.get("subs") or []
    if not subs or not config:
        return False
    cid = str(config.get("id") or "")
    name = (config.get("name") or "").strip()
    for s in subs:
        sid = str(s.get("id") or "")
        sname = (s.get("name") or "").strip()
        if cid and sid and sid == cid:
            return True
        if sname and name and (sname == name or sname in name):
            return True
    return False


def _proxy_pull_enabled(config: dict | None = None, settings: dict | None = None) -> bool:
    """拉取走代理？= 命中订阅源条目，或导入表单的显式开关（列/字段）被勾选。"""
    s = settings if settings is not None else load_settings()
    if _sub_proxy_enabled(config, s):
        return True
    cfg = config or {}
    v = cfg.get("proxy_pull", None)
    if v is None:
        v = cfg.get("use_proxy", None)
    return bool(v)


def _proxy_play_enabled(config: dict | None = None, settings: dict | None = None) -> bool:
    """播放（直播中转等）走代理？= 命中订阅源条目。"""
    s = settings if settings is not None else load_settings()
    return _sub_proxy_enabled(config, s)


def _update_proxies(config: dict | None = None) -> dict | None:
    """Resolve the proxy for a remote PULL: a global proxy (admin settings)
    is only used when the source opted in via proxy_pull (or legacy
    use_proxy / global proxy_pull_default). Returns a requests proxies
    dict or None for direct connection."""
    settings = load_settings()
    proxy = settings.get("proxy", "")
    if not proxy:
        return None
    if config is not None and not _proxy_pull_enabled(config, settings):
        return None
    return {"http": proxy, "https": proxy}


def _play_proxies(config: dict | None = None) -> dict | None:
    """Resolve the proxy for stream PLAY relaying: global proxy is only
    used when the source opted in via proxy_play (or legacy use_proxy /
    global proxy_play_default)."""
    settings = load_settings()
    proxy = settings.get("proxy", "")
    if not proxy:
        return None
    if config is not None and not _proxy_play_enabled(config, settings):
        return None
    return {"http": proxy, "https": proxy}


def _git_clone_shallow(repo_url: str, dest: Path, branch: str = "",
                       proxies: dict | None = None, token: str = "") -> tuple[bool, str]:
    """Shallow clone repo_url into dest (3 attempts). Proxy is applied via
    environment variables; the token, when present, is embedded in the URL."""
    repo = repo_url
    if token:
        parsed = urllib.parse.urlparse(repo)
        repo = f"{parsed.scheme}://{token}@{parsed.netloc}{parsed.path}"
    env = os.environ.copy()
    if proxies:
        env["HTTP_PROXY"] = proxies.get("http", "")
        env["HTTPS_PROXY"] = proxies.get("https", "")
    clone_cmd = ["git", "-c", "http.postBuffer=524288000", "-c", "http.lowSpeedLimit=0",
                 "clone", "--depth", "1"]
    if branch:
        clone_cmd.extend(["-b", branch])
    clone_cmd.extend([repo, str(dest)])
    last_err = ""
    for attempt in range(3):
        try:
            r = subprocess.run(clone_cmd, capture_output=True, text=True,
                               timeout=180, env=env)
        except subprocess.TimeoutExpired:
            last_err = "clone 超时"
            r = None
        if r is not None and r.returncode == 0:
            return True, ""
        if r is not None:
            last_err = r.stderr[:500]
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        if attempt < 2:
            time.sleep(2)
    return False, last_err


def _copy_probed_json(src_files: list[Path], dest_dir: Path) -> int:
    """Copy probed JSON files into dest_dir (flat). Returns the copy count."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    used_names: set[str] = set()
    for src in src_files:
        name = src.name
        stem, suffix = os.path.splitext(name)
        n = 1
        while name in used_names:
            name = f"{stem}-{n}{suffix}"
            n += 1
        used_names.add(name)
        shutil.copy2(src, dest_dir / name)
        copied += 1
    return copied


def _fetch_remote_to_dir(url: str, dest_dir: Path, proxies: dict | None,
                         token: str = "", data_path: str = "") -> dict:
    """Fetch one remote product address into dest_dir.

    Shared by POST /api/import/remote (manual import) and fetch_remote_update
    (scheduled auto-update), so both paths share address parsing and proxying.
    Every constructed URL passes validate_update_url (SSRF guard is never
    bypassed, with or without proxy).

    Returns {"ok": bool, "method": str, "files": int, "error": str}.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = parse_resource_target(url)
    ttype = target.get("type", "")
    headers = {"User-Agent": config.DEFAULT_UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def _get(u: str, extra_headers: dict | None = None, timeout: int = 0):
        ok, reason = validate_update_url(u, allow_private=True)
        if not ok:
            raise RuntimeError(f"SSRF 校验拒绝: {u} ({reason})")
        h = dict(headers)
        if extra_headers:
            h.update(extra_headers)
        return _requests_get_safe_redirects(
            u, allow_private=True, timeout=timeout or config_module.AUTO_UPDATE_FETCH_TIMEOUT,
            verify=_REQUESTS_VERIFY, headers=h, proxies=proxies,
        )

    # 1) Direct JSON link: single fetch, no clone needed
    if ttype == "direct_json_url":
        try:
            r = _get(url)
            r.raise_for_status()
            data = json.loads(r.content)
        except Exception as e:
            return {"ok": False, "error": f"直链下载或解析失败: {e}"}
        if detect_json_type(data) == "unknown":
            return {"ok": False, "error": "直链内容不是可识别的媒体 JSON"}
        name = os.path.basename(urllib.parse.urlparse(url).path) or "remote.json"
        (dest_dir / name).write_bytes(r.content)
        return {"ok": True, "method": "direct_url", "files": 1, "error": ""}

    # 2) GitHub web page directory / single file (github.com only): precise
    #    pull via raw/contents API, no clone
    clone_fallback_error = ""
    is_github = target.get("scheme_host", "").split("//")[-1] in ("github.com", "www.github.com")
    subpath = (target.get("subpath") or "").strip("/")
    if is_github and ttype in ("github_tree", "github_blob"):
        branch = target.get("branch") or "main"
        if not subpath and ttype == "github_blob":
            return {"ok": False, "error": "blob 地址缺少文件路径"}
        try:
            if subpath.endswith(".json"):
                raw_url = f"https://raw.githubusercontent.com/{target['owner']}/{target['repo']}/{branch}/{subpath}"
                r = _get(raw_url)
                if r.status_code != 200:
                    # raw URL missed (private repo or renamed default branch):
                    # fall back to the contents API
                    api_url = f"https://api.github.com/repos/{target['owner']}/{target['repo']}/contents/{subpath}"
                    gh_headers = {"Accept": "application/vnd.github.v3.raw"}
                    if token:
                        gh_headers["Authorization"] = f"Bearer {token}"
                    r = _get(api_url, gh_headers)
                if r.status_code != 200:
                    return {"ok": False, "error": f"指定文件下载失败 (HTTP {r.status_code}): {subpath}"}
                data = json.loads(r.content)
                if detect_json_type(data) == "unknown":
                    return {"ok": False, "error": f"文件 {subpath} 不是可识别的媒体 JSON"}
                name = subpath.split("/")[-1]
                (dest_dir / name).write_bytes(r.content)
                return {"ok": True, "method": "github_blob", "files": 1, "error": ""}
            api_url = f"https://api.github.com/repos/{target['owner']}/{target['repo']}/contents/{subpath}"
            gh_headers = {"Accept": "application/vnd.github.v3+json"}
            if token:
                gh_headers["Authorization"] = f"Bearer {token}"
            r = _get(api_url, gh_headers)
            if r.status_code == 404:
                return {"ok": False, "error": f"未在仓库中找到指定目录: {subpath}"}
            items = []
            if r.status_code != 200:
                # 403 限流等：不在此终止，落到下方 git clone 回退
                # （git 协议不受 API 匿名限额影响，匿名亦可 clone 公开仓库）
                clone_fallback_error = f"查询目录失败 (HTTP {r.status_code}): {r.text[:160]}"
            else:
                items = r.json()
            if isinstance(items, dict) and items.get("type") == "file":
                items = [items]
            if not isinstance(items, list):
                return {"ok": False, "error": f"目录 {subpath} 响应格式不正确"}
            got = 0
            for it in items:
                if it.get("type") != "file" or not str(it.get("name", "")).lower().endswith(".json"):
                    continue
                dl_url = it.get("download_url") or (
                    f"https://raw.githubusercontent.com/{target['owner']}/{target['repo']}/{branch}/{it.get('path', '')}")
                # raw 直链失败（国内常不可达/断流）自动回退 contents API；
                # 每个候选都用断点续传下载，对抗不稳定链路的大文件断流
                gh_raw_headers = {"Accept": "application/vnd.github.v3.raw"}
                if token:
                    gh_raw_headers["Authorization"] = f"Bearer {token}"
                candidates = [
                    (dl_url, headers),
                    (f"{api_url}/{it.get('path', '')}", gh_raw_headers),
                ]
                dest_file = dest_dir / it["name"]
                got_file = False
                last_dl_err = ""
                # 候选链路：先按当前代理设置，直连全部失败且全局代理可用时自动换代理重试
                attempts_ = [(candidates, proxies)]
                if not proxies:
                    _p_url = load_settings().get("proxy", "").strip()
                    if _p_url:
                        attempts_.append((candidates, {"http": _p_url, "https": _p_url}))
                for cand_list, px in attempts_:
                    for cand_url, cand_headers in cand_list:
                        dest_file.unlink(missing_ok=True)
                        ok_dl, err_dl = _download_stream_resumable(
                            cand_url, {**headers, **cand_headers}, dest_file, proxies=px)
                        if not ok_dl:
                            last_dl_err = err_dl
                            continue
                        try:
                            data = json.loads(dest_file.read_bytes())
                        except Exception:
                            dest_file.unlink(missing_ok=True)
                            last_dl_err = "下载内容不是合法 JSON"
                            continue
                        if detect_json_type(data) == "unknown":
                            dest_file.unlink(missing_ok=True)
                            last_dl_err = f"{it['name']} 不是可识别的媒体 JSON"
                            continue
                        got_file = True
                        got += 1
                        break
                    if got_file:
                        break
            if not got:
                # API 列目录失败（限流等）→ 落到 git clone 回退；
                # 确实列到了目录但内容无效 → 直接报错
                if not clone_fallback_error:
                    detail = f"（最后错误: {last_dl_err}）" if last_dl_err else ""
                    return {"ok": False, "error": f"目录 {subpath} 下未找到有效的媒体 JSON{detail}"}
            else:
                return {"ok": True, "method": "github_tree", "files": got, "error": ""}
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"直接获取失败: {e}"}

    # 2.5) HTML directory index (self-hosted server layout, e.g. a plain
    #      directory listing with .json links). Tried before the git fallback
    #      because a directory URL is not parseable as any of the five shapes.
    #      Existing local directories (offline git fixtures) skip straight
    #      to the clone step below instead of the HTTP probe.
    if ttype in ("direct_json_url", "git_repo") and not os.path.isdir(url):
        try:
            r = _get(url)
            content_type = (r.headers.get("content-type") or "").lower()
            body = r.text or ""
            looks_html = "html" in content_type or body.lstrip()[:1] == "<"
            if r.status_code == 200 and looks_html:
                links = _extract_json_links_from_html(body, url)
                got = 0
                for link in links:
                    try:
                        r_dl = _get(link)
                        if r_dl.status_code != 200:
                            continue
                        data = json.loads(r_dl.content)
                        if detect_json_type(data) == "unknown":
                            continue
                        name = os.path.basename(urllib.parse.urlparse(link).path) or "remote.json"
                        (dest_dir / name).write_bytes(r_dl.content)
                        got += 1
                    except Exception:
                        continue
                if got:
                    return {"ok": True, "method": "directory_index", "files": got, "error": ""}
                return {"ok": False, "error": "目录页中未找到有效的媒体 JSON 链接"}
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}
        except Exception:
            pass  # not an HTML directory page; fall through to git clone

    # 3) Git repositories (github_repo / git_repo): shallow clone then deep
    #    probe for media JSONs. data_path (per-call or global setting) narrows
    #    the probe root; when empty the whole working tree is probed.
    dest = dest_dir / "_clone"
    ok, err = _git_clone_shallow(target.get("clean_repo", url), dest,
                                 branch=target.get("branch", ""),
                                 proxies=proxies, token=token)
    if not ok and not proxies:
        # 直连 clone 失败时自动换全局代理重试一次
        _p_url = load_settings().get("proxy", "").strip()
        if _p_url:
            shutil.rmtree(dest, ignore_errors=True)
            ok, err = _git_clone_shallow(target.get("clean_repo", url), dest,
                                         branch=target.get("branch", ""),
                                         proxies={"http": _p_url, "https": _p_url}, token=token)
    if not ok:
        return {"ok": False, "error": f"git clone 失败: {err}"}
    pref = data_path or ""
    probe_root = dest / pref.strip("/") if pref.strip("/") else dest
    if not probe_root.exists() or not probe_root.is_dir():
        probe_root = dest
    files = _probe_media_json_in_dir(probe_root, "")
    if not files and probe_root != dest:
        files = _probe_media_json_in_dir(dest, "")
    if not files:
        return {"ok": False, "error": "克隆成功，但未探测到可识别的媒体 JSON 文件"}
    copied = _copy_probed_json(files, dest_dir)
    shutil.rmtree(dest, ignore_errors=True)
    return {"ok": True, "method": "git_clone", "files": copied, "error": ""}


def scan_local_update(config: dict) -> dict:
    """Scan a local directory for auto-update (design 3.3.1).

    Every JSON file is type-detected. Video JSONs go through volume
    grouping + project-field-priority resolution and INCREMENTAL import
    (no pre-clear; upsert preserves first_imported_at, so only new items
    enter recent updates). Live JSONs are fully replaced per region.
    config['source_type'] ('video' | 'live') filters which kind is
    processed; None processes both.
    """
    result = _empty_update_result()
    dir_path = config.get("source_path") or ""
    want_type = config.get("source_type") or None

    p = Path(dir_path)
    if not p.exists() or not p.is_dir():
        result["errors"].append(f"目录不存在或不可读: {dir_path}")
        return result

    files = _scan_json_files(dir_path)
    video_files: list[Path] = []
    live_entries: list[tuple[Path, dict]] = []

    for f in files:
        result["scanned"] += 1
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            result["errors"].append(f"{f.name}: JSON 解析失败: {e}")
            continue
        json_type = detect_json_type(data)
        if json_type == "unknown":
            result["errors"].append(f"{f.name}: 无法识别的 JSON 格式")
            continue
        if want_type and json_type != want_type:
            continue
        if json_type == "video":
            video_files.append(f)
        else:
            live_entries.append((f, data))

    groups = _group_volumes(video_files)
    with get_db() as db:
        for base_name, file_list in groups.items():
            try:
                merged, derived_base = _merge_json_volumes(file_list)
            except ValueError as e:
                result["errors"].append(f"{base_name}: {e}")
                continue
            items = merged.get("items", [])
            if not items:
                result["errors"].append(f"{base_name}: no items")
                continue
            project_id = _resolve_project_for_json(db, merged.get("project"), derived_base)
            # Incremental: no pre-clear (design 3.3.3); idempotent upsert.
            # A bangou already owned by a different project is recorded as a
            # per-group error instead of aborting the whole scan.
            try:
                stats = _import_items_to_project(db, items, project_id)
            except BangouConflictError as e:
                db.rollback()
                result["errors"].append(f"{base_name}: {e}")
                continue
            db.commit()
            result["videos_added"] += stats["new_videos"] + stats["new_series"]
            result["videos_updated"] += stats["updated_videos"] + stats["updated_series"]
            # 回填 config_id：数据源管理的数量统计依赖 videos/series.config_id
            cfg_id = config.get("id")
            if cfg_id and stats.get("batch_id"):
                db.execute("UPDATE videos SET config_id = ? WHERE import_batch_id = ? AND (config_id IS NULL OR config_id = 0)",
                           (cfg_id, stats["batch_id"]))
                db.execute("UPDATE series SET config_id = ? WHERE import_batch_id = ? AND (config_id IS NULL OR config_id = 0)",
                           (cfg_id, stats["batch_id"]))
                db.commit()
                result.setdefault("batch_ids", []).append(stats["batch_id"])

    # Live imports use their own transaction, after the video handle closes
    for f, data in live_entries:
        r = import_live_json(data, f.stem)
        if "error" in r:
            result["errors"].append(f"{f.name}: {r['error']}")
        else:
            result["live_channels"] += r["channels"]
            result["live_sources"] += r["sources"]

    return result


# 导入串行化：全量导入是「删旧插新」整库替换语义，并发执行会交错写入导致
# 数据翻倍（WAL 模式下写锁不再互斥）。所有导入入口统一经过这把可重入锁。
_import_lock = threading.RLock()


def _serialized(fn):
    def wrapper(*args, **kwargs):
        with _import_lock:
            return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


import_single_file_unified = _serialized(import_single_file_unified)
import_directory_unified = _serialized(import_directory_unified)
scan_local_update = _serialized(scan_local_update)


def _download_stream_resumable(
    url: str, headers: dict, dest_path: Path, proxies: dict | None = None,
    timeout=(10, 30), max_attempts: int = 6,
) -> tuple[bool, str]:
    """流式下载 + 断点续传。

    直连 GitHub 等不稳定链路上大文件极易中途断流（IncompleteRead），
    以 Range 从已下载字节继续，直到 Content-Length 拉满或重试次数耗尽。
    """
    last_err = ""
    for attempt in range(max_attempts):
        have = dest_path.stat().st_size if dest_path.exists() else 0
        hdr = dict(headers)
        if have:
            hdr["Range"] = f"bytes={have}-"
        try:
            r = requests.get(url, headers=hdr, stream=True, proxies=proxies,
                             timeout=timeout, verify=_REQUESTS_VERIFY)
            if r.status_code == 416:  # Range 超出：本地已完整
                return True, ""
            if r.status_code not in (200, 206):
                return False, f"HTTP {r.status_code}"
            total = r.headers.get("content-length")
            total = int(total) if total and total.isdigit() else None
            mode = "ab" if (have and r.status_code == 206) else "wb"
            start_ts = time.time()
            with open(dest_path, mode) as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        # 慢速链路快速放弃：8 秒内不足 256KB 判定不可用
                        if time.time() - start_ts > 8 and dest_path.stat().st_size - (have if mode == "ab" else 0) < 262144:
                            return False, "直连过慢（8s < 256KB），建议启用拉取代理"
            size = dest_path.stat().st_size
            if total and size < total:
                last_err = f"IncompleteRead {size}/{total}"
                time.sleep(0.8)
                continue
            return True, ""
        except Exception as e:
            last_err = str(e)
            time.sleep(0.8)
    return False, last_err


def _extract_json_links_from_html(html_text: str, base_url: str) -> list[str]:
    links = re.findall(r'href=["\']([^"\']+\.json)["\']', html_text, re.IGNORECASE)
    out: list[str] = []
    seen: set[str] = set()
    for href in links:
        full = urllib.parse.urljoin(base_url, href)
        if full not in seen:
            seen.add(full)
            out.append(full)
    return out


def fetch_remote_update(config: dict) -> dict:
    """Download remote JSON(s) and import (design 3.3.2).

    Address parsing (five shapes + HTML directory index) and proxy pulling
    are shared with the manual remote-import endpoint via _fetch_remote_to_dir.
    Remote files land in a temp directory and are processed by the same local
    scan logic, so volume merging stays shared.
    """
    result = _empty_update_result()
    url = config.get("source_path") or ""

    ok, reason = validate_update_url(url, allow_private=True)
    if not ok:
        result["errors"].append(f"URL 未通过安全校验: {reason}")
        return result

    proxies = _update_proxies(config)
    settings = load_settings()
    token = settings.get("token", "")
    data_path = settings.get("data_path", "")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        fetched = _fetch_remote_to_dir(url, tmp_dir, proxies,
                                       token=token, data_path=data_path)
        if not fetched.get("ok"):
            result["errors"].append(f"获取失败: {fetched.get('error', '未知错误')}")
            return result

        sub_config = dict(config)
        sub_config["source_path"] = str(tmp_dir)
        sub_result = scan_local_update(sub_config)
        for key in ("scanned", "videos_added", "videos_updated", "live_channels", "live_sources"):
            result[key] += sub_result.get(key, 0)
        result["errors"].extend(sub_result.get("errors", []))

    return result


def _calculate_next_run(update_interval: int, fail_count: int) -> datetime:
    """Next run time with exponential backoff capped at 4x (design 3.4.2)."""
    interval = max(int(update_interval or config.AUTO_UPDATE_DEFAULT_INTERVAL), config.AUTO_UPDATE_MIN_INTERVAL)
    multiplier = min(2 ** max(fail_count, 0), config.AUTO_UPDATE_MAX_BACKOFF_MULTIPLIER)
    return datetime.now(timezone.utc) + timedelta(seconds=interval * multiplier)


def run_auto_update(config_id: int, config: dict | None = None) -> dict:
    """Execute one auto-update run for a config: fetch/scan, import,
    compute status (success/partial/failed), apply backoff, write log.
    Never raises; failures are recorded in status/log rows."""
    start = time.monotonic()
    if config is None:
        with get_db() as db:
            row = db.execute(
                "SELECT * FROM auto_update_configs WHERE id = ?", (config_id,)
            ).fetchone()
        if not row:
            return {"error": "配置不存在"}
        config = _row_to_dict(row)

    log_errors: list[str] = []
    result: dict = {}
    try:
        if config.get("is_remote"):
            result = fetch_remote_update(config)
        else:
            result = scan_local_update(config)
    except Exception as e:
        result = _empty_update_result()
        result["errors"].append(f"执行异常: {e}")

    errors = result.get("errors", [])
    has_errors = len(errors) > 0
    imported_total = (
        result.get("videos_added", 0) + result.get("videos_updated", 0)
        + result.get("live_channels", 0) + result.get("live_sources", 0)
    )

    if has_errors and imported_total > 0:
        status = "partial"
        new_fail_count = int(config.get("fail_count") or 0) + 1
    elif has_errors:
        status = "failed"
        new_fail_count = int(config.get("fail_count") or 0) + 1
    else:
        status = "success"
        new_fail_count = 0

    now_utc = datetime.now(timezone.utc)
    next_run = _calculate_next_run(config.get("update_interval"), new_fail_count)
    duration_ms = int((time.monotonic() - start) * 1000)
    # Log message keeps only error text, not full URLs with credentials
    log_message = "; ".join(errors[:10]) if errors else ""

    with get_db() as db:
        db.execute(
            """UPDATE auto_update_configs
               SET last_run_at = ?, next_run_at = ?, last_status = ?,
                   last_result = ?, fail_count = ?, updated_at = ?
               WHERE id = ?""",
            (
                now_utc.isoformat(),
                next_run.isoformat(),
                status,
                json.dumps(result, ensure_ascii=False, default=str)[:8000],
                new_fail_count,
                now_utc.isoformat(),
                config_id,
            ),
        )
        db.execute(
            """INSERT INTO auto_update_logs
               (config_id, run_at, status, message, videos_added, videos_updated,
                live_channels, live_sources, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                config_id,
                now_utc.isoformat(),
                status,
                log_message,
                result.get("videos_added", 0),
                result.get("videos_updated", 0),
                result.get("live_channels", 0),
                result.get("live_sources", 0),
                duration_ms,
            ),
        )
        # Keep only the most recent N logs per config
        db.execute(
            """DELETE FROM auto_update_logs WHERE config_id = ? AND id NOT IN (
                SELECT id FROM auto_update_logs WHERE config_id = ?
                ORDER BY id DESC LIMIT ?
            )""",
            (config_id, config_id, config_module.AUTO_UPDATE_MAX_LOGS),
        )
        db.commit()

    return {
        "config_id": config_id,
        "status": status,
        "duration_ms": duration_ms,
        **result,
    }


_AUTO_UPDATE_RUNNING: set[int] = set()
_AUTO_UPDATE_LOCK = threading.Lock()


def scheduled_update_scan():
    """Periodic scan (design 3.2.2 simplified scheme): find enabled configs
    whose next_run_at is due and run each in its own daemon thread so one
    slow/failing config never blocks the others."""
    now = datetime.now(timezone.utc)
    try:
        with get_db() as db:
            rows = db.execute(
                """SELECT id FROM auto_update_configs
                   WHERE is_active = 1
                     AND (next_run_at IS NULL OR next_run_at <= ?)""",
                (now.isoformat(),),
            ).fetchall()
    except Exception:
        return
    for row in rows:
        config_id = row["id"]
        with _AUTO_UPDATE_LOCK:
            if config_id in _AUTO_UPDATE_RUNNING:
                continue
            _AUTO_UPDATE_RUNNING.add(config_id)

        def _run(cid=config_id):
            try:
                run_auto_update(cid)
            finally:
                with _AUTO_UPDATE_LOCK:
                    _AUTO_UPDATE_RUNNING.discard(cid)

        threading.Thread(target=_run, daemon=True, name=f"auto-update-{config_id}").start()


def live_probe_patrol():
    """Live source probe patrol (design 2.5.2): probe every active source
    whose last probe is older than LIVE_PROBE_INTERVAL_SECONDS (or never
    probed), then refresh channel aggregates from their current source."""
    from concurrent.futures import ThreadPoolExecutor

    cutoff = datetime.now() - timedelta(seconds=config.LIVE_PROBE_INTERVAL_SECONDS)
    try:
        with get_db() as db:
            sources = db.execute(
                """SELECT id, url, channel_id FROM live_channel_sources
                   WHERE is_active = 1
                     AND (last_probe_at IS NULL OR last_probe_at < ?)""",
                (cutoff.isoformat(),),
            ).fetchall()
    except Exception:
        return
    if not sources:
        return

    now_iso = datetime.now().isoformat()
    # Resolve per-channel PLAY preference so proxied sources are probed
    # through the proxy (direct probing would falsely mark them failed).
    proxy_by_channel: dict[int, dict | None] = {}
    try:
        with get_db() as db:
            cfg_rows = db.execute(
                """SELECT c.id AS channel_id, a.use_proxy AS use_proxy,
                          a.proxy_pull AS proxy_pull, a.proxy_play AS proxy_play
                   FROM live_channels c
                   LEFT JOIN auto_update_configs a ON a.id = c.config_id"""
            ).fetchall()
            forced_play_proxies = _play_proxies({"proxy_play": 1})
            for r in cfg_rows:
                try:
                    proxy_by_channel[int(r["channel_id"])] = (
                        forced_play_proxies if _proxy_play_enabled(dict(r)) else None
                    )
                except (TypeError, ValueError):
                    continue
    except Exception:
        proxy_by_channel = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        probed = list(pool.map(
            lambda s: (s["id"], s["channel_id"],
                       probe_live_url(s["url"], proxy_by_channel.get(s["channel_id"]))),
            sources,
        ))

    with get_db() as db:
        for source_id, _channel_id, result in probed:
            _apply_live_probe_result(db, source_id, result, now_iso)
        db.commit()
        # refresh aggregates for affected channels from their current source
        db.execute(
            """UPDATE live_channels SET
               last_probe_delay = (SELECT last_probe_delay FROM live_channel_sources
                                   WHERE id = live_channels.current_source_id),
               last_probe_at = ?,
               probe_status = COALESCE((SELECT probe_status FROM live_channel_sources
                                        WHERE id = live_channels.current_source_id), 'unknown')
               WHERE id IN (SELECT DISTINCT channel_id FROM live_channel_sources WHERE last_probe_at = ?)""",
            (now_iso, now_iso),
        )
        db.commit()


# -- API: Auto Update configs (admin only, design 4.2) --

@app.get("/api/admin/auto-update")
async def admin_list_auto_updates(user_payload=Depends(require_admin)):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM auto_update_configs ORDER BY id"
        ).fetchall()
        configs = []
        for r in rows:
            cd = _row_to_dict(r)
            if cd["source_type"] == "live":
                cnt = db.execute("SELECT COUNT(*) FROM live_channels WHERE config_id = ?", (cd["id"],)).fetchone()[0]
                if cnt == 0:
                    regions = db.execute("SELECT DISTINCT source_region FROM live_channels WHERE source_region != ''").fetchall()
                    matched_region = None
                    for reg in regions:
                        rname = reg["source_region"]
                        if rname and (rname in cd.get("source_path", "") or rname in cd.get("name", "")):
                            matched_region = rname
                            break
                    if matched_region:
                        cnt = db.execute("SELECT COUNT(*) FROM live_channels WHERE source_region = ?", (matched_region,)).fetchone()[0]
                        db.execute("UPDATE live_channels SET config_id = ? WHERE source_region = ? AND (config_id IS NULL OR config_id = 0)", (cd["id"], matched_region))
                cd["item_count"] = cnt
            else:
                v_cnt = db.execute("SELECT COUNT(*) FROM videos WHERE config_id = ?", (cd["id"],)).fetchone()[0]
                s_cnt = db.execute("SELECT COUNT(*) FROM series WHERE config_id = ?", (cd["id"],)).fetchone()[0]
                cd["item_count"] = v_cnt + s_cnt
            configs.append(cd)
        db.commit()
        return {"configs": configs}


@app.post("/api/admin/auto-update")
async def admin_create_auto_update(data: dict = Body(...), user_payload=Depends(require_admin)):
    name = str(data.get("name") or "").strip()
    source_type = str(data.get("source_type") or "").strip()
    source_path = str(data.get("source_path") or "").strip()
    is_remote = 1 if str(source_path).lower().startswith(("http://", "https://")) else 0
    if data.get("is_remote") is not None:
        is_remote = 1 if data.get("is_remote") else 0
    try:
        update_interval = int(data.get("update_interval") or config.AUTO_UPDATE_DEFAULT_INTERVAL)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="update_interval 必须是整数")
    update_interval = max(update_interval, config.AUTO_UPDATE_MIN_INTERVAL)

    if not name:
        raise HTTPException(status_code=400, detail="名称必填")
    if source_type not in ("video", "live"):
        raise HTTPException(status_code=400, detail="source_type 必须是 video 或 live")
    if not source_path:
        raise HTTPException(status_code=400, detail="产物地址必填")
    if is_remote:
        ok, reason = validate_update_url(source_path, allow_private=True)
        if not ok:
            raise HTTPException(status_code=400, detail=f"远程地址未通过安全校验: {reason}")
    else:
        p = Path(source_path)
        if not (p.is_dir() or p.is_file()):
            raise HTTPException(status_code=400, detail="本地路径不存在（需为存在的目录或文件）")

    # Tri-state proxy fields: 1/True → 1, 0/False → 0, missing/"" → NULL (follow default)
    proxy_pull = _tri_proxy_value(data, "proxy_pull", "use_proxy")
    proxy_play = _tri_proxy_value(data, "proxy_play")
    legacy_use_proxy = proxy_pull if proxy_pull is not None else 0

    with get_db() as db:
        dup = db.execute("SELECT id FROM auto_update_configs WHERE name = ?", (name,)).fetchone()
        if dup:
            raise HTTPException(status_code=400, detail="配置名称已存在")
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor = db.execute(
            """INSERT INTO auto_update_configs
               (name, source_type, source_path, is_remote, use_proxy, proxy_pull, proxy_play,
                update_interval, next_run_at, last_status, fail_count, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 1, ?, ?)""",
            (name, source_type, source_path, is_remote, legacy_use_proxy,
             proxy_pull, proxy_play, update_interval, now_iso, now_iso, now_iso),
        )
        db.commit()
        new_id = cursor.lastrowid
        row = db.execute("SELECT * FROM auto_update_configs WHERE id = ?", (new_id,)).fetchone()
    return {"ok": True, "config": _row_to_dict(row)}


@app.get("/api/admin/auto-update/{config_id:int}")
async def admin_get_auto_update(config_id: int, user_payload=Depends(require_admin)):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM auto_update_configs WHERE id = ?", (config_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="配置不存在")
    return _row_to_dict(row)


@app.patch("/api/admin/auto-update/{config_id:int}")
async def admin_update_auto_update(config_id: int, data: dict = Body(...), user_payload=Depends(require_admin)):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM auto_update_configs WHERE id = ?", (config_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="配置不存在")

        updates: dict = {}
        if "name" in data:
            name = str(data.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="名称不能为空")
            dup = db.execute(
                "SELECT id FROM auto_update_configs WHERE name = ? AND id != ?",
                (name, config_id),
            ).fetchone()
            if dup:
                raise HTTPException(status_code=400, detail="配置名称已存在")
            updates["name"] = name
        if "source_type" in data:
            st = str(data.get("source_type") or "").strip()
            if st not in ("video", "live"):
                raise HTTPException(status_code=400, detail="source_type 必须是 video 或 live")
            updates["source_type"] = st
        if "source_path" in data:
            sp = str(data.get("source_path") or "").strip()
            if not sp:
                raise HTTPException(status_code=400, detail="产物地址不能为空")
            is_remote = 1 if sp.lower().startswith(("http://", "https://")) else 0
            if "is_remote" in data:
                is_remote = 1 if data.get("is_remote") else 0
            if is_remote:
                ok, reason = validate_update_url(sp, allow_private=True)
                if not ok:
                    raise HTTPException(status_code=400, detail=f"远程地址未通过安全校验: {reason}")
            else:
                p = Path(sp)
                if not (p.is_dir() or p.is_file()):
                    raise HTTPException(status_code=400, detail="本地路径不存在（需为存在的目录或文件）")
            updates["source_path"] = sp
            updates["is_remote"] = is_remote
        elif "is_remote" in data:
            raise HTTPException(status_code=400, detail="is_remote 需与 source_path 一同修改")
        if "update_interval" in data:
            try:
                ui = int(data.get("update_interval"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="update_interval 必须是整数")
            updates["update_interval"] = max(ui, config.AUTO_UPDATE_MIN_INTERVAL)
        if "is_active" in data:
            updates["is_active"] = 1 if data.get("is_active") else 0
        # Tri-state proxy updates: explicit True/False sets 1/0; absent leaves
        # NULL (follow); empty string clears to NULL.
        for k in ("proxy_pull", "proxy_play"):
            if k in data:
                v = data.get(k)
                if v in (1, True, "1", "true", "True"):
                    updates[k] = 1
                elif v in (0, False, "0", "false", "False"):
                    updates[k] = 0
                elif v in ("", None):
                    updates[k] = None
        # Legacy use_proxy mirrors pull choice for backwards compatibility.
        if "use_proxy" in data:
            updates["use_proxy"] = 1 if data.get("use_proxy") else 0
            if "proxy_pull" not in data:
                updates["proxy_pull"] = updates["use_proxy"]

        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            params = list(updates.values())
            params.append(datetime.now(timezone.utc).isoformat())
            params.append(config_id)
            db.execute(
                f"UPDATE auto_update_configs SET {sets}, updated_at = ? WHERE id = ?",
                params,
            )
            # Reset next run so an edited config is picked up promptly
            db.execute(
                "UPDATE auto_update_configs SET next_run_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), config_id),
            )
            db.commit()
        updated = db.execute(
            "SELECT * FROM auto_update_configs WHERE id = ?", (config_id,)
        ).fetchone()
    return {"ok": True, "config": _row_to_dict(updated)}


@app.delete("/api/admin/auto-update/{config_id:int}")
async def admin_delete_auto_update(config_id: int, purge_data: bool = False, user_payload=Depends(require_admin)):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM auto_update_configs WHERE id = ?", (config_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="配置不存在")
        if purge_data:
            if row["source_type"] == "live":
                ch_rows = db.execute("SELECT id FROM live_channels WHERE config_id = ?", (config_id,)).fetchall()
                if not ch_rows and row["source_path"]:
                    stem = Path(urllib.parse.urlsplit(row["source_path"]).path).stem
                    ch_rows = db.execute("SELECT id FROM live_channels WHERE source_region = ? OR source_region = ?", (stem, row["name"])).fetchall()
                for ch in ch_rows:
                    db.execute("DELETE FROM live_channel_sources WHERE channel_id = ?", (ch["id"],))
                    db.execute("DELETE FROM live_channels WHERE id = ?", (ch["id"],))
            else:
                db.execute("DELETE FROM episodes WHERE season_id IN (SELECT id FROM seasons WHERE series_id IN (SELECT id FROM series WHERE config_id = ?))", (config_id,))
                db.execute("DELETE FROM seasons WHERE series_id IN (SELECT id FROM series WHERE config_id = ?)", (config_id,))
                db.execute("DELETE FROM series WHERE config_id = ?", (config_id,))
                db.execute("DELETE FROM urls WHERE target_type='video' AND target_id IN (SELECT id FROM videos WHERE config_id = ?)", (config_id,))
                db.execute("DELETE FROM videos WHERE config_id = ?", (config_id,))

        db.execute("DELETE FROM auto_update_logs WHERE config_id = ?", (config_id,))
        db.execute("DELETE FROM auto_update_configs WHERE id = ?", (config_id,))
        db.commit()
    return {"ok": True, "purged": purge_data}


@app.post("/api/admin/auto-update/{config_id:int}/trigger")
async def admin_trigger_auto_update(config_id: int, user_payload=Depends(require_admin)):
    """Manually trigger an immediate update run (design 3.5.1). Runs in a
    background thread and returns immediately; the result lands in
    last_status/last_result and auto_update_logs."""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM auto_update_configs WHERE id = ?", (config_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="配置不存在")

    with _AUTO_UPDATE_LOCK:
        if config_id in _AUTO_UPDATE_RUNNING:
            return {"ok": True, "message": "更新任务正在执行", "config_id": config_id}
        _AUTO_UPDATE_RUNNING.add(config_id)

    def _run():
        try:
            run_auto_update(config_id, _row_to_dict(row))
        finally:
            with _AUTO_UPDATE_LOCK:
                _AUTO_UPDATE_RUNNING.discard(config_id)

    threading.Thread(target=_run, daemon=True, name=f"auto-update-trigger-{config_id}").start()
    return {"ok": True, "message": "更新任务已触发", "config_id": config_id}


@app.get("/api/admin/auto-update/{config_id:int}/logs")
async def admin_auto_update_logs(config_id: int, limit: int = 20, user_payload=Depends(require_admin)):
    limit = min(max(limit, 1), config.AUTO_UPDATE_MAX_LOGS)
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM auto_update_configs WHERE id = ?", (config_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="配置不存在")
        logs = db.execute(
            """SELECT * FROM auto_update_logs WHERE config_id = ?
               ORDER BY id DESC LIMIT ?""",
            (config_id, limit),
        ).fetchall()
        return {"logs": [_row_to_dict(r) for r in logs]}


# -- Download Tool (simplified) --

_tasks_lock = threading.Lock()
_download_threads = {}
_cancel_events = {}
_task_last_update = {}
_LOG_MAX = 300


def _load_tasks():
    if DOWNLOAD_TASKS_FILE.exists():
        try:
            with open(DOWNLOAD_TASKS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_tasks(tasks):
    DOWNLOAD_TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DOWNLOAD_TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


def _task_update(task_id, throttle=0, **kw):
    with _tasks_lock:
        tasks = _load_tasks()
        for t in tasks:
            if t["id"] != task_id:
                continue
            now = time.monotonic()
            last = _task_last_update.get(task_id, 0)
            if throttle and now - last < throttle and "status" not in kw and "log" not in kw:
                return
            _task_last_update[task_id] = now
            t.update(kw)
            break
        _save_tasks(tasks)


def _task_log(task_id, line):
    line = str(line).rstrip()[:500]
    with _tasks_lock:
        tasks = _load_tasks()
        for t in tasks:
            if t["id"] == task_id:
                log = t.get("log") or []
                log.append(line)
                t["log"] = log[-_LOG_MAX:]
                break
        _save_tasks(tasks)


# -- Local file serving with HTTP Range (browser seek support) --

def _serve_file_with_range(fp, request, media_type="video/mp4", filename=None):
    """Serve a local file honoring the Range header (206 partial content).

    Starlette FileResponse does not process Range; implement it here so
    players can seek inside downloaded files.
    """
    fp = Path(fp)
    size = fp.stat().st_size
    headers = {"Accept-Ranges": "bytes"}
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    range_header = request.headers.get("range") if request else None
    if not range_header:
        headers["Content-Length"] = str(size)
        return FileResponse(fp, media_type=media_type, headers=headers)

    m = re.match(r"bytes=(\d*)-(\d*)$", range_header.strip(), re.IGNORECASE)
    if not m:
        return FileResponse(fp, media_type=media_type, headers=headers)
    start_s, end_s = m.groups()
    if start_s == "" and end_s == "":
        return FileResponse(fp, media_type=media_type, headers=headers)
    if start_s == "":
        # Suffix range: bytes=-N means the trailing N bytes
        n = int(end_s)
        start = max(size - n, 0)
        end = size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    if start >= size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    end = min(end, size - 1)
    length = end - start + 1
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(length)

    def _iterator():
        with open(fp, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(_iterator(), status_code=206, media_type=media_type,
                             headers=headers)


# -- Download Worker (mp4 streaming + HLS mirroring, pure Python) --

def _safe_title(title, bangou=""):
    name = (title or bangou or "video").replace("/", "_").replace(" ", "_")
    name = re.sub(r'[\\/:*?"<>|\r\n]', '', name).strip("_")[:80]
    return name or "video"


def _sanitize_task_url(url):
    """Only http/https is accepted, to keep worker URLs inject-free."""
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme in ("http", "https") and parts.netloc:
            return url
    except Exception:
        pass
    return ""


def _download_proxy_for_site(site):
    """Per-site proxy opt-in from the global admin settings."""
    settings = load_settings()
    proxy = settings.get("proxy", "")
    sources = settings.get("proxy_sources", {})
    if proxy and site and sources.get(site, True):
        return proxy
    return ""


def _mirror_dir(task_id):
    return DOWNLOAD_FILES_DIR / task_id


def _mirror_seg_dir(task_id):
    d = _mirror_dir(task_id) / "segs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mirror_playlist(task_id):
    return _mirror_dir(task_id) / "playlist.m3u8"


def _http_playlist(task_id):
    """Rewrite the local playlist (relative segs/ refs) into fetchable
    absolute /api/download/{id}/seg/<name> URLs for players."""
    pl = _mirror_playlist(task_id)
    def _strip_prefix(ref):
        return ref[5:] if ref.startswith("segs/") else ref
    out = []
    for line in pl.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(("#EXT-X-KEY:", "#EXT-X-MAP:", "#EXT-X-MEDIA:")) and 'URI="' in s:
            line = re.sub(r'URI="([^"]+)"',
                          lambda m: f'URI="/api/download/{task_id}/seg/{_strip_prefix(m.group(1))}"', line)
        elif s and not s.startswith("#"):
            line = f"/api/download/{task_id}/seg/{_strip_prefix(s.strip())}"
        out.append(line)
    return "\n".join(out) + "\n"


def _hls_request(url, proxies, is_playlist=False):
    """HLS request with Referer; segments stream to disk, playlists load whole."""
    headers = {"User-Agent": config.DEFAULT_UA}
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme in ("http", "https") and parts.netloc:
            headers["Referer"] = f"{parts.scheme}://{parts.netloc}/"
    except ValueError:
        pass
    return requests.get(url, proxies=proxies, headers=headers,
                        timeout=config.DOWNLOAD_HTTP_TIMEOUT,
                        stream=not is_playlist, verify=_REQUESTS_VERIFY)


def _pick_hls_variant(text, url):
    """Master playlist: pick the highest-bandwidth media variant."""
    best, max_bw = None, -1
    attrs = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#EXT-X-STREAM-INF"):
            m = re.search(r"BANDWIDTH=(\d+)", s)
            attrs = {"bw": int(m.group(1)) if m else -1}
        elif s and not s.startswith("#"):
            if attrs is not None and attrs["bw"] > max_bw:
                max_bw, best = attrs["bw"], s
            attrs = None
    if not best:
        raise RuntimeError("master playlist 未找到媒体变体")
    return urllib.parse.urljoin(url, best)


def _local_seg_name(url, kind, extra=""):
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    ext = {"key": ".key", "map": ".init", "media": ".m2ts"}.get(kind, ".ts")
    return f"{h}{extra}{ext}"


def _mirror_hls(task):
    """Mirror a remote m3u8 stream to local files (playlist + segments +
    keys), no external downloader needed. Sets task fields mirror=True,
    file=playlist. Raises on failure; the caller records the error."""
    task_id = task["id"]
    url = task["url"]
    seg_dir = _mirror_seg_dir(task_id)

    proxy = _download_proxy_for_site(task.get("site"))
    proxies = {"http": proxy, "https": proxy} if proxy else None
    cancel = _cancel_events.get(task_id)

    r = _hls_request(url, proxies, is_playlist=True)
    r.raise_for_status()
    text = r.text
    base_url = url
    if "#EXT-X-STREAM-INF" in text:
        base_url = _pick_hls_variant(text, url)
        text = _hls_request(base_url, proxies, is_playlist=True).text
    if "#EXT-X-STREAM-INF" in text:
        raise RuntimeError("无法定位媒体分片列表")

    total = 0
    byterange = None
    refs = []
    lines = text.splitlines()
    for raw in lines:
        s = raw.strip()
        if s.startswith("#EXT-X-KEY:"):
            m = re.search(r'URI="([^"]+)"', s)
            if m and "METHOD=AES-128" in s:
                key_url = urllib.parse.urljoin(base_url, m.group(1))
                refs.append(("key", key_url, _local_seg_name(key_url, "key"), None))
                total += 1
        elif s.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', s)
            if m:
                map_url = urllib.parse.urljoin(base_url, m.group(1))
                refs.append(("map", map_url, _local_seg_name(map_url, "map"), None))
                total += 1
        elif s.startswith("#EXT-X-MEDIA:"):
            m = re.search(r'URI="([^"]+)"', s)
            if m:
                media_url = urllib.parse.urljoin(base_url, m.group(1))
                refs.append(("media", media_url, _local_seg_name(media_url, "media"), None))
                total += 1
        elif s.startswith("#EXT-X-BYTERANGE:"):
            spec = s[len("#EXT-X-BYTERANGE:"):].strip()
            try:
                length, off = spec.split("@", 1)
                byterange = (int(length), int(off))
            except ValueError:
                byterange = None
        elif s.startswith("#"):
            continue
        elif s:
            seg_url = urllib.parse.urljoin(base_url, s)
            if byterange:
                length, off = byterange
                refs.append(("seg", seg_url, _local_seg_name(seg_url, "seg", f"-{off}"), byterange))
            else:
                refs.append(("seg", seg_url, _local_seg_name(seg_url, "seg"), None))
            total += 1
            byterange = None

    if not any(kind == "seg" for kind, *_r in refs):
        raise RuntimeError("playlist 中没有可分片视频内容")

    file_cache = {}
    done = 0
    _task_update(task_id, status="running", message=f"镜像分片 0/{total}")
    for kind, abs_url, local, br in refs:
        if cancel and cancel.is_set():
            raise RuntimeError("已取消")
        target = seg_dir / local
        if br:
            data = file_cache.get(abs_url)
            if data is None:
                err = None
                resp = None
                for attempt in range(config.DOWNLOAD_SEGMENT_RETRY):
                    try:
                        resp = _hls_request(abs_url, proxies)
                        resp.raise_for_status()
                        data = resp.content
                        file_cache[abs_url] = data
                        break
                    except requests.RequestException as e:
                        err = e
                        if attempt < config.DOWNLOAD_SEGMENT_RETRY - 1:
                            time.sleep(1)
                    finally:
                        try:
                            if resp is not None:
                                resp.close()
                        except Exception:
                            pass
                else:
                    raise RuntimeError(f"分片下载失败: {err}")
            length, off = br
            target.write_bytes(data[off:off + length])
        else:
            err = None
            resp = None
            for attempt in range(config.DOWNLOAD_SEGMENT_RETRY):
                try:
                    resp = _hls_request(abs_url, proxies)
                    resp.raise_for_status()
                    with open(target, "wb") as f:
                        shutil.copyfileobj(resp.raw, f)
                    break
                except (requests.RequestException, OSError) as e:
                    err = e
                    if attempt < config.DOWNLOAD_SEGMENT_RETRY - 1:
                        time.sleep(1)
                finally:
                    try:
                        if resp is not None:
                            resp.close()
                    except Exception:
                        pass
            else:
                raise RuntimeError(f"分片下载失败: {err}")
        done += 1
        if done % 5 == 0 or done == total:
            _task_update(task_id, throttle=1, progress=int(done * 100 / max(total, 1)),
                         message=f"镜像分片 {done}/{total}")

    out_lines = []
    ref_iter = iter(refs)
    for raw in lines:
        s = raw.strip()
        if s.startswith("#EXT-X-KEY:"):
            if re.search(r'URI="([^"]+)"', s) and "METHOD=AES-128" in s:
                key_url = urllib.parse.urljoin(base_url, re.search(r'URI="([^"]+)"', s).group(1))
                local = _local_seg_name(key_url, "key")
                out_lines.append(re.sub(r'URI="[^"]+"', f'URI="segs/{local}"', raw))
            else:
                out_lines.append(raw)
        elif s.startswith(("#EXT-X-MAP:", "#EXT-X-MEDIA:")):
            m = re.search(r'URI="([^"]+)"', s)
            if m:
                map_url = urllib.parse.urljoin(base_url, m.group(1))
                local = _local_seg_name(map_url, "map" if s.startswith("#EXT-X-MAP:") else "media")
                out_lines.append(re.sub(r'URI="[^"]+"', f'URI="segs/{local}"', raw))
            else:
                out_lines.append(raw)
        elif s.startswith("#EXT-X-BYTERANGE:"):
            continue
        elif s.startswith("#"):
            out_lines.append(raw)
        elif s:
            kind, _u, _local, _br = next(nr for nr in ref_iter if nr[0] == "seg")
            out_lines.append(f"segs/{_local}")
    playlist_path = _mirror_playlist(task_id)
    playlist_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    size = sum(p.stat().st_size for p in seg_dir.rglob("*") if p.is_file())
    _task_update(task_id, status="done", progress=100, mirror=True,
                 file=str(playlist_path), size=size,
                 message=f"下载完成（{total} 个分片已镜像）")
    _task_log(task_id, f"完成: 镜像 {total} 个分片到 {seg_dir}")


# -- B2: MP4 moov box faststart 预处理（纯 Python 实现 qt-faststart，无 ffmpeg 依赖） --
# 背景：mp4 的 moov box（索引）如果在文件尾部（mdat 之后），浏览器必须把整个文件
# 下载完才能开始解码播放——外网弱网访问本地服务器时表现为"要等全部下载完才有画面"。
# moov 在头部时，播放器拿到 ftyp+moov+第一片 mdat 即可出首帧，配合 HTTP Range
# 支持"秒开 + 边下边播 + 任意拖动"。

def _iter_mp4_top_atoms(fp):
    """扫描顶层 atom，返回 [(pos, size, type)]。只读 atom 头，大文件开销可忽略。"""
    atoms = []
    size = fp.stat().st_size
    with open(fp, "rb") as f:
        pos = 0
        while pos + 8 <= size:
            f.seek(pos)
            head = f.read(16)
            if len(head) < 8:
                break
            box_size, box_type = struct.unpack(">I4s", head[:8])
            if box_size == 1:
                if len(head) < 16:
                    break
                box_size = struct.unpack(">Q", head[8:16])[0]
            elif box_size == 0:
                box_size = size - pos
            if box_size < 8 or pos + box_size > size:
                break
            atoms.append((pos, box_size, box_type))
            pos += box_size
    return atoms


def _mp4_atom_layout(fp):
    """返回 (moov_pos, mdat_pos)；任一缺失返回 (None, None)。"""
    moov_pos = mdat_pos = None
    for pos, _size, typ in _iter_mp4_top_atoms(Path(fp)):
        if typ == b"moov" and moov_pos is None:
            moov_pos = pos
        elif typ == b"mdat" and mdat_pos is None:
            mdat_pos = pos
    return moov_pos, mdat_pos


def _patch_stco_in_buffer(buf, start, end, delta):
    """递归遍历 [start, end) 内的 box 树，把 stco/co64 的 chunk 偏移加上 delta。
    moov 从尾部搬到头部后，mdat 数据整体后移 delta 字节，索引里的绝对偏移
    必须同步修正，否则搬移后的文件不可播。"""
    pos = start
    while pos + 8 <= end:
        size = struct.unpack_from(">I", buf, pos)[0]
        typ = bytes(buf[pos + 4:pos + 8])
        hdr = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack_from(">Q", buf, pos + 8)[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            return
        if typ == b"stco":
            count = struct.unpack_from(">I", buf, pos + hdr + 4)[0]
            base = pos + hdr + 8
            for i in range(count):
                off = base + i * 4
                if off + 4 > end:
                    return
                old = struct.unpack_from(">I", buf, off)[0]
                struct.pack_into(">I", buf, off, (old + delta) & 0xFFFFFFFF)
        elif typ == b"co64":
            count = struct.unpack_from(">I", buf, pos + hdr + 4)[0]
            base = pos + hdr + 8
            for i in range(count):
                off = base + i * 8
                if off + 8 > end:
                    return
                old = struct.unpack_from(">Q", buf, off)[0]
                struct.pack_into(">Q", buf, off, old + delta)
        elif typ in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
            _patch_stco_in_buffer(buf, pos + hdr, pos + size, delta)
        pos += size


def _mp4_faststart(src, dst):
    """把 src 的 moov atom 搬到 mdat 之前并修正 chunk 偏移，写出 dst。
    算法与 qt-faststart 一致；调用方需保证 moov 当前位于 mdat 之后。
    返回搬移的字节数（moov 大小）。"""
    src, dst = Path(src), Path(dst)
    size = src.stat().st_size
    atoms = _iter_mp4_top_atoms(src)
    moov = next((a for a in atoms if a[2] == b"moov"), None)
    mdat = next((a for a in atoms if a[2] == b"mdat"), None)
    if not moov or not mdat:
        raise ValueError("未找到 moov/mdat atom，不是可处理的 mp4")
    moov_pos, moov_len = moov[0], moov[1]
    if moov_pos < mdat[0]:
        raise ValueError("moov 已在 mdat 之前，无需处理")

    with open(src, "rb") as f:
        f.seek(moov_pos)
        moov_data = bytearray(f.read(moov_len))
    # mdat 新位置 = 旧位置 + moov_len（moov 搬到 mdat 之前），所有 chunk 偏移同步 +moov_len
    _patch_stco_in_buffer(moov_data, 0, moov_len, moov_len)

    with open(src, "rb") as fin, open(dst, "wb") as out:
        moov_written = False
        for pos, blen, typ in atoms:
            if typ == b"moov":
                continue
            if typ == b"mdat" and not moov_written:
                out.write(moov_data)
                moov_written = True
            fin.seek(pos)
            remaining = blen
            while remaining > 0:
                chunk = fin.read(min(1 << 20, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        if not moov_written:
            out.write(moov_data)
    return moov_len


def _ensure_faststart(fp):
    """若 fp 的 moov 在尾部则原位搬移到头部。返回 (是否发生搬移, 说明)。"""
    fp = Path(fp)
    moov_pos, mdat_pos = _mp4_atom_layout(fp)
    if moov_pos is None or mdat_pos is None:
        return False, "非 mp4 布局（无 moov/mdat），跳过"
    if moov_pos < mdat_pos:
        return False, "moov 已在头部"
    tmp = fp.with_name(fp.name + ".faststart.tmp")
    t0 = time.time()
    moved = _mp4_faststart(fp, tmp)
    # 校验搬移结果可解析且 moov 已在头部，再原子替换，避免中途失败损坏原文件
    v_moov, v_mdat = _mp4_atom_layout(tmp)
    if v_moov is None or v_mdat is None or v_moov > v_mdat:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise RuntimeError("faststart 校验失败，已保留原文件")
    tmp.replace(fp)
    return True, f"moov 由尾部移至头部（{moved} 字节，耗时 {time.time() - t0:.1f}s）"


def _video_media_type(fp):
    """Media type by magic bytes, fallback to extension mapping."""
    fp = Path(fp)
    try:
        with fp.open("rb") as f:
            head = f.read(32)
    except OSError:
        head = b""
    h = head
    if h[:4] == b"\x1a\x45\xdf\xa3":
        return "video/x-matroska"
    if h[:1] == b"\x47" and len(h) >= 188 and h[188:189] == b"\x47":
        return "video/mp2t"
    if b"ftyp" in h[:32]:
        return "video/mp4"
    if h[:3] == b"FLV" and h[3:4] == b"\x01":
        return "video/x-flv"
    if h[:4] == b"RIFF" and b"AVI " in h[:12]:
        return "video/x-msvideo"
    if h[:16] == b"\x30\x26\xb2\x75\x8e\x66\xcf\x11\xa6\xd9\x00\xaa\x00\x62\xce\x6c":
        return "video/x-ms-wmv"
    return {
        ".ts": "video/mp2t",
        ".mkv": "video/x-matroska",
        ".flv": "video/x-flv",
        ".avi": "video/x-msvideo",
        ".wmv": "video/x-ms-wmv",
        ".webm": "video/webm",
    }.get(fp.suffix.lower(), "video/mp4")


def _download_mp4(task):
    """Plain http(s) mp4 streaming download with progress tracking."""
    task_id = task["id"]
    url = task["url"]
    out_dir = DOWNLOAD_FILES_DIR / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    save_name = _safe_title(task.get("title"), task.get("bangou")) + ".mp4"
    out_file = out_dir / save_name
    cancel = _cancel_events.get(task_id)
    try:
        proxy = _download_proxy_for_site(task.get("site"))
        proxies = {"http": proxy, "https": proxy} if proxy else None
        headers = {"User-Agent": config.DEFAULT_UA}
        try:
            parts = urllib.parse.urlsplit(url)
            if parts.scheme in ("http", "https") and parts.netloc:
                headers["Referer"] = f"{parts.scheme}://{parts.netloc}/"
        except ValueError:
            pass
        _task_update(task_id, status="running", message="MP4 下载中...")
        _task_log(task_id, f"下载: {url}")
        with requests.get(url, proxies=proxies, headers=headers, timeout=60,
                          stream=True, verify=_REQUESTS_VERIFY) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0) or 0)
            done = 0
            with open(out_file, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if cancel and cancel.is_set():
                        _task_update(task_id, status="canceled", message="已取消")
                        _task_log(task_id, "任务已取消")
                        return
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            pct = int(done * 100 / total)
                            _task_update(task_id, throttle=0.5, progress=pct,
                                         message=f"下载中 {pct}%")
        if cancel and cancel.is_set():
            _task_update(task_id, status="canceled", message="已取消")
            _task_log(task_id, "任务已取消")
            return
        _task_update(task_id, status="done", progress=100,
                     file=str(out_file), size=out_file.stat().st_size,
                     message="下载完成")
        _task_log(task_id, f"完成: {out_file.name} ({out_file.stat().st_size} bytes)")
        # B2: moov 在尾部的 mp4 必须整文件下载完才能播——完成后立即做 faststart
        # 预处理（纯 Python），让外网访问本地服务器时可以秒开 + 边下边播
        try:
            moved, detail = _ensure_faststart(out_file)
            _task_update(task_id, faststart=True)
            if moved:
                _task_log(task_id, f"faststart: {detail}，已支持秒开/边下边播")
        except Exception as fe:
            _task_update(task_id, faststart=False)
            _task_log(task_id, f"faststart 预处理跳过: {fe}")
    except Exception as e:
        _task_update(task_id, status="error", message=str(e))
        _task_log(task_id, f"错误: {e}")


def _run_download(task_id):
    with _tasks_lock:
        tasks = _load_tasks()
        task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return
    url = _sanitize_task_url(task.get("url", ""))
    if not url:
        _task_update(task_id, status="error", message="无效的视频地址")
    elif ".m3u8" in url.lower():
        try:
            _mirror_hls(task)
        except Exception as e:
            _task_update(task_id, status="error", message=str(e))
            _task_log(task_id, f"错误: {e}")
    else:
        _download_mp4(task)
    with _tasks_lock:
        _download_threads.pop(task_id, None)
        _cancel_events.pop(task_id, None)


def _resolve_download_video(task):
    """Locate a playable video file for the task. Prefers task['file'];
    falls back to the largest video file inside the task directory and
    repairs task['file'] when it drifted. Returns (Path, changed)."""
    task_id = task.get("id", "")
    fallback_dir = DOWNLOAD_FILES_DIR / task_id if task_id else None
    if task.get("file"):
        fp = Path(task["file"])
        if fp.exists():
            return fp, False
        if fallback_dir and fallback_dir.exists() and fp.name:
            alt = fallback_dir / fp.name
            if alt.exists():
                task["file"] = str(alt)
                return alt, True
    if fallback_dir and fallback_dir.exists():
        vids = [p for p in fallback_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in (".mp4", ".mkv", ".ts")]
        if vids:
            best = max(vids, key=lambda p: p.stat().st_size)
            changed = task.get("file") != str(best)
            task["file"] = str(best)
            return best, changed
    return None, False


def _create_download_task(data):
    """Create a download task from a library entry or an explicit URL.

    Resolution order: explicit url, then the best-ranked active URL row of
    the target (video/series/episode by bangou within a project). Returns
    (task, error).
    """
    bangou = str(data.get("bangou") or "").strip()
    target_type = str(data.get("target_type") or "video").strip()
    try:
        project_id = int(data.get("project_id") or 1)
    except (TypeError, ValueError):
        return None, "project_id 必须是整数", None
    url = _sanitize_task_url(data.get("url") or "")
    title = str(data.get("title") or "").strip()
    site = str(data.get("site") or "").strip()
    target_id = data.get("target_id")

    if target_type not in ("video", "series", "episode"):
        return None, "target_type 必须是 video/series/episode", None

    if not url:
        if not bangou and not target_id:
            return None, "缺少 bangou、target_id 或 url", None
        with get_db() as db:
            if target_type == "video":
                found = _find_media_row(db, project_id, bangou)
                if not found:
                    return None, "视频不存在", None
                table, row = found
                if table != "videos":
                    return None, "该 bangou 是剧集，请以 target_type=series 重试", None
                target_id = row["id"]
                title = title or row["title"] or bangou
                site = site or row["site"] or ""
            elif target_type == "series":
                row = _find_media_row(db, project_id, bangou)
                if not row or row[0] != "series":
                    return None, "剧集不存在", None
                target_id = row[1]["id"]
                title = title or row[1]["title"] or bangou
                site = site or row[1]["site"] or ""
            else:
                row = db.execute(
                    "SELECT id, ep_title, ep_number FROM episodes WHERE id = ?", (target_id,)
                ).fetchone()
                if not row:
                    return None, "剧集单集不存在", None
                title = title or row["ep_title"] or (f"第 {row['ep_number']} 集" if row["ep_number"] else "剧集单集")
            urow = db.execute(
                """SELECT url FROM urls WHERE target_id = ? AND target_type = ?
                   AND is_active = 1
                   ORDER BY is_backup, priority, id LIMIT 1""",
                (target_id, target_type),
            ).fetchone()
            if not urow and target_type == "series":
                # 剧集本体常无独立地址：回退到第一季第一集
                first_ep = db.execute(
                    """SELECT e.id FROM episodes e
                       JOIN seasons sn ON e.season_id = sn.id
                       WHERE sn.series_id = ?
                       ORDER BY sn.season_number, e.ep_number LIMIT 1""",
                    (target_id,),
                ).fetchone()
                if first_ep:
                    urow = db.execute(
                        """SELECT url FROM urls WHERE target_id = ? AND target_type = 'episode'
                           AND is_active = 1
                           ORDER BY is_backup, priority, id LIMIT 1""",
                        (first_ep["id"],),
                    ).fetchone()
            url = _sanitize_task_url(urow["url"]) if urow else ""
    if not url:
        return None, "该内容没有可下载的地址", None

    with _tasks_lock:
        tasks = _load_tasks()
        task = {
            "id": f"dl_{uuid.uuid4().hex[:12]}",
            "bangou": bangou,
            "title": title or bangou or url,
            "url": url,
            "site": site,
            "project_id": project_id,
            "format": "m3u8" if ".m3u8" in url.lower() else "mp4",
            "mirror": False,
            "status": "pending",
            "progress": 0,
            "file": "",
            "size": 0,
            "message": "等待中",
            "error": "",
            "log": [],
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "series_title": str(data.get("series_title") or "").strip(),
            "season_title": str(data.get("season_title") or "").strip(),
            "ep_number": data.get("ep_number") if isinstance(data.get("ep_number"), int) else None,
        }
        tasks.insert(0, task)
        _save_tasks(tasks)
    return task, None, None


@app.post("/api/download")
async def api_download_start(data: dict = Body(...), user_payload=Depends(require_auth)):
    task, err, _ = _create_download_task(data)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    evt = threading.Event()
    _cancel_events[task["id"]] = evt
    t = threading.Thread(target=_run_download, args=(task["id"],), daemon=True)
    _download_threads[task["id"]] = t
    t.start()
    return {"ok": True, "task": task}


@app.get("/api/download/tasks")
async def api_download_tasks(user_payload=Depends(require_auth)):
    return {"items": _load_tasks()[:50]}


@app.get("/api/download/{task_id}")
async def api_download_status(task_id: str, user_payload=Depends(require_auth)):
    tasks = _load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    return task


@app.delete("/api/download/{task_id}")
async def api_download_delete(task_id: str, user_payload=Depends(require_auth)):
    evt = _cancel_events.get(task_id)
    if evt:
        evt.set()
    with _tasks_lock:
        tasks = _load_tasks()
        tasks = [t for t in tasks if t["id"] != task_id]
        _save_tasks(tasks)
        _cancel_events.pop(task_id, None)
        _download_threads.pop(task_id, None)
    out_dir = DOWNLOAD_FILES_DIR / task_id
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    return {"ok": True}


@app.post("/api/download/{task_id}/cancel")
async def api_download_cancel(task_id: str, user_payload=Depends(require_auth)):
    tasks = _load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    evt = _cancel_events.get(task_id)
    if evt:
        evt.set()
    _task_update(task_id, status="canceled", message="已取消")
    _task_log(task_id, "收到取消请求")
    return {"ok": True}


@app.post("/api/download/{task_id}/retry")
async def api_download_retry(task_id: str, user_payload=Depends(require_auth)):
    """Retry a failed/canceled task; finished segments are reused."""
    tasks = _load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if task.get("status") not in ("error", "canceled"):
        return JSONResponse({"error": "仅失败或已取消的任务可重试"}, status_code=400)
    if task_id in _download_threads and _download_threads[task_id].is_alive():
        return JSONResponse({"error": "任务正在运行"}, status_code=400)
    _cancel_events.pop(task_id, None)
    _task_update(task_id, status="pending", progress=0, message="准备重试（复用已有分片）")
    evt = threading.Event()
    _cancel_events[task_id] = evt
    t = threading.Thread(target=_run_download, args=(task_id,), daemon=True)
    _download_threads[task_id] = t
    t.start()
    return {"ok": True}


@app.get("/api/download/{task_id}/file")
async def api_download_file(task_id: str, request: Request):
    tasks = _load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if task.get("mirror"):
        return JSONResponse(
            {"error": "镜像任务请通过 play.m3u8 播放；如需合成 MP4 请在部署环境安装 ffmpeg 后重试"},
            status_code=409)
    fp, changed = await run_in_threadpool(_resolve_download_video, task)
    if not fp:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    if changed:
        with _tasks_lock:
            current = _load_tasks()
            cur = next((t for t in current if t["id"] == task_id), None)
            if cur:
                cur["file"] = str(fp)
            _save_tasks(current)
    return _serve_file_with_range(fp, request, media_type=_video_media_type(fp),
                                  filename=fp.name)


_FFMPEG_BIN_CACHE = {"path": None, "checked": False}


def _ffmpeg_bin():
    """探测部署环境 ffmpeg（结果缓存）。封面生成为尽力而为：无 ffmpeg 时
    前端展示占位封面，不影响播放。"""
    if not _FFMPEG_BIN_CACHE["checked"]:
        _FFMPEG_BIN_CACHE["path"] = shutil.which("ffmpeg")
        _FFMPEG_BIN_CACHE["checked"] = True
    return _FFMPEG_BIN_CACHE["path"]


@app.get("/api/download/{task_id}/poster")
async def api_download_poster(task_id: str):
    """下载任务的封面图（列表页快速预览）。

    懒生成 + 磁盘缓存：首次请求时用 ffmpeg 从本地文件抽帧（默认取第 3 秒，
    超出时长则回退第 0 秒），生成 480 宽 JPEG 存到任务目录。无 ffmpeg 或
    抽帧失败返回 404，前端回退占位图。"""
    tasks = _load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if task.get("mirror"):
        return JSONResponse({"error": "镜像任务无单一本地视频文件"}, status_code=404)
    fp, _changed = await run_in_threadpool(_resolve_download_video, task)
    if not fp:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    poster = fp.parent / "poster.jpg"
    if not poster.exists():
        ffbin = _ffmpeg_bin()
        if not ffbin:
            return JSONResponse({"error": "ffmpeg 不可用，无法生成封面"}, status_code=404)

        def _gen():
            for seek in ("3", "0"):
                r = subprocess.run(
                    [ffbin, "-y", "-ss", seek, "-i", str(fp), "-frames:v", "1",
                     "-vf", "scale=480:-2", "-q:v", "4", str(poster)],
                    capture_output=True, timeout=60)
                if r.returncode == 0 and poster.exists() and poster.stat().st_size > 0:
                    return True
                try:
                    poster.unlink()
                except OSError:
                    pass
            return False

        ok = await run_in_threadpool(_gen)
        if not ok:
            return JSONResponse({"error": "封面生成失败"}, status_code=404)
    return FileResponse(poster, media_type="image/jpeg")


@app.get("/api/download/{task_id}/play.m3u8")
@app.get("/api/download/{task_id}/play")
async def api_download_play(task_id: str, request: Request, probe: bool = False):
    """Progressive playback. Mirror tasks serve the rewritten playlist;
    mp4 tasks serve the file itself with HTTP Range support."""
    tasks = _load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if task.get("mirror"):
        pl = _mirror_playlist(task_id)
        if pl.exists() and pl.stat().st_size > 0:
            if probe:
                return {"status": "ready", "task_id": task_id}
            return Response(_http_playlist(task_id).encode("utf-8"),
                            media_type="application/vnd.apple.mpegurl")
        return JSONResponse({"status": "preparing", "task_id": task_id}, status_code=202)
    fp, changed = await run_in_threadpool(_resolve_download_video, task)
    if not fp:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    if changed:
        with _tasks_lock:
            current = _load_tasks()
            cur = next((t for t in current if t["id"] == task_id), None)
            if cur:
                cur["file"] = str(fp)
            _save_tasks(current)
    return _serve_file_with_range(fp, request, media_type=_video_media_type(fp))


@app.get("/api/download/{task_id}/seg/{name:path}")
async def api_download_seg(task_id: str, name: str):
    """Mirror task segment/key/init service for hls.js."""
    seg_dir = _mirror_seg_dir(task_id).resolve()
    fp = (seg_dir / name).resolve()
    try:
        fp.relative_to(seg_dir)
    except ValueError:
        return JSONResponse({"error": "invalid path"}, status_code=400)
    if not fp.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(fp, media_type="application/octet-stream")


# -- Static Files --

@app.get("/")
async def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return PlainTextResponse("suenplayer backend running", status_code=200)


@app.get("/{path:path}")
async def static_files(path: str, request: Request):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")
    file_path = STATIC_DIR / path
    if file_path.exists() and file_path.is_file():
        ext = file_path.suffix.lower()
        ct = MIME_TYPES.get(ext, "application/octet-stream")
        return FileResponse(file_path, media_type=ct)
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"error": "not found"}, status_code=404)


# -- Startup --

_init_db_schema()
_bootstrap_default_data()


# -- Background Scheduler (auto update + live probe patrol) --
# Design doc 8.1: APScheduler in-process, initialized at startup.
# Guarded by SUENMEDIA_DISABLE_SCHEDULER so test environments (TestClient)
# can keep runs deterministic without background threads.

_scheduler = None
_scheduler_logger = logging.getLogger("suenplayer.scheduler")


def _scheduler_disabled_by_env() -> bool:
    return os.environ.get("SUENMEDIA_DISABLE_SCHEDULER", "").strip().lower() in ("1", "true", "yes")


def _start_background_scheduler():
    """Start the in-process background scheduler.

    Jobs:
    - auto_update_scan: every AUTO_UPDATE_SCAN_INTERVAL seconds (default 60),
      picks up auto_update_configs rows whose next_run_at is due.
    - live_probe_patrol: every LIVE_PROBE_INTERVAL_SECONDS seconds (default 4h),
      re-probes active live sources whose last probe is stale.
    """
    global _scheduler
    if _scheduler_disabled_by_env():
        _scheduler_logger.info("background scheduler disabled by SUENMEDIA_DISABLE_SCHEDULER")
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        _scheduler_logger.warning("apscheduler not installed; background scheduler disabled")
        return
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    scan_interval = max(30, int(getattr(config, "AUTO_UPDATE_SCAN_INTERVAL", 60)))
    patrol_interval = max(300, int(getattr(config, "LIVE_PROBE_INTERVAL_SECONDS", 4 * 3600)))
    _scheduler.add_job(
        scheduled_update_scan, "interval", seconds=scan_interval,
        id="auto_update_scan", max_instances=1, coalesce=True,
    )
    _scheduler.add_job(
        live_probe_patrol, "interval", seconds=patrol_interval,
        id="live_probe_patrol", max_instances=1, coalesce=True,
    )
    _scheduler.start()
    _scheduler_logger.info(
        "background scheduler started (auto_update_scan every %ss, live_probe_patrol every %ss)",
        scan_interval, patrol_interval,
    )


_start_background_scheduler()
