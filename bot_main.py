# ==============================
# bot_main.py — Anomalies v2.5 (Fixed for Render)
#
# FIX v2.5:
#   - SSL: aiohttp.TCPConnector nhận ssl.SSLContext (qua certifi) thay vì ssl=False
#   - MongoDB: ensure_indexes() chạy trong executor với log traceback đầy đủ
#   - Dashboard guilds: chờ bot.is_ready() trước khi truyền shared state
#   - Thêm /health endpoint check MongoDB + bot status
#
# Biến môi trường cần thiết:
#   DISCORD_TOKEN, MONGO_URI, TIDB_URL (optional), BOT_OWNER_ID
#   DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI
#   SESSION_SECRET
# ==============================

from __future__ import annotations
import os as _os, sys as _sys
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
for _candidate in [_BASE_DIR, _os.path.dirname(_BASE_DIR)]:
    _core = _os.path.join(_candidate, "core")
    if _os.path.isdir(_core) and _core not in _sys.path:
        _sys.path.insert(0, _core)
del _os, _sys, _BASE_DIR, _candidate, _core


import asyncio
import os
import ssl
import sys
import glob
import importlib
import traceback

# ── Đảm bảo thư mục gốc dự án trong sys.path ──────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import certifi
import aiohttp
import disnake
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from typing import AsyncIterator

import config_manager
import database_tidb

# ── Tải dashboard server (Web Dashboard) ──────────────────────────
_DASH_DIR = os.path.join(_HERE, "dashboard")
if _DASH_DIR not in sys.path:
    sys.path.insert(0, _DASH_DIR)

# ── Config ────────────────────────────────────────────────────────
TOKEN        = os.environ.get("DISCORD_TOKEN", "")
PORT         = int(os.environ.get("PORT", 8000))
BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "1306441206296875099"))

if not TOKEN:
    print("[bot_main] CẢNH BÁO: DISCORD_TOKEN chưa được đặt!")


# ── FIX SSL: Tạo SSLContext đúng chuẩn dùng certifi ──────────────
# aiohttp >= 3.9 KHÔNG chấp nhận ssl=<string path>.
# Phải truyền ssl=ssl.SSLContext hoặc ssl=True/False.
# Dùng certifi.where() làm CA bundle để verify cert Discord/MongoDB.
def _make_ssl_context() -> ssl.SSLContext:
    """Tạo SSLContext với certifi CA bundle — tương thích aiohttp 3.9+."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    return ctx


# ── Bot setup ─────────────────────────────────────────────────────
intents = disnake.Intents.default()
intents.members         = True
intents.message_content = True

# FIX: Tạo TCPConnector với ssl=SSLContext thay vì ssl=False.
# ssl=False tắt hoàn toàn SSL verification — không an toàn và gây lỗi trên Render.
# ssl=_make_ssl_context() giữ nguyên mã hóa TLS và verify cert qua certifi.
_ssl_ctx   = _make_ssl_context()
_connector = aiohttp.TCPConnector(ssl=_ssl_ctx)

bot = disnake.AutoShardedInteractionBot(
    intents=intents,
    connector=_connector,
)


# ── Load cogs từ thư mục cogs/ ────────────────────────────────────

def _load_cogs() -> None:
    """Load tất cả cogs trong thư mục cogs/. Bỏ qua cog lỗi để bot vẫn chạy."""
    cog_dir = os.path.join(_HERE, "cogs")
    if not os.path.isdir(cog_dir):
        print("[bot_main] Không tìm thấy thư mục cogs/ — bỏ qua.")
        return
    for path in sorted(glob.glob(os.path.join(cog_dir, "*.py"))):
        name = os.path.basename(path)[:-3]
        if name.startswith("_"):
            continue
        module_name = f"cogs.{name}"
        try:
            bot.load_extension(module_name)
            print(f"[bot_main] ✓ Loaded cog: {module_name}")
        except Exception as e:
            print(f"[bot_main] ✗ Lỗi load cog {module_name}: {e}")
            traceback.print_exc()


# ── Bot events ────────────────────────────────────────────────────

@bot.event
async def on_ready() -> None:
    print(f"[bot] ✓ Logged in as {bot.user} (id={bot.user.id})")
    print(f"[bot] Đang quản lý {len(bot.guilds)} server(s).")

    # FIX: Chạy ensure_indexes() trong executor để không block event loop.
    # Thêm try/except + traceback để log lỗi chi tiết nếu MongoDB từ chối kết nối.
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, config_manager.ensure_indexes)
        print("[bot] ✓ MongoDB indexes OK.")
    except Exception as e:
        print(f"[bot] ✗ ensure_indexes thất bại:")
        print(f"  Lỗi: {e}")
        print(f"  Chi tiết:\n{traceback.format_exc()}")
        print("  → Kiểm tra MONGO_URI và Atlas Network Access (IP Whitelist: 0.0.0.0/0).")

    # Khởi tạo TiDB tables (chạy trong thread)
    try:
        result = await loop.run_in_executor(None, database_tidb.ensure_tables)
        if result["ok"]:
            print("[bot] ✓ TiDB tables OK.")
        else:
            print(f"[bot] ✗ TiDB tables lỗi: {result.get('error')} — {result.get('hint')}")
    except Exception as e:
        print(f"[bot] ✗ TiDB ensure_tables thất bại: {e}")
        print(traceback.format_exc())


@bot.event
async def on_guild_join(guild: disnake.Guild) -> None:
    print(f"[bot] Tham gia server: {guild.name} (id={guild.id})")


@bot.event
async def on_guild_remove(guild: disnake.Guild) -> None:
    print(f"[bot] Rời server: {guild.name} (id={guild.id})")


# ── Import FastAPI app từ dashboard/server.py ─────────────────────

def _import_dashboard_app():
    """
    Import FastAPI app từ dashboard/server.py và gán app.state.bot.
    Trả về (app, module) hoặc (None, None) nếu import thất bại.
    """
    try:
        spec   = importlib.util.spec_from_file_location(
            "dashboard.server",
            os.path.join(_DASH_DIR, "server.py"),
        )
        module = importlib.util.module_from_spec(spec)   # type: ignore[arg-type]
        sys.modules["dashboard.server"] = module
        spec.loader.exec_module(module)                  # type: ignore[union-attr]

        dash_app: FastAPI = module.app
        dash_app.state.bot = bot
        module.bot = bot

        print("[bot_main] ✓ dashboard/server.py imported, app.state.bot đã được gán.")
        return dash_app, module
    except Exception as e:
        print(f"[bot_main] ✗ Không import được dashboard/server.py: {e}")
        traceback.print_exc()
        return None, None


# ── Lifespan ──────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Lifespan chính: khởi động Bot + Dashboard cùng event loop.

    FIX v2.5:
    - Bot task chạy qua create_task → Web truy cập bot.guilds trực tiếp
    - init_shared() chờ bot.is_ready() để đảm bảo guilds đã load xong
    """
    app.state.bot = bot
    _load_cogs()

    if not TOKEN:
        print("[bot_main] DISCORD_TOKEN trống — bot không kết nối Discord.")
        bot_task = None
    else:
        bot_task = asyncio.create_task(bot.start(TOKEN), name="discord-bot")
        print("[bot_main] Bot đang kết nối Discord...")

    try:
        yield
    finally:
        print("[bot_main] Đang tắt...")
        if bot_task is not None:
            bot_task.cancel()
            try:
                await bot_task
            except (asyncio.CancelledError, Exception):
                pass
        if not bot.is_closed():
            await bot.close()
        # Đóng aiohttp connector sạch sẽ
        if not _connector.closed:
            await _connector.close()
        print("[bot_main] Bot đã đóng kết nối.")


