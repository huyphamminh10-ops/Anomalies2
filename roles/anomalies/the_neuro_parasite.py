import disnake
import random
from roles.base_role import BaseRole


def _corrupt_name(name: str, percent: float) -> str:
    """Phá hủy tên role theo tỉ lệ percent (0.25, 0.5, 0.75)."""
    chars = list(name)
    corrupt_chars = "!@#$%^&*?~<>"
    n = max(1, int(len(chars) * percent))
    indices = random.sample(range(len(chars)), min(n, len(chars)))
    for i in indices:
        if chars[i] != " ":
            chars[i] = random.choice(corrupt_chars)
    return "".join(chars)


class TheNeuroParasite(BaseRole):
    name = "Ký Sinh Thần Kinh"
    team = "Anomalies"
    max_count = 1

    description = (
        "Bạn là Ký Sinh Trùng — một thực thể có khả năng tha hóa tâm trí người khác.\n\n"
        "• Mỗi đêm, bạn có thể chọn 1 người để ký sinh.\n"
        "• Quá trình gồm 4 giai đoạn qua từng ngày:\n"
        "  - Giai đoạn 1 (Ngày 1): Tên role bị phá hủy 25%.\n"
        "  - Giai đoạn 2 (Ngày 2): Tên bị phá hủy 50%. Nếu vật chủ chết từ đây, Neuro cũng chết.\n"
        "  - Giai đoạn 3 (Ngày 3): Tên bị phá hủy 75%.\n"
        "  - Giai đoạn 4 (Ngày 4): Vật chủ chính thức trở thành Anomaly.\n"
        "• Thám Tử soi → ra phe của role đang ký sinh + '?'.\n"
        "• Thám Trưởng soi → ra tên role bị phá hủy.\n"
        "• **Kẻ Báo Oán** có thể dùng kỹ năng hồi sinh để giải thoát vật chủ — Neuro sẽ chết."
    )

    dm_message = (
        "🦠 **KÝ SINH THẦN KINH**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "📋 **Cơ chế Kỹ Năng:**\n"
        "• Mỗi đêm, chọn 1 mục tiêu để ký sinh.\n"
        "• Cần 4 ngày để tha hóa hoàn toàn vật chủ.\n"
        "• Tên role vật chủ bị phá hủy dần từng ngày (25% → 50% → 75% → 100%).\n"
        "• Thám Tử soi ra '<phe>?' trong suốt quá trình.\n"
        "• Thám Trưởng soi ra tên bị phá hủy.\n\n"
        "⚠ **Giới Hạn:**\n"
        "• Từ giai đoạn 2 trở đi, nếu vật chủ chết → bạn cũng chết.\n"
        "• Kẻ Báo Oán có thể giải thoát vật chủ và giết bạn.\n"
        "• Nếu bạn chết, quá trình tha hóa lập tức bị hủy."
    )

    def __init__(self, player):
        super().__init__(player)
        self.host_id = None
        self.days_infected = 0          # đếm số ngày (0 → 4)
        self.infected_history = set()

    async def on_game_start(self, game):
        teammates = [
            game.players[pid]
            for pid, role in game.roles.items()
            if getattr(role, 'team', '') == 'Anomalies' and pid != self.player.id
        ]
        if not teammates:
            return
        names = ', '.join('**' + m.display_name + '**' for m in teammates)
        await self.safe_send(
            embed=disnake.Embed(
                title='👥 Đồng Đội Dị Thể',
                description='Đồng đội của bạn:\n' + names,
                color=0xe74c3c
            )
        )

    # =====================================
    # GÁN THUỘC TÍNH GIẢ LÊN VẬT CHỦ
    # =====================================

    def _inject_parasite_attrs(self, game):
        """Đặt các thuộc tính giả lên role của vật chủ để Thám Tử / Thám Trưởng đọc đúng."""
        if not self.host_id:
            return
        host_role = game.roles.get(self.host_id)
        if not host_role:
            return

        stage = self.days_infected  # 1–4

        # Lưu tên gốc lần đầu
        if not hasattr(host_role, "_original_name_neuro"):
            host_role._original_name_neuro = host_role.name
            host_role._original_team_neuro = host_role.team

        corrupt_map = {1: 0.25, 2: 0.50, 3: 0.75, 4: 1.0}
        pct = corrupt_map.get(stage, 0.25)

        host_role._neuro_corrupted_name = _corrupt_name(host_role._original_name_neuro, pct)
        host_role._neuro_stage = stage
        host_role._neuro_parasite_id = self.player.id

    def _remove_parasite_attrs(self, game):
        """Xóa các thuộc tính giả khi ký sinh kết thúc."""
        if not self.host_id:
            return
        host_role = game.roles.get(self.host_id)
        if not host_role:
            return
        for attr in ("_original_name_neuro", "_original_team_neuro",
                     "_neuro_corrupted_name", "_neuro_stage", "_neuro_parasite_id"):
            if hasattr(host_role, attr):
                delattr(host_role, attr)

    # =====================================
    # UI BAN ĐÊM - CHỌN MỤC TIÊU
    # =====================================

    async def send_ui(self, game):
        if self.host_id and game.is_alive(self.host_id):
            stage = self.days_infected
            stage_names = {
                1: "Giai đoạn 1 — Tên bị phá hủy 25%",
                2: "Giai đoạn 2 — Tên bị phá hủy 50% ⚠️",
                3: "Giai đoạn 3 — Tên bị phá hủy 75%",
                4: "Giai đoạn 4 — Tha hóa hoàn tất!",
            }
            host_name = game.players.get(self.host_id)
            host_display = host_name.display_name if host_name else "???"
            await self.safe_send(
                embed=disnake.Embed(
                    title="🦠 ĐANG KÝ SINH",
                    description=(
                        f"Vật chủ: **{host_display}**\n"
                        f"**{stage_names.get(stage, f'Ngày {stage}/4')}**\n\n"
                        f"Tiến độ: **{stage}/4** ngày."
                    ),
                    color=0x9b59b6
                )
            )
            return

        alive = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
            and p.id not in self.infected_history
            and game.roles.get(p.id)
            and game.roles[p.id].team != "Anomalies"
        ]
        if not alive:
            return

        view = self.ParasiteView(game, self, alive)
        await self.safe_send(
            embed=disnake.Embed(
                title="🦠 CHỌN MỤC TIÊU KÝ SINH",
                description="Hãy chọn một nạn nhân để bắt đầu quá trình tha hóa (4 ngày):",
                color=0x9b59b6
            ),
            view=view
        )

    # =====================================
    # XỬ LÝ QUA TỪNG NGÀY
    # =====================================

    async def on_day_start(self, game):
        if not self.host_id:
            return

        if not game.is_alive(self.player.id):
            self._remove_parasite_attrs(game)
            self.host_id = None
            self.days_infected = 0
            return

        if not game.is_alive(self.host_id):
            self._remove_parasite_attrs(game)
            self.host_id = None
            self.days_infected = 0
            return

        self.days_infected += 1
        self._inject_parasite_attrs(game)

        if self.days_infected >= 4:
            await self.complete_corruption(game)

    async def complete_corruption(self, game):
        host = game.players.get(self.host_id)
        if host:
            self._remove_parasite_attrs(game)
            from roles.anomalies.anomaly import Anomaly
            new_role = Anomaly(host)
            game.roles[self.host_id] = new_role
            self.host_id = None
            self.days_infected = 0
            await new_role.on_game_start(game)
            try:
                await host.send(
                    embed=disnake.Embed(
                        title="🔴 BẠN ĐÃ BỊ THA HÓA",
                        description="Ký sinh đã hoàn tất — bạn đã trở thành một **Anomaly**.",
                        color=0xe74c3c
                    )
                )
            except Exception:
                pass
            if hasattr(game, "channel") and game.channel:
                try:
                    await game.channel.send(
                        embed=disnake.Embed(
                            title="⚠️ CẢNH BÁO",
                            description="Một thực thể đã tha hóa thành công một nạn nhân.",
                            color=0xe74c3c
                        )
                    )
                except Exception:
                    pass

    # =====================================
    # KHI VẬT CHỦ HOẶC NEURO CHẾT
    # =====================================

    async def on_player_death(self, game, dead_player_id):
        if self.host_id is None:
            return

        if dead_player_id == self.player.id:
            # Neuro chết → hủy ký sinh
            self._remove_parasite_attrs(game)
            self.host_id = None
            self.days_infected = 0
            return

        if dead_player_id == self.host_id:
            stage = self.days_infected
            if stage >= 2:
                # Từ giai đoạn 2 trở đi: vật chủ chết → Neuro cũng chết
                self._remove_parasite_attrs(game)
                self.host_id = None
                self.days_infected = 0
                await game.kill_player(self.player, reason="Vật chủ chết khi đang ký sinh giai đoạn 2+", bypass_protection=True)
                await game.add_log("🦠 Ký Sinh Thần Kinh đã chết vì vật chủ bị tiêu diệt ở giai đoạn nguy hiểm!")
            else:
                self._remove_parasite_attrs(game)
                self.host_id = None
                self.days_infected = 0

    # =====================================
    # GIẢI THOÁT BỞI KẺ BÁO OÁN (Retributionist)
    # =====================================

    async def free_host(self, game):
        """
        Kẻ Báo Oán gọi method này để giải thoát vật chủ.
        Vật chủ trở về role gốc, Neuro chết.
        """
        if not self.host_id:
            return False

        host_role = game.roles.get(self.host_id)
        if host_role and hasattr(host_role, "_original_name_neuro"):
            # Khôi phục role gốc
            host_role.name = host_role._original_name_neuro
            host_role.team = host_role._original_team_neuro
            self._remove_parasite_attrs(game)

        self.host_id = None
        self.days_infected = 0

        # Neuro chết
        await game.kill_player(self.player, reason="Bị Kẻ Báo Oán giải thoát vật chủ", bypass_protection=True)
        await game.add_log("🦠 Ký Sinh Thần Kinh đã bị tiêu diệt bởi Kẻ Báo Oán!")
        return True

    # =====================================
    # VIEW
    # =====================================

    class ParasiteView(disnake.ui.View):
        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            options = [
                disnake.SelectOption(label=p.display_name, value=str(p.id))
                for p in alive_list
            ][:25]
            self.add_item(TheNeuroParasite.ParasiteSelect(game, role, options))

    class ParasiteSelect(disnake.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role
            super().__init__(
                placeholder="Chọn mục tiêu ký sinh...",
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

            target_id = int(self.values[0])
            self.role.host_id = target_id
            self.role.days_infected = 0
            self.role.infected_history.add(target_id)

            await interaction.response.send_message(
                embed=disnake.Embed(
                    title="🦠 KÝ SINH BẮT ĐẦU",
                    description=(
                        "Ký sinh đã bắt đầu lên mục tiêu.\n"
                        "Quá trình tha hóa sẽ hoàn tất sau **4 ngày** (4 giai đoạn).\n\n"
                        "⚠️ Từ giai đoạn 2, nếu vật chủ chết → bạn cũng chết."
                    ),
                    color=0x9b59b6
                ),
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)
