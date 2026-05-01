import disnake
from roles.base_role import BaseRole


class TheBioMimic(BaseRole):
    name = "Kẻ Mô Phỏng Sinh Học"
    team = "Anomalies"

    description = """
    Chọn một Survivor để cộng sinh.
    Nếu bạn bị Cách ly, người cộng sinh sẽ bị loại theo.
    Nếu người cộng sinh chết trước, bạn nhận một lần miễn nhiễm sát thương ban đêm.
    """

    dm_message = (
        "🧬 **KẺ MÔ PHỎNG SINH HỌC**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "🔗 Đầu game, bạn chọn 1 Survivor để liên kết cộng sinh.\n\n"
        "💀 Nếu người cộng sinh bị giết trước → bạn nhận 1 lần miễn nhiễm sát thương ban đêm.\n"
        "🚪 Nếu bạn bị Cách Ly/trục xuất → người cộng sinh bị loại theo.\n\n"
        "👥 Bạn biết danh tính toàn bộ đồng đội Dị Thể.\n"
        "🎯 Mục tiêu: Ẩn náu trong bóng tối nhờ liên kết sinh học để sống sót."
    )

    max_count = 1

    def __init__(self, player):
        super().__init__(player)
        self.host_id = None
        self.link_used = False
        self.night_immunity = False

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


    # =========================================
    # GỬI UI BAN ĐÊM (chỉ nếu chưa có host)
    # =========================================
    async def send_ui(self, game):

        if self.host_id is not None:
            return

        alive = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
            and getattr(game.roles.get(p.id), "team", None) == "Survivors"
        ]

        if not alive:
            return

        view = self.MimicView(game, self, alive)

        await self.safe_send(
            "🧬 Chọn một Survivor để Cộng Sinh (không thể đổi sau khi chọn):",
            view=view
        )

    # =========================================
    # VIEW CHỌN HOST
    # =========================================
    class MimicView(disnake.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                disnake.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]
            self.add_item(TheBioMimic.MimicSelect(game, role, options))

    class MimicSelect(disnake.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role

            super().__init__(
                placeholder="Chọn mục tiêu cộng sinh...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):

            target_id = int(self.values[0])

            target_role = self.game.roles.get(target_id)
            if not target_role or target_role.team != "Survivors":
                await interaction.response.send_message(
                    "Chỉ có thể cộng sinh với Người Sống Sót.",
                    ephemeral=True
                )
                return

            self.role.host_id = target_id

            await interaction.response.send_message(
                "🧬 Liên kết sinh học đã hình thành.",
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)
