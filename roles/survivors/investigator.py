import discord
from roles.base_role import BaseRole


class Investigator(BaseRole):
    name      = "Thám Tử"
    team      = "Survivors"
    max_count = 2

    description = (
        "Mỗi đêm bạn có thể điều tra 1 người chơi.\n\n"
        "• Kết quả trả về: 🔴 Dị Thể hoặc 🟢 Người Sống Sót.\n"
        "• Không tiết lộ tên vai trò cụ thể, chỉ cho biết phe.\n"
        "• Nếu điều tra trúng Anomaly, một cảnh báo ẩn danh sẽ gửi vào kênh Dị Thể."
    )

    dm_message = (
        "🔎 **THÁM TỬ**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 người để điều tra.\n"
        "Kết quả sẽ cho biết người đó thuộc phe nào:\n"
        "• 🔴 ĐỎ = Dị Thể (Dị Thể)\n"
        "• 🟢 XANH = Người Sống Sót (Người Sống Sót)\n\n"
        "⚠ Hãy chia sẻ thông tin khéo léo — tiết lộ thân phận quá sớm có thể nguy hiểm."
    )

    async def send_ui(self, game):
        view = InvestigatorView(game, self)
        await self.safe_send(
            embed=discord.Embed(
                title="🔎 ĐÊM — THÁM TỬ",
                description="Chọn 1 người để điều tra phe của họ:",
                color=0x3498db
            ),
            view=view
        )


class InvestigatorSelect(discord.ui.Select):
    def __init__(self, game, role):
        self.game = game
        self.role = role

        options = [
            discord.SelectOption(label=p.display_name, value=str(p.id))
            for p in game.get_alive_players()
            if p != role.player
        ][:25]

        super().__init__(
            placeholder="Chọn mục tiêu điều tra...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        target      = self.game.get_member(int(self.values[0]))
        target_role = self.game.get_role(target)
        if not target_role:
            await interaction.response.send_message("❌ Không thể xác định vai trò mục tiêu.", ephemeral=True)
            return

        if target_role.team == "Anomalies":
            result = "🔴 **ĐỎ** — Người này thuộc phe **Dị Thể**!"
            color  = 0xe74c3c
            # ── Cảnh báo Dị Thể (không nói tên ai bị điều tra) ──
            if hasattr(self.game, "anomaly_chat_mgr"):
                await self.game.anomaly_chat_mgr.send(
                    embed=discord.Embed(
                        title="🔎 CẢNH BÁO TRINH SÁT",
                        description=(
                            "**THÁM TỬ** đã điều tra đêm nay và phát hiện "
                            "một thành viên phe Dị Thể!\n\n"
                            "⚠️ Một trong số các bạn đang bị **nghi ngờ** — "
                            "hãy cảnh giác và bảo vệ danh tính!"
                        ),
                        color=0xff6b35
                    )
                )
        elif target_role.team == "Survivors":
            result = "🟢 **XANH** — Người này thuộc phe **Người Sống Sót**."
            color  = 0x2ecc71
        else:
            result = "❓ **Không xác định** — Không thể xác định phe của người này."
            color  = 0x95a5a6

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔎 KẾT QUẢ ĐIỀU TRA",
                description=result,
                color=color
            ),
            ephemeral=True
        )


class InvestigatorView(discord.ui.View):
    def __init__(self, game, role):
        super().__init__(timeout=60)
        self.add_item(InvestigatorSelect(game, role))
