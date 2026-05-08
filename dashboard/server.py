"""
dashboard/server.py — Anomalies Web Dashboard
FastAPI backend với Discord OAuth2 Login
Chạy trên Render.com
"""

from __future__ import annotations

import os
import time
import hmac
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import uvicorn

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
BOT_OWNER_ID        = 1306441206296875099
DISCORD_CLIENT_ID   = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI  = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/callback")
SECRET_KEY          = os.environ.get("SESSION_SECRET", secrets.token_hex(32))
MONGO_URI           = os.environ.get("MONGO_URI", "")

DISCORD_API   = "https://discord.com/api/v10"
OAUTH_SCOPES  = "identify guilds"

# ══════════════════════════════════════════════════════════════
# MONGODB
# ══════════════════════════════════════════════════════════════
_client = None

def get_db():
    global _client
    if _client is None and MONGO_URI:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    return _client["Anomalies_DB"] if _client else None

def col(name: str):
    db = get_db()
    return db[name] if db is not None else None

# ══════════════════════════════════════════════════════════════
# SESSION (signed cookie)
# ══════════════════════════════════════════════════════════════

def _sign(data: str) -> str:
    return hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()

def set_session(response: Response, user_id: str, access_token: str, username: str, avatar: str):
    payload = f"{user_id}|{access_token}|{username}|{avatar}"
    sig = _sign(payload)
    cookie_val = f"{payload}||{sig}"
    response.set_cookie("session", cookie_val, httponly=True, samesite="lax", max_age=86400*7)

def get_session(request: Request) -> Optional[dict]:
    cookie = request.cookies.get("session", "")
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
        "user_id": user_id,
        "access_token": access_token,
        "username": username,
        "avatar": avatar,
        "is_owner": int(user_id) == BOT_OWNER_ID
    }

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

# ══════════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════════
app = FastAPI(title="Anomalies Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ══════════════════════════════════════════════════════════════
# AUTH ROUTES
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

@app.get("/auth/callback")
async def callback(code: str, response: Response):
    async with httpx.AsyncClient() as http:
        # Exchange code for token
        token_resp = await http.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        if token_resp.status_code != 200:
            raise HTTPException(400, "Không lấy được token từ Discord")
        token_data = token_resp.json()
        access_token = token_data["access_token"]

        # Fetch user info
        user_resp = await http.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_resp.status_code != 200:
            raise HTTPException(400, "Không lấy được thông tin user")
        user = user_resp.json()

    user_id  = user["id"]
    username = user.get("global_name") or user.get("username", "Unknown")
    avatar   = user.get("avatar", "")
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png" if avatar else f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"

    redirect = RedirectResponse("/", status_code=302)
    set_session(redirect, user_id, access_token, username, avatar_url)
    return redirect

@app.get("/auth/logout")
async def logout(response: Response):
    redirect = RedirectResponse("/", status_code=302)
    redirect.delete_cookie("session")
    return redirect

# ══════════════════════════════════════════════════════════════
# API — PUBLIC (cần đăng nhập)
# ══════════════════════════════════════════════════════════════

@app.get("/api/dash/me")
@app.get("/api/me")
async def api_me(request: Request):
    session = get_session(request)
    if not session:
        return JSONResponse({"logged_in": False})
    return JSONResponse({
        "logged_in": True,
        "user_id": session["user_id"],
        "username": session["username"],
        "avatar": session["avatar"],
        "is_owner": session["is_owner"]
    })

@app.get("/api/dash/roles")
async def api_roles(request: Request):
    """Trả về danh sách tất cả vai trò từ MongoDB hoặc hardcode."""
    session = require_auth(request)
    # Lấy từ DB nếu có, fallback về danh sách hardcode
    roles_data = _get_roles_catalog()
    return JSONResponse(roles_data)

@app.get("/api/dash/guilds")
async def api_guilds(request: Request):
    """Lấy danh sách server mà user có trong game (từ Discord)."""
    session = require_auth(request)
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {session['access_token']}"}
        )
        if resp.status_code != 200:
            return JSONResponse([])
        guilds = resp.json()
    # Lọc guild có config trong DB
    db_col = col("guild_configs")
    result = []
    if db_col:
        for g in guilds:
            doc = db_col.find_one({"guild_id": str(g["id"])})
            if doc:
                icon = g.get("icon")
                icon_url = f"https://cdn.discordapp.com/icons/{g['id']}/{icon}.png" if icon else None
                result.append({
                    "id": g["id"],
                    "name": g["name"],
                    "icon": icon_url,
                    "permissions": g.get("permissions", 0)
                })
    return JSONResponse(result)

