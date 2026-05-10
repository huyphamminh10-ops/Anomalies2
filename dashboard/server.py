"""
dashboard/server.py — Anomalies Web Dashboard v3.1
FastAPI + Discord OAuth2 + MongoDB + TiDB
Deploy trên Render.com (.onrender.com)

FIX v3.1:
  #1 - ID Stringify: guild_id/user_id/channel_id luôn str(), filter chỉ dùng {"guild_id": str(id)}
  #2 - MongoDB timeout + ping + trả None thay vì crash
  #3 - TiDB cho Feedbacks (id 10 ký tự), Changelogs (INT AUTO_INCREMENT), Bans
  #4 - Lobby State: query bổ sung sang lobby_states để lấy is_playing + player_count
  #5 - Cache Invalidation: Dashboard cập nhật last_updated, Bot so sánh để reload
"""
from __future__ import annotations

import os
import time
import hmac
import hashlib
import secrets
import string
import json
from datetime import datetime, timezone
from typing import Optional

import re
import glob
import httpx
import pymysql
import pymysql.cursors
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import uvicorn

# ══════════════════════════════════════════════════════════════
# CONFIG — lấy từ biến môi trường Render
# ══════════════════════════════════════════════════════════════
BOT_OWNER_ID          = str(os.environ.get("BOT_OWNER_ID", "1306441206296875099"))
DISCORD_CLIENT_ID     = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI  = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/discord/callback")
SECRET_KEY            = os.environ.get("SESSION_SECRET", secrets.token_hex(32))
MONGO_URI             = os.environ.get("MONGO_URI", "")

IS_RENDER = bool(os.environ.get("RENDER_EXTERNAL_URL", ""))

DISCORD_API  = "https://discord.com/api/v10"
OAUTH_SCOPES = "identify guilds"

# ══════════════════════════════════════════════════════════════
# MONGODB
# FIX #2: serverSelectionTimeoutMS=5000, connectTimeoutMS=10000,
#         ping trước khi trả DB, trả None thay vì crash nếu lỗi.
# ══════════════════════════════════════════════════════════════
_client: Optional[MongoClient] = None

def get_db():
    global _client
    if _client is None and MONGO_URI:
        try:
            _client = MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000,
            )
            _client.admin.command("ping")
            print("[mongo] Kết nối MongoDB thành công.")
        except Exception as e:
            print(f"[mongo] Không kết nối được MongoDB: {e}")
            _client = None
            return None
    return _client["Anomalies_DB"] if _client else None

def col(name: str):
    try:
        db = get_db()
        return db[name] if db is not None else None
    except Exception as e:
        print(f"[mongo] Lỗi lấy collection {name}: {e}")
        return None

# FIX #1: Tất cả filter MongoDB chỉ dùng str(id) — không dùng $in nữa để tránh xung đột index
def _gf(guild_id) -> dict:
    """Guild filter — luôn dùng str để nhất quán với index unique."""
    return {"guild_id": str(guild_id)}

def _uf(user_id) -> dict:
    """User filter — luôn str."""
    return {"user_id": str(user_id)}

def _cf(channel_id) -> dict:
    """Channel filter — luôn str."""
    return {"channel_id": str(channel_id)}

# ══════════════════════════════════════════════════════════════
# TIDB — Dùng cho Feedbacks, Changelogs, Bans
# FIX #3: Feedbacks + Changelogs chuyển sang TiDB theo yêu cầu
# ══════════════════════════════════════════════════════════════
TIDB_URI = os.environ.get(
    "TIDB_URI",
    "mysql://pmiJpFtdc5E8WwZ.root:r0QZSVZVEINtmH39@gateway01.ap-southeast-1.prod.aws.tidbcloud.com:4000/sys"
)

def _parse_tidb_uri(uri: str) -> dict | None:
    m = re.match(r"mysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", uri)
    if not m:
        return None
    db_name = m.group(5)
    if db_name.lower() == "sys":
        db_name = "test"
    return {"user": m.group(1), "password": m.group(2),
            "host": m.group(3), "port": int(m.group(4)), "database": db_name}

def _get_tidb_conn():
    info = _parse_tidb_uri(TIDB_URI)
    if not info:
        return None
    if "tidbcloud" in info["host"]:
        ssl_config = {"ca": "/etc/ssl/certs/ca-certificates.crt"} if IS_RENDER else {"ssl_mode": "VERIFY_IDENTITY"}
    else:
        ssl_config = {}
    try:
        conn = pymysql.connect(
            host=info["host"], user=info["user"], password=info["password"],
            database=info["database"], port=info["port"],
            ssl=ssl_config,
            connect_timeout=8,
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
            charset="utf8mb4",
        )
        return conn
    except Exception as e:
        print(f"[tidb] Không kết nối được TiDB: {e}")
        return None

