# ══════════════════════════════════════════════════════════════════
# updater.py — Anomalies v2.3 (Fixed for Hugging Face)
#
# FIX v2.3:
#   - Bỏ _clear_session() — không còn dùng file-based singleton
#   - Detect HF qua SPACE_ID → dùng os._exit(0) thay vì os.execv()
#   - os._exit(0) an toàn hơn sys.exit() trên HF (không trigger atexit,
#     không raise SystemExit, HF tự restart Space)
#   - register_emergency_callback(): callback từ app.py hủy trận TRƯỚC countdown
#   - run_update_sequence(): emergency cleanup → save pending → warning 30s → shutdown → exit
#   - _claim_pending(): atomic rename — không gửi thông báo 2 lần
#   - ujson cho mọi I/O file
# ══════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Optional, Callable, Awaitable

try:
    import ujson as json
except ImportError:
    import json  # type: ignore

import disnake
from disnake.ext import commands

BOT_OWNER_ID = 1306441206296875099

_BASE_DIR           = os.path.dirname(os.path.abspath(__file__))
UPDATE_PENDING_FILE = os.path.join(_BASE_DIR, "update_pending.json")
UPDATE_SENDING_FILE = os.path.join(_BASE_DIR, "update_sending.json")

# FIX: Không còn dùng BOT_SESSION_FILE — singleton đã chuyển sang thread-level
# BOT_SESSION_FILE    = os.path.join(_BASE_DIR, "bot_session.json")  # ĐÃ XÓA

# Detect Hugging Face
_IS_HUGGING_FACE = bool(os.environ.get("SPACE_ID"))

_owner_state: dict = {
    "step":    None,
    "content": "",
}

# Callback để hủy trận khẩn cấp — đăng ký từ app.py
_emergency_callback: Optional[Callable[[str], Awaitable[None]]] = None


def register_emergency_callback(fn: Callable[[str], Awaitable[None]]):
    """
    Đăng ký hàm callback từ app.py.
    updater.py gọi hàm này TRƯỚC khi đếm ngược để hủy các trận đang diễn ra.
    """
    global _emergency_callback
    _emergency_callback = fn
    print("[Updater] Emergency callback đã đăng ký.")


# ══════════════════════════════════════════════════════════════════
# HELPERS — PENDING FILE (atomic, ujson)
# ══════════════════════════════════════════════════════════════════

def _save_pending(content: str):
    data     = {"content": content, "timestamp": time.time()}
    tmp_path = UPDATE_PENDING_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, UPDATE_PENDING_FILE)


