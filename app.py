# ==============================
# app.py — Anomalies v3.0 (Unified Bot + Web Architecture)
#
# KIẾN TRÚC MỚI:
#   - Bot và Web chạy CÙNG event loop (không còn threading riêng)
#   - Uvicorn dùng uvicorn.Config + uvicorn.Server (không blocking)
#   - asyncio.create_task() khởi chạy Uvicorn trong on_ready của Bot
#   - app.state.bot = bot → Dashboard truy cập bot.guilds trực tiếp từ RAM
#   - config_manager (PyMongo) dùng chung với Bot
#   - database_tidb (TiDB) cho Feedback & Update Log
#   - Lắng nghe 0.0.0.0:PORT (lấy từ os.environ.get('PORT', 8080))
#
# FIX LỖI:
#   - [404] Dashboard được mount trực tiếp vào cùng FastAPI app với Bot
#   - [Dữ liệu trắng] bot.guilds lấy từ RAM thật, không qua API riêng
#   - [Connection Refused] Uvicorn bind 0.0.0.0 thay vì localhost
#   - [Blocking] uvicorn.Server.serve() chạy qua asyncio.create_task()
#
# Cách chạy:
#   python app.py                   ← entry point duy nhất
#   PORT=8000 python app.py         ← local dev
#   DISCORD_TOKEN=... python app.py ← với token
# ==============================

from __future__ import annotations

try:
    import ujson as _json_lib
except ImportError:
    import json as _json_lib  # type: ignore

import aiohttp
import asyncio
import certifi
import glob
import importlib
import inspect
import os
import random
import socket
import string
import sys
import time as _time_module
import traceback
import urllib.request

import disnake
import uvicorn
from disnake.ext import commands, tasks
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

# ── Đảm bảo thư mục gốc trong sys.path ───────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ── Thêm dashboard/ vào sys.path ──────────────────────────────────
_DASH_DIR = os.path.join(_HERE, "dashboard")
if _DASH_DIR not in sys.path:
    sys.path.insert(0, _DASH_DIR)

# ── Import các module nội bộ ──────────────────────────────────────
from config_manager import (
    load_guild_config, save_guild_config,
    load_all_configs,
    load_guild_lobby, save_guild_lobby,
    get_guild_status,
    ensure_indexes,
    save_active_players, load_active_players, clear_active_players,
    _get_db as _cm_get_db,
)
from event_roles_loader import get_loader as get_event_loader
from updater import (
    handle_owner_dm,
    greet_owner_on_setup,
    send_post_update_embeds,
    BOT_OWNER_ID,
    register_emergency_callback,
)
import database_tidb

# ── Cogs Settings ─────────────────────────────────────────────────
try:
    from cogs.settings import check_command_permission as _check_cmd_perm
except ImportError:
    def _check_cmd_perm(*args, **kwargs): return True

# ══════════════════════════════════════════════════════════════════
# CONFIG — Biến môi trường
# ══════════════════════════════════════════════════════════════════

TOKEN        = os.environ.get("DISCORD_TOKEN", "")
PORT         = int(os.environ.get("PORT", 8080))
_IS_HF       = bool(os.environ.get("SPACE_ID"))

if not TOKEN:
    print("[app] CẢNH BÁO: DISCORD_TOKEN chưa được đặt!")
if _IS_HF:
    print(f"[app] Đang chạy trên Hugging Face Space: {os.environ.get('SPACE_ID')}")
else:
    print(f"[app] Môi trường: Local/Render — Port={PORT}")

# ══════════════════════════════════════════════════════════════════
# GAME STATE CONSTANTS
# ══════════════════════════════════════════════════════════════════

MIN_PLAYERS       = 5
MAX_PLAYERS       = 65
COUNTDOWN_DEFAULT = 200
_EDIT_INTERVAL    = 1.05  # giây tối thiểu giữa 2 lần edit


class GameState:
    WAITING   = "WAITING"
    COUNTDOWN = "COUNTDOWN"
    FULL_FAST = "FULL_FAST"
    IN_GAME   = "IN_GAME"


