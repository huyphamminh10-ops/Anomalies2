import disnake
from disnake.ui import View, Select
from roles.base_role import BaseRole


# ==========================================
# VIEW CHỌN NGƯỜI ĐỂ HỒI SINH
# ==========================================

class ReviveView(View):
    def __init__(self, role, game, is_day=False):
        super().__init__(timeout=60)
        self.role = role
        self.game = game
        self.is_day = is_day

        dead_survivors = [
            p for p in game.get_dead_players()
            if (lambda r=game.get_role(p): r and r.team == "Survivors")()
            and p != role.player
        ]

        if not dead_survivors:
            return

        options = [
            disnake.SelectOption(label=p.display_name, value=str(p.id))
            for p in dead_survivors
        ][:25]

        select = Select(
            placeholder="⚰️ Chọn Survivor để hồi sinh...",
            options=options[:25],
            custom_id="retrib_target"
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("❌ Đây không phải lựa chọn của bạn!", ephemeral=True)
            return

        selected_id = int(interaction.data["values"][0])
        target = self.game.get_member(selected_id)

        if not target:
            await interaction.response.send_message("❌ Không tìm thấy người này.", ephemeral=True)
            return

        await interaction.response.edit_message(
            embed=disnake.Embed(
                title="⚰️ XÁC NHẬN HỒI SINH",
                description=(
                    f"Bạn sẽ hồi sinh **{target.display_name}**.\n\n"
                    f"{'⚠ Vì đây là ban ngày, bạn sẽ bị **lộ diện** trước thị trấn!' if self.is_day else '✅ Hồi sinh ban đêm – danh tính của bạn được giữ bí mật.'}"
                ),
                color=0x9b59b6
            ),
            view=None
        )

        await self.role.revive(self.game, target, is_day=self.is_day)


class Retributionist(BaseRole):
    name = "Kẻ Báo Oán"
    team = "Survivors"
    max_count = 1
    dif = 7
    rarity = "epic"

    description = (
        "Một lần duy nhất, bạn có thể hồi sinh 1 Survivor đã chết.\n"
        "Nếu hồi sinh vào ban ngày, bạn sẽ bị lộ diện."
    )

    dm_message = (
        "⚡ **KẺ BÁO OÁN**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "🔄 Một lần duy nhất trong cả game, bạn có thể hồi sinh 1 Survivor đã chết.\n\n"
        "☀️ Hồi sinh ban ngày → bạn bị **lộ diện** trước thị trấn.\n"
        "🌙 Hồi sinh ban đêm → danh tính được giữ bí mật.\n"
        "⚠️ Chỉ dùng được 1 lần — hãy chọn thời điểm thích hợp!\n"
        "🎯 Mục tiêu: Tận dụng kỹ năng hồi sinh đúng lúc để lật ngược thế cờ."
    )


    def __init__(self, player):
        super().__init__(player)
        self.used = False
        self.revealed = False

    # ==============================
    # GỬI UI HỒI SINH
    # ==============================

    async def send_revive_ui(self, game, is_day=False):
        if self.used:
            await self.safe_send(
                embed=disnake.Embed(
                    title="⚰️ NGƯỜI PHỤC HẬN",
                    description="❌ Bạn đã dùng khả năng hồi sinh rồi.",
                    color=0x95a5a6
                )
            )
            return

        dead_survivors = [
            p for p in game.get_dead_players()
            if (lambda r=game.get_role(p): r and r.team == "Survivors")()
            and p != self.player
        ]

        if not dead_survivors:
            await self.safe_send(
                embed=disnake.Embed(
                    title="⚰️ NGƯỜI PHỤC HẬN",
                    description="Chưa có Survivor nào tử vong để hồi sinh.",
                    color=0x95a5a6
                )
            )
            return

        embed = disnake.Embed(
            title="⚰️ NGƯỜI PHỤC HẬN",
            description=(
                "Bạn có thể hồi sinh 1 Survivor đã chết.\n\n"
                f"{'⚠ **Cảnh báo:** Hồi sinh ban ngày sẽ làm lộ danh tính của bạn!' if is_day else '🌙 Ban đêm – danh tính của bạn được bảo vệ.'}\n\n"
                "Chọn người bạn muốn đưa trở lại:"
            ),
            color=0x9b59b6
        )

        view = ReviveView(self, game, is_day=is_day)

        try:
            await self.safe_send(embed=embed, view=view)
        except Exception as e:
            print(f"[ERROR] Không thể gửi DM cho {self.player}: {e}")

    # ==============================
    # HỒI SINH
    # ==============================

    async def revive(self, game, target, is_day=False):
        if self.used:
            return

        if target == self.player:
            return

        role = game.get_role(target)

        if not role or role.team != "Survivors":
            return

        self.used = True

        await game.revive_player(target)

        # Nếu hồi sinh ban ngày → lộ diện
        if is_day and not self.revealed:
            self.revealed = True

            member = game.guild.get_member(self.player.id)
            if member:
                game.save_nick(member)
            try:
                await member.edit(nick="NGƯỜI PHỤC HẬN")
            except Exception:
                pass

            await game.log_channel.send(
                embed=disnake.Embed(
                    title="⚰️ HỒI SINH",
                    description=f"Người Phục Hậu đã hồi sinh **{target.display_name}** trước mắt mọi người!",
                    color=0x9b59b6
                )
            )
        else:
            await game.log_channel.send(
                embed=disnake.Embed(
                    description=f"⚰️ Một Survivor đã được hồi sinh bí mật trong đêm!",
                    color=0x9b59b6
                )
            )


    # ==============================
    # GỬI UI BAN ĐÊM — inherit từ ReviveView đã có sẵn
    # ==============================

    async def send_ui(self, game):
        # Kiểm tra có Neuro-Parasite đang ký sinh không
        neuro_role = None
        for pid, r in game.roles.items():
            if r.__class__.__name__ == "TheNeuroParasite" and getattr(r, "host_id", None) and game.is_alive(pid):
                neuro_role = r
                break

        dead_survivors = [
            game.guild.get_member(pid)
            for pid, role in game.roles.items()
            if role.team == "Survivors"
            and pid in game.dead_players
            and game.guild.get_member(pid)
        ]

        if self.used and not neuro_role:
            status = "❌ Đã dùng lượt hồi sinh."
            try:
                await self.safe_send(
                    embed=disnake.Embed(
                        title="🔮 ĐÊM — KẺ BÁO OÁN",
                        description=status,
                        color=0x7f8c8d
                    )
                )
            except Exception:
                pass
            return

        # Xây dựng view với cả 2 tùy chọn: hồi sinh + giải thoát vật chủ
        view = RetributionistView(self, game, dead_survivors, neuro_role)
        desc = ""
        if not self.used and dead_survivors:
            desc += f"Có **{len(dead_survivors)}** Survivor đã ngã xuống.\nBạn có thể **hồi sinh 1 người** đêm nay.\n\n"
        if neuro_role:
            host = game.players.get(neuro_role.host_id)
            host_name = host.display_name if host else "???"
            desc += f"🦠 **{host_name}** đang bị Ký Sinh Thần Kinh!\nBạn có thể **giải thoát** họ — Neuro sẽ chết.\n\n"
        if not desc:
            desc = "Không có hành động nào khả dụng đêm nay."

        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="🔮 ĐÊM — KẺ BÁO OÁN",
                    description=desc.strip(),
                    color=0x1abc9c
                ),
                view=view
            )
        except Exception:
            pass


