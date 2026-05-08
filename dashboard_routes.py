# ══════════════════════════════════════════════════════════════════
# dashboard_routes.py — Anomalies Dashboard v1.0
# Tích hợp trực tiếp vào app.py FastAPI
#
# - Discord OAuth2 Login (identify + guilds)
# - Signed cookie session (HMAC-SHA256, không cần DB)
# - Routes: /auth/*, /api/*, / (SPA)
# - Chia sẻ trực tiếp: guilds, active_games, bot, game_stats
# - Không cần process riêng, không cần port riêng
# ══════════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

if TYPE_CHECKING:
    pass

# ──────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────
BOT_OWNER_ID          = 1306441206296875099
DISCORD_CLIENT_ID     = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI  = os.environ.get(
    "DISCORD_REDIRECT_URI",
    "http://localhost:8000/auth/callback",
)
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
    payload   = f"{user_id}|{access_token}|{username}|{avatar}"
    sig       = _sign(payload)
    cookie    = f"{payload}||{sig}"
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


def _guild_state_summary() -> list[dict]:
    """Lấy trạng thái tất cả guild từ in-memory state (real-time)."""
    bot         = _shared.get("bot")
    guilds      = _shared.get("guilds", {})
    active_games= _shared.get("active_games", {})
    result      = []
    for gid, gs in guilds.items():
        discord_guild = bot.get_guild(int(gid)) if bot else None
        name  = discord_guild.name if discord_guild else gid
        icon  = None
        if discord_guild and discord_guild.icon:
            icon = str(discord_guild.icon.url)

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
            "guild_id":      gid,
            "guild_name":    name,
            "icon":          icon,
            "status":        status,
            "player_count":  len(players),
            "max_players":   gs.get("countdown_time", 65),  # placeholder
        })
    return result


def _get_guild_full_status(guild_id: str) -> dict:
    """Chi tiết trạng thái một guild — dùng cho admin rooms."""
    bot          = _shared.get("bot")
    guilds       = _shared.get("guilds", {})
    active_games = _shared.get("active_games", {})
    gs           = guilds.get(guild_id, {})

    discord_guild = bot.get_guild(int(guild_id)) if bot else None
    name  = discord_guild.name if discord_guild else guild_id
    icon  = str(discord_guild.icon.url) if (discord_guild and discord_guild.icon) else None

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
            "id":           str(m.id),
            "name":         m.display_name,
            "avatar":       str(m.display_avatar.url) if hasattr(m, "display_avatar") else None,
        })

    # Active game info nếu đang chơi
    game_info = {}
    if guild_id in active_games:
        game = active_games[guild_id]
        try:
            alive = [str(p.id) for p in game.alive_players] if hasattr(game, "alive_players") else []
            dead  = [str(p.id) for p in game.dead_players]  if hasattr(game, "dead_players")  else []
            game_info = {
                "alive_count": len(alive),
                "dead_count":  len(dead),
                "day":         getattr(game, "day_count", 0),
                "phase":       getattr(game, "phase", "unknown"),
            }
        except Exception:
            pass

    # Config từ DB
    cfg_col = _col("guild_configs")
    cfg = {}
    if cfg_col:
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
# ROLE CATALOG (38 vai trò)
# ──────────────────────────────────────────────────────────────────

