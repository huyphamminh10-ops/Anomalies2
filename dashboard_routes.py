# ══════════════════════════════════════════════════════════════════
# dashboard_routes.py — Anomalies Dashboard v2.3
# Tích hợp trực tiếp vào app.py FastAPI
#
# - Discord OAuth2 Login (identify + guilds)
# - Signed cookie session (HMAC-SHA256, không cần DB)
# - Routes: /auth/*, /api/dash/*, /dashboard (SPA)
# - Chia sẻ trực tiếp: guilds, active_games, bot, game_stats
# - Không cần process riêng, không cần port riêng
#
# THÊM MỚI v2.3:
#   + /api/dash/stats              — thống kê tổng quan (owner)
#   + /api/dash/player/{user_id}   — tra cứu player
#   + /api/dash/me/guilds          — alias cho /api/dash/guilds
#   + /api/dash/me                 — alias cho /api/me
#   + Fix feedback 500: nội dung rỗng vẫn OK nếu có ảnh
# ══════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx

import config_manager
import database_tidb
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

# ──────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────
BOT_OWNER_ID          = 1306441206296875099
DISCORD_CLIENT_ID     = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI  = os.environ.get("DISCORD_REDIRECT_URI", "")
_SECRET_KEY           = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
DISCORD_API           = "https://discord.com/api/v10"

# Shared state — được gán từ app.py sau khi import
_shared: dict = {
    "bot":          None,   # commands.Bot instance
    "guilds":       {},     # guild state dict từ app.py
    "active_games": {},     # active GameEngine instances
    "game_stats":   {},     # game_stats dict từ app.py
    "col":          None,   # hàm col(name) từ config_manager
}


def init_shared(bot, guilds: dict, active_games: dict, game_stats: dict, col_fn):
    """Gọi từ app.py sau khi bot sẵn sàng để truyền shared state."""
    _shared["bot"]          = bot
    _shared["guilds"]       = guilds
    _shared["active_games"] = active_games
    _shared["game_stats"]   = game_stats
    _shared["col"]          = col_fn


# ──────────────────────────────────────────────────────────────────
# SESSION — Signed cookie (không cần Redis / DB)
# ──────────────────────────────────────────────────────────────────

