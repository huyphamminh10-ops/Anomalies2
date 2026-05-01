import disnake
from roles.base_role import BaseRole


class TheSleeper(BaseRole):
    name = "Kẻ Ngủ Mê"
    team = "Survivors"
    faction = "Survivors"
    max_count = 1

    description = (
        "Bạn bị cách ly khỏi thế giới bên ngoài.\n\n"
        "• Không thể thấy và không thể tham gia kênh chat Thị Trấn.\n"
        "• Mỗi sáng bạn nhận được bản log chi tiết hoạt động đêm qua (không nêu tên thủ phạm).\n"
        "• Vũ khí duy nhất của bạn là Giấy lời nhắn.\n"
        "• Khi bạn chết, toàn bộ ghi chú sẽ được công bố."
    )

    dm_message = (
        "😴 **KẺ NGỦ MÊ**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🚫 Bạn không thể thấy và không thể tham gia chat Thị Trấn.\n\n"
        "🌙 Mỗi sáng bạn sẽ nhận được báo cáo chi tiết những gì đã xảy ra đêm qua.\n"
        "⚠ Không bao giờ tiết lộ danh tính thủ phạm.\n\n"
        "📝 Hãy cập nhật Giấy lời nhắn mỗi ngày.\n"
        "Nếu bạn chết, toàn bộ ghi chú sẽ được công bố cho tất cả mọi người."
    )

    def __init__(self, player):
        super().__init__(player)
        self.notes     = []
        self.triggered = False

    def can_see_town_chat(self):
        return False

    def can_talk_town_chat(self):
        return False

    # ==============================
    # GỬI UI BAN ĐÊM — Modal cập nhật ghi chú
    # ==============================

    async def send_ui(self, game):
        view = self.SleeperNightView(self)
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="😴 ĐÊM — KẺ SAY NGỦ",
                    description=(
                        "Bạn bị cách ly và không thể hành động trực tiếp.\n\n"
                        f"📓 Ghi chú hiện tại: **{len(self.notes)}/20 dòng**\n\n"
                        "Nhấn **Cập nhật ghi chú** để viết thêm quan sát vào Giấy lời nhắn."
                    ),
                    color=0x7f8c8d
                ),
                view=view
            )
        except Exception:
            pass

    class SleeperNightView(disnake.ui.View):
        def __init__(self, role):
            super().__init__(timeout=60)
            self.role = role

        @disnake.ui.button(label="📝 Cập nhật ghi chú", style=disnake.ButtonStyle.primary)
        async def open_notes(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return
            await interaction.response.send_modal(TheSleeper.NoteModal(self.role))

        @disnake.ui.button(label="📖 Xem ghi chú hiện tại", style=disnake.ButtonStyle.secondary)
        async def view_notes(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return
            notes_text = self.role.get_full_notes()
            await interaction.response.send_message(
                embed=disnake.Embed(
                    title="📓 GHI CHÚ CỦA BẠN",
                    description=notes_text[:4000],
                    color=0x7f8c8d
                ),
                ephemeral=True
            )

    class NoteModal(disnake.ui.Modal):
        note_input = disnake.ui.TextInput(
            label="Ghi chú mới",
            placeholder="Viết quan sát, nghi ngờ của bạn...",
            style=disnake.TextStyle.paragraph,
            max_length=500,
            required=True
        )

        def __init__(self, role):
            super().__init__(title="📝 Cập nhật Giấy Lời Nhắn")
            self.role = role

        async def on_submit(self, interaction: disnake.ModalInteraction):
            content = self.note_input.value.strip()
            await self.role.update_note(content)
            await interaction.response.send_message(
                embed=disnake.Embed(
                    description=f"✅ Ghi chú đã được lưu! ({len(self.role.notes)}/20 dòng)",
                    color=0x27ae60
                ),
                ephemeral=True
            )

    # ==============================
    # NHẬN LOG MỖI SÁNG
    # ==============================

    async def send_night_report(self, game, day_number):
        if not self.player.alive:
            return

        report_lines = game.generate_night_report()
        message      = f"🌙 **CHỈ THỊ TỪ HỆ THỐNG - NGÀY {day_number}**\n\n"

        if report_lines:
            for line in report_lines:
                message += f"> {line}\n"
        else:
            message += "> Đêm qua không có hoạt động đáng chú ý.\n"

        message += (
            "\n📝 Lời nhắc: Bạn không thể lên tiếng.\n"
            "Hãy ghi tất cả vào Giấy lời nhắn."
        )

        try:
            await self.safe_send(embed=disnake.Embed(
                title=f"🌅 BÁO CÁO NGÀY {day_number}",
                description=message[:4096],
                color=0xf39c12
            ))
        except Exception:
            pass

    async def update_note(self, content):
        if len(self.notes) >= 20:
            self.notes.pop(0)
        self.notes.append(content)

    def get_full_notes(self):
        if not self.notes:
            return "Không có ghi chú nào."
        return "\n".join(f"{i+1}. {n}" for i, n in enumerate(self.notes))

    # ==============================
    # KHI CHẾT → CÔNG BỐ GIẤY LỜI NHẮN
    # ==============================

    async def on_death(self, game, death_reason=None, killer=None):
        if self.triggered:
            return
        self.triggered = True

        notes_content = self.get_full_notes()
        await game.add_log("📖 Giấy lời nhắn của Kẻ Say Ngủ đã được công bố trước toàn Thị Trấn!")
        await game.reveal_message_to_town(
            f"📓 **GIẤY LỜI NHẮN CỦA KẺ SAY NGỦ**\n\n{notes_content}"
        )
