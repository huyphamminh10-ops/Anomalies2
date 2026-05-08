import disnake
from roles.base_role import BaseRole


class Medium(BaseRole):
    name = "Nhà Ngoại Cảm"
    team = "Survivors"
    max_count = 1
    rarity = "rare"

    description = (
        "Vào ban đêm bạn có thể trò chuyện với những người đã chết.\n"
        "Không tham gia bỏ phiếu."
    )

    dm_message = (
        "🕯️ **NHÀ NGOẠI CẢM**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "👻 Vào ban đêm bạn có thể mở séance để trò chuyện với người đã chết.\n"
        "📡 Các linh hồn có thể cung cấp manh mối quan trọng.\n\n"
        "🚫 Bạn không tham gia bỏ phiếu cách ly ban ngày.\n"
        "🎯 Mục tiêu: Thu thập thông tin từ cõi âm để giúp thị trấn chiến thắng."
    )


    def vote_weight(self):
        return 0

    # ==============================
    # GỬI UI BAN ĐÊM — Xác nhận mở séance
    # ==============================

    async def send_ui(self, game):
        dead_players = game.get_dead_players()

        if not dead_players:
            try:
                await self.safe_send(
                    embed=disnake.Embed(
                        title="🕯️ ĐÊM — ĐỒNG CỐT",
                        description="Chưa có linh hồn nào để giao tiếp đêm nay.",
                        color=0x9b59b6
                    )
                )
            except Exception:
                pass
            return

        view = self.SeanceView(game, self, dead_players)
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="🕯️ ĐÊM — ĐỒNG CỐT",
                    description=(
                        f"Có **{len(dead_players)}** linh hồn đang chờ.\n\n"
                        "Nhấn **Mở Séance** để tạo kênh giao tiếp với người đã khuất đêm nay."
                    ),
                    color=0x9b59b6
                ),
                view=view
            )
        except Exception:
            pass

    # ==============================
    # VIEW
    # ==============================

    class SeanceView(disnake.ui.View):
        def __init__(self, game, role, dead_players):
            super().__init__(timeout=60)
            self.game         = game
            self.role         = role
            self.dead_players = dead_players
            self.opened       = False

        @disnake.ui.button(label="🕯️ Mở Séance", style=disnake.ButtonStyle.primary)
        async def open_seance(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            if self.opened:
                await interaction.response.send_message("Séance đã được mở rồi.", ephemeral=True)
                return

            self.opened = True
            button.disabled = True
            button.label    = "✅ Đã mở Séance"
            await interaction.message.edit(view=self)

            # Tạo séance channel
            await self.role.night_action(self.game)

            await interaction.response.send_message(
                embed=disnake.Embed(
                    description=(
                        "✅ Séance đã mở!\n"
                        "Một kênh bí mật đã được tạo — bạn có thể giao tiếp với linh hồn người đã khuất."
                    ),
                    color=0x9b59b6
                ),
                ephemeral=True
            )

        @disnake.ui.button(label="❌ Bỏ qua", style=disnake.ButtonStyle.secondary)
        async def skip(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            await interaction.response.send_message("Bạn đã chọn không mở séance đêm nay.", ephemeral=True)

    # ==============================
    # TẠO SEANCE CHANNEL
    # ==============================

    async def night_action(self, game):
        dead_players = game.get_dead_players()
        if not dead_players:
            return

        guild = game.guild
        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(read_messages=False),
            self.player:        disnake.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        for dead in dead_players:
            overwrites[dead] = disnake.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await guild.create_text_channel(
            name=f"seance-night-{game.night_count}",
            overwrites=overwrites
        )
        game.temp_channels.append(channel)

        await channel.send(
            embed=disnake.Embed(
                title="🕯️ SÉANCE — Giao Tiếp Tâm Linh",
                description=(
                    f"Đêm {game.night_count} — Đồng Cốt đã mở cổng kết nối.\n\n"
                    "Người sống và người đã khuất có thể trò chuyện ở đây.\n"
                    "⚠️ Kênh này sẽ tự đóng khi bình minh ló dạng."
                ),
                color=0x9b59b6
            )
        )