def _sign(data: str) -> str:
    return hmac.new(_SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()


def _set_session(response: Response, user_id: str, access_token: str,
                 username: str, avatar: str) -> None:
    payload = f"{user_id}|{access_token}|{username}|{avatar}"
    sig     = _sign(payload)
    cookie  = f"{payload}||{sig}"
    response.set_cookie(
        "dash_session", cookie,
        httponly=True, samesite="lax", max_age=86_400 * 7,
    )


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


# ──────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────

def _col(name: str):
    fn = _shared.get("col")
    return fn(name) if fn else None


def _discord_permissions_int(g: dict) -> int:
    """Discord trả `permissions` dạng string (bitfield); ép int an toàn."""
    p = g.get("permissions", 0)
    if isinstance(p, str):
        try:
            return int(p)
        except ValueError:
            return 0
    try:
        return int(p or 0)
    except (TypeError, ValueError):
        return 0


def _guild_state_summary() -> list[dict]:
    """Lấy trạng thái tất cả guild từ in-memory state (real-time), fallback về DB."""
    bot          = _shared.get("bot")
    guilds       = _shared.get("guilds", {})
    active_games = _shared.get("active_games", {})

    if guilds is None:
        cfg_col = _col("guild_configs")
        if cfg_col is not None:
            docs = list(cfg_col.find({}, {"_id": 0, "guild_id": 1, "guild_name": 1, "status": 1, "max_players": 1, "min_players": 1, "countdown_time": 1}))
            return [{
                "guild_id":     d.get("guild_id", ""),
                "guild_name":   d.get("guild_name") or d.get("guild_id", ""),
                "icon":         None,
                "status":       d.get("status", "waiting"),
                "player_count": 0,
                "max_players":  d.get("max_players", 65),
                "min_players":  d.get("min_players", 5),
                "countdown_time": d.get("countdown_time", 200),
            } for d in docs]
        return []

    result = []
    for gid, gs in guilds.items():
        discord_guild = bot.get_guild(int(gid)) if bot else None
        name = discord_guild.name if discord_guild else gid
        icon = str(discord_guild.icon.url) if (discord_guild and discord_guild.icon) else None

        state = gs.get("state", "WAITING")
        if gid in active_games:
            status = "playing"
        elif state in ("COUNTDOWN", "FULL_FAST"):
            status = "countdown"
        elif state == "WAITING":
            status = "waiting"
        else:
            status = state.lower()

        players = gs.get("players_join_order", [])
        result.append({
            "guild_id":       gid,
            "guild_name":     name,
            "icon":           icon,
            "status":         status,
            "player_count":   len(players),
            "max_players":    gs.get("max_players", 65),
            "min_players":    gs.get("min_players", 5),
            "countdown_time": gs.get("countdown_seconds", gs.get("countdown_time", 200)),
        })
    return result


def _get_guild_full_status(guild_id: str) -> dict:
    """Chi tiết trạng thái một guild — dùng cho admin rooms."""
    bot          = _shared.get("bot")
    guilds       = _shared.get("guilds", {})
    active_games = _shared.get("active_games", {})
    gs           = guilds.get(guild_id, {})

    discord_guild = bot.get_guild(int(guild_id)) if bot else None
    name = discord_guild.name if discord_guild else guild_id
    icon = str(discord_guild.icon.url) if (discord_guild and discord_guild.icon) else None

    state = gs.get("state", "WAITING")
    if guild_id in active_games:
        status = "playing"
    elif state == "COUNTDOWN":
        status = "countdown"
    elif state == "FULL_FAST":
        status = "full"
    elif state == "WAITING":
        status = "waiting"
    else:
        status = state.lower()

    players = gs.get("players_join_order", [])
    player_info = []
    for m in players:
        player_info.append({
            "id":     str(m.id),
            "name":   m.display_name,
            "avatar": str(m.display_avatar.url) if hasattr(m, "display_avatar") else None,
        })

    game_info = {}
    if guild_id in active_games:
        game = active_games[guild_id]
        try:
            # FIX: đếm chính xác từ property alive_players của class game
            alive_players = list(game.alive_players) if hasattr(game, "alive_players") else []
            dead_players  = list(game.dead_players)  if hasattr(game, "dead_players")  else []
            alive_ids     = [str(p.id) for p in alive_players]
            dead_ids      = [str(p.id) for p in dead_players]

            # FIX: lấy danh sách vai trò đang có mặt từ game.roles dict
            roles_map = getattr(game, "roles", {})
            active_role_names = []
            role_faction_counts = {}
            for pid, role_obj in roles_map.items():
                if str(pid) not in alive_ids:
                    continue  # chỉ tính vai trò còn sống
                rname    = getattr(role_obj, "name", "?")
                rfaction = getattr(role_obj, "team", "?")
                active_role_names.append(rname)
                role_faction_counts[rfaction] = role_faction_counts.get(rfaction, 0) + 1

            game_info = {
                "alive_count":    len(alive_ids),
                "dead_count":     len(dead_ids),
                "day":            getattr(game, "day_count", 0),
                "phase":          getattr(game, "phase", "unknown"),
                "active_roles":   sorted(set(active_role_names)),
                "faction_counts": role_faction_counts,
            }
        except Exception as _ge:
            print(f"[api_room_detail] game_info error: {_ge}")
            game_info = {"alive_count": 0, "dead_count": 0, "day": 0, "phase": "unknown", "error": str(_ge)}

    cfg_col = _col("guild_configs")
    cfg = {}
    if cfg_col is not None:
        doc = cfg_col.find_one({"guild_id": guild_id})
        if doc:
            doc.pop("_id", None)
            cfg = doc

    return {
        "guild_id":     guild_id,
        "guild_name":   name,
        "icon":         icon,
        "status":       status,
        "player_count": len(players),
        "players":      player_info,
        "game_info":    game_info,
        "config":       cfg,
    }


# ──────────────────────────────────────────────────────────────────
# ROLE CATALOG — tự động đọc từ roles/ classes
# Hàm _build_roles_catalog() quét AST các file role và trích xuất
# name, team, description, fake_good, anomaly_chat_mgr trực tiếp.
# ──────────────────────────────────────────────────────────────────

def _build_roles_catalog() -> list:
    """
    Đọc trực tiếp từ các file class trong thư mục roles/.
    Trả về danh sách 43 vai trò với name/team/faction/description
    được lấy nguyên từ source code — không ghi đè thủ công.
    """
    import ast as _ast
    import glob as _glob

    _COLOR_MAP = {
        'Dân Thường': '#4ade80', 'Thám Trưởng': '#60a5fa', 'Thám Tử': '#38bdf8',
        'Cai Ngục': '#f59e0b', 'Nhà Dược Học Điên': '#ef4444', 'Thị Trưởng': '#a78bfa',
        'Phụ Tá Thị Trưởng': '#c4b5fd', 'Nhà Ngoại Cảm': '#94a3b8',
        'Người Tiên Tri': '#6366f1', 'Kẻ Báo Oán': '#ec4899', 'Điệp Viên': '#34d399',
        'Kiến Trúc Sư': '#06b6d4', 'Nhà Lưu Trữ': '#8b5cf6', 'Kẻ Báo Thù': '#dc2626',
        'Người Giám Sát': '#f97316', 'Kẻ Ngủ Mê': '#64748b', 'Thợ Đặt Bẫy': '#84cc16',
        'Kẻ Trừng Phạt': '#fb923c', 'Dị Thể': '#f87171', 'Dị Thể Hành Quyết': '#ef4444',
        'Lãnh Chúa': '#dc2626', 'Lao Công': '#b91c1c', 'Tín Hiệu Giả': '#991b1b',
        'Ký Sinh Thần Kinh': '#7f1d1d', 'Kiến Trúc Sư Bóng Tối': '#450a0a',
        'Kẻ Rình Rập': '#fca5a5', 'Kẻ Đánh Cắp Lời Thì Thầm': '#fecaca',
        'Nguồn Tĩnh Điện': '#fee2e2', 'Máy Hủy Tài Liệu': '#ef4444',
        'Kẻ Mô Phỏng Sinh Học': '#dc2626', 'Sứ Giả Tận Thế': '#ff6b35',
        'Kẻ Điều Khiển': '#fb7185', 'Mù Quáng': '#a78bfa', 'Kẻ Giải Mã': '#22d3ee',
        'Người Thử Nghiệm': '#38d9f5', 'KẺ GIẾT NGƯỜI HÀNG LOẠT': '#fbbf24',
        'A.I THA HÓA': '#d97706', 'ĐỒNG HỒ TẬN THẾ': '#b45309',
        'Kẻ Dệt Mộng': '#7c3aed', 'Con Tàu Ma': '#475569', 'Sâu Lỗi': '#ef4444',
        'Kẻ Tâm Thần': '#f59e0b', 'Kẻ Dệt Thời Gian': '#8b5cf6',
    }
    # Vai trò có khả năng đặc biệt cần icon cảnh báo
    _SPECIAL_FLAGS: dict = {
        'Kẻ Mô Phỏng Sinh Học': {'fake_good': True},
        'Tín Hiệu Giả':          {'fake_good': True},
        'Mù Quáng':              {'anomaly_chat_mgr': True},
        'Thám Trưởng':           {'anomaly_chat_mgr': True},
        'Kẻ Tâm Thần':           {'anomaly_chat_mgr': True},
    }
    _FOLDER_FACTION = {
        'survivors': 'Survivors',
        'anomalies': 'Anomalies',
        'unknown':   'Neutrals',
        'event':     'Event',
    }

    import os as _os
    base_dir = _os.path.dirname(_os.path.abspath(__file__))
    pattern  = _os.path.join(base_dir, 'roles', '**', '*.py')
    role_files = sorted(_glob.glob(pattern, recursive=True))
    role_files = [
        f for f in role_files
        if '__init__' not in f
        and 'base_role' not in f
        and 'role_manager' not in f
    ]

    catalog = []
    for filepath in role_files:
        try:
            with open(filepath, encoding='utf-8') as fh:
                src = fh.read()
            tree = _ast.parse(src)
            for node in _ast.walk(tree):
                if not isinstance(node, _ast.ClassDef):
                    continue
                attrs: dict = {}
                for item in node.body:
                    if not isinstance(item, _ast.Assign):
                        continue
                    for t in item.targets:
                        if isinstance(t, _ast.Name) and t.id in (
                            'name', 'team', 'description', 'dm_message'
                        ):
                            try:
                                attrs[t.id] = _ast.literal_eval(item.value)
                            except Exception:
                                pass
                if 'name' not in attrs or 'team' not in attrs:
                    continue
                # Xác định folder (survivors/anomalies/unknown/event)
                parts = filepath.replace('\\', '/').split('/roles/')
                folder = parts[1].split('/')[0] if len(parts) > 1 else 'unknown'
                name   = attrs['name']
                flags  = _SPECIAL_FLAGS.get(name, {})
                catalog.append({
                    'name':             name,
                    'team':             attrs.get('team', ''),
                    'faction':          _FOLDER_FACTION.get(folder, folder.capitalize()),
                    'color':            _COLOR_MAP.get(name, '#888888'),
                    'description':      (attrs.get('description') or '').strip(),
                    'dm_message':       attrs.get('dm_message', ''),
                    'fake_good':        flags.get('fake_good', False),
                    'anomaly_chat_mgr': flags.get('anomaly_chat_mgr', False),
                })
        except Exception as exc:
            print(f'[roles_catalog] Lỗi parse {filepath}: {exc}')

    return catalog


# Build catalog một lần khi module load — cache lại để tránh re-parse mỗi request
try:
    _ROLES_CATALOG = _build_roles_catalog()
    print(f'[roles_catalog] Loaded {len(_ROLES_CATALOG)} roles from source files.')
except Exception as _e:
    print(f'[roles_catalog] Fallback — không đọc được roles/: {_e}')
    _ROLES_CATALOG = []

# ──────────────────────────────────────────────────────────────────
# ROUTER
# ──────────────────────────────────────────────────────────────────

router = APIRouter()


# ── AUTH ───────────────────────────────────────────────────────────

@router.get("/auth/login")
@router.get("/auth/discord/login")
async def auth_login(request: Request):
    state = secrets.token_hex(16)
    redirect_uri = DISCORD_REDIRECT_URI
    if not redirect_uri:
        base = str(request.base_url).rstrip("/")
        redirect_uri = f"{base}/auth/discord/callback"
    import urllib.parse
    url = (
        "https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&response_type=code"
        f"&scope=identify%20guilds"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/auth/callback")
@router.get("/auth/discord/callback")
async def auth_callback(request: Request, code: str, response: Response, state: str = ""):
    async with httpx.AsyncClient() as http:
        used_redirect = DISCORD_REDIRECT_URI
        if not used_redirect:
            base = str(request.base_url).rstrip("/")
            used_redirect = f"{base}/auth/discord/callback"
        tr = await http.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id":     DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  used_redirect,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if tr.status_code != 200:
            raise HTTPException(400, "Không lấy được token Discord")
        access_token = tr.json()["access_token"]

        ur = await http.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if ur.status_code != 200:
            raise HTTPException(400, "Không lấy được thông tin user")
        user = ur.json()

    uid      = user["id"]
    username = user.get("global_name") or user.get("username", "Unknown")
    avatar_h = user.get("avatar", "")
    avatar   = (
        f"https://cdn.discordapp.com/avatars/{uid}/{avatar_h}.png"
        if avatar_h else
        f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"
    )
    redir = HTMLResponse(
        content='<html><head><meta http-equiv="refresh" content="0;url=/dashboard"></head><body>Đang chuyển hướng...</body></html>',
        status_code=200,
    )
    _set_session(redir, uid, access_token, username, avatar)
    return redir


@router.get("/auth/logout")
async def auth_logout():
    redir = RedirectResponse("/dashboard", status_code=302)
    redir.delete_cookie("dash_session")
    return redir


# ── API — CHUNG ────────────────────────────────────────────────────

@router.get("/api/me")
@router.get("/api/dash/me")
async def api_me(request: Request):
    s = _get_session(request)
    if not s:
        return JSONResponse({"logged_in": False}, status_code=401)
    return JSONResponse({
        "logged_in": True,
        "user_id":   s["user_id"],
        "username":  s["username"],
        "avatar":    s["avatar"],
        "is_owner":  s["is_owner"],
    })


@router.get("/api/dash/roles")
async def api_roles(request: Request):
    _require_auth(request)
    return JSONResponse(_ROLES_CATALOG)


@router.get("/api/dash/guilds")
@router.get("/api/dash/me/guilds")
async def api_guilds(request: Request):
    """
    Server mà user tham gia trên Discord VÀ bot đang ở server đó
    (hoặc đã có bản ghi guild_configs / lobby in-memory).
    Trước đây chỉ hiện khi đã có MongoDB config → user không thấy server mới.
    """
    s = _require_auth(request)
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {s['access_token']}"},
        )
        raw = resp.json() if resp.status_code == 200 else []
    user_guilds = raw if isinstance(raw, list) else []

    bot         = _shared.get("bot")
    cfg_col     = _col("guild_configs")
    in_memory   = _shared.get("guilds") or {}
    result      = []

    for g in user_guilds:
        gid = str(g.get("id", ""))
        if not gid:
            continue

        has_config = False
        if cfg_col is not None:
            has_config = cfg_col.count_documents({"guild_id": gid}, limit=1) > 0

        bot_in_guild = False
        discord_guild = None
        if bot is not None and getattr(bot, "user", None):
            try:
                discord_guild = bot.get_guild(int(gid))
                bot_in_guild = discord_guild is not None
            except (ValueError, TypeError):
                bot_in_guild = False

        if not has_config and gid not in in_memory and not bot_in_guild:
            continue

        perms = _discord_permissions_int(g)
        is_manager = bool(perms & 0x20) or bool(perms & 0x08) or bool(g.get("owner", False))
        icon_api = g.get("icon")
        if discord_guild and discord_guild.icon:
            icon_url = str(discord_guild.icon.url)
        elif icon_api:
            icon_url = f"https://cdn.discordapp.com/icons/{gid}/{icon_api}.png?size=64"
        else:
            icon_url = None

        result.append({
            "id":           gid,
            "name":         g.get("name", gid),
            "icon":         icon_url,
            "is_manager":   is_manager,
            "permissions":  str(perms),
        })
    return JSONResponse(result)


@router.get("/api/dash/guild/{guild_id}/config")
async def api_guild_config(guild_id: str, request: Request):
    s = _require_auth(request)
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {s['access_token']}"},
        )
        user_guilds = resp.json() if resp.status_code == 200 else []
    if not isinstance(user_guilds, list):
        user_guilds = []
    if not any(str(g.get("id")) == str(guild_id) for g in user_guilds):
        raise HTTPException(403, "Bạn không thuộc server này")

    # Không bắt buộc đã có document — trả default giống bot (load_guild_config)
    cfg = config_manager.load_guild_config(guild_id)
    return JSONResponse(cfg)


