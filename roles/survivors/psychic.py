"""
roles/survivors/psychic.py — Người Tiên Tri (rework hoàn toàn)

Kỹ năng 1: Tiên Đoán Tương Lai  (dùng 1 lần, không mất nếu đúng + hồi KN3)
Kỹ năng 2: Kiểm Tra Ba           (dùng 1 lần, 30% sai 1 phần)
Kỹ năng 3: Bảo Hộ Linh Hồn      (dùng 2 lần, KN1 đoán đúng hồi +1)
"""
from __future__ import annotations
import random
import discord
from roles.base_role import BaseRole

# ── Label phe hiển thị ───────────────────────────────────────────────────────
_TEAM_LABEL = {
    "Survivors": "Sống sót hiền lành",
    "Anomalies": "Dị thể",
    "Unknown":   "Thực thể KXĐ",
}

def _team_label(team: str) -> str:
    return _TEAM_LABEL.get(team, team)


# ════════════════════════════════════════════════════════════════════════════
# ROLE CLASS
# ════════════════════════════════════════════════════════════════════════════

class Psychic(BaseRole):
    name      = "Người Tiên Tri"
    team      = "Survivors"
    max_count = 1

    description = (
        "Sở hữu 3 kỹ năng siêu nhiên, mỗi kỹ năng chỉ dùng được số lần giới hạn.\n\n"
        "🔮 **KN1 — Tiên Đoán Tương Lai** *(1 lần)*\n"
        "Viết dự đoán, A.I phán xét. Đúng → KN3 hồi 1 lần, KN1 không mất. Sai → mất KN1.\n\n"
        "👁️ **KN2 — Kiểm Tra Ba** *(1 lần)*\n"
        "Chọn 3 người, nhận thống kê phe của họ. 30% kết quả bị sai 1 phần.\n\n"
        "🛡️ **KN3 — Bảo Hộ Linh Hồn** *(2 lần)*\n"
        "Tự bảo vệ bản thân khỏi bị giết trong đêm đó."
    )

    dm_message = (
        "🔮 **NGƯỜI TIÊN TRI**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "Bạn có 3 kỹ năng siêu nhiên:\n"
        "🔮 **KN1 — Tiên Đoán:** Dùng A.I để kiểm tra dự đoán của bạn.\n"
        "👁️ **KN2 — Kiểm Tra Ba:** Xem thống kê phe của 3 người bạn chọn.\n"
        "🛡️ **KN3 — Bảo Hộ:** Tự bảo vệ bản thân 1 đêm.\n\n"
        "Mỗi đêm bạn có thể dùng 1 hoặc nhiều kỹ năng còn lại."
    )

    def __init__(self, player):
        super().__init__(player)
        self.skill1_uses  = 1   # Tiên đoán
        self.skill2_uses  = 1   # Kiểm tra ba
        self.skill3_uses  = 2   # Bảo hộ linh hồn
        self.shield_tonight = False   # KN3 kích hoạt đêm nay

    async def send_ui(self, game):
        self.shield_tonight = False   # reset mỗi đêm
        embed = discord.Embed(
            title="🔮 ĐÊM — NGƯỜI TIÊN TRI",
            color=0x9b59b6
        )

        lines = []
        lines.append(f"🔮 **KN1 — Tiên Đoán Tương Lai** — {'✅ Còn ' + str(self.skill1_uses) + ' lần' if self.skill1_uses > 0 else '❌ Đã dùng hết'}")
        lines.append(f"👁️ **KN2 — Kiểm Tra Ba**         — {'✅ Còn ' + str(self.skill2_uses) + ' lần' if self.skill2_uses > 0 else '❌ Đã dùng hết'}")
        lines.append(f"🛡️ **KN3 — Bảo Hộ Linh Hồn**    — {'✅ Còn ' + str(self.skill3_uses) + ' lần' if self.skill3_uses > 0 else '❌ Đã dùng hết'}")
        embed.description = "\n".join(lines) + "\n\nChọn kỹ năng muốn dùng đêm nay:"

        view = PsychicMainView(game, self)
        await self.safe_send(embed=embed, view=view)

    async def on_attacked(self, game, attacker):
        """Hook gọi khi bị tấn công — KN3 chặn nếu đang bật."""
        if self.shield_tonight:
            self.shield_tonight = False
            return True   # True = chặn được
        return False


# ════════════════════════════════════════════════════════════════════════════
# VIEW CHÍNH — chọn kỹ năng
# ════════════════════════════════════════════════════════════════════════════

