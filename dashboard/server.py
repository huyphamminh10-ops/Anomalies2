"""
dashboard/server.py — Anomalies Dashboard v2.5 (Integrated Architecture)
=========================================================================

KIẾN TRÚC TÍCH HỢP:
  • Bot Disnake và FastAPI chạy CÙNG event loop (qua bot_main.py).
  • app.state.bot → truy cập bot.guilds trực tiếp (không qua API riêng).
  • config_manager (PyMongo) → dùng chung với Bot, đọc/ghi cùng MongoDB.
  • database_tidb → lưu Feedback & Update Log vào TiDB (ID 15 ký tự).

CÁC VẤN ĐỀ ĐÃ SỬA:
  1. [Hình 1 trắng] Danh sách Server lấy từ bot.guilds (tên + icon thật).
  2. [MongoDB đồng nhất] Web dùng load_guild_config() / save_guild_config()
     từ config_manager → sửa trên Web là sửa thẳng vào DB mà Bot đọc.
  3. [TiDB Feedback] POST /api/dash/feedback lưu vào TiDB với ID 15 ký tự.
  4. [TiDB Update Log] POST /api/dash/admin/changelog lưu vào TiDB,
     chỉ BOT_OWNER_ID được phép, trả JSON lỗi chi tiết thay vì 500.
  5. [Lỗi kết nối] try-except mọi chỗ, trả {"error":..., "hint":...}.
  6. [render.yaml] startCommand: python bot_main.py (xem render.yaml).

ENTRY POINT: bot_main.py (không phải file này).
"""

from __future__ import annotations
import os as _os, sys as _sys
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
for _candidate in [_BASE_DIR, _os.path.dirname(_BASE_DIR)]:
    _core = _os.path.join(_candidate, "core")
    if _os.path.isdir(_core) and _core not in _sys.path:
        _sys.path.insert(0, _core)
del _os, _sys, _BASE_DIR, _candidate, _core


import asyncio
import collections
import hashlib
import hmac
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Deque, Optional

import disnake
import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

