"""
roles/survivors/psychic.py — Người Tiên Tri (rework hoàn toàn)

Kỹ năng 1: Tiên Đoán Tương Lai  (1 lần | đoán đúng → KN3 +1, KN1 không mất | sai → mất KN1)
Kỹ năng 2: Kiểm Tra Ba           (1 lần | 30% sai 1 phần)
Kỹ năng 3: Bảo Hộ Linh Hồn      (2 lần | KN1 đúng → +1 lần)

on_game_start: DM bảng danh sách vai trò trận (không tiết lộ ai - vai)
"""
from __future__ import annotations
import random
import disnake
from roles.base_role import BaseRole

# ── Nhãn phe hiển thị ────────────────────────────────────────────────────────
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
    dif = 7

    description = (
        "Sở hữu 3 kỹ năng siêu nhiên, mỗi kỹ năng chỉ dùng được số lần giới hạn.\n\n"
        "🔮 **KN1 — Tiên Đoán Tương Lai** *(1 lần)*\n"
        "Viết dự đoán sự kiện đêm nay. A.I Gemini phán xét.\n"
        "✅ Đúng → KN3 hồi 1 lần, KN1 **không mất**.\n"
        "❌ Sai → mất KN1 vĩnh viễn.\n\n"
        "👁️ **KN2 — Kiểm Tra Ba** *(1 lần)*\n"
        "Chọn 3 người, nhận thống kê phe của họ. 30% kết quả bị sai 1 phần.\n\n"
        "🛡️ **KN3 — Bảo Hộ Linh Hồn** *(2 lần)*\n"
        "Tự bảo vệ bản thân khỏi bị giết trong đêm đó."
    )

    dm_message = (
        "🔮 **NGƯỜI TIÊN TRI**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "Bạn sở hữu 3 kỹ năng siêu nhiên:\n\n"
        "🔮 **KN1 — Tiên Đoán:** Ghi dự đoán, Gemini A.I kiểm chứng.\n"
        "  • Đúng → KN3 được hồi 1 lần, KN1 **không mất**\n"
        "  • Sai → KN1 **mất vĩnh viễn**\n\n"
        "👁️ **KN2 — Kiểm Tra Ba:** Chọn 3 người, xem thống kê phe của họ.\n"
        "  • Chỉ dùng 1 lần. Có 30% khả năng sai 1 phần.\n\n"
        "🛡️ **KN3 — Bảo Hộ Linh Hồn:** Tự bảo vệ bản thân 1 đêm.\n"
        "  • Mặc định 2 lần. KN1 đoán đúng hồi thêm 1 lần.\n\n"
        "Chúc bạn may mắn, hỡi người nắm giữ vận mệnh! 🌙"
    )

    def __init__(self, player):
        super().__init__(player)
        self.skill1_uses    = 1   # Tiên đoán
        self.skill2_uses    = 1   # Kiểm tra ba
        self.skill3_uses    = 2   # Bảo hộ linh hồn
        self.shield_tonight = False  # KN3 kích hoạt đêm nay

    # ── Hook: game bắt đầu ───────────────────────────────────────────────────
    async def on_game_start(self, game):
        """
        Gửi DM bảng danh sách tất cả vai trò trong trận.
        Không tiết lộ ai đang giữ vai trò nào.
        """
        # Thu thập danh sách vai trò không trùng
        role_names = sorted(set(
            getattr(r, "name", "???")
            for r in game.roles.values()
        ))

        # Nhóm theo phe
        survivor_roles = []
        anomaly_roles  = []
        unknown_roles  = []

        for pid, r in game.roles.items():
            rname = getattr(r, "name", "???")
            rteam = getattr(r, "team", "Survivors")
            entry = f"• {rname}"
            if rteam == "Anomalies":
                if entry not in anomaly_roles:
                    anomaly_roles.append(entry)
            elif rteam == "Unknown":
                if entry not in unknown_roles:
                    unknown_roles.append(entry)
            else:
                if entry not in survivor_roles:
                    survivor_roles.append(entry)

        embed = disnake.Embed(
            title="📋 DANH SÁCH VAI TRÒ TRẬN NÀY",
            description=(
                "Đây là tất cả các vai trò xuất hiện trong trận.\n"
                "*(Không tiết lộ ai đang giữ vai nào)*"
            ),
            color=0x9b59b6
        )

        if survivor_roles:
            embed.add_field(
                name="🟢 Phe Sống Sót",
                value="\n".join(sorted(survivor_roles)),
                inline=False
            )
        if anomaly_roles:
            embed.add_field(
                name="🔴 Phe Dị Thể",
                value="\n".join(sorted(anomaly_roles)),
                inline=False
            )
        if unknown_roles:
            embed.add_field(
                name="⚫ Thực Thể KXĐ",
                value="\n".join(sorted(unknown_roles)),
                inline=False
            )

        embed.set_footer(text="Người Tiên Tri | Dùng /psychic khi đêm đến để mở kỹ năng")
        await self.safe_send(embed=embed)

    # ── Hook: bị tấn công ────────────────────────────────────────────────────
    async def on_attacked(self, game, attacker):
        """Chặn đòn tấn công nếu KN3 đang bật đêm nay."""
        if self.shield_tonight:
            self.shield_tonight = False
            return True   # True = chặn thành công
        return False

    # ── Gửi UI đêm ───────────────────────────────────────────────────────────
    async def send_ui(self, game):
        self.shield_tonight = False  # reset mỗi đêm

        def _status(uses, label):
            if uses > 0:
                return f"✅ Còn **{uses}** lần"
            return "❌ Đã hết"

        embed = disnake.Embed(
            title="🔮 ĐÊM — NGƯỜI TIÊN TRI",
            color=0x9b59b6
        )
        embed.description = (
            f"🔮 **KN1 — Tiên Đoán Tương Lai** — {_status(self.skill1_uses, 'KN1')}\n"
            f"👁️ **KN2 — Kiểm Tra Ba**          — {_status(self.skill2_uses, 'KN2')}\n"
            f"🛡️ **KN3 — Bảo Hộ Linh Hồn**     — {_status(self.skill3_uses, 'KN3')}\n\n"
            "Chọn kỹ năng muốn dùng đêm nay:"
        )

        view = PsychicMainView(game, self)
        await self.safe_send(embed=embed, view=view)