# ==========================================
# VIEW TỔNG HỢP: HỒI SINH + GIẢI THOÁT VẬT CHỦ
# ==========================================

class RetributionistView(disnake.ui.View):
    def __init__(self, role, game, dead_survivors, neuro_role=None):
        super().__init__(timeout=60)
        self.role = role
        self.game = game
        self.neuro_role = neuro_role

        # Select hồi sinh nếu còn lượt và có người chết
        if not role.used and dead_survivors:
            options = [
                disnake.SelectOption(label=p.display_name, value=str(p.id))
                for p in dead_survivors
            ][:25]
            select = disnake.ui.Select(
                placeholder="⚰️ Chọn Survivor để hồi sinh...",
                options=options,
                custom_id="retrib_revive"
            )
            select.callback = self._on_revive
            self.add_item(select)

        # Nút giải thoát vật chủ Neuro
        if neuro_role:
            btn = disnake.ui.Button(
                label="🦠 Giải Thoát Vật Chủ Neuro",
                style=disnake.ButtonStyle.danger,
                custom_id="retrib_free_host",
                row=1
            )
            btn.callback = self._on_free_host
            self.add_item(btn)

    async def _on_revive(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("❌ Đây không phải lựa chọn của bạn!", ephemeral=True)
            return
        selected_id = int(interaction.data["values"][0])
        target = self.game.get_member(selected_id)
        if not target:
            await interaction.response.send_message("❌ Không tìm thấy người này.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await self.role.revive(self.game, target, is_day=False)

    async def _on_free_host(self, interaction: disnake.MessageInteraction):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("❌ Đây không phải lựa chọn của bạn!", ephemeral=True)
            return
        if not self.neuro_role:
            await interaction.response.send_message("❌ Không tìm thấy Ký Sinh Thần Kinh.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        success = await self.neuro_role.free_host(self.game)
        if success:
            host = self.game.players.get(self.neuro_role.host_id or 0)
            await interaction.followup.send(
                embed=disnake.Embed(
                    title="🦠 GIẢI THOÁT THÀNH CÔNG",
                    description="Vật chủ đã được trả về role gốc.\n**Ký Sinh Thần Kinh đã bị tiêu diệt!**",
                    color=0x2ecc71
                ),
                ephemeral=True
            )
        else:
            await interaction.followup.send("❌ Giải thoát thất bại.", ephemeral=True)
