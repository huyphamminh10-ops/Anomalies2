import discord
from roles.base_role import BaseRole


class Vigilante(BaseRole):
    name = "Kẻ Trừng Phạt"
    team = "Survivors"
    max_count = 2
    rarity = "rare"

    description = (
        "Bạn có 3 viên đạn để trừng trị nghi phạm.\n"
        "Nếu bắn ban ngày sẽ bị lộ diện.\n"
        "Không tham gia bỏ phiếu cách ly."
    )

    dm_message = (
        "🔫 **KẺ TRỪNG PHẠT**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "💥 Bạn có 3 viên đạn để trừng phạt kẻ tình nghi bất cứ lúc nào.\n\n"
        "☀️ Bắn ban ngày → bạn bị **lộ diện** trước toàn thị trấn.\n"
        "🌙 Bắn ban đêm → danh tính được giữ bí mật.\n"
        "🚫 Bạn không tham gia bỏ phiếu cách ly.\n"
        "⚠️ Bắn nhầm Survivor có thể làm mất lòng tin của thị trấn!\n"
        "🎯 Mục tiêu: Hành động quyết đoán khi thị trấn do dự."
    )


    def __init__(self, player):
        super().__init__(player)
        self.bullets  = 3
        self.revealed = False

    def vote_weight(self):
        return 0

    # ==============================
    # GỬI UI BAN ĐÊM — Chọn bắn hoặc bỏ qua
    # ==============================

    async def send_ui(self, game):
        if self.bullets <= 0:
            try:
                await self.safe_send(
                    embed=discord.Embed(
                        title="🔫 ĐÊM — CẢNH BINH TỰ PHÁT",
                        description="❌ Bạn đã hết đạn. Không thể hành động đêm nay.",
                        color=0x7f8c8d
                    )
                )
            except Exception:
                pass
            return

        alive_targets = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
        ]

        if not alive_targets:
            return

        view = self.VigilanteView(game, self, alive_targets)
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="🔫 ĐÊM — CẢNH BINH TỰ PHÁT",
                    description=(
                        f"🔫 Đạn còn lại: **{self.bullets}/3**\n\n"
                        "Chọn mục tiêu để bắn đêm nay, hoặc bỏ qua để bảo toàn đạn.\n\n"
                        "⚠️ Nếu bạn bắn nhầm Survivor, lương tâm sẽ giết chết bạn ngay sau đó!"
                    ),
                    color=0xc0392b
                ),
                view=view
            )
        except Exception:
            pass

    # ==============================
    # VIEW
    # ==============================

    class VigilanteView(discord.ui.View):
        def __init__(self, game, role, target_list):
            super().__init__(timeout=60)
            self.add_item(Vigilante.ShootSelect(game, role, target_list))
            self.add_item(Vigilante.SkipButton(role))

    class ShootSelect(discord.ui.Select):
        def __init__(self, game, role, target_list):
            self.game = game
            self.role = role
            options = [
                discord.SelectOption(label=p.display_name, value=str(p.id), emoji="🎯")
                for p in target_list
            ][:25]
            super().__init__(
                placeholder="🔫 Chọn mục tiêu để bắn...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            target_id = int(self.values[0])
            target    = self.game.players.get(target_id)

            if not target:
                await interaction.response.send_message("Mục tiêu không hợp lệ.", ephemeral=True)
                return

            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)

            await self.role.shoot(self.game, target, is_day=False)

            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"🔫 Bạn đã bắn **{target.display_name}** — đạn còn lại: {self.role.bullets}/3",
                    color=0xc0392b
                ),
                ephemeral=True
            )

    class SkipButton(discord.ui.Button):
        def __init__(self, role):
            super().__init__(label="💤 Bỏ qua đêm nay", style=discord.ButtonStyle.secondary)
            self.role = role

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)
            await interaction.response.send_message(
                f"💤 Bạn bỏ qua đêm nay. Đạn còn lại: **{self.role.bullets}/3**",
                ephemeral=True
            )

    # ==============================
    # BẮN
    # ==============================

    async def shoot(self, game, target, is_day=False):
        if self.bullets <= 0 or target == self.player:
            return

        # BUG FIX #15: Kiểm tra target còn sống trước khi tốn đạn
        target_id = target.id if hasattr(target, "id") else target
        if not game.is_alive(target_id):
            try:
                await self.safe_send("⚠️ Mục tiêu đã chết rồi — không tốn đạn.")
            except Exception:
                pass
            return

        self.bullets -= 1
        target_role = game.roles.get(target_id)
        await game.kill_player(target, reason="Bị Vigilante bắn")

        if is_day and not self.revealed:
            self.revealed = True
            member = game.guild.get_member(self.player.id)
            try:
                await member.edit(nick="VIGILANTE")
            except Exception:
                pass

            await game.log_channel.send(
                embed=discord.Embed(
                    description="🔫 Một Cảnh Binh Tự Phát đã nổ súng!",
                    color=0xc0392b
                )
            )

        # BUG FIX #14: Nếu bắn nhầm Survivor → lương tâm giết bản thân
        if target_role and getattr(target_role, "team", "") == "Survivors":
            try:
                await self.safe_send(
                    embed=discord.Embed(
                        title="💀 LƯƠNG TÂM CẮN RỨT",
                        description=(
                            "Bạn đã bắn nhầm một **Survivor vô tội**!\n"
                            "Lương tâm không cho phép bạn tiếp tục sống..."
                        ),
                        color=0x8e44ad
                    )
                )
            except Exception:
                pass
            vigilante_member = game.get_member(self.player.id)
            if vigilante_member and game.is_alive(self.player.id):
                await game.kill_player(vigilante_member, reason="Tự trừng phạt vì bắn nhầm Survivor", bypass=True)
