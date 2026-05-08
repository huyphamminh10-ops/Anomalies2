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
# Ưu tiên env var; fallback tự động detect từ request nếu không có
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
    """Lấy trạng thái tất cả guild từ in-memory state (real-time), fallback về DB."""
    bot         = _shared.get("bot")
    guilds      = _shared.get("guilds", {})
    active_games= _shared.get("active_games", {})

    # Fallback: nếu bot chưa chạy, lấy từ DB
    if not guilds:
        cfg_col = _col("guild_configs")
        if cfg_col:
            docs = list(cfg_col.find({}, {"_id": 0, "guild_id": 1, "guild_name": 1, "status": 1, "max_players": 1}))
            return [{
                "guild_id": d.get("guild_id", ""),
                "guild_name": d.get("guild_name") or d.get("guild_id", ""),
                "icon": None,
                "status": d.get("status", "waiting"),
                "player_count": 0,
                "max_players": d.get("max_players", 200),
            } for d in docs]
        return []
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
    {"name":"Thường Dân",          "faction":"Survivors","description":"Không có kỹ năng đặc biệt. Sống sót đến cuối game là chiến thắng.","color":"#4ade80","tips":"Quan sát hành vi người chơi và bỏ phiếu sáng suốt.","dm_message":"🏘️ **DÂN THƯỜNG**\n\nBạn thuộc phe **Người Sống Sót**.\n\nBạn không có khả năng đặc biệt, nhưng lá phiếu của bạn rất quan trọng.\n\n🎯 Mục tiêu: Giúp thị trấn xác định và loại bỏ tất cả Dị Thể.\n💡 Hãy lắng nghe, quan sát và đưa ra phán đoán chính xác mỗi ngày."},
    {"name":"Thám Trưởng",         "faction":"Survivors","description":"Điều tra một người mỗi đêm để biết họ thuộc phe nào.","color":"#60a5fa","tips":"Xác nhận thông tin từ nhiều nguồn trước khi cáo buộc công khai.","dm_message":"👮 **THÁM TRƯỞNG**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Mỗi đêm bạn chọn 1 người để kiểm tra danh tính.\nKết quả cho biết chính xác vai trò của họ.\n\n⚠ Chú ý: Một số Dị Thể có thể dùng khả năng đánh lừa kết quả điều tra.\n💡 Thông tin của bạn rất quý giá — hãy cân nhắc khi nào nên tiết lộ với thị trấn."},
    {"name":"Cai Ngục",            "faction":"Survivors","description":"Giam cầm một người mỗi đêm. Có thể thẩm vấn và xử tử.","color":"#f59e0b","tips":"Nhốt người nghi vấn vào những đêm mấu chốt để vô hiệu hóa hành động của họ.","dm_message":"⚖️ **CAI NGỤC**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Mỗi đêm bạn có thể giam 1 người:\n  - Người bị giam không thể dùng kỹ năng và không thể bị giết.\n  - Bạn có thể trò chuyện ẩn danh với tù nhân.\n\n💥 Bạn có 1 viên đạn để xử tử tù nhân.\n⚠️ Nếu xử tử sai người thuộc phe Người Sống Sót, bạn sẽ tự mất khả năng hành động.\n🎯 Mục tiêu: Bảo vệ thị trấn bằng cách vô hiệu hóa kẻ thù đúng lúc."},
    {"name":"Thị Trưởng",          "faction":"Survivors","description":"Có thể lộ diện để nhận 3 phiếu bầu. Rất mạnh nhưng nguy hiểm.","color":"#a78bfa","tips":"Thời điểm lộ diện quyết định thắng bại — đừng hành động quá sớm.","dm_message":"🏛️ **THỊ TRƯỞNG**\n\nBạn thuộc phe **Người Sống Sót**.\n\n👑 Bạn là thủ lĩnh của thị trấn — phiếu bầu có hệ số x3 khi lộ diện.\n\n🔓 Lộ Diện: Tiết lộ bạn là Thị Trưởng để kích hoạt hiệu ứng phiếu.\n🔫 Bạn có 3 viên đạn để phản công nếu bị Dị Thể tấn công.\n⚠️ Một khi lộ diện, bạn trở thành mục tiêu ưu tiên của kẻ thù!\n🎯 Mục tiêu: Dẫn dắt thị trấn đến chiến thắng."},
    {"name":"Trợ Lý Thị Trưởng",  "faction":"Survivors","description":"Hỗ trợ Thị Trưởng và nhận quyền bầu cử đặc biệt khi cần.","color":"#c4b5fd","tips":"Phối hợp chặt với Thị Trưởng để kiểm soát vote.","dm_message":"🤝 **PHỤ TÁ THỊ TRƯỞNG**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🔎 Bạn biết danh tính Thị Trưởng ngay từ đầu trận.\n📊 Hãy theo dõi trạng thái sống/chết của Thị Trưởng mỗi đêm.\n\n💡 Phối hợp cùng Thị Trưởng để lãnh đạo thị trấn hiệu quả.\n⚠️ Nếu lộ diện quá sớm, bạn có thể bị kẻ thù nhắm tới.\n🎯 Mục tiêu: Hỗ trợ và bảo vệ Thị Trưởng đến cuối game."},
    {"name":"Thám Tử",             "faction":"Survivors","description":"Điều tra sâu hơn, nhận thêm thông tin cụ thể về vai trò mục tiêu.","color":"#38bdf8","tips":"Kết hợp với Thám Trưởng để xác nhận nghi phạm nhanh hơn.","dm_message":"🔎 **THÁM TỬ**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Mỗi đêm bạn chọn 1 người để điều tra.\nKết quả sẽ cho biết người đó thuộc phe nào:\n• 🔴 ĐỎ = Dị Thể (Dị Thể)\n• 🟢 XANH = Người Sống Sót (Người Sống Sót)\n\n⚠ Hãy chia sẻ thông tin khéo léo — tiết lộ thân phận quá sớm có thể nguy hiểm."},
    {"name":"Pháp Quan",           "faction":"Survivors","description":"Giao tiếp với người đã chết để lấy thông tin mỗi đêm.","color":"#94a3b8","tips":"Thông tin từ người chết rất quý — hãy chuyển tải khéo léo mà không lộ vai trò.","dm_message":"🕯️ **NHÀ NGOẠI CẢM**\n\nBạn thuộc phe **Người Sống Sót**.\n\n👻 Vào ban đêm bạn có thể mở séance để trò chuyện với người đã chết.\n📡 Các linh hồn có thể cung cấp manh mối quan trọng.\n\n🚫 Bạn không tham gia bỏ phiếu cách ly ban ngày.\n🎯 Mục tiêu: Thu thập thông tin từ cõi âm để giúp thị trấn chiến thắng."},
    {"name":"Điệp Viên",           "faction":"Survivors","description":"Theo dõi ai đó và biết họ đã làm gì đêm qua.","color":"#34d399","tips":"Theo dõi những người im lặng nhưng có vẻ tự tin bất thường.","dm_message":"👁️ **ĐIỆP VIÊN**\n\nBạn thuộc phe **Người Sống Sót**.\n\n📡 Mỗi đêm bạn tự động nhận thông tin về mục tiêu mà Dị Thể nhắm vào.\n🔕 Bạn không biết ai là kẻ giết — chỉ biết ai bị nhắm.\n\n💡 Hãy chia sẻ thông tin cẩn thận — lộ sớm có thể khiến bạn bị tiêu diệt.\n🎯 Mục tiêu: Dùng tin tức để hướng dẫn thị trấn bỏ phiếu đúng người."},
    {"name":"Cảnh Sát",            "faction":"Survivors","description":"Bắn chết một người vào ban ngày. Chỉ được dùng 1 lần.","color":"#fb923c","tips":"Chỉ hành động khi chắc chắn — sai lầm có thể gây hại cho phe bạn.","dm_message":"🔫 **KẺ TRỪNG PHẠT**\n\nBạn thuộc phe **Người Sống Sót**.\n\n💥 Bạn có 3 viên đạn để trừng phạt kẻ tình nghi bất cứ lúc nào.\n\n☀️ Bắn ban ngày → bạn bị **lộ diện** trước toàn thị trấn.\n🌙 Bắn ban đêm → danh tính được giữ bí mật.\n🚫 Bạn không tham gia bỏ phiếu cách ly.\n⚠️ Bắn nhầm Survivor có thể làm mất lòng tin của thị trấn!\n🎯 Mục tiêu: Hành động quyết đoán khi thị trấn do dự."},
    {"name":"Bẫy Thủ",            "faction":"Survivors","description":"Đặt bẫy để phát hiện và bắt Dị Thể tấn công.","color":"#84cc16","tips":"Đặt bẫy gần người quan trọng (Thám Trưởng, Cai Ngục) để bảo vệ.","dm_message":"🪤 **THỢ ĐẶT BẪY**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🏠 Nhà bạn có một chiếc bẫy — kích hoạt **một lần** khi bị tấn công.\n\nKhi bẫy bắt được Dị Thể (4 kết quả xác suất bằng nhau):\n👁️ 25% — Kẻ tấn công bị **lộ danh tính** trước thị trấn\n💀 25% — Kẻ tấn công bị **tiêu diệt** tại chỗ\n💥 25% — **Phản đòn**: Bạn chết, kẻ tấn công thoát\n😵 25% — Kẻ tấn công bị **Stun**, mất lượt hành động đêm hôm sau\n\n⚠️ Bẫy chỉ hoạt động **một lần duy nhất**.\n🎯 Mục tiêu: Trở thành cái bẫy sống để vạch mặt hoặc tiêu diệt Dị Thể."},
    {"name":"Kiến Trúc Sư",        "faction":"Survivors","description":"Xây dựng công trình phòng thủ, gia cố bảo vệ người chơi khác.","color":"#06b6d4","tips":"Ưu tiên bảo vệ các vai trò điều tra và kiểm soát.","dm_message":"🏗️ **KIẾN TRÚC SƯ**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Bạn có thể gia cố nhà ở, bảo vệ Người Sống Sót khỏi bị giết trong đêm.\n\n📋 Cơ chế:\n• Chọn tối đa 5 người mỗi lượt Gia Cố.\n• Chỉ có tác dụng với Người Sống Sót — Dị Thể không được bảo vệ.\n• Bạn có **2 lượt** dùng trong suốt cả trận.\n\n💡 Hãy dùng đúng lúc — bảo vệ các vai trò quan trọng khi thị trấn bị đe dọa."},
    {"name":"Nhà Lưu Trữ",         "faction":"Survivors","description":"Bảo quản bằng chứng và thông tin quan trọng qua các đêm.","color":"#8b5cf6","tips":"Ghi chép kỹ lưỡng để cung cấp bằng chứng vào ban ngày.","dm_message":"📚 **NHÀ LƯU TRỮ**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Mỗi đêm bạn chọn 1 người đã chết để đọc di chúc bí mật của họ.\n\n📋 Cơ chế:\n• Mỗi người chỉ được đọc 1 lần.\n• Thông tin chỉ gửi riêng cho bạn.\n• Nếu di chúc bị Glitch-Worm phá hủy hoặc không tồn tại, bạn sẽ thấy thông báo.\n\n💡 Đây là công cụ điều tra ngầm — khai thác thông tin người chết trước khi bị xóa."},
    {"name":"Phục Sinh Sư",        "faction":"Survivors","description":"Hồi sinh một người đã chết. Cực kỳ hiếm và mạnh.","color":"#ec4899","tips":"Hồi sinh Thám Trưởng hoặc Cai Ngục ở giai đoạn cuối để lật ngược thế cờ.","dm_message":"⚡ **KẺ BÁO OÁN**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🔄 Một lần duy nhất trong cả game, bạn có thể hồi sinh 1 Survivor đã chết.\n\n☀️ Hồi sinh ban ngày → bạn bị **lộ diện** trước thị trấn.\n🌙 Hồi sinh ban đêm → danh tính được giữ bí mật.\n⚠️ Chỉ dùng được 1 lần — hãy chọn thời điểm thích hợp!\n🎯 Mục tiêu: Tận dụng kỹ năng hồi sinh đúng lúc để lật ngược thế cờ."},
    {"name":"Giám Hộ Viên",        "faction":"Survivors","description":"Canh gác mục tiêu — kẻ tấn công mục tiêu sẽ bị tiêu diệt.","color":"#f97316","tips":"Ưu tiên bảo vệ các vai trò quan trọng như Thám Trưởng hoặc Cai Ngục.","dm_message":"📷 **NGƯỜI GIÁM SÁT**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🌙 Bạn kiểm soát camera an ninh — mỗi đêm có thể bật Camera để theo dõi.\n\n📋 Cơ chế:\n• Camera ghi lại tối đa 3 người đang hoạt động trong đêm (ngẫu nhiên).\n• Nếu phát hiện Anomaly, một cảnh báo tự động được gửi vào kênh Dị Thể.\n• Bạn có **3 lượt** sử dụng trong suốt trận.\n\n⚠ Cẩn thận: Cảnh báo tới Dị Thể có thể khiến chúng biết bạn đang theo dõi.\n💡 Chọn đúng thời điểm dùng Camera để tối đa hiệu quả."},
    {"name":"Tâm Lý Gia",          "faction":"Survivors","description":"Đọc hành vi và phát hiện vai trò qua tâm lý.","color":"#6366f1","tips":"Chú ý ai nói quá nhiều hoặc quá ít so với bình thường.","dm_message":"🔮 **NGƯỜI TIÊN TRI**\n\nBạn thuộc phe **Người Sống Sót**.\n\nBạn sở hữu 3 kỹ năng siêu nhiên:\n\n🔮 **KN1 — Tiên Đoán:** Ghi dự đoán, Gemini A.I kiểm chứng.\n  • Đúng → KN3 được hồi 1 lần, KN1 **không mất**\n  • Sai → KN1 **mất vĩnh viễn**\n\n👁️ **KN2 — Kiểm Tra Ba:** Chọn 3 người, xem thống kê phe của họ.\n  • Chỉ dùng 1 lần. Có 30% khả năng sai 1 phần.\n\n🛡️ **KN3 — Bảo Hộ Linh Hồn:** Tự bảo vệ bản thân 1 đêm.\n  • Mặc định 2 lần. KN1 đoán đúng hồi thêm 1 lần.\n\nChúc bạn may mắn, hỡi người nắm giữ vận mệnh! 🌙"},
    {"name":"Người Ngủ",           "faction":"Survivors","description":"Có vẻ bình thường nhưng có khả năng đặc biệt xảy ra khi ngủ.","color":"#64748b","tips":"Giữ bình thản — thông tin đến khi bạn ít ngờ tới nhất.","dm_message":"😴 **KẺ NGỦ MÊ**\n\nBạn thuộc phe **Người Sống Sót**.\n\n🚫 Bạn không thể thấy và không thể tham gia chat Thị Trấn.\n\n🌙 Mỗi sáng bạn sẽ nhận được báo cáo chi tiết những gì đã xảy ra đêm qua.\n⚠ Không bao giờ tiết lộ danh tính thủ phạm.\n\n📝 Hãy cập nhật Giấy lời nhắn mỗi ngày.\nNếu bạn chết, toàn bộ ghi chú sẽ được công bố cho tất cả mọi người."},
    {"name":"Dược Sĩ Điên",        "faction":"Survivors","description":"Tạo ra các loại thuốc ngẫu nhiên — có thể cứu người hoặc gây hại.","color":"#ef4444","tips":"Rủi ro cao, phần thưởng cao — chỉ dùng khi thực sự cần thiết.","dm_message":"🧪 **NHÀ DƯỢC HỌC ĐIÊN**\n\nBạn thuộc phe **Người Sống Sót**.\n\nBạn có 4 loại thuốc đặc biệt:\n\n💊 **Hồi Phục Nhanh** `×2` — Bảo vệ mục tiêu khỏi bị giết 1 lần. Có thể dùng cho bản thân.\n\n💀 **Ngừng Tim** `×1` — Giết mục tiêu ngay lập tức.\n\n✨ **Phát Sáng** `×1` — Nếu mục tiêu bị Dị Thể giết, kẻ đó bị lộ tên với toàn thị trấn.\n\n⚗️ **Trường Sinh / Virus** `×1`\n   • Hồi Phục còn → Bất tử 2 đêm.\n   • Hồi Phục hết → Mục tiêu chết ngay, ai giết họ cũng chết theo.\n\n📌 Không thể dùng thuốc cho bản thân (trừ Hồi Phục).\n📌 Tối thiểu 16 người chơi."},
    {"name":"Người Báo Thù",       "faction":"Survivors","description":"Sau khi chết, có thể tiêu diệt kẻ đã giết mình.","color":"#dc2626","tips":"Hãy để lại di chúc rõ ràng để đồng đội biết ai đã giết bạn.","dm_message":"⚔️ **KẺ BÁO THÙ**\n\nBạn thuộc phe **Người Sống Sót**.\n\nNếu bạn chết, bạn sẽ kéo kẻ thù xuống cùng mình.\n\n🔥 Cơ chế trả thù:\n• Bị Trục xuất: Giết Mayor và 1 Survivor bạn chọn.\n• Bị Dị Thể giết: Giết Lãnh Chúa và 1 Anomaly bạn chọn.\n• Bị Unknown giết: Giết chính kẻ đã ra tay với bạn.\n\n⏳ Khi bạn chết, trận đấu sẽ tạm dừng 30 giây để bạn chọn mục tiêu."},
    # Anomalies
    {"name":"Dị Thể",              "faction":"Anomalies","description":"Dị Thể cơ bản. Giết một người mỗi đêm để loại bỏ Survivors.","color":"#f87171","tips":"Ưu tiên tiêu diệt Thám Trưởng, Cai Ngục và Thám Tử trước tiên.","dm_message":"🔴 **DỊ THỂ**\n\nBạn thuộc phe **Dị Thể**.\n\nBạn là chiến binh cốt lõi — sức mạnh nằm ở tập thể.\n\n📋 Cơ chế:\n• Mỗi đêm phe bạn cùng bỏ phiếu chọn 1 người để tiêu diệt.\n• Khi **Lãnh Chúa còn sống**: Lãnh Chúa có quyền quyết định cuối cùng.\n• Khi **Lãnh Chúa chết**: vote đa số trong phe sẽ quyết định mục tiêu.\n\n👁️ Bạn biết danh tính toàn bộ đồng đội Dị Thể.\n\n🏆 Điều kiện thắng: Dị Thể chiếm đa số hoặc bằng số Người Sống Sót còn lại.\n💡 Hãy phối hợp với đồng đội — sức mạnh của bạn là tổ chức, không phải cá nhân."},
    {"name":"Người Hành Quyết",    "faction":"Anomalies","description":"Dị Thể mạnh mẽ với khả năng xử tử đặc biệt không thể bị chặn.","color":"#ef4444","tips":"Dùng khả năng khi Survivors đang có nhiều lớp bảo vệ.","dm_message":"⚔️ **DỊ THỂ HÀNH QUYẾT**\n\nBạn thuộc phe **Dị Thể**.\n\n🌙 Mỗi đêm bạn có thể chọn 1 người để hành quyết — xuyên qua mọi lớp bảo vệ.\n\n📋 Cơ chế:\n• Mục tiêu bị giết kể cả khi có bảo vệ.\n• Người bảo vệ mục tiêu cũng bị phản thương và tiêu diệt.\n• Bạn có **2 lượt** — mỗi đêm hồi 1 lượt sau khi dùng."},
    {"name":"Lãnh Chúa",           "faction":"Anomalies","description":"Chỉ huy Dị Thể. Biết danh sách đồng đội và điều phối tấn công.","color":"#dc2626","tips":"Phân công rõ mục tiêu mỗi đêm để tối ưu hiệu quả tấn công.","dm_message":"👑 **LÃNH CHÚA**\n\nBạn thuộc phe **Dị Thể**.\n\n🎯 Mỗi đêm bạn quyết định mục tiêu tấn công của cả phe Dị Thể.\n👥 Bạn biết danh tính toàn bộ đồng đội Dị Thể.\n\n⚠️ Khi bạn chết, phe Dị Thể mất thủ lĩnh — họ phải bỏ phiếu chung để chọn mục tiêu.\n🎯 Mục tiêu: Điều phối phe Dị Thể tiêu diệt Người Sống Sót trước khi bị lộ."},
    {"name":"Nhà Vệ Sinh",         "faction":"Anomalies","description":"Xóa di chúc và bằng chứng của nạn nhân sau khi chết.","color":"#b91c1c","tips":"Ưu tiên xóa bằng chứng của Thám Trưởng và Cai Ngục.","dm_message":"🧹 **LAO CÔNG**\n\nBạn thuộc phe **Dị Thể**.\n\n🗑️ Mỗi đêm bạn chọn 1 mục tiêu để dọn dẹp.\n   Nếu mục tiêu chết đêm đó → vai trò của họ bị **xóa sạch** khỏi thông báo.\n   Thị trấn sẽ không biết ai vừa chết là vai gì!\n\n👥 Bạn biết danh tính toàn bộ đồng đội Dị Thể.\n🎯 Mục tiêu: Giúp phe Dị Thể hoạt động trong bóng tối."},
    {"name":"Phát Tín Hiệu Giả",   "faction":"Anomalies","description":"Gửi kết quả điều tra sai lệch cho Thám Trưởng và Thám Tử.","color":"#991b1b","tips":"Tạo bóng nghi lên Survivors đáng tin nhất để gây hỗn loạn.","dm_message":"📡 **TÍN HIỆU GIẢ**\n\nBạn thuộc phe **Dị Thể**.\n\n🌙 Mỗi đêm bạn phát tín hiệu giả cho 1 người — nếu Sheriff hoặc Investigator điều tra họ, kết quả bị bóp méo.\n\n• Kết quả: 'Survivor - Power Role' thay vì thực tế.\n• Không thể dùng 2 lần liên tiếp trên cùng 1 người.\n• Bạn có **3 lượt** trong cả trận."},
    {"name":"Ký Sinh Thần Kinh",   "faction":"Anomalies","description":"Ký sinh vào não nạn nhân và điều khiển hành động của họ từ xa.","color":"#7f1d1d","tips":"Điều khiển Cai Ngục để nhốt đồng đội của Survivors.","dm_message":"🦠 **KÝ SINH THẦN KINH**\n\nBạn thuộc phe **Dị Thể**.\n\n📖 **Lore:** Một sinh vật gớm ghiếc vô hình, có khả năng xâm nhập vào hệ thần kinh của những kẻ sống sót, từ từ ăn mòn ý lý và biến họ thành những con rối phục tùng phe Dị Thể.\n\n📋 **Cơ chế Kỹ Năng:**\n• Mỗi đêm, chọn 1 mục tiêu để ký sinh.\n• Cần 3 ngày (3 vòng ban ngày) để tha hóa hoàn toàn vật chủ.\n• Vật chủ sẽ bị biến thành Anomaly (hoặc Anomaly Servant) và mất role cũ.\n\n⚠ **Giới Hạn & Cân Bằng:**\n• Chỉ có thể ký sinh 1 người cùng lúc.\n• Không thể chọn đồng đội Dị Thể hoặc những người đã từng bị ký sinh trước đó.\n• Nếu vật chủ chết, bạn mất liên kết và có thể ký sinh người mới.\n• Nếu bạn chết, quá trình tha hóa đang diễn ra sẽ lập tức bị hủy bỏ."},
    {"name":"Bóng Tối Kiến Trúc Sư","faction":"Anomalies","description":"Xây dựng bẫy và công trình tấn công để chống Survivors.","color":"#450a0a","tips":"Đặt bẫy ở nơi Survivors thường hoạt động.","dm_message":"🌑 **KIẾN TRÚC SƯ BÓNG TỐI**\n\nBạn thuộc phe **Dị Thể**.\n\n🌙 Mỗi đêm bạn chọn 3 ngôi nhà để phong tỏa trong bóng tối.\n\n📋 Cơ chế:\n• 3 người được chọn sẽ bị khóa — không thể dùng bất kỳ kỹ năng đêm nào.\n• Mỗi người chỉ bị nhắm 1 lần. Danh sách mục tiêu thu hẹp dần theo thời gian.\n\n💡 Hãy ưu tiên phong tỏa các vai trò nguy hiểm như Jailor, Architect, Sheriff."},
    {"name":"Kẻ Rình Rập Lỗi",    "faction":"Anomalies","description":"Theo dõi mục tiêu qua nhiều đêm rồi tấn công bất ngờ.","color":"#fca5a5","tips":"Kiên nhẫn quan sát trước khi ra tay để chắc chắn không bị chặn.","dm_message":"👁️ **KẺ RÌNH RẬP**\n\nBạn thuộc phe **Dị Thể**.\n\n🌙 Mỗi đêm bạn chọn 1 Survivor để quét và phát hiện vai trò thực của họ.\n\n📋 Cơ chế:\n• Chỉ nhắm được Người Sống Sót — không thể theo dõi Dị Thể khác.\n• Không thể theo dõi cùng 1 người 2 đêm liên tiếp.\n• Kết quả được lưu vào bộ nhớ để dùng sau.\n\n💡 Dùng thông tin thu thập được để lên kế hoạch loại bỏ mục tiêu nguy hiểm nhất."},
    {"name":"Tên Trộm Thì Thầm",   "faction":"Anomalies","description":"Nghe lén thông tin riêng tư và sử dụng chống lại Survivors.","color":"#fecaca","tips":"Tập trung vào kênh liên lạc của Thám Trưởng và Cai Ngục.","dm_message":"🤫 **KẺ ĐÁNH CẮP LỜI THÌ THẦM**\n\nBạn thuộc phe **Dị Thể**.\n\n🌙 Mỗi đêm chọn 2 người để nghe lén — nếu họ có tương tác bí mật, bạn đọc được di chúc của cả hai.\n\n• Không thể chọn lại cùng cặp 2 đêm liên tiếp.\n💡 Nhắm vào những người nghi ngờ đang liên lạc ngầm."},
    {"name":"Người Phát Sóng Tĩnh","faction":"Anomalies","description":"Gây nhiễu thông tin liên lạc trong team Survivors.","color":"#fee2e2","tips":"Kích hoạt vào đêm quan trọng khi Survivors chuẩn bị phối hợp.","dm_message":"📻 **NGUỒN TĨNH ĐIỆN**\n\nBạn thuộc phe **Dị Thể**.\n\n🌙 Mỗi đêm bạn chọn 1 người để phát nhiễu — tin nhắn hệ thống của họ bị biến dạng.\n\n• Các nguyên âm bị thay thế bằng ký hiệu đặc biệt.\n💡 Phát nhiễu đúng thời điểm để Người Sống Sót không thể đọc kết quả điều tra."},
    {"name":"Người Cắt Xé",        "faction":"Anomalies","description":"Vô hiệu hóa khả năng đặc biệt của nạn nhân trong một đêm.","color":"#ef4444","tips":"Khóa Giám Hộ Viên trước khi tấn công mục tiêu chính.","dm_message":"🗂️ **MÁY HỦY TÀI LIỆU**\n\nBạn thuộc phe **Dị Thể**.\n\n🌙 Mỗi đêm bạn chọn 1 người để hủy di chúc nếu họ bị giết.\n\n📋 Cơ chế:\n• Nếu mục tiêu chết trong đêm bạn đánh dấu, di chúc của họ bị xóa hoàn toàn.\n💡 Nhắm vào Archivist, Sleeper hoặc bất kỳ ai có thể để lại thông tin nguy hiểm."},
    {"name":"Kẻ Ăn Chân Lý",       "faction":"Anomalies","description":"Cung cấp kết quả điều tra sai cho Thám Trưởng như thể thật.","color":"#dc2626","tips":"Phối hợp với Lãnh Chúa để tối ưu thông tin giả.","dm_message":"🧬 **KẺ MÔ PHỎNG SINH HỌC**\n\nBạn thuộc phe **Dị Thể**.\n\n🔗 Đầu game, bạn chọn 1 Survivor để liên kết cộng sinh.\n\n💀 Nếu người cộng sinh bị giết trước → bạn nhận 1 lần miễn nhiễm sát thương ban đêm.\n🚪 Nếu bạn bị Cách Ly/trục xuất → người cộng sinh bị loại theo.\n\n👥 Bạn biết danh tính toàn bộ đồng đội Dị Thể.\n🎯 Mục tiêu: Ẩn náu trong bóng tối nhờ liên kết sinh học để sống sót."},
    # Unknown
    {"name":"Sát Nhân Hàng Loạt",  "faction":"Unknown","description":"Chiến thắng một mình. Phải giết đủ người để là người duy nhất còn sống.","color":"#fbbf24","tips":"Giữ bí mật tuyệt đối — dùng cả hai phe để loại lẫn nhau.","dm_message":"🔪 **KẺ GIẾT NGƯỜI HÀNG LOẠT**\n\nBạn thuộc phe **Thực Thể Không Xác Định** — chỉ chiến đấu cho bản thân.\n\n🌙 Mỗi đêm bạn chọn 1 người để sát hại trực tiếp.\n\n📋 Cơ chế:\n• Không thể giết cùng 1 người 2 đêm liên tiếp.\n• Hành động giết xảy ra ngay trong đêm — không cần chờ resolve.\n\n🏆 Điều kiện thắng: Chỉ còn mình bạn sống sót.\n⚠ Cả Người Sống Sót lẫn Dị Thể đều là mục tiêu — không có đồng minh."},
    {"name":"Kẻ Tâm Thần",         "faction":"Unknown","description":"Có mục tiêu ẩn riêng. Hoàn thành mục tiêu để thắng một mình.","color":"#f59e0b","tips":"Đọc kỹ mục tiêu trong DM — mỗi game có thể khác nhau.","dm_message":"🩸 **KẺ TÂM THẦN**\n\nBạn thuộc phe **Thực Thể Ẩn**.\n\nBạn xuất hiện như một thành viên của Dị Thể trong mắt họ.\nBạn có thể đọc được kênh chat bí mật của Dị Thể.\n\n🎯 Mục tiêu:\nBị Cách Ly và Trục Xuất vào ban ngày.\n\n🔥 Điều kiện thắng nghiệt ngã:\n- Bị loại bằng bỏ phiếu.\n- KHÔNG có bất kỳ phiếu nào từ phe Dị Thể bầu cho bạn.\n\nNếu chỉ 1 Anomaly bỏ phiếu cho bạn → bạn thua ngay lập tức."},
    {"name":"AI Bị Hỏng",          "faction":"Unknown","description":"AI không còn tuân theo lập trình. Mục tiêu bí ẩn thay đổi theo đêm.","color":"#d97706","tips":"Thích nghi nhanh với mục tiêu mới — sự linh hoạt là chìa khóa.","dm_message":"🤖 **A.I THA HÓA**\n\nBạn thuộc phe **Thực Thể Ẩn** — không phe phái, chỉ có mục tiêu thu thập và tiêu diệt.\n\n🌙 Mỗi đêm bạn thực hiện 2 hành động:\n• 🔍 QUÉT: Phân tích 1 người để nhận tài nguyên.\n  - Quét Anomaly  → +1 Điểm Khiên  (khi đủ 3 → tự động chặn 1 đòn tấn công)\n  - Quét Survivor → +1 Điểm Giết   (khi đủ 2 → dùng được 1 lần giết)\n• 💀 GIẾT: Tiêu tốn 2 Điểm Giết để hạ mục tiêu.\n\n🏆 Điều kiện thắng: Đã giết ≥3 Người Sống Sót + ≥3 Dị Thể + ≥3 Unknown (tổng 9).\n⚠️ Không thể quét cùng 1 người 2 đêm liên tiếp.\n🔢 Tối thiểu 32 người chơi mới kích hoạt vai trò này."},
    {"name":"Đồng Hồ Tận Thế",     "faction":"Unknown","description":"Đếm ngược bí mật. Khi hết giờ, mọi người đều thua — chỉ bạn thắng.","color":"#b45309","tips":"Kéo dài game càng lâu càng tốt — đừng để ai biết vai trò của bạn.","dm_message":"⏳ **ĐỒNG HỒ TẬN THẾ**\n\nBạn thuộc phe **Thực Thể Ẩn** — mục tiêu của bạn là thời gian, không phải máu.\n\n🌙 Mỗi đêm bạn có thể kích hoạt Tua Nhanh để rút ngắn thảo luận ban ngày.\n\n📋 Cơ chế:\n• Tua Nhanh: Thảo luận ban ngày còn 20 giây thay vì 90 giây.\n• Có **2 lượt** — không thể dùng 2 đêm liên tiếp.\n\n🏆 Điều kiện thắng: Trận đấu vẫn chưa kết thúc khi đến **Đêm 18**.\n💡 Hãy kiên nhẫn, tránh bị lộ và cản trở thị trấn kết thúc trận sớm."},
    {"name":"Người Dệt Giấc Mơ",   "faction":"Unknown","description":"Điều khiển giấc mơ của người khác. Thắng khi gây đủ hỗn loạn.","color":"#92400e","tips":"Tạo ảo giác và mâu thuẫn giữa các thành viên cả hai phe.","dm_message":"🌙 **KẺ DỆT MỘNG**\n\nBạn thuộc phe **Thực Thể Ẩn** — không giết, chỉ dệt sợi liên kết.\n\n🌙 Mỗi đêm bạn chọn 2 người để kết nối tâm trí — họ sẽ thấy vai trò của nhau trong giấc mơ.\n\n📋 Cơ chế:\n• Cả 2 người trong cặp đều nhận DM biết vai trò của nhau.\n• Tối đa **3 cặp** (6 người riêng biệt). Không tái chọn người đã dùng đêm trước.\n\n🏆 Điều kiện thắng: Cả 3 cặp đều còn sống đồng thời.\n⚠ Thách thức: Duy trì 6 người cùng sống sót trong khi thị trấn đang loại người mỗi ngày."},
    {"name":"Con Tàu Ma",           "faction":"Unknown","description":"Linh hồn lang thang. Thắng khi khiến cả hai phe nghi ngờ nhau đủ mức.","color":"#78350f","tips":"Rải thông tin mâu thuẫn một cách tinh tế, không quá lộ liễu.","dm_message":"🚢 **CON TÀU MA**\n\nBạn thuộc phe **Thực Thể Ẩn** — mục tiêu của bạn là bắt cóc, không phải giết.\n\n🌙 Từ Đêm 3 trở đi, mỗi đêm bạn bắt cóc 1 người đưa lên tàu — họ biến mất khỏi thế giới sống.\n\n📋 Cơ chế:\n• Người bị bắt cóc bị loại tạm thời — không chết nhưng không còn trong trận.\n• Không thể bắt cùng 1 người 2 đêm liên tiếp.\n• Số mục tiêu cần đủ phụ thuộc số người chơi ban đầu.\n\n🏆 Điều kiện thắng: Bắt đủ số người theo quy định.\n💡 Hãy ưu tiên bắt người quan trọng để vô hiệu hóa sức mạnh của Người Sống Sót."},
    {"name":"Con Sâu Lỗi",         "faction":"Unknown","description":"Ký sinh vào game. Thắng khi game bị hủy giữa chừng.","color":"#451a03","tips":"Gây bất ổn từ sớm để khiến người chơi bỏ cuộc.","dm_message":"🪱 **SÂU LỖI**\n\nBạn thuộc phe **Dị Thể**.\n\n🌙 Mỗi đêm bạn chọn 1 người để cài mã độc — nếu họ chết đêm đó, di chúc bị phá hủy hoàn toàn.\n\n📋 Cơ chế:\n• Di chúc bị thay thế bằng thông báo: '✖ Dữ liệu đã bị Glitch-Worm phá hủy.'\n• Không thể dùng 2 đêm liên tiếp.\n• Vô hiệu nếu mục tiêu đã bị Janitor làm sạch.\n• Bạn có **3 lượt** trong cả trận.\n\n💡 Nhắm vào Sleeper, Psychopath hoặc bất kỳ ai có di chúc quan trọng."},
    {"name":"Kẻ Dệt Thời Gian",    "faction":"Unknown","description":"Thao túng thứ tự hành động và timeline của đêm.","color":"#fde68a","tips":"Hiểu rõ priority system để khai thác tối đa khả năng.","dm_message":"⏳ **KẺ DỆT THỜI GIAN**\n\nBạn thuộc phe **Thực Thể Ẩn** — sức mạnh của bạn là thời gian.\n\n🌅 PASSIVE — Nhãn Quan Thời Gian:\nMỗi sáng bạn nhận DM biết tên 1 kẻ đã ra tay giết người đêm qua.\n\n⏪ ACTIVE — Rewind Timeline (1 lần duy nhất):\n• Dùng được từ Đêm 5 trở đi, khi còn hơn 8 người sống.\n• Khôi phục danh sách sống/chết, di chúc về trạng thái 2 ngày trước.\n\n💡 Bạn không có đồng minh — hãy dùng thông tin passive để thao túng cả hai phe và tồn tại đến cuối."},
    # Event
    {"name":"Người Mù",            "faction":"Event","description":"Vai trò sự kiện. Không thể thấy username người chơi khác — chỉ thấy số.","color":"#a855f7","tips":"Dựa vào giọng nói và hành vi thay vì tên người chơi.","dm_message":"👁 **MÙ QUÁNG**\n\nBạn thuộc phe **Dị Thể** — Vai Trò Sự Kiện Đặc Biệt.\n\n🌫 Bạn có khả năng gây mù tạm thời cho kẻ thù.\nKhi kích hoạt, toàn bộ Người Sống Sót và Unknown sẽ không thể nhìn thấy tên mục tiêu thật.\n\n⚡ **Kỹ năng:** Gây Mù — tối đa **3 lần** trong cả trận.\n🌙 Hiệu ứng kéo dài đến hết đêm kích hoạt.\n\n🎯 Mục tiêu: Phe Dị Thể chiến thắng."},
    {"name":"Người Giải Mật Mã",   "faction":"Event","description":"Giải mã các mật mã xuất hiện trong game để nhận thông tin quan trọng.","color":"#9333ea","tips":"Tốc độ là lợi thế — giải mã nhanh hơn đối thủ.","dm_message":"💀 **KẺ GIẢI MÃ**\n\nBạn thuộc phe **Thực Thể Ẩn** — không đồng minh, không phe phái.\n\n📡 **Passive – Nhiễu Loạn Hệ Thống:**\nKhi bạn còn sống, mọi thông báo công khai của bot bị nhiễu ký tự ngẫu nhiên.\nKể cả thông báo đêm, sáng, bỏ phiếu, di chúc — tất cả.\n\n💬 **Passive – Nhiễu Chat Người Chơi:**\nMọi tin nhắn người chơi gửi trong kênh game đều bị nhiễu ~50% ký tự.\nHiệu ứng này luôn hoạt động, **không** bị destroy mode thay thế.\n\n💣 **Kỹ năng – Phá Hủy Hệ Thống (5 lần):**\nKích hoạt ban đêm để biến mọi thông báo bot thành chuỗi ký tự hỗn loạn hoàn toàn.\n\n🏆 **Chiến thắng khi:**\n• **4 Người Sống Sót** đã chết **VÀ** **4 Dị Thể** đã chết\n• Cả hai phe thiệt hại nặng nề — hệ thống sụp đổ.\n\n⚠️ DM riêng của bạn sẽ không bị nhiễu."},
    {"name":"Người Kiểm Tra Chuyên Nghiệp","faction":"Event","description":"Vai trò test chuyên nghiệp cho server thử nghiệm tính năng mới.","color":"#7c3aed","tips":"Báo cáo mọi bất thường cho admin ngay lập tức.","dm_message":"🔬 **NGƯỜI THỬ NGHIỆM**\n\nBạn thuộc phe **Người Sống Sót** — Vai Trò Sự Kiện Đặc Biệt.\n\n🧪 Bạn có thiết bị theo dõi dị thể đặc biệt.\n👑 Ngay khi game bắt đầu, bạn sẽ biết ai là **Lãnh Chúa**.\n\n⚡ **Kỹ năng đặc biệt (1 lần):** Ép Lãnh Chúa tiêu diệt 1 Anomaly đồng đội.\n🤝 Nếu cả 2 Người Thử Nghiệm cùng kích hoạt — Lãnh Chúa mất **2 Anomaly** cùng lúc!\n☠️ Sau khi kích hoạt, bạn sẽ **hi sinh ngay lập tức**.\n\n🎯 Mục tiêu: Phe Người Sống Sót chiến thắng."},
]


# ──────────────────────────────────────────────────────────────────
# ROUTER
# ──────────────────────────────────────────────────────────────────
router = APIRouter()

# ── AUTH ──────────────────────────────────────────────────────────

@router.get("/auth/login")
async def auth_login(request: Request):
    state = secrets.token_hex(16)
    # Tự detect redirect URI từ request nếu env var chưa set
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
async def auth_callback(code: str, response: Response, state: str = ""):
    # Xử lý cả /auth/callback và /auth/discord/callback
    async with httpx.AsyncClient() as http:
        # Tự detect redirect_uri khớp với URL Discord gọi về
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
