import discord
from roles.base_role import BaseRole


class SerialKiller(BaseRole):
    name = "KẺ GIẾT NGƯỜI HÀNG LOẠT"
    team = "Unknown Entities"
    win_type = "solo"  # BUG FIX: Phải là solo để WinConditionManager check đúng

    description = (
        "Bạn là kẻ giết người hàng loạt không phe phái — chỉ muốn là người sống sót duy nhất.\n\n"
        "• Mỗi đêm chọn 1 người để sát hại ngay lập tức.\n"
        "• Không thể giết cùng 1 người 2 đêm liên tiếp.\n"
        "• Điều kiện thắng: Là người duy nhất còn sống."
    )

    dm_message = (
        "🔪 **KẺ GIẾT NGƯỜI HÀNG LOẠT**\n\n"
        "Bạn thuộc phe **Thực Thể Không Xác Định** — chỉ chiến đấu cho bản thân.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 người để sát hại trực tiếp.\n\n"
        "📋 Cơ chế:\n"
        "• Không thể giết cùng 1 người 2 đêm liên tiếp.\n"
        "• Hành động giết xảy ra ngay trong đêm — không cần chờ resolve.\n\n"
        "🏆 Điều kiện thắng: Chỉ còn mình bạn sống sót.\n"
        "⚠ Cả Người Sống Sót lẫn Dị Thể đều là mục tiêu — không có đồng minh."
    )
    def __init__(self, player):
        super().__init__(player)
        self.last_target_id = None
        self.has_killed_tonight = False

    # ==============================
    # GỬI UI BAN ĐÊM
    # ==============================

    async def send_ui(self, game):

        self.has_killed_tonight = False

        alive_players = [
            p for p in game.get_alive_players()
            if p != self.player
        ]

        if not alive_players:
            return

        view = self.SerialKillerView(game, self, alive_players)
        await self.safe_send("🔪 Chọn mục tiêu để giết:", view=view)

    # ==============================
    # CHECK WIN CONDITION
    # ==============================

    def check_win_condition(self, game) -> bool:
        # BUG FIX: Phải sync — WinConditionManager đóng coroutine nếu là async
        alive = game.get_alive_players()
        alive_ids = {p.id for p in alive}
        return len(alive_ids) == 1 and self.player.id in alive_ids

    # ==============================
    # VIEW
    # ==============================

    class SerialKillerView(discord.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            self.game = game
            self.role = role

            options = [
                discord.SelectOption(
                    label=p.display_name,
                    value=str(p.id)
                )
                for p in alive_list
            ][:25]

            select = SerialKiller.SerialKillerSelect(game, role, options)
            self.add_item(select)

    # ==============================
    # SELECT
    # ==============================

    class SerialKillerSelect(discord.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role

            super().__init__(
                placeholder="Chọn nạn nhân...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):

            if self.role.has_killed_tonight:
                await interaction.response.send_message(
                    "Bạn đã giết người đêm nay rồi.",
                    ephemeral=True
                )
                return

            target = self.game.get_member(int(self.values[0]))

            if not target:
                return

            if target.id == self.role.player.id:
                await interaction.response.send_message(
                    "Bạn không thể tự sát.",
                    ephemeral=True
                )
                return

            if self.role.last_target_id == target.id:
                await interaction.response.send_message(
                    "Bạn không thể giết cùng một người 2 đêm liên tiếp.",
                    ephemeral=True
                )
                return

            self.role.last_target_id = target.id
            self.role.has_killed_tonight = True

            await self.game.kill_player(
                target,
                reason="Bị Serial Killer sát hại"
            )

            await interaction.response.send_message(
                f"🔪 Bạn đã giết {target.display_name}.",
                ephemeral=True
            )

            # Disable UI sau khi chọn
            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)

            # Check thắng (sync — result handled by _check_win loop)
            self.game._check_win()