@app.get("/api/dash/guild/{guild_id}/config")
async def api_guild_config(guild_id: str, request: Request):
    session = require_auth(request)
    _assert_guild_access(session, guild_id)
    db_col = col("guild_configs")
    if not db_col:
        return JSONResponse({})
    doc = db_col.find_one({"guild_id": guild_id})
    if doc:
        doc.pop("_id", None)
    return JSONResponse(doc or {})

@app.post("/api/dash/guild/{guild_id}/config")
async def api_update_config(guild_id: str, request: Request):
    session = require_auth(request)
    _assert_guild_access(session, guild_id)
    data = await request.json()
    # Whitelist các field được phép sửa
    allowed = {
        "max_players", "min_players", "countdown_time", "allow_chat",
        "mute_dead", "no_remove_roles", "music", "skip_discussion",
        "day_time", "vote_time", "skip_discussion_delay"
    }
    update = {k: v for k, v in data.items() if k in allowed}
    db_col = col("guild_configs")
    if db_col and update:
        db_col.update_one({"guild_id": guild_id}, {"$set": update}, upsert=True)
    return JSONResponse({"ok": True})

@app.get("/api/dash/guild/{guild_id}/status")
async def api_guild_status(guild_id: str, request: Request):
    require_auth(request)
    db_col = col("guild_configs")
    if not db_col:
        return JSONResponse({"status": None})
    doc = db_col.find_one({"guild_id": guild_id}, {"status": 1, "max_players": 1})
    status = doc.get("status") if doc else None
    return JSONResponse({"status": status, "max_players": doc.get("max_players", 65) if doc else 65})

@app.get("/api/dash/changelog")
async def api_changelog(request: Request):
    require_auth(request)
    db_col = col("changelogs")
    if not db_col:
        return JSONResponse([])
    logs = list(db_col.find({}, {"_id": 0}).sort("created_at", -1).limit(20))
    return JSONResponse(logs)

