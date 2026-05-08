import disnake
from disnake.ui import View, Select, Button
from roles.base_role import BaseRole


# ==========================================
# VIEW CHỌN NGƯỜI CẦN GIAM
# ==========================================

class JailView(View):
    def __init__(self, role, game):
        super().__init__(timeout=60)
        self.role = role
        self.game = game

        alive_players = [
            p for p in game.get_alive_players()
            if p != role.player and p != role.last_target
        ]

        if not alive_players:
            return

        options = [
            disnake.SelectOption(label=p.display_name, value=str(p.id))
            for p in alive_players
        ][:25]

        select = Select(
            placeholder="🔒 Chọn người để giam giữ...",
            options=options[:25],
            custom_id="jailor_target"
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: disnake.ApplicationCommandInteraction):
        selected_id = int(interaction.data["values"][0])
        target = self.game.get_member(selected_id)

        if not target:
            await interaction.response.send_message("❌ Không tìm thấy người này.", ephemeral=True)
            return

        self.game.set_selected_target(self.role.player, target)

        await interaction.response.edit_message(
            embed=disnake.Embed(
                title="🔒 ĐÃ CHỌN TÙ NHÂN",
                description=(
                    f"Bạn sẽ giam **{target.display_name}** đêm nay.\n\n"
                    f"{'⚠ Bạn còn 1 viên đạn để xử tử họ.' if self.role.has_bullet else '❌ Bạn đã hết đạn.'}"
                ),
                color=0xe67e22
            ),
            view=None
        )


# ==========================================
# VIEW XỬ TỬ TÙ NHÂN (TRONG PHÒNG GIAM)
# ==========================================

class ExecuteView(View):
    def __init__(self, role, game):
        super().__init__(timeout=None)
        self.role = role
        self.game = game

    @disnake.ui.button(label="⚡ XỬ TỬ", style=disnake.ButtonStyle.danger, custom_id="jailor_execute")
    async def execute(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("❌ Bạn không phải Quản Ngục!", ephemeral=True)
            return

        if not self.role.has_bullet:
            await interaction.response.send_message(
                embed=disnake.Embed(
                    title="❌ HẾT ĐẠN",
                    description="Bạn không còn viên đạn nào để xử tử.",
                    color=0x95a5a6
                ),
                ephemeral=True
            )
            return

        if not self.role.current_prisoner:
            await interaction.response.send_message("❌ Không có tù nhân nào!", ephemeral=True)
            return

        button.disabled = True
        await interaction.response.edit_message(view=self)

        await self.role.execute_prisoner(self.game)

        await interaction.followup.send(
            embed=disnake.Embed(
                title="⚡ ĐÃ XỬ TỬ",
                description=f"**{self.role.current_prisoner.display_name}** đã bị xử tử.",
                color=0xe74c3c
            )
        )

    @disnake.ui.button(label="🔓 Tha Cho Họ", style=disnake.ButtonStyle.secondary, custom_id="jailor_release")
    async def release(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("❌ Bạn không phải Quản Ngục!", ephemeral=True)
            return

        await interaction.response.send_message(
            embed=disnake.Embed(
                title="🔓 ĐÃ THA",
                description="Tù nhân sẽ được thả ra vào buổi sáng.",
                color=0x2ecc71
            ),
            ephemeral=True
        )


class Jailor(BaseRole):
    name = "Cai Ngục"
    team = "Survivors"
    max_count = 1
    is_unique = True
    rarity = "rare"

    description = (
        "Mỗi đêm bạn có thể giam giữ 1 người.\n"
        "Người bị giam không thể dùng kỹ năng và không thể bị giết.\n"
        "Bạn có 1 viên đạn để xử tử họ."
    )

    dm_message = (
        "⚖️ **CAI NGỤC**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🌙 Mỗi đêm bạn có thể giam 1 người:\n"
        "  - Người bị giam không thể dùng kỹ năng và không thể bị giết.\n"
        "  - Bạn có thể trò chuyện ẩn danh với tù nhân.\n\n"
        "💥 Bạn có 1 viên đạn để xử tử tù nhân.\n"
        "⚠️ Nếu xử tử sai người thuộc phe Người Sống Sót, bạn sẽ tự mất khả năng hành động.\n"
        "🎯 Mục tiêu: Bảo vệ thị trấn bằng cách vô hiệu hóa kẻ thù đúng lúc."
    )



    def __init__(self, player):
        super().__init__(player)
        self.has_bullet = True
        self.last_target = None
        self.current_prisoner = None

    # ==============================
    # GỬI UI CHỌN TARGET
    # ==============================

    async def send_night_ui(self, game):
        embed = disnake.Embed(
            title="🔒 QUẢN NGỤC - CHỌN TÙ NHÂN",
            description=(
                "Chọn người bạn muốn giam giữ đêm nay.\n\n"
                f"🔫 Viên đạn: {'✅ Còn 1' if self.has_bullet else '❌ Hết đạn'}\n"
                "⚠ Bạn không thể giam cùng người 2 đêm liên tiếp."
            ),
            color=0xe67e22
        )

        if self.last_target:
            embed.set_footer(text=f"Đêm trước đã giam: {self.last_target.display_name}")

        view = JailView(self, game)

        try:
            await self.safe_send(embed=embed, view=view)
        except Exception as e:
            print(f"[ERROR] Không thể gửi DM cho {self.player}: {e}")

    # ==============================
    # BAN ĐÊM
    # ==============================

    async def night_action(self, game):
        target = game.get_selected_target(self.player)

        if not target:
            return

        if self.last_target == target:
            return  # Không cho giam cùng người 2 đêm liên tiếp

        self.current_prisoner = target
        self.last_target = target

        game.block_player(target)
        game.protect_player(target)

        await self.create_private_chat(game, target)

    # ==============================
    # TẠO CHAT RIÊNG + GỬI NÚT XỬ TỬ
    # ==============================

    async def create_private_chat(self, game, target):
        guild = game.guild

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(read_messages=False),
            self.player: disnake.PermissionOverwrite(read_messages=True, send_messages=True),
            target: disnake.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        channel = await guild.create_text_channel(
            name=f"cell-{target.name}",
            overwrites=overwrites
        )

        game.temp_channels.append(channel)

        # Thông báo trong phòng giam
        await channel.send(
            embed=disnake.Embed(
                title="🔒 PHÒNG GIAM",
                description=(
                    f"{target.mention} đã bị giam giữ.\n\n"
                    "Bạn không thể dùng kỹ năng đêm nay và sẽ được bảo vệ khỏi các cuộc tấn công."
                ),
                color=0xe67e22
            )
        )

        # Gửi nút xử tử cho Jailor qua DM
        if self.has_bullet:
            await self.safe_send(
                embed=disnake.Embed(
                    title="⚡ QUYẾT ĐỊNH CỦA QUẢN NGỤC",
                    description=f"Bạn có muốn xử tử **{target.display_name}** không?",
                    color=0xe74c3c
                ),
                view=ExecuteView(self, game)
            )

    # ==============================
    # XỬ TỬ
    # ==============================

    async def execute_prisoner(self, game):
        if not self.has_bullet:
            return

        if not self.current_prisoner:
            return

        self.has_bullet = False
        await game.kill_player(self.current_prisoner, reason="Bị Quản Ngục xử tử")

    # ==============================
    # RESET
    # ==============================

    async def on_death(self, game):
        await super().on_death(game)
        self.current_prisoner = None

