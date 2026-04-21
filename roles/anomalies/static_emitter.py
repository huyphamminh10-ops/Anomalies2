import discord
from roles.base_role import BaseRole


class TheStaticEmitter(BaseRole):
    name = "Nguồn Tĩnh Điện"
    team = "Anomalies"

    description = (
        "Bạn phát nhiễu hệ thống — làm méo mó tin nhắn mà người chơi nhận được.\n\n"
        "• Mỗi đêm chọn 1 người — toàn bộ tin nhắn hệ thống gửi đến họ bị mã hóa nhiễu.\n"
        "• Ký tự bị thay thế: a→@, o→0, i→!, e→#, u→µ.\n"
        "• Gây nhầm lẫn và khó đọc thông tin quan trọng."
    )

    dm_message = (
        "📻 **THE STATIC-EMITTER – BỘ PHÁT NHIỄU**\n\n"
        "Bạn thuộc phe **Anomalies**.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 người để phát nhiễu — tin nhắn hệ thống của họ bị biến dạng.\n\n"
        "• Các nguyên âm bị thay thế bằng ký hiệu đặc biệt.\n"
        "💡 Phát nhiễu đúng thời điểm để Survivors không thể đọc kết quả điều tra."
    )

    def __init__(self, player):
        super().__init__(player)
        self.target_zone = None
        self.target_id   = None

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
    # GỬI UI BAN ĐÊM
    # ==============================

    async def send_ui(self, game):
        alive_targets = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
            and game.roles.get(p.id)
            and game.roles[p.id].team != "Anomalies"
        ]

        if not alive_targets:
            return

        view = self.StaticView(game, self, alive_targets)
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="📻 ĐÊM — BỘ PHÁT NHIỄU",
                    description=(
                        "Chọn 1 người để **phát nhiễu** — mọi tin nhắn hệ thống gửi đến họ đêm nay sẽ bị biến dạng.\n\n"
                        "```\na → @    o → 0\ni → !    e → #\nu → µ\n```\n"
                        "🎯 Nhắm vào Sheriff, Investigator hoặc Psychic."
                    ),
                    color=0x9b59b6
                ),
                view=view
            )
        except Exception:
            pass

    class StaticView(discord.ui.View):
        def __init__(self, game, role, target_list):
            super().__init__(timeout=60)
            self.add_item(TheStaticEmitter.StaticSelect(game, role, target_list))

        @discord.ui.button(label="💤 Bỏ qua đêm nay", style=discord.ButtonStyle.secondary, row=1)
        async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
            role = self.children[0].role
            if interaction.user.id != role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            await interaction.response.send_message("Bạn bỏ qua đêm nay.", ephemeral=True)

    class StaticSelect(discord.ui.Select):
        def __init__(self, game, role, target_list):
            self.game = game
            self.role = role
            options   = [
                discord.SelectOption(label=p.display_name, value=str(p.id), emoji="📻")
                for p in target_list
            ][:25]
            super().__init__(
                placeholder="Chọn mục tiêu phát nhiễu...",
                options=options,
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            target_id           = int(self.values[0])
            self.role.target_id = target_id
            self.role.select_zone(target_id)

            target = self.game.players.get(target_id)
            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"📻 Nhiễu đã phát đến **{target.display_name if target else '?'}** — thông tin của họ sẽ bị bóp méo đêm nay.",
                    color=0x9b59b6
                ),
                ephemeral=True
            )

    def select_zone(self, zone_id):
        self.target_zone = zone_id
        return True

    def on_system_message(self, player, message):
        if player.zone == self.target_zone or getattr(player, "id", None) == self.target_id:
            return self.glitch_text(message)
        return message

    def glitch_text(self, text):
        for k, v in {"a": "@", "o": "0", "i": "!", "e": "#", "u": "µ"}.items():
            text = text.replace(k, v)
        return text

    def reset_night(self):
        self.target_zone = None
        self.target_id   = None