# ── Thêm thư mục gốc vào sys.path ─────────────────────────────────
_DASH_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT     = os.path.dirname(_DASH_DIR)
for _p in (_ROOT, _DASH_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config_manager   # noqa: E402 — dùng chung với Bot
import database_tidb    # noqa: E402 — TiDB cho Feedback & Update Log

# ── dashboard_routes (OAuth2, SPA, các route phụ) ─────────────────
try:
    from dashboard_routes import router as _dash_router, init_shared  # type: ignore
    _HAS_ROUTES = True
except ImportError:
    _HAS_ROUTES = False
    print("[server] CẢNH BÁO: Không tìm thấy dashboard_routes.py")

# ===========================================================================
# CONFIG
# ===========================================================================

TOKEN         : str = os.environ.get("DISCORD_TOKEN", "")
BOT_OWNER_ID  : int = int(os.environ.get("BOT_OWNER_ID", "1306441206296875099"))
_SECRET_KEY   : str = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
DISCORD_API         = "https://discord.com/api/v10"

MAX_LOG_ENTRIES  = 200
MAX_METRIC_POINTS = 120

if not TOKEN:
    print("[server] CẢNH BÁO: DISCORD_TOKEN chưa được đặt!")

# ===========================================================================
# IN-MEMORY STORES
# ===========================================================================

event_log       : Deque[dict] = collections.deque(maxlen=MAX_LOG_ENTRIES)
latency_history : Deque[dict] = collections.deque(maxlen=MAX_METRIC_POINTS)
_ws_clients     : set[WebSocket] = set()
_active_games   : dict = {}   # guild_id → GameEngine
_guilds_state   : dict = {}   # guild_id → trạng thái in-memory


def _log(kind: str, **payload) -> None:
    event_log.appendleft({"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **payload})


# ===========================================================================
# SESSION — Signed cookie (HMAC-SHA256, không cần Redis/DB)
# ===========================================================================

def _sign(data: str) -> str:
    return hmac.new(_SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()


def _set_session(response: Response, user_id: str, access_token: str,
                 username: str, avatar: str) -> None:
    payload = f"{user_id}|{access_token}|{username}|{avatar}"
    cookie  = f"{payload}||{_sign(payload)}"
    response.set_cookie("dash_session", cookie, httponly=True, samesite="lax", max_age=86_400 * 7)


def _get_session(request: Request) -> Optional[dict]:
    cookie = request.cookies.get("dash_session", "")
    if "||" not in cookie:
        return None
    payload, sig = cookie.rsplit("||", 1)
    if not hmac.compare_digest(_sign(payload), sig):
        return None
    parts = payload.split("|", 3)
    if len(parts) != 4:
        return None
    user_id, access_token, username, avatar = parts
    return {
        "user_id":      user_id,
        "access_token": access_token,
        "username":     username,
        "avatar":       avatar,
        "is_owner":     int(user_id) == BOT_OWNER_ID,
    }


def _require_auth(request: Request) -> dict:
    s = _get_session(request)
    if not s:
        raise HTTPException(401, "Chưa đăng nhập")
    return s


def _require_owner(request: Request) -> dict:
    s = _require_auth(request)
    if not s["is_owner"]:
        raise HTTPException(403, "Chỉ dành cho chủ bot")
    return s


# ===========================================================================
# HELPERS — MongoDB collection accessor
# ===========================================================================

def _col(name: str):
    """Trả về MongoDB collection. Thread-safe (PyMongo tự quản lý pool)."""
    db = config_manager._get_db()
    return db[name] if db is not None else None


# ===========================================================================
# BOT — được khởi động từ bot_main.py, không tạo mới ở đây.
# Nếu server.py chạy độc lập (uvicorn dashboard.server:app), tạo bot fallback.
# ===========================================================================

def _get_bot() -> Optional[disnake.AutoShardedInteractionBot]:
    """
    Lấy bot instance:
      1. Ưu tiên app.state.bot (được gán bởi bot_main.py — kiến trúc tích hợp).
      2. Fallback: dùng biến module-level (khi server.py chạy standalone).
    """
    # app.state.bot được gán sau khi lifespan chạy; dùng global fallback lúc đầu
    return _standalone_bot


# Bot fallback khi chạy standalone (không qua bot_main.py)
_standalone_bot: Optional[disnake.AutoShardedInteractionBot] = None


# ===========================================================================
# BACKGROUND TASK — metrics mỗi 60 giây
# ===========================================================================

async def _metrics_collector() -> None:
    bot = _get_bot()
    if bot is None:
        return
    await bot.wait_until_ready()
    while not bot.is_closed():
        latency_history.append({
            "ts":          datetime.now(timezone.utc).isoformat(),
            "latency_ms":  round(bot.latency * 1000, 2),
            "guild_count": len(bot.guilds),
            "shard_count": bot.shard_count or 1,
        })
        if _ws_clients:
            snapshot = latency_history[0]
            dead: set[WebSocket] = set()
            for ws in _ws_clients:
                try:
                    await ws.send_json({"event": "metrics", "data": snapshot})
                except Exception:
                    dead.add(ws)
            _ws_clients.difference_update(dead)
        await asyncio.sleep(60)


# ===========================================================================
# LIFESPAN — dùng khi server.py chạy standalone (uvicorn dashboard.server:app)
# Khi chạy qua bot_main.py, lifespan trong bot_main.py được dùng thay thế.
# ===========================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _standalone_bot

    # Nếu bot_main.py đã gán app.state.bot, dùng luôn
    if hasattr(app.state, "bot") and app.state.bot is not None:
        _standalone_bot = app.state.bot
        print("[server] Dùng bot từ app.state.bot (integrated mode).")
    elif TOKEN:
        # Standalone mode: tự tạo bot
        intents = disnake.Intents.default()
        intents.members = True
        intents.message_content = True
        _standalone_bot = disnake.AutoShardedInteractionBot(intents=intents)

        @_standalone_bot.event
        async def on_ready():
            _log("ready", bot_id=str(_standalone_bot.user.id), bot_name=str(_standalone_bot.user))
            print(f"[bot] Logged in as {_standalone_bot.user} (id={_standalone_bot.user.id})")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, config_manager.ensure_indexes)
            result = await loop.run_in_executor(None, database_tidb.ensure_tables)
            if not result["ok"]:
                print(f"[server] TiDB tables lỗi: {result.get('error')}")
            if _HAS_ROUTES:
                init_shared(bot=_standalone_bot, guilds=_guilds_state,
                            active_games=_active_games, game_stats={}, col_fn=_col)

        bot_task = asyncio.create_task(_standalone_bot.start(TOKEN), name="discord-bot")
    else:
        print("[server] DISCORD_TOKEN trống — bot không kết nối.")
        bot_task = None

    metrics_task = asyncio.create_task(_metrics_collector(), name="metrics-collector")

    # Truyền shared state vào dashboard_routes
    if _HAS_ROUTES and _standalone_bot:
        asyncio.create_task(_init_routes_when_ready(_standalone_bot))

    try:
        yield
    finally:
        metrics_task.cancel()
        try:
            await metrics_task
        except (asyncio.CancelledError, Exception):
            pass
        if "bot_task" in dir() and bot_task is not None:
            bot_task.cancel()
            try:
                await bot_task
            except (asyncio.CancelledError, Exception):
                pass
        if _standalone_bot and not _standalone_bot.is_closed():
            await _standalone_bot.close()


async def _init_routes_when_ready(bot_instance) -> None:
    """Chờ bot ready rồi mới init_shared (tránh race condition)."""
    await bot_instance.wait_until_ready()
    if _HAS_ROUTES:
        init_shared(bot=bot_instance, guilds=_guilds_state,
                    active_games=_active_games, game_stats={}, col_fn=_col)
        print("[server] dashboard_routes đã nhận shared state.")


# ===========================================================================
# FASTAPI APP
# ===========================================================================

app = FastAPI(title="Anomalies Dashboard", version="2.5.0", lifespan=lifespan)

if _HAS_ROUTES:
    app.include_router(_dash_router)

# ===========================================================================
# HELPERS — require bot ready / get guild
# ===========================================================================

def _active_bot() -> disnake.AutoShardedInteractionBot:
    """
    Lấy bot instance đang hoạt động.
    Ưu tiên app.state.bot (gán bởi bot_main.py) → _standalone_bot → lỗi.
    """
    b = getattr(app.state, "bot", None) or _standalone_bot
    if b is None or b.user is None:
        raise HTTPException(503, "Bot đang khởi động — vui lòng thử lại sau vài giây.")
    return b


def _get_guild(guild_id: int) -> disnake.Guild:
    b = _active_bot()
    g = b.get_guild(guild_id)
    if g is None:
        raise HTTPException(404, "Không tìm thấy server hoặc bot chưa tham gia server này.")
    return g


# ===========================================================================
# PYDANTIC MODELS
# ===========================================================================

class SendMessageBody(BaseModel):
    guild_id:   int
    channel_id: int
    content:    str
    tts:        bool = False


class UpdateStatusBody(BaseModel):
    status:        str = "online"
    activity_type: str = "playing"
    activity_name: str = ""


# ===========================================================================
# GET /api/dash/guilds — danh sách server từ bot.guilds (FIX icon trắng)
# ===========================================================================
#
# VẤN ĐỀ CŨ: dashboard_routes.py lấy icon từ Discord API của USER → CDN hash
#   đôi khi khác với hash thật của guild → ảnh trắng.
# FIX: Lấy trực tiếp từ bot.get_guild() → guild.icon.url luôn đúng.
# Route này OVERRIDE route trong dashboard_routes (đăng ký trực tiếp trên app).

@app.get("/api/dash/guilds")
@app.get("/api/dash/me/guilds")
async def api_guilds_from_bot(request: Request) -> JSONResponse:
    """
    Danh sách server mà user là thành viên VÀ bot đang quản lý.

    FIX ICON TRẮNG:
      - Lấy tên, icon từ bot.get_guild() (object Guild thật từ Discord Gateway)
        thay vì từ Discord REST API của user (đôi khi hash khác nhau).
      - Nếu bot chưa ready (user_guilds rỗng), fallback về Discord API của user.

    FIX CONFIG:
      - Kiểm tra guild có config trong MongoDB không (load_guild_config).
      - Chỉ trả các guild mà bot đang phục vụ.
    """
    s = _require_auth(request)

    # Lấy danh sách guild của user từ Discord API
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(
                f"{DISCORD_API}/users/@me/guilds",
                headers={"Authorization": f"Bearer {s['access_token']}"},
            )
        user_guilds = resp.json() if resp.status_code == 200 else []
        if not isinstance(user_guilds, list):
            user_guilds = []
    except Exception as e:
        print(f"[api_guilds] Lỗi fetch user guilds: {e}")
        user_guilds = []

    b      = getattr(app.state, "bot", None) or _standalone_bot
    result = []

    for g in user_guilds:
        gid  = str(g.get("id", ""))
        if not gid:
            continue

        perms      = int(g.get("permissions", 0))
        is_manager = bool(perms & 0x20) or bool(g.get("owner", False))

        # ── Ưu tiên lấy tên + icon từ bot.guilds (chính xác 100%) ──
        discord_guild = b.get_guild(int(gid)) if b and b.user else None

        if discord_guild:
            # Bot đang quản lý server này → lấy thông tin thật
            name = discord_guild.name
            icon = str(discord_guild.icon.url) if discord_guild.icon else None
        else:
            # Bot không ở server này → kiểm tra có config trong MongoDB không
            loop = asyncio.get_event_loop()
            cfg  = await loop.run_in_executor(None, config_manager.load_guild_config, gid)
            # Nếu chỉ trả default_config (không có record) thì bỏ qua
            cfg_col = _col("guild_configs")
            has_record = False
            if cfg_col:
                try:
                    has_record = cfg_col.count_documents({"guild_id": gid}, limit=1) > 0
                except Exception:
                    pass
            if not has_record:
                continue  # Không hiển thị server mà bot không quản lý
            # Fallback về thông tin từ Discord API của user
            name      = g.get("name", gid)
            icon_hash = g.get("icon")
            icon      = f"https://cdn.discordapp.com/icons/{gid}/{icon_hash}.png" if icon_hash else None

        result.append({
            "id":         gid,
            "name":       name,
            "icon":       icon,          # URL đầy đủ, không bao giờ là hash rời
            "is_manager": is_manager,
            "member_count": discord_guild.member_count if discord_guild else None,
        })

    return JSONResponse(result)


# ===========================================================================
# GET /api/dash/guild/{guild_id}/config — đọc config từ MongoDB qua config_manager
# ===========================================================================

@app.get("/api/dash/guild/{guild_id}/config")
async def api_guild_config(guild_id: str, request: Request) -> JSONResponse:
    """
    Đọc config của guild từ MongoDB qua config_manager.load_guild_config().
    Cùng driver mà Bot đang dùng → đảm bảo nhất quán dữ liệu.
    """
    _require_auth(request)
    try:
        loop = asyncio.get_event_loop()
        cfg  = await loop.run_in_executor(None, config_manager.load_guild_config, guild_id)
        return JSONResponse(cfg)
    except Exception as e:
        print(f"[api_guild_config] Lỗi: {e}")
        raise HTTPException(500, f"Lỗi đọc config: {type(e).__name__}: {e}")


# ===========================================================================
# POST /api/dash/guild/{guild_id}/config — lưu config vào MongoDB qua config_manager
# ===========================================================================

@app.post("/api/dash/guild/{guild_id}/config")
async def api_update_config(guild_id: str, request: Request) -> JSONResponse:
    """
    Lưu config guild vào MongoDB qua config_manager.save_guild_config().
    Bot sẽ tự detect thay đổi qua cache invalidation (last_updated).
    → Sửa trên Web = sửa thẳng vào DB mà Bot đang đọc.

    Quyền: user phải có MANAGE_GUILD trên server đó, hoặc là BOT_OWNER_ID.
    """
    s = _require_auth(request)

    # Kiểm tra quyền qua Discord API
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(
                f"{DISCORD_API}/users/@me/guilds",
                headers={"Authorization": f"Bearer {s['access_token']}"},
            )
        user_guilds = resp.json() if resp.status_code == 200 else []
    except Exception as e:
        print(f"[api_update_config] Lỗi fetch user guilds: {e}")
        user_guilds = []

    guild = next((g for g in user_guilds if str(g.get("id")) == guild_id), None)
    if not guild and not s["is_owner"]:
        raise HTTPException(403, "Bạn không thuộc server này")

    if guild:
        perms      = int(guild.get("permissions", 0))
        is_manager = bool(perms & 0x20) or bool(guild.get("owner", False))
        if not is_manager and not s["is_owner"]:
            raise HTTPException(403, f"Bạn không có quyền MANAGE_GUILD trên server {guild.get('name', guild_id)}")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Request body không phải JSON hợp lệ")

    # Lọc chỉ các field hợp lệ (dựa trên default_config)
    allowed = set(config_manager.default_config().keys())
    payload = {k: v for k, v in data.items() if k in allowed}

    if not payload:
        raise HTTPException(400, "Không có field hợp lệ nào để cập nhật")

    # Lấy tên guild từ bot.guilds nếu có
    b             = getattr(app.state, "bot", None) or _standalone_bot
    discord_guild = b.get_guild(int(guild_id)) if b and b.user else None
    guild_name    = discord_guild.name if discord_guild else (guild.get("name") if guild else guild_id)

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: config_manager.save_guild_config(guild_id, payload, guild_name=guild_name)
        )
        return JSONResponse({"ok": True, "updated_fields": list(payload.keys())})
    except Exception as e:
        print(f"[api_update_config] Lỗi save: {e}")
        raise HTTPException(500, f"Lỗi lưu config: {type(e).__name__}: {e}")


# ===========================================================================
# POST /api/dash/feedback — lưu vào TiDB với ID 15 ký tự
# ===========================================================================

@app.post("/api/dash/feedback")
async def post_feedback(request: Request) -> JSONResponse:
    """
    Nhận feedback từ user đã đăng nhập và lưu vào TiDB.

    Thay đổi so với v2.4:
      - Không lưu vào MongoDB (feedbacks collection) nữa.
      - Lưu vào TiDB với PK là ID 15 ký tự ngẫu nhiên.
      - Trả lỗi chi tiết (error + hint) thay vì HTTP 500 im lặng.
    """
    s = _require_auth(request)

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Request body không phải JSON hợp lệ")

    content = str(data.get("content", "")).strip()[:2000]
    images  = [str(u) for u in data.get("images", [])[:5] if u]

    if not content and not images:
        raise HTTPException(400, "Nội dung trống — cần có text hoặc ảnh")

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: database_tidb.insert_feedback(
            user_id  = s["user_id"],
            username = s["username"],
            avatar   = s["avatar"],
            content  = content,
            images   = images,
        )
    )

    if not result.get("ok"):
        # Trả lỗi chi tiết thay vì 500 generic
        return JSONResponse(
            status_code=503,
            content={
                "ok":    False,
                "error": result.get("error", "Lỗi không xác định"),
                "hint":  result.get("hint", "Kiểm tra kết nối TiDB và IP Whitelist"),
            }
        )

    return JSONResponse({"ok": True, "id": result.get("id")})


# ===========================================================================
# GET /api/dash/admin/feedbacks — lấy danh sách feedback từ TiDB
# ===========================================================================

@app.get("/api/dash/admin/feedbacks")
async def get_admin_feedbacks(request: Request, limit: int = 100, offset: int = 0) -> JSONResponse:
    """Lấy danh sách feedback từ TiDB. Owner only."""
    _require_owner(request)
    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: database_tidb.get_feedbacks(limit=limit, offset=offset)
    )
    if not result.get("ok"):
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": result.get("error"), "hint": result.get("hint")}
        )
    return JSONResponse(result["items"])


