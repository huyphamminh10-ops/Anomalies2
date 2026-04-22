import discord
from roles.base_role import BaseRole


class TheArchitect(BaseRole):
    name = "Kiến Trúc Sư"
    team = "Survivors"
    max_count = 1

    def __init__(self, player):
        super().__init__(player)
        self.used_tonight = False
        self.uses_left = 2

    description = (
        "Bạn có thể gia cố nhà ở để bảo vệ người chơi khỏi bị tấn công vào ban đêm.\n\n"
        "• Mỗi đêm chọn tối đa 5 người để bảo vệ (chỉ Người Sống Sót được bảo vệ).\n"
        "• Tổng cộng có 2 lượt Gia Cố trong cả trận.\n"
        "• Người được bảo vệ sẽ sống sót qua đòn tấn công không có bypass."
    )

    dm_message = (
        "🏗️ **KIẾN TRÚC SƯ**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🌙 Bạn có thể gia cố nhà ở, bảo vệ Người Sống Sót khỏi bị giết trong đêm.\n\n"
        "📋 Cơ chế:\n"
        "• Chọn tối đa 5 người mỗi lượt Gia Cố.\n"
        "• Chỉ có tác dụng với Người Sống Sót — Dị Thể không được bảo vệ.\n"
        "• Bạn có **2 lượt** dùng trong suốt cả trận.\n\n"
        "💡 Hãy dùng đúng lúc — bảo vệ các vai trò quan trọng khi thị trấn bị đe dọa."
    )

    # ==================================
    # GỬI UI BAN ĐÊM
    # ==================================
    async def send_ui(self, game):

        self.used_tonight = False

        if self.uses_left <= 0:
            await self.safe_send("🏗 Bạn đã hết lượt Gia Cố.")
            return

        alive = [
            p for p in game.get_alive_players()
            if p != self.player
        ]

        view = self.ArchitectView(game, self, alive)
        await self.safe_send(
            f"🏗 Bạn còn {self.uses_left} lượt Gia Cố.\nChọn tối đa 5 người:",
            view=view
        )

    # ==================================
    # VIEW
    # ==================================
    class ArchitectView(discord.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                discord.SelectOption(
                    label=p.display_name,
                    value=str(p.id)
                )
                for p in alive_list
            ][:25]

            self.add_item(TheArchitect.ArchitectSelect(game, role, options))

    # ==================================
    # SELECT
    # ==================================
    class ArchitectSelect(discord.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role

            super().__init__(
                placeholder="Chọn tối đa 5 mục tiêu...",
                options=options[:25],
                min_values=1,
                max_values=5
            )

        async def callback(self, interaction: discord.Interaction):

            if self.role.used_tonight:
                await interaction.response.send_message(
                    "Bạn đã Gia Cố đêm nay rồi.",
                    ephemeral=True
                )
                return

            protected_count = 0

            for value in self.values:
                target = self.game.get_member(int(value))
                if not target:
                    continue
                target_role = self.game.roles.get(target.id)

                # Chỉ bảo vệ Người Sống Sót
                if target_role and target_role.team == "Survivors":
                    self.game.protected.add(target.id)
                    protected_count += 1

            self.role.uses_left -= 1
            self.role.used_tonight = True

            await interaction.response.send_message(
                f"🏗 Bạn đã Gia Cố {protected_count} nhà.",
                ephemeral=True
            )

            # Disable UI
            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)
