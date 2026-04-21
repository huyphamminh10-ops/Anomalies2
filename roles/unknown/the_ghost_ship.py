import discord
from roles.base_role import BaseRole


class TheGhostShip(BaseRole):
    name = "Con Tàu Ma"
    team = "Unknown"
    max_count = 1

    def __init__(self, player):
        super().__init__(player)
        self.abducted             = set()
        self.last_target          = None
        self.required_abductions  = 5

    description = (
        "Bạn là Tàu Ma bí ẩn — bắt cóc người chơi đưa về thế giới bên kia mà không giết họ.\n\n"
        "• Bắt đầu từ Đêm 3, mỗi đêm bắt cóc 1 người — họ bị loại tạm thời khỏi thế giới sống.\n"
        "• Không thể bắt cùng 1 người 2 đêm liên tiếp.\n"
        "• Số người cần bắt tăng dần theo số người chơi ban đầu (công thức: 5 + (lobby-20)/5).\n"
        "• Điều kiện thắng: Bắt đủ số người quy định."
    )

    dm_message = (
        "🚢 **CON TÀU MA**\n\n"
        "Bạn thuộc phe **Thực Thể Ẩn** — mục tiêu của bạn là bắt cóc, không phải giết.\n\n"
        "🌙 Từ Đêm 3 trở đi, mỗi đêm bạn bắt cóc 1 người đưa lên tàu — họ biến mất khỏi thế giới sống.\n\n"
        "📋 Cơ chế:\n"
        "• Người bị bắt cóc bị loại tạm thời — không chết nhưng không còn trong trận.\n"
        "• Không thể bắt cùng 1 người 2 đêm liên tiếp.\n"
        "• Số mục tiêu cần đủ phụ thuộc số người chơi ban đầu.\n\n"
        "🏆 Điều kiện thắng: Bắt đủ số người theo quy định.\n"
        "💡 Hãy ưu tiên bắt người quan trọng để vô hiệu hóa sức mạnh của Người Sống Sót."
    )

    # ================================
    # TÍNH SỐ NGƯỜI CẦN BẮT
    # ================================
    def calculate_required(self, game):
        lobby_size = game.initial_player_count
        self.required_abductions = 5 + ((lobby_size - 20) // 5)

    # ================================
    # CHECK WIN
    # ================================
    def check_win_condition(self, game):
        return len(self.abducted) >= self.required_abductions

    # ================================
    # GỬI UI BAN ĐÊM
    # ================================
    async def send_ui(self, game):

        if game.night_count < 3:
            return

        alive = [
            p for p in game.get_alive_players()
            if p.id not in self.abducted and p.id != self.player.id
        ]

        if not alive:
            return

        view = self.GhostView(game, self, alive)

        await self.safe_send(
            f"🚢 Đã bắt: {len(self.abducted)}/{self.required_abductions}\n"
            "Chọn người để bắt cóc:",
            view=view
        )

    # ================================
    # VIEW
    # ================================
    class GhostView(discord.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                discord.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]
            self.add_item(TheGhostShip.GhostSelect(game, role, options))

    class GhostSelect(discord.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role
            super().__init__(
                placeholder="Chọn mục tiêu bị bắt cóc...",
                options=options,
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):

            target_id = int(self.values[0])

            if target_id == self.role.last_target:
                await interaction.response.send_message(
                    "Không thể bắt cùng một người 2 đêm liên tiếp.",
                    ephemeral=True
                )
                return

            self.role.abducted.add(target_id)
            self.role.last_target = target_id

            # Loại khỏi danh sách sống
            self.game.temporarily_removed.add(target_id)

            target = self.game.get_member(target_id)
            if target:
                await target.send(
                    "🌫 Bạn đã bị cuốn lên Tàu Ma...\n"
                    "Bạn vẫn chưa chết, nhưng bạn không còn trong thế giới này."
                )

            await interaction.response.send_message(
                "🚢 Mục tiêu đã bị bắt cóc.",
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)