# ===========================================================================
# POST /api/dash/admin/feedback/reply — owner trả lời feedback trong TiDB
# ===========================================================================

@app.post("/api/dash/admin/feedback/reply")
async def reply_feedback(request: Request) -> JSONResponse:
    """Owner trả lời một feedback theo ID (15 ký tự). Owner only."""
    _require_owner(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Request body không phải JSON hợp lệ")

    feedback_id = str(data.get("id", "")).strip()
    reply_text  = str(data.get("reply", "")).strip()[:1000]

    if not feedback_id:
        raise HTTPException(400, "Thiếu feedback id")

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: database_tidb.reply_feedback(feedback_id, reply_text)
    )
    if not result.get("ok"):
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": result.get("error"), "hint": result.get("hint", "")}
        )
    return JSONResponse({"ok": True})


# ===========================================================================
# POST /api/dash/admin/changelog — lưu update log vào TiDB (owner only)
# ===========================================================================

@app.post("/api/dash/admin/changelog")
async def post_changelog(request: Request) -> JSONResponse:
    """
    Đăng update log — chỉ BOT_OWNER_ID.
    Lưu vào TiDB với PK là ID 15 ký tự ngẫu nhiên.
    Trả lỗi chi tiết thay vì 500 generic (đặc biệt khi TiDB IP chưa được whitelist).
    """
    s = _require_owner(request)   # Throw 403 nếu không phải owner

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Request body không phải JSON hợp lệ")

    title   = str(data.get("title",   "")).strip()[:200]
    content = str(data.get("content", "")).strip()[:5000]
    version = str(data.get("version", "")).strip()[:20]

    if not title or not content:
        raise HTTPException(400, "Thiếu tiêu đề hoặc nội dung")

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: database_tidb.insert_update_log(
            user_id = s["user_id"],
            title   = title,
            content = content,
            version = version,
        )
    )

    if not result.get("ok"):
        return JSONResponse(
            status_code=503,
            content={
                "ok":    False,
                "error": result.get("error", "Lỗi không xác định"),
                "hint":  result.get("hint", "Kiểm tra kết nối TiDB và IP Whitelist"),
            }
        )

    return JSONResponse({"ok": True, "id": result.get("id")})


