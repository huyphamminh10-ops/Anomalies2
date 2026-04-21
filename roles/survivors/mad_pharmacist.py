import discord
from roles.base_role import BaseRole


class MadPharmacist(BaseRole):
    name        = "Nhà Dược Học Điên"
    team        = "Survivors"
    max_count   = 1
    min_players = 16

    # ══════════════════════════════════════════════════
    # INIT — 4 loại thuốc, mỗi chai dùng 1 lần
    # ══════════════════════════════════════════════════
    def __init__(self, player):
        super().__init__(player)
        self.potion_heal   = 2      # Hồi Phục Nhanh      — 2 lần
        self.potion_stop   = 1      # Thuốc Ngừng Tim      — 1 lần
        self.potion_glow   = 1      # Thuốc Phát Sáng      — 1 lần
        self.potion_ult    = 1      # Thuốc Trường Sinh / Thuốc Virus — 1 lần

        # Trạng thái runtime
        self.glow_targets: set = set()   # pid đang "phát sáng" — lộ diện khi chết
        self.immortal_targets: dict = {} # pid → số đêm còn bất tử
        self.virus_targets: set = set()  # pid đã uống Thuốc Virus — ai giết họ chết theo
        self.used_tonight = False

    # ══════════════════════════════════════════════════
    # DESCRIPTION & DM
    # ══════════════════════════════════════════════════
    description = (
        "Một dược sư điên đã chế được 4 loại thuốc đặc biệt.\n\n"
        "💊 **Hồi Phục Nhanh** *(2 lần — có thể dùng cho bản thân)*\n"
        "   Bảo vệ mục tiêu khỏi 1 lần bị giết trong đêm.\n\n"
        "💀 **Thuốc Ngừng Tim** *(1 lần)*\n"
        "   Giết mục tiêu ngay lập tức.\n\n"
        "✨ **Thuốc Phát Sáng** *(1 lần)*\n"
        "   Nếu mục tiêu bị Dị Thể giết, kẻ tấn công bị lộ tên cho toàn thị trấn.\n\n"
        "⚗️ **Thuốc Trường Sinh / Thuốc Virus** *(1 lần)*\n"
        "   — Nếu Hồi Phục vẫn còn: Bất tử 2 đêm tiếp theo.\n"
        "   — Nếu Hồi Phục đã hết: Mục tiêu chết ngay; ai cố giết họ chết theo.\n\n"
        "⚠️ Không dùng được cho bản thân (trừ Hồi Phục). Mỗi chai chỉ dùng 1 lần."
    )

    dm_message = (
        "🧪 **NHÀ DƯỢC HỌC ĐIÊN**\n\n"
        "Bạn thuộc phe **Survivors**.\n\n"
        "Bạn có 4 loại thuốc đặc biệt:\n\n"
        "💊 **Hồi Phục Nhanh** `×2` — Bảo vệ mục tiêu khỏi bị giết 1 lần. Có thể dùng cho bản thân.\n\n"
        "💀 **Ngừng Tim** `×1` — Giết mục tiêu ngay lập tức.\n\n"
        "✨ **Phát Sáng** `×1` — Nếu mục tiêu bị Dị Thể giết, kẻ đó bị lộ tên với toàn thị trấn.\n\n"
        "⚗️ **Trường Sinh / Virus** `×1`\n"
        "   • Hồi Phục còn → Bất tử 2 đêm.\n"
        "   • Hồi Phục hết → Mục tiêu chết ngay, ai giết họ cũng chết theo.\n\n"
        "📌 Không thể dùng thuốc cho bản thân (trừ Hồi Phục).\n"
        "📌 Tối thiểu 16 người chơi."
    )

    # ══════════════════════════════════════════════════
    # GỬI UI BAN ĐÊM
    # ══════════════════════════════════════════════════
    async def send_ui(self, game):
        self.used_tonight = False

        # Giảm đếm bất tử các mục tiêu
        expired = []
        for pid in list(self.immortal_targets):
            self.immortal_targets[pid] -= 1
            if self.immortal_targets[pid] <= 0:
                expired.append(pid)
                del self.immortal_targets[pid]

        # Kiểm tra còn thuốc không
        has_any = (
            self.potion_heal > 0 or self.potion_stop > 0 or
            self.potion_glow > 0 or self.potion_ult > 0
        )
        if not has_any:
            await self.safe_send(embed=discord.Embed(
                title="🧪 NHÀ DƯỢC HỌC ĐIÊN",
                description="Bạn đã dùng hết tất cả thuốc.",
                color=0x7f8c8d
            ))
            return

        ult_label = self._ult_label()

        embed = discord.Embed(
            title="🧪 NHÀ DƯỢC HỌC ĐIÊN — HÀNH ĐỘNG ĐÊM",
            description=(
                f"💊 Hồi Phục Nhanh : `{self.potion_heal}` lần còn lại\n"
                f"💀 Ngừng Tim       : `{self.potion_stop}` lần còn lại\n"
                f"✨ Phát Sáng       : `{self.potion_glow}` lần còn lại\n"
                f"⚗️ {ult_label}     : `{self.potion_ult}` lần còn lại\n\n"
                "Chọn thuốc và mục tiêu bên dưới."
            ),
            color=0x8e44ad
        )

        alive = [p for p in game.get_alive_players()]
        alive_others = [p for p in alive if p != self.player]

        view = MadPharmacist.PotionView(game, self, alive, alive_others)
        await self.safe_send(embed=embed, view=view)

    def _ult_label(self):
        return "Trường Sinh" if self.potion_heal > 0 else "Virus"

    # ══════════════════════════════════════════════════
    # HOOK: on_death — xử lý virus phòng thủ
    # ══════════════════════════════════════════════════
    async def on_death(self, game):
        pass   # Pharmacist không có on_death đặc biệt cho bản thân

    # ══════════════════════════════════════════════════
    # HOOK: can_be_killed — check bất tử và virus
    # Gọi từ game.py thông qua hook kill_player
    # ══════════════════════════════════════════════════

    # ══════════════════════════════════════════════════
    # VIEW CHỌN THUỐC
    # ══════════════════════════════════════════════════
    class PotionView(discord.ui.View):
        def __init__(self, game, role, alive_all, alive_others):
            super().__init__(timeout=60)
            self.game        = game
            self.role        = role
            self.alive_all   = alive_all    # bao gồm bản thân (cho Hồi Phục)
            self.alive_others = alive_others

            # Potion selector
            potion_options = []
            if role.potion_heal > 0:
                potion_options.append(discord.SelectOption(
                    label=f"💊 Hồi Phục Nhanh (×{role.potion_heal})",
                    value="heal",
                    description="Bảo vệ mục tiêu khỏi bị giết 1 lần (dùng cho bản thân được)"
                ))
            if role.potion_stop > 0:
                potion_options.append(discord.SelectOption(
                    label="💀 Thuốc Ngừng Tim",
                    value="stop",
                    description="Giết mục tiêu ngay lập tức"
                ))
            if role.potion_glow > 0:
                potion_options.append(discord.SelectOption(
                    label="✨ Thuốc Phát Sáng",
                    value="glow",
                    description="Lộ diện kẻ Dị Thể nếu chúng giết mục tiêu này"
                ))
            if role.potion_ult > 0:
                ult_name = "⚗️ Trường Sinh (Hồi Phục còn)" if role.potion_heal > 0 else "☠️ Thuốc Virus (Hồi Phục hết)"
                ult_desc = "Bất tử 2 đêm" if role.potion_heal > 0 else "Chết ngay; ai giết họ cũng chết theo"
                potion_options.append(discord.SelectOption(
                    label=ult_name,
                    value="ult",
                    description=ult_desc
                ))

            self.add_item(MadPharmacist.PotionSelect(game, role, potion_options))

    # ══════════════════════════════════════════════════
    # SELECT CHỌN THUỐC
    # ══════════════════════════════════════════════════
    class PotionSelect(discord.ui.Select):
        def __init__(self, game, role, options):
            self.game = game
            self.role = role
            super().__init__(
                placeholder="🧪 Chọn loại thuốc muốn dùng...",
                options=options[:25],
                min_values=1,
                max_values=1,
                row=0
            )

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            potion = self.values[0]
            # Xác định pool mục tiêu
            if potion == "heal":
                target_pool = self.game.get_alive_players()  # bao gồm bản thân
            else:
                target_pool = [p for p in self.game.get_alive_players() if p != self.role.player]

            target_options = [
                discord.SelectOption(label=p.display_name, value=str(p.id))
                for p in target_pool
            ][:25]

            if not target_options:
                await interaction.response.send_message("❌ Không có mục tiêu hợp lệ.", ephemeral=True)
                return

            # Thay view bằng target selector
            new_view = MadPharmacist.TargetView(self.game, self.role, potion, target_options)
            await interaction.response.edit_message(
                content=f"🎯 Chọn mục tiêu để dùng **{self._potion_name(potion)}**:",
                view=new_view
            )

        def _potion_name(self, p):
            return {
                "heal": "💊 Hồi Phục Nhanh",
                "stop": "💀 Thuốc Ngừng Tim",
                "glow": "✨ Thuốc Phát Sáng",
                "ult":  "⚗️ Trường Sinh / ☠️ Virus",
            }.get(p, p)

    # ══════════════════════════════════════════════════
    # VIEW CHỌN MỤC TIÊU
    # ══════════════════════════════════════════════════
    class TargetView(discord.ui.View):
        def __init__(self, game, role, potion, target_options):
            super().__init__(timeout=60)
            self.add_item(MadPharmacist.TargetSelect(game, role, potion, target_options))

    # ══════════════════════════════════════════════════
    # SELECT MỤC TIÊU + APPLY EFFECT
    # ══════════════════════════════════════════════════
    class TargetSelect(discord.ui.Select):
        def __init__(self, game, role, potion, options):
            self.game   = game
            self.role   = role
            self.potion = potion
            super().__init__(
                placeholder="🎯 Chọn người...",
                options=options[:25],
                min_values=1,
                max_values=1,
                row=0
            )

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.role.player.id:
                await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
                return

            if self.role.used_tonight:
                await interaction.response.send_message("Bạn đã dùng thuốc đêm nay rồi.", ephemeral=True)
                return

            target_id  = int(self.values[0])
            target     = self.game.get_member(target_id)
            if not target or not self.game.is_alive(target_id):
                await interaction.response.send_message("❌ Mục tiêu không hợp lệ.", ephemeral=True)
                return

            result_msg = await self._apply(target, target_id)
            self.role.used_tonight = True

            # Disable view
            for item in self.view.children:
                item.disabled = True
            await interaction.response.edit_message(content=result_msg, view=self.view)

        async def _apply(self, target, target_id) -> str:
            role = self.role
            game = self.game

            # ── 💊 HỒI PHỤC NHANH ─────────────────────────────────
            if self.potion == "heal":
                role.potion_heal -= 1
                game.protected.add(target_id)
                return f"💊 Đã cho **{target.display_name}** uống Thuốc Hồi Phục. Họ sẽ sống sót nếu bị tấn công đêm nay."

            # ── 💀 NGỪNG TIM ──────────────────────────────────────
            elif self.potion == "stop":
                role.potion_stop -= 1
                await game.kill_player(target, reason="Bị Nhà Dược Học Điên đầu độc")
                return f"💀 **{target.display_name}** đã uống Thuốc Ngừng Tim. Họ gục xuống trong đêm..."

            # ── ✨ PHÁT SÁNG ──────────────────────────────────────
            elif self.potion == "glow":
                role.potion_glow -= 1
                role.glow_targets.add(target_id)
                return f"✨ **{target.display_name}** đã được bôi Thuốc Phát Sáng. Kẻ nào dám giết họ sẽ bị lộ diện!"

            # ── ⚗️ TRƯỜNG SINH hoặc ☠️ VIRUS ──────────────────────
            elif self.potion == "ult":
                role.potion_ult -= 1

                if role.potion_heal > 0:
                    # Dạng 1: Trường Sinh
                    role.immortal_targets[target_id] = 2
                    return (
                        f"⚗️ **{target.display_name}** đã uống Thuốc Trường Sinh. "
                        f"Họ bất tử trong **2 đêm** tới!"
                    )
                else:
                    # Dạng 2: Virus
                    role.virus_targets.add(target_id)
                    await game.kill_player(target, reason="Bị Nhà Dược Học Điên tiêm Thuốc Virus", bypass=True)
                    return (
                        f"☠️ **{target.display_name}** đã uống Thuốc Virus và gục ngay lập tức. "
                        f"Bất kỳ ai cố giết họ sẽ chết theo!"
                    )

            return "✅ Đã dùng thuốc."