@router.post("/api/dash/guild/{guild_id}/config")
async def api_update_config(guild_id: str, request: Request):
    s = _require_auth(request)

    # Kiểm tra quyền MANAGE_GUILD qua Discord API
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {s['access_token']}"},
        )
        user_guilds = resp.json() if resp.status_code == 200 else []

    guild = next((g for g in user_guilds if str(g.get("id")) == str(guild_id)), None)
    if not guild:
        raise HTTPException(403, "Lỗi: Bạn không có quyền chỉnh sửa phòng của server này")

    perms      = _discord_permissions_int(guild)
    is_manager = bool(perms & 0x20) or bool(perms & 0x08) or bool(guild.get("owner", False))
    if not is_manager and not s["is_owner"]:
        raise HTTPException(403, f"Lỗi: Bạn không có quyền chỉnh sửa phòng của server {guild['name']}")

    data = await request.json()
    _ALLOWED = {
        "max_players", "min_players", "countdown_time",
        "allow_chat", "mute_dead", "no_remove_roles",
        "music", "skip_discussion", "day_time",
        "vote_time", "skip_discussion_delay",
        "text_channel_id", "voice_channel_id",
        "dead_role_id", "alive_role_id",
    }
    update = {k: v for k, v in data.items() if k in _ALLOWED}
    if not update:
        raise HTTPException(400, "Không có field hợp lệ")

    cfg_col = _col("guild_configs")
    if cfg_col is not None:
        cfg_col.update_one({"guild_id": guild_id}, {"$set": update}, upsert=True)
        # Invalidate cache trong app.py nếu có
        try:
            import sys
            app_mod = sys.modules.get("app") or sys.modules.get("__main__")
            if app_mod and hasattr(app_mod, "invalidate_config_cache"):
                app_mod.invalidate_config_cache(guild_id)
        except Exception:
            pass
    return JSONResponse({"ok": True})


