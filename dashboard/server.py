"""
dashboard/server.py — Anomalies Dashboard v2.4
Single-Process Architecture: FastAPI + Disnake bot chạy chung một event loop.

Kiến trúc:
  - lifespan() khởi động bot.start(TOKEN) bằng asyncio.create_task()
  - Web + Bot dùng chung event loop → bot.guilds luôn sẵn sàng cho Web
  - dashboard_routes.py được mount vào đây với shared state đầy đủ
  - config_manager._get_db() dùng PyMongo đồng bộ trong thread pool
    (gọi qua run_in_executor để không block event loop)

Sửa lỗi:
  1. Bot + Web một tiến trình → /api/dash/guilds lấy từ bot.guilds thật
  2. /api/dash/stats trả đúng field: total_guilds, active_games,
     total_bans, total_feedbacks, total_changelogs, db_ok
  3. POST /api/dash/feedback và /api/dash/admin/changelog bọc try-except
     chi tiết, trả 500 có message thay vì im lặng
  4. render.yaml startCommand dùng python -m uvicorn
"""

from __future__ import annotations

import asyncio
import collections
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Deque

import disnake
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ── Thêm thư mục gốc vào sys.path để import dashboard_routes, config_manager
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config_manager  # noqa: E402  (sync PyMongo)

# dashboard_routes nằm trong thư mục gốc (cạnh app.py)
try:
    from dashboard_routes import router as _dash_router, init_shared  # type: ignore
    _HAS_ROUTES = True
except ImportError:
    _HAS_ROUTES = False
    print("[server] CẢNH BÁO: Không tìm thấy dashboard_routes.py — các route /api/dash/* sẽ bị thiếu.")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TOKEN: str = os.environ.get("DISCORD_TOKEN", "")
if not TOKEN:
    print("[server] CẢNH BÁO: Biến môi trường DISCORD_TOKEN chưa được đặt!")

MAX_LOG_ENTRIES: int = 200
MAX_METRIC_POINTS: int = 120  # ~2 giờ với 1 mẫu/phút

# ---------------------------------------------------------------------------
# In-memory stores (dùng chung trong cùng process)
# ---------------------------------------------------------------------------

event_log: Deque[dict] = collections.deque(maxlen=MAX_LOG_ENTRIES)
latency_history: Deque[dict] = collections.deque(maxlen=MAX_METRIC_POINTS)
_ws_clients: set[WebSocket] = set()

# Shared state được truyền vào dashboard_routes
# active_games và guilds_state được bot events cập nhật
_active_games: dict = {}   # guild_id -> GameEngine (nếu có)
_guilds_state: dict = {}   # guild_id -> {"state": ..., "players_join_order": [...], ...}


def _log(kind: str, **payload) -> None:
    event_log.appendleft(
        {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **payload}
    )


def _col(name: str):
    """Trả về MongoDB collection theo tên. Thread-safe (PyMongo tự quản lý pool)."""
    db = config_manager._get_db()
    return db[name] if db is not None else None


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = disnake.Intents.default()
intents.members = True
intents.message_content = True

bot = disnake.AutoShardedInteractionBot(intents=intents)


@bot.event
async def on_ready() -> None:
    _log("ready", bot_id=str(bot.user.id), bot_name=str(bot.user))
    print(f"[bot] Logged in as {bot.user} (id={bot.user.id})")
    print(f"[bot] Đang quản lý {len(bot.guilds)} server(s).")

    # Khởi tạo MongoDB indexes (chạy trong thread để không block loop)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, config_manager.ensure_indexes)

    # Truyền shared state sang dashboard_routes sau khi bot sẵn sàng
    if _HAS_ROUTES:
        init_shared(
            bot=bot,
            guilds=_guilds_state,
            active_games=_active_games,
            game_stats={},
            col_fn=_col,
        )
        print("[server] dashboard_routes đã nhận shared state từ bot.")


