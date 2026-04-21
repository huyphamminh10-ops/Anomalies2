# ==============================
# app.py — Anomalies v2.3 (Fixed for Hugging Face)
# FIX v2.3:
#   - Bot chạy trong background thread daemon (không bị Streamlit reload ảnh hưởng)
#   - Singleton dùng threading.Event + module-level flag (KHÔNG dùng file, KHÔNG dùng sys.exit)
#   - Detect môi trường HF qua biến SPACE_ID
#   - /ping endpoint cho UptimeRobot keep-alive
#   - asyncio event loop riêng cho bot thread (không share với Streamlit)
#   - Reconnect tự động với exponential backoff
#   - graceful_shutdown: KHÔNG gọi sys.exit()
# ==============================

try:
    import ujson as _json_lib
except ImportError:
    import json as _json_lib  # type: ignore

import aiohttp
import discord
import asyncio
import certifi
import os
import glob
import sys
import importlib
import inspect
import traceback
import time as _time_module
import threading as _threading
import builtins as _builtins
import socket
import atexit
from discord.ext import commands, tasks
from discord import app_commands
from cogs.settings import check_command_permission as _check_cmd_perm
from config_manager import (
    load_guild_config, save_guild_config,
    load_all_configs,
    load_guild_lobby, save_guild_lobby,
    get_guild_status,
    ensure_indexes,
    save_active_players, load_active_players, clear_active_players,
)
from event_roles_loader import get_loader as get_event_loader
from updater import (
    handle_owner_dm,
    greet_owner_on_setup,
    send_post_update_embeds,
    BOT_OWNER_ID,
    register_emergency_callback,
)

# ── FastAPI (tuỳ chọn, cho /ping + /get-table) ───────────────────
try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    _fastapi_app = FastAPI()
    game_stats: dict = {"table_content": "Đang khởi tạo..."}

    @_fastapi_app.get("/get-table")
    async def get_table():
        return game_stats

    @_fastapi_app.get("/")
    @_fastapi_app.head("/")
    async def _root_health_check():
        return {"status": "ok", "bot": "Anomalies", "message": "Service is live"}

    @_fastapi_app.get("/ping")
    async def ping():
        """Endpoint cho UptimeRobot keep-alive."""
        return JSONResponse({
            "status": "ok",
            "bot_running": _BOT_STARTED.is_set(),
            "environment": "hugging_face" if _IS_HUGGING_FACE else "local",
        })

except ImportError:
    _fastapi_app = None
    game_stats: dict = {}

# ── Detect môi trường Hugging Face ───────────────────────────────
_IS_HUGGING_FACE = bool(os.environ.get("SPACE_ID"))
if _IS_HUGGING_FACE:
    print(f"[Env] Đang chạy trên Hugging Face Space: {os.environ.get('SPACE_ID')}")
else:
    print("[Env] Đang chạy môi trường local/khác.")

# ── Intents + Bot ─────────────────────────────────────────────────
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

session: aiohttp.ClientSession | None = None
_shutting_down: bool = False

# ══════════════════════════════════════════════════════════════════
# SINGLETON — Socket lock liên process
#
# Streamlit/Hugging Face có thể tạo nhiều process riêng biệt, nên biến global
# chỉ chặn được trong cùng process. Socket lock dùng một TCP port cố định:
# process nào bind được port này là process duy nhất được phép chạy Discord bot.
# Process khác thấy port bị chiếm thì return ngay, không start bot trùng.
# ══════════════════════════════════════════════════════════════════

_bot_state = getattr(_builtins, "_ANOMALIES_BOT_STATE", None)
if _bot_state is None:
    _bot_state = {
        "started": _threading.Event(),
        "thread": None,
        "lock": _threading.Lock(),
        "loop": None,
        "socket": None,
    }
    setattr(_builtins, "_ANOMALIES_BOT_STATE", _bot_state)

_BOT_STARTED: _threading.Event = _bot_state["started"]
_BOT_THREAD:  _threading.Thread | None = _bot_state.get("thread")
_BOT_LOCK:    _threading.Lock = _bot_state["lock"]
_bot_loop:    asyncio.AbstractEventLoop | None = _bot_state.get("loop")
_READY_BOOTSTRAPPED: bool = False
_SOCKET_LOCK_PORT = int(os.environ.get("BOT_LOCK_PORT", "25565"))


def _acquire_socket_lock() -> bool:
    existing_socket = _bot_state.get("socket")
    if existing_socket is not None:
        return True

    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        lock_socket.bind(("127.0.0.1", _SOCKET_LOCK_PORT))
        lock_socket.listen(1)
    except OSError as e:
        lock_socket.close()
        print(
            f"[SocketLock] Port 127.0.0.1:{_SOCKET_LOCK_PORT} đã bị chiếm "
            f"({e}). Một instance bot khác đang chạy — bỏ qua khởi động."
        )
        return False

    _bot_state["socket"] = lock_socket
    print(f"[SocketLock] Đã giữ port 127.0.0.1:{_SOCKET_LOCK_PORT} cho instance bot này.")
    return True


def _release_socket_lock():
    lock_socket = _bot_state.get("socket")
    if lock_socket is None:
        return

    try:
        lock_socket.close()
        print(f"[SocketLock] Đã giải phóng port 127.0.0.1:{_SOCKET_LOCK_PORT}.")
    except Exception as e:
        print(f"[SocketLock] Lỗi khi giải phóng socket: {e}")
    finally:
        _bot_state["socket"] = None


atexit.register(_release_socket_lock)