# Shared game state (Bot và Web cùng đọc/ghi)
guilds:             dict = {}
active_games:       dict = {}
game_stats:         dict = {"table_content": "Đang khởi tạo..."}
_config_cache:      dict = {}
_config_cache_time: dict = {}
_pending_role_maps: dict = {}

# ══════════════════════════════════════════════════════════════════
# DISCORD BOT
# ══════════════════════════════════════════════════════════════════

intents = disnake.Intents.all()
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)

session: aiohttp.ClientSession | None = None
_shutting_down: bool       = False
_READY_BOOTSTRAPPED: bool  = False

# ══════════════════════════════════════════════════════════════════
# FASTAPI APP — Tích hợp Dashboard
# ══════════════════════════════════════════════════════════════════

app = FastAPI(title="Anomalies Bot + Dashboard", version="3.0.0")

# CORS — cho phép dashboard gọi API
_ALLOW_ORIGINS = [
    "https://anomalies2.onrender.com",
    "http://localhost:8000",
    "http://localhost:8080",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8080",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gán bot vào app.state ngay (sẽ được gán lại sau khi bot ready)
app.state.bot = bot

# ── Mount Dashboard routes ─────────────────────────────────────────
_DASHBOARD_OK = False
try:
    from dashboard_routes import router as _dash_router, init_shared as _dash_init
    app.include_router(_dash_router)
    _DASHBOARD_OK = True
    print("[Dashboard] Routes từ dashboard_routes.py đã được mount.")
except ImportError as _e:
    print(f"[Dashboard] Bỏ qua dashboard_routes.py: {_e}")

# ── Mount dashboard/server.py routes (nếu có) ─────────────────────
try:
    _dash_server_path = os.path.join(_DASH_DIR, "server.py")
    if os.path.isfile(_dash_server_path):
        _spec   = importlib.util.spec_from_file_location("dashboard.server", _dash_server_path)
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["dashboard.server"] = _module
        _spec.loader.exec_module(_module)

        # Gán bot vào module level
        _module.bot = bot
        if hasattr(_module, "app"):
            _dash_server_app: FastAPI = _module.app
            _dash_server_app.state.bot = bot
            # Mount tất cả routes từ dashboard/server.py (trừ docs/openapi)
            for _route in _dash_server_app.routes:
                _route_path = getattr(_route, "path", "")
                if _route_path not in ("/openapi.json", "/docs", "/redoc", "/"):
                    app.routes.append(_route)
            print("[Dashboard] Routes từ dashboard/server.py đã được mount.")
except Exception as _de:
    print(f"[Dashboard] Bỏ qua dashboard/server.py: {_de}")

# ── Serve dashboard/index.html ─────────────────────────────────────
_DASH_HTML_PATH = os.path.join(_DASH_DIR, "index.html")

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
@app.get("/dashboard/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard(request: Request, full_path: str = ""):
    """Serve SPA dashboard HTML."""
    if os.path.isfile(_DASH_HTML_PATH):
        with open(_DASH_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Dashboard chưa được cấu hình.</h1>", status_code=404)


# ══════════════════════════════════════════════════════════════════
# API ENDPOINTS — Bot data (Dashboard lấy trực tiếp từ RAM)
# ══════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    """Root redirect về dashboard nếu có, còn lại health check."""
    if _DASHBOARD_OK or os.path.isfile(_DASH_HTML_PATH):
        return RedirectResponse("/dashboard", status_code=302)
    return {"status": "ok", "bot": "Anomalies", "version": "3.0.0"}


@app.head("/")
async def root_head():
    return JSONResponse({"status": "ok"})


@app.get("/ping")
async def ping():
    """Keep-alive cho UptimeRobot."""
    _bot: commands.Bot = app.state.bot
    return JSONResponse({
        "status":       "ok",
        "bot_ready":    _bot.user is not None if _bot else False,
        "guild_count":  len(_bot.guilds) if _bot and _bot.user else 0,
        "latency_ms":   round(_bot.latency * 1000, 2) if _bot and _bot.user else -1,
        "environment":  "hugging_face" if _IS_HF else "render",
    })


@app.get("/get-table")
async def get_table():
    """Backward-compat: trả game_stats."""
    return game_stats


@app.get("/health")
async def health():
    _bot: commands.Bot = app.state.bot
    return {
        "status":      "ok",
        "bot_ready":   _bot.user is not None if _bot else False,
        "guild_count": len(_bot.guilds) if _bot and _bot.user else 0,
    }


# ── API: Danh sách Server (lấy trực tiếp từ bot.guilds trong RAM) ──

@app.get("/api/guilds")
async def api_guilds():
    """
    Trả danh sách server Bot đang online.
    Dữ liệu lấy trực tiếp từ bot.guilds → KHÔNG bao giờ trắng khi bot online.
    """
    _bot: commands.Bot = app.state.bot
    if _bot is None or _bot.user is None:
        return JSONResponse({"ok": False, "error": "Bot chưa ready"}, status_code=503)

    result = []
    for guild in _bot.guilds:
        icon_url = str(guild.icon.url) if guild.icon else None
        result.append({
            "id":          str(guild.id),
            "name":        guild.name,
            "icon":        icon_url,
            "member_count": guild.member_count,
        })
    return {"ok": True, "guilds": result, "count": len(result)}


@app.get("/api/guilds/{guild_id}/config")
async def api_guild_config(guild_id: str):
    """Lấy config của một guild từ MongoDB qua config_manager."""
    try:
        cfg = load_guild_config(guild_id)
        return {"ok": True, "config": cfg}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/guilds/{guild_id}/config")
async def api_save_guild_config(guild_id: str, request: Request):
    """Lưu config guild vào MongoDB qua config_manager."""
    try:
        body = await request.json()
        save_guild_config(guild_id, body)
        # Xóa cache để bot đọc config mới ngay
        _config_cache.pop(str(guild_id), None)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── API: Bot Avatar ────────────────────────────────────────────────

@app.get("/api/bot/info")
async def api_bot_info():
    """Thông tin Bot: avatar, tên, số server."""
    _bot: commands.Bot = app.state.bot
    if _bot is None or _bot.user is None:
        return JSONResponse({"ok": False, "error": "Bot chưa ready"}, status_code=503)
    return {
        "ok":          True,
        "id":          str(_bot.user.id),
        "name":        str(_bot.user.name),
        "avatar":      str(_bot.user.avatar.url) if _bot.user.avatar else None,
        "guild_count": len(_bot.guilds),
        "latency_ms":  round(_bot.latency * 1000, 2),
    }


# ══════════════════════════════════════════════════════════════════
# API: FEEDBACK — Lưu vào TiDB với ID 15 ký tự
# ══════════════════════════════════════════════════════════════════

class _FeedbackBody(dict):
    pass


@app.post("/api/feedback")
async def api_post_feedback(request: Request):
    """
    Nhận POST feedback, tạo ID 15 ký tự bằng generate_tidb_id(),
    lưu vào TiDB, trả về JSON chứa ID xác nhận.
    """
    try:
        body     = await request.json()
        user_id  = str(body.get("user_id", "anonymous"))
        username = str(body.get("username", "Ẩn danh"))
        avatar   = str(body.get("avatar", ""))
        content  = str(body.get("content", ""))
        images   = body.get("images", [])
        if not isinstance(images, list):
            images = []

        if not content and not images:
            raise HTTPException(400, "Nội dung hoặc hình ảnh không được để trống.")

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: database_tidb.insert_feedback(user_id, username, avatar, content, images),
        )

        if result["ok"]:
            return JSONResponse({"ok": True, "id": result["id"], "message": "Feedback đã được lưu."})
        else:
            return JSONResponse(
                {"ok": False, "error": result.get("error"), "hint": result.get("hint")},
                status_code=500,
            )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))