def _rand_id(n=10) -> str:
    """Tạo chuỗi ngẫu nhiên n ký tự (chữ + số) dùng làm Feedback ID."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(n))

def _tidb_ensure_tables():
    """Tạo tất cả bảng TiDB nếu chưa tồn tại."""
    conn = _get_tidb_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            # Bảng Bans — quản lý user bị cấm
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bans (
                    user_id    VARCHAR(32)  PRIMARY KEY,
                    reason     VARCHAR(500) NOT NULL DEFAULT '',
                    mode       VARCHAR(20)  NOT NULL DEFAULT 'ban',
                    created_at VARCHAR(50)  NOT NULL DEFAULT ''
                )
            """)
            # FIX #3: Bảng Feedbacks — ID 10 ký tự ngẫu nhiên
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedbacks (
                    id         VARCHAR(10)   PRIMARY KEY,
                    user_id    VARCHAR(32)   NOT NULL DEFAULT '',
                    username   VARCHAR(100)  NOT NULL DEFAULT '',
                    avatar     VARCHAR(300)  NOT NULL DEFAULT '',
                    content    TEXT,
                    images     TEXT,
                    reply      TEXT,
                    created_at VARCHAR(50)   NOT NULL DEFAULT ''
                )
            """)
            # FIX #3: Bảng Changelogs — INT AUTO_INCREMENT PK
            cur.execute("""
                CREATE TABLE IF NOT EXISTS changelogs (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    version    VARCHAR(20)   NOT NULL DEFAULT '',
                    title      VARCHAR(200)  NOT NULL DEFAULT '',
                    content    TEXT,
                    created_at VARCHAR(50)   NOT NULL DEFAULT ''
                )
            """)
        conn.commit()
    except Exception as e:
        print(f"[tidb] Lỗi tạo bảng: {e}")
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════════
# ROLE SCANNER
# ══════════════════════════════════════════════════════════════
_ROLES_CACHE: list = []

def _scan_roles_from_files() -> list:
    global _ROLES_CACHE
    if _ROLES_CACHE:
        return _ROLES_CACHE

    roles_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "roles")
    if not os.path.exists(roles_root):
        return _default_roles()

    faction_map = {
        "Survivors": "Survivors", "Anomalies": "Anomalies",
        "Unknown": "Unknown", "Unknown Entities": "Unknown", "Event": "Event",
    }
    color_map = {
        "Survivors": "#3dd68c", "Anomalies": "#f05050",
        "Unknown": "#f5c231", "Event": "#a78bfa",
    }
    results = []
    for subfolder in ["survivors", "anomalies", "unknown", "event"]:
        folder = os.path.join(roles_root, subfolder)
        if not os.path.isdir(folder):
            continue
        for fpath in sorted(glob.glob(os.path.join(folder, "*.py"))):
            fname = os.path.basename(fpath)
            if fname.startswith("_"):
                continue
            try:
                content = open(fpath, encoding="utf-8").read()
                nm = re.search(r'^\s+name\s*=\s*["\'](.*?)["\']', content, re.MULTILINE)
                tm = re.search(r'^\s+team\s*=\s*["\'](.*?)["\']', content, re.MULTILINE)
                if not nm:
                    continue
                name    = nm.group(1).strip()
                team    = tm.group(1).strip() if tm else subfolder.capitalize()
                faction = faction_map.get(team, subfolder.capitalize())
                color   = color_map.get(faction, "#7c6af7")

                dm = re.search(r'description\s*=\s*\(\s*(.*?)\s*\)', content, re.DOTALL)
                if not dm:
                    dm = re.search(r'description\s*=\s*["\'](.*?)["\']', content)
                desc = ""
                if dm:
                    raw = dm.group(1)
                    raw = re.sub(r'["\']\s*["\']+', ' ', raw)
                    raw = re.sub(r'^[\s"\']+|[\s"\']+$', '', raw, flags=re.MULTILINE)
                    raw = re.sub(r'\{[^}]*\}', '...', raw)
                    raw = raw.replace("\\n", "\n").replace("\\t", " ").replace("\\\\", "\\")
                    raw = re.sub(r' +', ' ', raw)
                    desc = raw.strip()

                results.append({
                    "name": name, "faction": faction, "team": team,
                    "description": desc, "color": color,
                })
            except Exception as e:
                print(f"[roles_scan] Lỗi đọc {fpath}: {e}")

    _ROLES_CACHE = results if results else _default_roles()
    return _ROLES_CACHE

# ══════════════════════════════════════════════════════════════
# SESSION — cookie có chữ ký HMAC
# ══════════════════════════════════════════════════════════════
COOKIE_NAME    = "session_data"
COOKIE_MAX_AGE = 86400 * 7  # 7 ngày

def _sign(data: str) -> str:
    return hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()

def set_session(response: Response, user_id: str, username: str, avatar_url: str, access_token: str = ""):
    import base64
    payload_dict = {
        "u": str(user_id),
        "t": access_token,
        "n": username,
        "a": avatar_url,
        "exp": int(time.time()) + COOKIE_MAX_AGE,
    }
    data    = json.dumps(payload_dict, separators=(",", ":"))
    payload = base64.urlsafe_b64encode(data.encode()).decode()
    sig         = _sign(payload)
    cookie_val  = f"{payload}.{sig}"
    is_https    = os.environ.get("IS_HTTPS", "true").lower() != "false"
    response.set_cookie(
        key=COOKIE_NAME, value=cookie_val,
        httponly=True, secure=is_https, samesite="lax",
        max_age=COOKIE_MAX_AGE, path="/",
    )

def get_session(request: Request) -> Optional[dict]:
    import base64
    cookie = request.cookies.get(COOKIE_NAME, "")
    if not cookie or "." not in cookie:
        return None
    payload, sig = cookie.rsplit(".", 1)
    if not hmac.compare_digest(_sign(payload), sig):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
        if int(time.time()) > data.get("exp", 0):
            return None
        return {
            "user_id":      str(data["u"]),
            "access_token": data["t"],
            "username":     data["n"],
            "avatar":       data["a"],
            "is_owner":     str(data["u"]) == BOT_OWNER_ID,
        }
    except Exception:
        return None

def _clear_session(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/")

def require_auth(request: Request) -> dict:
    session = get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return session

def require_owner(request: Request) -> dict:
    session = require_auth(request)
    if not session["is_owner"]:
        raise HTTPException(status_code=403, detail="Chỉ dành cho chủ bot")
    return session

def _has_manage_guild(permissions: int) -> bool:
    return bool(permissions & 0x20) or bool(permissions & 0x8)

def _assert_guild_access(session: dict, guild_id: str, guilds_list: list = None):
    if session["is_owner"]:
        return True
    if guilds_list:
        for g in guilds_list:
            if str(g["id"]) == str(guild_id):
                return _has_manage_guild(int(g.get("permissions", 0)))
    raise HTTPException(status_code=403, detail="Không có quyền truy cập server này")

# ══════════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════════
app = FastAPI(title="Anomalies Dashboard v3.1")

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
origins = ["http://localhost:8000", "http://127.0.0.1:8000"]
if RENDER_URL:
    origins.append(RENDER_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def _startup():
    _tidb_ensure_tables()

# ══════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════
@app.get("/auth/login")
async def login():
    state = secrets.token_hex(16)
    url = (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={OAUTH_SCOPES.replace(' ', '%20')}"
        f"&state={state}"
    )
    return RedirectResponse(url)

@app.get("/auth/discord/callback")
async def callback(code: str = None, error: str = None, error_description: str = None):
    if error:
        return RedirectResponse(url=f"/?auth_error={error}", status_code=303)
    if not code:
        raise HTTPException(400, "Thiếu code từ Discord")
    try:
        async with httpx.AsyncClient() as http:
            token_resp = await http.post(
                "https://discord.com/api/oauth2/token",
                data={
                    "client_id":     DISCORD_CLIENT_ID,
                    "client_secret": DISCORD_CLIENT_SECRET,
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "redirect_uri":  DISCORD_REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_resp.status_code != 200:
                raise HTTPException(400, f"Discord từ chối code: {token_resp.status_code}")
            token_data = token_resp.json()
            if "access_token" not in token_data:
                err  = token_data.get("error", "unknown")
                desc = token_data.get("error_description", "")
                raise HTTPException(400, f"Discord OAuth lỗi: {err} — {desc}")
            access_token = token_data["access_token"]
            user_resp = await http.get(
                f"{DISCORD_API}/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if user_resp.status_code != 200:
                raise HTTPException(400, "Không lấy được thông tin user")
            user = user_resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Lỗi xác thực OAuth: {exc}")

    user_id  = str(user["id"])
    username = user.get("global_name") or user.get("username", "Unknown")
    avatar   = user.get("avatar") or ""
    if avatar:
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.webp?size=128"
    else:
        default_index = int(user_id) % 6
        avatar_url = f"https://cdn.discordapp.com/embed/avatars/{default_index}.png"

    redirect = RedirectResponse(url="/", status_code=303)
    set_session(redirect, user_id=user_id, username=username, avatar_url=avatar_url, access_token=access_token)
    return redirect

@app.get("/auth/logout")
async def logout():
    redirect = RedirectResponse("/", status_code=303)
    redirect.delete_cookie(key=COOKIE_NAME, path="/")
    return redirect

# ══════════════════════════════════════════════════════════════
# API — PUBLIC
# ══════════════════════════════════════════════════════════════
@app.get("/api/me")
@app.get("/api/dash/me")
async def api_me(request: Request):
    session = get_session(request)
    if not session:
        return JSONResponse({"logged_in": False})
    return JSONResponse({
        "logged_in": True,
        "user_id":   session["user_id"],
        "username":  session["username"],
        "avatar":    session["avatar"],
        "is_owner":  session["is_owner"],
    })

@app.get("/api/dash/roles")
async def api_roles(request: Request):
    return JSONResponse(_scan_roles_from_files())

@app.get("/api/dash/guilds")
async def api_guilds(request: Request):
    """Danh sách server user đang ở + bot có config.
    FIX #4: Query bổ sung vào lobby_states để lấy is_playing + player_count thực tế.
    FIX #1: guild_id luôn str().
    """
    session = require_auth(request)
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(
                f"{DISCORD_API}/users/@me/guilds",
                headers={"Authorization": f"Bearer {session['access_token']}"},
            )
            if resp.status_code != 200:
                return JSONResponse([])
            guilds = resp.json()
    except Exception as e:
        print(f"[guilds] Discord API error: {e}")
        return JSONResponse([])

    db_configs = col("guild_configs")
    db_lobbies = col("lobby_states")
    result = []
    if db_configs:
        for g in guilds:
            try:
                gid = str(g["id"])
                # FIX #1: filter chỉ dùng str()
                cfg_doc = db_configs.find_one(
                    _gf(gid),
                    {"_id": 0, "status": 1, "max_players": 1}
                )
                if cfg_doc is None:
                    continue

                icon = g.get("icon")
                icon_url = (
                    f"https://cdn.discordapp.com/icons/{gid}/{icon}.png"
                    if icon else None
                )

                # FIX #4: Lấy trạng thái phòng chơi thực tế từ lobby_states
                is_playing   = False
                player_count = 0
                if db_lobbies:
                    try:
                        lobby_doc = db_lobbies.find_one(
                            _gf(gid),
                            {"_id": 0, "is_playing": 1, "player_count": 1, "player_ids": 1}
                        )
                        if lobby_doc:
                            is_playing   = bool(lobby_doc.get("is_playing", False))
                            # Hỗ trợ cả player_count (số) lẫn player_ids (list)
                            player_count = (
                                lobby_doc.get("player_count")
                                or len(lobby_doc.get("player_ids", []))
                                or 0
                            )
                    except PyMongoError:
                        pass

                result.append({
                    "id":            gid,
                    "name":          g.get("name", "Unknown"),
                    "icon":          icon_url,
                    "permissions":   str(g.get("permissions", 0)),
                    "status":        cfg_doc.get("status"),
                    "max_players":   cfg_doc.get("max_players", 65),
                    "is_playing":    is_playing,
                    "active_players": player_count,
                })
            except PyMongoError as e:
                print(f"[guilds] MongoDB error cho guild {g.get('id')}: {e}")
                continue
            except Exception as e:
                print(f"[guilds] Lỗi cho guild {g.get('id')}: {e}")
                continue
    return JSONResponse(result)

@app.get("/api/dash/guild/{guild_id}/config")
async def api_guild_config(guild_id: str, request: Request):
    session = require_auth(request)
    db_col = col("guild_configs")
    if not db_col:
        return JSONResponse({})
    try:
        # FIX #1: filter chỉ str()
        doc = db_col.find_one(_gf(guild_id))
    except PyMongoError as e:
        print(f"[guild_config] MongoDB error: {e}")
        return JSONResponse({})
    if doc:
        doc.pop("_id", None)
    return JSONResponse(doc or {})

@app.post("/api/dash/guild/{guild_id}/config")
async def api_update_config(guild_id: str, request: Request):
    session = require_auth(request)

    guilds = []
    if not session["is_owner"]:
        try:
            async with httpx.AsyncClient() as http:
                resp = await http.get(
                    f"{DISCORD_API}/users/@me/guilds",
                    headers={"Authorization": f"Bearer {session['access_token']}"},
                )
                if resp.status_code == 200:
                    guilds = resp.json()
        except Exception as e:
            print(f"[update_config] Lỗi lấy guild list: {e}")
        _assert_guild_access(session, guild_id, guilds)

    data = await request.json()
    allowed = {
        "max_players", "min_players", "countdown_time", "allow_chat",
        "mute_dead", "no_remove_roles", "music", "skip_discussion",
        "day_time", "vote_time", "skip_discussion_delay",
    }
    update = {k: v for k, v in data.items() if k in allowed}
    # FIX #5: Cập nhật last_updated để Bot biết cần reload cache
    update["last_updated"] = time.time()
    db_col = col("guild_configs")
    if db_col and update:
        try:
            # FIX #1: filter chỉ str()
            db_col.update_one(_gf(guild_id), {"$set": update}, upsert=True)
        except PyMongoError as e:
            print(f"[update_config] MongoDB error: {e}")
            raise HTTPException(500, "Lỗi lưu cấu hình")
    return JSONResponse({"ok": True})

@app.get("/api/dash/guild/{guild_id}/status")
async def api_guild_status(guild_id: str, request: Request):
    require_auth(request)
    db_col = col("guild_configs")
    db_lobbies = col("lobby_states")
    if not db_col:
        return JSONResponse({"status": None})
    try:
        cfg = db_col.find_one(_gf(guild_id), {"status": 1, "max_players": 1, "_id": 0})
    except PyMongoError as e:
        print(f"[guild_status] MongoDB error: {e}")
        return JSONResponse({"status": None})

    # FIX #4: Bổ sung query lobby_states để lấy player_count thực tế
    is_playing   = False
    player_count = 0
    if db_lobbies:
        try:
            lobby = db_lobbies.find_one(
                _gf(guild_id),
                {"_id": 0, "is_playing": 1, "player_count": 1, "player_ids": 1}
            )
            if lobby:
                is_playing   = bool(lobby.get("is_playing", False))
                player_count = lobby.get("player_count") or len(lobby.get("player_ids", [])) or 0
        except PyMongoError:
            pass

    return JSONResponse({
        "status":         cfg.get("status") if cfg else None,
        "max_players":    cfg.get("max_players", 65) if cfg else 65,
        "is_playing":     is_playing,
        "active_players": player_count,
    })

@app.get("/api/dash/changelog")
async def api_changelog(request: Request):
    """FIX #3: Đọc changelogs từ TiDB (INT AUTO_INCREMENT PK)."""
    require_auth(request)
    conn = _get_tidb_conn()
    if not conn:
        return JSONResponse([])
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, version, title, content, created_at FROM changelogs ORDER BY id DESC LIMIT 30")
            rows = cur.fetchall()
        return JSONResponse(list(rows))
    except Exception as e:
        print(f"[changelog] TiDB error: {e}")
        return JSONResponse([])
    finally:
        conn.close()

