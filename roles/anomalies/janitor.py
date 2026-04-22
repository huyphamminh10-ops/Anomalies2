import discord
from roles.base_role import BaseRole


class Janitor(BaseRole):
    name = "Lao Công"
    team = "Anomalies"
    max_count = 1

    description = "Xóa vai trò của nạn nhân nếu họ chết trong đêm."

    dm_message = (
        "🧹 **LAO CÔNG**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "🗑️ Mỗi đêm bạn chọn 1 mục tiêu để dọn dẹp.\n"
        "   Nếu mục tiêu chết đêm đó → vai trò của họ bị **xóa sạch** khỏi thông báo.\n"
        "   Thị trấn sẽ không biết ai vừa chết là vai gì!\n\n"
        "👥 Bạn biết danh tính toàn bộ đồng đội Dị Thể.\n"
        "🎯 Mục tiêu: Giúp phe Dị Thể hoạt động trong bóng tối."
    )


    def __init__(self, player):
        super().__init__(player)
        self.clean_target_id = None

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


    # ==============================
    # GỬI UI BAN ĐÊM — Chọn mục tiêu dọn dẹp
    # ==============================

    async def send_ui(self, game):
        alive_targets = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
        ]

        if not alive_targets:
            return

        view = self.JanitorView(game, self, alive_targets)
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="🧹 ĐÊM — KẺ DỌN DẸP",
                    description=(
                        "Chọn 1 người để **xóa sạch dấu vết vai trò** nếu họ bị giết đêm nay.\n\n"
                        "Khi mục tiêu chết, vai trò của họ sẽ **bị ẩn** — thị trấn không biết họ là ai."
                    ),
                    color=0x1abc9c
                ),
                view=view
            )
        except Exception:
            pass

    class JanitorView(discord.ui.View):
        def __init__(self, game, role, target_list):
            super().__init__(timeout=60)
            self.add_item(Janitor.CleanSelect(game, role, target_list))

        @discord.ui.button(label="💤 Bỏ qua", style=discord.ButtonStyle.secondary, row=1)
        async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
            role = self.children[0].role
            if interaction.user.id != role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            await interaction.response.send_message("Bạn bỏ qua đêm nay — không dọn dẹp ai.", ephemeral=True)

    class CleanSelect(discord.ui.Select):
        def __init__(self, game, role, target_list):
            self.game = game
            self.role = role
            options   = [
                discord.SelectOption(label=p.display_name, value=str(p.id), emoji="🧹")
                for p in target_list
            ][:25]
            super().__init__(
                placeholder="Chọn mục tiêu cần xóa dấu vết...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            target_id = int(self.values[0])
            self.role.clean_target_id             = target_id
            self.game.night_effects["clean_target"] = target_id

            target = self.game.players.get(target_id)
            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"🧹 Bạn sẽ xóa dấu vết của **{target.display_name if target else '?'}** nếu họ chết đêm nay.",
                    color=0x1abc9c
                ),
                ephemeral=True
            )

    async def night_action(self, game, target=None):
        if target:
            self.clean_target_id                  = target.id
            game.night_effects["clean_target"]    = target.id
