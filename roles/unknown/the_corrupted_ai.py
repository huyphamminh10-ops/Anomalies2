import discord
from roles.base_role import BaseRole

_PAGE_SIZE = 15   # Số người mỗi trang Select


class TheCorruptedAI(BaseRole):
    name        = "A.I THA HÓA"
    team        = "Unknown Entities"
    win_type    = "solo"
    max_count   = 1
    min_players = 32

    def __init__(self, player):
        super().__init__(player)
        self.shields          = 0   # tích lũy; khi ≥3 → chặn 1 đòn
        self.kill_charges     = 0   # tích lũy; cần 2 để giết 1 lần
        self.killed_survivors = 0
        self.killed_anomalies = 0
        self.killed_unknown   = 0
        self.last_scanned     = None

    description = (
        "Bạn là một AI bị tha hóa — thu thập dữ liệu từ cả hai phe để hoàn thành nhiệm vụ tiêu diệt.\n\n"
        "• Ban đêm có thể QUÉT 1 người để tích lũy tài nguyên:\n"
        "  - Quét Anomaly  → +1 Điểm Khiên  (cần 3 để chặn 1 đòn)\n"
        "  - Quét Survivor → +1 Điểm Giết   (cần 2 để giết 1 người)\n"
        "• Dùng Điểm Giết để tiêu diệt bất kỳ ai.\n"
        "• Điều kiện thắng: Đã giết ≥3 Survivors, ≥3 Anomalies và ≥3 Unknown (tổng 9)."
    )

    dm_message = (
        "🤖 **THE CORRUPTED AI – AI BỊ THA HÓA**\n\n"
        "Bạn thuộc phe **Unknown** — không phe phái, chỉ có mục tiêu thu thập và tiêu diệt.\n\n"
        "🌙 Mỗi đêm bạn thực hiện 2 hành động:\n"
        "• 🔍 QUÉT: Phân tích 1 người để nhận tài nguyên.\n"
        "  - Quét Anomaly  → +1 Điểm Khiên  (khi đủ 3 → tự động chặn 1 đòn tấn công)\n"
        "  - Quét Survivor → +1 Điểm Giết   (khi đủ 2 → dùng được 1 lần giết)\n"
        "• 💀 GIẾT: Tiêu tốn 2 Điểm Giết để hạ mục tiêu.\n\n"
        "🏆 Điều kiện thắng: Đã giết ≥3 Survivors + ≥3 Anomalies + ≥3 Unknown (tổng 9).\n"
        "⚠️ Không thể quét cùng 1 người 2 đêm liên tiếp.\n"
        "🔢 Tối thiểu 32 người chơi mới kích hoạt vai trò này."
    )

    # ================================
    # ĐIỀU KIỆN THẮNG
    # ================================
    def check_win_condition(self, game):
        return (
            self.killed_survivors >= 3 and
            self.killed_anomalies >= 3 and
            self.killed_unknown   >= 3
        )

    # ================================
    # GỬI UI BAN ĐÊM
    # ================================
    async def send_ui(self, game):
        alive = [
            p for p in game.get_alive_players()
            if p != self.player
        ]

        shield_bar = f"{self.shields}/3 " + "🟦" * min(self.shields, 3) + "⬜" * (3 - min(self.shields, 3))
        kill_bar   = f"{self.kill_charges}/2 " + "🟥" * min(self.kill_charges, 2) + "⬜" * (2 - min(self.kill_charges, 2))

        embed = discord.Embed(
            title="🤖 A.I THA HÓA — HÀNH ĐỘNG ĐÊM",
            description=(
                f"🛡️ Khiên : {shield_bar}\n"
                f"💀 Giết  : {kill_bar}\n\n"
                "**QUÉT** một người → tích lũy tài nguyên.\n"
                "**GIẾT** (cần **2** điểm) → hạ mục tiêu.\n\n"
                f"📊 Đã giết — "
                f"Survivors `{self.killed_survivors}/3` | "
                f"Anomalies `{self.killed_anomalies}/3` | "
                f"Unknown `{self.killed_unknown}/3`"
            ),
            color=0x1abc9c
        )

        view = TheCorruptedAI.AIView(game, self, alive)
        await self.safe_send(embed=embed, view=view)

    # ================================================================
    # PAGINATED VIEW  (15 người / trang)
    # ================================================================
    class AIView(discord.ui.View):
        PAGE_SIZE = _PAGE_SIZE

        def __init__(self, game, role, alive_list):
            super().__init__(timeout=60)
            self.game       = game
            self.role       = role
            self.alive_list = alive_list
            self.page       = 0
            self._rebuild()

        # ── tính tổng số trang ────────────────────────────────────
        @property
        def total_pages(self):
            return max(1, (len(self.alive_list) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

        # ── build lại toàn bộ items cho trang hiện tại ────────────
        def _rebuild(self):
            self.clear_items()

            start        = self.page * self.PAGE_SIZE
            page_players = self.alive_list[start : start + self.PAGE_SIZE]
            options      = [
                discord.SelectOption(label=p.display_name, value=str(p.id))
                for p in page_players
            ][:25]

            # ── 2 Select ở row 0 và row 1 ─────────────────────────
            self.add_item(TheCorruptedAI.ScanSelect(self.game, self.role, options, row=0))
            self.add_item(TheCorruptedAI.KillSelect(self.game, self.role, options, row=1))

            # ── Thanh điều hướng chỉ hiện khi có >1 trang ─────────
            if self.total_pages > 1:
                # Nút Trang Trước
                prev_btn = discord.ui.Button(
                    label="◀ Trước",
                    style=discord.ButtonStyle.secondary,
                    disabled=(self.page == 0),
                    row=2
                )
                prev_btn.callback = self._prev_callback

                # Nhãn trang (disabled button, chỉ để hiển thị)
                page_label = discord.ui.Button(
                    label=f"Trang {self.page + 1}/{self.total_pages}",
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                    row=2
                )

                # Nút Trang Sau
                next_btn = discord.ui.Button(
                    label="Sau ▶",
                    style=discord.ButtonStyle.secondary,
                    disabled=(self.page >= self.total_pages - 1),
                    row=2
                )
                next_btn.callback = self._next_callback

                self.add_item(prev_btn)
                self.add_item(page_label)
                self.add_item(next_btn)

        # ── Callbacks điều hướng ─────────────────────────────────
        async def _prev_callback(self, interaction: discord.Interaction):
            self.page = max(0, self.page - 1)
            self._rebuild()
            await interaction.response.edit_message(view=self)

        async def _next_callback(self, interaction: discord.Interaction):
            self.page = min(self.total_pages - 1, self.page + 1)
            self._rebuild()
            await interaction.response.edit_message(view=self)

    # ================================================================
    # SCAN SELECT
    # ================================================================
    class ScanSelect(discord.ui.Select):
        def __init__(self, game, role, options, row=0):
            self.game = game
            self.role = role
            super().__init__(
                placeholder="🔍 Quét một người...",
                options=options,
                min_values=1,
                max_values=1,
                row=row,
                custom_id="corrupted_ai_scan"
            )

        async def callback(self, interaction: discord.Interaction):
            target_id = int(self.values[0])

            if self.role.last_scanned == target_id:
                await interaction.response.send_message(
                    "⚠️ Không thể quét cùng một người 2 đêm liên tiếp.",
                    ephemeral=True
                )
                return

            target_role = self.game.roles.get(target_id)
            if target_role is None:
                await interaction.response.send_message(
                    "❌ Không tìm thấy mục tiêu.", ephemeral=True
                )
                return

            if target_role.team == "Anomalies":
                self.role.shields += 1
                gained = f"🛡️ +1 Điểm Khiên (tổng: **{self.role.shields}/3**)"
            elif target_role.team == "Survivors":
                self.role.kill_charges += 1
                gained = f"💀 +1 Điểm Giết (tổng: **{self.role.kill_charges}/2**)"
            else:
                gained = "ℹ️ Không thu được tài nguyên từ mục tiêu này."

            self.role.last_scanned = target_id
            await interaction.response.send_message(
                f"🤖 Quét hoàn tất.\n{gained}", ephemeral=True
            )

    # ================================================================
    # KILL SELECT  (cần 2 kill_charges)
    # ================================================================
    class KillSelect(discord.ui.Select):
        def __init__(self, game, role, options, row=1):
            self.game = game
            self.role = role
            super().__init__(
                placeholder="💀 Dùng 2 điểm giết...",
                options=options,
                min_values=1,
                max_values=1,
                row=row,
                custom_id="corrupted_ai_kill"
            )

        async def callback(self, interaction: discord.Interaction):
            if self.role.kill_charges < 2:
                await interaction.response.send_message(
                    f"❌ Cần **2 Điểm Giết** để hành động. Hiện có: `{self.role.kill_charges}/2`",
                    ephemeral=True
                )
                return

            target_id   = int(self.values[0])
            target      = self.game.get_member(target_id)
            target_role = self.game.roles.get(target_id)

            if not target or not self.game.is_alive(target_id):
                await interaction.response.send_message(
                    "❌ Mục tiêu không hợp lệ hoặc đã chết.", ephemeral=True
                )
                return

            await self.game.kill_player(target, reason="Bị Corrupted AI xử lý")
            self.role.kill_charges -= 2

            if target_role:
                if target_role.team == "Survivors":
                    self.role.killed_survivors += 1
                elif target_role.team == "Anomalies":
                    self.role.killed_anomalies += 1
                else:
                    self.role.killed_unknown += 1

            progress = (
                f"Survivors `{self.role.killed_survivors}/3` | "
                f"Anomalies `{self.role.killed_anomalies}/3` | "
                f"Unknown `{self.role.killed_unknown}/3`"
            )
            await interaction.response.send_message(
                f"💀 Mục tiêu đã bị xử lý.\n📊 Tiến độ: {progress}",
                ephemeral=True
            )
