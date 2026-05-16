import disnake
from roles.base_role import BaseRole


class ThePuppeteer(BaseRole):
    name = "Kẻ Điều Khiển"
    team = "Anomalies"
    max_count = 1
    dif = 12

    description = (
        "Bạn điều khiển tâm trí Người Sống Sót, ép họ bỏ phiếu theo ý muốn của mình vào ban ngày.\n\n"
        "• Mỗi đêm chọn 1 Survivor và 1 mục tiêu vote — sáng hôm sau họ bị ép vote đó.\n"
        "• Không thể điều khiển cùng 1 người 2 lần liên tiếp.\n"
        "• Có **3 lượt** sử dụng trong suốt trận.\n\n"
        "⚠ **Nerf:**\n"
        "• Bạn **không tham gia bỏ phiếu** cũng như không giết người.\n"
        "• Nếu mục tiêu bị **Jailor giam**, bạn sẽ tự tay vote thay vì điều khiển họ."
    )

    dm_message = (
        "🎭 **KẺ ĐIỀU KHIỂN**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "🌙 Mỗi đêm bạn gắn sợi dây vô hình vào 1 Survivor — sáng hôm sau họ bị ép vote theo lệnh của bạn.\n\n"
        "📋 Cơ chế:\n"
        "• Chọn nạn nhân → chọn người họ sẽ bị ép vote.\n"
        "• Không điều khiển được cùng 1 người 2 đêm liên tiếp.\n"
        "• Bạn có **3 lượt** điều khiển trong cả trận.\n\n"
        "⚠ **Giới hạn (Nerf):**\n"
        "• Bạn **không được tham gia bỏ phiếu** ban ngày.\n"
        "• Nếu mục tiêu bị Jailor giam → bạn sẽ tự vote thay cho họ.\n\n"
        "💡 Hãy dùng để loại bỏ Người Sống Sót quan trọng hoặc bảo vệ đồng đội khỏi bị vote."
    )

    def __init__(self, player):
        super().__init__(player)
        self.uses_left = 3
        self.last_controlled = None
        self.control_data = None
        self.can_vote = False  # Nerf: Puppeteer không được tham gia bỏ phiếu

    def apply_control(self, game):
        """
        Gọi vào đầu phase ban ngày để áp dụng điều khiển.
        Nếu nạn nhân đang bị Jailor giam → Puppeteer tự vote thay.
        """
        if not self.control_data:
            return
        victim_id, forced_vote_id = self.control_data
        self.control_data = None

        # Kiểm tra nếu nạn nhân bị Jailor giam
        jailed_ids = getattr(game, "jailed_player_ids", set())
        if victim_id in jailed_ids:
            # Puppeteer tự vote thay
            game.force_vote(self.player.id, forced_vote_id)
        else:
            # Điều khiển bình thường
            game.force_vote(victim_id, forced_vote_id)

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


    # ==================================
    # GỬI UI BAN ĐÊM
    # ==================================
    async def send_ui(self, game):

        if self.uses_left <= 0:
            await self.safe_send(
                embed=disnake.Embed(
                    title="🎭 ĐÊM — THE PUPPETEER",
                    description="❌ Bạn đã hết **3 lượt** Điều Khiển.",
                    color=0x7f8c8d
                )
            )
            return

        alive = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
        ]

        if not alive:
            return

        view = self.PuppeteerTargetView(game, self, alive)
        await self.safe_send(
            embed=disnake.Embed(
                title="🎭 ĐÊM — THE PUPPETEER",
                description=f"🎭 Bạn còn **{self.uses_left}/3 lượt**.\nChọn Survivor để điều khiển:",
                color=0x9b59b6
            ),
            view=view
        )

    # ==================================
    # VIEW 1: CHỌN NẠN NHÂN
    # ==================================
    class PuppeteerTargetView(disnake.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                disnake.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25][:25][:25]
            self.add_item(ThePuppeteer.PuppeteerTargetSelect(game, role, options))

    class PuppeteerTargetSelect(disnake.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role
            super().__init__(
                placeholder="Chọn người bị điều khiển...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message(
                    "Đây không phải lượt của bạn.", ephemeral=True
                )
                return

            victim_id = int(self.values[0])

            if self.role.last_controlled == victim_id:
                await interaction.response.send_message(
                    "Bạn không thể điều khiển cùng một người 2 lần liên tiếp.",
                    ephemeral=True
                )
                return

            victim_role = self.game.roles.get(victim_id)

            if not victim_role or victim_role.team != "Survivors":
                await interaction.response.send_message(
                    "Chỉ có thể điều khiển Survivor.",
                    ephemeral=True
                )
                return

            alive = self.game.get_alive_players()

            view = ThePuppeteer.PuppeteerVoteView(
                self.game, self.role, victim_id, alive
            )

            # Vô hiệu hóa Select chọn nạn nhân ngay sau khi chọn
            for item in self.view.children:
                item.disabled = True
            self.placeholder = "✅ Đã chọn nạn nhân"
            await interaction.response.edit_message(view=self.view)

            await interaction.followup.send(
                "Chọn mục tiêu mà họ sẽ bị ép vote:",
                view=view,
                ephemeral=True
            )

    # ==================================
    # VIEW 2: CHỌN MỤC TIÊU VOTE
    # ==================================
    class PuppeteerVoteView(disnake.ui.View):
        def __init__(self, game, role, victim_id, alive_list):
            super().__init__(timeout=60)
            options = [
                disnake.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]
            self.add_item(ThePuppeteer.PuppeteerVoteSelect(
                game, role, victim_id, options
            ))

    class PuppeteerVoteSelect(disnake.ui.Select):
        def __init__(self, game, role, victim_id, options):
            self.game = game
            self.role = role
            self.victim_id = victim_id

            super().__init__(
                placeholder="Chọn mục tiêu bị ép vote...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):

            forced_vote_id = int(self.values[0])

            self.role.control_data = (self.victim_id, forced_vote_id)
            self.role.last_controlled = self.victim_id
            self.role.uses_left -= 1

            await interaction.response.send_message(
                "🎭 Điều khiển thành công. Sáng mai họ sẽ bị ép bỏ phiếu.",
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)
