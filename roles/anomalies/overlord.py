import discord
from roles.base_role import BaseRole


class Overlord(BaseRole):
    name = "Lãnh Chúa"
    team = "Anomalies"
    max_count = 1
    rarity = "legendary"

    description = (
        "Bạn là Lãnh Chúa – thủ lĩnh Dị Thể.\n"
        "Bạn quyết định mục tiêu giết mỗi đêm.\n"
        "Khi bạn chết, phe sẽ phải vote chung."
    )

    dm_message = (
        "👑 **LÃNH CHÚA**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "🎯 Mỗi đêm bạn quyết định mục tiêu tấn công của cả phe Dị Thể.\n"
        "👥 Bạn biết danh tính toàn bộ đồng đội Dị Thể.\n\n"
        "⚠️ Khi bạn chết, phe Dị Thể mất thủ lĩnh — họ phải bỏ phiếu chung để chọn mục tiêu.\n"
        "🎯 Mục tiêu: Điều phối phe Dị Thể tiêu diệt Người Sống Sót trước khi bị lộ."
    )


    def __init__(self, player):
        super().__init__(player)
        self.kill_target_id = None

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
    # GỬI UI BAN ĐÊM — Chọn mục tiêu tiêu diệt
    # ==============================

    async def send_ui(self, game):
        alive_targets = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
            and game.roles.get(p.id)
            and game.roles[p.id].team != "Dị Thể"
        ]

        if not alive_targets:
            return

        # Hiển thị danh sách đồng đội còn sống
        teammates = [
            f"• {game.players[pid].display_name}"
            for pid, role in game.roles.items()
            if role.team == "Anomalies" and pid != self.player.id and game.is_alive(pid)
        ]
        team_info = "\n".join(teammates) if teammates else "_(Không còn đồng đội)_"

        view = self.OverlordView(game, self, alive_targets)
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="👑 ĐÊM — LÃNH CHÚA",
                    description=(
                        "Bạn là thủ lĩnh — **quyết định của bạn là mệnh lệnh**.\n\n"
                        f"👥 Đồng đội còn sống:\n{team_info}\n\n"
                        "Chọn mục tiêu để tiêu diệt đêm nay:"
                    ),
                    color=0x8e44ad
                ),
                view=view
            )
        except Exception:
            pass

    class OverlordView(discord.ui.View):
        def __init__(self, game, role, target_list):
            super().__init__(timeout=60)
            self.add_item(Overlord.KillSelect(game, role, target_list))

        @discord.ui.button(label="💤 Bỏ qua đêm nay", style=discord.ButtonStyle.secondary, row=1)
        async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
            role = self.children[0].role
            if interaction.user.id != role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            await interaction.response.send_message("Bạn bỏ qua đêm nay — không ai bị giết.", ephemeral=True)

    class KillSelect(discord.ui.Select):
        def __init__(self, game, role, target_list):
            self.game = game
            self.role = role
            options   = [
                discord.SelectOption(label=p.display_name, value=str(p.id), emoji="🎯")
                for p in target_list
            ][:25]
            super().__init__(
                placeholder="Chọn mục tiêu tiêu diệt...",
                options=options,
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            target_id = int(self.values[0])
            self.role.kill_target_id = target_id
            self.game.queue_kill(target_id, reason="Bị Dị Thể tiêu diệt trong đêm")

            target = self.game.players.get(target_id)
            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"👑 Lệnh đã ban ra: **{target.display_name if target else '?'}** sẽ bị tiêu diệt đêm nay.",
                    color=0x8e44ad
                ),
                ephemeral=True
            )

    def on_death(self, game):
        game.overlord_alive = False
