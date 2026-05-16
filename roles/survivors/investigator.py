import disnake
from roles.base_role import BaseRole


class Investigator(BaseRole):
    name      = "Thám Tử"
    team      = "Survivors"
    max_count = 2
    dif = 4

    description = (
        "Mỗi đêm bạn có thể điều tra 1 người chơi.\n\n"
        "• Kết quả trả về: 🔴 Dị Thể hoặc 🟢 Người Sống Sót.\n"
        "• Không tiết lộ tên vai trò cụ thể, chỉ cho biết phe.\n"
        "• Nếu điều tra trúng Anomaly, một cảnh báo ẩn danh sẽ gửi vào kênh Dị Thể."
    )

    dm_message = (
        "🔎 **THÁM TỬ**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 người để điều tra.\n"
        "Kết quả sẽ cho biết người đó thuộc phe nào:\n"
        "• 🔴 ĐỎ = Dị Thể (Dị Thể)\n"
        "• 🟢 XANH = Người Sống Sót (Người Sống Sót)\n\n"
        "⚠ Hãy chia sẻ thông tin khéo léo — tiết lộ thân phận quá sớm có thể nguy hiểm."
    )

    async def send_ui(self, game):
        view = InvestigatorView(game, self)
        await self.safe_send(
            embed=disnake.Embed(
                title="🔎 ĐÊM — THÁM TỬ",
                description="Chọn 1 người để điều tra phe của họ:",
                color=0x3498db
            ),
            view=view
        )


class InvestigatorSelect(disnake.ui.Select):
    def __init__(self, game, role):
        self.game = game
        self.role = role

        options = [
            disnake.SelectOption(label=p.display_name, value=str(p.id))
            for p in game.get_alive_players()
            if p != role.player
        ][:25]

        super().__init__(
            placeholder="Chọn mục tiêu điều tra...",
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

        target      = self.game.get_member(int(self.values[0]))
        target_role = self.game.get_role(target)
        if not target_role:
            await interaction.response.send_message("❌ Không thể xác định vai trò mục tiêu.", ephemeral=True)
            return

        # Nếu đang cải trang → hiển thị màu phe của role cải trang
        effective_team = target_role.team
        if hasattr(target_role, "disguise_team") and target_role.disguise_team:
            effective_team = target_role.disguise_team

        if effective_team == "Anomalies":
            result = "🔴 **ĐỎ** — Người này thuộc phe **Dị Thể**!"
            color  = 0xe74c3c
            # ── Cảnh báo Dị Thể (không nói tên ai bị điều tra) ──
            # FIX BUG: max_count=2 ⇒ 2 Thám Tử cùng cảnh báo → embed gửi 2 lần.
            # Dedupe per-night: chỉ gửi 1 cảnh báo / đêm dù bao nhiêu Thám Tử trúng.
            already_warned = self.game.night_effects.get("investigator_warning_sent", False)
            if not already_warned and hasattr(self.game, "anomaly_chat_mgr"):
                # Chỉ cảnh báo nếu role thực sự là Anomaly (không phải chỉ cải trang thành Anomaly)
                if target_role.team == "Anomalies":
                    self.game.night_effects["investigator_warning_sent"] = True
                await self.game.anomaly_chat_mgr.send(
                    embed=disnake.Embed(
                        title="🔎 CẢNH BÁO TRINH SÁT",
                        description=(
                            "**THÁM TỬ** đã điều tra đêm nay và phát hiện "
                            "một thành viên phe Dị Thể!\n\n"
                            "⚠️ Một trong số các bạn đang bị **nghi ngờ** — "
                            "hãy cảnh giác và bảo vệ danh tính!"
                        ),
                        color=0xff6b35
                    )
                )
        elif effective_team == "Survivors":
            result = "🟢 **XANH** — Người này thuộc phe **Người Sống Sót**."
            color  = 0x2ecc71
        elif effective_team in ("Unknown Entities", "Unknown"):
            result = "❓ **KHÔNG XÁC ĐỊNH** — Người này thuộc phe **Thực Thể Ẩn**."
            color  = 0x95a5a6
        else:
            result = "❓ **Không xác định** — Không thể xác định phe của người này."
            color  = 0x95a5a6

        await interaction.response.send_message(
            embed=disnake.Embed(
                title="🔎 KẾT QUẢ ĐIỀU TRA",
                description=result,
                color=color
            ),
            ephemeral=True
        )

        # FIX BUG: khoá Select sau khi đã chọn để Thám Tử không bấm lại
        # (mỗi lần bấm trúng Anomaly lại bắn cảnh báo).
        try:
            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)
        except Exception:
            pass


class InvestigatorView(disnake.ui.View):
    def __init__(self, game, role):
        super().__init__(timeout=60)
        self.add_item(InvestigatorSelect(game, role))