@app.post("/api/dash/feedback")
async def api_feedback(request: Request):
    session = require_auth(request)
    data = await request.json()
    content = str(data.get("content", "")).strip()[:2000]
    images  = data.get("images", [])[:5]
    if not content and not images:
        raise HTTPException(400, "Nội dung trống")
    db_col = col("feedbacks")
    if db_col:
        db_col.insert_one({
            "user_id":   session["user_id"],
            "username":  session["username"],
            "avatar":    session["avatar"],
            "content":   content,
            "images":    images,
            "reply":     None,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    return JSONResponse({"ok": True})

# ══════════════════════════════════════════════════════════════
# API — OWNER ONLY
# ══════════════════════════════════════════════════════════════

@app.get("/api/dash/admin/feedbacks")
async def api_admin_feedbacks(request: Request):
    require_owner(request)
    db_col = col("feedbacks")
    if not db_col:
        return JSONResponse([])
    docs = list(db_col.find({}, {"_id": 0}).sort("created_at", -1).limit(50))
    return JSONResponse(docs)

@app.post("/api/dash/admin/feedback/{fb_id}/reply")
async def api_reply_feedback(fb_id: str, request: Request):
    require_owner(request)
    data = await request.json()
    reply = str(data.get("reply", "")).strip()[:1000]
    from bson import ObjectId
    db_col = col("feedbacks")
    if db_col:
        db_col.update_one({"_id": ObjectId(fb_id)}, {"$set": {"reply": reply}})
    return JSONResponse({"ok": True})

@app.post("/api/dash/admin/feedback/{fb_id}/reply_by_index")
async def api_reply_feedback_by_index(fb_id: str, request: Request):
    """Reply bằng index (created_at + user_id) thay vì ObjectId."""
    require_owner(request)
    data = await request.json()
    reply = str(data.get("reply", "")).strip()[:1000]
    created_at = data.get("created_at", "")
    db_col = col("feedbacks")
    if db_col and created_at:
        db_col.update_one({"created_at": created_at}, {"$set": {"reply": reply}})
    return JSONResponse({"ok": True})

@app.post("/api/dash/admin/changelog")
async def api_post_changelog(request: Request):
    require_owner(request)
    data = await request.json()
    title   = str(data.get("title", "")).strip()[:200]
    content = str(data.get("content", "")).strip()[:5000]
    version = str(data.get("version", "")).strip()[:20]
    if not title or not content:
        raise HTTPException(400, "Thiếu tiêu đề hoặc nội dung")
    db_col = col("changelogs")
    if db_col:
        db_col.insert_one({
            "title":      title,
            "content":    content,
            "version":    version,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    return JSONResponse({"ok": True})

@app.get("/api/dash/admin/bans")
async def api_admin_bans(request: Request):
    require_owner(request)
    db_col = col("bans")
    if not db_col:
        return JSONResponse([])
    docs = list(db_col.find({}, {"_id": 0}).sort("created_at", -1))
    return JSONResponse(docs)

@app.post("/api/dash/admin/ban")
async def api_ban_player(request: Request):
    require_owner(request)
    data = await request.json()
    user_id = str(data.get("user_id", "")).strip()
    reason  = str(data.get("reason", "Không có lý do")).strip()[:500]
    mode    = data.get("mode", "ban")  # "ban" | "lobby"
    if not user_id:
        raise HTTPException(400, "Thiếu user_id")
    db_col = col("bans")
    if db_col:
        db_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id":    user_id,
                "reason":     reason,
                "mode":       mode,
                "created_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
    return JSONResponse({"ok": True})

@app.delete("/api/dash/admin/ban/{user_id}")
async def api_unban_player(user_id: str, request: Request):
    require_owner(request)
    db_col = col("bans")
    if db_col:
        db_col.delete_one({"user_id": user_id})
    return JSONResponse({"ok": True})

@app.get("/api/dash/admin/rooms")
async def api_admin_guilds(request: Request):
    require_owner(request)
    db_col = col("guild_configs")
    if not db_col:
        return JSONResponse([])
    docs = list(db_col.find({}, {"_id": 0, "guild_id": 1, "guild_name": 1, "status": 1, "max_players": 1}))
    return JSONResponse(docs)

# ══════════════════════════════════════════════════════════════
# SERVE FRONTEND (SPA)
# ══════════════════════════════════════════════════════════════

@app.get("/{full_path:path}", response_class=HTMLResponse)
async def serve_spa(full_path: str):
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Dashboard đang khởi động...</h1>")

# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _assert_guild_access(session: dict, guild_id: str):
    """Owner có thể access tất cả guild. User thường cần xác minh quyền."""
    if session["is_owner"]:
        return
    # TODO: kiểm tra user có quyền manage_guild trong Discord server đó

def _get_roles_catalog() -> list:
    return [
        # Survivors
        {"name": "Thường Dân",        "faction": "Survivors", "team": "Survivors", "description": "Không có kỹ năng đặc biệt. Tồn tại đến cuối game là chiến thắng.", "color": "#4ade80"},
        {"name": "Thám Trưởng",       "faction": "Survivors", "team": "Survivors", "description": "Điều tra một người mỗi đêm để biết phe của họ.", "color": "#60a5fa"},
        {"name": "Cai Ngục",          "faction": "Survivors", "team": "Survivors", "description": "Giam cầm một người mỗi đêm. Có thể thẩm vấn và xử tử tù nhân.", "color": "#f59e0b"},
        {"name": "Thị Trưởng",        "faction": "Survivors", "team": "Survivors", "description": "Có thể lộ diện để nhận 3 phiếu bầu. Rất mạnh nhưng nguy hiểm.", "color": "#a78bfa"},
        {"name": "Trợ Lý Thị Trưởng","faction": "Survivors", "team": "Survivors", "description": "Hỗ trợ Thị Trưởng và nhận quyền bầu cử đặc biệt.", "color": "#c4b5fd"},
        {"name": "Thám Tử",           "faction": "Survivors", "team": "Survivors", "description": "Điều tra sâu hơn, nhận thêm thông tin về vai trò.", "color": "#38bdf8"},
        {"name": "Pháp Quan",         "faction": "Survivors", "team": "Survivors", "description": "Giao tiếp với người đã chết để lấy thông tin.", "color": "#94a3b8"},
        {"name": "Điệp Viên",         "faction": "Survivors", "team": "Survivors", "description": "Theo dõi ai đó và biết họ đã làm gì đêm qua.", "color": "#34d399"},
        {"name": "Cảnh Sát",          "faction": "Survivors", "team": "Survivors", "description": "Bắn chết một người vào ban ngày. Chỉ 1 lần.", "color": "#fb923c"},
        {"name": "Bẫy Thủ",          "faction": "Survivors", "team": "Survivors", "description": "Đặt bẫy để phát hiện và bắt Dị Thể.", "color": "#84cc16"},
        {"name": "Kiến Trúc Sư",      "faction": "Survivors", "team": "Survivors", "description": "Xây dựng công trình phòng thủ cho người chơi khác.", "color": "#06b6d4"},
        {"name": "Nhà Lưu Trữ",       "faction": "Survivors", "team": "Survivors", "description": "Bảo quản thông tin và bằng chứng qua các đêm.", "color": "#8b5cf6"},
        {"name": "Phục Sinh Sư",      "faction": "Survivors", "team": "Survivors", "description": "Hồi sinh một người đã chết. Cực kỳ hiếm và mạnh.", "color": "#ec4899"},
        {"name": "Giám Hộ Viên",      "faction": "Survivors", "team": "Survivors", "description": "Canh gác mục tiêu — kẻ tấn công sẽ bị tiêu diệt.", "color": "#f97316"},
        {"name": "Tâm Lý Gia",        "faction": "Survivors", "team": "Survivors", "description": "Đọc tâm trí và phát hiện vai trò qua hành vi.", "color": "#6366f1"},
        {"name": "Người Ngủ",         "faction": "Survivors", "team": "Survivors", "description": "Ngủ rất ngon. Nhưng có điều gì đó kỳ lạ xảy ra khi ngủ.", "color": "#64748b"},
        {"name": "Dược Sĩ Điên",      "faction": "Survivors", "team": "Survivors", "description": "Tạo ra các loại thuốc ngẫu nhiên — có thể cứu người hoặc giết người.", "color": "#ef4444"},
        {"name": "Người Báo Thù",     "faction": "Survivors", "team": "Survivors", "description": "Sau khi chết, có thể tiêu diệt kẻ đã giết mình.", "color": "#dc2626"},
        # Anomalies
        {"name": "Dị Thể",            "faction": "Anomalies", "team": "Anomalies", "description": "Dị Thể cơ bản. Giết một người mỗi đêm để loại bỏ Survivors.", "color": "#f87171"},
        {"name": "Người Hành Quyết",  "faction": "Anomalies", "team": "Anomalies", "description": "Dị Thể mạnh mẽ với khả năng xử tử đặc biệt.", "color": "#ef4444"},
        {"name": "Lãnh Chúa",         "faction": "Anomalies", "team": "Anomalies", "description": "Chỉ huy các Dị Thể. Biết danh sách đồng đội.", "color": "#dc2626"},
        {"name": "Nhà Vệ Sinh",       "faction": "Anomalies", "team": "Anomalies", "description": "Xóa di chúc và bằng chứng của nạn nhân.", "color": "#b91c1c"},
        {"name": "Phát Tín Hiệu Giả", "faction": "Anomalies", "team": "Anomalies", "description": "Gửi thông tin sai lệch cho Thám Tử và Thám Trưởng.", "color": "#991b1b"},
        {"name": "Kẻ Hút Não",        "faction": "Anomalies", "team": "Anomalies", "description": "Điều khiển hành động của người chơi khác.", "color": "#7f1d1d"},
        {"name": "Bóng Tối Kiến Trúc Sư","faction": "Anomalies","team":"Anomalies","description":"Dị Thể xây dựng bẫy để chống lại Survivors.", "color": "#450a0a"},
        {"name": "Ký Sinh Thần Kinh",  "faction": "Anomalies","team":"Anomalies","description":"Ký sinh vào não nạn nhân và điều khiển từ xa.", "color": "#fca5a5"},
        {"name": "Kẻ Rình Rập Lỗi",   "faction": "Anomalies","team":"Anomalies","description":"Theo dõi mục tiêu qua nhiều đêm rồi tấn công bất ngờ.", "color": "#fecaca"},
        {"name": "Tên Trộm Thì Thầm",  "faction": "Anomalies","team":"Anomalies","description":"Nghe lén thông tin riêng tư và sử dụng chống lại Survivors.", "color": "#fee2e2"},
        {"name": "Người Phát Sóng Tĩnh","faction":"Anomalies","team":"Anomalies","description":"Gây nhiễu thông tin liên lạc trong team Survivors.", "color": "#fef2f2"},
        {"name": "Người Cắt Xé",       "faction": "Anomalies","team":"Anomalies","description":"Vô hiệu hóa khả năng đặc biệt của nạn nhân.", "color": "#ef4444"},
        {"name": "Kẻ Ăn Chân Lý",      "faction": "Anomalies","team":"Anomalies","description":"Tiên tri giả — cung cấp kết quả điều tra sai cho Thám Trưởng.", "color": "#dc2626"},
        # Unknown
        {"name": "Sát Nhân Hàng Loạt", "faction": "Unknown",   "team": "Unknown",   "description": "Chiến thắng một mình. Giết mọi người còn sống.", "color": "#fbbf24"},
        {"name": "Kẻ Tâm Thần",        "faction": "Unknown",   "team": "Unknown",   "description": "Mục tiêu ẩn. Hoàn thành mục tiêu để thắng một mình.", "color": "#f59e0b"},
        {"name": "AI Bị Hỏng",         "faction": "Unknown",   "team": "Unknown",   "description": "AI không còn tuân theo lập trình. Mục tiêu bí ẩn.", "color": "#d97706"},
        {"name": "Đồng Hồ Tận Thế",    "faction": "Unknown",   "team": "Unknown",   "description": "Đếm ngược. Khi hết giờ, mọi người đều thua.", "color": "#b45309"},
        {"name": "Người Dệt Giấc Mơ",  "faction": "Unknown",   "team": "Unknown",   "description": "Điều khiển giấc mơ. Thắng khi gây đủ hỗn loạn.", "color": "#92400e"},
        {"name": "Con Tàu Ma",          "faction": "Unknown",   "team": "Unknown",   "description": "Linh hồn lang thang. Thắng bằng cách khiến cả hai phe nghi ngờ nhau.", "color": "#78350f"},
        {"name": "Con Sâu Lỗi",        "faction": "Unknown",   "team": "Unknown",   "description": "Ký sinh vào game. Thắng khi game bị hủy.", "color": "#451a03"},
        {"name": "Kẻ Dệt Thời Gian",   "faction": "Unknown",   "team": "Unknown",   "description": "Thao túng thứ tự hành động và timeline của game.", "color": "#fde68a"},
        # Event
        {"name": "Người Mù",           "faction": "Event",     "team": "Event",     "description": "Vai trò sự kiện đặc biệt. Không thể thấy username người khác.", "color": "#a855f7"},
        {"name": "Người Giải Mật Mã",  "faction": "Event",     "team": "Event",     "description": "Giải mã các mật mã để nhận thông tin quan trọng.", "color": "#9333ea"},
        {"name": "Người Kiểm Tra Chuyên Nghiệp","faction":"Event","team":"Event",   "description": "Vai trò test chuyên nghiệp cho các server đặc biệt.", "color": "#7c3aed"},
    ]


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=False)
