import discord
from roles.base_role import BaseRole


class TheDarkArchitect(BaseRole):
    name = "Kiến Trúc Sư Bóng Tối"
    team = "Anomalies"
    max_count = 1

    description = (
        "Bạn kiến trúc bóng tối — mỗi đêm phong tỏa hành động của 3 người chơi.\n\n"
        "• Chọn đúng 3 mục tiêu mỗi đêm để khóa họ — không thể thực hiện bất kỳ hành động đêm nào.\n"
        "• Mỗi người chỉ bị phong tỏa được 1 lần duy nhất trong cả trận.\n"
        "• Nếu còn ít hơn 3 người chưa bị phong tỏa, khả năng sẽ vô hiệu hóa."
    )

    dm_message = (
        "🌑 **THE DARK-ARCHITECT – KIẾN TRÚC SƯ BÓNG TỐI**\n\n"
        "Bạn thuộc phe **Anomalies**.\n\n"
        "🌙 Mỗi đêm bạn chọn 3 ngôi nhà để phong tỏa trong bóng tối.\n\n"
        "📋 Cơ chế:\n"
        "• 3 người được chọn sẽ bị khóa — không thể dùng bất kỳ kỹ năng đêm nào.\n"
        "• Mỗi người chỉ bị nhắm 1 lần. Danh sách mục tiêu thu hẹp dần theo thời gian.\n\n"
        "💡 Hãy ưu tiên phong tỏa các vai trò nguy hiểm như Jailor, Architect, Sheriff."
    )

    def __init__(self, player):
        super().__init__(player)
        self.used_targets = set()      # Những người đã từng bị chọn (vĩnh viễn)
        self.blocked_targets = set()   # Người bị khóa trong đêm hiện tại

    async def on_game_start(self, game):
        """Thông báo danh sách đồng đội khi game bắt đầu."""
        import discord
        teammates = [
            game.players[pid]
            for pid, role in game.roles.items()
            if getattr(role, 'team', '') == 'Anomalies' and pid != self.player.id
        ]
        if not teammates:
            return
        names = ', '.join('**' + m.display_name + '**' for m in teammates)
        desc = 'Đồng đội của bạn:' + chr(10) + names
        await self.safe_send(
            embed=discord.Embed(
                title='👥 Đồng Đội Dị Thể',
                description=desc,
                color=0xe74c3c
            )
        )


    # =====================================
    # GỬI UI BAN ĐÊM
    # =====================================
    async def send_ui(self, game):

        # Chỉ chọn những người chưa từng bị khóa
        alive = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
            and p.id not in self.used_targets
        ]

        if len(alive) < 3:
            await self.safe_send(
                "🌑 Không còn đủ mục tiêu chưa bị bóng tối chạm tới."
            )
            return

        view = self.ArchitectView(game, self, alive)

        await self.safe_send(
            "🌑 Chọn 3 ngôi nhà để chìm vào bóng tối:",
            view=view
        )

    # =====================================
    # VIEW
    # =====================================
    class ArchitectView(discord.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                discord.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]
            self.add_item(TheDarkArchitect.ArchitectSelect(game, role, options))

    class ArchitectSelect(discord.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role

            n = min(3, len(options))
            super().__init__(
                placeholder="Chọn đúng 3 mục tiêu...",
                options=options,
                min_values=n,
                max_values=n
            )

        async def callback(self, interaction: discord.Interaction):

            targets = {int(v) for v in self.values}

            self.role.blocked_targets = targets
            self.role.used_targets.update(targets)

            await interaction.response.send_message(
                "🌑 Bóng tối đã được thiết kế.",
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)
