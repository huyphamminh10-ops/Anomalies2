import asyncio
import disnake
from roles.base_role import BaseRole


class TheAvenger(BaseRole):
    name = "Kẻ Báo Thù"
    team = "Unknown Entities"   # ← Đổi sang Thực Thể Ẩn
    faction = "Unknown Entities"
    win_type = "solo"
    max_count = 1

    description = (
        "Bạn mang trong mình sự uất hận và sẽ kéo kẻ thù xuống mồ cùng mình tùy theo cách bạn bị tiêu diệt.\n\n"
        "• Bị Trục xuất (ban ngày): Chọn 1 người để giết.\n"
        "• Bị Dị Thể cắn: Chọn 1 người để giết.\n"
        "• Bị Thực Thể Ẩn tiêu diệt: Tự động giết chính kẻ đã ra tay.\n\n"
        "⚠ **Nerf:** Nếu bị trục xuất mà chọn nhầm Psychopath, Psychopath vẫn thắng với kết quả 'Bị Trục Xuất Ban Ngày'.\n"
        "Khi bạn chết, hệ thống sẽ dừng 30 giây để bạn chọn mục tiêu."
    )

    dm_message = (
        "⚔️ **KẺ BÁO THÙ**\n\n"
        "Bạn thuộc phe **Thực Thể Ẩn**.\n\n"
        "Nếu bạn chết, bạn sẽ kéo kẻ thù xuống cùng mình.\n\n"
        "🔥 Cơ chế trả thù:\n"
        "• Bị Trục xuất ban ngày: Chọn 1 người để giết.\n"
        "• Bị Dị Thể cắn: Chọn 1 người để giết.\n"
        "• Bị Unknown giết: Giết chính kẻ đã ra tay.\n\n"
        "⏳ Khi bạn chết, trận đấu sẽ tạm dừng 30 giây để bạn chọn mục tiêu."
    )

    def check_win_condition(self, game) -> bool:
        # Avenger thắng khi không còn Anomaly nào (cùng điều kiện với Survivor)
        alive_ids = game.alive_players - game.temporarily_removed
        for pid in alive_ids:
            r = game.roles.get(pid)
            if r and getattr(r, "team", "") == "Anomalies":
                return False
        return True

    def __init__(self, player):
        super().__init__(player)
        self.triggered = False

    # ==============================
    # GỬI UI BAN ĐÊM — Không có action, chỉ nhắc nhở
    # ==============================

    async def send_ui(self, game):
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="⚔️ ĐÊM — KẺ BÁO THÙ",
                    description=(
                        "Bạn không có hành động đặc biệt vào ban đêm.\n\n"
                        "🔥 Sức mạnh của bạn kích hoạt **khi bạn bị tiêu diệt**.\n"
                        "Hãy sống sót qua đêm nay."
                    ),
                    color=0x8e44ad
                )
            )
        except Exception:
            pass

    # ==============================
    # HOOK KHI CHẾT — Gửi UI chọn mục tiêu báo thù
    # ==============================

    async def on_death(self, game, death_reason, killer=None):
        if self.triggered:
            return
        self.triggered = True

        await game.add_log("⚔️ Kẻ Báo Thù đã ngã xuống... Trận đấu tạm dừng 30 giây để thực hiện trả thù.")

        if death_reason == "vote":
            await self._revenge_vote(game)
        elif death_reason == "anomalies":
            await self._revenge_anomalies(game)
        elif death_reason == "unknown":
            await self._revenge_unknown(game, killer)

    # ==============================
    # BỊ VOTE (BỊ TRỤC XUẤT BAN NGÀY) → chọn 1 người bất kỳ
    # ==============================

    async def _revenge_vote(self, game):
        # Nerf: không tự động giết Mayor, chỉ chọn 1 người bất kỳ
        candidates = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
        ]
        if not candidates:
            return

        chosen = await self._ask_revenge_target(game, candidates, "Bị trục xuất — Chọn 1 người để kéo theo:")
        if chosen and game.is_alive(chosen.id):
            # Nerf: nếu chọn nhầm Psychopath → Psychopath vẫn thắng (không bypass win)
            target_role = game.roles.get(chosen.id)
            if target_role and getattr(target_role, "name", "") == "Kẻ Tâm Thần":
                await game.add_log(
                    f"⚔️ Kẻ Báo Thù chọn {chosen.display_name} — nhưng **Kẻ Tâm Thần** vẫn thắng theo luật Bị Trục Xuất Ban Ngày!"
                )
                # Vẫn giết nhưng Psychopath đã được coi là thắng vì bị trục xuất
                await game.kill_player(chosen, reason="revenge", bypass_protection=True)
            else:
                await game.kill_player(chosen, reason="revenge", bypass_protection=True)
                await game.add_log(f"💀 {chosen.display_name} đã bị Kẻ Báo Thù kéo theo khi bị trục xuất!")

    # ==============================
    # BỊ DỊ THỂ CẮN → chọn 1 người bất kỳ
    # ==============================

    async def _revenge_anomalies(self, game):
        # Nerf: không tự động giết Lãnh Chúa, chỉ chọn 1 người bất kỳ
        candidates = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
        ]
        if not candidates:
            return

        chosen = await self._ask_revenge_target(game, candidates, "Bị Dị Thể cắn — Chọn 1 người để kéo theo:")
        if chosen and game.is_alive(chosen.id):
            await game.kill_player(chosen, reason="revenge", bypass_protection=True)
            await game.add_log(f"💀 {chosen.display_name} đã bị tiêu diệt bởi lời nguyền báo thù!")

    # ==============================
    # BỊ UNKNOWN → tự động giết kẻ ra tay
    # ==============================

    async def _revenge_unknown(self, game, killer=None):
        # BUG FIX #13: engine không truyền killer → tự tìm trong last_night_killers
        if killer is None:
            for kid in game.last_night_killers:
                r = game.roles.get(kid)
                if r and getattr(r, "team", "") in ("Unknown", "Unknown Entities"):
                    killer = game.get_member(kid)
                    break
        if killer and game.is_alive(killer.id if hasattr(killer, "id") else killer):
            await game.kill_player(killer, reason="revenge", bypass_protection=True)
            kname = killer.display_name if hasattr(killer, "display_name") else str(killer)
            await game.add_log(f"💀 {kname} đã bị Kẻ Báo Thù kéo xuống mồ cùng mình!")

    # ==============================
    # UI CHỌN MỤC TIÊU BÁO THÙ
    # ==============================

    async def _ask_revenge_target(self, game, candidates, prompt):
        future   = asyncio.get_event_loop().create_future()
        view     = self.RevengeView(self, candidates, prompt, future)

        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="⚔️ CHỌN MỤC TIÊU BÁO THÙ",
                    description=(
                        f"{prompt}\n\n"
                        "⏳ Bạn có **30 giây** để chọn.\n"
                        "Nếu không chọn, mục tiêu ngẫu nhiên sẽ bị chọn thay bạn."
                    ),
                    color=0x8e44ad
                ),
                view=view
            )
        except Exception:
            return None

        try:
            return await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            import random
            return random.choice(candidates) if candidates else None

    class RevengeView(disnake.ui.View):
        def __init__(self, role, candidates, prompt, future):
            super().__init__(timeout=30)
            self.role    = role
            self.future  = future
            self.add_item(TheAvenger.RevengeSelect(role, candidates, future))

        async def on_timeout(self):
            if not self.future.done():
                self.future.cancel()
            for item in self.children:
                item.disabled = True

    class RevengeSelect(disnake.ui.Select):
        def __init__(self, role, candidates, future):
            self.role    = role
            self.future  = future
            self.game_players = {str(p.id): p for p in candidates}
            options = [
                disnake.SelectOption(label=p.display_name, value=str(p.id), emoji="💀")
                for p in candidates
            ][:25]
            super().__init__(
                placeholder="Chọn mục tiêu trả thù...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            target = self.game_players.get(self.values[0])
            if not self.future.done():
                self.future.set_result(target)

            for item in self.view.children:
                item.disabled = True
            await interaction.message.edit(view=self.view)
            await interaction.response.send_message(
                embed=disnake.Embed(
                    description=f"⚔️ Bạn đã chọn **{target.display_name}** — lời nguyền đã được gửi đi.",
                    color=0x8e44ad
                ),
                ephemeral=True
            )
