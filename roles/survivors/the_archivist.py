import discord
from roles.base_role import BaseRole


class TheArchivist(BaseRole):
    name = "Nhà Lưu Trữ"
    team = "Survivors"
    max_count = 1

    def __init__(self, player):
        super().__init__(player)
        self.read_history = set()
        self.used_tonight = False

    description = (
        "Mỗi đêm bạn có thể bí mật đọc di chúc của những người đã chết.\n\n"
        "• Chỉ có thể đọc di chúc của người chưa được đọc trước đó.\n"
        "• Thông tin chỉ được gửi riêng cho bạn — không hiển thị công khai.\n"
        "• Nếu người đó không để lại di chúc, bạn sẽ nhận được thông báo tương ứng."
    )

    dm_message = (
        "📚 **NHÀ LƯU TRỮ**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 người đã chết để đọc di chúc bí mật của họ.\n\n"
        "📋 Cơ chế:\n"
        "• Mỗi người chỉ được đọc 1 lần.\n"
        "• Thông tin chỉ gửi riêng cho bạn.\n"
        "• Nếu di chúc bị Glitch-Worm phá hủy hoặc không tồn tại, bạn sẽ thấy thông báo.\n\n"
        "💡 Đây là công cụ điều tra ngầm — khai thác thông tin người chết trước khi bị xóa."
    )

    # ==================================
    # GỬI UI BAN ĐÊM
    # ==================================
    async def send_ui(self, game):

        self.used_tonight = False

        dead_players = game.get_dead_players()

        available = [
            p for p in dead_players
            if p.id not in self.read_history
        ]

        if not available:
            await self.safe_send("📚 Không có di chúc nào để đọc.")
            return

        view = self.ArchivistView(game, self, available)
        await self.safe_send("📚 Chọn người đã chết để đọc di chúc:", view=view)

    # ==================================
    # VIEW
    # ==================================
    class ArchivistView(discord.ui.View):
        def __init__(self, game, role, dead_list):
            super().__init__(timeout=60)
            options = [
                discord.SelectOption(
                    label=p.display_name,
                    value=str(p.id)
                )
                for p in dead_list
            ][:25]

            self.add_item(TheArchivist.ArchivistSelect(game, role, options))

    # ==================================
    # SELECT
    # ==================================
    class ArchivistSelect(discord.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role

            super().__init__(
                placeholder="Chọn người đã chết...",
                options=options,
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):

            if self.role.used_tonight:
                await interaction.response.send_message(
                    "Bạn đã đọc di chúc đêm nay rồi.",
                    ephemeral=True
                )
                return

            target_id = int(self.values[0])
            target = self.game.get_member(target_id)

            will_text = self.game.wills.get(target_id)

            if not will_text:
                will_text = "✖ Người này không để lại di chúc."

            self.role.read_history.add(target_id)
            self.role.used_tonight = True

            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"📖 DI CHÚC CỦA {target.display_name}",
                    description=will_text,
                    color=0x95a5a6
                ),
                ephemeral=True
            )

            # Disable UI
            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)