# ── Build app tổng hợp ────────────────────────────────────────────

def _build_app() -> FastAPI:
    """
    Import dashboard app và wrap lại với lifespan tích hợp Bot.
    Mọi route từ dashboard/server.py đều được giữ nguyên.
    """
    dash_app, dash_module = _import_dashboard_app()

    if dash_app is None:
        print("[bot_main] Chạy với minimal app (không có dashboard routes).")
        minimal_app = FastAPI(title="Anomalies Bot", lifespan=_lifespan)

        @minimal_app.get("/health")
        async def health():
            db_ok = False
            try:
                db = config_manager._get_db()
                db_ok = db is not None
            except Exception:
                pass
            return JSONResponse({
                "status":      "ok",
                "bot_ready":   bot.is_ready(),
                "guild_count": len(bot.guilds),
                "db_ok":       db_ok,
            })

        @minimal_app.get("/ping")
        async def ping():
            return {"pong": True}

        return minimal_app

    main_app = FastAPI(
        title="Anomalies Dashboard + Bot",
        version="2.5.0",
        lifespan=_lifespan,
    )

    for route in dash_app.routes:
        main_app.routes.append(route)

    main_app.middleware_stack = None  # reset để build lại sau khi thêm routes
    main_app.state.bot = bot
    dash_app.state.bot = bot

    # ── /health endpoint để UptimeRobot keep-alive + debug ────────
    @main_app.get("/health")
    async def health():
        db_ok = False
        try:
            db = config_manager._get_db()
            db_ok = db is not None
        except Exception:
            pass
        return JSONResponse({
            "status":      "ok",
            "bot_ready":   bot.is_ready(),
            "guild_count": len(bot.guilds),
            "db_ok":       db_ok,
        })

    @main_app.get("/ping")
    async def ping():
        return {"pong": True}

    # FIX: init_shared() phải chờ bot.is_ready() trước khi truyền shared state.
    # Nếu gọi ngay lúc startup, bot.guilds còn rỗng → Dashboard không thấy guild nào.
    try:
        from dashboard_routes import init_shared  # type: ignore

        async def _init_routes_after_ready():
            """Chờ bot ready (guilds đã load) rồi mới truyền shared state sang routes."""
            print("[bot_main] Đang chờ bot.wait_until_ready()...")
            await bot.wait_until_ready()
            print(f"[bot_main] Bot ready — {len(bot.guilds)} guild(s) đang quản lý.")

            import config_manager as _cm

            def _col(name: str):
                try:
                    db = _cm._get_db()
                    return db[name] if db is not None else None
                except Exception as e:
                    print(f"[bot_main] _col('{name}') lỗi: {e}")
                    return None

            init_shared(
                bot=bot,
                guilds={},          # app.py dùng dict nội bộ; bot_main dùng bot.guilds trực tiếp
                active_games={},
                game_stats={},
                col_fn=_col,
            )
            print("[bot_main] ✓ dashboard_routes đã nhận shared state.")

        @main_app.on_event("startup")
        async def _startup_init():
            asyncio.create_task(_init_routes_after_ready(), name="init-routes")

    except ImportError:
        print("[bot_main] dashboard_routes.py không có — bỏ qua init_shared.")

    return main_app


# ── Entry point ───────────────────────────────────────────────────

def main() -> None:
    """
    Điểm vào chính của toàn bộ dự án.
    Bot và Web Dashboard chạy cùng một tiến trình, cùng một event loop.

    render.yaml startCommand: python bot_main.py
    """
    app = _build_app()

    print(f"[bot_main] Khởi động trên port {PORT}...")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
