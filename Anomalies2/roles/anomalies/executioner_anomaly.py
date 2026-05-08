import disnake
from roles.base_role import BaseRole


class TheExecutionerAnomaly(BaseRole):
    name = "Dị Thể Hành Quyết"
    team = "Anomalies"

    description = (
        "Bạn là một Dị Thể hành quyết lạnh lùng — có thể xử tử mục tiêu dù họ được bảo vệ.\n\n"
        "• Mỗi đêm chọn 1 mục tiêu để hành quyết. Đòn tấn công xuyên qua bảo vệ.\n"
        "• Nếu mục tiêu có người bảo vệ, người bảo vệ đó cũng bị tiêu diệt (phản thương).\n"
        "• Có **2 lượt** sử dụng trong cả trận, mỗi lượt cần 1 đêm hồi chiêu."
    )

    dm_message = (
        "⚔️ **DỊ THỂ HÀNH QUYẾT**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "🌙 Mỗi đêm bạn có thể chọn 1 người để hành quyết — xuyên qua mọi lớp bảo vệ.\n\n"
        "📋 Cơ chế:\n"
        "• Mục tiêu bị giết kể cả khi có bảo vệ.\n"
        "• Người bảo vệ mục tiêu cũng bị phản thương và tiêu diệt.\n"
        "• Bạn có **2 lượt** — mỗi đêm hồi 1 lượt sau khi dùng."
    )

    def __init__(self, player):
        super().__init__(player)
        self.target_id = None
        self.cooldown  = 0
        self.max_uses  = 2
        self.used      = 0

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
        uses_left = self.max_uses - self.used

        if uses_left <= 0:
            try:
                await self.safe_send(embed=disnake.Embed(
                    title="⚔️ ĐÊM — KẺ HÀNH QUYẾT",
                    description="❌ Bạn đã dùng hết **2 lượt** hành quyết. Không thể hành động.",
                    color=0x7f8c8d
                ))
            except Exception:
                pass
            return

        if self.cooldown > 0:
            try:
                await self.safe_send(embed=disnake.Embed(
                    title="⚔️ ĐÊM — KẺ HÀNH QUYẾT",
                    description=f"⏳ Đang hồi chiêu — còn **{self.cooldown} đêm** nữa mới có thể hành quyết.\n\nLượt còn lại: **{uses_left}/{self.max_uses}**",
                    color=0x7f8c8d
                ))
            except Exception:
                pass
            return

        alive_targets = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
            and game.roles.get(p.id)
            and game.roles[p.id].team != "Dị Thể"
        ]

        if not alive_targets:
            return

        view = self.ExecutionView(game, self, alive_targets)
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="⚔️ ĐÊM — KẺ HÀNH QUYẾT",
                    description=(
                        f"🗡️ Lượt còn lại: **{uses_left}/{self.max_uses}**\n\n"
                        "Chọn mục tiêu để **hành quyết** — đòn tấn công xuyên qua mọi lớp bảo vệ.\n"
                        "⚠️ Người bảo vệ mục tiêu cũng sẽ bị tiêu diệt!"
                    ),
                    color=0xe74c3c
                ),
                view=view
            )
        except Exception:
            pass

    class ExecutionView(disnake.ui.View):
        def __init__(self, game, role, target_list):
            super().__init__(timeout=60)
            self.add_item(TheExecutionerAnomaly.ExecuteSelect(game, role, target_list))

        @disnake.ui.button(label="💤 Bỏ qua / Hồi chiêu", style=disnake.ButtonStyle.secondary, row=1)
        async def skip(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            role = self.children[0].role
            if interaction.user.id != role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            await interaction.response.send_message("Bạn bỏ qua đêm nay để hồi chiêu.", ephemeral=True)

    class ExecuteSelect(disnake.ui.Select):
        def __init__(self, game, role, target_list):
            self.game = game
            self.role = role
            options   = [
                disnake.SelectOption(label=p.display_name, value=str(p.id), emoji="⚔️")
                for p in target_list
            ][:25]
            super().__init__(
                placeholder="Chọn mục tiêu hành quyết...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            target_id = int(self.values[0])
            ok        = self.role.select_target(target_id, self.game)

            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)

            target = self.game.players.get(target_id)
            if ok:
                await interaction.response.send_message(
                    embed=disnake.Embed(
                        description=f"⚔️ Lệnh hành quyết đã được ban ra cho **{target.display_name if target else '?'}**.",
                        color=0xe74c3c
                    ),
                    ephemeral=True
                )
            else:
                await interaction.response.send_message("❌ Không thể hành quyết mục tiêu này.", ephemeral=True)

    def select_target(self, target_id, engine):
        if self.used >= self.max_uses or self.cooldown > 0:
            return False
        if not engine.players.get(target_id) or not engine.players[target_id].alive:
            return False
        if target_id == self.player.id:
            return False
        self.target_id = target_id
        return True

    def resolve_kill(self, engine):
        if not self.target_id:
            return
        target = engine.players.get(self.target_id)
        if not target or not target.alive:
            return

        protectors = engine.get_protectors(self.target_id)
        target.alive = False
        engine.queue_death(target.id, cause="Execution")

        for protector_id in protectors:
            protector = engine.players.get(protector_id)
            if protector and protector.alive:
                protector.alive = False
                engine.queue_death(protector.id, cause="Backlash")

        self.used     += 1
        self.cooldown  = 1

    def end_night(self):
        self.target_id = None
        if self.cooldown > 0:
            self.cooldown -= 1