# ===========================================================================
# GET /api/dash/changelog — lấy update log từ TiDB
# ===========================================================================

@app.get("/api/dash/changelog")
async def get_changelog(request: Request, limit: int = 30) -> JSONResponse:
    """Lấy danh sách update log từ TiDB. Mọi user đã đăng nhập."""
    _require_auth(request)
    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: database_tidb.get_update_logs(limit=limit)
    )
    if not result.get("ok"):
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": result.get("error"), "hint": result.get("hint")}
        )
    return JSONResponse(result["items"])


# ===========================================================================
# GET /api/dash/stats — thống kê tổng quan
# ===========================================================================

@app.get("/api/dash/stats")
async def dash_stats() -> JSONResponse:
    """
    Thống kê: guilds, bans từ MongoDB; feedbacks, changelogs từ TiDB.
    db_ok kiểm tra cả MongoDB và TiDB.
    """
    b          = getattr(app.state, "bot", None) or _standalone_bot
    mongo_ok   = config_manager._get_db() is not None
    tidb_ok    = False
    total_guilds = total_bans = total_feedbacks = total_changelogs = 0
    active_games_count = len(_active_games)

    if mongo_ok:
        loop = asyncio.get_event_loop()
        try:
            def _mongo_counts():
                db = config_manager._get_db()
                if db is None:
                    return (0, 0)
                return (
                    db["guild_configs"].count_documents({}),
                    db["bans"].count_documents({}),
                )
            total_guilds, total_bans = await loop.run_in_executor(None, _mongo_counts)
        except Exception as e:
            print(f"[stats] Lỗi MongoDB count: {e}")
            mongo_ok = False

    # Đếm từ TiDB (chạy trong thread)
    loop = asyncio.get_event_loop()
    try:
        total_feedbacks, total_changelogs = await loop.run_in_executor(
            None,
            lambda: (database_tidb.count_feedbacks(), database_tidb.count_update_logs())
        )
        tidb_ok = True
    except Exception as e:
        print(f"[stats] Lỗi TiDB count: {e}")

    return JSONResponse({
        "total_guilds":     total_guilds,
        "active_games":     active_games_count,
        "total_bans":       total_bans,
        "total_feedbacks":  total_feedbacks,
        "total_changelogs": total_changelogs,
        "db_ok":            mongo_ok,
        "tidb_ok":          tidb_ok,
        # Tương thích với code cũ
        "serverCount":      total_guilds,
        "banCount":         total_bans,
        "feedbackCount":    total_feedbacks,
    })


