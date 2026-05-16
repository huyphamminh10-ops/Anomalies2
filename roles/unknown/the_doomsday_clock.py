import disnake
from roles.base_role import BaseRole


class TheDoomsdayClock(BaseRole):
    name = "ĐỒNG HỒ TẬN THẾ"
    team = "Unknown"
    win_type = "solo"
    max_count = 1

    def __init__(self, player):
        super().__init__(player)
        self.fast_forward_uses = 2
        self.last_used_night = -1

    description = (
        "Bạn là đồng hồ đếm ngược đến tận thế — thắng bằng cách kéo dài trận đấu đủ lâu.\n\n"
        "• Có **2 lượt Tua Nhanh** — rút ngắn thời gian thảo luận ban ngày xuống còn 20 giây.\n"
        "• Không thể dùng Tua Nhanh 2 đêm liên tiếp.\n"
        "• Điều kiện thắng: Trận đấu kéo dài đến **Đêm 18**."
    )

    dm_message = (
        "⏳ **ĐỒNG HỒ TẬN THẾ**\n\n"
        "Bạn thuộc phe **Thực Thể Ẩn** — mục tiêu của bạn là thời gian, không phải máu.\n\n"
        "🌙 Mỗi đêm bạn có thể kích hoạt Tua Nhanh để rút ngắn thảo luận ban ngày.\n\n"
        "📋 Cơ chế:\n"
        "• Tua Nhanh: Thảo luận ban ngày còn 20 giây thay vì 90 giây.\n"
        "• Có **2 lượt** — không thể dùng 2 đêm liên tiếp.\n\n"
        "🏆 Điều kiện thắng: Trận đấu vẫn chưa kết thúc khi đến **Đêm 18**.\n"
        "💡 Hãy kiên nhẫn, tránh bị lộ và cản trở thị trấn kết thúc trận sớm."
    )

    # ================================
    # ĐIỀU KIỆN THẮNG
    # ================================
    def check_win_condition(self, game):
        if game.night_count >= 18:
            return True
        return False

    # ================================
    # GỬI UI BAN ĐÊM
    # ================================
    async def send_ui(self, game):

        if self.fast_forward_uses <= 0:
            await self.safe_send("⏳ Bạn đã hết lượt Tua Nhanh.")
            return

        if self.last_used_night == game.night_count - 1:
            await self.safe_send("⏳ Bạn không thể Tua Nhanh 2 đêm liên tiếp.")
            return

        view = self.DoomsdayView(game, self)
        await self.safe_send(
            f"⏳ Bạn còn {self.fast_forward_uses} lượt.\n"
            "Bạn có muốn Tua Nhanh thời gian thảo luận ngày mai?",
            view=view
        )

    # ================================
    # VIEW
    # ================================
    class DoomsdayView(disnake.ui.View):
        def __init__(self, game, role):
            super().__init__(timeout=60)
            self.game = game
            self.role = role

        @disnake.ui.button(label="⏩ Tua Nhanh", style=disnake.ButtonStyle.danger)
        async def fast_forward(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):

            self.role.fast_forward_uses -= 1
            self.role.last_used_night = self.game.night_count

            # Set flag trong game
            self.game.fast_forward_next_day = True

            await interaction.response.send_message(
                "⏳ Thời gian đã bị thao túng...",
                ephemeral=True
            )

            for item in self.children:
                item.disabled = True

            await interaction.message.edit(view=self)
