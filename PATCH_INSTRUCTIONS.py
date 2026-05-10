# ══════════════════════════════════════════════════════════════════
# PATCH HƯỚNG DẪN — Anomalies v2.3 → v2.3-fixed
#
# Áp dụng các thay đổi này vào app.py và dashboard_routes.py
# Hai file đã được fix hoàn toàn: config_manager.py và bot_main.py
# ══════════════════════════════════════════════════════════════════


# ╔══════════════════════════════════════════════════════════════════╗
# ║  FILE: app.py                                                   ║
# ╚══════════════════════════════════════════════════════════════════╝

# ─────────────────────────────────────────────────────────────────
# [1] THÊM import ssl ở đầu file (sau "import certifi")
# ─────────────────────────────────────────────────────────────────
# TÌM:
import certifi

# THAY BẰNG:
import certifi
import ssl  # ← THÊM DÒNG NÀY


# ─────────────────────────────────────────────────────────────────
# [2] FIX hàm _make_bot_with_proxy() — dòng ~1720
# Sửa TCPConnector(ssl=False) → TCPConnector(ssl=ssl_ctx)
# ─────────────────────────────────────────────────────────────────
# TÌM (khoảng dòng 1720):
def _make_bot_with_proxy(proxy: str | None) -> commands.Bot:
    """Tạo bot instance mới với proxy connector (nếu có)."""
    _intents = disnake.Intents.all()
    if proxy:
        connector = aiohttp.TCPConnector(ssl=False)

# THAY BẰNG:
def _make_bot_with_proxy(proxy: str | None) -> commands.Bot:
    """Tạo bot instance mới với proxy connector (nếu có)."""
    _intents = disnake.Intents.all()
    # FIX: aiohttp 3.9+ yêu cầu ssl là SSLContext, không phải string hay False.
    # ssl=False tắt hoàn toàn TLS → không an toàn và gây TypeError trên một số phiên bản.
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    if proxy:
        connector = aiohttp.TCPConnector(ssl=_ssl_ctx)


# ─────────────────────────────────────────────────────────────────
# [3] FIX phần on_ready() — khởi tạo aiohttp session (dòng ~1598)
# ─────────────────────────────────────────────────────────────────
# TÌM:
    if session is None or session.closed:
        session = aiohttp.ClientSession()
        print("[Bot] aiohttp session đã tạo.")

# THAY BẰNG:
    if session is None or session.closed:
        # FIX: Truyền SSLContext vào connector thay vì dùng default không certifi
        _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        _connector = aiohttp.TCPConnector(ssl=_ssl_ctx)
        session = aiohttp.ClientSession(connector=_connector)
        print("[Bot] aiohttp session đã tạo (SSL via certifi).")


# ─────────────────────────────────────────────────────────────────
# [4] FIX phần on_ready() — ensure_indexes (dòng ~1601)
# Bọc ensure_indexes trong try/except với traceback chi tiết
# ─────────────────────────────────────────────────────────────────
# TÌM:
    # Khởi tạo MongoDB indexes (chạy 1 lần)
    ensure_indexes()

# THAY BẰNG:
    # Khởi tạo MongoDB indexes — chạy trong executor để không block event loop
    # FIX: Thêm try/except + traceback để biết chính xác lý do thất bại
    try:
        _loop = asyncio.get_event_loop()
        await _loop.run_in_executor(None, ensure_indexes)
        print("[Bot] ✓ MongoDB indexes OK.")
    except Exception as _mongo_err:
        print(f"[Bot] ✗ ensure_indexes thất bại: {_mongo_err}")
        print(traceback.format_exc())
        print("[Bot] → Kiểm tra MONGO_URI và Atlas IP Whitelist (0.0.0.0/0).")


# ╔══════════════════════════════════════════════════════════════════╗
# ║  FILE: dashboard_routes.py                                      ║
# ╚══════════════════════════════════════════════════════════════════╝

# ─────────────────────────────────────────────────────────────────
# [5] FIX hàm api_guilds() — thêm guard bot.is_ready() (dòng ~593)
# ─────────────────────────────────────────────────────────────────
# TÌM:
@router.get("/api/dash/guilds")
@router.get("/api/dash/me/guilds")
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
        has_config = False
        if cfg_col:
            has_config = cfg_col.count_documents({"guild_id": gid}, limit=1) > 0
        if not has_config and gid not in _shared.get("guilds", {}):
            continue
        perms      = int(g.get("permissions", 0))
        is_manager = bool(perms & 0x20) or g.get("owner", False)
        icon       = g.get("icon")
        result.append({
            "id":         gid,
            "name":       g["name"],
            "icon":       f"https://cdn.discordapp.com/icons/{gid}/{icon}.png" if icon else None,
            "is_manager": is_manager,
        })
    return JSONResponse(result)

# THAY BẰNG:
@router.get("/api/dash/guilds")
@router.get("/api/dash/me/guilds")
async def api_guilds(request: Request):
    """Server mà user thuộc về và có config trong bot.

    FIX v2.3:
    - Kiểm tra bot.is_ready() trước khi truy vấn dữ liệu.
      Nếu bot chưa ready, trả 503 thay vì trả list rỗng gây nhầm lẫn.
    - Chạy count_documents trong executor (hàm blocking) để không block event loop.
    - Thêm timeout cho httpx để tránh treo request.
    """
    s = _require_auth(request)

    # FIX: Đảm bảo bot đã ready trước khi lấy dữ liệu guild
    bot = _shared.get("bot")
    if bot is not None and not bot.is_ready():
        return JSONResponse(
            {"error": "Bot chưa sẵn sàng, vui lòng thử lại sau vài giây."},
            status_code=503,
        )

    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {s['access_token']}"},
        )
        user_guilds = resp.json() if resp.status_code == 200 else []

    cfg_col = _col("guild_configs")
    result  = []
    loop    = asyncio.get_event_loop()

    for g in user_guilds:
        gid = g["id"]
        has_config = False
        if cfg_col is not None:
            # FIX: count_documents là blocking I/O — chạy trong executor
            try:
                has_config = await loop.run_in_executor(
                    None,
                    lambda _gid=gid: cfg_col.count_documents({"guild_id": _gid}, limit=1) > 0
                )
            except Exception as _e:
                import traceback as _tb
                print(f"[api_guilds] Lỗi count_documents guild {gid}: {_e}")
                print(_tb.format_exc())

        if not has_config and gid not in _shared.get("guilds", {}):
            continue

        perms      = int(g.get("permissions", 0))
        is_manager = bool(perms & 0x20) or g.get("owner", False)
        icon       = g.get("icon")
        result.append({
            "id":         gid,
            "name":       g["name"],
            "icon":       f"https://cdn.discordapp.com/icons/{gid}/{icon}.png" if icon else None,
            "is_manager": is_manager,
        })
    return JSONResponse(result)


# ─────────────────────────────────────────────────────────────────
# [6] THÊM import asyncio ở đầu dashboard_routes.py (nếu chưa có)
# ─────────────────────────────────────────────────────────────────
# Thêm vào khối import ở đầu file:
import asyncio
