import discord
from roles.base_role import BaseRole


class MayorAide(BaseRole):
    name = "Phụ Tá Thị Trưởng"
    team = "Survivors"
    max_count = 1
    rarity = "common"

    description = (
        "Bạn biết ai là Thị Trưởng ngay từ đầu trận.\n"
        "Hãy phối hợp để dẫn dắt thị trấn."
    )

    dm_message = (
        "🤝 **PHỤ TÁ THỊ TRƯỞNG**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🔎 Bạn biết danh tính Thị Trưởng ngay từ đầu trận.\n"
        "📊 Hãy theo dõi trạng thái sống/chết của Thị Trưởng mỗi đêm.\n\n"
        "💡 Phối hợp cùng Thị Trưởng để lãnh đạo thị trấn hiệu quả.\n"
        "⚠️ Nếu lộ diện quá sớm, bạn có thể bị kẻ thù nhắm tới.\n"
        "🎯 Mục tiêu: Hỗ trợ và bảo vệ Thị Trưởng đến cuối game."
    )


    def __init__(self, player):
        super().__init__(player)
        self.mayor = None

    # ==============================
    # GỬI UI BAN ĐÊM — Hiển thị thông tin Mayor và trạng thái
    # ==============================

    async def send_ui(self, game):
        mayor_role = game.get_role_by_name("Thị Trưởng")
        status_desc = "❌ Thị Trưởng chưa được xác định." if not mayor_role else (
            f"🏛️ Thị Trưởng: **{mayor_role.player.display_name}**\n"
            f"❤️ Trạng thái: {'🟢 Còn sống' if game.is_alive(mayor_role.player.id) else '💀 Đã chết'}"
        )

        view = self.AideNightView(self, mayor_role)
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="👔 ĐÊM — TRỢ LÝ THỊ TRƯỞNG",
                    description=(
                        f"{status_desc}\n\n"
                        "Bạn không có hành động đặc biệt vào ban đêm.\n"
                        "Hãy bảo vệ Thị Trưởng vào ban ngày."
                    ),
                    color=0x2ecc71
                ),
                view=view
            )
        except Exception:
            pass

    class AideNightView(discord.ui.View):
        def __init__(self, role, mayor_role):
            super().__init__(timeout=60)
            self.role       = role
            self.mayor_role = mayor_role

        @discord.ui.button(label="🏛️ Xem thông tin Thị Trưởng", style=discord.ButtonStyle.primary)
        async def view_mayor(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            if not self.mayor_role:
                await interaction.response.send_message("Chưa có Thị Trưởng trong trận này.", ephemeral=True)
                return

            await interaction.response.send_message(
                embed=discord.Embed(
                    title="🏛️ THÔNG TIN THỊ TRƯỞNG",
                    description=(
                        f"👤 Tên: **{self.mayor_role.player.display_name}**\n"
                        f"🆔 ID: `{self.mayor_role.player.id}`"
                    ),
                    color=0x2ecc71
                ),
                ephemeral=True
            )

    # ==============================
    # KHI GAME BẮT ĐẦU
    # ==============================

    async def on_game_start(self, game):
        self.mayor = game.get_role_by_name("Thị Trưởng")

        if self.mayor:
            try:
                await self.safe_send(
                    embed=discord.Embed(
                        title="👔 TRỢ LÝ THỊ TRƯỞNG",
                        description=(
                            f"🏛️ Thị Trưởng là: {self.mayor.player.mention}\n\n"
                            "Hãy hỗ trợ và bảo vệ họ trong suốt trận đấu."
                        ),
                        color=0x2ecc71
                    )
                )
            except Exception:
                pass

    # ==============================
    # KHI MAYOR CHẾT
    # ==============================

    async def on_other_death(self, game, dead_player):
        if self.mayor and dead_player == self.mayor.player:
            try:
                await self.safe_send(
                    embed=discord.Embed(
                        title="⚠️ CẢNH BÁO",
                        description=(
                            "💀 **Thị Trưởng đã chết.**\n\n"
                            "Hãy dẫn dắt thị trấn một mình từ bây giờ."
                        ),
                        color=0xe74c3c
                    )
                )
            except Exception:
                pass