class PsychicMainView(discord.ui.View):
    def __init__(self, game, role: Psychic):
        super().__init__(timeout=90)
        self._game = game
        self._role = role
        self._rebuild()

    def _rebuild(self):
        self.clear_items()

        btn1 = discord.ui.Button(
            label=f"🔮 Tiên Đoán ({self._role.skill1_uses} lần)",
            style=discord.ButtonStyle.primary,
            disabled=(self._role.skill1_uses <= 0),
            row=0
        )
        btn1.callback = self._use_skill1
        self.add_item(btn1)

        btn2 = discord.ui.Button(
            label=f"👁️ Kiểm Tra Ba ({self._role.skill2_uses} lần)",
            style=discord.ButtonStyle.secondary,
            disabled=(self._role.skill2_uses <= 0),
            row=0
        )
        btn2.callback = self._use_skill2
        self.add_item(btn2)

        btn3 = discord.ui.Button(
            label=f"🛡️ Bảo Hộ ({self._role.skill3_uses} lần)",
            style=discord.ButtonStyle.success,
            disabled=(self._role.skill3_uses <= 0),
            row=0
        )
        btn3.callback = self._use_skill3
        self.add_item(btn3)

    def _check_owner(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self._role.player.id

    # ── KN1: Tiên Đoán ───────────────────────────────────────────────────────
    async def _use_skill1(self, interaction: discord.Interaction):
        if not self._check_owner(interaction):
            return await interaction.response.send_message("Không phải lượt của bạn.", ephemeral=True)
        if self._role.skill1_uses <= 0:
            return await interaction.response.send_message("❌ KN1 đã hết lượt dùng.", ephemeral=True)

        await interaction.response.send_modal(ProphecyModal(self._game, self._role, self))

    # ── KN2: Kiểm Tra Ba ─────────────────────────────────────────────────────
    async def _use_skill2(self, interaction: discord.Interaction):
        if not self._check_owner(interaction):
            return await interaction.response.send_message("Không phải lượt của bạn.", ephemeral=True)
        if self._role.skill2_uses <= 0:
            return await interaction.response.send_message("❌ KN2 đã hết lượt dùng.", ephemeral=True)

        alive = [p for p in self._game.get_alive_players() if p.id != self._role.player.id]
        if len(alive) < 3:
            return await interaction.response.send_message(
                "❌ Cần ít nhất 3 người sống để dùng kỹ năng này.", ephemeral=True
            )

        options = [
            discord.SelectOption(label=p.display_name, value=str(p.id))
            for p in alive
        ][:25]

        view = TrioCheckView(self._game, self._role, self, options)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="👁️ KIỂM TRA BA",
                description="Chọn đúng **3 người** để cảm nhận phe của họ:",
                color=0x8e44ad
            ),
            view=view,
            ephemeral=True
        )

    # ── KN3: Bảo Hộ Linh Hồn ────────────────────────────────────────────────
    async def _use_skill3(self, interaction: discord.Interaction):
        if not self._check_owner(interaction):
            return await interaction.response.send_message("Không phải lượt của bạn.", ephemeral=True)
        if self._role.skill3_uses <= 0:
            return await interaction.response.send_message("❌ KN3 đã hết lượt dùng.", ephemeral=True)

        self._role.skill3_uses    -= 1
        self._role.shield_tonight  = True

        # Đăng ký bảo vệ với game engine
        self._game.protected.add(self._role.player.id)

        # Disable nút KN3 ngay
        self._rebuild()
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass

        await interaction.followup.send(
            embed=discord.Embed(
                title="🛡️ BẢO HỘ LINH HỒN",
                description=(
                    "✨ Bạn đã bao phủ linh hồn mình bằng một lớp **năng lượng hộ vệ**.\n"
                    f"Bạn được bảo vệ khỏi bị giết đêm nay.\n\n"
                    f"*KN3 còn lại: {self._role.skill3_uses} lần.*"
                ),
                color=0x27ae60
            ),
            ephemeral=True
        )


# ════════════════════════════════════════════════════════════════════════════
# KN1 — MODAL TIÊN ĐOÁN
# ════════════════════════════════════════════════════════════════════════════

