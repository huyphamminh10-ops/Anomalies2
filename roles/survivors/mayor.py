import discord
from discord.ui import View, Button
from discord import Embed

class Mayor:
    name = "Thị Trưởng"
    team = "Survivors"
    max_count = 1
    description = (
        "Bạn là Thị Trưởng – người được dân thị trấn tin tưởng nhất.\n"
        "Bạn có thể lộ diện để phiếu bầu có hệ số x3.\n"
        "Bạn có 3 viên đạn để phản đòn nếu bị Dị Thể tấn công."
    )

    dm_message = (
        "🏛️ **MAYOR – THỊ TRƯỞNG**\n\n"
        "Bạn thuộc phe **Survivors**.\n\n"
        "👑 Bạn là thủ lĩnh của thị trấn — phiếu bầu có hệ số x3 khi lộ diện.\n\n"
        "🔓 Lộ Diện: Tiết lộ bạn là Thị Trưởng để kích hoạt hiệu ứng phiếu.\n"
        "🔫 Bạn có 3 viên đạn để phản công nếu bị Dị Thể tấn công.\n"
        "⚠️ Một khi lộ diện, bạn trở thành mục tiêu ưu tiên của kẻ thù!\n"
        "🎯 Mục tiêu: Dẫn dắt thị trấn đến chiến thắng."
    )


    def __init__(self, player):
        self.player = player
        self.revealed = False
        self.bullets = 3
        self.original_nick = None

    # ==============================
    # GỬI DM NÚT LỘ DIỆN
    # ==============================

    async def send_reveal_button(self):
        embed = Embed(
            title="🏛 THỊ TRƯỞNG",
            description="Bạn có muốn lộ diện để tăng sức nặng phiếu bầu không?",
            color=0xf1c40f
        )

        view = RevealView(self)

        try:
            await self.safe_send(embed=embed, view=view)
        except:
            print(f"[ERROR] Không thể gửi DM cho {self.player}")

    # ==============================
    # KHI BỊ TẤN CÔNG BAN ĐÊM
    # ==============================

    async def on_attacked(self, game, anomalies_group):
        if self.bullets > 0:
            self.bullets -= 1

            # Giết 1 dị thể trong nhóm vote
            if anomalies_group:
                target = anomalies_group[0]
                await game.kill_player(target, reason="Bị Thị Trưởng phản đòn")

            return False  # Không chết

        return True  # Hết đạn → chết bình thường

    # ==============================
    # HỆ SỐ VOTE
    # ==============================

    def vote_weight(self):
        return 3 if self.revealed else 1

    # ==============================
    # RESET SAU GAME
    # ==============================

    async def reset_nickname(self):
        if self.original_nick:
            try:
                await self.player.edit(nick=self.original_nick)
            except:
                pass


# ==========================================
# VIEW CHỨA NÚT LỘ DIỆN
# ==========================================

class RevealView(View):
    def __init__(self, role):
        super().__init__(timeout=None)
        self.role = role

    @discord.ui.button(label="LỘ DIỆN", style=discord.ButtonStyle.danger)
    async def reveal(self, interaction: discord.Interaction, button: Button):

        if self.role.revealed:
            await interaction.response.send_message(
                "Bạn đã lộ diện rồi!",
                ephemeral=True
            )
            return

        self.role.revealed = True

        guild = interaction.guild
        member = guild.get_member(self.role.player.id)

        self.role.original_nick = member.nick

        try:
            await member.edit(nick="THỊ TRƯỞNG")
        except:
            print("[ERROR] Không thể đổi nickname Thị Trưởng")

        await interaction.response.send_message(
            "Bạn đã lộ diện trước toàn thị trấn!",
            ephemeral=True
        )

        # Gửi log trận đấu
        if hasattr(interaction.client, "game_log_channel"):
            log_channel = interaction.client.game_log_channel
            embed = Embed(
                title="🏛 THÔNG BÁO",
                description="Thị Trưởng đã lộ diện trước toàn thị trấn!",
                color=0xf1c40f
            )
            await log_channel.send(embed=embed)