_ROLES_CATALOG = [
    # Survivors
    {"name":"Thường Dân",          "faction":"Survivors","description":"Không có kỹ năng đặc biệt. Sống sót đến cuối game là chiến thắng.","color":"#4ade80","tips":"Quan sát hành vi người chơi và bỏ phiếu sáng suốt."},
    {"name":"Thám Trưởng",         "faction":"Survivors","description":"Điều tra một người mỗi đêm để biết họ thuộc phe nào.","color":"#60a5fa","tips":"Xác nhận thông tin từ nhiều nguồn trước khi cáo buộc công khai."},
    {"name":"Cai Ngục",            "faction":"Survivors","description":"Giam cầm một người mỗi đêm. Có thể thẩm vấn và xử tử.","color":"#f59e0b","tips":"Nhốt người nghi vấn vào những đêm mấu chốt để vô hiệu hóa hành động của họ."},
    {"name":"Thị Trưởng",          "faction":"Survivors","description":"Có thể lộ diện để nhận 3 phiếu bầu. Rất mạnh nhưng nguy hiểm.","color":"#a78bfa","tips":"Thời điểm lộ diện quyết định thắng bại — đừng hành động quá sớm."},
    {"name":"Trợ Lý Thị Trưởng",  "faction":"Survivors","description":"Hỗ trợ Thị Trưởng và nhận quyền bầu cử đặc biệt khi cần.","color":"#c4b5fd","tips":"Phối hợp chặt với Thị Trưởng để kiểm soát vote."},
    {"name":"Thám Tử",             "faction":"Survivors","description":"Điều tra sâu hơn, nhận thêm thông tin cụ thể về vai trò mục tiêu.","color":"#38bdf8","tips":"Kết hợp với Thám Trưởng để xác nhận nghi phạm nhanh hơn."},
    {"name":"Pháp Quan",           "faction":"Survivors","description":"Giao tiếp với người đã chết để lấy thông tin mỗi đêm.","color":"#94a3b8","tips":"Thông tin từ người chết rất quý — hãy chuyển tải khéo léo mà không lộ vai trò."},
    {"name":"Điệp Viên",           "faction":"Survivors","description":"Theo dõi ai đó và biết họ đã làm gì đêm qua.","color":"#34d399","tips":"Theo dõi những người im lặng nhưng có vẻ tự tin bất thường."},
    {"name":"Cảnh Sát",            "faction":"Survivors","description":"Bắn chết một người vào ban ngày. Chỉ được dùng 1 lần.","color":"#fb923c","tips":"Chỉ hành động khi chắc chắn — sai lầm có thể gây hại cho phe bạn."},
    {"name":"Bẫy Thủ",            "faction":"Survivors","description":"Đặt bẫy để phát hiện và bắt Dị Thể tấn công.","color":"#84cc16","tips":"Đặt bẫy gần người quan trọng (Thám Trưởng, Cai Ngục) để bảo vệ."},
    {"name":"Kiến Trúc Sư",        "faction":"Survivors","description":"Xây dựng công trình phòng thủ, gia cố bảo vệ người chơi khác.","color":"#06b6d4","tips":"Ưu tiên bảo vệ các vai trò điều tra và kiểm soát."},
    {"name":"Nhà Lưu Trữ",         "faction":"Survivors","description":"Bảo quản bằng chứng và thông tin quan trọng qua các đêm.","color":"#8b5cf6","tips":"Ghi chép kỹ lưỡng để cung cấp bằng chứng vào ban ngày."},
    {"name":"Phục Sinh Sư",        "faction":"Survivors","description":"Hồi sinh một người đã chết. Cực kỳ hiếm và mạnh.","color":"#ec4899","tips":"Hồi sinh Thám Trưởng hoặc Cai Ngục ở giai đoạn cuối để lật ngược thế cờ."},
    {"name":"Giám Hộ Viên",        "faction":"Survivors","description":"Canh gác mục tiêu — kẻ tấn công mục tiêu sẽ bị tiêu diệt.","color":"#f97316","tips":"Ưu tiên bảo vệ các vai trò quan trọng như Thám Trưởng hoặc Cai Ngục."},
    {"name":"Tâm Lý Gia",          "faction":"Survivors","description":"Đọc hành vi và phát hiện vai trò qua tâm lý.","color":"#6366f1","tips":"Chú ý ai nói quá nhiều hoặc quá ít so với bình thường."},
    {"name":"Người Ngủ",           "faction":"Survivors","description":"Có vẻ bình thường nhưng có khả năng đặc biệt xảy ra khi ngủ.","color":"#64748b","tips":"Giữ bình thản — thông tin đến khi bạn ít ngờ tới nhất."},
    {"name":"Dược Sĩ Điên",        "faction":"Survivors","description":"Tạo ra các loại thuốc ngẫu nhiên — có thể cứu người hoặc gây hại.","color":"#ef4444","tips":"Rủi ro cao, phần thưởng cao — chỉ dùng khi thực sự cần thiết."},
    {"name":"Người Báo Thù",       "faction":"Survivors","description":"Sau khi chết, có thể tiêu diệt kẻ đã giết mình.","color":"#dc2626","tips":"Hãy để lại di chúc rõ ràng để đồng đội biết ai đã giết bạn."},
    # Anomalies
    {"name":"Dị Thể",              "faction":"Anomalies","description":"Dị Thể cơ bản. Giết một người mỗi đêm để loại bỏ Survivors.","color":"#f87171","tips":"Ưu tiên tiêu diệt Thám Trưởng, Cai Ngục và Thám Tử trước tiên."},
    {"name":"Người Hành Quyết",    "faction":"Anomalies","description":"Dị Thể mạnh mẽ với khả năng xử tử đặc biệt không thể bị chặn.","color":"#ef4444","tips":"Dùng khả năng khi Survivors đang có nhiều lớp bảo vệ."},
    {"name":"Lãnh Chúa",           "faction":"Anomalies","description":"Chỉ huy Dị Thể. Biết danh sách đồng đội và điều phối tấn công.","color":"#dc2626","tips":"Phân công rõ mục tiêu mỗi đêm để tối ưu hiệu quả tấn công."},
    {"name":"Nhà Vệ Sinh",         "faction":"Anomalies","description":"Xóa di chúc và bằng chứng của nạn nhân sau khi chết.","color":"#b91c1c","tips":"Ưu tiên xóa bằng chứng của Thám Trưởng và Cai Ngục."},
    {"name":"Phát Tín Hiệu Giả",   "faction":"Anomalies","description":"Gửi kết quả điều tra sai lệch cho Thám Trưởng và Thám Tử.","color":"#991b1b","tips":"Tạo bóng nghi lên Survivors đáng tin nhất để gây hỗn loạn."},
    {"name":"Ký Sinh Thần Kinh",   "faction":"Anomalies","description":"Ký sinh vào não nạn nhân và điều khiển hành động của họ từ xa.","color":"#7f1d1d","tips":"Điều khiển Cai Ngục để nhốt đồng đội của Survivors."},
    {"name":"Bóng Tối Kiến Trúc Sư","faction":"Anomalies","description":"Xây dựng bẫy và công trình tấn công để chống Survivors.","color":"#450a0a","tips":"Đặt bẫy ở nơi Survivors thường hoạt động."},
    {"name":"Kẻ Rình Rập Lỗi",    "faction":"Anomalies","description":"Theo dõi mục tiêu qua nhiều đêm rồi tấn công bất ngờ.","color":"#fca5a5","tips":"Kiên nhẫn quan sát trước khi ra tay để chắc chắn không bị chặn."},
    {"name":"Tên Trộm Thì Thầm",   "faction":"Anomalies","description":"Nghe lén thông tin riêng tư và sử dụng chống lại Survivors.","color":"#fecaca","tips":"Tập trung vào kênh liên lạc của Thám Trưởng và Cai Ngục."},
    {"name":"Người Phát Sóng Tĩnh","faction":"Anomalies","description":"Gây nhiễu thông tin liên lạc trong team Survivors.","color":"#fee2e2","tips":"Kích hoạt vào đêm quan trọng khi Survivors chuẩn bị phối hợp."},
    {"name":"Người Cắt Xé",        "faction":"Anomalies","description":"Vô hiệu hóa khả năng đặc biệt của nạn nhân trong một đêm.","color":"#ef4444","tips":"Khóa Giám Hộ Viên trước khi tấn công mục tiêu chính."},
    {"name":"Kẻ Ăn Chân Lý",       "faction":"Anomalies","description":"Cung cấp kết quả điều tra sai cho Thám Trưởng như thể thật.","color":"#dc2626","tips":"Phối hợp với Lãnh Chúa để tối ưu thông tin giả."},
    # Unknown
    {"name":"Sát Nhân Hàng Loạt",  "faction":"Unknown","description":"Chiến thắng một mình. Phải giết đủ người để là người duy nhất còn sống.","color":"#fbbf24","tips":"Giữ bí mật tuyệt đối — dùng cả hai phe để loại lẫn nhau."},
    {"name":"Kẻ Tâm Thần",         "faction":"Unknown","description":"Có mục tiêu ẩn riêng. Hoàn thành mục tiêu để thắng một mình.","color":"#f59e0b","tips":"Đọc kỹ mục tiêu trong DM — mỗi game có thể khác nhau."},
    {"name":"AI Bị Hỏng",          "faction":"Unknown","description":"AI không còn tuân theo lập trình. Mục tiêu bí ẩn thay đổi theo đêm.","color":"#d97706","tips":"Thích nghi nhanh với mục tiêu mới — sự linh hoạt là chìa khóa."},
    {"name":"Đồng Hồ Tận Thế",     "faction":"Unknown","description":"Đếm ngược bí mật. Khi hết giờ, mọi người đều thua — chỉ bạn thắng.","color":"#b45309","tips":"Kéo dài game càng lâu càng tốt — đừng để ai biết vai trò của bạn."},
    {"name":"Người Dệt Giấc Mơ",   "faction":"Unknown","description":"Điều khiển giấc mơ của người khác. Thắng khi gây đủ hỗn loạn.","color":"#92400e","tips":"Tạo ảo giác và mâu thuẫn giữa các thành viên cả hai phe."},
    {"name":"Con Tàu Ma",           "faction":"Unknown","description":"Linh hồn lang thang. Thắng khi khiến cả hai phe nghi ngờ nhau đủ mức.","color":"#78350f","tips":"Rải thông tin mâu thuẫn một cách tinh tế, không quá lộ liễu."},
    {"name":"Con Sâu Lỗi",         "faction":"Unknown","description":"Ký sinh vào game. Thắng khi game bị hủy giữa chừng.","color":"#451a03","tips":"Gây bất ổn từ sớm để khiến người chơi bỏ cuộc."},
    {"name":"Kẻ Dệt Thời Gian",    "faction":"Unknown","description":"Thao túng thứ tự hành động và timeline của đêm.","color":"#fde68a","tips":"Hiểu rõ priority system để khai thác tối đa khả năng."},
    # Event
    {"name":"Người Mù",            "faction":"Event","description":"Vai trò sự kiện. Không thể thấy username người chơi khác — chỉ thấy số.","color":"#a855f7","tips":"Dựa vào giọng nói và hành vi thay vì tên người chơi."},
    {"name":"Người Giải Mật Mã",   "faction":"Event","description":"Giải mã các mật mã xuất hiện trong game để nhận thông tin quan trọng.","color":"#9333ea","tips":"Tốc độ là lợi thế — giải mã nhanh hơn đối thủ."},
    {"name":"Người Kiểm Tra Chuyên Nghiệp","faction":"Event","description":"Vai trò test chuyên nghiệp cho server thử nghiệm tính năng mới.","color":"#7c3aed","tips":"Báo cáo mọi bất thường cho admin ngay lập tức."},
]