# ===========================================================================
# GET /api/dash/info — tổng quan bot
# ===========================================================================

@app.get("/api/dash/info")
async def dash_info() -> JSONResponse:
    b = _active_bot()
    return JSONResponse({
        "bot": {
            "id":            str(b.user.id),
            "name":          b.user.name,
            "discriminator": b.user.discriminator,
            "avatar":        str(b.user.avatar.url) if b.user.avatar else None,
            "shard_count":   b.shard_count,
        },
        "stats": {
            "guild_count": len(b.guilds),
            "user_count":  sum(g.member_count or 0 for g in b.guilds),
            "latency_ms":  round(b.latency * 1000, 2),
        },
        "guilds": [
            {
                "id":           str(g.id),
                "name":         g.name,
                "member_count": g.member_count,
                "icon":         str(g.icon.url) if g.icon else None,
            }
            for g in b.guilds
        ],
    })


# ===========================================================================
# GET /api/dash/guild/{guild_id} — chi tiết guild từ bot.guilds
# ===========================================================================

@app.get("/api/dash/guild/{guild_id}")
async def guild_info(guild_id: int) -> JSONResponse:
    guild = _get_guild(guild_id)
    return JSONResponse({
        "id":           str(guild.id),
        "name":         guild.name,
        "member_count": guild.member_count,
        "icon":         str(guild.icon.url) if guild.icon else None,
        "owner_id":     str(guild.owner_id),
        "channels": [
            {"id": str(c.id), "name": c.name, "type": str(c.type)}
            for c in guild.channels
        ],
        "roles": [
            {"id": str(r.id), "name": r.name, "color": str(r.color)}
            for r in guild.roles
        ],
    })


