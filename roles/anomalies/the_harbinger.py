import discord
from roles.base_role import BaseRole


class TheHarbinger(BaseRole):
    name = "Sứ Giả Tận Thế"
    team = "Anomalies"
    max_count = 1

    description = """
    Mỗi đêm đánh dấu một mục tiêu. 
    Khi có đủ 3 người bị đánh dấu còn sống, 
    Harbinger có thể kích hoạt để tiêu diệt cả 3 cùng lúc vào đêm sau. 
    Đêm kích hoạt đó, phe Dị Thể không được chọn mục tiêu khác.
    """

    dm_message = (
        "☠️ **SỨ GIẢ TẬN THẾ**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "🔴 Mỗi đêm bạn đánh dấu 1 người.\n"
        "   Khi đủ 3 người bị đánh dấu còn sống → bạn có thể kích hoạt.\n\n"
        "💥 Khi kích hoạt: Tiêu diệt cả 3 mục tiêu cùng lúc vào đêm sau.\n"
        "   ⚠️ Đêm kích hoạt, phe Dị Thể KHÔNG chọn được mục tiêu khác.\n\n"
        "👥 Bạn biết danh tính toàn bộ đồng đội Dị Thể.\n"
        "🎯 Mục tiêu: Tích lũy dấu để thực hiện cú diệt hàng loạt."
    )


    def __init__(self, player):
        super().__init__(player)
        self.marked = set()
        self.mark_order = []
        self.can_mark = True
        self.mass_kill_ready = False
        self.cooldown = False

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


    # =========================================
    # GỬI UI BAN ĐÊM
    # =========================================
    async def send_ui(self, game):

        if not self.can_mark:
            return

        # Nếu đủ 3 người sống bị đánh dấu → cho phép kích hoạt
        alive_marked = [
            pid for pid in self.marked
            if game.is_alive(pid)
        ]

        if len(alive_marked) >= 3 and not self.mass_kill_ready:
            view = self.ActivateView(game, self)
            try:  # BUG FIX #16: wrap tất cả player.send() trong try/except
                await self.safe_send(
                    "☠️ Bạn đã có đủ 3 mục tiêu bị đánh dấu.\n"
                    "Bạn có muốn kích hoạt Tiêu Diệt Hàng Loạt không?",
                    view=view
                )
            except Exception:
                pass
            return

        # Nếu đang cooldown
        if self.cooldown:
            try:
                await self.safe_send("Bạn đang hồi phục sau vụ thảm sát.")
            except Exception:
                pass
            self.cooldown = False
            return

        # Chọn người để đánh dấu
        alive = [
            p for p in game.get_alive_players()
            if p.id not in self.marked and p.id != self.player.id
        ]

        if not alive:
            return

        view = self.MarkView(game, self, alive)

        try:  # BUG FIX #16
            await self.safe_send(
                f"☠️ Đã đánh dấu: {len(self.marked)}/3\n"
                "Chọn người để Đánh Dấu:",
                view=view
            )
        except Exception:
            pass

    # =========================================
    # VIEW CHỌN ĐÁNH DẤU
    # =========================================
    class MarkView(discord.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                discord.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]
            self.add_item(TheHarbinger.MarkSelect(game, role, options))

    class MarkSelect(discord.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role

            super().__init__(
                placeholder="Chọn mục tiêu...",
                options=options,
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):

            target_id = int(self.values[0])

            self.role.marked.add(target_id)
            self.role.mark_order.append(target_id)

            await interaction.response.send_message(
                "☠️ Mục tiêu đã bị đánh dấu.",
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)

    # =========================================
    # VIEW KÍCH HOẠT MASS KILL
    # =========================================
    class ActivateView(discord.ui.View):
        def __init__(self, game, role):
            super().__init__(timeout=60)
            self.game = game
            self.role = role

        @discord.ui.button(label="☠️ Kích Hoạt", style=discord.ButtonStyle.danger)
        async def activate(self, interaction: discord.Interaction, button: discord.ui.Button):

            alive_marked = [
                pid for pid in self.role.marked
                if self.game.is_alive(pid)
            ]

            if len(alive_marked) < 3:
                await interaction.response.send_message(
                    "Không đủ 3 mục tiêu còn sống.",
                    ephemeral=True
                )
                return

            # Đánh dấu để engine xử lý cuối đêm
            self.role.mass_kill_ready = True

            await interaction.response.send_message(
                "☠️ Dấu hiệu đã được triệu hồi...",
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)
