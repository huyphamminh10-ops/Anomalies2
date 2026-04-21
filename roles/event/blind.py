# ══════════════════════════════════════════════════════════════════
# roles/event/blind.py — Early Access Event Role
# Blind: Dị thể gây mù — làm xáo trộn danh sách mục tiêu của
# Survivors và Unknown khi họ dùng kỹ năng trong đêm.
# ══════════════════════════════════════════════════════════════════

import discord
from roles.base_role import BaseRole

# ── Tên hiển thị thay thế khi bị mù ─────────────────────────────
BLIND_LABEL = "👁 : ĐÃ BỊ MÙ"
BLIND_VALUE_PREFIX = "blind_"   # value của SelectOption bị mù: "blind_0", "blind_1"...


def make_blind_options(count: int) -> list[discord.SelectOption]:
    """Tạo danh sách SelectOption giả — toàn bộ là '👁 : ĐÃ BỊ MÙ'."""
    return [
        discord.SelectOption(
            label = BLIND_LABEL,
            value = f"{BLIND_VALUE_PREFIX}{i}",
            description = "Bạn không thể nhận diện mục tiêu này."
        )
        for i in range(max(1, count))
    ]


def is_blind_value(value: str) -> bool:
    """Kiểm tra xem value của SelectOption có phải do blind tạo ra không."""
    return value.startswith(BLIND_VALUE_PREFIX)


class Blind(BaseRole):
    name        = "Mù Quáng"
    team        = "Anomalies"
    faction     = "Anomalies"
    max_count   = 1
    min_players = 10

    description = (
        "Blind là một dị thể gây ra hiện tượng mù tạm thời.\n\n"
        "• Kích hoạt khiến toàn bộ Survivors và Unknown mất khả năng nhận diện mục tiêu.\n"
        "• Khi bị mù, danh sách chọn mục tiêu hiển thị '👁 : ĐÃ BỊ MÙ' thay vì tên thật.\n"
        "• Hiệu ứng kéo dài đến hết đêm đó.\n"
        "• Tối đa 3 lần sử dụng trong cả trận.\n"
        "• Blind không tham gia hành động tấn công — chỉ hỗ trợ chiến thuật."
    )

    dm_message = (
        "👁 **BLIND – MÙ**\n\n"
        "Bạn thuộc phe **Anomalies** — Early Access Event Role.\n\n"
        "🌫 Bạn có khả năng gây mù tạm thời cho kẻ thù.\n"
        "Khi kích hoạt, toàn bộ Survivors và Unknown sẽ không thể nhìn thấy tên mục tiêu thật.\n\n"
        "⚡ **Kỹ năng:** Gây Mù — tối đa **3 lần** trong cả trận.\n"
        "🌙 Hiệu ứng kéo dài đến hết đêm kích hoạt.\n\n"
        "🎯 Mục tiêu: Phe Anomalies chiến thắng."
    )

    def __init__(self, player):
        super().__init__(player)
        self.blind_remaining_uses: int = 3

    # ══════════════════════════════════════════════════════════════
    # GAME START
    # ══════════════════════════════════════════════════════════════

    async def on_game_start(self, game):
        # Đảm bảo key tồn tại trong night_effects
        game.night_effects.setdefault("blind_active", False)

        # Đăng ký hook on_day_end để tắt blind sau mỗi ngày
        game.register_mode_hook("on_day_end", self._on_day_end)

        try:
            await self.safe_send(
                embed=discord.Embed(
                    title       = "👁 BLIND — SỨ GIẢ CỦA BÓNG TỐI",
                    description = self.dm_message,
                    color       = 0x2c3e50
                )
            )
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # NIGHT UI
    # ══════════════════════════════════════════════════════════════

    async def send_ui(self, game):
        # Reset blind_active mỗi đêm mới
        game.night_effects["blind_active"] = False

        if not self.alive:
            return

        if self.blind_remaining_uses <= 0:
            try:
                await self.safe_send(
                    embed=discord.Embed(
                        title       = "🌙 ĐÊM — BLIND",
                        description = "Bạn đã dùng hết **3 lượt** gây mù.\n\n💤 Nghỉ ngơi đêm nay.",
                        color       = 0x95a5a6
                    )
                )
            except Exception:
                pass
            return

        view = BlindView(game, self)
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title       = "🌙 ĐÊM — BLIND",
                    description = (
                        f"👁 Lượt gây mù còn lại: **{self.blind_remaining_uses}/3**\n\n"
                        "Kích hoạt để che giấu danh sách mục tiêu của tất cả Survivors và Unknown.\n"
                        "Họ sẽ không biết mình đang chọn ai đêm nay."
                    ),
                    color       = 0x2c3e50
                ),
                view=view
            )
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # ACTIVATE — Gọi từ View
    # ══════════════════════════════════════════════════════════════

    async def activate_blind(self, game) -> tuple[bool, str]:
        if not self.alive:
            return False, "Bạn đã chết."
        if self.blind_remaining_uses <= 0:
            return False, "Đã hết lượt sử dụng."
        if game.night_effects.get("blind_active"):
            return False, "Hiệu ứng mù đang hoạt động rồi."

        self.blind_remaining_uses -= 1
        game.night_effects["blind_active"] = True

        # Thông báo toàn server (ẩn danh — không lộ Blind)
        try:
            if game.text_channel:
                await game.text_channel.send(
                    embed=discord.Embed(
                        title       = "🌫 HIỆN TƯỢNG DỊ THƯỜNG",
                        description = (
                            "Một hiện tượng dị thường đã xảy ra…\n\n"
                            "Tầm nhìn của nhiều người chơi đã bị bóp méo.\n"
                            "Một số kỹ năng đêm nay có thể không nhìn thấy mục tiêu thật."
                        ),
                        color       = 0x2c3e50
                    )
                )
        except Exception:
            pass

        return True, f"Đã kích hoạt! Còn lại {self.blind_remaining_uses} lượt."

    # ══════════════════════════════════════════════════════════════
    # HOOK — Tắt blind sau mỗi ngày
    # ══════════════════════════════════════════════════════════════

    async def _on_day_end(self, game):
        if game.night_effects.get("blind_active"):
            game.night_effects["blind_active"] = False


# ══════════════════════════════════════════════════════════════════
# DISCORD UI
# ══════════════════════════════════════════════════════════════════

class BlindView(discord.ui.View):
    def __init__(self, game, role: Blind):
        super().__init__(timeout=60)
        self.game = game
        self.role = role

    @discord.ui.button(label="👁 Kích hoạt Gây Mù", style=discord.ButtonStyle.danger, emoji="🌫")
    async def btn_activate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        success, msg = await self.role.activate_blind(self.game)
        color = 0x2c3e50 if success else 0xe74c3c
        await interaction.response.send_message(
            embed=discord.Embed(
                title       = "👁 GÂY MÙ" if success else "❌ Thất bại",
                description = msg,
                color       = color
            ),
            ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="💤 Bỏ qua đêm nay", style=discord.ButtonStyle.secondary)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
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


# ══════════════════════════════════════════════════════════════════
# ĐĂNG KÝ VÀO ROLE MANAGER
# ══════════════════════════════════════════════════════════════════

def register_role(manager):
    manager.register(Blind)
