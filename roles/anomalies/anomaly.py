import discord
from roles.base_role import BaseRole


class Anomaly(BaseRole):
    name = "Dị Thể"
    team = "Anomalies"
    max_count = 10

    description = (
        "Bạn là một Dị Thể — thành viên chiến đấu cốt lõi của phe Dị Thể.\n\n"
        "• Mỗi đêm bỏ phiếu cùng phe để chọn 1 mục tiêu tiêu diệt.\n"
        "• Khi Lãnh Chúa còn sống: Lãnh Chúa quyết định mục tiêu cuối cùng.\n"
        "• Khi Lãnh Chúa chết: toàn bộ Dị Thể còn sống cùng vote — đa số thắng.\n"
        "• Bạn biết danh tính tất cả đồng đội Dị Thể ngay từ đầu trận."
    )

    dm_message = (
        "🔴 **DỊ THỂ**\n\n"
        "Bạn thuộc phe **Dị Thể**.\n\n"
        "Bạn là chiến binh cốt lõi — sức mạnh nằm ở tập thể.\n\n"
        "📋 Cơ chế:\n"
        "• Mỗi đêm phe bạn cùng bỏ phiếu chọn 1 người để tiêu diệt.\n"
        "• Khi **Lãnh Chúa còn sống**: Lãnh Chúa có quyền quyết định cuối cùng.\n"
        "• Khi **Lãnh Chúa chết**: vote đa số trong phe sẽ quyết định mục tiêu.\n\n"
        "👁️ Bạn biết danh tính toàn bộ đồng đội Dị Thể.\n\n"
        "🏆 Điều kiện thắng: Dị Thể chiếm đa số hoặc bằng số Người Sống Sót còn lại.\n"
        "💡 Hãy phối hợp với đồng đội — sức mạnh của bạn là tổ chức, không phải cá nhân."
    )

    def __init__(self, player):
        super().__init__(player)
        self.vote_target = None       # Mục tiêu vote đêm nay
        self.anomaly_chat = None      # Kênh chat riêng của phe (nếu có)

    # =========================================
    # HOOK: GAME BẮT ĐẦU — Thông báo đồng đội
    # =========================================
    async def on_game_start(self, game):
        teammates = [
            game._players_dict[pid]
            for pid, role in game.roles.items()
            if getattr(role, "team", "") == "Anomalies" and pid != self.player.id
        ]

        if not teammates:
            return

        names = ", ".join(f"**{m.display_name}**" for m in teammates)

        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="👥 ĐỒNG ĐỘI DỊ THỂ",
                    description=f"Đồng đội của bạn:\n{names}",
                    color=0xe74c3c
                )
            )
        except Exception:
            pass

    # =========================================
    # GỬI UI BAN ĐÊM — Vote chọn mục tiêu
    # =========================================
    async def send_ui(self, game):
        self.vote_target = None

        overlord     = game.get_role_by_name("Lãnh Chúa")
        has_overlord = overlord is not None  # Lãnh Chúa có trong trận không

        # Nếu Lãnh Chúa còn sống → Lãnh Chúa tự quyết, Anomaly không cần vote
        if has_overlord and game.overlord_alive and game.is_alive(overlord.player.id):
            try:
                await self.safe_send(
                    embed=discord.Embed(
                        title="🌙 ĐÊM — CHỜ LỆNH",
                        description="Lãnh Chúa đang quyết định mục tiêu đêm nay.\nBạn không cần hành động.",
                        color=0xe74c3c
                    )
                )
            except Exception:
                pass
            return

        # Tự vote — Lãnh Chúa chết hoặc không có Lãnh Chúa trong trận
        alive_targets = [
            p for p in game.get_alive_players()
            if p.id != self.player.id
            and game.roles.get(p.id)
            and game.roles[p.id].team != "Dị Thể"
        ]

        if not alive_targets:
            return

        view = self.AnomalyVoteView(game, self, alive_targets)

        # Mô tả khác nhau tùy có Lãnh Chúa hay không
        if has_overlord:
            desc = "Lãnh Chúa đã ngã xuống.\nPhe Dị Thể tự quyết định — hãy bỏ phiếu chọn mục tiêu:"
        else:
            desc = "Phe Dị Thể tự quyết định — hãy bỏ phiếu chọn mục tiêu:"

        try:
            await self.safe_send(
                embed=discord.Embed(
                    title="🗳️ VOTE MỤC TIÊU ĐÊM NAY",
                    description=desc,
                    color=0xe74c3c
                ),
                view=view
            )
        except Exception:
            pass

    # =========================================
    # VIEW VOTE MỤC TIÊU
    # =========================================
    class AnomalyVoteView(discord.ui.View):
        def __init__(self, game, role, target_list):
            super().__init__(timeout=game.config.night_time + 30)
            options = [
                discord.SelectOption(label=p.display_name, value=str(p.id))
                for p in target_list
            ][:25]
            self.add_item(Anomaly.AnomalyVoteSelect(game, role, options))

    class AnomalyVoteSelect(discord.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role

            super().__init__(
                placeholder="Chọn mục tiêu để tiêu diệt...",
                options=options[:25],
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message(
                    "Đây không phải lượt của bạn.",
                    ephemeral=True
                )
                return

            target_id = int(self.values[0])
            self.role.vote_target = target_id

            # Tổng hợp vote từ tất cả Dị Thể và queue kill cho mục tiêu nhiều vote nhất
            self._resolve_anomaly_vote(target_id)

            target = self.game.players.get(target_id)
            await interaction.response.send_message(
                f"🗳️ Bạn đã vote: **{target.display_name if target else '?'}**",
                ephemeral=True
            )

            for item in self.view.children:
                item.disabled = True

            await interaction.message.edit(view=self.view)

        def _resolve_anomaly_vote(self, my_vote):
            """Tổng hợp vote — nếu đa số đồng ý, queue kill ngay."""
            vote_count = {}

            for pid, role in self.game.roles.items():
                if role.team == "Anomalies" and self.game.is_alive(pid):
                    v = getattr(role, "vote_target", None)
                    if v:
                        vote_count[v] = vote_count.get(v, 0) + 1

            # Tính đa số
            alive_anomalies = sum(
                1 for pid, role in self.game.roles.items()
                if role.team == "Anomalies" and self.game.is_alive(pid)
            )
            majority = alive_anomalies // 2 + 1

            for target_id, count in vote_count.items():
                if count >= majority:
                    # Tránh queue trùng
                    already_queued = any(
                        t == target_id for t, _, _ in self.game.kill_queue
                    )
                    if not already_queued:
                        self.game.queue_kill(
                            target_id,
                            reason="Bị Dị Thể tiêu diệt trong đêm"
                        )
                    break