# ══════════════════════════════════════════════════════════════════
# BACKGROUND TASKS
# ══════════════════════════════════════════════════════════════════

import time as _time


@tasks.loop(seconds=30)
async def update_game_board():
    global game_stats, session
    if _shutting_down:
        return
    if session is None or session.closed:
        return
    try:
        async with session.get(
            "http://127.0.0.1:8000/get-table",
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


MIN_PLAYERS       = 5
MAX_PLAYERS       = 65
COUNTDOWN_DEFAULT = 200


# ==============================
# GAME STATE
# ==============================

class GameState:
    WAITING   = "WAITING"
    COUNTDOWN = "COUNTDOWN"
    FULL_FAST = "FULL_FAST"
    IN_GAME   = "IN_GAME"


guilds             = {}
active_games       = {}
_pending_role_maps: dict[str, dict] = {}
_config_cache      = {}
_config_cache_time = {}

_EDIT_INTERVAL = 1.0


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


def get_guild_state(guild_id):
    gid = str(guild_id)
    if gid not in guilds:
        cfg = get_cached_config(gid)
        guilds[gid] = {
            "state":               GameState.WAITING,
            "countdown_time":      cfg_countdown(cfg),
            "lobby_message":       None,
            "current_page":        0,
            "players_join_order":  [],
            "lobby_lock":          None,
            "original_nicknames":  {},
            "loop_started":        False,
            "dirty":               False,
            "last_edit_time":      0.0,
            "_backoff_until":      0.0,
            "is_active":           False,
        }
    return guilds[gid]


# ==============================
# UTIL
# ==============================

def format_time(seconds):
    m = seconds // 60
    s = seconds % 60
    return f"{m:02}:{s:02}"


def progress_bar(current, total, length=20):
    if total <= 0:
        return "░" * length
    filled = max(0, min(length, int(length * (total - current) / total)))
    return "█" * filled + "░" * (length - filled)


def paginate_players(players, page):
    per_page = 11
    return players[page * per_page : (page + 1) * per_page]


# ==============================
# EMBED
# ==============================

def build_embed(gs, guild_id=None):
    cfg           = get_cached_config(str(guild_id)) if guild_id else {}
    min_p         = cfg_min_players(cfg)
    max_p         = cfg_max_players(cfg)
    countdown_max = cfg_countdown(cfg)

    state          = gs["state"]
    countdown_time = max(0, gs["countdown_time"])  # không hiện số âm
    current_page   = gs["current_page"]
    players        = gs["players_join_order"]
    total_pages    = max(1, (len(players) - 1) // 11 + 1)

    embed = discord.Embed()

    if state == GameState.WAITING:
        embed.title       = "🔴 》ANOMALIES《"
        embed.description = f"Đang chờ đủ {min_p} người..."
        embed.color       = discord.Color.green()

    elif state in (GameState.COUNTDOWN, GameState.FULL_FAST):
        embed.title = "🔴 》ANOMALIES《"
        embed.color = discord.Color.gold()
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
        embed.color       = discord.Color.purple()

    players_page = paginate_players(players, current_page)
    if players_page:
        text = "\n".join(
            f"{i}. {p.display_name}"
            for i, p in enumerate(players_page, start=1 + current_page * 11)
        )
        embed.add_field(name=f"👥 Người Chơi ({len(players)}/{max_p})", value=text, inline=False)

    embed.set_footer(text=f"Trang {current_page + 1}/{total_pages}")
    return embed


# ==============================
# VIEW TASK
# ==============================

async def update_lobby(gs, guild_id=None):
    gs["dirty"] = True


async def _flush_lobby(gs, guild_id=None):
    if not gs.get("lobby_message") or not gs.get("dirty"):
        return

    now = _time.monotonic()
    if now < gs.get("_backoff_until", 0.0):
        return
    if now - gs.get("last_edit_time", 0.0) < _EDIT_INTERVAL:
        return

    gs["dirty"]          = False
    gs["last_edit_time"] = now

    try:
        await gs["lobby_message"].edit(embed=build_embed(gs, guild_id=guild_id))
    except discord.errors.HTTPException as e:
        if e.status == 429:
            retry_after = getattr(e, "retry_after", None) or 2.5
            gs["_backoff_until"] = _time.monotonic() + retry_after
            gs["dirty"]          = True
        elif e.status in (404, 10008):  # Unknown Message — bị xóa tay
            gs["lobby_message"] = None
            # Tạo lại message mới trong kênh text
            if guild_id:
                try:
                    raw_cfg  = get_cached_config(str(guild_id))
                    tc       = bot.get_channel(raw_cfg.get("text_channel_id", 0))
                    if tc:
                        new_msg = await tc.send(embed=build_embed(gs, guild_id=guild_id))
                        gs["lobby_message"] = new_msg
                        save_guild_lobby(str(guild_id), {
                            "message_id": new_msg.id,
                            "channel_id":  tc.id
                        })
                        print(f"[flush_lobby] [{guild_id}] Message bị xóa — đã tạo lại {new_msg.id}")
                except Exception as _e:
                    print(f"[flush_lobby] [{guild_id}] Không tạo lại được message: {_e}")
    except Exception:
        pass


# ==============================
# PURGE CHANNEL
# ==============================

_PURGE_INTERVAL = 30   # giây

async def _purge_channel(guild_id: str, reason: str = "Tự Động Dọn Dẹp"):
    """
    Xóa tất cả tin nhắn trong text channel trừ lobby embed.
    Gửi thông báo, tự xóa sau 15 giây.
    """
    try:
        gid     = str(guild_id)
        raw_cfg = get_cached_config(gid)
        tc_id   = raw_cfg.get("text_channel_id")
        if not tc_id:
            return
        channel = bot.get_channel(int(tc_id))
        if not channel:
            return

        gs        = get_guild_state(gid)
        lobby_msg = gs.get("lobby_message")
        lobby_id  = lobby_msg.id if lobby_msg else None

        deleted = []
        try:
            deleted = await channel.purge(
                limit=200,
                check=lambda m: (lobby_id is None or m.id != lobby_id),
                bulk=True
            )
        except discord.Forbidden:
            async for msg in channel.history(limit=200):
                if lobby_id and msg.id == lobby_id:
                    continue
                try:
                    await msg.delete()
                    deleted.append(msg)
                    await asyncio.sleep(0.4)
                except Exception:
                    pass
        except Exception as e:
            print(f"[purge_channel] [{guild_id}] purge lỗi: {e}")
            return

        count = len(deleted)
        if count == 0:
            return

        guild_obj  = channel.guild
        guild_name = guild_obj.name if guild_obj else gid
        await channel.send(
            f"🧹 **[ {guild_name} ]** : Đã Xóa **{count}** Tin Nhắn ( {reason} )",
            delete_after=15
        )

    except Exception as e:
        print(f"[purge_channel] [{guild_id}] Lỗi: {e}")


# ==============================
# ROLE LOADER
# ==============================

def load_role_classes(base_dir=None):
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    roles_dir = os.path.join(base_dir, "roles")
    survivors, anomalies, unknowns = [], [], []
    folders = {"survivors": survivors, "anomalies": anomalies, "unknown": unknowns}

    for folder, bucket in folders.items():
        folder_path = os.path.join(roles_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        for filepath in glob.glob(os.path.join(folder_path, "*.py")):
            filename = os.path.basename(filepath)
            if filename.startswith("_"):
                continue
            module_name = f"roles.{folder}.{filename[:-3]}"
            try:
                mod = importlib.import_module(module_name)
                for _, obj in inspect.getmembers(mod, inspect.isclass):
                    if (
                        obj.__module__ == module_name
                        and hasattr(obj, "name")
                        and hasattr(obj, "team")
                        and obj.__name__ not in ("BaseRole", "ExtensibleBaseRole")
                    ):
                        bucket.append(obj)
            except Exception as e:
                print(f"  [roles] ✘ {module_name}: {e}")

    print(f"[roles] Survivors={len(survivors)} | Anomalies={len(anomalies)} | Unknown={len(unknowns)}")
    return survivors, anomalies, unknowns


# ==============================
# BUILD GAME CONFIG
# ==============================

def build_game_config(raw_config: dict):
    from game import GameConfig
    return GameConfig(
        max_players              = raw_config.get("max_players", MAX_PLAYERS),
        min_players              = raw_config.get("min_players", MIN_PLAYERS),
        allow_voice              = raw_config.get("allow_voice", True),
        mute_dead                = raw_config.get("mute_dead", True),
        no_remove_roles          = raw_config.get("no_remove_roles", False),
        voice_mode               = raw_config.get("voice_mode", "free"),
        parliament_seconds       = raw_config.get("parliament_seconds", 60),
        anonymous_vote           = raw_config.get("anonymous_vote", False),
        allow_skip               = raw_config.get("skip_discussion", True),
        weighted_vote            = raw_config.get("weighted_vote", True),
        revote_on_tie            = raw_config.get("revote_on_tie", True),
        auto_random_if_no_action = raw_config.get("auto_random_if_no_action", True),
        dm_fallback_to_public    = raw_config.get("dm_fallback_to_public", True),
        debug_mode               = raw_config.get("debug_mode", False),
        save_crash_log           = raw_config.get("save_crash_log", True),
        large_server_mode        = raw_config.get("large_server_mode", False),
        large_server_threshold   = raw_config.get("large_server_threshold", 40),
        dead_role_id             = raw_config.get("dead_role_id"),
        alive_role_id            = raw_config.get("alive_role_id"),
        text_channel_id          = raw_config.get("text_channel_id"),
        voice_channel_id         = raw_config.get("voice_channel_id"),
        category_id              = raw_config.get("category_id"),
        role_distribute_time     = raw_config.get("role_distribute_time", 15),
        night_time               = raw_config.get("night_time", 45),
        day_time                 = max(30, min(120, raw_config.get("day_time", 90))),
        vote_time                = max(15, min(45,  raw_config.get("vote_time", 30))),
        skip_discussion_delay    = raw_config.get("skip_discussion_delay", 30),
    )


# ==============================
# RESET LOBBY
# ==============================

def _reset_lobby(gs: dict, guild_id: str = None):
    gs["state"]              = GameState.WAITING
    gs["players_join_order"] = []
    gs["original_nicknames"] = {}
    gs["dirty"]              = True
    gs["is_active"]          = False
    if guild_id:
        cfg = get_cached_config(str(guild_id))
        cdt = cfg_countdown(cfg)
        gs["countdown_time"] = max(10, cdt)  # tối thiểu 10s, không bao giờ âm
        invalidate_config_cache(str(guild_id))
        try:
            _cfg = load_guild_config(str(guild_id))
            _cfg.pop("status", None)
            save_guild_config(str(guild_id), _cfg)
        except Exception:
            pass
        try:
            clear_active_players(str(guild_id))
        except Exception:
            pass
    else:
        gs["countdown_time"] = COUNTDOWN_DEFAULT


# ==============================
# LAUNCH GAME
# ==============================

async def launch_game(guild_id: str, gs: dict):
    gid = str(guild_id)

    if gs.get("is_active"):
        print(f"[launch_game] [{gid}] ⚠️ is_active=True — bỏ qua.")
        return

    if get_guild_status(gid) == "ingame":
        # Nếu không có engine đang chạy → status cũ bị kẹt, tự động dọn
        if gid not in active_games:
            print(f"[launch_game] [{gid}] status=ingame nhưng không có engine — tự reset.")
            try:
                _cfg = load_guild_config(gid)
                _cfg.pop("status", None)
                save_guild_config(gid, _cfg)
            except Exception:
                pass
            clear_active_players(gid)
        else:
            print(f"[launch_game] [{gid}] ⚠️ status=ingame + engine đang chạy — bỏ qua.")
            return

    raw_config   = get_cached_config(gid)
    text_channel = bot.get_channel(raw_config.get("text_channel_id", 0))

    if not text_channel:
        _reset_lobby(gs, guild_id=gid)
        await update_lobby(gs, guild_id=gid)
        return

    members = gs["players_join_order"][:]
    min_p   = cfg_min_players(raw_config)
    max_p   = cfg_max_players(raw_config)

    if len(members) < min_p:
        await text_channel.send(f"⚠️ Không đủ {min_p} người. Quay về sảnh chờ.")
        gs["is_active"] = False   # unlock trước khi reset
        _reset_lobby(gs, guild_id=gid)
        await update_lobby(gs, guild_id=gid)
        return

    if len(members) > max_p:
        members = members[:max_p]

    gs["is_active"] = True
    gs["state"]     = GameState.IN_GAME
    await update_lobby(gs, guild_id=gid)

    try:
        from game import GameEngine

        survivor_classes, anomaly_classes, unknown_classes = load_role_classes()

        if not (survivor_classes or anomaly_classes or unknown_classes):
            await text_channel.send("❌ Không load được role. Kiểm tra thư mục `roles/`.")
            _reset_lobby(gs, guild_id=gid)
            await update_lobby(gs, guild_id=gid)
            return

        game_config = build_game_config(raw_config)

        engine = GameEngine(
            guild         = bot.get_guild(int(gid)),
            members       = members,
            text_channel  = text_channel,
            config        = game_config,
            voice_channel = bot.get_channel(raw_config.get("voice_channel_id", 0)),
        )

        active_games[gid] = engine
        await engine.start(survivor_classes, anomaly_classes, unknown_classes)

    except Exception as e:
        print(f"[launch_game] [{gid}] FATAL: {e}\n{traceback.format_exc()}")
        try:
            await text_channel.send(f"❌ Lỗi nghiêm trọng khi khởi động trận: `{e}`")
        except Exception:
            pass
    finally:
        # Dọn engine: nếu crash chưa ended thì end_game() để unmute/gỡ role
        _engine = active_games.pop(gid, None)
        if _engine and not _engine.ended:
            try:
                _engine._muting_enabled = False
                await asyncio.wait_for(
                    _engine.end_game("Trận bị huỷ do lỗi hệ thống"),
                    timeout=10.0
                )
            except Exception as _fe:
                print(f"[launch_game] [{gid}] end_game cleanup lỗi: {_fe}")
        _reset_lobby(gs, guild_id=gid)
        await update_lobby(gs, guild_id=gid)


# ==============================
# LOBBY LOCK HELPER
# ==============================

def _get_lobby_lock(gs: dict) -> asyncio.Lock:
    if gs.get("lobby_lock") is None:
        gs["lobby_lock"] = asyncio.Lock()
    return gs["lobby_lock"]


# ==============================
# INIT GUILD
# ==============================

async def init_guild(guild_id: str, text_channel):
    gid = str(guild_id)

    if get_guild_status(gid) == "ingame":
        # Chỉ tin status=ingame nếu CÓ engine thực sự đang chạy
        # Nếu không có engine (crash/restart), reset về WAITING để tránh bị kẹt
        if gid in active_games:
            print(f"  [{gid}] status=ingame + engine đang chạy — giữ nguyên.")
            gs = get_guild_state(gid)
            gs["is_active"] = True
            gs["state"]     = GameState.IN_GAME
            await update_lobby(gs, guild_id=gid)
            return
        else:
            # Không có engine → crash cũ, dọn status và tiếp tục init bình thường
            print(f"  [{gid}] status=ingame nhưng không có engine — tự động reset.")
            try:
                _cfg = load_guild_config(gid)
                _cfg.pop("status", None)
                save_guild_config(gid, _cfg)
            except Exception:
                pass
            try:
                clear_active_players(gid)
            except Exception:
                pass

    gs = get_guild_state(gid)

    # ── Khôi phục danh sách người chơi từ MongoDB ──────────────────
    # Chỉ restore khi lobby đang ở trạng thái WAITING (không phải ingame)
    saved_player_ids = load_active_players(gid)
    if saved_player_ids:
        guild_obj = bot.get_guild(int(gid))
        if guild_obj:
            restored = []
            for pid in saved_player_ids:
                member = guild_obj.get_member(pid)
                if member is None:
                    # Cache chưa có → fetch từ API (chậm hơn nhưng chính xác)
                    try:
                        member = await guild_obj.fetch_member(pid)
                    except Exception:
                        member = None
                if member is not None:
                    restored.append(member)
            gs["players_join_order"] = restored
            print(f"  [{gid}] Restored {len(restored)}/{len(saved_player_ids)} player(s) vào lobby.")
        else:
            print(f"  [{gid}] Không tìm thấy guild object, bỏ qua restore players.")

    saved = load_guild_lobby(gid)
    if saved and saved.get("message_id"):
        try:
            msg = await text_channel.fetch_message(saved["message_id"])
            gs["lobby_message"]  = msg
            gs["state"]          = saved.get("state", GameState.WAITING)
            gs["countdown_time"] = saved.get("countdown_time", COUNTDOWN_DEFAULT)
            print(f"  [{gid}] Restored lobby message {msg.id}")
        except discord.NotFound:
            gs["lobby_message"] = None
        except Exception as e:
            print(f"  [{gid}] Lỗi fetch lobby message: {e}")
            gs["lobby_message"] = None

    if gs["lobby_message"] is None:
        try:
            embed = build_embed(gs, guild_id=gid)
            msg   = await text_channel.send(embed=embed)
            gs["lobby_message"] = msg
            save_guild_lobby(gid, {"message_id": msg.id, "channel_id": text_channel.id})
            print(f"  [{gid}] Tạo lobby message mới: {msg.id}")
        except Exception as e:
            print(f"  [{gid}] Lỗi tạo lobby message: {e}")

    if not gs["loop_started"]:
        gs["loop_started"] = True
        asyncio.create_task(_lobby_loop(gid))


async def _lobby_loop(guild_id: str):
    gid           = str(guild_id)
    purge_counter = 0

    while True:
        try:
            gs = get_guild_state(gid)

            if gs.get("is_active") or gs["state"] == GameState.IN_GAME:
                purge_counter = 0   # reset khi vào game
                await asyncio.sleep(1)
                continue

            if gs["state"] in (GameState.COUNTDOWN, GameState.FULL_FAST):
                gs["countdown_time"] -= 1
                await update_lobby(gs, guild_id=gid)

                if gs["countdown_time"] <= 0 and not gs.get("is_active"):
                    # Chặn loop ngay — đặt is_active trước khi fire task
                    gs["is_active"] = True
                    gs["state"]     = GameState.IN_GAME
                    gs["countdown_time"] = 0
                    asyncio.create_task(launch_game(gid, gs))
                    purge_counter = 0
                    continue   # không chạy _flush_lobby lần này

            await _flush_lobby(gs, guild_id=gid)

            # ── Auto purge mỗi 30 giây khi chờ ──────────────────
            purge_counter += 1
            if purge_counter >= _PURGE_INTERVAL:
                purge_counter = 0
                asyncio.create_task(_purge_channel(gid, reason="Tự Động Dọn Dẹp"))

        except Exception as e:
            print(f"[lobby_loop] [{gid}] Lỗi: {e}")

        await asyncio.sleep(1)


# ══════════════════════════════════════════════════════════════════
# GRACEFUL SHUTDOWN — KHÔNG gọi sys.exit()
# ══════════════════════════════════════════════════════════════════

async def graceful_shutdown(reason: str = "unknown"):
    """
    Đóng bot an toàn.
    FIX: KHÔNG gọi sys.exit() — để Hugging Face tự quyết định lifecycle.
    Thứ tự: tasks → games → asyncio tasks → bot.close() → session.close()
    """
    global _shutting_down, session

    if _shutting_down:
        return
    _shutting_down = True

    print(f"[Shutdown] Bắt đầu graceful shutdown: {reason}")

    # 1. Dừng background tasks
    for loop_task in (update_game_board,):
        try:
            if loop_task.is_running():
                loop_task.cancel()
        except Exception:
            pass

    # 2. Kết thúc các trận đang diễn ra
    if active_games:
        for gid, engine in list(active_games.items()):
            try:
                engine._muting_enabled = False
                await asyncio.wait_for(
                    engine.end_game(f"Bot shutdown: {reason}"),
                    timeout=5.0
                )
            except Exception as e:
                print(f"[Shutdown] end_game [{gid}] lỗi: {e}")
        await asyncio.sleep(0.5)

    # 3. Hủy asyncio tasks còn lại (với timeout để không treo mãi)
    current_task = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current_task and not t.done()]
    if pending:
        for t in pending:
            t.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            print("[Shutdown] Task gathering timeout (5s).")
        except Exception:
            pass

    # 4. bot.close() trước — giải phóng token Discord
    if not bot.is_closed():
        try:
            await bot.close()
            print("[Shutdown] bot.close() — token Discord đã giải phóng.")
        except Exception as e:
            print(f"[Shutdown] bot.close() lỗi: {e}")

    # 5. session.close() sau
    if session and not session.closed:
        try:
            await session.close()
            await asyncio.sleep(0.25)
            print("[Shutdown] aiohttp session đã đóng.")
        except Exception as e:
            print(f"[Shutdown] session.close() lỗi: {e}")
        session = None

    # FIX: KHÔNG gọi sys.exit() ở đây
    print("[Shutdown] Graceful shutdown hoàn tất.")


# ══════════════════════════════════════════════════════════════════
# EMERGENCY CALLBACK
# ══════════════════════════════════════════════════════════════════

async def _emergency_cleanup_all_games(reason: str):
    if not active_games:
        print("[Emergency] Không có trận nào đang diễn ra.")
        return

    print(f"[Emergency] Hủy {len(active_games)} trận: {reason}")

    for gid, engine in list(active_games.items()):
        try:
            text_ch = getattr(engine, "text_channel", None)
            if text_ch:
                await text_ch.send(
                    embed=discord.Embed(
                        title="🔧 TRẬN ĐẤU BỊ HỦY DO CẬP NHẬT",
                        description=(
                            f"**{reason}**\n\n"
                            "Bot sẽ restart trong **30 giây**.\n"
                            "Toàn bộ vai trò sẽ được thu hồi ngay bây giờ.\n"
                            "Sau khi cập nhật, hãy bắt đầu trận mới. 🙏"
                        ),
                        color=0xe74c3c,
                    )
                )
        except Exception as e:
            print(f"[Emergency] Gửi thông báo [{gid}] lỗi: {e}")

        try:
            engine._muting_enabled = False
        except Exception:
            pass

        try:
            await asyncio.wait_for(
                engine.end_game("Cập nhật bot — Trận bị hủy"),
                timeout=10.0
            )
            print(f"[Emergency] Đã hủy trận [{gid}].")
        except asyncio.TimeoutError:
            print(f"[Emergency] end_game [{gid}] timeout — bỏ qua.")
        except Exception as e:
            print(f"[Emergency] end_game [{gid}] lỗi: {e}")

        await asyncio.sleep(0.3)


# ==============================
# ON VOICE STATE UPDATE
# ==============================

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    guild_id   = str(member.guild.id)
    raw_config = get_cached_config(guild_id)

    if not raw_config.get("voice_channel_id"):
        return

    voice_channel = bot.get_channel(raw_config["voice_channel_id"])
    text_channel  = bot.get_channel(raw_config.get("text_channel_id", 0))
    gs            = get_guild_state(guild_id)

    if after.channel == voice_channel and before.channel != voice_channel:
        if gs.get("is_active") or gs["state"] == GameState.IN_GAME:
            engine = active_games.get(guild_id)
            pid    = member.id

            if engine and pid in engine._players_dict:
                if pid in engine.dead_players and engine.config.mute_dead:
                    try:
                        await member.edit(mute=True)
                    except Exception:
                        pass
                return

            gs["original_nicknames"][pid] = member.nick
            try:
                await member.edit(nick="👻 Spectator")
            except Exception:
                pass

            if engine:
                engine.spectators.add(pid)
                await engine.dead_chat_mgr.add_spectator(member)
            return

        async with _get_lobby_lock(gs):
            if member not in gs["players_join_order"]:
                gs["players_join_order"].append(member)
                save_active_players(guild_id, [m.id for m in gs["players_join_order"]])

        player_count = len(gs["players_join_order"])
        max_p        = cfg_max_players(raw_config)
        min_p        = cfg_min_players(raw_config)

        if player_count >= max_p:
            gs["state"]          = GameState.FULL_FAST
            gs["countdown_time"] = 10
        elif player_count >= min_p and gs["state"] == GameState.WAITING:
            gs["state"]          = GameState.COUNTDOWN
            gs["countdown_time"] = cfg_countdown(raw_config)

        await update_lobby(gs, guild_id=guild_id)

    if before.channel == voice_channel and after.channel != voice_channel:
        async with _get_lobby_lock(gs):
            if member in gs["players_join_order"]:
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

        engine = active_games.get(guild_id)
        # Chỉ xử lý 'rời trận' khi có engine đang chạy thực sự
        if engine and not engine.ended and (gs.get("is_active") or gs["state"] == GameState.IN_GAME):
            if text_channel:
                await text_channel.send(f"🚪 **{member.display_name}** đã rời trận giữa chừng.")

            if member.id in engine.alive_players:
                engine.alive_players.discard(member.id)
                engine.dead_players.add(member.id)
                engine._invalidate_alive_cache()
                await engine.dead_chat_mgr.add_dead_player(member)
                engine._check_win()
            engine.spectators.discard(member.id)

        pid = member.id
        if pid in gs.get("original_nicknames", {}):
            original_nick = gs["original_nicknames"].pop(pid)
            try:
                await member.edit(nick=original_nick)
            except Exception:
                pass

        await update_lobby(gs, guild_id=guild_id)


# ==============================
# SLASH COMMAND: /clear
# ==============================

@bot.tree.command(name="clear", description="Xóa tất cả tin nhắn trong kênh (trừ bảng lobby)")
@app_commands.guild_only()
async def clear_command(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    cfg      = get_cached_config(guild_id)
    gs       = get_guild_state(guild_id)

    if not _check_cmd_perm(interaction, cfg):
        return await interaction.response.send_message("❌ Bạn không có quyền.", ephemeral=True)

    text_channel_id = cfg.get("text_channel_id")
    if not text_channel_id:
        return await interaction.response.send_message("⚠️ Server chưa setup.", ephemeral=True)

    channel = bot.get_channel(text_channel_id)
    if not channel:
        return await interaction.response.send_message("⚠️ Không thể truy cập kênh.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    lobby_msg_id = gs["lobby_message"].id if gs.get("lobby_message") else None

    try:
        deleted = await channel.purge(
            limit=None,
            check=lambda msg: msg.id != lobby_msg_id,
            bulk=True,
        )
    except Exception as e:
        return await interaction.followup.send(f"❌ Lỗi: `{e}`", ephemeral=True)

    await interaction.followup.send(
        f"[{interaction.guild.name}] : Đã dọn **{len(deleted)}** Tin nhắn",
        ephemeral=False,
    )


# ==============================
# ON MESSAGE
# ==============================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if not message.guild:
        await handle_owner_dm(bot, message)
        return

    game = active_games.get(str(message.guild.id))
    if game:
        try:
            from game import handle_will_message
            if await handle_will_message(game, message):
                return
        except Exception as e:
            print(f"[on_message] handle_will_message lỗi: {e}")

    await bot.process_commands(message)


# ══════════════════════════════════════════════════════════════════
# BOT EVENTS
# ══════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    global session, _READY_BOOTSTRAPPED
    print(f"[Bot] Đã đăng nhập: {bot.user} (ID: {bot.user.id})")
    print(f"[Bot] Môi trường: {'Hugging Face' if _IS_HUGGING_FACE else 'Local'}")

    if _READY_BOOTSTRAPPED:
        print("[Bot] on_ready được gọi lại — bỏ qua load cogs/sync/init để tránh chạy trùng.")
        if not update_game_board.is_running():
            update_game_board.start()
        return

    if session is None or session.closed:
        session = aiohttp.ClientSession()
        print("[Bot] aiohttp session đã tạo.")

    # Khởi tạo MongoDB indexes (chạy 1 lần)
    ensure_indexes()

    # Đăng ký emergency callback cho updater
    register_emergency_callback(_emergency_cleanup_all_games)

    # Load cogs trước, rồi mới sync slash commands
    base_dir = os.path.abspath(os.path.dirname(__file__))
    cogs_dir = os.path.abspath(os.path.join(base_dir, "cogs"))
    cog_load_errors = []
    if os.path.isdir(cogs_dir):
        print(f"[Bot] Đang load cogs từ: {cogs_dir}")
        for filename in sorted(os.listdir(cogs_dir)):
            if filename.endswith(".py") and not filename.startswith("_"):
                cog_name = f"cogs.{filename[:-3]}"
                try:
                    if cog_name not in bot.extensions:
                        await bot.load_extension(cog_name)
                        print(f"[Bot] Đã load: {cog_name}")
                except Exception as e:
                    cog_load_errors.append(cog_name)
                    print(f"[Bot] Lỗi load {cog_name}: {e}")
                    traceback.print_exc()
    else:
        cog_load_errors.append("cogs_dir_missing")
        print(f"[Bot] Không tìm thấy thư mục cogs: {cogs_dir}")

    # Chỉ sync sau khi toàn bộ Cog đã load thành công
    if cog_load_errors:
        print(f"[Bot] Bỏ qua sync slash commands vì còn lỗi load cogs: {cog_load_errors}")
    else:
        try:
            synced = await bot.tree.sync()
            print(f"[Bot] Đã sync {len(synced)} slash commands.")
        except Exception as e:
            print(f"[Bot] Lỗi sync commands: {e}")
            traceback.print_exc()

    # Khởi tạo các guild đang active
    all_configs = load_all_configs()
    print(f"[Bot] Khởi tạo {len(all_configs)} guild(s)...")
    for guild_id, cfg in all_configs.items():
        tc_id = cfg.get("text_channel_id")
        if not tc_id:
            continue
        text_channel = bot.get_channel(tc_id)
        if not text_channel:
            continue
        try:
            await init_guild(guild_id, text_channel)
            print(f"  [Bot] Guild {guild_id} khởi tạo OK.")
            asyncio.create_task(_purge_channel(guild_id, reason="Khởi Động Lại"))
        except Exception as e:
            print(f"  [Bot] Guild {guild_id} lỗi: {e}")

    # Gửi post-update embeds nếu vừa restart
    await send_post_update_embeds(bot)

    # Greet owner
    await greet_owner_on_setup(bot)

    # Khởi động background tasks
    if not update_game_board.is_running():
        update_game_board.start()

    # Đặt trạng thái "Đang Chơi"
    await bot.change_presence(
        activity=discord.Game(name="Made by Nang5Gram ( a.k.a Huy Ph. )")
    )

    _READY_BOOTSTRAPPED = True
    print("[Bot] Bot sẵn sàng hoạt động.")


@bot.event
async def on_guild_join(guild):
    print(f"[Bot] Đã join guild: {guild.name} ({guild.id})")


@bot.event
async def on_guild_remove(guild):
    gid = str(guild.id)
    guilds.pop(gid, None)
    active_games.pop(gid, None)
    print(f"[Bot] Đã rời guild: {guild.name} ({guild.id})")


# ══════════════════════════════════════════════════════════════════
# BOT RUNNER — Chạy trong background thread daemon riêng
# FIX: Đây là fix cốt lõi cho vấn đề infinite restart loop.
#      Bot thread là daemon → không bị ảnh hưởng khi Streamlit reload.
# ══════════════════════════════════════════════════════════════════

def _run_bot_in_thread():
    """
    Hàm chạy trong thread daemon riêng.
    - Tạo event loop MỚI (không share với Streamlit/main thread)
    - Reconnect tự động với exponential backoff khi mất kết nối
    - Dừng sạch khi _shutting_down = True
    """
    global _bot_loop, _shutting_down

    TOKEN = os.environ.get("DISCORD_TOKEN", "")
    if not TOKEN:
        print("[BotThread] FATAL: Biến môi trường DISCORD_TOKEN chưa được đặt!")
        return

    print("[BotThread] Bot thread đang khởi động...")
    loop = None

    try:
        # Tạo event loop riêng cho thread này
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _bot_loop = loop
        _bot_state["loop"] = loop

        MAX_RETRIES = 5
        retry_count = 0
        base_delay  = 5

        while not _shutting_down and retry_count < MAX_RETRIES:
            try:
                # Chạy bot với reconnect=True (tự reconnect khi Discord ngắt kết nối)
                loop.run_until_complete(bot.start(TOKEN, reconnect=True))

            except discord.LoginFailure:
                print("[BotThread] FATAL: Token Discord không hợp lệ! Kiểm tra DISCORD_TOKEN.")
                break

            except KeyboardInterrupt:
                print("[BotThread] KeyboardInterrupt — dừng bot.")
                break

            except Exception as e:
                if _shutting_down:
                    break
                retry_count += 1
                # Exponential backoff: 5s, 10s, 20s, 40s, 80s
                delay = base_delay * (2 ** min(retry_count - 1, 4))
                print(f"[BotThread] Lỗi: {e}")
                print(f"[BotThread] Retry {retry_count}/{MAX_RETRIES} sau {delay}s...")
                traceback.print_exc()
                _time_module.sleep(delay)

            else:
                # bot.start() kết thúc bình thường → graceful shutdown đã xảy ra
                print("[BotThread] Bot đã thoát bình thường.")
                break

        if retry_count >= MAX_RETRIES:
            print(f"[BotThread] Đã thử lại {MAX_RETRIES} lần mà không thành công — dừng hẳn.")

    except Exception as e:
        print(f"[BotThread] Lỗi ngoài ý muốn: {e}")
        traceback.print_exc()
    finally:
        _BOT_STARTED.clear()
        _bot_state["thread"] = None
        _bot_state["loop"] = None
        if loop is not None and not loop.is_closed():
            try:
                loop.close()
            except Exception as e:
                print(f"[BotThread] Lỗi khi đóng event loop: {e}")
        _release_socket_lock()
        print("[BotThread] Bot thread kết thúc.")


def start_bot_once():
    """
    Khởi động bot ĐÚNG MỘT LẦN duy nhất, bất kể Streamlit reload bao nhiêu lần.

    Cơ chế hoạt động:
    1. _BOT_LOCK đảm bảo thread-safety trong cùng process
    2. Socket lock trên 127.0.0.1:BOT_LOCK_PORT chặn nhiều process HF/Streamlit
    3. st.cache_resource gọi hàm này đúng một lần cho mỗi lifecycle Streamlit
    4. daemon=True → thread tự kết thúc khi process tắt
    """
    global _BOT_THREAD

    with _BOT_LOCK:
        existing_thread = _bot_state.get("thread")
        if _BOT_STARTED.is_set() and existing_thread is not None and existing_thread.is_alive():
            print("[Singleton] Bot đã chạy rồi — bỏ qua (Streamlit reload bình thường).")
            return

        if _BOT_STARTED.is_set():
            print("[Singleton] Bot thread cũ không còn chạy — cho phép khởi động lại.")
            _BOT_STARTED.clear()
            _bot_state["thread"] = None

        if not os.environ.get("DISCORD_TOKEN"):
            print("[Singleton] DISCORD_TOKEN chưa được đặt — bỏ qua khởi động bot.")
            return

        if not _acquire_socket_lock():
            return

        print("[Singleton] Khởi động bot lần đầu tiên...")
        _BOT_STARTED.set()

        try:
            _BOT_THREAD = _threading.Thread(
                target=_run_bot_in_thread,
                name="DiscordBotThread",
                daemon=True,  # QUAN TRỌNG: daemon=True → tự tắt khi process tắt
            )
            _bot_state["thread"] = _BOT_THREAD
            _BOT_THREAD.start()
            print(f"[Singleton] Bot thread đã start (ident={_BOT_THREAD.ident})")
        except Exception as e:
            _BOT_STARTED.clear()
            _bot_state["thread"] = None
            _release_socket_lock()
            print(f"[Singleton] Lỗi khi tạo bot thread: {e}")
            traceback.print_exc()


# ── Streamlit UI ──────────────────────────────────────────────────
try:
    import streamlit as st

    st.set_page_config(
        page_title="Anomalies Bot",
        page_icon="🎮",
        layout="wide",
    )

    @st.cache_resource(show_spinner=False)
    def _start_bot_cached_for_streamlit():
        start_bot_once()
        return True

    _start_bot_cached_for_streamlit()

    st.title("🎮 Anomalies Bot — Dashboard")

    col1, col2, col3 = st.columns(3)

    with col1:
        env_label = "☁️ Hugging Face" if _IS_HUGGING_FACE else "🖥️ Local"
        st.metric("Môi trường", env_label)

    with col2:
        bot_status = "🟢 Đang chạy" if _BOT_STARTED.is_set() else "🔴 Chưa khởi động"
        st.metric("Bot Status", bot_status)

    with col3:
        thread_alive = _BOT_THREAD is not None and _BOT_THREAD.is_alive()
        thread_status = "🟢 Active" if thread_alive else "🔴 Stopped"
        st.metric("Bot Thread", thread_status)

    st.divider()

    if _BOT_STARTED.is_set() and thread_alive:
        st.success("Bot đang hoạt động bình thường.")
    elif _BOT_STARTED.is_set() and not thread_alive:
        st.error("Bot thread đã dừng! Kiểm tra log.")
    else:
        st.warning("Bot chưa được khởi động. Kiểm tra biến môi trường DISCORD_TOKEN.")

    with st.expander("Game Stats"):
        st.json(game_stats)

except ImportError:
    # Không chạy trong Streamlit — chế độ standalone
    print("[Main] Streamlit không có — chạy standalone.")
    start_bot_once()
    if _BOT_THREAD:
        try:
            _BOT_THREAD.join()
        except KeyboardInterrupt:
            print("[Main] Nhận Ctrl+C — đang tắt...")
            _shutting_down = True