# ===========================================================================
# GET /api/dash/members/{guild_id}
# ===========================================================================

@app.get("/api/dash/members/{guild_id}")
async def guild_members(guild_id: int, q: str = "", limit: int = 50) -> JSONResponse:
    guild  = _get_guild(guild_id)
    limit  = min(max(1, limit), 500)
    q_low  = q.lower()
    members = [
        m for m in guild.members
        if q_low in m.display_name.lower() or q_low in str(m).lower()
    ][:limit]
    return JSONResponse({
        "guild_id":      str(guild_id),
        "total_matched": len(members),
        "members": [
            {
                "id":           str(m.id),
                "username":     str(m),
                "display_name": m.display_name,
                "bot":          m.bot,
                "avatar":       str(m.avatar.url) if m.avatar else None,
                "joined_at":    m.joined_at.isoformat() if m.joined_at else None,
                "roles":        [str(r.id) for r in m.roles if r.name != "@everyone"],
                "top_role":     m.top_role.name,
            }
            for m in members
        ],
    })


# ===========================================================================
# GET /api/dash/channels/{guild_id}
# ===========================================================================

@app.get("/api/dash/channels/{guild_id}")
async def guild_channels(guild_id: int) -> JSONResponse:
    guild       = _get_guild(guild_id)
    channels_out = []
    for ch in sorted(guild.channels, key=lambda c: c.position):
        entry: dict = {"id": str(ch.id), "name": ch.name, "type": str(ch.type), "position": ch.position}
        if isinstance(ch, disnake.TextChannel):
            entry.update({"topic": ch.topic, "slowmode_delay": ch.slowmode_delay,
                          "nsfw": ch.nsfw, "last_message_id": str(ch.last_message_id) if ch.last_message_id else None})
        elif isinstance(ch, disnake.VoiceChannel):
            entry.update({"bitrate": ch.bitrate, "user_limit": ch.user_limit})
        elif isinstance(ch, disnake.CategoryChannel):
            entry["child_count"] = len(ch.channels)
        channels_out.append(entry)
    return JSONResponse({"guild_id": str(guild_id), "channels": channels_out})


