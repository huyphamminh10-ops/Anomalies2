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

    if not guilds:
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
# ROLE CATALOG (38 vai trò)
# ──────────────────────────────────────────────────────────────────

_ROLES_CATALOG = [
    # ── Survivors ──────────────────────────────────────────────────
    {
        "name": "Thường Dân", "faction": "Survivors", "color": "#4ade80",
        "description": "Không có kỹ năng đặc biệt. Sống sót đến cuối game là chiến thắng.",
        "tips": "Quan sát hành vi người chơi và bỏ phiếu sáng suốt.",
        "dm_message": "🏘️ **DÂN THƯỜNG**\n\nBạn thuộc phe **Người Sống Sót**.\n\nBạn không có khả năng đặc biệt, nhưng lá phiếu của bạn rất quan trọng.\n\n🎯 Mục tiêu: Giúp thị trấn xác định và loại bỏ tất cả Dị Thể.\n💡 Hãy lắng nghe, quan sát và đưa ra phán đoán chính xác mỗi ngày.",
    },
    {
        "name": "Thám Trưởng", "faction": "Survivors", "color": "#60a5fa",
        "description": "Điều tra một người mỗi đêm để biết họ thuộc phe nào.",
        "tips": "Xác nhận thông tin từ nhiều nguồn trước khi cáo buộc công khai.",
        "dm_message": "👮 **THÁM TRƯỞNG**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Mỗi đêm bạn chọn 1 người để kiểm tra danh tính.\nKết quả cho biết chính xác vai trò của họ.\n\n⚠ Chú ý: Một số Dị Thể có thể dùng khả năng đánh lừa kết quả điều tra.\n💡 Thông tin của bạn rất quý giá — hãy cân nhắc khi nào nên tiết lộ với thị trấn.",
    },
    {
        "name": "Cai Ngục", "faction": "Survivors", "color": "#f59e0b",
        "description": "Giam cầm một người mỗi đêm. Có thể thẩm vấn và xử tử. Có 1 viên đạn để xử tử tù nhân.",
        "tips": "Nhốt người nghi vấn vào những đêm mấu chốt để vô hiệu hóa hành động của họ.",
        "dm_message": "⚖️ **CAI NGỤC**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Mỗi đêm bạn có thể giam 1 người:\n  - Người bị giam không thể dùng kỹ năng và không thể bị giết.\n  - Bạn có thể trò chuyện ẩn danh với tù nhân.\n\n💥 Bạn có 1 viên đạn để xử tử tù nhân.\n⚠️ Nếu xử tử sai người thuộc phe Người Sống Sót, bạn sẽ tự mất khả năng hành động.",
    },
    {
        "name": "Thị Trưởng", "faction": "Survivors", "color": "#a78bfa",
        "description": "Có thể lộ diện để nhận 3 phiếu bầu. Rất mạnh nhưng nguy hiểm khi lộ diện.",
        "tips": "Thời điểm lộ diện quyết định thắng bại — đừng hành động quá sớm.",
        "dm_message": "🏛️ **THỊ TRƯỞNG**\n\nBạn thuộc phe **Người Sống Sót**.\n\n👑 Bạn là thủ lĩnh của thị trấn — phiếu bầu có hệ số x3 khi lộ diện.\n\n🔓 Lộ Diện: Tiết lộ bạn là Thị Trưởng để kích hoạt hiệu ứng phiếu.\n🔫 Bạn có 3 viên đạn để phản công nếu bị Dị Thể tấn công.",
    },
    {
        "name": "Phụ Tá Thị Trưởng", "faction": "Survivors", "color": "#c4b5fd",
        "description": "Hỗ trợ Thị Trưởng và biết danh tính Thị Trưởng ngay từ đầu trận.",
        "tips": "Phối hợp chặt với Thị Trưởng để kiểm soát vote.",
        "dm_message": "🤝 **PHỤ TÁ THỊ TRƯỞNG**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🔎 Bạn biết danh tính Thị Trưởng ngay từ đầu trận.\n💡 Phối hợp cùng Thị Trưởng để lãnh đạo thị trấn hiệu quả.",
    },
    {
        "name": "Thám Tử", "faction": "Survivors", "color": "#38bdf8",
        "description": "Điều tra sâu hơn, nhận thông tin về phe của mục tiêu (Survivor / Anomaly).",
        "tips": "Kết hợp với Thám Trưởng để xác nhận nghi phạm nhanh hơn.",
        "dm_message": "🔎 **THÁM TỬ**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Mỗi đêm bạn chọn 1 người để điều tra.\nKết quả sẽ cho biết người đó thuộc phe nào:\n• 🔴 ĐỎ = Dị Thể\n• 🟢 XANH = Người Sống Sót",
    },
    {
        "name": "Nhà Ngoại Cảm", "faction": "Survivors", "color": "#94a3b8",
        "description": "Giao tiếp với người đã chết để lấy thông tin mỗi đêm qua séance.",
        "tips": "Thông tin từ người chết rất quý — hãy chuyển tải khéo léo mà không lộ vai trò.",
        "dm_message": "🕯️ **NHÀ NGOẠI CẢM**\n\nBạn thuộc phe **Người Sống Sót**.\n\n👻 Vào ban đêm bạn có thể mở séance để trò chuyện với người đã chết.",
    },
    {
        "name": "Điệp Viên", "faction": "Survivors", "color": "#34d399",
        "description": "Theo dõi và tự động nhận thông tin về mục tiêu mà Dị Thể nhắm vào mỗi đêm.",
        "tips": "Theo dõi những người im lặng nhưng có vẻ tự tin bất thường.",
        "dm_message": "👁️ **ĐIỆP VIÊN**\n\nBạn thuộc phe **Người Sống Sót**.\n\n📡 Mỗi đêm bạn tự động nhận thông tin về mục tiêu mà Dị Thể nhắm vào.",
    },
    {
        "name": "Kẻ Trừng Phạt", "faction": "Survivors", "color": "#fb923c",
        "description": "Có 3 viên đạn để bắn tỉa. Bắn ban ngày bị lộ diện, bắn ban đêm ẩn danh.",
        "tips": "Chỉ hành động khi chắc chắn — sai lầm có thể gây hại cho phe bạn.",
        "dm_message": "🔫 **KẺ TRỪNG PHẠT**\n\nBạn thuộc phe **Người Sống Sót**.\n\n💥 Bạn có 3 viên đạn để trừng phạt kẻ tình nghi bất cứ lúc nào.\n☀️ Bắn ban ngày → lộ diện. 🌙 Bắn ban đêm → ẩn danh.",
    },
    {
        "name": "Thợ Đặt Bẫy", "faction": "Survivors", "color": "#84cc16",
        "description": "Đặt bẫy ở nhà — kẻ tấn công có thể bị lộ danh tính, bị giết, hoặc bị Stun.",
        "tips": "Đặt bẫy gần người quan trọng (Thám Trưởng, Cai Ngục) để bảo vệ.",
        "dm_message": "🪤 **THỢ ĐẶT BẪY**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🏠 Nhà bạn có bẫy — kích hoạt một lần khi bị tấn công.\n\nKết quả (25% mỗi loại):\n👁️ Lộ danh tính | 💀 Tiêu diệt | 💥 Phản đòn | 😵 Stun",
    },
    {
        "name": "Kiến Trúc Sư", "faction": "Survivors", "color": "#06b6d4",
        "description": "Gia cố nhà ở, bảo vệ Người Sống Sót khỏi bị giết trong đêm. Có 2 lượt.",
        "tips": "Ưu tiên bảo vệ các vai trò điều tra và kiểm soát.",
        "dm_message": "🏗️ **KIẾN TRÚC SƯ**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Bạn có thể gia cố nhà ở, bảo vệ Người Sống Sót khỏi bị giết trong đêm.\nBạn có **2 lượt** dùng trong suốt cả trận.",
    },
    {
        "name": "Nhà Lưu Trữ", "faction": "Survivors", "color": "#8b5cf6",
        "description": "Mỗi đêm đọc di chúc bí mật của người đã chết để thu thập thông tin.",
        "tips": "Ghi chép kỹ lưỡng để cung cấp bằng chứng vào ban ngày.",
        "dm_message": "📚 **NHÀ LƯU TRỮ**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Mỗi đêm bạn chọn 1 người đã chết để đọc di chúc bí mật của họ.",
    },
    {
        "name": "Kẻ Báo Oán", "faction": "Survivors", "color": "#ec4899",
        "description": "Hồi sinh một người đã chết một lần duy nhất. Cực kỳ hiếm và mạnh.",
        "tips": "Hồi sinh Thám Trưởng hoặc Cai Ngục ở giai đoạn cuối để lật ngược thế cờ.",
        "dm_message": "⚡ **KẺ BÁO OÁN**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🔄 Một lần duy nhất trong cả game, bạn có thể hồi sinh 1 Survivor đã chết.",
    },
    {
        "name": "Người Giám Sát", "faction": "Survivors", "color": "#f97316",
        "description": "Kiểm soát camera an ninh, mỗi đêm ghi lại 3 người đang hoạt động. Có 3 lượt.",
        "tips": "Ưu tiên bảo vệ các vai trò quan trọng như Thám Trưởng hoặc Cai Ngục.",
        "dm_message": "📷 **NGƯỜI GIÁM SÁT**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Bạn kiểm soát camera an ninh — mỗi đêm ghi lại tối đa 3 người đang hoạt động.\nBạn có **3 lượt** sử dụng.",
    },
    {
        "name": "Người Tiên Tri", "faction": "Survivors", "color": "#6366f1",
        "description": "Sở hữu 3 kỹ năng: Tiên Đoán, Kiểm Tra Ba người, và Bảo Hộ Linh Hồn.",
        "tips": "Chú ý ai nói quá nhiều hoặc quá ít so với bình thường.",
        "dm_message": "🔮 **NGƯỜI TIÊN TRI**\n\nBạn thuộc phe **Người Sống Sót**.\n\nBạn sở hữu 3 kỹ năng siêu nhiên:\n🔮 **Tiên Đoán** | 👁️ **Kiểm Tra Ba** | 🛡️ **Bảo Hộ Linh Hồn**",
    },
    {
        "name": "Kẻ Ngủ Mê", "faction": "Survivors", "color": "#64748b",
        "description": "Không thể tham gia chat Thị Trấn nhưng nhận báo cáo chi tiết mỗi sáng về những gì xảy ra đêm qua.",
        "tips": "Giữ bình thản — thông tin đến khi bạn ít ngờ tới nhất.",
        "dm_message": "😴 **KẺ NGỦ MÊ**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🚫 Bạn không thể thấy và không thể tham gia chat Thị Trấn.\n🌙 Mỗi sáng bạn nhận báo cáo chi tiết những gì đã xảy ra đêm qua.",
    },
    {
        "name": "Nhà Dược Học Điên", "faction": "Survivors", "color": "#ef4444",
        "description": "Có 4 loại thuốc đặc biệt: Hồi Phục Nhanh, Ngừng Tim, Phát Sáng, và Trường Sinh/Virus.",
        "tips": "Rủi ro cao, phần thưởng cao — chỉ dùng khi thực sự cần thiết.",
        "dm_message": "🧪 **NHÀ DƯỢC HỌC ĐIÊN**\n\nBạn thuộc phe **Người Sống Sót**.\n\nBạn có 4 loại thuốc:\n💊 Hồi Phục Nhanh ×2 | 💀 Ngừng Tim ×1 | ✨ Phát Sáng ×1 | ⚗️ Trường Sinh/Virus ×1",
    },
    {
        "name": "Kẻ Báo Thù", "faction": "Survivors", "color": "#dc2626",
        "description": "Sau khi chết, kéo kẻ thù xuống cùng. Bị trục xuất giết Mayor, bị Dị Thể giết sẽ tiêu diệt Lãnh Chúa.",
        "tips": "Hãy để lại di chúc rõ ràng để đồng đội biết ai đã giết bạn.",
        "dm_message": "⚔️ **KẺ BÁO THÙ**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🔥 Nếu bị giết, bạn sẽ kéo kẻ thù xuống cùng mình.",
    },
    # ── Anomalies ──────────────────────────────────────────────────
    {
        "name": "Dị Thể", "faction": "Anomalies", "color": "#f87171",
        "description": "Chiến binh cốt lõi của phe Dị Thể. Mỗi đêm phe bỏ phiếu chọn 1 người để tiêu diệt.",
        "tips": "Ưu tiên tiêu diệt Thám Trưởng, Cai Ngục và Thám Tử trước tiên.",
        "dm_message": "🔴 **DỊ THỂ**\n\nBạn thuộc phe **Dị Thể**.\n\n📋 Mỗi đêm phe bạn cùng bỏ phiếu chọn 1 người để tiêu diệt.\n👁️ Bạn biết danh tính toàn bộ đồng đội Dị Thể.",
    },
    {
        "name": "Dị Thể Hành Quyết", "faction": "Anomalies", "color": "#ef4444",
        "description": "Hành quyết xuyên qua mọi lớp bảo vệ. Người bảo vệ mục tiêu cũng bị phản thương. Có 2 lượt.",
        "tips": "Dùng khả năng khi Survivors đang có nhiều lớp bảo vệ.",
        "dm_message": "⚔️ **DỊ THỂ HÀNH QUYẾT**\n\nBạn thuộc phe **Dị Thể**.\n\n🌙 Bạn có thể hành quyết xuyên qua mọi lớp bảo vệ.\nBạn có **2 lượt**.",
    },
    {
        "name": "Lãnh Chúa", "faction": "Anomalies", "color": "#dc2626",
        "description": "Chỉ huy Dị Thể. Quyết định mục tiêu tấn công của cả phe mỗi đêm và biết danh sách đồng đội.",
        "tips": "Phân công rõ mục tiêu mỗi đêm để tối ưu hiệu quả tấn công.",
        "dm_message": "👑 **LÃNH CHÚA**\n\nBạn thuộc phe **Dị Thể**.\n\nBạn là chỉ huy — quyết định mục tiêu tấn công của cả phe mỗi đêm.",
    },
    {
        "name": "Lao Công", "faction": "Anomalies", "color": "#b91c1c",
        "description": "Xóa vai trò của nạn nhân khỏi thông báo nếu họ chết trong đêm được chọn.",
        "tips": "Ưu tiên xóa bằng chứng của Thám Trưởng và Cai Ngục.",
        "dm_message": "🧹 **LAO CÔNG**\n\nBạn thuộc phe **Dị Thể**.\n\nBạn có thể xóa vai trò nạn nhân khỏi thông báo khi họ chết.",
    },
    {
        "name": "Tín Hiệu Giả", "faction": "Anomalies", "color": "#991b1b",
        "description": "Gửi kết quả điều tra sai lệch cho Thám Trưởng và Thám Tử. Có 3 lượt.",
        "tips": "Tạo bóng nghi lên Survivors đáng tin nhất để gây hỗn loạn.",
        "dm_message": "📡 **TÍN HIỆU GIẢ**\n\nBạn thuộc phe **Dị Thể**.\n\nBạn có thể gửi kết quả điều tra sai lệch cho Thám Trưởng và Thám Tử. Có **3 lượt**.",
    },
    {
        "name": "Ký Sinh Thần Kinh", "faction": "Anomalies", "color": "#7f1d1d",
        "description": "Ký sinh vào não nạn nhân. Cần 3 ngày để tha hóa hoàn toàn và biến vật chủ thành Anomaly.",
        "tips": "Điều khiển Cai Ngục để nhốt đồng đội của Survivors.",
        "dm_message": "🧠 **KÝ SINH THẦN KINH**\n\nBạn thuộc phe **Dị Thể**.\n\nBạn có thể ký sinh vào não nạn nhân. Sau 3 ngày, vật chủ trở thành Anomaly.",
    },
    {
        "name": "Kiến Trúc Sư Bóng Tối", "faction": "Anomalies", "color": "#450a0a",
        "description": "Phong tỏa 3 ngôi nhà mỗi đêm trong bóng tối — những người bị chọn không thể dùng kỹ năng.",
        "tips": "Đặt bẫy ở nơi Survivors thường hoạt động.",
        "dm_message": "🌑 **KIẾN TRÚC SƯ BÓNG TỐI**\n\nBạn thuộc phe **Dị Thể**.\n\nMỗi đêm phong tỏa 3 ngôi nhà — những người bị chọn không thể dùng kỹ năng.",
    },
    {
        "name": "Kẻ Rình Rập", "faction": "Anomalies", "color": "#fca5a5",
        "description": "Theo dõi Survivor mỗi đêm để phát hiện vai trò thực của họ. Không rình 2 đêm liên tiếp.",
        "tips": "Kiên nhẫn quan sát trước khi ra tay để chắc chắn không bị chặn.",
        "dm_message": "👀 **KẺ RÌNH RẬP**\n\nBạn thuộc phe **Dị Thể**.\n\nTheo dõi Survivor mỗi đêm để phát hiện vai trò của họ. Không rình 2 đêm liên tiếp.",
    },
    {
        "name": "Kẻ Đánh Cắp Lời Thì Thầm", "faction": "Anomalies", "color": "#fecaca",
        "description": "Nghe lén 2 người mỗi đêm và đọc được di chúc của cả hai nếu họ có tương tác bí mật.",
        "tips": "Tập trung vào kênh liên lạc của Thám Trưởng và Cai Ngục.",
        "dm_message": "🎧 **KẺ ĐÁNH CẮP LỜI THÌ THẦM**\n\nBạn thuộc phe **Dị Thể**.\n\nMỗi đêm nghe lén 2 người và đọc di chúc của họ.",
    },
    {
        "name": "Nguồn Tĩnh Điện", "faction": "Anomalies", "color": "#fee2e2",
        "description": "Phát nhiễu tin nhắn hệ thống của 1 người mỗi đêm — các nguyên âm bị biến dạng bằng ký hiệu.",
        "tips": "Kích hoạt vào đêm quan trọng khi Survivors chuẩn bị phối hợp.",
        "dm_message": "⚡ **NGUỒN TĨNH ĐIỆN**\n\nBạn thuộc phe **Dị Thể**.\n\nMỗi đêm phát nhiễu tin nhắn hệ thống của 1 người.",
    },
    {
        "name": "Máy Hủy Tài Liệu", "faction": "Anomalies", "color": "#ef4444",
        "description": "Đánh dấu 1 người mỗi đêm — nếu họ bị giết, di chúc bị xóa hoàn toàn.",
        "tips": "Khóa Giám Hộ Viên trước khi tấn công mục tiêu chính.",
        "dm_message": "🗑️ **MÁY HỦY TÀI LIỆU**\n\nBạn thuộc phe **Dị Thể**.\n\nĐánh dấu 1 người mỗi đêm — nếu họ bị giết, di chúc bị xóa.",
    },
    {
        "name": "Kẻ Mô Phỏng Sinh Học", "faction": "Anomalies", "color": "#dc2626",
        "description": "Liên kết cộng sinh với 1 Survivor. Nếu người cộng sinh chết trước, nhận 1 lần miễn nhiễm sát thương.",
        "tips": "Phối hợp với Lãnh Chúa để tối ưu thông tin giả.",
        "dm_message": "🧬 **KẺ MÔ PHỎNG SINH HỌC**\n\nBạn thuộc phe **Dị Thể**.\n\nLiên kết cộng sinh với 1 Survivor để nhận khả năng miễn nhiễm.",
    },
    # ── Unknown ────────────────────────────────────────────────────
    {
        "name": "Sát Nhân Hàng Loạt", "faction": "Unknown", "color": "#fbbf24",
        "description": "Chiến thắng một mình. Giết 1 người mỗi đêm. Điều kiện thắng: chỉ còn mình sống sót.",
        "tips": "Giữ bí mật tuyệt đối — dùng cả hai phe để loại lẫn nhau.",
        "dm_message": "🔪 **SÁT NHÂN HÀNG LOẠT**\n\nBạn chiến thắng **một mình**.\n\nGiết 1 người mỗi đêm. Điều kiện thắng: chỉ còn mình bạn sống sót.",
    },
    {
        "name": "Kẻ Tâm Thần", "faction": "Unknown", "color": "#f59e0b",
        "description": "Mục tiêu bí ẩn: bị Cách Ly bằng bỏ phiếu mà không có phiếu nào từ phe Dị Thể.",
        "tips": "Đọc kỹ mục tiêu trong DM — mỗi game có thể khác nhau.",
        "dm_message": "🎭 **KẺ TÂM THẦN**\n\nMục tiêu bí ẩn: bị Cách Ly bằng bỏ phiếu mà không có phiếu nào từ Dị Thể.",
    },
    {
        "name": "A.I Tha Hóa", "faction": "Unknown", "color": "#d97706",
        "description": "Mỗi đêm thực hiện 2 hành động: QUÉT (thu tài nguyên) và GIẾT. Quét Anomaly → Điểm Khiên, Quét Survivor → Điểm Giết.",
        "tips": "Thích nghi nhanh với mục tiêu mới — sự linh hoạt là chìa khóa.",
        "dm_message": "🤖 **A.I THA HÓA**\n\nMỗi đêm thực hiện 2 hành động: QUÉT và GIẾT.\nQuét Anomaly → Điểm Khiên | Quét Survivor → Điểm Giết.",
    },
    {
        "name": "Đồng Hồ Tận Thế", "faction": "Unknown", "color": "#b45309",
        "description": "Thực thể bí ẩn đếm ngược đến thảm họa. Mục tiêu và cơ chế chiến thắng được tiết lộ dần.",
        "tips": "Không ai biết bạn tồn tại cho đến khi quá muộn.",
        "dm_message": "⏰ **ĐỒNG HỒ TẬN THẾ**\n\nThực thể bí ẩn đếm ngược đến thảm họa. Mục tiêu được tiết lộ dần.",
    },
    {
        "name": "Kẻ Dệt Mộng", "faction": "Unknown", "color": "#7c3aed",
        "description": "Điều khiển giấc mơ của người chơi và thao túng thực tại của trò chơi.",
        "tips": "Ảo giác là vũ khí mạnh nhất của bạn.",
        "dm_message": "🌙 **KẺ DỆT MỘNG**\n\nBạn điều khiển giấc mơ của người chơi và thao túng thực tại.",
    },
    {
        "name": "Con Tàu Ma", "faction": "Unknown", "color": "#475569",
        "description": "Thực thể vô hình lang thang trong trận đấu với khả năng bí ẩn.",
        "tips": "Di chuyển trong bóng tối và không để lại dấu vết.",
        "dm_message": "👻 **CON TÀU MA**\n\nThực thể vô hình lang thang trong trận đấu với khả năng bí ẩn.",
    },
    {
        "name": "Sâu Lỗi", "faction": "Unknown", "color": "#ef4444",
        "description": "Xâm nhập hệ thống và phá hủy di chúc, ghi chép của người chơi khác.",
        "tips": "Nhắm vào Nhà Lưu Trữ và Kẻ Ngủ Mê để xóa thông tin quan trọng.",
        "dm_message": "🐛 **SÂU LỖI**\n\nXâm nhập hệ thống và phá hủy di chúc, ghi chép của người chơi khác.",
    },
    {
        "name": "Kẻ Tâm Thần Bạo Lực", "faction": "Unknown", "color": "#dc2626",
        "description": "Thực thể không ổn định với mục tiêu thay đổi theo từng giai đoạn của trận đấu.",
        "tips": "Đọc kỹ mục tiêu sau mỗi pha thay đổi.",
        "dm_message": "😈 **KẺ TÂM THẦN BẠO LỰC**\n\nMục tiêu thay đổi theo từng giai đoạn của trận đấu.",
    },
    {
        "name": "Kẻ Dệt Thời Gian", "faction": "Unknown", "color": "#8b5cf6",
        "description": "Thao túng dòng thời gian và có thể đảo ngược một số sự kiện trong trận đấu.",
        "tips": "Dùng khả năng vào thời điểm then chốt để lật ngược tình thế.",
        "dm_message": "⌛ **KẺ DỆT THỜI GIAN**\n\nThao túng dòng thời gian và có thể đảo ngược một số sự kiện.",
    },
]


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
        "countdown_time": gs.get("countdown_seconds", gs.get("countdown_time", 200)),
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
                    return (0, 0)
                return (
                    db["guild_configs"].count_documents({}),
                    db["bans"].count_documents({}),
                )

            loop = asyncio.get_event_loop()
            total_guilds, total_bans = await loop.run_in_executor(None, _mongo_counts)
        except Exception as e:
            print(f"[api_stats] Lỗi MongoDB count: {e}")
            mongo_ok = False

    tidb_ok = False
    total_feedbacks = 0
    total_changelogs = 0
    try:
        loop = asyncio.get_event_loop()

        def _tidb_counts():
            # Wrap each count individually so one table failure does not crash the other
            try:
                fb = database_tidb.count_feedbacks()
            except Exception as e_fb:
                print(f"[api_stats] TiDB count_feedbacks lỗi: {e_fb}")
                fb = 0
            try:
                cl = database_tidb.count_update_logs()
            except Exception as e_cl:
                print(f"[api_stats] TiDB count_update_logs lỗi: {e_cl}")
                cl = 0
            return (fb, cl)

        total_feedbacks, total_changelogs = await loop.run_in_executor(None, _tidb_counts)
        tidb_ok = True
    except Exception as e:
        print(f"[api_stats] Lỗi TiDB count: {e}")

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
    """Tra cứu thông tin người chơi theo Discord user_id."""
    _require_auth(request)
    players_col = _col("players")
    if players_col is None:
        raise HTTPException(404, "404 ×[")
    doc = players_col.find_one({"user_id": user_id})
    if not doc:
        raise HTTPException(404, "404 ×[")
    doc.pop("_id", None)
    return JSONResponse(doc)