class ProphecyModal(discord.ui.Modal, title="🔮 Tiên Đoán Tương Lai"):
    prediction = discord.ui.TextInput(
        label="Dự đoán của bạn",
        placeholder="VD: Người X là Dị Thể / Đêm nay sẽ có người chết...",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=True
    )

    def __init__(self, game, role: Psychic, parent_view: PsychicMainView):
        super().__init__(timeout=120)
        self._game        = game
        self._role        = role
        self._parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        pred_text = self.prediction.value.strip()

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔮 Đang hỏi A.I...",
                description=f"*\"{pred_text}\"*\n\nĐang phán xét dự đoán của bạn...",
                color=0x9b59b6
            ),
            ephemeral=True
        )

        # ── Gọi Gemini ───────────────────────────────────────────────────────
        result = await self._ask_gemini(pred_text)

        if result is True:
            # Đúng → không mất KN1, hồi KN3
            self._role.skill3_uses += 1
            outcome_embed = discord.Embed(
                title="🔮 TIÊN ĐOÁN — ĐÚNG!",
                description=(
                    f"*\"{pred_text}\"*\n\n"
                    "✅ **A.I xác nhận dự đoán của bạn là có cơ sở!**\n\n"
                    f"• 🔮 KN1 còn lại: **{self._role.skill1_uses} lần** *(không mất)*\n"
                    f"• 🛡️ KN3 được hồi thêm 1 lần → còn **{self._role.skill3_uses} lần**"
                ),
                color=0x2ecc71
            )
        else:
            # Sai → mất KN1
            self._role.skill1_uses = 0
            outcome_embed = discord.Embed(
                title="🔮 TIÊN ĐOÁN — SAI!",
                description=(
                    f"*\"{pred_text}\"*\n\n"
                    "❌ **A.I không xác nhận dự đoán này.**\n\n"
                    f"• 🔮 KN1 đã bị tiêu hao — còn **0 lần**"
                ),
                color=0xe74c3c
            )

        await interaction.followup.send(embed=outcome_embed, ephemeral=True)

        # Cập nhật lại view chính
        self._parent_view._rebuild()
        try:
            await self._role.player.send(view=self._parent_view)
        except Exception:
            pass

    async def _ask_gemini(self, prediction: str) -> bool:
        """
        Hỏi Gemini: dự đoán này có khả năng đúng không?
        Trả về True nếu Gemini xác nhận, False nếu không.
        Fallback ngẫu nhiên nếu Gemini không khả dụng.
        """
        gemini = getattr(self._game, "gemini_host", None)
        if gemini is None or not getattr(gemini, "enabled", False):
            # Không có Gemini → fallback 50/50
            return random.random() < 0.5

        # Xây context về trạng thái game
        alive_count = len(self._game.get_alive_players())
        dead_count  = len([p for p in self._game.players if not self._game.is_alive(p)])
        day_count   = getattr(self._game, "day_count", 1)

        system = (
            "Bạn là một nhà tiên tri huyền bí trong một trò chơi nhập vai suy luận xã hội. "
            "Nhiệm vụ của bạn là phán xét xem một dự đoán của người chơi có hợp lý hay không "
            "dựa trên bối cảnh game. Trả lời CHỈ bằng 'ĐÚNG' hoặc 'SAI', không giải thích thêm."
        )

        prompt = (
            f"Trò chơi đang ở ngày {day_count}. "
            f"Còn {alive_count} người sống, {dead_count} người đã chết.\n"
            f"Dự đoán của người chơi: \"{prediction}\"\n\n"
            "Dự đoán này có hợp lý và có khả năng đúng trong bối cảnh này không? "
            "Chỉ trả lời 'ĐÚNG' hoặc 'SAI'."
        )

        try:
            response = await gemini._generate(
                system_instruction=system,
                prompt=prompt,
                key="main"
            )
            if response:
                return "ĐÚNG" in response.upper()
        except Exception:
            pass

        return random.random() < 0.5


# ════════════════════════════════════════════════════════════════════════════
# KN2 — TRIO CHECK VIEW
# ════════════════════════════════════════════════════════════════════════════

class TrioCheckView(discord.ui.View):
    def __init__(self, game, role: Psychic, parent_view: PsychicMainView, options: list):
        super().__init__(timeout=60)
        self._game        = game
        self._role        = role
        self._parent_view = parent_view
        self.add_item(TrioCheckSelect(game, role, parent_view, options))


class TrioCheckSelect(discord.ui.Select):
    def __init__(self, game, role: Psychic, parent_view: PsychicMainView, options: list):
        self._game        = game
        self._role        = role
        self._parent_view = parent_view
        super().__init__(
            placeholder="Chọn đúng 3 người...",
            options=options,
            min_values=3,
            max_values=3
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self._role.player.id:
            return await interaction.response.send_message("Không phải lượt của bạn.", ephemeral=True)

        # Trừ lượt dùng
        self._role.skill2_uses = 0

        # Lấy team thực của 3 người được chọn
        real_teams = []
        for vid in self.values:
            member    = self._game.get_member(int(vid))
            role_obj  = self._game.roles.get(int(vid))
            team      = getattr(role_obj, "team", "Survivors") if role_obj else "Survivors"
            real_teams.append(team)

        # 30% xác suất sai 1 phần
        display_teams = real_teams[:]
        if random.random() < 0.30 and len(display_teams) >= 2:
            # Đổi chỗ 2 phần tử ngẫu nhiên → 1 thông tin sai
            i, j = random.sample(range(len(display_teams)), 2)
            display_teams[i], display_teams[j] = display_teams[j], display_teams[i]

        # Đếm phe (dùng display_teams để hiển thị)
        counts = {}
        for t in display_teams:
            label = _team_label(t)
            counts[label] = counts.get(label, 0) + 1

        result_lines = [f"**{cnt} {lbl}**" for lbl, cnt in sorted(counts.items())]
        desc = (
            "3 người bạn đã chọn có:\n\n"
            + "\n".join(result_lines)
            + "\n\n⚠️ *Thông tin này có thể không chính xác một phần.*"
        )

        # Disable select
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(view=self.view)

        await interaction.followup.send(
            embed=discord.Embed(
                title="👁️ KẾT QUẢ KIỂM TRA BA",
                description=desc,
                color=0x8e44ad
            ),
            ephemeral=True
        )

        # Cập nhật view chính
        self._parent_view._rebuild()
        try:
            await self._role.player.send(view=self._parent_view)
        except Exception:
            pass
