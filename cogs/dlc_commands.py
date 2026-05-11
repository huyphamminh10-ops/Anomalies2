# ══════════════════════════════════════════════════════════════════
# cogs/dlc_commands.py — Lệnh DLC cho Anomalies Bot
#
# Lệnh:
#   /mods   → DM người dùng để nhập mã serial
#   /wallet → Xem số dư Gold & Gems
#
# DOELCES v1.0
# ══════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
import disnake
from disnake.ext import commands

# ── Import core modules ────────────────────────────────────────────
try:
    from core.dlc_economy import (
        redeem_serial,
        get_player_wallet,
        get_player_dlcs,
        validate_serial_format,
    )
    from core.dlc_loader import get_all_dlcs_summary, get_dlc_by_folder
    _ECONOMY_OK = True
except ImportError:
    _ECONOMY_OK = False


class DLCCommands(commands.Cog):
    """Cog xử lý lệnh DLC / Mods."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ──────────────────────────────────────────────────────────────
    # /mods — Nhập mã serial kích hoạt
    # ──────────────────────────────────────────────────────────────

    @commands.slash_command(
        name="mods",
        description="Nhập mã Serial để kích hoạt Mod DLC",
    )
    async def mods_command(self, inter: disnake.ApplicationCommandInteraction):
        """
        Quy trình:
        1. Bot DM người dùng hỏi mã serial
        2. Chờ người dùng trả lời trong DM (timeout 90s)
        3. Validate + redeem serial
        4. Trả kết quả
        """
        await inter.response.send_message(
            "📬 Tôi đã gửi tin nhắn riêng cho bạn! Hãy kiểm tra DM.",
            ephemeral=True
        )

        try:
            dm_channel = await inter.author.create_dm()
        except disnake.Forbidden:
            await inter.edit_original_response(
                content="❌ Không thể gửi DM cho bạn. Hãy bật DM từ server này trong cài đặt Discord."
            )
            return

        # Gửi embed hỏi mã
        ask_embed = disnake.Embed(
            title="🔑 Kích Hoạt Mod DLC",
            description=(
                "Vui lòng nhập **Mã Serial** của Mod bạn muốn kích hoạt.\n\n"
                "**Định dạng:**\n"
                "```\n<TÊN_MOD>:<KEY_25_KÝ_TỰ>\n```\n"
                "**Ví dụ:**\n"
                "```\nTOIKObidien:59c19yu0%951b@@5odv0#i%t\n```\n"
                "⏰ Bạn có **90 giây** để nhập mã."
            ),
            color=0x5865F2,
        )
        ask_embed.set_footer(text="Mã Serial của Mod?")
        await dm_channel.send(embed=ask_embed)

        # Chờ phản hồi trong DM
        def check(m: disnake.Message):
            return m.author.id == inter.author.id and m.channel.id == dm_channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=90.0)
        except asyncio.TimeoutError:
            timeout_embed = disnake.Embed(
                title="⏰ Hết Thời Gian",
                description="Bạn không nhập mã trong 90 giây. Hãy dùng `/mods` lại.",
                color=0xFF4444,
            )
            await dm_channel.send(embed=timeout_embed)
            return

        serial_str = msg.content.strip()

        # Gửi thông báo đang xử lý
        processing_embed = disnake.Embed(
            title="⏳ Đang xử lý...",
            description=f"Đang kiểm tra mã `{serial_str[:40]}{'...' if len(serial_str) > 40 else ''}`",
            color=0xFAA61A,
        )
        proc_msg = await dm_channel.send(embed=processing_embed)

        # Xử lý redeem
        if not _ECONOMY_OK:
            result = {"ok": False, "message": "❌ Hệ thống DLC chưa được khởi tạo.", "mod_name": None}
        else:
            result = redeem_serial(str(inter.author.id), serial_str)

        # Trả kết quả
        mod_name = result.get("mod_name") or "Unknown"
        if result["ok"]:
            result_embed = disnake.Embed(
                title="✅ Kích Hoạt Thành Công!",
                description=result["message"],
                color=0x57F287,
            )
            result_embed.add_field(
                name="📦 Mod đã kích hoạt",
                value=f"`{mod_name}`",
                inline=True,
            )
            result_embed.set_footer(text="Dùng /settings để bật Mod trong server của bạn")
        else:
            result_embed = disnake.Embed(
                title="❌ Kích Hoạt Thất Bại",
                description=result["message"],
                color=0xFF4444,
            )

        await proc_msg.edit(embed=result_embed)

    # ──────────────────────────────────────────────────────────────
    # /wallet — Xem số dư
    # ──────────────────────────────────────────────────────────────

    @commands.slash_command(
        name="wallet",
        description="Xem số dư Gold và Gems của bạn",
    )
    async def wallet_command(self, inter: disnake.ApplicationCommandInteraction):
        await inter.response.defer(ephemeral=True)

        if not _ECONOMY_OK:
            await inter.edit_original_response(content="❌ Hệ thống kinh tế chưa sẵn sàng.")
            return

        user_id = str(inter.author.id)
        wallet  = get_player_wallet(user_id)
        owned   = get_player_dlcs(user_id)

        embed = disnake.Embed(
            title=f"💰 Ví của {inter.author.display_name}",
            color=0xF1C40F,
        )
        embed.add_field(name="🪙 Gold",  value=f"`{wallet['gold']:,}`",       inline=True)
        embed.add_field(name="💎 Gems",  value=f"`{wallet['gems']:,}`",       inline=True)
        embed.add_field(name="🎮 Trận",  value=f"`{wallet['total_games']:,}`", inline=True)

        if owned:
            embed.add_field(
                name=f"📦 Mods đã sở hữu ({len(owned)})",
                value="\n".join(f"• `{m}`" for m in owned),
                inline=False,
            )
        else:
            embed.add_field(name="📦 Mods", value="Chưa có Mod nào.", inline=False)

        embed.set_thumbnail(url=inter.author.display_avatar.url)
        await inter.edit_original_response(embed=embed)

    # ──────────────────────────────────────────────────────────────
    # /dlclist — Xem danh sách DLC (mọi người)
    # ──────────────────────────────────────────────────────────────

    @commands.slash_command(
        name="dlclist",
        description="Xem danh sách Mod DLC có sẵn",
    )
    async def dlclist_command(self, inter: disnake.ApplicationCommandInteraction):
        await inter.response.defer(ephemeral=False)

        if not _ECONOMY_OK:
            await inter.edit_original_response(content="❌ Hệ thống DLC chưa sẵn sàng.")
            return

        dlcs = get_all_dlcs_summary()
        if not dlcs:
            await inter.edit_original_response(
                content="📭 Hiện chưa có Mod DLC nào. Hãy kiểm tra lại sau!"
            )
            return

        owned = set(get_player_dlcs(str(inter.author.id)))

        embed = disnake.Embed(
            title="📦 Danh Sách Mod DLC — DOELCES v1.0",
            description=f"Có **{len(dlcs)}** Mod DLC. Mua tại Dashboard hoặc dùng `/mods` để kích hoạt.",
            color=0x5865F2,
        )

        for dlc in dlcs[:10]:  # Giới hạn 10 field
            name     = dlc["name"]
            price    = dlc["price"]["display"]
            features = ", ".join(dlc["features"][:3]) or "—"
            status   = "✅ Đã sở hữu" if dlc["folder_name"] in owned else price

            embed.add_field(
                name=f"{'🔓' if dlc['folder_name'] in owned else '🔒'} {name}",
                value=f"*{dlc['description'][:80]}*\n💡 `{features}`\n{status}",
                inline=False,
            )

        embed.set_footer(text="Mua Mod tại Dashboard • /wallet để xem số dư")
        await inter.edit_original_response(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(DLCCommands(bot))
