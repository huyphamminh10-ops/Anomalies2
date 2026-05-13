import disnake
from roles.base_role import BaseRole


class SerialKiller(BaseRole):
    name = "KẺ GIẾT NGƯỜI HÀNG LOẠT"
    team = "Unknown Entities"
    win_type = "solo"

    description = (
        "Bạn là kẻ giết người hàng loạt không phe phái — chỉ muốn là người sống sót duy nhất.\n\n"
        "• Mỗi đêm chọn 1 người để sát hại ngay lập tức.\n"
        "• Không thể giết cùng 1 người 2 đêm liên tiếp.\n"
        "• **Kỹ Năng Cải Trang (1 lần duy nhất):** Bỏ qua giết người đêm đó để giả danh một vai trò khác.\n"
        "  - Khi cải trang, không thể giết 2 đêm tiếp theo.\n"
        "  - Thám Tử soi → ra màu phe đang cải trang.\n"
        "  - Thám Trưởng soi → ra tên role cải trang.\n"
        "• Điều kiện thắng: Là người duy nhất còn sống."
    )

    dm_message = (
        "🔪 **KẺ GIẾT NGƯỜI HÀNG LOẠT**\n\n"
        "Bạn thuộc phe **Thực Thể Không Xác Định** — chỉ chiến đấu cho bản thân.\n\n"
        "🌙 Mỗi đêm bạn chọn 1 người để sát hại trực tiếp.\n\n"
        "📋 Cơ chế:\n"
        "• Không thể giết cùng 1 người 2 đêm liên tiếp.\n"
        "• **Cải Trang (1 lần):** Bỏ qua giết người để giả danh một role khác trong trận.\n"
        "  Khi cải trang, bạn mang danh nghĩa role đó trong 2 đêm.\n"
        "  - Thám Tử → màu phe role cải trang.\n"
        "  - Thám Trưởng → tên role cải trang.\n\n"
        "🏆 Điều kiện thắng: Chỉ còn mình bạn sống sót."
    )

    def __init__(self, player):
        super().__init__(player)
        self.last_target_id = None
        self.has_killed_tonight = False
        # --- Cải Trang ---
        self.disguise_used = False        # đã dùng kỹ năng chưa
        self.disguise_role = None         # tên role đang cải trang
        self.disguise_team = None         # phe của role cải trang (cho Thám Tử)
        self.disguise_nights_left = 0     # số đêm còn lại của cải trang

    def check_win_condition(self, game) -> bool:
        alive = game.get_alive_players()
        alive_ids = {p.id for p in alive}
        return len(alive_ids) == 1 and self.player.id in alive_ids

    # ==============================
    # GỬI UI BAN ĐÊM
    # ==============================

    async def send_ui(self, game):
        self.has_killed_tonight = False

        # Giảm đếm cải trang nếu đang hoạt động
        if self.disguise_nights_left > 0:
            self.disguise_nights_left -= 1
            if self.disguise_nights_left <= 0:
                self.disguise_role = None
                self.disguise_team = None

        alive_players = [p for p in game.get_alive_players() if p != self.player]
        if not alive_players:
            return

        # Lấy danh sách role đang có trong trận để chọn cải trang
        available_roles = list({
            r.name
            for pid, r in game.roles.items()
            if r.name != self.name and game.is_alive(pid)
        })

        view = self.SerialKillerView(game, self, alive_players, available_roles)

        disguise_status = ""
        if self.disguise_role:
            disguise_status = f"\n\n🎭 **Đang cải trang thành:** {self.disguise_role} (còn {self.disguise_nights_left} đêm)"
        elif self.disguise_used:
            disguise_status = "\n\n🎭 Kỹ năng Cải Trang đã được sử dụng."

        await self.safe_send(
            embed=disnake.Embed(
                title="🔪 ĐÊM — KẺ GIẾT NGƯỜI HÀNG LOẠT",
                description=f"Chọn hành động đêm nay:{disguise_status}",
                color=0xe74c3c
            ),
            view=view
        )

    # ==============================
    # VIEW
    # ==============================

    class SerialKillerView(disnake.ui.View):
        def __init__(self, game, role, alive_list, available_roles):
            super().__init__(timeout=60)
            self.game = game
            self.role = role

            options = [
                disnake.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]

            self.add_item(SerialKiller.SerialKillerSelect(game, role, options))

            # Nút Cải Trang nếu chưa dùng và không đang cải trang
            if not role.disguise_used and not role.disguise_role:
                self.add_item(SerialKiller.DisguiseButton(game, role, available_roles))

    # ==============================
    # SELECT — GIẾT NGƯỜI
    # ==============================

    class SerialKillerSelect(disnake.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role
            super().__init__(
                placeholder="Chọn nạn nhân...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):
            if self.role.has_killed_tonight:
                await interaction.response.send_message(
                    "Bạn đã giết người đêm nay rồi.", ephemeral=True
                )
                return

            # Đang trong thời gian cải trang — không thể giết
            if self.role.disguise_nights_left > 0:
                await interaction.response.send_message(
                    "⚠️ Bạn đang cải trang — không thể giết trong 2 đêm sau khi kích hoạt Cải Trang.",
                    ephemeral=True
                )
                return

            target = self.game.get_member(int(self.values[0]))
            if not target:
                return

            if target.id == self.role.player.id:
                await interaction.response.send_message("Bạn không thể tự sát.", ephemeral=True)
                return

            if self.role.last_target_id == target.id:
                await interaction.response.send_message(
                    "Bạn không thể giết cùng một người 2 đêm liên tiếp.", ephemeral=True
                )
                return

            self.role.last_target_id = target.id
            self.role.has_killed_tonight = True

            await self.game.kill_player(target, reason="Bị Serial Killer sát hại")
            await interaction.response.send_message(
                f"🔪 Bạn đã giết {target.display_name}.", ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)
            self.game._check_win()

    # ==============================
    # BUTTON — CẢI TRANG
    # ==============================

    class DisguiseButton(disnake.ui.Button):
        def __init__(self, game, role, available_roles):
            self.game = game
            self.role = role
            self.available_roles = available_roles
            super().__init__(
                label="🎭 Cải Trang (1 lần)",
                style=disnake.ButtonStyle.primary,
                row=1
            )

        async def callback(self, interaction: disnake.MessageInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            if not self.available_roles:
                await interaction.response.send_message("❌ Không có vai trò nào để cải trang.", ephemeral=True)
                return

            # Gửi UI chọn role cải trang
            options = [
                disnake.SelectOption(label=r, value=r)
                for r in self.available_roles
            ][:25]

            view = SerialKiller.DisguiseSelectView(self.game, self.role, options)
            await interaction.response.send_message(
                embed=disnake.Embed(
                    title="🎭 CHỌN VAI TRÒ CẢI TRANG",
                    description=(
                        "Chọn một vai trò trong trận để giả danh.\n"
                        "Bạn sẽ mang danh nghĩa role đó trong **2 đêm**.\n"
                        "Trong thời gian này, bạn **không thể giết người**."
                    ),
                    color=0x9b59b6
                ),
                view=view,
                ephemeral=True
            )

    class DisguiseSelectView(disnake.ui.View):
        def __init__(self, game, role, options):
            super().__init__(timeout=60)
            self.add_item(SerialKiller.DisguiseSelect(game, role, options))

    class DisguiseSelect(disnake.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role
            super().__init__(
                placeholder="Chọn nhân vật để cải trang...",
                options=options,
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):
            chosen_role_name = self.values[0]

            # Lấy team của role được chọn (để Thám Tử soi ra đúng màu)
            chosen_team = None
            for pid, r in self.game.roles.items():
                if r.name == chosen_role_name:
                    chosen_team = r.team
                    break

            self.role.disguise_used = True
            self.role.disguise_role = chosen_role_name
            self.role.disguise_team = chosen_team
            self.role.disguise_nights_left = 2  # 2 đêm cải trang

            for item in self.view.children:
                item.disabled = True
            await interaction.response.edit_message(view=self.view)
            await interaction.followup.send(
                embed=disnake.Embed(
                    title="🎭 CẢI TRANG THÀNH CÔNG",
                    description=(
                        f"Bạn đang giả danh **{chosen_role_name}**.\n"
                        f"Thời gian: **2 đêm**.\n\n"
                        "⚠️ Bạn không thể giết người trong thời gian cải trang."
                    ),
                    color=0x9b59b6
                ),
                ephemeral=True
            )
