import discord
from roles.base_role import BaseRole


class TheGlitchStalker(BaseRole):
    name = "Kẻ Rình Rập"
    team = "Anomalies"
    max_count = 1

    description = (
        "Bạn theo dõi bí mật để khai thác lỗ hổng trong hệ thống của Người Sống Sót.\n\n"
        "• Mỗi đêm chọn 1 Survivor để theo dõi và phát hiện vai trò thực của họ.\n"
        "• Không thể theo dõi cùng một người 2 đêm liên tiếp.\n"
        "• Kết quả chỉ gửi riêng cho bạn qua DM."
    )

    dm_message = (
        "👁️ **KẺ RÌNH RẬP**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 Survivor để quét và phát hiện vai trò thực của họ.\n\n"
        "📋 Cơ chế:\n"
        "• Chỉ nhắm được Người Sống Sót — không thể theo dõi Dị Thể khác.\n"
        "• Không thể theo dõi cùng 1 người 2 đêm liên tiếp.\n"
        "• Kết quả được lưu vào bộ nhớ để dùng sau.\n\n"
        "💡 Dùng thông tin thu thập được để lên kế hoạch loại bỏ mục tiêu nguy hiểm nhất."
    )

    def __init__(self, player):
        super().__init__(player)
        self.target_id = None
        self.last_target = None          # FIX: khởi tạo để tránh AttributeError
        self.discovered_roles = {}

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
    # UI BAN ĐÊM
    # =====================================
    async def send_ui(self, game):

        alive = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
            and game.roles.get(p.id)
            and game.roles[p.id].team == "Survivors"
            and p.id != self.last_target
        ]

        if not alive:
            await self.safe_send(
                embed=discord.Embed(
                    title="👁️ ĐÊM — KẺ RÌNH RẬP",
                    description="Không còn Survivor nào chưa bị theo dõi gần đây.",
                    color=0xe74c3c
                )
            )
            return

        view = self.StalkerView(game, self, alive)

        await self.safe_send(
            embed=discord.Embed(
                title="👁️ ĐÊM — KẺ RÌNH RẬP",
                description="Chọn 1 Survivor để theo dõi và phát hiện vai trò thực của họ:",
                color=0xe74c3c
            ),
            view=view
        )

    # =====================================
    # VIEW
    # =====================================
    class StalkerView(discord.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                discord.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]
            self.add_item(TheGlitchStalker.StalkerSelect(game, role, options))

    class StalkerSelect(discord.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role

            super().__init__(
                placeholder="Chọn mục tiêu...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message(
                    "Đây không phải lượt của bạn.", ephemeral=True
                )
                return

            self.role.target_id = int(self.values[0])
            self.role.last_target = self.role.target_id

            await interaction.response.send_message(
                "👁️ Đang theo dõi mục tiêu...",
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)