# ════════════════════════════════════════════════════════════════════════════
# VIEW CHÍNH — chọn kỹ năng
# ════════════════════════════════════════════════════════════════════════════

class PsychicMainView(disnake.ui.View):
    def __init__(self, game, role: Psychic):
        super().__init__(timeout=90)
        self._game = game
        self._role = role
        self._rebuild()

    def _rebuild(self):
        self.clear_items()

        btn1 = disnake.ui.Button(
            label=f"🔮 Tiên Đoán ({self._role.skill1_uses} lần)",
            style=disnake.ButtonStyle.primary,
            disabled=(self._role.skill1_uses <= 0),
            row=0
        )
        btn1.callback = self._use_skill1
        self.add_item(btn1)

        btn2 = disnake.ui.Button(
            label=f"👁️ Kiểm Tra Ba ({self._role.skill2_uses} lần)",
            style=disnake.ButtonStyle.secondary,
            disabled=(self._role.skill2_uses <= 0),
            row=0
        )
        btn2.callback = self._use_skill2
        self.add_item(btn2)

        btn3 = disnake.ui.Button(
            label=f"🛡️ Bảo Hộ ({self._role.skill3_uses} lần)",
            style=disnake.ButtonStyle.success,
            disabled=(self._role.skill3_uses <= 0),
            row=0
        )
        btn3.callback = self._use_skill3
        self.add_item(btn3)

    def _is_owner(self, interaction: disnake.ApplicationCommandInteraction) -> bool:
        return interaction.user.id == self._role.player.id

    # ── KN1: Tiên Đoán ───────────────────────────────────────────────────────
    async def _use_skill1(self, interaction: disnake.ApplicationCommandInteraction):
        if not self._is_owner(interaction):
            return await interaction.response.send_message(
                "❌ Đây không phải lượt của bạn.", ephemeral=True
            )
        if self._role.skill1_uses <= 0:
            return await interaction.response.send_message(
                "❌ KN1 đã hết lượt dùng.", ephemeral=True
            )
        await interaction.response.send_modal(ProphecyModal(self._game, self._role, self))

    # ── KN2: Kiểm Tra Ba ─────────────────────────────────────────────────────
    async def _use_skill2(self, interaction: disnake.ApplicationCommandInteraction):
        if not self._is_owner(interaction):
            return await interaction.response.send_message(
                "❌ Đây không phải lượt của bạn.", ephemeral=True
            )
        if self._role.skill2_uses <= 0:
            return await interaction.response.send_message(
                "❌ KN2 đã hết lượt dùng.", ephemeral=True
            )

        alive = [p for p in self._game.get_alive_players() if p.id != self._role.player.id]
        if len(alive) < 3:
            return await interaction.response.send_message(
                "❌ Cần ít nhất 3 người còn sống (không kể bạn) để dùng kỹ năng này.",
                ephemeral=True
            )

        options = [
            disnake.SelectOption(label=p.display_name, value=str(p.id))
            for p in alive
        ][:25]

        view = TrioCheckView(self._game, self._role, self, options)
        await interaction.response.send_message(
            embed=disnake.Embed(
                title="👁️ KIỂM TRA BA",
                description=(
                    "Chọn đúng **3 người** để cảm nhận phe của họ.\n\n"
                    "⚠️ *Chỉ được dùng 1 lần. Kết quả có thể sai 1 phần.*"
                ),
                color=0x8e44ad
            ),
            view=view,
            ephemeral=True
        )

    # ── KN3: Bảo Hộ Linh Hồn ────────────────────────────────────────────────
    async def _use_skill3(self, interaction: disnake.ApplicationCommandInteraction):
        if not self._is_owner(interaction):
            return await interaction.response.send_message(
                "❌ Đây không phải lượt của bạn.", ephemeral=True
            )
        if self._role.skill3_uses <= 0:
            return await interaction.response.send_message(
                "❌ KN3 đã hết lượt dùng.", ephemeral=True
            )

        self._role.skill3_uses    -= 1
        self._role.shield_tonight  = True

        # Đăng ký bảo vệ với game engine
        if hasattr(self._game, "protected"):
            self._game.protected.add(self._role.player.id)

        self._rebuild()
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass

        await interaction.followup.send(
            embed=disnake.Embed(
                title="🛡️ BẢO HỘ LINH HỒN — ĐÃ KÍCH HOẠT",
                description=(
                    "✨ Bạn đã bao phủ linh hồn mình bằng một lớp **năng lượng hộ vệ**.\n\n"
                    "Bạn được bảo vệ khỏi bị giết trong đêm nay.\n\n"
                    f"*KN3 còn lại: **{self._role.skill3_uses}** lần.*"
                ),
                color=0x27ae60
            ),
            ephemeral=True
        )


