import disnake
from roles.base_role import BaseRole


class ThePsychopath(BaseRole):
    name = "Kẻ Tâm Thần"
    team = "Unknown"
    faction = "Unknown"
    max_count = 1
    win_type  = "solo"

    description = (
        "Bạn xuất hiện trong danh sách đồng loại của phe Dị Thể. "
        "Họ sẽ thấy bạn như đồng đội và bạn có thể đọc được kênh chat bí mật của họ.\n\n"
        "Mục tiêu: Bị Cách ly và Trục xuất bởi Thị Trấn.\n"
        "Điều kiện thắng: Bị loại bằng bỏ phiếu ban ngày và "
        "KHÔNG có bất kỳ phiếu nào từ phe Dị Thể bầu cho bạn."
    )

    dm_message = (
        "🩸 **KẺ TÂM THẦN**\n\n"
        "Bạn thuộc phe **Thực Thể Ẩn**.\n\n"
        "Bạn xuất hiện như một thành viên của Dị Thể trong mắt họ.\n"
        "Bạn có thể đọc được kênh chat bí mật của Dị Thể.\n\n"
        "🎯 Mục tiêu:\n"
        "Bị Cách Ly và Trục Xuất vào ban ngày.\n\n"
        "🔥 Điều kiện thắng nghiệt ngã:\n"
        "- Bị loại bằng bỏ phiếu.\n"
        "- KHÔNG có bất kỳ phiếu nào từ phe Dị Thể bầu cho bạn.\n\n"
        "Nếu chỉ 1 Anomaly bỏ phiếu cho bạn → bạn thua ngay lập tức."
    )

    def __init__(self, player):
        super().__init__(player)
        self._exile_win_ready = False

    def appear_as_anomaly(self):
        return True

    def can_read_anomaly_chat(self):
        return True

    # ==============================
    # GỬI UI BAN ĐÊM — Nhắc nhở chiến lược + xem trạng thái
    # ==============================

    async def send_ui(self, game):
        # Đếm số Anomaly còn sống
        anomaly_count = sum(
            1 for pid, role in game.roles.items()
            if role.team == "Anomalies" and game.is_alive(pid)
        )

        view = self.PsychopathView(self)
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="🩸 ĐÊM — KẺ THẦN KINH",
                    description=(
                        "Bạn không có hành động đặc biệt vào ban đêm.\n\n"
                        f"👥 Dị Thể còn sống: **{anomaly_count}** người\n"
                        "_(Họ thấy bạn như đồng đội — nhưng đừng để họ bầu cho bạn!)_\n\n"
                        "⚠️ **Mục tiêu của bạn:**\n"
                        "Khiến **Thị Trấn** bầu trục xuất bạn,\n"
                        "nhưng **không** để bất kỳ Anomaly nào bỏ phiếu cho bạn.\n\n"
                        "💡 Hãy hành động như một Survivor thật sự nghi ngờ bạn."
                    ),
                    color=0x8e44ad
                ),
                view=view
            )
        except Exception:
            pass

    class PsychopathView(disnake.ui.View):
        def __init__(self, role):
            super().__init__(timeout=60)
            self.role = role

        @disnake.ui.button(label="🩸 Xem điều kiện thắng", style=disnake.ButtonStyle.danger)
        async def view_win_condition(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            await interaction.response.send_message(
                embed=disnake.Embed(
                    title="🎯 ĐIỀU KIỆN THẮNG",
                    description=(
                        "✅ **Bị trục xuất bằng bỏ phiếu ban ngày**\n"
                        "❌ **KHÔNG có bất kỳ Anomaly nào bầu cho bạn**\n\n"
                        "Nếu ngay cả 1 Anomaly bỏ phiếu cho bạn → **thua ngay lập tức**.\n\n"
                        "💡 Chiến lược: Thuyết phục Thị Trấn rằng bạn đáng ngờ,\n"
                        "đồng thời thuyết phục Dị Thể rằng bạn là đồng đội đáng tin."
                    ),
                    color=0x8e44ad
                ),
                ephemeral=True
            )

        @disnake.ui.button(label="📖 Xem luật chơi", style=disnake.ButtonStyle.secondary)
        async def view_rules(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            await interaction.response.send_message(
                embed=disnake.Embed(
                    title="📖 LUẬT CHƠI — KẺ THẦN KINH",
                    description=(
                        "🔴 **Bạn trông như Anomaly** với tất cả Dị Thể.\n"
                        "🟢 **Bạn có thể đọc kênh chat bí mật** của Dị Thể.\n\n"
                        "Ban ngày: Hành xử như bị nghi ngờ để bị bỏ phiếu.\n"
                        "Ban đêm: Quan sát Dị Thể nhưng đừng lộ bài."
                    ),
                    color=0x8e44ad
                ),
                ephemeral=True
            )

    # ==============================
    # ĐIỀU KIỆN THẮNG ĐẶC BIỆT
    # ==============================

    def check_win_condition(self, game) -> bool:
        """
        Thắng khi: chính Psychopath bị vote trục xuất VÀ
        không có bất kỳ Anomaly nào đã bỏ phiếu cho mình.
        Trạng thái được ghi vào self._exile_win_ready bởi on_death().
        """
        return getattr(self, "_exile_win_ready", False)

    def on_exile_vote(self, game, vote_data: dict):
        """
        Gọi từ game.py ngay trước khi kill_player() trong phase vote.
        vote_data: {voter_id: target_id}
        """
        if self.player.id not in vote_data.values():
            return  # Không phải mình bị vote
        for voter_id, target_id in vote_data.items():
            if target_id != self.player.id:
                continue
            voter_role = game.roles.get(voter_id)
            if voter_role and getattr(voter_role, "team", "") == "Anomalies":
                self._exile_win_ready = False
                return
        self._exile_win_ready = True