# ── API — OWNER ONLY ───────────────────────────────────────────────

@router.get("/api/dash/admin/feedbacks")
async def api_admin_feedbacks(request: Request):
    _require_owner(request)
    fb_col = _col("feedbacks")
    if fb_col is None:
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
    if fb_col is not None and created_at:
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


# ── GAMEPLAY GUIDES ────────────────────────────────────────────────

# Dữ liệu hướng dẫn chơi — lấy cảm hứng từ cogs/help.py
_COMMANDS_DATA = [
    {
        "emoji": "⚙️",
        "name": "/setup",
        "desc": (
            "Cài đặt bot lần đầu cho server — chọn kênh chat chữ, kênh thoại "
            "và danh mục (Category) thông qua menu tương tác. Bot sẽ tự tạo kênh "
            "nếu bạn chọn *Tạo cho tôi*."
        ),
        "perm": "Chủ server / Admin",
        "image_url": "",
    },
    {
        "emoji": "🔧",
        "name": "/setting",
        "desc": (
            "Điều chỉnh các thông số trận đấu: số người, thời gian thảo luận, "
            "thời gian bỏ phiếu, đếm ngược, bật/tắt mute, phân quyền lệnh..."
        ),
        "perm": "Theo cấu hình /setting → Quyền sử dụng lệnh",
        "image_url": "",
    },
    {
        "emoji": "🗑️",
        "name": "/clear",
        "desc": (
            "Xóa toàn bộ tin nhắn trong kênh game (dọn sạch sau trận). "
            "Thường dùng sau khi trận kết thúc để chuẩn bị cho trận tiếp theo."
        ),
        "perm": "Theo cấu hình /setting → Quyền sử dụng lệnh",
        "image_url": "",
    },
    {
        "emoji": "👁️",
        "name": "/role",
        "desc": (
            "Xem danh sách tất cả các vai trò trong game, đọc mô tả chi tiết, "
            "mẹo chơi, và chỉnh sửa tỉ lệ xuất hiện của từng role trong trận tiếp theo."
        ),
        "perm": "Tất cả mọi người",
        "image_url": "",
    },
    {
        "emoji": "❓",
        "name": "/help",
        "desc": "Hiển thị trang trợ giúp này.",
        "perm": "Tất cả mọi người",
        "image_url": "",
    },
]

