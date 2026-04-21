import discord
from roles.base_role import BaseRole


class TheWhisperThief(BaseRole):
    name = "Kẻ Đánh Cắp Lời Thì Thầm"
    team = "Anomalies"

    description = (
        "Bạn nghe lén bí mật — nếu 2 người bạn chọn có tương tác bí mật trong đêm, bạn đọc được di chúc của cả hai.\n\n"
        "• Mỗi đêm chọn 2 người khác nhau — không thể chọn lại cùng cặp 2 đêm liên tiếp.\n"
        "• Nếu cặp đó có tương tác bí mật với nhau, bạn nhận bản sao di chúc của họ."
    )

    dm_message = (
        "🤫 **THE WHISPER-THIEF – KẺ TRỘM THẦM THÌ**\n\n"
        "Bạn thuộc phe **Anomalies**.\n\n"
        "🌙 Mỗi đêm chọn 2 người để nghe lén — nếu họ có tương tác bí mật, bạn đọc được di chúc của cả hai.\n\n"
        "• Không thể chọn lại cùng cặp 2 đêm liên tiếp.\n"
        "💡 Nhắm vào những người nghi ngờ đang liên lạc ngầm."
    )

    def __init__(self, player):
        super().__init__(player)
        self.targets      = []
        self.last_targets = None

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
    # GỬI UI BAN ĐÊM — Chọn 2 mục tiêu
    # ==============================

    async def send_ui(self, game):
        alive_targets = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
        ]

        if len(alive_targets) < 2:
            try:
                await self.safe_send(embed=discord.Embed(
                    title="🤫 ĐÊM — KẺ TRỘM THẦM THÌ",
                    description="❌ Không đủ 2 người còn sống để nghe lén.",
                    color=0x7f8c8d
                ))
            except Exception:
                pass
            return

        last_pair_info = ""
        if self.last_targets:
            last_pair_info = f"\n⚠️ Không thể chọn lại cặp đêm trước."

        view = self.WhisperView(game, self, alive_targets)
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="🤫 ĐÊM — KẺ TRỘM THẦM THÌ",
                    description=(
                        "Chọn **2 người** để nghe lén — nếu họ có tương tác bí mật với nhau, "
                        "bạn sẽ nhận được bản sao di chúc của cả hai.{}\n\n"
                        "🎯 Hãy nhắm vào những người bạn nghi ngờ đang phối hợp ngầm."
                    ).format(last_pair_info),
                    color=0x2c3e50
                ),
                view=view
            )
        except Exception:
            pass

    class WhisperView(discord.ui.View):
        def __init__(self, game, role, target_list):
            super().__init__(timeout=60)
            self.game   = game
            self.role   = role
            self.add_item(TheWhisperThief.WhisperSelect(game, role, target_list))

        @discord.ui.button(label="💤 Bỏ qua đêm nay", style=discord.ButtonStyle.secondary, row=1)
        async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            await interaction.response.send_message("Bạn bỏ qua đêm nay.", ephemeral=True)

    class WhisperSelect(discord.ui.Select):
        def __init__(self, game, role, target_list):
            self.game = game
            self.role = role
            options   = [
                discord.SelectOption(label=p.display_name, value=str(p.id), emoji="🤫")
                for p in target_list
            ][:25]
            super().__init__(
                placeholder="Chọn đúng 2 người để nghe lén...",
                options=options,
                min_values=2,
                max_values=2
            )

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            p1_id, p2_id = int(self.values[0]), int(self.values[1])
            p1 = self.game.players.get(p1_id)
            p2 = self.game.players.get(p2_id)
            ok = self.role.select_targets(p1_id, p2_id)

            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)

            if ok:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=(
                            f"🤫 Đang nghe lén cuộc trò chuyện giữa:\n"
                            f"• **{p1.display_name if p1 else '?'}**\n"
                            f"• **{p2.display_name if p2 else '?'}**\n\n"
                            "Nếu họ có tương tác bí mật đêm nay, bạn sẽ nhận được di chúc của họ vào buổi sáng."
                        ),
                        color=0x2c3e50
                    ),
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ Không thể chọn lại cùng cặp 2 đêm liên tiếp!",
                    ephemeral=True
                )

    def select_targets(self, p1, p2):
        if p1 == p2:
            return False
        if self.last_targets == (p1, p2) or self.last_targets == (p2, p1):
            return False
        self.targets      = [p1, p2]
        self.last_targets = (p1, p2)
        return True

    def resolve(self, engine):
        if len(self.targets) != 2:
            return
        t1, t2 = self.targets
        if engine.had_secret_interaction(t1, t2):
            copied = {
                t1: engine.players[t1].will,
                t2: engine.players[t2].will
            }
            engine.send_private(self.player.id, copied)

    def reset_night(self):
        self.targets = []
