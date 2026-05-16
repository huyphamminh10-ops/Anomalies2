import disnake
from roles.base_role import BaseRole


class Sheriff(BaseRole):
    name      = "Thám Trưởng"
    team      = "Survivors"
    max_count = 1
    dif = 3

    description = (
        "Mỗi đêm bạn có thể kiểm tra 1 người chơi và biết chính xác vai trò của họ.\n\n"
        "• Kết quả trả về tên vai trò cụ thể.\n"
        "• Nếu mục tiêu đang dùng khả năng giả mạo (fake_good), bạn sẽ thấy kết quả không đáng ngờ.\n"
        "• Nếu phát hiện Anomaly, cảnh báo ẩn danh sẽ gửi vào kênh Dị Thể.\n"
        "• **Chỉ có 2 lượt kiểm tra trong toàn bộ trận** — hãy sử dụng khôn ngoan!\n"
        "• Bạn có thể bỏ qua đêm để tiết kiệm lượt."
    )

    dm_message = (
        "👮 **THÁM TRƯỞNG**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 người để kiểm tra danh tính.\n"
        "Kết quả cho biết chính xác vai trò của họ.\n\n"
        "⚠ **Giới hạn: 2 lượt trong toàn bộ trận.**\n"
        "💡 Bạn có thể bỏ qua đêm để tiết kiệm lượt cho lúc quan trọng hơn."
    )

    def __init__(self, player):
        super().__init__(player)
        self.uses_left = 2  # Tổng 2 lần cả trận

    async def send_ui(self, game):
        view = SheriffView(game, self)
        await self.safe_send(
            embed=disnake.Embed(
                title="👮 ĐÊM — THÁM TRƯỞNG",
                description=(
                    f"🔍 Bạn còn **{self.uses_left}/2 lượt** kiểm tra.\n\n"
                    "Chọn 1 người để kiểm tra danh tính chính xác, hoặc bỏ qua đêm nay:"
                ),
                color=0x2ecc71
            ),
            view=view
        )


class SheriffSelect(disnake.ui.Select):
    def __init__(self, game, role):
        self.game = game
        self.role = role

        options = [
            disnake.SelectOption(label=p.display_name, value=str(p.id))
            for p in game.get_alive_players()
            if p != role.player
        ][:25]

        super().__init__(
            placeholder="Chọn mục tiêu kiểm tra...",
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

        if self.role.uses_left <= 0:
            await interaction.response.send_message(
                "⚠️ Bạn đã hết **2 lượt** kiểm tra rồi.", ephemeral=True
            )
            return

        self.role.uses_left -= 1

        target      = self.game.get_member(int(self.values[0]))
        target_role = self.game.get_role(target)
        if not target_role:
            await interaction.response.send_message("❌ Không thể xác định vai trò mục tiêu.", ephemeral=True)
            return

        # Nếu đang Cải Trang → trả về role cải trang
        if hasattr(target_role, "disguise_role") and target_role.disguise_role:
            result = f"Người này đang là: **{target_role.disguise_role}**"
            color  = 0xf39c12
        # Nếu là Mimic giả tốt
        elif hasattr(target_role, "fake_good") and target_role.fake_good:
            result = "🟢 Không phát hiện điều gì đáng ngờ."
            color  = 0x2ecc71
        else:
            result = f"Người này là: **{target_role.name}**"
            color  = 0x2ecc71

            # ── Cảnh báo Dị Thể nếu kết quả lộ vai Anomaly ──
            if getattr(target_role, "team", "") == "Anomalies":
                if hasattr(self.game, "anomaly_chat_mgr"):
                    await self.game.anomaly_chat_mgr.send(
                        embed=disnake.Embed(
                            title="👮 CẢNH BÁO THÁM TRƯỞNG",
                            description=(
                                "**THÁM TRƯỞNG** đã điều tra và xác định được "
                                "danh tính của một thành viên phe Dị Thể!\n\n"
                                "🚨 Nguy hiểm — danh tính chính xác của **một người trong phe** "
                                "đã bị lộ!\n"
                                "Hãy **thảo luận ngay** trong kênh này để đưa ra phương án ứng phó."
                            ),
                            color=0xff0000
                        )
                    )

        # Vô hiệu hóa View sau khi dùng
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(view=self.view)
        await interaction.followup.send(
            embed=disnake.Embed(
                title=f"👮 KẾT QUẢ KIỂM TRA (còn {self.role.uses_left} lượt)",
                description=result,
                color=color
            ),
            ephemeral=True
        )


class SheriffView(disnake.ui.View):
    def __init__(self, game, role):
        super().__init__(timeout=60)
        self.game = game
        self.role = role

        if role.uses_left > 0:
            self.add_item(SheriffSelect(game, role))

        self.add_item(SheriffSkipButton(role))


class SheriffSkipButton(disnake.ui.Button):
    def __init__(self, role):
        self.role = role
        super().__init__(
            label="💤 Bỏ qua đêm nay",
            style=disnake.ButtonStyle.secondary,
            row=1
        )

    async def callback(self, interaction: disnake.MessageInteraction):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
            return
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(view=self.view)
        await interaction.followup.send(
            f"💤 Bạn bỏ qua đêm nay. Còn **{self.role.uses_left}/2** lượt.",
            ephemeral=True
        )