@app.get("/api/feedback")
async def api_get_feedbacks(limit: int = 50, offset: int = 0):
    """Lấy danh sách feedback từ TiDB."""
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: database_tidb.get_feedbacks(limit, offset),
    )
    if result["ok"]:
        return result
    raise HTTPException(500, result.get("error", "TiDB error"))


# ══════════════════════════════════════════════════════════════════
# UTIL FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def _to_int(value, default=None):
    """Ép kiểu ID về int an toàn."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def get_cached_config(guild_id: str) -> dict:
    import time
    gid = str(guild_id)
    now = time.monotonic()
    if gid not in _config_cache or now - _config_cache_time.get(gid, 0) > 30:
        _config_cache[gid] = load_guild_config(gid)
        _config_cache_time[gid] = now
    return _config_cache[gid]


def invalidate_config_cache(guild_id: str):
    _config_cache.pop(str(guild_id), None)


def cfg_min_players(cfg: dict) -> int:
    return cfg.get("min_players_to_start") or cfg.get("min_players", MIN_PLAYERS)


def cfg_max_players(cfg: dict) -> int:
    return cfg.get("max_players", MAX_PLAYERS)


def cfg_countdown(cfg: dict) -> int:
    return cfg.get("countdown_seconds") or cfg.get("countdown_time", COUNTDOWN_DEFAULT)


def get_guild_state(guild_id) -> dict:
    gid = str(guild_id)
    if gid not in guilds:
        cfg = get_cached_config(gid)
        guilds[gid] = {
            "state":              GameState.WAITING,
            "countdown_time":     cfg_countdown(cfg),
            "lobby_message":      None,
            "current_page":       0,
            "players_join_order": [],
            "lobby_lock":         None,
            "original_nicknames": {},
            "loop_started":       False,
            "dirty":              False,
            "last_edit_time":     0.0,
            "_backoff_until":     0.0,
            "is_active":          False,
        }
    return guilds[gid]


def format_time(seconds: int) -> str:
    m = seconds // 60
    s = seconds % 60
    return f"{m:02}:{s:02}"


def progress_bar(current: int, total: int, length: int = 20) -> str:
    if total <= 0:
        return "░" * length
    filled = max(0, min(length, int(length * (total - current) / total)))
    return "█" * filled + "░" * (length - filled)


def paginate_players(players, page):
    per_page = 11
    return players[page * per_page: (page + 1) * per_page]


# ══════════════════════════════════════════════════════════════════
# LOBBY EMBED & VIEW
# ══════════════════════════════════════════════════════════════════

def build_embed(gs: dict, guild_id=None) -> disnake.Embed:
    cfg           = get_cached_config(str(guild_id)) if guild_id else {}
    min_p         = cfg_min_players(cfg)
    max_p         = cfg_max_players(cfg)
    countdown_max = cfg_countdown(cfg)

    state          = gs["state"]
    countdown_time = max(0, gs["countdown_time"])
    current_page   = gs["current_page"]
    players        = gs["players_join_order"]
    total_pages    = max(1, (len(players) - 1) // 11 + 1)

    embed = disnake.Embed()

    if state == GameState.WAITING:
        embed.title       = "🔴 》ANOMALIES《"
        embed.description = f"Đang chờ đủ {min_p} người..."
        embed.color       = disnake.Color.green()
    elif state in (GameState.COUNTDOWN, GameState.FULL_FAST):
        embed.title = "🔴 》ANOMALIES《"
        embed.color = disnake.Color.gold()
        embed.add_field(
            name="⏳ Thời Gian",
            value=f"{format_time(countdown_time)}\n{progress_bar(countdown_time, countdown_max)}",
            inline=False,
        )
        if state == GameState.FULL_FAST:
            embed.add_field(name="🔒 Trạng Thái", value="ĐÃ ĐẦY – Không nhận thêm người", inline=False)
    elif state == GameState.IN_GAME:
        embed.title       = "🔥 TRẬN ĐẤU ĐANG DIỄN RA"
        embed.description = "Vui lòng chờ trận này kết thúc."
        embed.color       = disnake.Color.purple()

    players_page = paginate_players(players, current_page)
    if players_page:
        text = "\n".join(
            f"{i}. {p.display_name}"
            for i, p in enumerate(players_page, start=1 + current_page * 11)
        )
        embed.add_field(name=f"👥 Người Chơi ({len(players)}/{max_p})", value=text, inline=False)

    embed.set_footer(text=f"Trang {current_page + 1}/{total_pages}")
    return embed


def _get_lobby_lock(gs: dict) -> asyncio.Lock:
    if gs.get("lobby_lock") is None:
        gs["lobby_lock"] = asyncio.Lock()
    return gs["lobby_lock"]


async def update_lobby(gs: dict, guild_id: str):
    """Cập nhật embed lobby (rate-limit safe)."""
    import time
    msg = gs.get("lobby_message")
    if msg is None:
        return
    now = time.monotonic()
    if now - gs.get("last_edit_time", 0) < _EDIT_INTERVAL:
        gs["dirty"] = True
        return
    try:
        embed = build_embed(gs, guild_id=guild_id)
        view  = build_lobby_view(guild_id)
        await msg.edit(embed=embed, view=view)
        gs["last_edit_time"] = time.monotonic()
        gs["dirty"]          = False
    except disnake.NotFound:
        gs["lobby_message"] = None
    except disnake.HTTPException:
        gs["dirty"] = True


class JoinButton(disnake.ui.Button):
    def __init__(self):
        super().__init__(
            label="✋ Tham Gia",
            style=disnake.ButtonStyle.success,
            custom_id="lobby_join_button",
            emoji="🎮",
        )

    async def callback(self, interaction: disnake.Interaction):
        guild_id   = str(interaction.guild_id)
        raw_config = get_cached_config(guild_id)
        gs         = get_guild_state(guild_id)
        member     = interaction.user

        if gs.get("is_active") or gs["state"] == GameState.IN_GAME:
            return await interaction.response.send_message(
                "❌ Trận đấu đang diễn ra, bạn không thể tham gia lúc này.", ephemeral=True
            )

        max_p = cfg_max_players(raw_config)
        if len(gs["players_join_order"]) >= max_p:
            return await interaction.response.send_message("❌ Sảnh đã đầy người!", ephemeral=True)

        async with _get_lobby_lock(gs):
            if member in gs["players_join_order"]:
                return await interaction.response.send_message("✅ Bạn đã ở trong sảnh rồi!", ephemeral=True)
            gs["players_join_order"].append(member)
            save_active_players(guild_id, [m.id for m in gs["players_join_order"]])

        player_count = len(gs["players_join_order"])
        min_p        = cfg_min_players(raw_config)

        if player_count >= max_p:
            gs["state"]          = GameState.FULL_FAST
            gs["countdown_time"] = 10
        elif player_count >= min_p and gs["state"] == GameState.WAITING:
            gs["state"]          = GameState.COUNTDOWN
            gs["countdown_time"] = cfg_countdown(raw_config)

        await update_lobby(gs, guild_id=guild_id)
        await interaction.response.send_message(
            f"✅ **{member.display_name}** đã tham gia sảnh!", ephemeral=True
        )


class LeaveButton(disnake.ui.Button):
    def __init__(self):
        super().__init__(
            label="🚪 Rời Sảnh",
            style=disnake.ButtonStyle.danger,
            custom_id="lobby_leave_button",
            emoji="🚶",
        )

    async def callback(self, interaction: disnake.Interaction):
        guild_id   = str(interaction.guild_id)
        raw_config = get_cached_config(guild_id)
        gs         = get_guild_state(guild_id)
        member     = interaction.user

        if gs.get("is_active") or gs["state"] == GameState.IN_GAME:
            return await interaction.response.send_message("❌ Trận đấu đang diễn ra.", ephemeral=True)

        async with _get_lobby_lock(gs):
            if member not in gs["players_join_order"]:
                return await interaction.response.send_message("❌ Bạn chưa ở trong sảnh.", ephemeral=True)
            gs["players_join_order"].remove(member)
            save_active_players(guild_id, [m.id for m in gs["players_join_order"]])

        player_count = len(gs["players_join_order"])
        min_p        = cfg_min_players(raw_config)

        if gs["state"] == GameState.FULL_FAST:
            gs["state"]          = GameState.COUNTDOWN
            gs["countdown_time"] = 60
        if gs["state"] == GameState.COUNTDOWN and player_count < min_p:
            gs["state"]          = GameState.WAITING
            gs["countdown_time"] = cfg_countdown(raw_config)

        await update_lobby(gs, guild_id=guild_id)
        await interaction.response.send_message(
            f"👋 **{member.display_name}** đã rời sảnh.", ephemeral=True
        )


def build_lobby_view(guild_id: str) -> disnake.ui.View:
    cfg   = get_cached_config(str(guild_id))
    vc_id = _to_int(cfg.get("voice_channel_id"))
    view  = disnake.ui.View(timeout=None)

    if vc_id:
        guild_id_int = int(guild_id)
        view.add_item(disnake.ui.Button(
            label="Tham Gia Tại Kênh Thoại",
            style=disnake.ButtonStyle.link,
            url=f"https://discord.com/channels/{guild_id_int}/{vc_id}",
            emoji="🔊",
        ))
    else:
        view.add_item(JoinButton())
        view.add_item(LeaveButton())
    return view


# ══════════════════════════════════════════════════════════════════
# BACKGROUND TASKS
# ══════════════════════════════════════════════════════════════════

@tasks.loop(seconds=30)
async def update_game_board():
    global game_stats, session
    if _shutting_down:
        return
    if session is None or session.closed:
        return
    try:
        async with session.get(
            f"http://127.0.0.1:{PORT}/get-table",
            timeout=aiohttp.ClientTimeout(total=0.8),
        ) as resp:
            if resp.status == 200:
                data = await resp.json(loads=_json_lib.loads)
                game_stats.update(data)
    except Exception:
        pass


@update_game_board.before_loop
async def startup_check():
    await bot.wait_until_ready()


async def _init_guild(guild_id: str, text_channel) -> None:
    """Khởi tạo guild khi bot ready."""
    gs = get_guild_state(guild_id)
    try:
        embed = build_embed(gs, guild_id=guild_id)
        view  = build_lobby_view(guild_id)
        msg   = await text_channel.send(embed=embed, view=view)
        gs["lobby_message"] = msg
        print(f"  [Bot] Guild {guild_id}: Đã gửi lobby embed.")
    except Exception as e:
        print(f"  [Bot] Guild {guild_id}: Không gửi được embed: {e}")


async def _emergency_cleanup_all_games():
    """Dọn dẹp tất cả game khi có sự cố khẩn cấp."""
    print("[Emergency] Đang dọn dẹp toàn bộ game...")
    for gid, gs in list(guilds.items()):
        try:
            gs["state"]   = GameState.WAITING
            gs["is_active"] = False
            gs["players_join_order"] = []
            clear_active_players(gid)
        except Exception as e:
            print(f"[Emergency] Lỗi khi cleanup guild {gid}: {e}")


# ══════════════════════════════════════════════════════════════════
# BOT EVENTS
# ══════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    global session, _READY_BOOTSTRAPPED

    print(f"[Bot] Đã đăng nhập: {bot.user} (ID: {bot.user.id})")
    print(f"[Bot] Đang quản lý {len(bot.guilds)} server(s).")

    if _READY_BOOTSTRAPPED:
        print("[Bot] on_ready được gọi lại — bỏ qua bootstrap để tránh trùng lặp.")
        if not update_game_board.is_running():
            update_game_board.start()
        return

    # ── Cập nhật app.state.bot (đảm bảo luôn là bot thật đang online) ──
    app.state.bot = bot
    print("[Bot] app.state.bot đã được gán — Dashboard có thể đọc bot.guilds.")

    # ── aiohttp session ────────────────────────────────────────────
    if session is None or session.closed:
        session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=certifi.where()),
        )
        print("[Bot] aiohttp session đã tạo.")

    # ── Đăng ký persistent view ────────────────────────────────────
    _persistent_view = disnake.ui.View(timeout=None)
    _persistent_view.add_item(JoinButton())
    _persistent_view.add_item(LeaveButton())
    bot.add_view(_persistent_view)

    # ── MongoDB indexes ────────────────────────────────────────────
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, ensure_indexes)
    print("[Bot] MongoDB indexes OK.")

    # ── TiDB tables ────────────────────────────────────────────────
    tidb_result = await loop.run_in_executor(None, database_tidb.ensure_tables)
    if tidb_result["ok"]:
        print("[Bot] TiDB tables OK.")
    else:
        print(f"[Bot] TiDB warning: {tidb_result.get('error')} — {tidb_result.get('hint')}")

    # ── Đăng ký emergency callback ─────────────────────────────────
    register_emergency_callback(_emergency_cleanup_all_games)

    # ── Load cogs ──────────────────────────────────────────────────
    cogs_dir      = os.path.join(_HERE, "cogs")
    cog_load_errors = []
    if os.path.isdir(cogs_dir):
        print(f"[Bot] Đang load cogs từ: {cogs_dir}")
        for filename in sorted(os.listdir(cogs_dir)):
            if filename.endswith(".py") and not filename.startswith("_"):
                cog_name = f"cogs.{filename[:-3]}"
                try:
                    if cog_name not in bot.extensions:
                        bot.load_extension(cog_name)
                        print(f"[Bot] ✓ Loaded cog: {cog_name}")
                except Exception as e:
                    cog_load_errors.append(cog_name)
                    print(f"[Bot] ✗ Lỗi load {cog_name}: {e}")
                    traceback.print_exc()
    else:
        print(f"[Bot] Không tìm thấy thư mục cogs/")

    if cog_load_errors:
        print(f"[Bot] Một số cog lỗi: {cog_load_errors}")
    else:
        print("[Bot] Slash commands sẽ được sync tự động bởi disnake.")

    # ── Khởi tạo các guild đang active ────────────────────────────
    all_configs = load_all_configs()
    print(f"[Bot] Khởi tạo {len(all_configs)} guild(s)...")
    for guild_id, cfg in all_configs.items():
        tc_id = cfg.get("text_channel_id")
        if not tc_id:
            continue
        text_channel = bot.get_channel(_to_int(tc_id, 0))
        if not text_channel:
            continue
        try:
            await _init_guild(guild_id, text_channel)
        except Exception as e:
            print(f"  [Bot] Guild {guild_id} lỗi: {e}")

    # ── Updater tasks ──────────────────────────────────────────────
    await send_post_update_embeds(bot)
    await greet_owner_on_setup(bot)

    # ── Background tasks ───────────────────────────────────────────
    if not update_game_board.is_running():
        update_game_board.start()

    # ── Presence ───────────────────────────────────────────────────
    await bot.change_presence(
        activity=disnake.Game(name="Made by Nang5Gram ( a.k.a Huy Ph. )")
    )

    # ── Truyền shared state vào Dashboard routes ───────────────────
    try:
        if _DASHBOARD_OK:
            def _col_fn(name: str):
                try:
                    return _cm_get_db()[name]
                except Exception:
                    return None

            _dash_init(
                bot=bot,
                guilds=guilds,
                active_games=active_games,
                game_stats=game_stats,
                col_fn=_col_fn,
            )
            print("[Dashboard] Shared state đã được truyền vào dashboard_routes.")
    except Exception as _de:
        print(f"[Dashboard] Lỗi khi init_shared: {_de}")

    _READY_BOOTSTRAPPED = True
    print(f"[Bot] ✅ Bot sẵn sàng hoạt động. Web chạy trên port {PORT}.")


@bot.event
async def on_guild_join(guild: disnake.Guild):
    print(f"[Bot] Đã join guild: {guild.name} ({guild.id})")


@bot.event
async def on_guild_remove(guild: disnake.Guild):
    print(f"[Bot] Rời guild: {guild.name} ({guild.id})")


@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return
    if message.guild is None:
        # DM
        try:
            await handle_owner_dm(bot, message)
        except Exception as e:
            print(f"[on_message] handle_owner_dm lỗi: {e}")
        return
    await bot.process_commands(message)


@bot.event
async def on_error(event: str, *args, **kwargs):
    print(f"[Bot] Lỗi event {event}:")
    traceback.print_exc()


# ══════════════════════════════════════════════════════════════════
# UVICORN SERVER — Không blocking, chạy qua asyncio.create_task()
# ══════════════════════════════════════════════════════════════════

async def _start_uvicorn():
    """
    Khởi động Uvicorn server bên trong event loop của Bot.
    Dùng uvicorn.Config + uvicorn.Server thay vì uvicorn.run()
    để KHÔNG block event loop của Bot.
    """
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",      # Bắt buộc: lắng nghe mọi interface (fix Connection Refused)
        port=PORT,
        log_level="info",
        loop="none",          # Dùng event loop hiện tại (cùng loop với Bot)
        access_log=True,
    )
    server = uvicorn.Server(config)
    print(f"[Uvicorn] Khởi động Web Dashboard trên 0.0.0.0:{PORT}...")
    await server.serve()


# ══════════════════════════════════════════════════════════════════
# MAIN — Entry Point Duy Nhất
# ══════════════════════════════════════════════════════════════════

async def main():
    """
    Hàm main: chạy Bot và Uvicorn Web Server CÙNG event loop.

    Luồng hoạt động:
    1. asyncio.create_task(bot.start()) → Bot kết nối Discord
    2. asyncio.create_task(_start_uvicorn()) → Web server lắng nghe trên PORT
    3. Bot.on_ready() được gọi → app.state.bot = bot → Dashboard có bot.guilds thật
    4. Dashboard POST /api/feedback → lưu TiDB với ID 15 ký tự
    5. Dashboard GET /api/guilds → đọc bot.guilds từ RAM

    Cả hai chạy song song, KHÔNG block nhau.
    """
    print(f"[Main] Khởi động Anomalies v3.0 — Port={PORT}")

    # Task 1: Bot Discord
    if TOKEN:
        bot_task = asyncio.create_task(bot.start(TOKEN), name="discord-bot")
        print("[Main] Discord Bot task đã được tạo.")
    else:
        bot_task = None
        print("[Main] DISCORD_TOKEN trống — Bot không kết nối Discord.")

    # Task 2: Uvicorn Web Server (không blocking)
    web_task = asyncio.create_task(_start_uvicorn(), name="uvicorn-web")
    print("[Main] Uvicorn Web task đã được tạo.")

    # Chờ đến khi một trong hai kết thúc (hoặc bị lỗi)
    tasks_to_run = [t for t in [bot_task, web_task] if t is not None]
    try:
        done, pending = await asyncio.wait(
            tasks_to_run,
            return_when=asyncio.FIRST_EXCEPTION,
        )
        # Log nếu có task lỗi
        for task in done:
            if task.exception():
                print(f"[Main] Task '{task.get_name()}' lỗi: {task.exception()}")
    except (KeyboardInterrupt, SystemExit):
        print("[Main] Nhận tín hiệu tắt...")
    finally:
        print("[Main] Đang shutdown...")
        global _shutting_down
        _shutting_down = True

        # Đóng session aiohttp
        if session and not session.closed:
            await session.close()

        # Hủy các task còn lại
        for task in tasks_to_run:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        # Đóng bot nếu cần
        if not bot.is_closed():
            await bot.close()

        print("[Main] Đã shutdown hoàn tất.")


if __name__ == "__main__":
    asyncio.run(main())