@bot.event
async def on_guild_join(guild: disnake.Guild) -> None:
    _log("guild_join", guild_id=str(guild.id), guild_name=guild.name)


@bot.event
async def on_guild_remove(guild: disnake.Guild) -> None:
    _log("guild_leave", guild_id=str(guild.id), guild_name=guild.name)
    _guilds_state.pop(str(guild.id), None)


@bot.event
async def on_member_join(member: disnake.Member) -> None:
    _log(
        "member_join",
        guild_id=str(member.guild.id),
        user_id=str(member.id),
        username=str(member),
    )


@bot.event
async def on_member_remove(member: disnake.Member) -> None:
    _log(
        "member_leave",
        guild_id=str(member.guild.id),
        user_id=str(member.id),
        username=str(member),
    )


@bot.event
async def on_message(message: disnake.Message) -> None:
    if message.author.bot:
        return
    _log(
        "message",
        guild_id=str(message.guild.id) if message.guild else None,
        channel_id=str(message.channel.id),
        user_id=str(message.author.id),
        preview=message.content[:80],
    )


# ---------------------------------------------------------------------------
# Background task — thu thập metrics mỗi 60 giây
# ---------------------------------------------------------------------------

async def _metrics_collector() -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        latency_history.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "latency_ms": round(bot.latency * 1000, 2),
                "guild_count": len(bot.guilds),
                "shard_count": bot.shard_count or 1,
            }
        )
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


