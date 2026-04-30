import discord
import random
from roles.base_role import BaseRole


class Trapper(BaseRole):
    name = "Thợ Đặt Bẫy"
    team = "Survivors"
    max_count = 1
    rarity = "rare"

    description = (
        "Nhà bạn được đặt một chiếc bẫy.\n"
        "Nếu Dị Thể tấn công bạn, bẫy kích hoạt với 4 kết quả bằng nhau:\n"
        "25% — Kẻ tấn công bị lộ danh tính\n"
        "25% — Kẻ tấn công chết\n"
        "25% — Bạn chết, kẻ tấn công thoát (Phản Đòn)\n"
        "25% — Kẻ tấn công bị Stun, mất lượt đêm hôm sau\n"
        "⚠️ Bẫy chỉ hoạt động một lần duy nhất."
    )

    dm_message = (
        "🪤 **THỢ ĐẶT BẪY**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🏠 Nhà bạn có một chiếc bẫy — kích hoạt **một lần** khi bị tấn công.\n\n"
        "Khi bẫy bắt được Dị Thể (4 kết quả xác suất bằng nhau):\n"
        "👁️ 25% — Kẻ tấn công bị **lộ danh tính** trước thị trấn\n"
        "💀 25% — Kẻ tấn công bị **tiêu diệt** tại chỗ\n"
        "💥 25% — **Phản đòn**: Bạn chết, kẻ tấn công thoát\n"
        "😵 25% — Kẻ tấn công bị **Stun**, mất lượt hành động đêm hôm sau\n\n"
        "⚠️ Bẫy chỉ hoạt động **một lần duy nhất**.\n"
        "🎯 Mục tiêu: Trở thành cái bẫy sống để vạch mặt hoặc tiêu diệt Dị Thể."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trap_used = False  # Bẫy chỉ dùng một lần

    async def send_ui(self, game):
        if self.trap_used:
            desc  = (
                "⚠️ Bẫy của bạn đã **bị kích hoạt** rồi — không còn hiệu lực nữa.\n\n"
                "💤 Bạn không còn bảo vệ thụ động đêm nay."
            )
            color = 0x95a5a6
            title = "🪤 ĐÊM — THỢ ĐẶT BẪY (Bẫy đã dùng)"
            label = "🪤 Bẫy: ĐÃ DÙNG"
            style = discord.ButtonStyle.secondary
        else:
            desc  = (
                "Bẫy của bạn đang **hoạt động** đêm nay.\n\n"
                "Nếu Dị Thể tấn công bạn:\n"
                "👁️ **25%** — Kẻ tấn công bị lộ danh tính\n"
                "💀 **25%** — Kẻ tấn công bị tiêu diệt\n"
                "💥 **25%** — Phản đòn: bạn chết, kẻ thoát\n"
                "😵 **25%** — Kẻ tấn công bị Stun đêm sau\n\n"
                "⚠️ Bẫy chỉ dùng được **một lần**!\n"
                "💤 Hãy ngủ yên — bẫy tự kích hoạt."
            )
            color = 0xe67e22
            title = "🪤 ĐÊM — THỢ ĐẶT BẪY"
            label = "🪤 Bẫy: ĐANG HOẠT ĐỘNG"
            style = discord.ButtonStyle.success

        class TrapStatusView(discord.ui.View):
            def __init__(self_v):
                super().__init__(timeout=60)

            @discord.ui.button(label=label, style=style, disabled=True)
            async def trap_status(self_v, interaction: discord.Interaction, button: discord.ui.Button):
                pass

        try:
            await self.safe_send(
                embed=discord.Embed(title=title, description=desc, color=color),
                view=TrapStatusView()
            )
        except Exception:
            pass

    async def on_attacked(self, game, attackers=None):
        """Xử lý khi Thợ Đặt Bẫy bị tấn công."""
        if not attackers:
            return True

        # Bẫy đã dùng rồi → không kích hoạt, cho phép tấn công bình thường
        if self.trap_used:
            return True

        # Đánh dấu bẫy đã dùng
        self.trap_used = True
        target = attackers[0]

        outcome = random.choices(
            ["reveal", "kill_attacker", "backfire", "stun"],
            weights=[25, 25, 25, 25],
            k=1
        )[0]

        if outcome == "reveal":
            # 25%: Lộ danh tính kẻ tấn công
            member = game.guild.get_member(target.id)
            if member:
                game.save_nick(member)
                try:
                    await member.edit(nick="ANOMALY")
                except Exception:
                    pass
            await game.log_channel.send(embed=discord.Embed(
                title="🪤 BẪY KÍCH HOẠT — LỘ DIỆN",
                description="⚠️ Một Dị Thể đã bị **lộ danh tính** bởi bẫy của Thợ Đặt Bẫy!",
                color=0xf39c12
            ))
            try:
                await self.safe_send(embed=discord.Embed(
                    title="🪤 BẪY KÍCH HOẠT",
                    description="👁️ Kẻ tấn công đã bị **lộ danh tính**!\n⚠️ Bẫy đã hết hiệu lực.",
                    color=0xf39c12
                ))
            except Exception:
                pass
            return False  # Trapper sống sót

        elif outcome == "kill_attacker":
            # 25%: Giết kẻ tấn công
            await game.kill_player(target, reason="Bị bẫy của Thợ Đặt Bẫy giết")
            try:
                await self.safe_send(embed=discord.Embed(
                    title="🪤 BẪY KÍCH HOẠT",
                    description="💀 Kẻ tấn công đã bị **tiêu diệt** tại chỗ!\n⚠️ Bẫy đã hết hiệu lực.",
                    color=0x27ae60
                ))
            except Exception:
                pass
            return False  # Trapper sống sót

        elif outcome == "backfire":
            # 25%: Phản đòn — Thợ Đặt Bẫy chết, kẻ tấn công thoát
            try:
                await self.safe_send(embed=discord.Embed(
                    title="🪤 BẪY PHẢN ĐÒN",
                    description="💥 Bẫy phát nổ ngược — bạn đã **hy sinh**!\n⚠️ Bẫy đã hết hiệu lực.",
                    color=0xe74c3c
                ))
            except Exception:
                pass
            await game.log_channel.send(embed=discord.Embed(
                title="🪤 BẪY PHẢN ĐÒN",
                description="💥 Thợ Đặt Bẫy đã chết vì bẫy của chính mình! Kẻ tấn công thoát.",
                color=0xe74c3c
            ))
            return True  # Trapper chết (tấn công thành công)

        else:  # stun
            # 25%: Stun kẻ tấn công — bị block đêm hôm sau
            if not hasattr(game, "stun_next_night"):
                game.stun_next_night = set()
            game.stun_next_night.add(target.id)

            try:
                await self.safe_send(embed=discord.Embed(
                    title="🪤 BẪY KÍCH HOẠT — STUN",
                    description=(
                        "😵 Kẻ tấn công đã bị **Stun**!\n"
                        "Chúng sẽ mất lượt hành động đêm hôm sau.\n"
                        "⚠️ Bẫy đã hết hiệu lực."
                    ),
                    color=0x9b59b6
                ))
            except Exception:
                pass
            await game.log_channel.send(embed=discord.Embed(
                title="🪤 BẪY KÍCH HOẠT — STUN",
                description="😵 Một Dị Thể đã bị **Stun** bởi bẫy — mất lượt đêm sau!",
                color=0x9b59b6
            ))
            return False  # Trapper sống sót
