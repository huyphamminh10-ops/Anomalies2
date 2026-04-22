import discord
from roles.base_role import BaseRole


class TheFalseSignal(BaseRole):
    name = "Tín Hiệu Giả"
    team = "Anomalies"

    description = (
        "Bạn giả mạo tín hiệu để đánh lừa kết quả điều tra của Người Sống Sót.\n\n"
        "• Mỗi đêm đánh dấu 1 mục tiêu — nếu ai đó điều tra họ đêm đó, kết quả sẽ hiện 'Survivor - Power Role'.\n"
        "• Không thể đánh dấu cùng 1 người 2 đêm liên tiếp.\n"
        "• Có **3 lượt** sử dụng trong cả trận."
    )

    dm_message = (
        "📡 **TÍN HIỆU GIẢ**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "🌙 Mỗi đêm bạn phát tín hiệu giả cho 1 người — nếu Sheriff hoặc Investigator điều tra họ, kết quả bị bóp méo.\n\n"
        "• Kết quả: 'Survivor - Power Role' thay vì thực tế.\n"
        "• Không thể dùng 2 lần liên tiếp trên cùng 1 người.\n"
        "• Bạn có **3 lượt** trong cả trận."
    )

    def __init__(self, player):
        super().__init__(player)
        self.target_id   = None
        self.last_target = None
        self.max_uses    = 3
        self.used        = 0

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
        uses_left = self.max_uses - self.used

        if uses_left <= 0:
            try:
                await self.safe_send(embed=discord.Embed(
                    title="📡 ĐÊM — TÍN HIỆU GIẢ",
                    description="❌ Bạn đã dùng hết **3 lượt**. Không thể phát tín hiệu giả.",
                    color=0x7f8c8d
                ))
            except Exception:
                pass
            return

        alive_targets = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
        ]

        if not alive_targets:
            return

        view = self.FalseSignalView(game, self, alive_targets)
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="📡 ĐÊM — TÍN HIỆU GIẢ",
                    description=(
                        f"📡 Lượt còn lại: **{uses_left}/{self.max_uses}**\n"
                        f"{'⚠️ Không thể chọn lại người trước: **' + str(self.last_target) + '**' if self.last_target else ''}\n\n"
                        "Chọn 1 người để **phát tín hiệu giả** — ai điều tra họ đêm nay sẽ nhận kết quả sai."
                    ),
                    color=0x3498db
                ),
                view=view
            )
        except Exception:
            pass

    class FalseSignalView(discord.ui.View):
        def __init__(self, game, role, target_list):
            super().__init__(timeout=60)
            self.add_item(TheFalseSignal.SignalSelect(game, role, target_list))

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

    class SignalSelect(discord.ui.Select):
        def __init__(self, game, role, target_list):
            self.game = game
            self.role = role
            options   = [
                discord.SelectOption(label=p.display_name, value=str(p.id), emoji="📡")
                for p in target_list
            ][:25]
            super().__init__(
                placeholder="Chọn mục tiêu phát tín hiệu giả...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            target_id = int(self.values[0])
            ok        = self.role.select_target(target_id)

            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)

            target = self.game.players.get(target_id)
            if ok:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"📡 Tín hiệu giả đã phát đến **{target.display_name if target else '?'}** — lượt còn lại: {self.role.max_uses - self.role.used}/{self.role.max_uses}",
                        color=0x3498db
                    ),
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ Không thể chọn lại người này liên tiếp!", ephemeral=True)

    def select_target(self, target_id):
        if self.used >= self.max_uses:
            return False
        if target_id == self.player.id:
            return False
        if target_id == self.last_target:
            return False
        self.target_id   = target_id
        self.last_target = target_id
        return True

    def on_investigation(self, engine, investigator_id, target_id, result):
        if self.target_id == target_id:
            self.used += 1
            return "Survivor - Power Role"
        return result

    def reset_night(self):
        self.target_id = None
