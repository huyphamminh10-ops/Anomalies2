# ==============================
# bot_main.py — Anomalies v2.5 (Integrated Architecture)
# Entry point duy nhất: Bot khởi động và kéo FastAPI Web Dashboard theo.
#
# Kiến trúc tích hợp:
#   - uvicorn chạy FastAPI trên port $PORT (cho Render web service)
#   - Bot Disnake được khởi động bên trong lifespan của FastAPI
#   - Bot và Web dùng chung event loop → bot.guilds luôn có sẵn cho Web
#   - app.state.bot được gán để Web truy cập trực tiếp
#   - config_manager dùng chung giữa Bot và Web
#   - database_tidb dùng cho Feedback & Update Log (TiDB)
#
# Cách chạy:
#   python bot_main.py            ← Render startCommand
#   PORT=8000 python bot_main.py  ← local dev
#
# Biến môi trường cần thiết:
#   DISCORD_TOKEN, MONGO_URI, TIDB_URL (optional), BOT_OWNER_ID
#   DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI
#   SESSION_SECRET
# ==============================

from __future__ import annotations

import asyncio
import os
import sys
import glob
import importlib
import traceback

# ── Đảm bảo thư mục gốc dự án trong sys.path ──────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import disnake
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
from typing import AsyncIterator

import config_manager
import database_tidb

# ── Tải dashboard server (Web Dashboard) ──────────────────────────
# dashboard/server.py chứa tất cả các route Web
_DASH_DIR = os.path.join(_HERE, "dashboard")
if _DASH_DIR not in sys.path:
    sys.path.insert(0, _DASH_DIR)

# ── Config ────────────────────────────────────────────────────────
TOKEN        = os.environ.get("DISCORD_TOKEN", "")
PORT         = int(os.environ.get("PORT", 8000))
BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "1306441206296875099"))

if not TOKEN:
    print("[bot_main] CẢNH BÁO: DISCORD_TOKEN chưa được đặt!")

# ── Bot setup ─────────────────────────────────────────────────────
intents = disnake.Intents.default()
intents.members         = True
intents.message_content = True

bot = disnake.AutoShardedInteractionBot(intents=intents)


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

    # Khởi tạo MongoDB indexes (chạy trong thread để không block event loop)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, config_manager.ensure_indexes)
    print("[bot] MongoDB indexes OK.")

    # Khởi tạo TiDB tables (chạy trong thread)
    result = await loop.run_in_executor(None, database_tidb.ensure_tables)
    if result["ok"]:
        print("[bot] TiDB tables OK.")
    else:
        print(f"[bot] TiDB tables lỗi: {result.get('error')} — {result.get('hint')}")


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
    Trả về (app, True) hoặc (None, False) nếu import thất bại.
    """
    try:
        # Import module dashboard.server
        spec   = importlib.util.spec_from_file_location(
            "dashboard.server",
            os.path.join(_DASH_DIR, "server.py"),
        )
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules["dashboard.server"] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        dash_app: FastAPI = module.app

        # ── QUAN TRỌNG: Gán bot vào app.state.bot ────────────────
        # Web Dashboard truy cập bot.guilds qua app.state.bot
        # Thay vì tạo bot riêng trong server.py, Web dùng bot thật này.
        dash_app.state.bot = bot

        # Gán thêm vào module để server.py có thể dùng nếu cần
        module.bot = bot

        print("[bot_main] ✓ dashboard/server.py imported, app.state.bot đã được gán.")
        return dash_app, module
    except Exception as e:
        print(f"[bot_main] ✗ Không import được dashboard/server.py: {e}")
        traceback.print_exc()
        return None, None


# ── Tạo wrapper FastAPI app tích hợp ─────────────────────────────

@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Lifespan chính: khởi động Bot + Dashboard cùng event loop.
    Bot chạy qua create_task → Web có thể truy cập bot.guilds ngay.
    """
    # Gán bot vào state trước khi yield (để middleware và route truy cập ngay)
    app.state.bot = bot

    # Load cogs
    _load_cogs()

    # Khởi động bot
    if not TOKEN:
        print("[bot_main] DISCORD_TOKEN trống — bot không kết nối Discord.")
        bot_task = None
    else:
        bot_task = asyncio.create_task(bot.start(TOKEN), name="discord-bot")
        print("[bot_main] Bot đang kết nối Discord...")

    try:
        yield  # Web server chạy tại đây
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
        print("[bot_main] Bot đã đóng kết nối.")


# ── Build app tổng hợp ────────────────────────────────────────────

def _build_app() -> FastAPI:
    """
    Import dashboard app và wrap lại với lifespan tích hợp Bot.
    Mọi route từ dashboard/server.py đều được giữ nguyên.
    """
    dash_app, dash_module = _import_dashboard_app()

    if dash_app is None:
        # Fallback: tạo app đơn giản nếu dashboard không import được
        print("[bot_main] Chạy với minimal app (không có dashboard routes).")
        minimal_app = FastAPI(title="Anomalies Bot", lifespan=_lifespan)

        @minimal_app.get("/health")
        async def health():
            return {
                "status": "ok",
                "bot_ready": bot.user is not None,
                "guild_count": len(bot.guilds),
            }

        return minimal_app

    # ── Thay lifespan của dashboard app bằng lifespan tích hợp ───
    # FastAPI không cho thay lifespan sau khi tạo, nên ta tạo wrapper app mới
    # rồi mount toàn bộ routes từ dash_app vào đó.

    main_app = FastAPI(
        title="Anomalies Dashboard + Bot",
        version="2.5.0",
        lifespan=_lifespan,
    )

    # Copy tất cả routes từ dash_app (bỏ qua openapi/docs routes mặc định)
    for route in dash_app.routes:
        main_app.routes.append(route)

    # Copy middleware nếu có
    main_app.middleware_stack = None  # reset để build lại sau khi thêm routes

    # Gán state bot cho cả hai app
    main_app.state.bot = bot
    dash_app.state.bot = bot

    # Truyền shared state vào dashboard_routes nếu có
    try:
        from dashboard_routes import init_shared  # type: ignore

        async def _init_routes_after_ready():
            """Chờ bot ready rồi mới truyền shared state sang routes."""
            await bot.wait_until_ready()
            import config_manager as _cm

            def _col(name: str):
                db = _cm._get_db()
                return db[name] if db is not None else None

            init_shared(
                bot=bot,
                guilds={},
                active_games={},
                game_stats={},
                col_fn=_col,
            )
            print("[bot_main] dashboard_routes đã nhận shared state.")

        # Task này sẽ chạy sau khi event loop bắt đầu
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
        # Không dùng reload=True trên production
    )


if __name__ == "__main__":
    main()
