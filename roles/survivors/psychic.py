import discord
from roles.base_role import BaseRole


class Psychic(BaseRole):
    name      = "Người Tiên Tri"
    team      = "Survivors"
    max_count = 1

    description = (
        "Mỗi đêm bạn có thể cảm nhận linh hồn của 1 người chơi.\n\n"
        "• Nếu họ thuộc Dị Thể hoặc Thực Thể Ẩn: ⚠ Năng lượng xấu.\n"
        "• Nếu họ thuộc Người Sống Sót: ✨ Linh hồn trong sạch.\n"
        "• Nếu cảm nhận trúng Anomaly, cảnh báo mơ hồ gửi vào kênh Dị Thể.\n"
        "• Kết quả mang tính trực cảm — không chính xác tuyệt đối như Thám Tử."
    )

    dm_message = (
        "🔮 **NGƯỜI TIÊN TRI**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🌙 Mỗi đêm bạn dùng năng lực ngoại cảm để đọc linh hồn 1 người.\n"
        "• ⚠ Năng lượng xấu → người này có thể là mối đe dọa.\n"
        "• ✨ Linh hồn trong sạch → người này nhiều khả năng là đồng minh.\n\n"
        "💡 Kết quả của bạn khác với Thám Tử — hãy kết hợp thông tin để suy luận."
    )

    async def send_ui(self, game):
        view = PsychicView(game, self)
        await self.safe_send(
            embed=discord.Embed(
                title="🔮 ĐÊM — NGƯỜI TIÊN TRI",
                description="Chọn 1 người để cảm nhận linh hồn:",
                color=0x9b59b6
            ),
            view=view
        )


class PsychicSelect(discord.ui.Select):
    def __init__(self, game, role):
        self.game = game
        self.role = role

        options = [
            discord.SelectOption(label=p.display_name, value=str(p.id))
            for p in game.get_alive_players()
            if p != role.player
        ][:25]

        super().__init__(
            placeholder="Chọn mục tiêu cảm nhận...",
            options=options[:25],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        target      = self.game.get_member(int(self.values[0]))
        target_role = self.game.get_role(target)
        if not target_role:
            await interaction.response.send_message("❌ Không thể xác định vai trò mục tiêu.", ephemeral=True)
            return

        if target_role.team in ("Anomalies", "Unknown", "Unknown Entities"):
            result = "⚠️ Bạn cảm thấy người này mang **năng lượng tối tăm** và nguy hiểm..."
            color  = 0xe74c3c

            # ── Cảnh báo mơ hồ vào Dị Thể chat (chỉ khi là Dị Thể) ──
            if target_role.team == "Anomalies" and hasattr(self.game, "anomaly_chat_mgr"):
                await self.game.anomaly_chat_mgr.send(
                    embed=discord.Embed(
                        title="🔮 CẢNH BÁO NGOẠI CẢM",
                        description=(
                            "**NGƯỜI TIÊN TRI** đã cảm nhận được năng lượng tối từ "
                            "một thành viên trong phe Dị Thể!\n\n"
                            "⚠️ Kết quả này mang tính mơ hồ nhưng có thể khiến "
                            "Người Sống Sót **nghi ngờ** — hãy cẩn thận lời nói ban ngày."
                        ),
                        color=0x8e44ad
                    )
                )
        else:
            result = "✨ Linh hồn người này có vẻ **trong sạch** và hiền lành."
            color  = 0x2ecc71

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔮 LINH CẢM",
                description=result,
                color=color
            ),
            ephemeral=True
        )


class PsychicView(discord.ui.View):
    def __init__(self, game, role):
        super().__init__(timeout=60)
        self.add_item(PsychicSelect(game, role))
