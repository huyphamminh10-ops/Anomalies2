import asyncio
import disnake
from roles.base_role import BaseRole


class TheAvenger(BaseRole):
    name = "Kẻ Báo Thù"
    team = "Survivors"
    faction = "Survivors"
    max_count = 1

    description = (
        "Bạn mang trong mình sự uất hận và sẽ kéo kẻ thù xuống mồ cùng mình tùy theo cách bạn bị tiêu diệt.\n\n"
        "• Bị Trục xuất: Tiêu diệt Mayor và 1 Survivor tùy chọn.\n"
        "• Bị Dị Thể tiêu diệt: Tiêu diệt Lãnh Chúa và 1 Anomaly tùy chọn.\n"
        "• Bị Thực Thể Ẩn tiêu diệt: Tiêu diệt chính kẻ đã trực tiếp ra tay.\n\n"
        "Khi bạn chết, hệ thống sẽ dừng 30 giây để bạn chọn mục tiêu."
    )

    dm_message = (
        "⚔️ **KẺ BÁO THÙ**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "Nếu bạn chết, bạn sẽ kéo kẻ thù xuống cùng mình.\n\n"
        "🔥 Cơ chế trả thù:\n"
        "• Bị Trục xuất: Giết Mayor và 1 Survivor bạn chọn.\n"
        "• Bị Dị Thể giết: Giết Lãnh Chúa và 1 Anomaly bạn chọn.\n"
        "• Bị Unknown giết: Giết chính kẻ đã ra tay với bạn.\n\n"
        "⏳ Khi bạn chết, trận đấu sẽ tạm dừng 30 giây để bạn chọn mục tiêu."
    )

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
    # BỊ VOTE → chọn 1 Survivor
    # ==============================

    async def _revenge_vote(self, game):
        mayor = game.find_role("Mayor")
        # BUG FIX #12: role.alive không được engine update → dùng game.is_alive()
        if mayor and game.is_alive(mayor.player.id):
            await game.kill_player(mayor, reason="revenge", bypass_protection=True)
            await game.add_log("💀 Mayor đã bị Kẻ Báo Thù kéo xuống mồ!")

        candidates = [
            p for p in game.players
            if getattr(p, "faction", None) == "Survivors"
            and p.alive
            and p.id != self.player.id
        ]
        if not candidates:
            return

        chosen = await self._ask_revenge_target(game, candidates, "Chọn 1 Survivor để kéo theo:")
        if chosen and chosen.alive:
            await game.kill_player(chosen, reason="revenge", bypass_protection=True)
            await game.add_log(f"💀 {chosen.display_name} đã bị kéo theo trong cơn thịnh nộ của Kẻ Báo Thù!")

    # ==============================
    # BỊ ANOMALIES → chọn 1 Anomaly
    # ==============================

    async def _revenge_anomalies(self, game):
        overlord = game.find_role("Lãnh Chúa")
        # BUG FIX #12: role.alive không được engine update → dùng game.is_alive()
        if overlord and game.is_alive(overlord.player.id):
            await game.kill_player(overlord, reason="revenge", bypass_protection=True)
            await game.add_log("💀 Lãnh Chúa đã bị Kẻ Báo Thù tiêu diệt!")

        candidates = [
            p for p in game.players
            if getattr(p, "faction", None) == "Anomalies"
            and p.alive
        ]
        if not candidates:
            return

        chosen = await self._ask_revenge_target(game, candidates, "Chọn 1 Anomaly để kéo theo:")
        if chosen and chosen.alive:
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
