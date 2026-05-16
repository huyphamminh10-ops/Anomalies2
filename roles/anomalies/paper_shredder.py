import disnake
from roles.base_role import BaseRole


class ThePaperShredder(BaseRole):
    name = "Máy Hủy Tài Liệu"
    team = "Anomalies"
    dif = 6

    description = (
        "Bạn phá hủy di chúc của người chơi trước khi nó được công bố.\n\n"
        "• Mỗi đêm đánh dấu 1 người — nếu họ chết đêm đó, toàn bộ di chúc bị xóa sạch.\n"
        "• Ngăn chặn thông tin quan trọng bị lộ ra công cộng khi người đó tử vong."
    )

    dm_message = (
        "🗂️ **MÁY HỦY TÀI LIỆU**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 người để hủy di chúc nếu họ bị giết.\n\n"
        "📋 Cơ chế:\n"
        "• Nếu mục tiêu chết trong đêm bạn đánh dấu, di chúc của họ bị xóa hoàn toàn.\n"
        "💡 Nhắm vào Archivist, Sleeper hoặc bất kỳ ai có thể để lại thông tin nguy hiểm."
    )

    def __init__(self, player):
        super().__init__(player)
        self.target_id = None

    async def on_game_start(self, game):
        """Thông báo danh sách đồng đội khi game bắt đầu."""
        import disnake
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
            embed=disnake.Embed(
                title='👥 Đồng Đội Dị Thể',
                description=desc,
                color=0xe74c3c
            )
        )


    # ==============================
    # GỬI UI BAN ĐÊM
    # ==============================

    async def send_ui(self, game):
        alive_targets = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
        ]

        if not alive_targets:
            return

        view = self.ShredderView(game, self, alive_targets)
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="🗂️ ĐÊM — KẺ HỦY HỒ SƠ",
                    description=(
                        "Chọn 1 người để **hủy di chúc** nếu họ bị giết đêm nay.\n\n"
                        "📋 Mục tiêu nên là những người có thể để lại thông tin nguy hiểm:\n"
                        "• The Archivist\n• The Sleeper\n• Investigator\n• Bất kỳ Power Role nào"
                    ),
                    color=0xe74c3c
                ),
                view=view
            )
        except Exception:
            pass

    class ShredderView(disnake.ui.View):
        def __init__(self, game, role, target_list):
            super().__init__(timeout=60)
            self.add_item(ThePaperShredder.ShredSelect(game, role, target_list))

        @disnake.ui.button(label="💤 Bỏ qua đêm nay", style=disnake.ButtonStyle.secondary, row=1)
        async def skip(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            role = self.children[0].role
            if interaction.user.id != role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            await interaction.response.send_message("Bạn bỏ qua đêm nay.", ephemeral=True)

    class ShredSelect(disnake.ui.Select):
        def __init__(self, game, role, target_list):
            self.game = game
            self.role = role
            options   = [
                disnake.SelectOption(label=p.display_name, value=str(p.id), emoji="🗂️")
                for p in target_list
            ][:25]
            super().__init__(
                placeholder="Chọn mục tiêu hủy di chúc...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            target_id = int(self.values[0])
            self.role.select_target(target_id)

            target = self.game.players.get(target_id)
            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)
            await interaction.response.send_message(
                embed=disnake.Embed(
                    description=f"🗂️ Đã đánh dấu **{target.display_name if target else '?'}** — nếu họ chết đêm nay, di chúc sẽ bị hủy.",
                    color=0xe74c3c
                ),
                ephemeral=True
            )

    def select_target(self, target_id):
        self.target_id = target_id
        return True

    def on_death(self, engine, player_id, will_text):
        if self.target_id == player_id:
            return ""
        return will_text

    def reset_night(self):
        self.target_id = None
