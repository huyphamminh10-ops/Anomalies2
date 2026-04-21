import discord
from roles.base_role import BaseRole
import copy


class TheTimeWeaver(BaseRole):
    name = "Kẻ Dệt Thời Gian"
    team = "Unknown"
    max_count = 1

    def __init__(self, player):
        super().__init__(player)
        self.snapshots   = {}
        self.rewind_used = False

    description = (
        "Bạn thao túng dòng thời gian — quan sát quá khứ và có thể khôi phục trạng thái trò chơi.\n\n"
        "• Passive: Mỗi sáng bạn biết danh tính 1 kẻ đã giết người đêm qua (Nhãn Quan Thời Gian).\n"
        "• Active: 1 lần duy nhất trong trận (từ Đêm 5, khi còn >8 người), Rewind dòng thời gian về 2 ngày trước.\n"
        "• Khi Rewind: danh sách sống/chết và di chúc được khôi phục về thời điểm 2 ngày trước.\n"
        "• Không có điều kiện thắng riêng — phải tự sinh tồn đến cuối trận."
    )

    dm_message = (
        "⏳ **THE TIME-WEAVER – KẺ DỆT THỜI GIAN**\n\n"
        "Bạn thuộc phe **Unknown** — sức mạnh của bạn là thời gian.\n\n"
        "🌅 PASSIVE — Nhãn Quan Thời Gian:\n"
        "Mỗi sáng bạn nhận DM biết tên 1 kẻ đã ra tay giết người đêm qua.\n\n"
        "⏪ ACTIVE — Rewind Timeline (1 lần duy nhất):\n"
        "• Dùng được từ Đêm 5 trở đi, khi còn hơn 8 người sống.\n"
        "• Khôi phục danh sách sống/chết, di chúc về trạng thái 2 ngày trước.\n\n"
        "💡 Bạn không có đồng minh — hãy dùng thông tin passive để thao túng cả hai phe và tồn tại đến cuối."
    )

    # =================================
    # LƯU SNAPSHOT MỖI NGÀY
    # =================================
    def save_snapshot(self, game):
        self.snapshots[game.day_count] = copy.deepcopy({
            "alive": game.alive_players.copy(),
            "dead": game.dead_players.copy(),
            "wills": game.wills.copy(),
            "roles": game.roles_state_copy(),
        })

    # =================================
    # PASSIVE: Nhãn quan thời gian
    # =================================
    async def morning_passive(self, game):

        if game.last_night_killers:
            killer_id = game.last_night_killers[0]
            killer = game.get_member(killer_id)

            await self.safe_send(
                f"⏳ Nhãn quan thời gian cho thấy: {killer.display_name} đã giết ai đó đêm qua."
            )

    # =================================
    # GỬI UI
    # =================================
    async def send_ui(self, game):

        if self.rewind_used:
            return

        if game.night_count < 5:
            return

        if len(game.get_alive_players()) <= 8:
            return

        view = self.RewindView(game, self)

        await self.safe_send(
            "⏳ Bạn có muốn Khôi Phục Dòng Thời Gian (2 ngày trước)?",
            view=view
        )

    # =================================
    # VIEW
    # =================================
    class RewindView(discord.ui.View):
        def __init__(self, game, role):
            super().__init__(timeout=60)
            self.game = game
            self.role = role

        @discord.ui.button(label="⏪ Rewind Timeline", style=discord.ButtonStyle.danger)
        async def rewind(self, interaction: discord.Interaction, button: discord.ui.Button):

            target_day = self.game.day_count - 2

            if target_day not in self.role.snapshots:
                await interaction.response.send_message(
                    "Không thể quay về thời điểm đó.",
                    ephemeral=True
                )
                return

            snapshot = self.role.snapshots[target_day]

            # Restore state
            self.game.alive_players = snapshot["alive"]
            self.game.dead_players = snapshot["dead"]
            self.game.wills = snapshot["wills"]
            self.game.restore_roles(snapshot["roles"])

            self.role.rewind_used = True

            await interaction.response.send_message(
                "⏳ Dòng thời gian đã bị bẻ cong...",
                ephemeral=True
            )

            await self.game.broadcast(
                "⚠️ The timeline has been rewritten."
            )