@router.get("/api/dash/guild/{guild_id}/status")
async def api_guild_status(guild_id: str, request: Request):
    _require_auth(request)
    guilds       = _shared.get("guilds", {})
    active_games = _shared.get("active_games", {})
    gs           = guilds.get(guild_id, {})
    state        = gs.get("state", "WAITING")
    if guild_id in active_games:
        status = "playing"
    elif state == "COUNTDOWN":
        status = "countdown"
    elif state == "FULL_FAST":
        status = "full"
    else:
        status = "waiting"
    players = gs.get("players_join_order", [])
    return JSONResponse({
        "status":         status,
        "player_count":   len(players),
        "state":          state,
        # countdown_seconds = giây còn lại trong RAM (real-time)
        # countdown_time    = cấu hình gốc (DB)
        "countdown_time": gs.get("countdown_seconds", gs.get("countdown_time", 200)),
        "max_players":    gs.get("max_players", 65),
        "min_players":    gs.get("min_players", 5),
    })


@router.get("/api/dash/changelog")
async def api_changelog(request: Request):
    _require_auth(request)
    cl_col = _col("changelogs")
    if cl_col is None:
        return JSONResponse([])
    logs = list(cl_col.find({}, {"_id": 0}).sort("created_at", -1).limit(30))
    return JSONResponse(logs)


