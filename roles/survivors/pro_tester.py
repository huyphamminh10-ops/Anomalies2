# ══════════════════════════════════════════════════════════════════
# roles/event/pro_tester.py — Vai Trò Sự Kiện Đặc Biệt
# ══════════════════════════════════════════════════════════════════

import disnake
from roles.base_role import BaseRole


class ProTester(BaseRole):
    name        = "Người Thử Nghiệm"
    team        = "Survivors"
    faction     = "Survivors"
    max_count   = 2
    min_players = 7

    # ── Theo dõi mục tiêu đã bị Người Thử Nghiệm khác chọn trong cùng đêm ──
    # Giúp 2 Người Thử Nghiệm phối hợp mà không trùng mục tiêu
    _claimed_targets: set = set()

    description = (
        "Người Thử Nghiệm là người thử nghiệm chuyên nghiệp của tổ chức.\n\n"
        "• Ngay khi game bắt đầu, bạn biết chính xác ai là Lãnh Chúa.\n"
        "• Một lần duy nhất trong game: ép Lãnh Chúa giết 1 Anomaly đồng đội.\n"
        "• Sau khi kỹ năng kích hoạt, bạn sẽ chết ngay lập tức.\n"
        "• Nếu 2 Người Thử Nghiệm cùng kích hoạt đêm đó, Lãnh Chúa bị ép giết 2 Anomaly khác nhau!\n"
        "• Chỉ dùng được khi Lãnh Chúa còn sống và có ít nhất 1 Anomaly chưa bị nhắm."
    )

    dm_message = (
        "🔬 **NGƯỜI THỬ NGHIỆM**\n\n"
        "Bạn thuộc phe **Người Sống Sót** — Vai Trò Sự Kiện Đặc Biệt.\n\n"
        "🧪 Bạn có thiết bị theo dõi dị thể đặc biệt.\n"
        "👑 Ngay khi game bắt đầu, bạn sẽ biết ai là **Lãnh Chúa**.\n\n"
        "⚡ **Kỹ năng đặc biệt (1 lần):** Ép Lãnh Chúa tiêu diệt 1 Anomaly đồng đội.\n"
        "🤝 Nếu cả 2 Người Thử Nghiệm cùng kích hoạt — Lãnh Chúa mất **2 Anomaly** cùng lúc!\n"
        "☠️ Sau khi kích hoạt, bạn sẽ **hi sinh ngay lập tức**.\n\n"
        "🎯 Mục tiêu: Phe Người Sống Sót chiến thắng."
    )

    def __init__(self, player):
        super().__init__(player)
        self.ability_used   = False   # chỉ dùng 1 lần
        self.overlord_info  = None    # lưu tên Lãnh Chúa nhận được lúc game start

    # ══════════════════════════════════════════════════════════════
    # GAME START — Tiết lộ Lãnh Chúa + reset lock
    # ══════════════════════════════════════════════════════════════

    async def on_game_start(self, game):
        # Reset claimed targets mỗi game mới
        ProTester._claimed_targets = set()
        # Tìm Lãnh Chúa
        overlord_role = game.get_role_by_name("Lãnh Chúa")

        try:
            if overlord_role:
                self.overlord_info = overlord_role.player.display_name
                embed = disnake.Embed(
                    title       = "🔬 PRO TESTER — THÔNG TIN BÍ MẬT",
                    description = (
                        f"Thiết bị theo dõi của bạn đã xác định được:\n\n"
                        f"👑 **Lãnh Chúa** là: `{self.overlord_info}`\n\n"
                        f"Hãy sử dụng thông tin này một cách khôn ngoan.\n"
                        f"Bạn có thể dùng kỹ năng để ép hắn phản bội đồng đội — "
                        f"nhưng cái giá là mạng sống của bạn."
                    ),
                    color = 0x1abc9c
                )
                embed.set_footer(text="⚡ Kỹ năng: /pro_tester_activate | Chỉ 1 lần duy nhất")
            else:
                embed = disnake.Embed(
                    title       = "🔬 PRO TESTER — THÔNG TIN BÍ MẬT",
                    description = (
                        "Thiết bị không phát hiện Lãnh Chúa trong trận này.\n\n"
                        "Phe Dị Thể không có thủ lĩnh — "
                        "nhưng kỹ năng của bạn vẫn có thể kích hoạt nếu có Anomaly còn sống."
                    ),
                    color = 0x95a5a6
                )

            await self.safe_send(embed=embed)

        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # NIGHT UI — Không có action ban đêm, nhắc nhở kỹ năng
    # ══════════════════════════════════════════════════════════════

    async def send_ui(self, game):
        if self.ability_used:
            # Đã dùng rồi — chỉ thông báo
            try:
                await self.safe_send(
                    embed=disnake.Embed(
                        title       = "🌙 ĐÊM — PRO TESTER",
                        description = "Bạn đã sử dụng kỹ năng rồi.\n\n💤 Nghỉ ngơi và chờ bình minh.",
                        color       = 0x95a5a6
                    )
                )
            except Exception:
                pass
            return

        # Kiểm tra điều kiện
        can_use, reason = self._check_conditions(game)

        try:
            if can_use:
                view = ProTesterView(game, self)
                await self.safe_send(
                    embed=disnake.Embed(
                        title       = "🌙 ĐÊM — PRO TESTER",
                        description = (
                            f"👑 Lãnh Chúa: `{self.overlord_info or 'Không xác định'}`\n\n"
                            "⚡ Bạn có thể kích hoạt **Giao Thức Kiểm Soát** ngay bây giờ.\n"
                            "☠️ Sau khi kích hoạt, bạn sẽ **hi sinh ngay lập tức**.\n\n"
                            "Bạn có chắc chắn?"
                        ),
                        color = 0x1abc9c
                    ),
                    view=view
                )
            else:
                await self.safe_send(
                    embed=disnake.Embed(
                        title       = "🌙 ĐÊM — PRO TESTER",
                        description = f"⚠️ Không thể kích hoạt kỹ năng:\n{reason}\n\n💤 Nghỉ ngơi đêm nay.",
                        color       = 0xe74c3c
                    )
                )
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # ACTIVATE — Logic kích hoạt kỹ năng (gọi từ View)
    # ══════════════════════════════════════════════════════════════

    async def activate_ability(self, game, target_id: int | None = None):
        """
        Ép Lãnh Chúa giết 1 Anomaly.
        Nếu 2 Người Thử Nghiệm cùng kích hoạt — mỗi người chọn 1 mục tiêu khác nhau,
        Lãnh Chúa bị ép giết 2 Anomaly cùng lúc.
        """
        if self.ability_used:
            return False, "Kỹ năng đã được sử dụng rồi."

        can_use, reason = self._check_conditions(game)
        if not can_use:
            return False, reason

        self.ability_used = True

        # Anomaly chưa bị Người Thử Nghiệm nào nhắm trong đêm nay
        anomaly_targets = [
            pid for pid, role in game.roles.items()
            if role.team == "Anomalies"
            and role.name != "Lãnh Chúa"
            and game.is_alive(pid)
            and pid not in ProTester._claimed_targets
        ]

        if not anomaly_targets:
            return False, "Tất cả Anomaly đã bị Người Thử Nghiệm kia nhắm rồi — không còn mục tiêu."

        # Chọn mục tiêu (ưu tiên chọn cụ thể nếu chưa bị nhắm)
        if target_id and target_id in anomaly_targets:
            victim_id = target_id
        else:
            import random
            victim_id = random.choice(anomaly_targets)

        # Đánh dấu để Người Thử Nghiệm còn lại không chọn trùng
        ProTester._claimed_targets.add(victim_id)

        # ── 45% Trục Trặc khi cả 2 Pro Tester cùng kích hoạt đêm đó ──
        # Kiểm tra xem đây có phải Pro Tester thứ 2 không (claimed_targets đã có ≥ 2)
        if len(ProTester._claimed_targets) >= 2:
            import random
            if random.random() < 0.45:
                # Trục trặc: 1 trong 2 Dị Thể bị chọn chết ngẫu nhiên, còn lại an toàn
                # Đồng thời 1 trong 2 Pro Tester chết ngẫu nhiên
                all_claimed = list(ProTester._claimed_targets)
                dying_anomaly = random.choice(all_claimed)
                safe_anomaly  = [x for x in all_claimed if x != dying_anomaly][0] if len(all_claimed) > 1 else None

                # Tìm tất cả Pro Tester đang sống
                pro_testers = [
                    (pid, r) for pid, r in game.roles.items()
                    if isinstance(r, ProTester) and game.is_alive(pid)
                ]
                dying_pt_id = random.choice([pid for pid, _ in pro_testers]) if pro_testers else None

                # Thông báo trục trặc
                try:
                    text_ch = game.text_channel
                    if text_ch:
                        await text_ch.send(
                            embed=disnake.Embed(
                                title="⚡ TRỤC TRẶC HỆ THỐNG!",
                                description=(
                                    "**Hai Người Thử Nghiệm cùng kích hoạt giao thức — hệ thống bị quá tải!**\n\n"
                                    "🔴 Xác suất trục trặc **45%** đã xảy ra!\n"
                                    "• Chỉ **1 trong 2** Dị Thể bị tiêu diệt.\n"
                                    "• **1 trong 2** Người Thử Nghiệm cũng ngã xuống theo."
                                ),
                                color=0xff6b00
                            )
                        )
                except Exception:
                    pass

                # Giết Anomaly bị chọn ngẫu nhiên
                await game.kill_player(dying_anomaly, reason="Trục trặc giao thức Pro Tester", bypass_protection=True)

                # Giết 1 Pro Tester ngẫu nhiên (nếu chưa chết từ trước)
                if dying_pt_id and game.is_alive(dying_pt_id):
                    await game.kill_player(dying_pt_id, reason="Hi sinh vì trục trặc giao thức", bypass_protection=True)

                # Pro Tester hiện tại không cần tự giết nữa (đã được xử lý ở trên)
                # Trả về sớm để tránh chạy đoạn kill bên dưới
                return True, game.players[dying_anomaly].display_name if dying_anomaly in game.players else "???"

        victim = game.players.get(victim_id)
        victim_name = victim.display_name if victim else "???"

        # Thông báo toàn server
        try:
            text_ch = game.text_channel
            if text_ch:
                await text_ch.send(
                    embed=disnake.Embed(
                        title       = "⚠️ GIAO THỨC KIỂM SOÁT DỊ THỂ",
                        description = (
                            "Một **Người Thử Nghiệm** đã kích hoạt giao thức kiểm soát dị thể!\n\n"
                            "Lãnh Chúa đã bị ép tiêu diệt một Anomaly trong phe của mình...\n\n"
                            "Nhưng cái giá phải trả là mạng sống của Người Thử Nghiệm."
                        ),
                        color = 0xe74c3c
                    )
                )
        except Exception:
            pass

        # Ép Lãnh Chúa giết Anomaly (bypass protection)
        await game.kill_player(victim_id, reason="Bị Lãnh Chúa ép giết bởi giao thức Người Thử Nghiệm", bypass_protection=True)

        # Người Thử Nghiệm tự hi sinh
        await game.kill_player(self.player.id, reason="Hi sinh sau khi kích hoạt Giao Thức Kiểm Soát")

        return True, victim_name

    def _check_conditions(self, game) -> tuple[bool, str]:
        """Kiểm tra điều kiện có thể dùng kỹ năng không."""
        if self.ability_used:
            return False, "Kỹ năng đã được sử dụng rồi."

        # Lãnh Chúa có còn sống không
        overlord_role = game.get_role_by_name("Lãnh Chúa")
        if not overlord_role or not game.is_alive(overlord_role.player.id):
            return False, "Lãnh Chúa đã chết — không thể kiểm soát."

        # Có Anomaly chưa bị Người Thử Nghiệm kia nhắm không
        available = [
            pid for pid, role in game.roles.items()
            if role.team == "Anomalies"
            and role.name != "Lãnh Chúa"
            and game.is_alive(pid)
            and pid not in ProTester._claimed_targets
        ]
        if not available:
            return False, "Không còn Anomaly nào chưa bị nhắm để tiêu diệt."

        return True, ""