# ════════════════════════════════════════════════════════════════════════════
# KN1 — MODAL TIÊN ĐOÁN
# ════════════════════════════════════════════════════════════════════════════

class ProphecyModal(disnake.ui.Modal):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("title", "🔮 Tiên Đoán Tương Lai")
        super().__init__(*args, **kwargs)

    prediction = disnake.ui.TextInput(
        label="Dự đoán của bạn về đêm nay",
        placeholder=(
            "VD: Đêm nay Kẻ Trừng Phạt bắn chết Hunt\n"
            "     Đêm nay Thám Tử Soi trúng Dị Thể\n"
            "     Đêm nay Sói giết Cá Mập"
        ),
        style=disnake.TextInputStyle.paragraph,
        max_length=300,
        required=True
    )

    def __init__(self, game, role: Psychic, parent_view: PsychicMainView):
        super().__init__(timeout=120)
        self._game        = game
        self._role        = role
        self._parent_view = parent_view

    async def on_submit(self, interaction: disnake.ModalInteraction):
        pred_text = self.prediction.value.strip()

        await interaction.response.send_message(
            embed=disnake.Embed(
                title="🔮 Đang hỏi Gemini A.I...",
                description=(
                    f"📜 Dự đoán: *\"{pred_text}\"*\n\n"
                    "⏳ Đang phán xét..."
                ),
                color=0x9b59b6
            ),
            ephemeral=True
        )

        # ── Gọi Gemini ───────────────────────────────────────────────────────
        is_correct = await self._ask_gemini(pred_text)

        if is_correct:
            # Đúng → không mất KN1, hồi KN3 +1
            self._role.skill3_uses += 1
            outcome_embed = disnake.Embed(
                title="🔮 TIÊN ĐOÁN — ✅ ĐÚNG!",
                description=(
                    f"📜 *\"{pred_text}\"*\n\n"
                    "✅ **Gemini A.I xác nhận dự đoán của bạn có cơ sở!**\n\n"
                    f"• 🔮 KN1 còn lại: **{self._role.skill1_uses} lần** *(không bị mất)*\n"
                    f"• 🛡️ KN3 được hồi thêm 1 lần → còn **{self._role.skill3_uses} lần**"
                ),
                color=0x2ecc71
            )
        else:
            # Sai → mất KN1 vĩnh viễn
            self._role.skill1_uses = 0
            outcome_embed = disnake.Embed(
                title="🔮 TIÊN ĐOÁN — ❌ SAI!",
                description=(
                    f"📜 *\"{pred_text}\"*\n\n"
                    "❌ **Gemini A.I không xác nhận dự đoán này.**\n\n"
                    "• 🔮 KN1 đã bị tiêu hao — còn **0 lần** *(mất vĩnh viễn)*"
                ),
                color=0xe74c3c
            )

        await interaction.followup.send(embed=outcome_embed, ephemeral=True)

        # Cập nhật lại nút trên view chính
        self._parent_view._rebuild()
        try:
            await self._role.player.send(view=self._parent_view)
        except Exception:
            pass

    # ── Gọi Gemini ───────────────────────────────────────────────────────────
    async def _ask_gemini(self, prediction: str) -> bool:
        """
        Hỏi Gemini: dự đoán này về sự kiện đêm nay có khả năng đúng không?
        Trả về True nếu Gemini xác nhận, False nếu không.
        Fallback ngẫu nhiên 50/50 nếu Gemini không khả dụng.
        """
        gemini = getattr(self._game, "gemini_host", None)
        if gemini is None or not getattr(gemini, "enabled", False):
            return random.random() < 0.5

        # Xây dựng context game
        alive_count = len(self._game.get_alive_players())
        dead_count  = len([p for p in self._game.players if not self._game.is_alive(p)])
        day_count   = getattr(self._game, "day_count", 1)

        # Lấy danh sách vai trò đang có trong game để Gemini tham khảo
        role_list = ", ".join(sorted(set(
            getattr(r, "name", "?")
            for r in self._game.roles.values()
        )))

        system = (
            "Bạn là một nhà tiên tri huyền bí trong trò chơi nhập vai suy luận xã hội (giống Ma Sói). "
            "Nhiệm vụ là phán xét xem dự đoán về sự kiện đêm nay của người chơi có hợp lý hay không, "
            "dựa trên bối cảnh game. "
            "Chỉ trả lời đúng 1 từ: 'ĐÚNG' hoặc 'SAI'. Không giải thích thêm."
        )

        prompt = (
            f"Trận đang ở ngày thứ {day_count}.\n"
            f"Còn {alive_count} người sống, {dead_count} người đã chết.\n"
            f"Các vai trò trong trận: {role_list}.\n\n"
            f"Dự đoán của người chơi: \"{prediction}\"\n\n"
            "Dự đoán này về sự kiện đêm nay có hợp lý và có khả năng đúng không?\n"
            "Chỉ trả lời 'ĐÚNG' hoặc 'SAI'."
        )

        try:
            response = await gemini._generate(
                system_instruction=system,
                prompt=prompt,
                key="psychic_prophecy"
            )
            if response:
                return "ĐÚNG" in response.upper()
        except Exception:
            pass

        return random.random() < 0.5