# ===========================================================================
# GET /api/dash/roles/{guild_id}
# ===========================================================================

@app.get("/api/dash/roles/{guild_id}")
async def guild_roles(guild_id: int) -> JSONResponse:
    guild     = _get_guild(guild_id)
    roles_out = []
    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        roles_out.append({
            "id":           str(role.id),
            "name":         role.name,
            "color":        str(role.color),
            "hoist":        role.hoist,
            "mentionable":  role.mentionable,
            "position":     role.position,
            "managed":      role.managed,
            "member_count": sum(1 for m in guild.members if role in m.roles),
            "permissions":  {p: v for p, v in role.permissions},
        })
    return JSONResponse({"guild_id": str(guild_id), "roles": roles_out})


# ===========================================================================
# POST /api/dash/message
# ===========================================================================

@app.post("/api/dash/message")
async def send_message(body: SendMessageBody) -> JSONResponse:
    b       = _active_bot()
    channel = b.get_channel(body.channel_id)
    if channel is None:
        raise HTTPException(404, "Không tìm thấy kênh.")
    if not isinstance(channel, (disnake.TextChannel, disnake.Thread)):
        raise HTTPException(400, "Kênh đích không phải text channel.")
    if not channel.permissions_for(channel.guild.me).send_messages:
        raise HTTPException(403, "Bot không có quyền gửi tin nhắn vào kênh này.")
    if len(body.content) > 2000:
        raise HTTPException(400, "Nội dung vượt quá 2000 ký tự.")
    msg = await channel.send(body.content, tts=body.tts)
    _log("api_message_sent", channel_id=str(body.channel_id), guild_id=str(body.guild_id), message_id=str(msg.id))
    return JSONResponse({"ok": True, "message_id": str(msg.id)})