# ══════════════════════════════════════════════════════════════════
# DISCORD UI
# ══════════════════════════════════════════════════════════════════

class ProTesterView(disnake.ui.View):
    def __init__(self, game, role: ProTester):
        super().__init__(timeout=60)
        self.game = game
        self.role = role
        self._build(game)

    def _build(self, game):
        # Lấy Anomaly chưa bị Người Thử Nghiệm kia nhắm
        anomaly_targets = [
            pid for pid, r in game.roles.items()
            if r.team == "Anomalies"
            and r.name != "Lãnh Chúa"
            and game.is_alive(pid)
            and pid not in ProTester._claimed_targets
        ]

        if anomaly_targets:
            self.add_item(ProTesterSelect(game, self.role, anomaly_targets))

    @disnake.ui.button(label="⚡ Kích hoạt (Random)", style=disnake.ButtonStyle.danger, row=1)
    async def btn_random(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        success, result = await self.role.activate_ability(self.game, target_id=None)
        if success:
            await interaction.response.send_message(
                embed=disnake.Embed(
                    title       = "⚡ KÍCH HOẠT THÀNH CÔNG",
                    description = f"Lãnh Chúa đã bị ép giết **{result}**.\nBạn đã hi sinh vì nhiệm vụ.",
                    color       = 0xe74c3c
                ),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(f"❌ {result}", ephemeral=True)
        self.stop()

    @disnake.ui.button(label="💤 Bỏ qua đêm nay", style=disnake.ButtonStyle.secondary, row=1)
    async def btn_skip(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("💤 Bạn bỏ qua đêm nay.", ephemeral=True)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class ProTesterSelect(disnake.ui.Select):
    """Chọn mục tiêu Anomaly cụ thể để Lãnh Chúa giết."""
    def __init__(self, game, role: ProTester, anomaly_pids: list[int]):
        self.game = game
        self.role = role

        options = [
            disnake.SelectOption(
                label = game.players[pid][:25].display_name,
                value = str(pid),
                emoji = "🎯"
            )
            for pid in anomaly_pids
            if pid in game.players
        ][:25]

        super().__init__(
            placeholder = "Chọn Anomaly mục tiêu cụ thể...",
            options     = options,
            min_values  = 1,
            max_values  = 1,
            row         = 0
        )

    async def callback(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
            return

        target_id = int(self.values[0])

        for item in self.view.children:
            item.disabled = True
        await interaction.message.edit(view=self.view)

        success, result = await self.role.activate_ability(self.game, target_id=target_id)
        if success:
            await interaction.response.send_message(
                embed=disnake.Embed(
                    title       = "⚡ KÍCH HOẠT THÀNH CÔNG",
                    description = f"Lãnh Chúa đã bị ép giết **{result}**.\nBạn đã hi sinh vì nhiệm vụ.",
                    color       = 0xe74c3c
                ),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(f"❌ {result}", ephemeral=True)
        self.view.stop()


# ══════════════════════════════════════════════════════════════════
# ĐĂNG KÝ VÀO ROLE MANAGER
# ══════════════════════════════════════════════════════════════════

def register_role(manager):
    manager.register(ProTester)
