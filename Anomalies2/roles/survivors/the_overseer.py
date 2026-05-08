import disnake
import random
from roles.base_role import BaseRole


class TheOverseer(BaseRole):
    name = "Người Giám Sát"
    team = "Survivors"
    max_count = 1

    def __init__(self, player):
        super().__init__(player)
        self.used_tonight = False
        self.camera_uses  = 3

    description = (
        "Bạn kiểm soát hệ thống camera an ninh của thị trấn.\n\n"
        "• Mỗi đêm có thể xem Camera để nhận danh sách ngẫu nhiên tối đa 3 người đang hoạt động.\n"
        "• Nếu trong danh sách có Anomaly, một cảnh báo bí mật được gửi tới kênh chat riêng của Dị Thể.\n"
        "• Tổng cộng có **3 lượt** dùng Camera trong cả trận."
    )

    dm_message = (
        "📷 **NGƯỜI GIÁM SÁT**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🌙 Bạn kiểm soát camera an ninh — mỗi đêm có thể bật Camera để theo dõi.\n\n"
        "📋 Cơ chế:\n"
        "• Camera ghi lại tối đa 3 người đang hoạt động trong đêm (ngẫu nhiên).\n"
        "• Nếu phát hiện Anomaly, một cảnh báo tự động được gửi vào kênh Dị Thể.\n"
        "• Bạn có **3 lượt** sử dụng trong suốt trận.\n\n"
        "⚠ Cẩn thận: Cảnh báo tới Dị Thể có thể khiến chúng biết bạn đang theo dõi.\n"
        "💡 Chọn đúng thời điểm dùng Camera để tối đa hiệu quả."
    )

    # ==================================
    # GỬI UI BAN ĐÊM
    # ==================================
    async def send_ui(self, game):
        self.used_tonight = False

        if self.camera_uses <= 0:
            await self.safe_send(embed=disnake.Embed(
                title="📷 CAMERA HẾT LƯỢT",
                description="Bạn đã hết lượt dùng Camera trong trận này.",
                color=0x7f8c8d
            ))
            return

        view = self.OverseerView(game, self)
        await self.safe_send(
            embed=disnake.Embed(
                title="📷 ĐÊM — NGƯỜI GIÁM SÁT",
                description=(
                    f"🎯 Còn **{self.camera_uses}** lượt Camera.\n\n"
                    "Bạn có muốn truy cập camera an ninh đêm nay?"
                ),
                color=0x3498db
            ),
            view=view
        )

    # ==================================
    # VIEW
    # ==================================
    class OverseerView(disnake.ui.View):
        def __init__(self, game, role):
            super().__init__(timeout=60)
            self.game = game
            self.role = role

        @disnake.ui.button(label="📷 Xem Camera", style=disnake.ButtonStyle.primary)
        async def use_camera(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            if self.role.used_tonight:
                await interaction.response.send_message(
                    "Bạn đã dùng Camera đêm nay rồi.", ephemeral=True
                )
                return

            if self.role.camera_uses <= 0:
                await interaction.response.send_message(
                    "Bạn đã hết lượt dùng Camera.", ephemeral=True
                )
                return

            self.role.camera_uses   -= 1
            self.role.used_tonight   = True

            actors = list(self.game.night_actors)

            if not actors:
                result_text   = "📷 Camera không ghi nhận hoạt động nào đêm nay."
                anomaly_found = False
            else:
                random.shuffle(actors)
                selected      = actors[:3]
                names         = []
                anomaly_found = False

                for pid in selected:
                    member = self.game.get_member(pid)
                    role   = self.game.roles.get(pid)
                    if member:
                        names.append(member.display_name)
                    if role and role.team == "Anomalies":
                        anomaly_found = True

                result_text = "📷 Camera ghi nhận hoạt động từ:\n\n"
                result_text += "\n".join(f"• **{n}**" for n in names)

            # ── Cảnh báo kênh Dị Thể (không tiết lộ tên người) ──
            if anomaly_found and hasattr(self.game, "anomaly_chat_mgr"):
                await self.game.anomaly_chat_mgr.send(
                    embed=disnake.Embed(
                        title="🚨 CẢNH BÁO AN NINH",
                        description=(
                            "**NGƯỜI GIÁM SÁT** đã kích hoạt camera an ninh và phát hiện "
                            "có thành viên trong phe đang hoạt động!\n\n"
                            "⚠️ Hãy **cẩn thận hành động** — ai đó đang theo dõi!"
                        ),
                        color=0xff0000
                    )
                )

            await interaction.response.send_message(
                embed=disnake.Embed(
                    title="📷 BÁO CÁO CAMERA",
                    description=result_text,
                    color=0x3498db
                ),
                ephemeral=True
            )

            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)

        @disnake.ui.button(label="⏭ Bỏ Qua", style=disnake.ButtonStyle.secondary)
        async def skip(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            self.role.used_tonight = True
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)
