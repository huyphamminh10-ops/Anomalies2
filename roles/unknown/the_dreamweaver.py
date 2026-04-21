import discord
from roles.base_role import BaseRole


class TheDreamweaver(BaseRole):
    name = "Kẻ Dệt Mộng"
    team = "Unknown"
    max_count = 1

    def __init__(self, player):
        super().__init__(player)
        self.dream_pairs   = []
        self.max_pairs     = 3
        self.last_selected = set()

    description = (
        "Bạn dệt giấc mơ — liên kết tâm trí hai người chơi và tiết lộ vai trò của họ cho nhau.\n\n"
        "• Mỗi đêm chọn 2 người để dệt cặp Giấc Mơ — cả hai sẽ biết vai trò của nhau.\n"
        "• Tối đa dệt **3 cặp** trong cả trận. Không thể tái chọn người đã dùng đêm trước.\n"
        "• Điều kiện thắng: Cả 3 cặp (6 người) đều còn sống cùng lúc."
    )

    dm_message = (
        "🌙 **THE DREAMWEAVER – NGƯỜI DỆT GIẤC MƠ**\n\n"
        "Bạn thuộc phe **Unknown** — không giết, chỉ dệt sợi liên kết.\n\n"
        "🌙 Mỗi đêm bạn chọn 2 người để kết nối tâm trí — họ sẽ thấy vai trò của nhau trong giấc mơ.\n\n"
        "📋 Cơ chế:\n"
        "• Cả 2 người trong cặp đều nhận DM biết vai trò của nhau.\n"
        "• Tối đa **3 cặp** (6 người riêng biệt). Không tái chọn người đã dùng đêm trước.\n\n"
        "🏆 Điều kiện thắng: Cả 3 cặp đều còn sống đồng thời.\n"
        "⚠ Thách thức: Duy trì 6 người cùng sống sót trong khi thị trấn đang loại người mỗi ngày."
    )

    # ================================
    # ĐIỀU KIỆN THẮNG
    # ================================
    def check_win_condition(self, game):
        if len(self.dream_pairs) < 3:
            return False

        for id1, id2 in self.dream_pairs:
            if not game.is_alive(id1) or not game.is_alive(id2):
                return False

        return True

    # ================================
    # GỬI UI BAN ĐÊM
    # ================================
    async def send_ui(self, game):

        if len(self.dream_pairs) >= self.max_pairs:
            await self.safe_send("🌙 Bạn đã tạo đủ 3 cặp Giấc Mơ.")
            return

        alive = [
            p for p in game.get_alive_players()
            if p.id not in self.last_selected
        ]

        view = self.DreamView(game, self, alive)

        await self.safe_send(
            "🌙 Chọn 2 người để Dệt Giấc Mơ:",
            view=view
        )

    # ================================
    # VIEW
    # ================================
    class DreamView(discord.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                discord.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]
            self.add_item(TheDreamweaver.DreamSelect(game, role, options))

    class DreamSelect(discord.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role

            super().__init__(
                placeholder="Chọn 2 người...",
                options=options,
                min_values=2,
                max_values=2
            )

        async def callback(self, interaction: discord.Interaction):

            id1 = int(self.values[0])
            id2 = int(self.values[1])

            if id1 == id2:
                await interaction.response.send_message(
                    "Không thể chọn cùng một người.",
                    ephemeral=True
                )
                return

            # Lưu cặp
            self.role.dream_pairs.append((id1, id2))
            self.role.last_selected = {id1, id2}

            # Gửi thông tin role cho cả hai
            role1 = self.game.roles.get(id1)
            role2 = self.game.roles.get(id2)

            member1 = self.game.get_member(id1)
            member2 = self.game.get_member(id2)

            await member1.send(
                f"🌙 Bạn đã nằm mơ thấy {member2.display_name}.\n"
                f"Vai trò của họ là: {role2.name}"
            )

            await member2.send(
                f"🌙 Bạn đã nằm mơ thấy {member1.display_name}.\n"
                f"Vai trò của họ là: {role1.name}"
            )

            await interaction.response.send_message(
                "🌙 Giấc mơ đã được dệt.",
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)
