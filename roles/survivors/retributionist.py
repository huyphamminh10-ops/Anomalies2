import discord
from discord.ui import View, Select
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
            discord.SelectOption(label=p.display_name, value=str(p.id))
            for p in dead_survivors
        ][:25]

        select = Select(
            placeholder="⚰️ Chọn Survivor để hồi sinh...",
            options=options[:25],
            custom_id="retrib_target"
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("❌ Đây không phải lựa chọn của bạn!", ephemeral=True)
            return

        selected_id = int(interaction.data["values"][0])
        target = self.game.get_member(selected_id)

        if not target:
            await interaction.response.send_message("❌ Không tìm thấy người này.", ephemeral=True)
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
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
                embed=discord.Embed(
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
                embed=discord.Embed(
                    title="⚰️ NGƯỜI PHỤC HẬN",
                    description="Chưa có Survivor nào tử vong để hồi sinh.",
                    color=0x95a5a6
                )
            )
            return

        embed = discord.Embed(
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

            try:
                await member.edit(nick="NGƯỜI PHỤC HẬN")
            except:
                pass

            await game.log_channel.send(
                embed=discord.Embed(
                    title="⚰️ HỒI SINH",
                    description=f"Người Phục Hậu đã hồi sinh **{target.display_name}** trước mắt mọi người!",
                    color=0x9b59b6
                )
            )
        else:
            await game.log_channel.send(
                embed=discord.Embed(
                    description=f"⚰️ Một Survivor đã được hồi sinh bí mật trong đêm!",
                    color=0x9b59b6
                )
            )


    # ==============================
    # GỬI UI BAN ĐÊM — inherit từ ReviveView đã có sẵn
    # ==============================

    async def send_ui(self, game):
        dead_survivors = [
            game.guild.get_member(pid)
            for pid, role in game.roles.items()
            if role.team == "Survivors"
            and pid in game.dead_players
            and game.guild.get_member(pid)
        ]

        if not dead_survivors or self.used:
            status = "❌ Đã dùng lượt hồi sinh." if self.used else "💀 Chưa có Survivor nào tử vong."
            try:
                await self.safe_send(
                    embed=discord.Embed(
                        title="🔮 ĐÊM — KẺ HỒI SINH",
                        description=status,
                        color=0x7f8c8d
                    )
                )
            except Exception:
                pass
            return

        view = ReviveView(self, game, is_day=False)
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="🔮 ĐÊM — KẺ HỒI SINH",
                    description=(
                        f"Có **{len(dead_survivors)}** Survivor đã ngã xuống.\n\n"
                        "Bạn có thể **hồi sinh 1 người** từ cõi chết đêm nay.\n"
                        "⚠️ Chỉ có **1 lượt** trong cả trận — hãy chọn đúng thời điểm."
                    ),
                    color=0x1abc9c
                ),
                view=view
            )
        except Exception:
            pass
