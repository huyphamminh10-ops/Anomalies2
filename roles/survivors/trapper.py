import discord
import random
from roles.base_role import BaseRole


class Trapper(BaseRole):
    name = "Thợ Đặt Bẫy"
    team = "Survivors"
    max_count = 1
    rarity = "rare"

    description = (
        "Nhà bạn được đặt bẫy.\n"
        "Nếu Dị Thể tấn công bạn:\n"
        "50% họ chết\n"
        "50% họ bị lộ diện."
    )

    dm_message = (
        "🪤 **THỢ ĐẶT BẪY**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🏠 Nhà bạn luôn có bẫy kích hoạt — tự động phản công khi bị tấn công.\n\n"
        "⚔️ 50% — Kẻ tấn công bị tiêu diệt ngay tại chỗ.\n"
        "👁️ 50% — Kẻ tấn công bị **lộ danh tính** trước thị trấn.\n\n"
        "💤 Bạn không cần làm gì — bẫy tự động hoạt động mỗi đêm.\n"
        "🎯 Mục tiêu: Trở thành cái bẫy sống để vạch mặt hoặc tiêu diệt Dị Thể."
    )


    async def send_ui(self, game):
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="🪤 ĐÊM — THỢ ĐẶT BẪY",
                    description=(
                        "Bẫy của bạn đang **hoạt động** đêm nay.\n\n"
                        "Nếu Dị Thể tấn công bạn:\n"
                        "⚔️ **50%** — Kẻ tấn công bị tiêu diệt tại chỗ\n"
                        "👁️ **50%** — Kẻ tấn công bị lộ danh tính\n\n"
                        "💤 Hãy ngủ yên — bẫy tự kích hoạt."
                    ),
                    color=0xe67e22
                ),
                view=self.TrapStatusView()
            )
        except Exception:
            pass

    class TrapStatusView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="🪤 Bẫy: ĐANG HOẠT ĐỘNG", style=discord.ButtonStyle.success, disabled=True)
        async def trap_status(self, interaction: discord.Interaction, button: discord.ui.Button):
            pass

    async def on_attacked(self, game, attackers=None):
        if not attackers:
            return True

        outcome = random.choice(["kill", "reveal"])
        target  = attackers[0]

        if outcome == "kill":
            await game.kill_player(target, reason="Bị bẫy của Thợ Đặt Bẫy giết")
            try:
                await self.safe_send(embed=discord.Embed(
                    title="🪤 BẪY KÍCH HOẠT",
                    description="💀 Kẻ tấn công đã bị tiêu diệt!",
                    color=0x27ae60
                ))
            except Exception:
                pass
        else:
            member = game.guild.get_member(target.id)
            if member:
                game.save_nick(member)
            try:
                await member.edit(nick="ANOMALY")
            except Exception:
                pass
            await game.log_channel.send(embed=discord.Embed(
                description="⚠️ Một Dị Thể đã bị lộ diện bởi bẫy!",
                color=0xe74c3c
            ))
            try:
                await self.safe_send(embed=discord.Embed(
                    title="🪤 BẪY KÍCH HOẠT",
                    description="👁️ Kẻ tấn công đã bị **lộ danh tính**!",
                    color=0xf39c12
                ))
            except Exception:
                pass

        return False