# ──────────────────────────────────────────────────────────────────
# ROUTER
# ──────────────────────────────────────────────────────────────────
router = APIRouter()

# ── AUTH ──────────────────────────────────────────────────────────

@router.get("/auth/login")
async def auth_login():
    state = secrets.token_hex(16)
    url = (
        "https://discord.com/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify%20guilds"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/auth/callback")
async def auth_callback(code: str, response: Response):
    async with httpx.AsyncClient() as http:
        tr = await http.post(
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
    redir = RedirectResponse("/dashboard", status_code=302)
    _set_session(redir, uid, access_token, username, avatar)
    return redir


@router.get("/auth/logout")
async def auth_logout():
    redir = RedirectResponse("/dashboard", status_code=302)
    redir.delete_cookie("dash_session")
    return redir


# ── API — CHUNG ────────────────────────────────────────────────────

@router.get("/api/dash/me")
async def api_me(request: Request):
    s = _get_session(request)
    if not s:
        return JSONResponse({"logged_in": False})
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
async def api_guilds(request: Request):
    """Server mà user thuộc về và có config trong bot."""
    s = _require_auth(request)
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {s['access_token']}"},
        )
        user_guilds = resp.json() if resp.status_code == 200 else []

    cfg_col = _col("guild_configs")
    result  = []
    for g in user_guilds:
        gid = g["id"]
        # Kiểm tra guild có config trong bot không
        has_config = False
        if cfg_col:
            has_config = cfg_col.count_documents({"guild_id": gid}, limit=1) > 0
        if not has_config and gid not in _shared.get("guilds", {}):
            continue
        perms = int(g.get("permissions", 0))
        # Chỉ show nếu là owner hoặc có MANAGE_GUILD (0x20)
        is_manager = bool(perms & 0x20) or g.get("owner", False)
        icon = g.get("icon")
        result.append({
            "id":         gid,
            "name":       g["name"],
            "icon":       f"https://cdn.discordapp.com/icons/{gid}/{icon}.png" if icon else None,
            "is_manager": is_manager,
        })
    return JSONResponse(result)


@router.get("/api/dash/guild/{guild_id}/config")
async def api_guild_config(guild_id: str, request: Request):
    _require_auth(request)
    cfg_col = _col("guild_configs")
    if not cfg_col:
        return JSONResponse({})
    doc = cfg_col.find_one({"guild_id": guild_id})
    if doc:
        doc.pop("_id", None)
    return JSONResponse(doc or {})


@router.post("/api/dash/guild/{guild_id}/config")
async def api_update_config(guild_id: str, request: Request):
    s = _require_auth(request)
    data = await request.json()
    # Whitelist field được phép
    _ALLOWED = {
        "max_players", "min_players", "min_players_to_start",
        "countdown_time", "allow_chat", "mute_dead",
        "no_remove_roles", "music", "skip_discussion",
        "day_time", "vote_time", "skip_discussion_delay",
    }
    update = {k: v for k, v in data.items() if k in _ALLOWED}
    cfg_col = _col("guild_configs")
    if cfg_col and update:
        cfg_col.update_one(
            {"guild_id": guild_id},
            {"$set": update},
            upsert=True,
        )
        # Invalidate cache trong app.py
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
    players     = gs.get("players_join_order", [])
    return JSONResponse({
        "status":       status,
        "player_count": len(players),
        "state":        state,
    })


@router.get("/api/dash/changelog")
async def api_changelog(request: Request):
    _require_auth(request)
    cl_col = _col("changelogs")
    if not cl_col:
        return JSONResponse([])
    logs = list(cl_col.find({}, {"_id": 0}).sort("created_at", -1).limit(20))
    return JSONResponse(logs)


@router.post("/api/dash/feedback")
async def api_feedback(request: Request):
    s    = _require_auth(request)
    data = await request.json()
    content = str(data.get("content", "")).strip()[:2000]
    images  = [str(u) for u in data.get("images", [])[:5] if u]
    if not content and not images:
        raise HTTPException(400, "Nội dung trống")
    fb_col = _col("feedbacks")
    if fb_col:
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


# ── API — OWNER ONLY ───────────────────────────────────────────────

@router.get("/api/dash/admin/feedbacks")
async def api_admin_feedbacks(request: Request):
    _require_owner(request)
    fb_col = _col("feedbacks")
    if not fb_col:
        return JSONResponse([])
    docs = list(fb_col.find({}, {"_id": 0}).sort("created_at", -1).limit(100))
    return JSONResponse(docs)


@router.post("/api/dash/admin/feedback/reply")
async def api_reply_feedback(request: Request):
    _require_owner(request)
    data       = await request.json()
    created_at = data.get("created_at", "")
    reply      = str(data.get("reply", "")).strip()[:1000]
    fb_col     = _col("feedbacks")
    if fb_col and created_at:
        fb_col.update_one(
            {"created_at": created_at},
            {"$set": {"reply": reply}},
        )
    return JSONResponse({"ok": True})


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
    if cl_col:
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
    if not ban_col:
        return JSONResponse([])
    docs = list(ban_col.find({}, {"_id": 0}).sort("created_at", -1))
    return JSONResponse(docs)


@router.post("/api/dash/admin/ban")
async def api_ban_player(request: Request):
    _require_owner(request)
    data    = await request.json()
    user_id = str(data.get("user_id", "")).strip()
    reason  = str(data.get("reason",  "Không có lý do")).strip()[:500]
    mode    = data.get("mode", "ban")  # "ban" | "lobby"
    if not user_id:
        raise HTTPException(400, "Thiếu user_id")
    ban_col = _col("bans")
    if ban_col:
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
    if ban_col:
        ban_col.delete_one({"user_id": user_id})
    return JSONResponse({"ok": True})


@router.get("/api/dash/admin/rooms")
async def api_admin_rooms(request: Request):
    """Real-time trạng thái tất cả phòng từ in-memory state."""
    _require_owner(request)
    return JSONResponse(_guild_state_summary())


@router.get("/api/dash/admin/room/{guild_id}")
async def api_admin_room_detail(guild_id: str, request: Request):
    """Chi tiết một phòng — danh sách người chơi, game info."""
    _require_owner(request)
    return JSONResponse(_get_guild_full_status(guild_id))


@router.post("/api/dash/admin/room/{guild_id}/config")
async def api_admin_room_config(guild_id: str, request: Request):
    """Chủ bot có thể sửa bất kỳ guild nào không giới hạn field."""
    _require_owner(request)
    data    = await request.json()
    cfg_col = _col("guild_configs")
    if cfg_col and data:
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


# ── SPA SERVE ─────────────────────────────────────────────────────

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
