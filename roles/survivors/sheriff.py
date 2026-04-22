import discord
from roles.base_role import BaseRole


class Sheriff(BaseRole):
    name      = "Thám Trưởng"
    team      = "Survivors"
    max_count = 1

    description = (
        "Mỗi đêm bạn có thể kiểm tra 1 người chơi và biết chính xác vai trò của họ.\n\n"
        "• Kết quả trả về tên vai trò cụ thể.\n"
        "• Nếu mục tiêu đang dùng khả năng giả mạo (fake_good), bạn sẽ thấy kết quả không đáng ngờ.\n"
        "• Nếu phát hiện Anomaly, cảnh báo ẩn danh sẽ gửi vào kênh Dị Thể.\n"
        "• Đây là nguồn thông tin mạnh nhất của Người Sống Sót — hãy sử dụng khôn ngoan."
    )

    dm_message = (
        "👮 **THÁM TRƯỞNG**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 người để kiểm tra danh tính.\n"
        "Kết quả cho biết chính xác vai trò của họ.\n\n"
        "⚠ Chú ý: Một số Dị Thể có thể dùng khả năng đánh lừa kết quả điều tra.\n"
        "💡 Thông tin của bạn rất quý giá — hãy cân nhắc khi nào nên tiết lộ với thị trấn."
    )

    async def send_ui(self, game):
        view = SheriffView(game, self)
        await self.safe_send(
            embed=discord.Embed(
                title="👮 ĐÊM — CẢNH SÁT TRƯỞNG",
                description="Chọn 1 người để kiểm tra danh tính chính xác:",
                color=0x2ecc71
            ),
            view=view
        )


class SheriffSelect(discord.ui.Select):
    def __init__(self, game, role):
        self.game = game
        self.role = role

        options = [
            discord.SelectOption(label=p.display_name, value=str(p.id))
            for p in game.get_alive_players()
            if p != role.player
        ][:25]

        super().__init__(
            placeholder="Chọn mục tiêu kiểm tra...",
            options=options[:25],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        target      = self.game.get_member(int(self.values[0]))
        target_role = self.game.get_role(target)
        if not target_role:
            await interaction.response.send_message("❌ Không thể xác định vai trò mục tiêu.", ephemeral=True)
            return

        # Nếu là Mimic giả tốt
        if hasattr(target_role, "fake_good") and target_role.fake_good:
            result = "🟢 Không phát hiện điều gì đáng ngờ."
            color  = 0x2ecc71
        else:
            result = f"Người này là: **{target_role.name}**"
            color  = 0x2ecc71

            # ── Cảnh báo Dị Thể nếu kết quả lộ vai Anomaly ──
            if getattr(target_role, "team", "") == "Anomalies":
                if hasattr(self.game, "anomaly_chat_mgr"):
                    await self.game.anomaly_chat_mgr.send(
                        embed=discord.Embed(
                            title="👮 CẢNH BÁO CẢNH SÁT",
                            description=(
                                "**CẢNH SÁT TRƯỞNG** đã điều tra và xác định được "
                                "danh tính của một thành viên phe Dị Thể!\n\n"
                                "🚨 Nguy hiểm — danh tính chính xác của **một người trong phe** "
                                "đã bị lộ!\n"
                                "Hãy **thảo luận ngay** trong kênh này để đưa ra phương án ứng phó."
                            ),
                            color=0xff0000
                        )
                    )

        await interaction.response.send_message(
            embed=discord.Embed(
                title="👮 KẾT QUẢ KIỂM TRA",
                description=result,
                color=color
            ),
            ephemeral=True
        )


class SheriffView(discord.ui.View):
    def __init__(self, game, role):
        super().__init__(timeout=60)
        self.add_item(SheriffSelect(game, role))
