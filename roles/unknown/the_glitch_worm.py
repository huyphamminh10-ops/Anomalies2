import discord
from roles.base_role import BaseRole


class TheGlitchWorm(BaseRole):
    name = "Sâu Lỗi"
    team = "Anomalies"
    max_count = 1

    description = (
        "Bạn là sâu mã độc — xâm nhập và phá hủy di chúc của người chơi.\n\n"
        "• Mỗi đêm chọn 1 mục tiêu — nếu họ chết đêm đó, di chúc bị thay thế bằng thông báo lỗi.\n"
        "• Không thể dùng 2 đêm liên tiếp.\n"
        "• Không tác dụng nếu mục tiêu đã bị Janitor dọn sạch.\n"
        "• Có **3 lượt** sử dụng trong cả trận."
    )

    dm_message = (
        "🪱 **SÂU LỖI**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 người để cài mã độc — nếu họ chết đêm đó, di chúc bị phá hủy hoàn toàn.\n\n"
        "📋 Cơ chế:\n"
        "• Di chúc bị thay thế bằng thông báo: '✖ Dữ liệu đã bị Glitch-Worm phá hủy.'\n"
        "• Không thể dùng 2 đêm liên tiếp.\n"
        "• Vô hiệu nếu mục tiêu đã bị Janitor làm sạch.\n"
        "• Bạn có **3 lượt** trong cả trận.\n\n"
        "💡 Nhắm vào Sleeper, Psychopath hoặc bất kỳ ai có di chúc quan trọng."
    )

    def __init__(self, player):
        super().__init__(player)
        # BUG FIX: Thiếu __init__ → AttributeError khi send_ui truy cập
        # uses_left / last_used_night / marked_target
        self.uses_left       = 3
        self.last_used_night = -1   # -1 = chưa dùng lần nào
        self.marked_target   = None

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


    # ================================
    # GỬI UI BAN ĐÊM
    # ================================
    async def send_ui(self, game):

        if self.uses_left <= 0:
            await self.safe_send("🪱 Bạn đã hết lượt Ăn Dữ Liệu.")
            return

        if self.last_used_night == game.night_count - 1:
            await self.safe_send("🪱 Không thể dùng 2 đêm liên tiếp.")
            return

        alive = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
        ]

        view = self.GlitchView(game, self, alive)

        await self.safe_send(
            f"🪱 Còn {self.uses_left} lượt.\n"
            "Chọn người để phá hủy Di Chúc nếu họ chết đêm nay:",
            view=view
        )

    # ================================
    # VIEW
    # ================================
    class GlitchView(discord.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                discord.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]
            self.add_item(TheGlitchWorm.GlitchSelect(game, role, options))

    class GlitchSelect(discord.ui.Select):
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

            target_id = int(self.values[0])

            # Không thể dùng nếu mục tiêu đã bị Janitor
            if target_id in self.game.cleaned_roles:
                await interaction.response.send_message(
                    "Mục tiêu này đã bị dọn sạch. Không còn dữ liệu để ăn.",
                    ephemeral=True
                )
                return

            self.role.marked_target = target_id
            self.role.uses_left -= 1
            self.role.last_used_night = self.game.night_count

            await interaction.response.send_message(
                "🪱 Dữ liệu đã bị nhiễm lỗi...",
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)