@router.post("/api/dash/feedback")
async def api_feedback(request: Request):
    s    = _require_auth(request)
    data = await request.json()
    content = str(data.get("content", "")).strip()[:2000]
    images  = [str(u) for u in data.get("images", [])[:5] if u]
    # FIX: cho phép nội dung rỗng nếu có ảnh
    if not content and not images:
        raise HTTPException(400, "Nội dung trống")
    fb_col = _col("feedbacks")
    if fb_col is not None:
        fb_col.insert_one({
            "user_id":    s["user_id"],
            "username":   s["username"],
            "avatar":     s["avatar"],
            "content":    content,
            "images":     images,
            "reply":      None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return JSONResponse({"ok": True})


@router.get("/api/dash/stats")
async def api_stats(request: Request):
    """
    Thống kê tổng quan — mọi user đã đăng nhập.
    Schema khớp dashboard/index.html (total_guilds, db_ok, tidb_ok, …).
    """
    _require_auth(request)

    active_games = _shared.get("active_games") or {}
    active_games_count = len(active_games)

    mongo_ok = config_manager._get_db() is not None
    total_guilds = 0
    total_bans = 0
    if mongo_ok:
        try:

            def _mongo_counts():
                db = config_manager._get_db()
                if db is None:
                    return (0, 0, 0)
                guilds_n = db["guild_configs"].count_documents({})
                bans_n   = db["bans"].count_documents({})
                # Feedback count tu MongoDB collection (backup neu TiDB chua san)
                try:
                    feedbacks_n = db["feedbacks"].count_documents({})
                except Exception:
                    feedbacks_n = 0
                return (guilds_n, bans_n, feedbacks_n)

            loop = asyncio.get_event_loop()
            total_guilds, total_bans, mongo_feedback_count = await loop.run_in_executor(None, _mongo_counts)
        except Exception as e:
            print(f"[api_stats] Lỗi MongoDB count: {e}")
            mongo_ok = False
            mongo_feedback_count = 0

    tidb_ok = False
    total_feedbacks = 0
    total_changelogs = 0
    try:
        loop = asyncio.get_event_loop()

        def _tidb_counts():
            # Bọc từng hàm riêng — tránh lỗi bảng chưa tồn tại làm crash cả hai
            try:
                fb = database_tidb.count_feedbacks()
            except Exception as e_fb:
                print(f"[api_stats] count_feedbacks lỗi: {e_fb}")
                fb = 0
            try:
                cl = database_tidb.count_update_logs()
            except Exception as e_cl:
                print(f"[api_stats] count_update_logs lỗi: {e_cl}")
                cl = 0
            return (fb, cl)

        total_feedbacks, total_changelogs = await loop.run_in_executor(None, _tidb_counts)
        tidb_ok = True
    except Exception as e:
        print(f"[api_stats] Lỗi TiDB count: {e}")

    # Nếu TiDB không trả được số feedback, fallback về MongoDB count
    if not tidb_ok and mongo_ok:
        total_feedbacks = locals().get("mongo_feedback_count", 0)

    return JSONResponse({
        "total_guilds":     total_guilds,
        "active_games":     active_games_count,
        "total_bans":       total_bans,
        "total_feedbacks":  total_feedbacks,
        "total_changelogs": total_changelogs,
        "db_ok":            mongo_ok,
        "tidb_ok":          tidb_ok,
        "serverCount":      total_guilds,
        "banCount":         total_bans,
        "feedbackCount":    total_feedbacks,
    })


@router.get("/api/dash/player/{user_id}")
async def api_player_lookup(user_id: str, request: Request):
    """
    Tra cứu thông tin người chơi theo Discord user_id.

    FIX:
    - Ép uid về str trước khi query MongoDB để tránh lỗi làm tròn số BigInt JS.
    - Nếu người chơi đang trong game với vai Sheriff, trả thêm used_tonight
      để Admin biết họ đã dùng kỹ năng chưa.
    """
    _require_auth(request)
    # Luôn ép về string — Discord ID là 64-bit int, JS float64 mất chính xác
    uid_str = str(user_id).strip()
    if not uid_str or not uid_str.isdigit():
        raise HTTPException(400, "user_id không hợp lệ — phải là chuỗi số Discord ID")
    try:
        players_col = _col("players")
        if players_col is None:
            raise HTTPException(503, "Database chưa kết nối — thử lại sau")
        # FIX: query bằng str, tránh int conversion gây mất bit trên ID lớn
        doc = players_col.find_one({"user_id": uid_str})
        if not doc:
            # Thử tìm bằng int (fallback cho DB cũ lưu int)
            try:
                doc = players_col.find_one({"user_id": int(uid_str)})
            except Exception:
                pass
        if not doc:
            raise HTTPException(404, f"Không tìm thấy người chơi ID={uid_str}")
        doc.pop("_id", None)

        # Bổ sung trạng thái in-game nếu đang có game (Sheriff used_tonight)
        active_games = _shared.get("active_games") or {}
        in_game_info: dict | None = None
        for gid, game in active_games.items():
            try:
                roles_map = getattr(game, "roles", {})
                uid_int   = int(uid_str)
                role      = roles_map.get(uid_int)
                if role is None:
                    continue
                role_name = getattr(role, "name", "")
                entry = {
                    "guild_id":   gid,
                    "role_name":  role_name,
                    "is_alive":   uid_int in [
                        p.id for p in (game.alive_players if hasattr(game, "alive_players") else [])
                    ],
                }
                # Sheriff: hiển thị trạng thái used_tonight để Admin theo dõi
                if role_name in ("Thám Trưởng", "Sheriff"):
                    entry["used_tonight"] = bool(getattr(role, "used_tonight", False))
                in_game_info = entry
                break
            except Exception:
                pass

        if in_game_info:
            doc["in_game"] = in_game_info

        return JSONResponse(doc)
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[api_player_lookup] Lỗi DB uid={uid_str}: {exc}")
        raise HTTPException(500, f"Lỗi kết nối database: {type(exc).__name__}")


# ── API — OWNER ONLY ───────────────────────────────────────────────

@router.get("/api/dash/admin/feedbacks")
async def api_admin_feedbacks(request: Request):
    _require_owner(request)
    fb_col = _col("feedbacks")
    if fb_col is None:
        return JSONResponse([])
    docs = list(fb_col.find({}, {"_id": 0}).sort("created_at", -1).limit(100))
    return JSONResponse(docs)


@router.delete("/api/dash/admin/feedback/{fb_id}")
async def api_delete_feedback(fb_id: str, request: Request):
    """
    Xóa feedback khỏi MongoDB theo ObjectId hoặc TiDB theo ID 15 ký tự.
    Chỉ BOT_OWNER mới có quyền.
    """
    _require_owner(request)
    fb_id = str(fb_id).strip()
    if not fb_id:
        raise HTTPException(400, "Thiếu fb_id")

    # Thử xóa trong MongoDB (nếu có collection feedbacks)
    fb_col = _col("feedbacks")
    deleted_mongo = False
    if fb_col is not None:
        try:
            from bson import ObjectId
            result = fb_col.delete_one({"_id": ObjectId(fb_id)})
            deleted_mongo = result.deleted_count > 0
        except Exception:
            # Nếu fb_id không phải ObjectId, thử tìm theo created_at
            try:
                result = fb_col.delete_one({"created_at": fb_id})
                deleted_mongo = result.deleted_count > 0
            except Exception as exc:
                print(f"[api_delete_feedback] Lỗi MongoDB: {exc}")

    # Thử xóa trong TiDB (ID 15 ký tự)
    deleted_tidb = False
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, database_tidb.delete_feedback, fb_id)
        deleted_tidb = res.get("ok", False)
    except Exception as exc:
        print(f"[api_delete_feedback] Lỗi TiDB: {exc}")

    if not deleted_mongo and not deleted_tidb:
        raise HTTPException(404, f"Không tìm thấy feedback id={fb_id}")

    return JSONResponse({"ok": True, "deleted_mongo": deleted_mongo, "deleted_tidb": deleted_tidb})


@router.post("/api/dash/admin/feedback/reply")
async def api_reply_feedback(request: Request):
    """
    Ghi phản hồi feedback vào DB và (tuỳ chọn) gửi qua Discord Webhook.
    Body JSON:
      created_at  — định danh feedback trong MongoDB
      fb_id       — ID 15 ký tự TiDB (nếu có)
      reply       — nội dung phản hồi (tối đa 1000 ký tự)
      webhook_url — (tuỳ chọn) Discord Webhook URL để thông báo user
    """
    _require_owner(request)
    data        = await request.json()
    created_at  = data.get("created_at", "")
    fb_id       = str(data.get("fb_id", "")).strip()
    reply       = str(data.get("reply", "")).strip()[:1000]
    webhook_url = str(data.get("webhook_url", "")).strip()

    if not reply:
        raise HTTPException(400, "Nội dung phản hồi không được trống")

    # Lưu vào MongoDB
    fb_col = _col("feedbacks")
    if fb_col is not None and created_at:
        try:
            fb_col.update_one(
                {"created_at": created_at},
                {"$set": {"reply": reply}},
            )
        except Exception as exc:
            print(f"[api_reply_feedback] Lỗi MongoDB: {exc}")

    # Lưu vào TiDB (nếu có fb_id 15 ký tự)
    if fb_id:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, database_tidb.reply_feedback, fb_id, reply)
        except Exception as exc:
            print(f"[api_reply_feedback] Lỗi TiDB: {exc}")

    # Gửi Webhook Discord (tuỳ chọn)
    webhook_sent = False
    if webhook_url.startswith("https://discord.com/api/webhooks/"):
        try:
            payload = {
                "embeds": [{
                    "title": "💬 Phản hồi từ Bot Owner",
                    "description": reply,
                    "color": 0x7c6af7,
                    "footer": {
                        "text": f"Anomalies Bot • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                    },
                }]
            }
            async with httpx.AsyncClient() as http:
                wh_resp = await http.post(webhook_url, json=payload, timeout=10)
                webhook_sent = wh_resp.status_code in (200, 204)
        except Exception as exc:
            print(f"[api_reply_feedback] Lỗi gửi Webhook: {exc}")

    return JSONResponse({"ok": True, "webhook_sent": webhook_sent})


@router.post("/api/dash/admin/changelog")
async def api_post_changelog(request: Request):
    _require_owner(request)
    data    = await request.json()
    title   = str(data.get("title",   "")).strip()[:200]
    content = str(data.get("content", "")).strip()[:5000]
    version = str(data.get("version", "")).strip()[:20]
    if not title or not content:
        raise HTTPException(400, "Thiếu tiêu đề hoặc nội dung")
    cl_col = _col("changelogs")
    if cl_col is not None:
        cl_col.insert_one({
            "title":      title,
            "content":    content,
            "version":    version,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return JSONResponse({"ok": True})


@router.get("/api/dash/admin/bans")
async def api_admin_bans(request: Request):
    _require_owner(request)
    ban_col = _col("bans")
    if ban_col is None:
        return JSONResponse([])
    docs = list(ban_col.find({}, {"_id": 0}).sort("created_at", -1))
    return JSONResponse(docs)


@router.post("/api/dash/admin/ban")
async def api_ban_player(request: Request):
    _require_owner(request)
    data    = await request.json()
    user_id = str(data.get("user_id", "")).strip()
    reason  = str(data.get("reason",  "Không có lý do")).strip()[:500]
    mode    = data.get("mode", "ban")
    if mode not in ("ban", "lobby"):
        mode = "ban"
    if not user_id:
        raise HTTPException(400, "Thiếu user_id")
    ban_col = _col("bans")
    if ban_col is not None:
        ban_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id":    user_id,
                "reason":     reason,
                "mode":       mode,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
    return JSONResponse({"ok": True})


@router.delete("/api/dash/admin/ban/{user_id}")
async def api_unban(user_id: str, request: Request):
    _require_owner(request)
    ban_col = _col("bans")
    if ban_col is not None:
        ban_col.delete_one({"user_id": user_id})
    return JSONResponse({"ok": True})


@router.get("/api/dash/admin/rooms")
async def api_admin_rooms(request: Request):
    """Real-time trạng thái phòng (dùng trên trang Thống Kê cho mọi user đã đăng nhập)."""
    _require_auth(request)
    return JSONResponse(_guild_state_summary())


@router.get("/api/dash/admin/room/{guild_id}")
async def api_admin_room_detail(guild_id: str, request: Request):
    """Chi tiết một phòng — danh sách người chơi, game info, config."""
    _require_owner(request)
    return JSONResponse(_get_guild_full_status(guild_id))


@router.post("/api/dash/admin/room/{guild_id}/config")
async def api_admin_room_config(guild_id: str, request: Request):
    """Chủ bot có thể sửa bất kỳ guild nào không giới hạn field."""
    _require_owner(request)
    data = await request.json()
    cfg_col = _col("guild_configs")
    if cfg_col is not None and data:
        data.pop("_id", None)
        data.pop("guild_id", None)
        cfg_col.update_one(
            {"guild_id": guild_id},
            {"$set": data},
            upsert=True,
        )
        try:
            import sys
            app_mod = sys.modules.get("app") or sys.modules.get("__main__")
            if app_mod and hasattr(app_mod, "invalidate_config_cache"):
                app_mod.invalidate_config_cache(guild_id)
        except Exception:
            pass
    return JSONResponse({"ok": True})


# ── SPA SERVE ──────────────────────────────────────────────────────

def _load_spa_html() -> str:
    """Tìm file index.html theo nhiều đường dẫn có thể."""
    base = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base, "dashboard", "index.html"),
        os.path.join(base, "index.html"),
        os.path.join(os.getcwd(), "dashboard", "index.html"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    return (
        "<h2 style='font-family:sans-serif;padding:40px;color:#fff;background:#070a10'>"
        "Dashboard chưa được tìm thấy.<br/>"
        "Đặt file <code>dashboard/index.html</code> cạnh <code>app.py</code>.</h2>"
    )


@router.get("/dashboard")
async def serve_dashboard_root(request: Request):
    """Serve Dashboard SPA — root path."""
    return HTMLResponse(_load_spa_html())


@router.get("/dashboard/{full_path:path}")
async def serve_dashboard_sub(request: Request, full_path: str):
    """Serve Dashboard SPA — sub-paths (client-side routing)."""
    return HTMLResponse(_load_spa_html())