# ===========================================================================
# PUT /api/dash/status
# ===========================================================================

_ACTIVITY_MAP = {
    "playing":   disnake.ActivityType.playing,
    "listening": disnake.ActivityType.listening,
    "watching":  disnake.ActivityType.watching,
    "competing": disnake.ActivityType.competing,
}
_STATUS_MAP = {
    "online":    disnake.Status.online,
    "idle":      disnake.Status.idle,
    "dnd":       disnake.Status.dnd,
    "invisible": disnake.Status.invisible,
}


@app.put("/api/dash/status")
async def update_status(body: UpdateStatusBody) -> JSONResponse:
    b        = _active_bot()
    status   = _STATUS_MAP.get(body.status)
    if status is None:
        raise HTTPException(400, f"Status '{body.status}' không hợp lệ.")
    act_type = _ACTIVITY_MAP.get(body.activity_type)
    if act_type is None:
        raise HTTPException(400, f"activity_type '{body.activity_type}' không hợp lệ.")
    activity = disnake.Activity(type=act_type, name=body.activity_name) if body.activity_name else None
    await b.change_presence(status=status, activity=activity)
    _log("status_changed", status=body.status, activity_type=body.activity_type, activity_name=body.activity_name)
    return JSONResponse({"ok": True, "status": body.status})


# ===========================================================================
# GET /api/dash/logs, /api/dash/metrics
# ===========================================================================

@app.get("/api/dash/logs")
async def get_logs(kind: str = "", limit: int = 50) -> JSONResponse:
    limit   = min(max(1, limit), MAX_LOG_ENTRIES)
    entries = [e for e in event_log if not kind or e.get("kind") == kind][:limit]
    return JSONResponse({"total": len(entries), "entries": entries})


@app.get("/api/dash/metrics")
async def get_metrics() -> JSONResponse:
    b = _active_bot()
    return JSONResponse({
        "current": {
            "latency_ms":  round(b.latency * 1000, 2),
            "guild_count": len(b.guilds),
            "uptime_since": event_log[-1]["ts"] if event_log else None,
        },
        "history": list(latency_history),
    })


# ===========================================================================
# WebSocket /ws/stats
# ===========================================================================

@app.websocket("/ws/stats")
async def ws_stats(websocket: WebSocket) -> None:
    await websocket.accept()
    _ws_clients.add(websocket)
    b = getattr(app.state, "bot", None) or _standalone_bot
    if b and b.user:
        await websocket.send_json({"event": "connected", "data": {
            "bot_name":   str(b.user),
            "latency_ms": round(b.latency * 1000, 2),
            "guild_count": len(b.guilds),
        }})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


# ===========================================================================
# GET /health
# ===========================================================================

@app.get("/health")
async def health() -> JSONResponse:
    b        = getattr(app.state, "bot", None) or _standalone_bot
    mongo_ok = config_manager._get_db() is not None
    return JSONResponse({
        "status":      "ok",
        "bot_ready":   b.user is not None if b else False,
        "latency_ms":  round(b.latency * 1000, 2) if (b and b.user) else None,
        "guild_count": len(b.guilds) if (b and b.user) else 0,
        "db_connected": mongo_ok,
        "ws_clients":  len(_ws_clients),
        "log_entries": len(event_log),
    })