# ════════════════════════════════════════════════════════════════════════════
# KN2 — TRIO CHECK VIEW & SELECT
# ════════════════════════════════════════════════════════════════════════════

class TrioCheckView(disnake.ui.View):
    def __init__(self, game, role: Psychic, parent_view: PsychicMainView, options: list):
        super().__init__(timeout=60)
        self._game        = game
        self._role        = role
        self._parent_view = parent_view
        self.add_item(TrioCheckSelect(game, role, parent_view, options))


class TrioCheckSelect(disnake.ui.Select):
    def __init__(self, game, role: Psychic, parent_view: PsychicMainView, options: list):
        self._game        = game
        self._role        = role
        self._parent_view = parent_view
        super().__init__(
            placeholder="Chọn đúng 3 người để kiểm tra...",
            options=options,
            min_values=3,
            max_values=3
        )

    async def callback(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != self._role.player.id:
            return await interaction.response.send_message(
                "❌ Đây không phải lượt của bạn.", ephemeral=True
            )

        # Trừ lượt dùng
        self._role.skill2_uses = 0

        # Lấy team thực của 3 người được chọn
        real_teams = []
        for vid in self.values:
            role_obj = self._game.roles.get(int(vid))
            team     = getattr(role_obj, "team", "Survivors") if role_obj else "Survivors"
            real_teams.append(team)

        # ── 30% xác suất sai 1 phần ──────────────────────────────────────────
        # Cách sai: đổi 2 phần tử bất kỳ → thực tế 1 thông tin bị nhiễu
        display_teams = real_teams[:]
        if random.random() < 0.30 and len(set(display_teams)) >= 1:
            # Thay thế 1 team ngẫu nhiên bằng 1 team khác ngẫu nhiên
            all_teams = ["Survivors", "Anomalies", "Unknown"]
            idx       = random.randrange(len(display_teams))
            wrong_pool = [t for t in all_teams if t != display_teams[idx]]
            if wrong_pool:
                display_teams[idx] = random.choice(wrong_pool)

        # Đếm phe theo display_teams
        counts: dict[str, int] = {}
        for t in display_teams:
            label = _team_label(t)
            counts[label] = counts.get(label, 0) + 1

        # Định dạng kết quả
        result_lines = []
        for label, cnt in sorted(counts.items(), key=lambda x: -x[1]):
            result_lines.append(f"**{cnt}** người thuộc phe **{label}**")

        desc = (
            "3 người bạn đã chọn có:\n\n"
            + "\n".join(result_lines)
            + "\n\n⚠️ *Thông tin này có thể không chính xác một phần (30% sai).*"
        )

        # Disable select
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(view=self.view)

        await interaction.followup.send(
            embed=disnake.Embed(
                title="👁️ KẾT QUẢ — KIỂM TRA BA",
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