# ---------------------------------------------------------------------------
# Lifespan — Single event loop: bot + web cùng chạy
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Khởi động bot.start() bằng create_task để bot và web dùng chung
    event loop. Web có thể truy cập bot.guilds trực tiếp mà không cần IPC.
    """
    if not TOKEN:
        print("[server] DISCORD_TOKEN trống — bot sẽ không kết nối Discord.")
        bot_task = None
    else:
        bot_task = asyncio.create_task(bot.start(TOKEN), name="discord-bot")

    metrics_task = asyncio.create_task(_metrics_collector(), name="metrics-collector")

    try:
        yield
    finally:
        metrics_task.cancel()
        try:
            await metrics_task
        except (asyncio.CancelledError, Exception):
            pass

        if bot_task is not None:
            bot_task.cancel()
            try:
                await bot_task
            except (asyncio.CancelledError, Exception):
                pass
            if not bot.is_closed():
                await bot.close()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Anomalies Dashboard", version="2.4.0", lifespan=lifespan)

# Mount dashboard_routes (OAuth2, /api/dash/*, /dashboard SPA)
if _HAS_ROUTES:
    app.include_router(_dash_router)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_bot_ready() -> None:
    if bot.user is None:
        raise HTTPException(
            status_code=503,
            detail="Bot đang khởi động — vui lòng thử lại sau vài giây.",
        )


def _get_guild(guild_id: int) -> disnake.Guild:
    _require_bot_ready()
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy server hoặc bot chưa tham gia server này.",
        )
    return guild


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SendMessageBody(BaseModel):
    guild_id: int
    channel_id: int
    content: str
    tts: bool = False


class UpdateStatusBody(BaseModel):
    status: str = "online"        # online | idle | dnd | invisible
    activity_type: str = "playing"  # playing | listening | watching | competing
    activity_name: str = ""


# ---------------------------------------------------------------------------
# /api/dash/info — tổng quan bot (giữ nguyên cho tương thích)
# ---------------------------------------------------------------------------

@app.get("/api/dash/info")
async def dash_info() -> JSONResponse:
    _require_bot_ready()
    guilds = [
        {
            "id": str(g.id),
            "name": g.name,
            "member_count": g.member_count,
            "icon": str(g.icon.url) if g.icon else None,
        }
        for g in bot.guilds
    ]
    return JSONResponse(
        {
            "bot": {
                "id": str(bot.user.id),
                "name": bot.user.name,
                "discriminator": bot.user.discriminator,
                "avatar": str(bot.user.avatar.url) if bot.user.avatar else None,
                "shard_count": bot.shard_count,
            },
            "stats": {
                "guild_count": len(bot.guilds),
                "user_count": sum(g.member_count or 0 for g in bot.guilds),
                "latency_ms": round(bot.latency * 1000, 2),
            },
            "guilds": guilds,
        }
    )


# ---------------------------------------------------------------------------
# OVERRIDE /api/dash/stats — fix field names cho index.html
#
# index.html đọc:
#   stats.total_guilds, stats.active_games, stats.total_bans,
#   stats.total_feedbacks, stats.total_changelogs, stats.db_ok
#
# dashboard_routes.py (cũ) trả: serverCount, playerCount, banCount, feedbackCount
# → File này override lại để map đúng.
# ---------------------------------------------------------------------------

@app.get("/api/dash/stats")
async def dash_stats_override() -> JSONResponse:
    """
    Thống kê tổng quan — trả đúng field mà index.html mong đợi.
    Đây là override của route trong dashboard_routes.py (FastAPI ưu tiên route
    đăng ký trước, nhưng include_router thêm sau app.get nên route này thắng).

    Nếu dashboard_routes chưa được mount, route này vẫn hoạt động.
    """
    db_ok = config_manager._get_db() is not None
    total_guilds = total_bans = total_feedbacks = total_changelogs = active_games_count = 0

    if db_ok:
        loop = asyncio.get_event_loop()
        try:
            def _fetch_counts():
                db = config_manager._get_db()
                if db is None:
                    return (0, 0, 0, 0)
                return (
                    db["guild_configs"].count_documents({}),
                    db["bans"].count_documents({}),
                    db["feedbacks"].count_documents({}),
                    db["changelogs"].count_documents({}),
                )
            total_guilds, total_bans, total_feedbacks, total_changelogs = \
                await loop.run_in_executor(None, _fetch_counts)
        except Exception as e:
            print(f"[stats] Lỗi đếm documents: {e}")
            db_ok = False

    # active_games lấy từ bot.guilds thật (real-time)
    active_games_count = len(_active_games)

    return JSONResponse({
        "total_guilds":     total_guilds,
        "active_games":     active_games_count,
        "total_bans":       total_bans,
        "total_feedbacks":  total_feedbacks,
        "total_changelogs": total_changelogs,
        "db_ok":            db_ok,
        # Giữ cả tên cũ để tương thích nếu có code khác dùng
        "serverCount":      total_guilds,
        "banCount":         total_bans,
        "feedbackCount":    total_feedbacks,
    })


# ---------------------------------------------------------------------------
# OVERRIDE /api/dash/feedback — POST với try-except chi tiết
# ---------------------------------------------------------------------------

@app.post("/api/dash/feedback")
async def post_feedback(request) -> JSONResponse:
    """
    Nhận feedback từ người dùng đã đăng nhập.
    Bọc try-except đầy đủ, trả lỗi chi tiết thay vì 500 im lặng.
    """
    # Đọc session từ cookie (tái sử dụng logic từ dashboard_routes)
    from fastapi import Request as FRequest
    req: FRequest = request

    cookie = req.cookies.get("dash_session", "")
    if "||" not in cookie:
        raise HTTPException(401, "Chưa đăng nhập")

    import hashlib
    import hmac as _hmac
    _SECRET_KEY = os.environ.get("SESSION_SECRET", "")
    payload, sig = cookie.rsplit("||", 1)

    def _sign(data: str) -> str:
        return _hmac.new(_SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()

    if not _hmac.compare_digest(_sign(payload), sig):
        raise HTTPException(401, "Session không hợp lệ")

    parts = payload.split("|", 3)
    if len(parts) != 4:
        raise HTTPException(401, "Session bị hỏng")
    user_id, _token, username, avatar = parts

    try:
        data = await req.json()
    except Exception:
        raise HTTPException(400, "Request body không phải JSON hợp lệ")

    content = str(data.get("content", "")).strip()[:2000]
    images  = [str(u) for u in data.get("images", [])[:5] if u]

    if not content and not images:
        raise HTTPException(400, "Nội dung trống — cần có text hoặc ảnh")

    loop = asyncio.get_event_loop()
    try:
        def _insert():
            fb_col = _col("feedbacks")
            if fb_col is None:
                raise RuntimeError("Không kết nối được MongoDB — kiểm tra MONGO_URI")
            fb_col.insert_one({
                "user_id":    user_id,
                "username":   username,
                "avatar":     avatar,
                "content":    content,
                "images":     images,
                "reply":      None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

        await loop.run_in_executor(None, _insert)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        print(f"[feedback] Lỗi insert MongoDB: {e}")
        raise HTTPException(500, f"Lỗi lưu feedback vào database: {type(e).__name__}: {e}")

    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# OVERRIDE /api/dash/admin/changelog — POST với try-except chi tiết
# ---------------------------------------------------------------------------

@app.post("/api/dash/admin/changelog")
async def post_changelog(request) -> JSONResponse:
    """
    Đăng update/changelog — owner only, try-except chi tiết.
    """
    from fastapi import Request as FRequest
    req: FRequest = request

    # Kiểm tra owner (tái sử dụng logic session)
    cookie = req.cookies.get("dash_session", "")
    if "||" not in cookie:
        raise HTTPException(401, "Chưa đăng nhập")

    import hashlib
    import hmac as _hmac
    _SECRET_KEY = os.environ.get("SESSION_SECRET", "")
    payload, sig = cookie.rsplit("||", 1)

    def _sign(data: str) -> str:
        return _hmac.new(_SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()

    if not _hmac.compare_digest(_sign(payload), sig):
        raise HTTPException(401, "Session không hợp lệ")

    parts = payload.split("|", 3)
    if len(parts) != 4:
        raise HTTPException(401, "Session bị hỏng")
    user_id = parts[0]

    BOT_OWNER_ID = 1306441206296875099
    if int(user_id) != BOT_OWNER_ID:
        raise HTTPException(403, "Chỉ dành cho chủ bot")

    try:
        data = await req.json()
    except Exception:
        raise HTTPException(400, "Request body không phải JSON hợp lệ")

    title   = str(data.get("title",   "")).strip()[:200]
    content = str(data.get("content", "")).strip()[:5000]
    version = str(data.get("version", "")).strip()[:20]

    if not title or not content:
        raise HTTPException(400, "Thiếu tiêu đề hoặc nội dung")

    loop = asyncio.get_event_loop()
    try:
        def _insert():
            cl_col = _col("changelogs")
            if cl_col is None:
                raise RuntimeError("Không kết nối được MongoDB — kiểm tra MONGO_URI")
            cl_col.insert_one({
                "title":      title,
                "content":    content,
                "version":    version,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

        await loop.run_in_executor(None, _insert)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        print(f"[changelog] Lỗi insert MongoDB: {e}")
        raise HTTPException(500, f"Lỗi lưu changelog vào database: {type(e).__name__}: {e}")

    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# /api/dash/guild/{guild_id} — chi tiết guild từ bot.guilds thật
# ---------------------------------------------------------------------------

@app.get("/api/dash/guild/{guild_id}")
async def guild_info(guild_id: int) -> JSONResponse:
    guild = _get_guild(guild_id)
    return JSONResponse(
        {
            "id": str(guild.id),
            "name": guild.name,
            "member_count": guild.member_count,
            "icon": str(guild.icon.url) if guild.icon else None,
            "owner_id": str(guild.owner_id),
            "channels": [
                {"id": str(c.id), "name": c.name, "type": str(c.type)}
                for c in guild.channels
            ],
            "roles": [
                {"id": str(r.id), "name": r.name, "color": str(r.color)}
                for r in guild.roles
            ],
        }
    )


# ---------------------------------------------------------------------------
# /api/dash/members/{guild_id} — tìm kiếm thành viên
# ---------------------------------------------------------------------------

@app.get("/api/dash/members/{guild_id}")
async def guild_members(guild_id: int, q: str = "", limit: int = 50) -> JSONResponse:
    guild = _get_guild(guild_id)
    limit = min(max(1, limit), 500)

    members = [
        m for m in guild.members
        if q.lower() in m.display_name.lower() or q.lower() in str(m).lower()
    ][:limit]

    return JSONResponse(
        {
            "guild_id": str(guild_id),
            "total_matched": len(members),
            "members": [
                {
                    "id": str(m.id),
                    "username": str(m),
                    "display_name": m.display_name,
                    "bot": m.bot,
                    "avatar": str(m.avatar.url) if m.avatar else None,
                    "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                    "roles": [str(r.id) for r in m.roles if r.name != "@everyone"],
                    "top_role": m.top_role.name,
                }
                for m in members
            ],
        }
    )


# ---------------------------------------------------------------------------
# /api/dash/channels/{guild_id} — danh sách kênh chi tiết
# ---------------------------------------------------------------------------

@app.get("/api/dash/channels/{guild_id}")
async def guild_channels(guild_id: int) -> JSONResponse:
    guild = _get_guild(guild_id)

    channels_out = []
    for ch in sorted(guild.channels, key=lambda c: c.position):
        entry: dict = {
            "id": str(ch.id),
            "name": ch.name,
            "type": str(ch.type),
            "position": ch.position,
        }
        if isinstance(ch, disnake.TextChannel):
            entry.update(
                {
                    "topic": ch.topic,
                    "slowmode_delay": ch.slowmode_delay,
                    "nsfw": ch.nsfw,
                    "last_message_id": str(ch.last_message_id) if ch.last_message_id else None,
                }
            )
        elif isinstance(ch, disnake.VoiceChannel):
            entry.update({"bitrate": ch.bitrate, "user_limit": ch.user_limit})
        elif isinstance(ch, disnake.CategoryChannel):
            entry["child_count"] = len(ch.channels)
        channels_out.append(entry)

    return JSONResponse({"guild_id": str(guild_id), "channels": channels_out})


# ---------------------------------------------------------------------------
# /api/dash/roles/{guild_id} — danh sách role đầy đủ
# ---------------------------------------------------------------------------

@app.get("/api/dash/roles/{guild_id}")
async def guild_roles(guild_id: int) -> JSONResponse:
    guild = _get_guild(guild_id)

    roles_out = []
    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        perms = {p: v for p, v in role.permissions}
        roles_out.append(
            {
                "id": str(role.id),
                "name": role.name,
                "color": str(role.color),
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "position": role.position,
                "managed": role.managed,
                "member_count": sum(1 for m in guild.members if role in m.roles),
                "permissions": perms,
            }
        )

    return JSONResponse({"guild_id": str(guild_id), "roles": roles_out})


# ---------------------------------------------------------------------------
# POST /api/dash/message — gửi tin nhắn qua bot
# ---------------------------------------------------------------------------

@app.post("/api/dash/message")
async def send_message(body: SendMessageBody) -> JSONResponse:
    _require_bot_ready()

    channel = bot.get_channel(body.channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy kênh.")
    if not isinstance(channel, (disnake.TextChannel, disnake.Thread)):
        raise HTTPException(status_code=400, detail="Kênh đích không phải text channel.")
    if not channel.permissions_for(channel.guild.me).send_messages:
        raise HTTPException(status_code=403, detail="Bot không có quyền gửi tin nhắn vào kênh này.")
    if len(body.content) > 2000:
        raise HTTPException(status_code=400, detail="Nội dung vượt quá 2000 ký tự.")

    msg = await channel.send(body.content, tts=body.tts)
    _log(
        "api_message_sent",
        channel_id=str(body.channel_id),
        guild_id=str(body.guild_id),
        message_id=str(msg.id),
    )
    return JSONResponse(
        {"ok": True, "message_id": str(msg.id), "channel_id": str(body.channel_id)}
    )


# ---------------------------------------------------------------------------
# PUT /api/dash/status — đổi presence bot
# ---------------------------------------------------------------------------

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
    _require_bot_ready()

    status = _STATUS_MAP.get(body.status)
    if status is None:
        raise HTTPException(
            status_code=400,
            detail=f"Status '{body.status}' không hợp lệ. Dùng: online, idle, dnd, invisible.",
        )

    activity_type = _ACTIVITY_MAP.get(body.activity_type)
    if activity_type is None:
        raise HTTPException(
            status_code=400,
            detail=f"activity_type '{body.activity_type}' không hợp lệ.",
        )

    activity = (
        disnake.Activity(type=activity_type, name=body.activity_name)
        if body.activity_name
        else None
    )
    await bot.change_presence(status=status, activity=activity)

    _log(
        "status_changed",
        status=body.status,
        activity_type=body.activity_type,
        activity_name=body.activity_name,
    )
    return JSONResponse({"ok": True, "status": body.status, "activity": body.activity_name})


# ---------------------------------------------------------------------------
# GET /api/dash/logs — rolling event log
# ---------------------------------------------------------------------------

@app.get("/api/dash/logs")
async def get_logs(kind: str = "", limit: int = 50) -> JSONResponse:
    limit = min(max(1, limit), MAX_LOG_ENTRIES)
    entries = [e for e in event_log if not kind or e.get("kind") == kind][:limit]
    return JSONResponse({"total": len(entries), "entries": entries})


# ---------------------------------------------------------------------------
# GET /api/dash/metrics — lịch sử latency
# ---------------------------------------------------------------------------

@app.get("/api/dash/metrics")
async def get_metrics() -> JSONResponse:
    _require_bot_ready()
    return JSONResponse(
        {
            "current": {
                "latency_ms": round(bot.latency * 1000, 2),
                "guild_count": len(bot.guilds),
                "uptime_since": event_log[-1]["ts"] if event_log else None,
            },
            "history": list(latency_history),
        }
    )


# ---------------------------------------------------------------------------
# WebSocket /ws/stats — push live metrics
# ---------------------------------------------------------------------------

@app.websocket("/ws/stats")
async def ws_stats(websocket: WebSocket) -> None:
    await websocket.accept()
    _ws_clients.add(websocket)

    if bot.user is not None:
        await websocket.send_json(
            {
                "event": "connected",
                "data": {
                    "bot_name": str(bot.user),
                    "latency_ms": round(bot.latency * 1000, 2),
                    "guild_count": len(bot.guilds),
                },
            }
        )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


# ---------------------------------------------------------------------------
# GET /api/dash/audit/{guild_id} — audit log Discord
# ---------------------------------------------------------------------------

_AUDIT_ACTION_MAP: dict[str, disnake.AuditLogAction] = {
    "guild_update":        disnake.AuditLogAction.guild_update,
    "channel_create":      disnake.AuditLogAction.channel_create,
    "channel_update":      disnake.AuditLogAction.channel_update,
    "channel_delete":      disnake.AuditLogAction.channel_delete,
    "kick":                disnake.AuditLogAction.kick,
    "member_prune":        disnake.AuditLogAction.member_prune,
    "ban":                 disnake.AuditLogAction.ban,
    "unban":               disnake.AuditLogAction.unban,
    "member_update":       disnake.AuditLogAction.member_update,
    "member_role_update":  disnake.AuditLogAction.member_role_update,
    "member_move":         disnake.AuditLogAction.member_move,
    "member_disconnect":   disnake.AuditLogAction.member_disconnect,
    "role_create":         disnake.AuditLogAction.role_create,
    "role_update":         disnake.AuditLogAction.role_update,
    "role_delete":         disnake.AuditLogAction.role_delete,
    "invite_create":       disnake.AuditLogAction.invite_create,
    "invite_delete":       disnake.AuditLogAction.invite_delete,
    "message_delete":      disnake.AuditLogAction.message_delete,
    "message_bulk_delete": disnake.AuditLogAction.message_bulk_delete,
    "message_pin":         disnake.AuditLogAction.message_pin,
    "message_unpin":       disnake.AuditLogAction.message_unpin,
    "bot_add":             disnake.AuditLogAction.bot_add,
    "thread_create":       disnake.AuditLogAction.thread_create,
    "thread_update":       disnake.AuditLogAction.thread_update,
    "thread_delete":       disnake.AuditLogAction.thread_delete,
}


@app.get("/api/dash/audit/{guild_id}")
async def guild_audit(
    guild_id: int,
    limit: int = 50,
    action: str = "",
) -> JSONResponse:
    guild = _get_guild(guild_id)

    if not guild.me.guild_permissions.view_audit_log:
        raise HTTPException(status_code=403, detail="Bot thiếu quyền View Audit Log.")

    limit = min(max(1, limit), 100)
    action_filter: disnake.AuditLogAction | None = None

    if action:
        action_filter = _AUDIT_ACTION_MAP.get(action)
        if action_filter is None:
            raise HTTPException(
                status_code=400,
                detail=f"Action '{action}' không hợp lệ. Dùng: {', '.join(_AUDIT_ACTION_MAP)}",
            )

    entries = []
    async for entry in guild.audit_logs(limit=limit, action=action_filter):
        target_info: dict | None = None
        if isinstance(entry.target, disnake.Member):
            target_info = {"type": "member", "id": str(entry.target.id), "name": str(entry.target)}
        elif isinstance(entry.target, disnake.User):
            target_info = {"type": "user", "id": str(entry.target.id), "name": str(entry.target)}
        elif isinstance(entry.target, (disnake.TextChannel, disnake.VoiceChannel, disnake.CategoryChannel)):
            target_info = {"type": "channel", "id": str(entry.target.id), "name": entry.target.name}
        elif isinstance(entry.target, disnake.Role):
            target_info = {"type": "role", "id": str(entry.target.id), "name": entry.target.name}
        elif entry.target is not None:
            target_info = {"type": "unknown", "id": str(getattr(entry.target, "id", "?"))}

        changes: list[dict] = []
        for change in entry.changes.before.__dict__:
            before_val = getattr(entry.changes.before, change, None)
            after_val = getattr(entry.changes.after, change, None)
            changes.append({"field": change, "before": str(before_val), "after": str(after_val)})

        entries.append(
            {
                "id": str(entry.id),
                "action": str(entry.action).replace("AuditLogAction.", ""),
                "user": {
                    "id": str(entry.user.id) if entry.user else None,
                    "name": str(entry.user) if entry.user else None,
                },
                "target": target_info,
                "reason": entry.reason,
                "created_at": entry.created_at.isoformat(),
                "changes": changes,
            }
        )

    return JSONResponse(
        {
            "guild_id": str(guild_id),
            "action_filter": action or None,
            "count": len(entries),
            "entries": entries,
            "valid_actions": list(_AUDIT_ACTION_MAP.keys()),
        }
    )


# ---------------------------------------------------------------------------
# GET /health — health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> JSONResponse:
    db_ok = config_manager._get_db() is not None
    return JSONResponse(
        {
            "status": "ok",
            "bot_ready": bot.user is not None,
            "latency_ms": round(bot.latency * 1000, 2) if bot.user else None,
            "guild_count": len(bot.guilds) if bot.user else 0,
            "db_connected": db_ok,
            "ws_clients": len(_ws_clients),
            "log_entries": len(event_log),
        }
    )