@app.post("/api/dash/feedback")
async def api_feedback(request: Request):
    """FIX #3: Lưu feedback vào TiDB với ID 10 ký tự ngẫu nhiên."""
    session = require_auth(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Request body không hợp lệ")
    content    = str(data.get("content", "")).strip()[:2000]
    raw_images = data.get("images", [])
    if not isinstance(raw_images, list):
        raw_images = []
    MAX_IMG_B64 = 1_400_000
    images = [img for img in raw_images[:5] if isinstance(img, str) and len(img) <= MAX_IMG_B64]
    if not content and not images:
        raise HTTPException(400, "Nội dung trống")

    conn = _get_tidb_conn()
    if not conn:
        raise HTTPException(503, "Cơ sở dữ liệu chưa sẵn sàng")
    try:
        fb_id = _rand_id(10)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO feedbacks (id, user_id, username, avatar, content, images, reply, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, NULL, %s)""",
                (
                    fb_id,
                    str(session["user_id"]),     # FIX #1: luôn str()
                    session["username"],
                    session["avatar"],
                    content,
                    json.dumps(images, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                )
            )
        return JSONResponse({"ok": True, "id": fb_id})
    except Exception as e:
        print(f"[feedback] TiDB error: {e}")
        raise HTTPException(500, "Lỗi lưu dữ liệu")
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════════
# API — OWNER ONLY
# ══════════════════════════════════════════════════════════════
@app.get("/api/dash/admin/feedbacks")
async def api_admin_feedbacks(request: Request):
    """FIX #3: Đọc feedbacks từ TiDB."""
    require_owner(request)
    conn = _get_tidb_conn()
    if not conn:
        return JSONResponse([])
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, user_id, username, avatar, content, images, reply, created_at FROM feedbacks ORDER BY created_at DESC LIMIT 50")
            rows = cur.fetchall()
        # Parse images JSON string thành list
        for row in rows:
            if isinstance(row.get("images"), str):
                try:
                    row["images"] = json.loads(row["images"])
                except Exception:
                    row["images"] = []
        return JSONResponse(list(rows))
    except Exception as e:
        print(f"[admin_feedbacks] TiDB error: {e}")
        return JSONResponse([])
    finally:
        conn.close()

@app.post("/api/dash/admin/feedback/{fb_id}/reply_by_index")
async def api_reply_feedback_by_index(fb_id: str, request: Request):
    """FIX #3: Cập nhật reply trên TiDB — dùng id (PK) hoặc created_at fallback."""
    require_owner(request)
    data       = await request.json()
    reply      = str(data.get("reply", "")).strip()[:1000]
    created_at = data.get("created_at", "")
    conn = _get_tidb_conn()
    if not conn:
        raise HTTPException(503, "Không kết nối được TiDB")
    try:
        with conn.cursor() as cur:
            if fb_id and fb_id != "by_index":
                cur.execute("UPDATE feedbacks SET reply=%s WHERE id=%s", (reply, fb_id))
            elif created_at:
                cur.execute("UPDATE feedbacks SET reply=%s WHERE created_at=%s", (reply, created_at))
        return JSONResponse({"ok": True})
    except Exception as e:
        print(f"[reply_feedback] TiDB error: {e}")
        raise HTTPException(500, "Lỗi lưu reply")
    finally:
        conn.close()

@app.post("/api/dash/admin/changelog")
async def api_post_changelog(request: Request):
    """FIX #3: Lưu changelog vào TiDB với INT AUTO_INCREMENT PK."""
    require_owner(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Request body không hợp lệ")
    title   = str(data.get("title", "")).strip()[:200]
    content = str(data.get("content", "")).strip()[:5000]
    version = str(data.get("version", "")).strip()[:20]
    if not title or not content:
        raise HTTPException(400, "Thiếu tiêu đề hoặc nội dung")
    conn = _get_tidb_conn()
    if not conn:
        raise HTTPException(503, "Cơ sở dữ liệu chưa sẵn sàng")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO changelogs (version, title, content, created_at) VALUES (%s, %s, %s, %s)",
                (version, title, content, datetime.now(timezone.utc).isoformat())
            )
        return JSONResponse({"ok": True})
    except Exception as e:
        print(f"[changelog] TiDB error: {e}")
        raise HTTPException(500, "Lỗi lưu dữ liệu")
    finally:
        conn.close()

@app.get("/api/dash/admin/bans")
async def api_admin_bans(request: Request):
    require_owner(request)
    conn = _get_tidb_conn()
    if not conn:
        return JSONResponse([])
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, reason, mode, created_at FROM bans ORDER BY created_at DESC")
            rows = cur.fetchall()
        return JSONResponse(list(rows))
    except Exception as e:
        print(f"[tidb] Lỗi đọc bans: {e}")
        return JSONResponse([])
    finally:
        conn.close()

@app.post("/api/dash/admin/ban")
async def api_ban_player(request: Request):
    require_owner(request)
    data    = await request.json()
    user_id = str(data.get("user_id", "")).strip()   # FIX #1: str()
    reason  = str(data.get("reason", "Không có lý do")).strip()[:500]
    mode    = data.get("mode", "ban")
    if not user_id:
        raise HTTPException(400, "Thiếu user_id")
    conn = _get_tidb_conn()
    if not conn:
        raise HTTPException(503, "Không kết nối được TiDB")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bans (user_id, reason, mode, created_at)
                   VALUES (%s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE reason=%s, mode=%s, created_at=%s""",
                (user_id, reason, mode, datetime.now(timezone.utc).isoformat(),
                 reason, mode, datetime.now(timezone.utc).isoformat())
            )
        conn.commit()
    except Exception as e:
        print(f"[tidb] Lỗi ban: {e}")
        raise HTTPException(500, "Lỗi TiDB")
    finally:
        conn.close()
    return JSONResponse({"ok": True})

@app.delete("/api/dash/admin/ban/{user_id}")
async def api_unban_player(user_id: str, request: Request):
    require_owner(request)
    conn = _get_tidb_conn()
    if not conn:
        raise HTTPException(503, "Không kết nối được TiDB")
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bans WHERE user_id = %s", (str(user_id),))  # FIX #1: str()
        conn.commit()
    except Exception as e:
        print(f"[tidb] Lỗi unban: {e}")
        raise HTTPException(500, "Lỗi TiDB")
    finally:
        conn.close()
    return JSONResponse({"ok": True})

@app.get("/api/dash/player/lookup")
async def api_player_lookup(user_id: str, request: Request):
    require_auth(request)
    conn = _get_tidb_conn()
    ban_info = None
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM bans WHERE user_id = %s", (str(user_id),))  # FIX #1: str()
                ban_info = cur.fetchone()
        except Exception as e:
            print(f"[player_lookup] Lỗi TiDB: {e}")
        finally:
            conn.close()
    return JSONResponse({
        "user_id": str(user_id),
        "is_banned": ban_info is not None,
        "ban": ban_info,
    })

@app.get("/api/dash/stats")
async def api_stats(request: Request):
    require_auth(request)
    db = get_db()
    stats = {"total_guilds": 0, "active_games": 0, "total_bans": 0,
             "total_feedbacks": 0, "total_changelogs": 0, "db_ok": False}
    if db:
        stats["db_ok"] = True
        try:
            stats["total_guilds"] = db["guild_configs"].count_documents({})
        except Exception as e:
            print(f"[stats] Lỗi đếm total_guilds: {e}")
        try:
            stats["active_games"] = db["lobby_states"].count_documents({"is_playing": True})
        except Exception as e:
            print(f"[stats] Lỗi đếm active_games: {e}")
    # FIX #3: Đếm từ TiDB
    conn = _get_tidb_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as cnt FROM bans")
                row = cur.fetchone()
                stats["total_bans"] = row["cnt"] if row else 0
                cur.execute("SELECT COUNT(*) as cnt FROM feedbacks")
                row = cur.fetchone()
                stats["total_feedbacks"] = row["cnt"] if row else 0
                cur.execute("SELECT COUNT(*) as cnt FROM changelogs")
                row = cur.fetchone()
                stats["total_changelogs"] = row["cnt"] if row else 0
        except Exception as e:
            print(f"[stats] Lỗi TiDB: {e}")
        finally:
            conn.close()
    return JSONResponse(stats)

@app.get("/api/dash/admin/rooms")
async def api_admin_rooms(request: Request):
    """FIX #4: Bổ sung lookup lobby_states để lấy is_playing + player_count thực tế."""
    require_owner(request)
    db_col = col("guild_configs")
    db_lobbies = col("lobby_states")
    if not db_col:
        return JSONResponse([])
    try:
        docs = list(db_col.find({}, {
            "_id": 0, "guild_id": 1, "guild_name": 1,
            "status": 1, "max_players": 1, "min_players": 1,
        }))
    except PyMongoError as e:
        print(f"[admin_rooms] MongoDB error: {e}")
        return JSONResponse([])

    # FIX #4: Gắn thêm thông tin phòng từ lobby_states
    if db_lobbies:
        for doc in docs:
            gid = str(doc.get("guild_id", ""))
            doc["guild_id"] = gid
            try:
                lobby = db_lobbies.find_one(
                    _gf(gid),
                    {"_id": 0, "is_playing": 1, "player_count": 1, "player_ids": 1}
                )
                if lobby:
                    doc["is_playing"]    = bool(lobby.get("is_playing", False))
                    doc["active_players"] = (
                        lobby.get("player_count")
                        or len(lobby.get("player_ids", []))
                        or 0
                    )
                else:
                    doc["is_playing"]    = False
                    doc["active_players"] = 0
            except PyMongoError:
                doc["is_playing"]    = False
                doc["active_players"] = 0
    return JSONResponse(docs)

@app.get("/api/dash/admin/guild/{guild_id}/config")
async def api_admin_guild_config(guild_id: str, request: Request):
    require_owner(request)
    db_col = col("guild_configs")
    if not db_col:
        return JSONResponse({})
    try:
        doc = db_col.find_one(_gf(guild_id))  # FIX #1: str()
    except PyMongoError as e:
        print(f"[admin_guild_config] MongoDB error: {e}")
        return JSONResponse({})
    if doc:
        doc.pop("_id", None)
    return JSONResponse(doc or {})

@app.post("/api/dash/admin/guild/{guild_id}/config")
async def api_admin_update_config(guild_id: str, request: Request):
    require_owner(request)
    data = await request.json()
    allowed = {
        "max_players", "min_players", "countdown_time", "allow_chat",
        "mute_dead", "no_remove_roles", "music", "skip_discussion",
        "day_time", "vote_time", "skip_discussion_delay",
        "text_channel_id", "voice_channel_id", "dead_role_id", "alive_role_id",
    }
    update = {k: v for k, v in data.items() if k in allowed}
    # FIX #5: Đặt last_updated để Bot reload cache
    update["last_updated"] = time.time()
    db_col = col("guild_configs")
    if db_col and update:
        try:
            db_col.update_one(_gf(guild_id), {"$set": update}, upsert=True)  # FIX #1: str()
        except PyMongoError as e:
            print(f"[admin_update_config] MongoDB error: {e}")
            raise HTTPException(500, "Lỗi lưu cấu hình")
    return JSONResponse({"ok": True})

# ══════════════════════════════════════════════════════════════
# SPA
# ══════════════════════════════════════════════════════════════
@app.get("/{full_path:path}", response_class=HTMLResponse)
async def serve_spa(full_path: str):
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Anomalies Dashboard đang khởi động...</h1>", status_code=503)

# ══════════════════════════════════════════════════════════════
# DEFAULT ROLES CATALOG
# ══════════════════════════════════════════════════════════════
def _default_roles() -> list:
    return [
        # Survivors
        {"name":"Thường Dân",         "faction":"Survivors","team":"Survivors","description":"Không có kỹ năng đặc biệt. Tồn tại đến cuối game là chiến thắng.","color":"#4ade80"},
        {"name":"Thám Trưởng",        "faction":"Survivors","team":"Survivors","description":"Điều tra một người mỗi đêm để biết phe của họ.","color":"#60a5fa"},
        {"name":"Cai Ngục",           "faction":"Survivors","team":"Survivors","description":"Giam cầm một người mỗi đêm. Có thể thẩm vấn và xử tử tù nhân.","color":"#f59e0b"},
        {"name":"Thị Trưởng",         "faction":"Survivors","team":"Survivors","description":"Có thể lộ diện để nhận 3 phiếu bầu. Rất mạnh nhưng nguy hiểm.","color":"#a78bfa"},
        {"name":"Trợ Lý Thị Trưởng", "faction":"Survivors","team":"Survivors","description":"Hỗ trợ Thị Trưởng và nhận quyền bầu cử đặc biệt.","color":"#c4b5fd"},
        {"name":"Thám Tử",            "faction":"Survivors","team":"Survivors","description":"Điều tra sâu hơn, nhận thêm thông tin về vai trò.","color":"#38bdf8"},
        {"name":"Pháp Quan",          "faction":"Survivors","team":"Survivors","description":"Giao tiếp với người đã chết để lấy thông tin.","color":"#94a3b8"},
        {"name":"Điệp Viên",          "faction":"Survivors","team":"Survivors","description":"Theo dõi ai đó và biết họ đã làm gì đêm qua.","color":"#34d399"},
        {"name":"Cảnh Sát",           "faction":"Survivors","team":"Survivors","description":"Bắn chết một người vào ban ngày. Chỉ 1 lần.","color":"#fb923c"},
        {"name":"Bẫy Thủ",           "faction":"Survivors","team":"Survivors","description":"Đặt bẫy để phát hiện và bắt Dị Thể.","color":"#84cc16"},
        {"name":"Kiến Trúc Sư",       "faction":"Survivors","team":"Survivors","description":"Xây dựng công trình phòng thủ cho người chơi khác.","color":"#06b6d4"},
        {"name":"Nhà Lưu Trữ",        "faction":"Survivors","team":"Survivors","description":"Bảo quản thông tin và bằng chứng qua các đêm.","color":"#8b5cf6"},
        {"name":"Phục Sinh Sư",       "faction":"Survivors","team":"Survivors","description":"Hồi sinh một người đã chết. Cực kỳ hiếm và mạnh.","color":"#ec4899"},
        {"name":"Giám Hộ Viên",       "faction":"Survivors","team":"Survivors","description":"Canh gác mục tiêu — kẻ tấn công sẽ bị tiêu diệt.","color":"#f97316"},
        {"name":"Tâm Lý Gia",         "faction":"Survivors","team":"Survivors","description":"Đọc tâm trí và phát hiện vai trò qua hành vi.","color":"#6366f1"},
        {"name":"Người Ngủ",          "faction":"Survivors","team":"Survivors","description":"Ngủ rất ngon. Nhưng có điều gì đó kỳ lạ xảy ra khi ngủ.","color":"#64748b"},
        {"name":"Dược Sĩ Điên",       "faction":"Survivors","team":"Survivors","description":"Tạo ra các loại thuốc ngẫu nhiên — có thể cứu người hoặc giết người.","color":"#ef4444"},
        {"name":"Người Báo Thù",      "faction":"Survivors","team":"Survivors","description":"Sau khi chết, có thể tiêu diệt kẻ đã giết mình.","color":"#dc2626"},
        # Anomalies
        {"name":"Dị Thể",               "faction":"Anomalies","team":"Anomalies","description":"Dị Thể cơ bản. Giết một người mỗi đêm để loại bỏ Survivors.","color":"#f87171"},
        {"name":"Người Hành Quyết",     "faction":"Anomalies","team":"Anomalies","description":"Dị Thể mạnh mẽ với khả năng xử tử đặc biệt.","color":"#ef4444"},
        {"name":"Lãnh Chúa",            "faction":"Anomalies","team":"Anomalies","description":"Chỉ huy các Dị Thể. Biết danh sách đồng đội.","color":"#dc2626"},
        {"name":"Nhà Vệ Sinh",          "faction":"Anomalies","team":"Anomalies","description":"Xóa di chúc và bằng chứng của nạn nhân.","color":"#b91c1c"},
        {"name":"Phát Tín Hiệu Giả",   "faction":"Anomalies","team":"Anomalies","description":"Gửi thông tin sai lệch cho Thám Tử và Thám Trưởng.","color":"#991b1b"},
        {"name":"Kẻ Hút Não",           "faction":"Anomalies","team":"Anomalies","description":"Điều khiển hành động của người chơi khác.","color":"#7f1d1d"},
        {"name":"Bóng Tối Kiến Trúc Sư","faction":"Anomalies","team":"Anomalies","description":"Dị Thể xây dựng bẫy để chống lại Survivors.","color":"#450a0a"},
        {"name":"Ký Sinh Thần Kinh",    "faction":"Anomalies","team":"Anomalies","description":"Ký sinh vào não nạn nhân và điều khiển từ xa.","color":"#fca5a5"},
        {"name":"Kẻ Rình Rập Lỗi",      "faction":"Anomalies","team":"Anomalies","description":"Theo dõi mục tiêu qua nhiều đêm rồi tấn công bất ngờ.","color":"#fecaca"},
        {"name":"Tên Trộm Thì Thầm",    "faction":"Anomalies","team":"Anomalies","description":"Nghe lén thông tin riêng tư và sử dụng chống lại Survivors.","color":"#fee2e2"},
        {"name":"Người Phát Sóng Tĩnh", "faction":"Anomalies","team":"Anomalies","description":"Gây nhiễu thông tin liên lạc trong team Survivors.","color":"#fef2f2"},
        {"name":"Người Cắt Xé",         "faction":"Anomalies","team":"Anomalies","description":"Vô hiệu hóa khả năng đặc biệt của nạn nhân.","color":"#ef4444"},
        {"name":"Kẻ Ăn Chân Lý",        "faction":"Anomalies","team":"Anomalies","description":"Tiên tri giả — cung cấp kết quả điều tra sai.","color":"#dc2626"},
        # Unknown
        {"name":"Sát Nhân Hàng Loạt","faction":"Unknown","team":"Unknown","description":"Chiến thắng một mình. Giết mọi người còn sống.","color":"#fbbf24"},
        {"name":"Kẻ Tâm Thần",       "faction":"Unknown","team":"Unknown","description":"Mục tiêu ẩn. Hoàn thành mục tiêu để thắng một mình.","color":"#f59e0b"},
        {"name":"AI Bị Hỏng",         "faction":"Unknown","team":"Unknown","description":"AI không còn tuân theo lập trình. Mục tiêu bí ẩn.","color":"#d97706"},
        {"name":"Đồng Hồ Tận Thế",   "faction":"Unknown","team":"Unknown","description":"Đếm ngược. Khi hết giờ, mọi người đều thua.","color":"#b45309"},
        {"name":"Người Dệt Giấc Mơ", "faction":"Unknown","team":"Unknown","description":"Điều khiển giấc mơ. Thắng khi gây đủ hỗn loạn.","color":"#92400e"},
        {"name":"Con Tàu Ma",          "faction":"Unknown","team":"Unknown","description":"Linh hồn lang thang. Thắng bằng cách khiến hai phe nghi ngờ nhau.","color":"#78350f"},
        {"name":"Con Sâu Lỗi",         "faction":"Unknown","team":"Unknown","description":"Ký sinh vào game. Thắng khi game bị hủy.","color":"#451a03"},
        {"name":"Kẻ Dệt Thời Gian",   "faction":"Unknown","team":"Unknown","description":"Thao túng thứ tự hành động và timeline của game.","color":"#fde68a"},
        # Event
        {"name":"Người Mù",                       "faction":"Event","team":"Event","description":"Không thể thấy username người khác.","color":"#a855f7"},
        {"name":"Người Giải Mật Mã",               "faction":"Event","team":"Event","description":"Giải mã các mật mã để nhận thông tin quan trọng.","color":"#9333ea"},
        {"name":"Người Kiểm Tra Chuyên Nghiệp",   "faction":"Event","team":"Event","description":"Vai trò test cho các server đặc biệt.","color":"#7c3aed"},
    ]

# ══════════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=False,
    )