def _claim_pending() -> Optional[str]:
    """
    Atomic rename pending → sending.
    Chỉ một instance duy nhất claim được file → không gửi 2 lần.
    """
    if not os.path.exists(UPDATE_PENDING_FILE):
        return None
    try:
        os.replace(UPDATE_PENDING_FILE, UPDATE_SENDING_FILE)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[Updater] _claim_pending lỗi: {e}")
        return None
    try:
        with open(UPDATE_SENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("content")
    except Exception:
        return None


def _clear_sending():
    try:
        if os.path.exists(UPDATE_SENDING_FILE):
            os.remove(UPDATE_SENDING_FILE)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# FIX: Restart an toàn cho Hugging Face
#
# Trên HF: os._exit(0) → HF tự nhận biết process kết thúc → restart Space
# Local:   os.execv() → thay thế process hiện tại bằng instance mới
#
# TẠI SAO dùng os._exit(0) thay vì sys.exit()?
# - sys.exit() raise SystemExit exception → có thể bị catch → không thoát
# - sys.exit() trigger atexit handlers → có thể gây lỗi phụ
# - os._exit(0) thoát ngay lập tức, sạch, không raise exception
# - HF Space nhận exit code 0 → coi là "thoát bình thường" → restart
# ══════════════════════════════════════════════════════════════════

def _build_execv_args() -> tuple[str, list[str]]:
    """
    Trả về (python_executable, argv_list) để dùng với os.execv().
    Chỉ dùng khi chạy local (không phải HF).
    """
    python_exe = sys.executable or "/usr/bin/python3"

    # Ưu tiên: app.py trong cùng thư mục với updater.py
    candidate = os.path.join(_BASE_DIR, "app.py")
    if os.path.exists(candidate):
        return python_exe, [python_exe, candidate]

    # Fallback: sys.argv[0] nếu là file hợp lệ
    if sys.argv:
        argv0 = sys.argv[0]
        if not os.path.isabs(argv0):
            argv0 = os.path.join(os.getcwd(), argv0)
        if os.path.isfile(argv0):
            return python_exe, [python_exe, argv0] + sys.argv[1:]

    return python_exe, [python_exe, candidate]


# ══════════════════════════════════════════════════════════════════
# EMBED BUILDERS
# ══════════════════════════════════════════════════════════════════

def _build_update_embed(content: str) -> disnake.Embed:
    return disnake.Embed(
        title="🔄 CẬP NHẬT MỚI ĐÃ HOÀN TẤT",
        description=(
            "Cảm ơn bạn đã kiên nhẫn 🙏\n\n"
            "───────────────────────────────\n"
            f"{content}\n"
            "───────────────────────────────\n\n"
            "Bây giờ bạn đã có thể tiếp tục!\n"
            "**Sau 20 giây, bảng này sẽ tự xóa.**"
        ),
        color=0x2ecc71,
    ).set_footer(text="Have a nice day 🍀🍀")


def _build_warning_embed(seconds_left: int) -> disnake.Embed:
    return disnake.Embed(
        title="📢 CẢNH BÁO ⚠️",
        description=(
            "**Dev chuẩn bị Update mới**\n\n"
            f"Trong **{seconds_left} giây**, bot sẽ dừng trò chơi "
            "và trả lại vai trò cho mọi người.\n"
            "Sau đó bot sẽ được kích hoạt lại.\n\n"
            "🍀 **Chúc Một Ngày Tốt Lành** 😁\n\n"
            f"⏱️ Thời gian còn lại: **{seconds_left} giây**"
        ),
        color=0xe67e22,
    )


def _build_preview_embed(content: str) -> disnake.Embed:
    return disnake.Embed(
        title="👀 PREVIEW EMBED CẬP NHẬT",
        description=(
            "───────────────────────────────\n"
            f"{content}\n"
            "───────────────────────────────\n\n"
            "*Nhắn **Chấp nhận** để phát hoặc **Sửa lại** để làm lại.*"
        ),
        color=0x3498db,
    )


# ══════════════════════════════════════════════════════════════════
# CORE UPDATE SEQUENCE
# Thứ tự:
#   BƯỚC 0: Emergency cleanup (hủy trận, thu hồi Role) TRƯỚC countdown
#   BƯỚC 1: Lưu pending content (atomic)
#   BƯỚC 2: Gửi warning + đếm ngược 30s
#   BƯỚC 3: Graceful shutdown
#   BƯỚC 4 (FIX): os._exit(0) trên HF | os.execv() trên local
# ══════════════════════════════════════════════════════════════════

async def run_update_sequence(bot: commands.Bot, content: str):
    # ── BƯỚC 0: Hủy trận TRƯỚC khi đếm ngược ───────────────────
    if _emergency_callback is not None:
        print("[Updater] BƯỚC 0: Emergency cleanup — hủy tất cả trận...")
        try:
            await asyncio.wait_for(
                _emergency_callback("Chuẩn bị cập nhật — Bot restart trong 30 giây"),
                timeout=15.0
            )
            print("[Updater] BƯỚC 0: Emergency cleanup hoàn thành.")
        except asyncio.TimeoutError:
            print("[Updater] BƯỚC 0: Timeout — tiếp tục countdown.")
        except Exception as e:
            print(f"[Updater] BƯỚC 0: Lỗi: {e}")
    else:
        print("[Updater] BƯỚC 0: Không có emergency callback — bỏ qua.")

    # ── BƯỚC 1: Lưu pending ──────────────────────────────────────
    _save_pending(content)

    # ── BƯỚC 2: Gửi warning + đếm ngược 30s ─────────────────────
    from config_manager import load_all_configs
    all_configs  = load_all_configs()
    warning_msgs: list[tuple] = []

    for guild_id, cfg in all_configs.items():
        tc_id = cfg.get("text_channel_id")
        if not tc_id:
            continue
        ch = bot.get_channel(tc_id)
        if not ch:
            continue
        try:
            msg = await ch.send(embed=_build_warning_embed(30))
            warning_msgs.append((ch, msg))
        except Exception as e:
            print(f"[Updater] Gửi warning tới {guild_id} thất bại: {e}")

    for elapsed in range(30):
        await asyncio.sleep(1)
        remaining = 30 - elapsed - 1
        if remaining % 5 == 0 or remaining <= 5:
            new_embed = _build_warning_embed(remaining if remaining > 0 else 0)
            for ch, msg in warning_msgs:
                try:
                    await msg.edit(embed=new_embed)
                except Exception:
                    pass

    await asyncio.sleep(1)

    # ── BƯỚC 3: Graceful shutdown ────────────────────────────────
    bot_mod = sys.modules.get("app") or sys.modules.get("__main__")
    if bot_mod and hasattr(bot_mod, "graceful_shutdown"):
        try:
            await asyncio.wait_for(
                bot_mod.graceful_shutdown("updater restart"),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            print("[Updater] graceful_shutdown timeout — tiếp tục exit.")
        except Exception as e:
            print(f"[Updater] graceful_shutdown lỗi: {e}")

    # ── BƯỚC 4 (FIX): Thoát an toàn, tương thích HF ─────────────
    # FIX: Không còn _clear_session() vì không dùng file-based singleton nữa
    #
    # Trên Hugging Face:
    #   os._exit(0) → process thoát sạch → HF tự restart Space
    #   Bot thread mới sẽ acquire _BOT_STARTED từ đầu (module reload)
    #
    # Local:
    #   os.execv() → thay thế process hiện tại bằng instance mới
    if _IS_HUGGING_FACE:
        print("[Updater] BƯỚC 4: Môi trường HF — os._exit(0) để HF tự restart.")
        os._exit(0)
    else:
        python_exe, argv = _build_execv_args()
        print(f"[Updater] BƯỚC 4: Restart local via os.execv({python_exe}, {argv})")
        try:
            os.execv(python_exe, argv)
        except Exception as e:
            print(f"[Updater] os.execv thất bại: {e} — fallback os._exit(0).")
            os._exit(0)


# ══════════════════════════════════════════════════════════════════
# POST-RESTART — gửi embed update (atomic, không gửi 2 lần)
# ══════════════════════════════════════════════════════════════════

async def send_post_update_embeds(bot: commands.Bot):
    """
    Gọi trong on_ready sau restart.
    _claim_pending() là atomic rename → chỉ một instance xử lý file → không gửi 2 lần.
    """
    content = _claim_pending()
    if not content:
        return

    from config_manager import load_all_configs
    all_configs = load_all_configs()

    print(f"[Updater] Phát hiện update pending — gửi embed đến {len(all_configs)} server")

    bot_mod = sys.modules.get("app") or sys.modules.get("__main__")

    for guild_id, cfg in all_configs.items():
        tc_id = cfg.get("text_channel_id")
        if not tc_id:
            continue

        ch = bot.get_channel(tc_id)
        if not ch:
            try:
                ch = await bot.fetch_channel(tc_id)
            except Exception:
                continue

        lobby_msg_id: int | None = None
        if bot_mod and hasattr(bot_mod, "get_guild_state"):
            try:
                gs           = bot_mod.get_guild_state(guild_id)
                lobby_msg    = gs.get("lobby_message")
                lobby_msg_id = lobby_msg.id if lobby_msg else None
            except Exception:
                pass

        if lobby_msg_id is None:
            try:
                from config_manager import load_guild_lobby
                saved        = load_guild_lobby(guild_id)
                lobby_msg_id = saved.get("message_id") if saved else None
            except Exception:
                pass

        try:
            if lobby_msg_id:
                deleted = await ch.purge(
                    limit=50,
                    check=lambda msg, _id=lobby_msg_id: msg.id != _id,
                    bulk=True,
                )
                print(f"  [{guild_id}] Purge: xóa {len(deleted)} tin (giữ lobby {lobby_msg_id}).")
            else:
                print(f"  [{guild_id}] Không có lobby_msg_id → bỏ qua purge.")
        except Exception as e:
            print(f"  [{guild_id}] Purge lỗi: {e}")

        try:
            msg = await ch.send(embed=_build_update_embed(content))
            await asyncio.sleep(20)
            try:
                await msg.delete()
            except Exception:
                pass
        except Exception as e:
            print(f"[Updater] Gửi embed tới {guild_id} thất bại: {e}")

    _clear_sending()
    print("[Updater] Đã gửi embed update và xóa file sending.")


# ══════════════════════════════════════════════════════════════════
# DM CONVERSATION HANDLER
# ══════════════════════════════════════════════════════════════════

async def handle_owner_dm(bot: commands.Bot, message: disnake.Message) -> bool:
    if message.author.id != BOT_OWNER_ID:
        return False
    if message.guild is not None:
        return False

    text = message.content.strip()

    if text == "Có cập nhật":
        if _owner_state["step"] == "waiting_confirm":
            await message.channel.send("⚠️ Bạn đang ở bước xác nhận. Nhắn **Chấp nhận** hoặc **Sửa lại**.")
            return True
        _owner_state["step"]    = "waiting_content"
        _owner_state["content"] = ""
        await message.channel.send(
            "📝 **Nhập nội dung update.**\nKhi xong, nhắn **Xong rồi**."
        )
        return True

    if _owner_state["step"] == "waiting_content":
        if text == "Xong rồi":
            if not _owner_state["content"].strip():
                await message.channel.send("⚠️ Chưa có nội dung. Nhập trước rồi mới nhắn **Xong rồi**.")
                return True
            _owner_state["step"] = "waiting_confirm"
            await message.channel.send(embed=_build_preview_embed(_owner_state["content"]))
            await message.channel.send("Nhắn **Chấp nhận** hoặc **Sửa lại**.")
            return True
        else:
            sep = "\n" if _owner_state["content"] else ""
            _owner_state["content"] += sep + text
            await message.add_reaction("✅")
            return True

    if _owner_state["step"] == "waiting_confirm":
        if text == "Chấp nhận":
            content = _owner_state["content"]
            _owner_state["step"]    = None
            _owner_state["content"] = ""
            await message.channel.send("🚀 **Đã xác nhận!** Bot đếm ngược 30 giây và restart.")
            asyncio.create_task(run_update_sequence(bot, content))
            return True

        if text == "Sửa lại":
            _owner_state["step"]    = "waiting_content"
            _owner_state["content"] = ""
            await message.channel.send("🔄 Nhập lại nội dung. Khi xong nhắn **Xong rồi**.")
            return True

    return False


# ══════════════════════════════════════════════════════════════════
# OWNER GREETING
# ══════════════════════════════════════════════════════════════════

async def greet_owner_on_setup(bot: commands.Bot):
    """Gửi hướng dẫn update vào DM của owner khi bot sẵn sàng."""
    try:
        owner = await bot.fetch_user(BOT_OWNER_ID)
        if owner:
            await owner.send(
                "👋 **Hướng dẫn Update Bot:**\n\n"
                "1. Nhắn **Có cập nhật** vào đây.\n"
                "2. Nhập nội dung cập nhật (nhiều dòng).\n"
                "3. Nhắn **Xong rồi** khi hoàn tất.\n"
                "4. Xem preview → nhắn **Chấp nhận** hoặc **Sửa lại**.\n"
                "5. Bot hủy tất cả trận, đếm ngược 30s và restart.\n\n"
                "📌 Sau khi restart, bot tự gửi embed thông báo đến tất cả server."
            )
    except disnake.Forbidden:
        pass
    except Exception as e:
        print(f"[Updater] greet_owner_on_setup lỗi: {e}")