_FAQ_DATA = [
    {
        "emoji": "🎮",
        "title": "Cách tham gia & bắt đầu trận",
        "content": (
            "1. Vào kênh thoại của bot (kênh được chọn lúc /setup).\n"
            "2. Bot sẽ nhận diện bạn và thêm vào phòng chờ.\n"
            "3. Khi đủ số người tối thiểu, bot bắt đầu đếm ngược rồi tự động khởi động trận.\n"
            "4. Vai trò sẽ được gửi qua DM — hãy đảm bảo bật nhận tin nhắn từ server."
        ),
        "image_url": "",
    },
    {
        "emoji": "🌙",
        "title": "Cách thực hiện hành động ban đêm",
        "content": (
            "Khi màn đêm bắt đầu, bot gửi DM cho bạn kèm giao diện nút bấm hoặc menu chọn.\n\n"
            "• Chọn mục tiêu → bấm nút hoặc chọn từ menu Select.\n"
            "• Xác nhận → bấm nút xác nhận (nếu có).\n"
            "• Hành động sẽ được thực thi vào cuối đêm (trừ một số role đặc biệt).\n"
            "• Nếu không thực hiện gì, lượt đó coi như bỏ qua.\n\n"
            "Một số role có thể bị chặn hành động (bởi Kiến Trúc Sư Bóng Tối, Cai Ngục...) "
            "— bạn sẽ nhận thông báo trong DM."
        ),
        "image_url": "",
    },
    {
        "emoji": "☀️",
        "title": "Cách thảo luận & bỏ phiếu ban ngày",
        "content": (
            "Ban ngày, tất cả người sống được unmute và nói chuyện tự do.\n\n"
            "• Thảo luận trong kênh chat chữ và kênh thoại.\n"
            "• Khi hết giờ thảo luận, giai đoạn bỏ phiếu bắt đầu — bot gửi giao diện bỏ phiếu.\n"
            "• Mỗi người chỉ được 1 phiếu — bỏ phiếu cho người bạn nghi ngờ là Dị Thể.\n"
            "• Người nhận nhiều phiếu nhất sẽ bị trục xuất khỏi thị trấn.\n"
            "• Nếu hòa phiếu → không ai bị trục xuất trong ngày đó.\n\n"
            "Skip thảo luận: Nếu được bật, người chơi có thể vote rút ngắn thời gian thảo luận."
        ),
        "image_url": "",
    },
    {
        "emoji": "📜",
        "title": "Cách nhập & xem di chúc",
        "content": (
            "Ghi di chúc — hoàn toàn qua DM của bot:\n"
            "Nhắn tin trực tiếp cho bot (DM): 'Nhập di chúc'\n"
            "Bot sẽ phản hồi hướng dẫn — sau đó mỗi tin nhắn bạn gửi trong DM = 1 dòng di chúc.\n\n"
            "• Tối đa 45 dòng, mỗi dòng tối đa 60 ký tự (không tính dấu cách).\n"
            "• Di chúc lưu tự động sau mỗi dòng — không cần lệnh kết thúc.\n"
            "• Khi bạn chết, di chúc tự động khóa.\n\n"
            "Xem di chúc: Mỗi sáng, bot gửi bảng LÁ THƯ NGƯỜI CHẾT kèm menu chọn tại kênh game."
        ),
        "image_url": "",
    },
    {
        "emoji": "💬",
        "title": "Các kênh chat riêng tư có gì?",
        "content": (
            "Kênh Dị Thể (Anomaly Chat):\n"
            "Kênh riêng tư chỉ dành cho phe Dị Thể. Các thành viên Dị Thể có thể "
            "thảo luận chiến thuật mà không bị phe Survivor biết.\n\n"
            "Kênh Người Chết (Dead Chat):\n"
            "Kênh dành riêng cho người đã chết. Người chết có thể nói chuyện với nhau "
            "nhưng không thể can thiệp vào trận đấu.\n\n"
            "DM (Tin nhắn riêng):\n"
            "Bot gửi DM khi: nhận vai trò, thực hiện hành động đêm, nhận kết quả điều tra, "
            "nhận thông báo bị tấn công, và xem di chúc."
        ),
        "image_url": "",
    },
    {
        "emoji": "🏆",
        "title": "Điều kiện thắng của mỗi phe",
        "content": (
            "Survivors (Người Sống Sót):\n"
            "Loại bỏ tất cả Dị Thể và các thực thể đe dọa còn lại.\n\n"
            "Anomalies (Dị Thể):\n"
            "Chiếm đa số — số Dị Thể sống bằng hoặc hơn số Survivor còn lại.\n\n"
            "Unknown Entities (Thực Thể Ẩn):\n"
            "Mỗi role có điều kiện riêng — đọc mô tả vai trò trong DM để biết chi tiết."
        ),
        "image_url": "",
    },
    {
        "emoji": "🔍",
        "title": "Vai trò điều tra hoạt động thế nào?",
        "content": (
            "Thám Tử: Điều tra 1 người/đêm — nhận kết quả là danh sách vai trò gợi ý.\n\n"
            "Thám Trưởng: Điều tra 1 người/đêm — biết chính xác vai trò của họ.\n\n"
            "Điệp Viên: Mỗi đêm nhận thông tin Dị Thể nhắm vào ai.\n\n"
            "Người Tiên Tri: Cảm nhận linh hồn 1 người — biết họ thuộc phe thiện hay ác.\n\n"
            "Tín Hiệu Giả (Dị Thể): Giả mạo kết quả điều tra gửi cho Thám Tử/Thám Trưởng."
        ),
        "image_url": "",
    },
    {
        "emoji": "⚰️",
        "title": "Điều gì xảy ra khi bạn chết?",
        "content": (
            "• Bạn nhận role Dead và bị mute trong kênh thoại.\n"
            "• Bạn được thêm vào Dead Chat — có thể nói chuyện với người chết khác.\n"
            "• Di chúc của bạn (nếu có) tự động khóa lại.\n"
            "• Bạn vẫn có thể theo dõi diễn biến qua kênh chat chính (chỉ xem).\n"
            "• Kẻ Báo Oán có thể hồi sinh bạn — bạn sẽ nhận DM thông báo.\n\n"
            "Người chết không được tiết lộ thông tin cho người sống qua kênh công khai."
        ),
        "image_url": "",
    },
    {
        "emoji": "🎭",
        "title": "Spectator — theo dõi trận không tham gia",
        "content": (
            "Nếu bạn vào kênh thoại sau khi trận đã bắt đầu, "
            "bot sẽ tự động cho bạn vào chế độ Spectator (khán giả).\n\n"
            "• Nickname được đổi thành 'Spectator' trong trận.\n"
            "• Có thể xem kênh chat nhưng không thể gửi tin nhắn vào chat game.\n"
            "• Không thể tham gia bỏ phiếu hay thực hiện hành động.\n"
            "• Sau khi trận kết thúc, nickname được tự động trả lại tên gốc."
        ),
        "image_url": "",
    },
    {
        "emoji": "🌀",
        "title": "Unknown Entities — các thực thể bí ẩn là gì?",
        "content": (
            "Các Unknown Entities không thuộc phe Survivors hay Anomalies — "
            "họ có mục tiêu và điều kiện thắng riêng.\n\n"
            "Kẻ Giết Người Hàng Loạt — tấn công mỗi đêm, muốn là người sống duy nhất.\n"
            "A.I Tha Hóa — thu thập dữ liệu từ cả hai phe.\n"
            "Đồng Hồ Tận Thế — kéo dài trận đủ số ngày.\n"
            "Kẻ Dệt Mộng — liên kết 2 người, họ biết vai trò của nhau.\n"
            "Con Tàu Ma — bắt cóc người chơi đưa vào vùng trung gian.\n"
            "Kẻ Dệt Thời Gian — quan sát và thao túng dòng thời gian."
        ),
        "image_url": "",
    },
]


@router.get("/api/dash/gameplay-guides")
async def api_gameplay_guides(request: Request):
    """
    Trả về dữ liệu Hướng dẫn chơi cho Dashboard:
      - commands: danh sách lệnh slash (từ COMMANDS_DATA của help.py)
      - faq: câu hỏi thường gặp về gameplay (từ GAMEPLAY_FAQ của help.py)
    Trường image_url để trống — thêm URL ảnh sau này khi cần.
    """
    _require_auth(request)
    return JSONResponse({
        "commands": _COMMANDS_DATA,
        "faq":      _FAQ_DATA,
    })


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
