# ══════════════════════════════════════════════════════════════════
# roles/event/cipher_breaker.py — Vai Trò Sự Kiện Đặc Biệt
# Kẻ Giải Mã: Kẻ Mã Hóa — Thực Thể Ẩn solo win
#
# Cơ chế hoạt động:
#   - on_game_start: wrap game.text_channel bằng CipherChannel
#   - CipherChannel intercept TẤT CẢ .send() → nhiễu tự động
#   - on_game_start: đăng ký hook on_player_message → nhiễu chat người chơi
#   - Chat người chơi: LUÔN nhiễu passive (intensity=0.50), độc lập với
#     destroy mode — người chơi chỉ đọc được ~50% tin nhắn của nhau.
#   - game.py không cần sửa gì thêm
# ══════════════════════════════════════════════════════════════════

import random
import discord
from roles.base_role import BaseRole

# ── Bộ ký tự ─────────────────────────────────────────────────────
# ASCII noise
_ASCII       = list("×÷=/_ <>[]!@#₫%^&*()-'+:;?~")
# Box Drawing — ─━│┃┌┐└┘├┤┬┴┼╔╗╚╝║═╠╣╦╩╬
_BOX         = [chr(i) for i in range(0x2500, 0x2570)]
# Braille — ⠁⠂⠃⠄⠅⠆⠇⠈⠉...
_BRAILLE     = [chr(i) for i in range(0x2801, 0x2840)]
# Runic — ᚠᚡᚢᚣᚤ...
_RUNIC       = [chr(i) for i in range(0x16A0, 0x16F0)]
# Math Operators — ∀∂∃∅∆∇∈∏∑√∞∫≠≡≤≥
_MATH        = [chr(i) for i in range(0x2200, 0x2260)]
# Geometric shapes — ■□▲△▶▷◆◇○●
_GEO         = [chr(i) for i in range(0x25A0, 0x25FF)]
# Arrows — ←↑→↓↔↕↖↗↘↙
_ARROWS      = [chr(i) for i in range(0x2190, 0x21B0)]

# Passive: nhiễu nhẹ — ký tự dễ nhầm với chữ cái thật
# Loại bỏ space để đảm bảo _corrupt_text/_corrupt_player_msg
# không bao giờ tạo ra hoặc thay thế bằng dấu cách.
_NOISE_CHARS = [ch for ch in _ASCII + _BOX[:20] + _MATH[:20] + _ARROWS[:15] if ch != " "]
# Active: phá hủy hoàn toàn — tất cả pool
_CHAOS_POOL  = _ASCII + _BOX + _BRAILLE + _RUNIC + _MATH + _GEO + _ARROWS

# ── Ngưỡng win ───────────────────────────────────────────────────
WIN_SURVIVORS_DEAD = 4
WIN_ANOMALIES_DEAD = 4

# ── Nhiễu chat người chơi ────────────────────────────────────────
# Luôn là passive (không bị destroy mode ảnh hưởng).
# 0.50 = ~50% ký tự bị thay — người chơi vẫn đọc được khoảng một nửa.
PLAYER_MSG_CORRUPT_INTENSITY: float = 0.50


# ══════════════════════════════════════════════════════════════════
# TEXT TRANSFORM
# ══════════════════════════════════════════════════════════════════

def _corrupt_text(text: str, intensity: float = 0.20) -> str:
    """Passive: nhiễu nhẹ — vẫn đọc được phần lớn.
    Chỉ corrupt ký tự chữ/số — whitespace luôn giữ nguyên để cách chữ ra."""
    if not text:
        return text
    chars = list(text)
    for i in range(len(chars)):
        if chars[i].isspace():
            continue
        if random.random() < intensity:
            chars[i] = random.choice(_NOISE_CHARS)
    # Chèn thêm ký tự lạ — chỉ vào vị trí không phải whitespace
    non_ws = [i for i, ch in enumerate(chars) if not ch.isspace()]
    for _ in range(max(1, int(len(text) * 0.08))):
        pos = random.choice(non_ws) if non_ws else random.randint(0, len(chars))
        chars.insert(pos, random.choice(_NOISE_CHARS))
    return "".join(chars)


def _destroy_text(text: str) -> str:
    """Active: phá hủy hoàn toàn — chuỗi hỗn loạn."""
    if not text:
        return text
    return "".join(random.choice(_CHAOS_POOL) for _ in range(max(10, len(text))))


def _corrupt_player_msg(text: str) -> str:
    """
    Nhiễu tin nhắn người chơi — LUÔN passive, độc lập với destroy mode.
    intensity = PLAYER_MSG_CORRUPT_INTENSITY (0.50) → ~50% ký tự bị thay.
    Không chèn thêm ký tự (giữ độ dài gốc để đọc bớt khó hơn).
    """
    if not text:
        return text
    chars = list(text)
    for i in range(len(chars)):
        if chars[i].isspace():
            continue
        if random.random() < PLAYER_MSG_CORRUPT_INTENSITY:
            chars[i] = random.choice(_NOISE_CHARS)
    return "".join(chars)


def _transform_embed(embed: discord.Embed, fn) -> discord.Embed:
    """Áp transform lên title + description của embed."""
    if embed.title:
        embed.title = fn(embed.title)
    if embed.description:
        embed.description = fn(embed.description)
    # Nhiễu cả fields
    for field in embed.fields:
        embed._fields[embed.fields.index(field)] = {
            "name":   fn(field.name)  if field.name  else field.name,
            "value":  fn(field.value) if field.value else field.value,
            "inline": field.inline,
        }
    return embed


# ══════════════════════════════════════════════════════════════════
# CIPHER CHANNEL WRAPPER
# Wrap text_channel — intercept tất cả .send() mà không cần
# sửa game.py ở bất kỳ chỗ nào.
# ══════════════════════════════════════════════════════════════════

class CipherChannel:
    """
    Proxy của discord.TextChannel.
    Khi cipher_alive=True  → nhiễu passive mọi tin nhắn.
    Khi cipher_destroy=True → phá hủy hoàn toàn.
    Mọi attribute/method khác delegate thẳng về channel gốc.
    """

    def __init__(self, original: discord.TextChannel, game):
        self._original = original
        self._game     = game

    def _pick_fn(self):
        """Chọn hàm transform phù hợp theo state hiện tại."""
        effects = self._game.night_effects
        if effects.get("cipher_destroy_active", False):
            return _destroy_text
        if effects.get("cipher_alive", False):
            return _corrupt_text
        return None

    async def send(self, content=None, embed=None, **kwargs):
        fn = self._pick_fn()
        if fn:
            if content:
                content = fn(content)
            if embed:
                embed = _transform_embed(embed, fn)
        return await self._original.send(content=content, embed=embed, **kwargs)

    # Delegate tất cả attribute còn lại về channel gốc
    def __getattr__(self, item):
        return getattr(self._original, item)


# ══════════════════════════════════════════════════════════════════
# MAIN CLASS
# ══════════════════════════════════════════════════════════════════

class CipherBreaker(BaseRole):
    name        = "Kẻ Giải Mã"
    team        = "Unknown Entities"
    faction     = "Unknown Entities"
    win_type    = "solo"
    max_count   = 1
    min_players = 16

    description = (
        "Kẻ Mã Hóa — thực thể bí ẩn phá hủy hệ thống truyền tin.\n\n"
        "• **Passive:** Khi còn sống, mọi thông báo bot đều bị nhiễu ký tự.\n"
        "• **Passive:** Chat của người chơi bị nhiễu ~50% ký tự (luôn hoạt động, kể cả khi không dùng kỹ năng).\n"
        "• **Kỹ năng (5 lần):** Phá hủy hoàn toàn mọi thông báo bot thành chuỗi hỗn loạn.\n"
        "• **Chiến thắng:** 4 Người Sống Sót VÀ 4 Dị Thể đã chết.\n"
        "• DM riêng của Kẻ Giải Mã không bị ảnh hưởng."
    )

    dm_message = (
        "💀 **KẺ GIẢI MÃ**\n\n"
        "Bạn thuộc phe **Thực Thể Ẩn** — không đồng minh, không phe phái.\n\n"
        "📡 **Passive – Nhiễu Loạn Hệ Thống:**\n"
        "Khi bạn còn sống, mọi thông báo công khai của bot bị nhiễu ký tự ngẫu nhiên.\n"
        "Kể cả thông báo đêm, sáng, bỏ phiếu, di chúc — tất cả.\n\n"
        "💬 **Passive – Nhiễu Chat Người Chơi:**\n"
        "Mọi tin nhắn người chơi gửi trong kênh game đều bị nhiễu ~50% ký tự.\n"
        "Hiệu ứng này luôn hoạt động, **không** bị destroy mode thay thế.\n\n"
        "💣 **Kỹ năng – Phá Hủy Hệ Thống (5 lần):**\n"
        "Kích hoạt ban đêm để biến mọi thông báo bot thành chuỗi ký tự hỗn loạn hoàn toàn.\n\n"
        "🏆 **Chiến thắng khi:**\n"
        "• **4 Người Sống Sót** đã chết **VÀ** **4 Dị Thể** đã chết\n"
        "• Cả hai phe thiệt hại nặng nề — hệ thống sụp đổ.\n\n"
        "⚠️ DM riêng của bạn sẽ không bị nhiễu."
    )

    def __init__(self, player):
        super().__init__(player)
        self.destroy_uses: int    = 5
        self.destroy_active: bool = False
        self.survivors_killed: int = 0
        self.anomalies_killed: int = 0
        self._original_channel    = None  # lưu channel gốc để restore khi chết

    # ══════════════════════════════════════════════════════════════
    # GAME START — wrap text_channel
    # ══════════════════════════════════════════════════════════════

    async def on_game_start(self, game):
        # Wrap text_channel bằng CipherChannel
        self._original_channel  = game.text_channel
        game.text_channel       = CipherChannel(game.text_channel, game)
        game.log_channel        = game.text_channel  # sync log_channel

        # Bật passive
        game.night_effects["cipher_alive"]          = True
        game.night_effects["cipher_destroy_active"] = False

        # Đăng ký hook đếm kills
        game.register_mode_hook("on_night_end",       self._on_night_end)
        game.register_mode_hook("on_vote_end",        self._on_vote_end)
        # Intercept chat người chơi — luôn passive, độc lập với destroy mode
        game.register_mode_hook("on_player_message",  self._on_player_message)

        # DM riêng — không đi qua CipherChannel nên không bị nhiễu
        try:
            await self.safe_send(
                embed=discord.Embed(
                    title       = "💀 KẺ GIẢI MÃ — MÃ HÓA HỆTHỐNG",
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
        # Reset destroy mỗi đêm
        self.destroy_active = False
        game.night_effects["cipher_destroy_active"] = False

        if not self.alive:
            return

        try:
            desc = (
                f"📊 **Tiến độ thắng:**\n"
                f"• Người Sống Sót đã chết: **{self.survivors_killed}/{WIN_SURVIVORS_DEAD}**\n"
                f"• Dị Thể đã chết: **{self.anomalies_killed}/{WIN_ANOMALIES_DEAD}**\n\n"
            )

            if self.destroy_uses <= 0:
                await self.safe_send(
                    embed=discord.Embed(
                        title       = "🌙 ĐÊM — KẺ GIẢI MÃ",
                        description = desc + "💣 Đã hết lượt phá hủy.\n💤 Passive nhiễu vẫn hoạt động.",
                        color       = 0x2c3e50
                    )
                )
                return

            view = CipherBreakerView(game, self)
            await self.safe_send(
                embed=discord.Embed(
                    title       = "🌙 ĐÊM — KẺ GIẢI MÃ",
                    description = desc + f"💣 Lượt phá hủy còn lại: **{self.destroy_uses}/5**\n"
                                         "Kích hoạt để biến mọi thông báo thành hỗn loạn hoàn toàn.",
                    color       = 0x2c3e50
                ),
                view=view
            )
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # ACTIVATE
    # ══════════════════════════════════════════════════════════════

    async def activate_destroy(self, game) -> tuple[bool, str]:
        if not self.alive:
            return False, "Bạn đã chết."
        if self.destroy_uses <= 0:
            return False, "Đã hết lượt phá hủy."
        if self.destroy_active:
            return False, "Đã kích hoạt đêm nay rồi."

        self.destroy_uses   -= 1
        self.destroy_active  = True
        game.night_effects["cipher_destroy_active"] = True
        return True, f"Đã kích hoạt! Còn lại **{self.destroy_uses}** lượt."

    # ══════════════════════════════════════════════════════════════
    # HOOK — Nhiễu chat người chơi
    # ══════════════════════════════════════════════════════════════

    async def _on_player_message(self, game, message: discord.Message):
        """
        Intercept tin nhắn người chơi trong kênh game.
        - Luôn dùng passive corrupt (PLAYER_MSG_CORRUPT_INTENSITY=0.50).
        - Không phụ thuộc vào destroy mode — dù bot bị chaos, chat vẫn
          chỉ bị passive để người chơi còn đọc được ~50%.
        - Bỏ qua: bot messages, DM, tin nhắn ngoài text_channel.
        - Cách hoạt động: xóa tin gốc → gửi lại bản đã nhiễu dưới tên
          webhook giả (nếu game hỗ trợ), hoặc reply thay thế.
        """
        if not self.alive:
            return
        if message.author.bot:
            return
        # Chỉ intercept trong kênh game chính
        channel_id = getattr(self._original_channel, "id", None) or getattr(game.text_channel, "_original", game.text_channel).id
        if message.channel.id != channel_id:
            return

        corrupted = _corrupt_player_msg(message.content) if message.content else message.content

        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            # Không có quyền xóa — gửi phiên bản nhiễu như reply thay thế
            if corrupted and corrupted != message.content:
                await self._original_channel.send(
                    f"**{message.author.display_name}:** {corrupted}"
                )
            return

        if corrupted:
            await self._original_channel.send(
                f"**{message.author.display_name}:** {corrupted}"
            )

    # ══════════════════════════════════════════════════════════════
    # HOOKS — Đếm kills
    # ══════════════════════════════════════════════════════════════

    async def _on_night_end(self, game):
        game.night_effects["cipher_destroy_active"] = False
        self._recount(game)

    async def _on_vote_end(self, game):
        self._recount(game)

    def _recount(self, game):
        """Đếm lại toàn bộ dead_players theo faction."""
        if not self.alive:
            return
        s = a = 0
        for pid in game.dead_players:
            role = game.roles.get(pid)
            if not role:
                continue
            t = getattr(role, "team", None) or getattr(role, "faction", "")
            if t == "Survivors":
                s += 1
            elif t == "Anomalies":
                a += 1
        self.survivors_killed = s
        self.anomalies_killed = a

    # ══════════════════════════════════════════════════════════════
    # WIN CONDITION
    # ══════════════════════════════════════════════════════════════

    def check_win_condition(self, game) -> bool:
        if not self.alive:
            return False
        return (
            self.survivors_killed >= WIN_SURVIVORS_DEAD
            and self.anomalies_killed >= WIN_ANOMALIES_DEAD
        )

    # ══════════════════════════════════════════════════════════════
    # ON DEATH — restore channel gốc, tắt passive
    # ══════════════════════════════════════════════════════════════

    def on_death(self, game):
        game.night_effects["cipher_alive"]          = False
        game.night_effects["cipher_destroy_active"] = False
        # Restore text_channel về gốc
        if self._original_channel is not None:
            game.text_channel = self._original_channel
            game.log_channel  = self._original_channel
            self._original_channel = None


# ══════════════════════════════════════════════════════════════════
# DISCORD UI
# ══════════════════════════════════════════════════════════════════

class CipherBreakerView(discord.ui.View):
    def __init__(self, game, role: "CipherBreaker"):
        super().__init__(timeout=60)
        self.game = game
        self.role = role

    @discord.ui.button(label="💣 Kích hoạt Phá Hủy", style=discord.ButtonStyle.danger, emoji="💀")
    async def btn_destroy(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.role.player.id:
            await interaction.response.send_message("Đây không phải lượt của bạn.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        success, msg = await self.role.activate_destroy(self.game)
        await interaction.response.send_message(
            embed=discord.Embed(
                title       = "💣 PHÁ HỦY HỆ THỐNG" if success else "❌ Thất bại",
                description = msg,
                color       = 0xe74c3c if success else 0x95a5a6
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
        await interaction.response.send_message(
            "💤 Bỏ qua — passive nhiễu vẫn hoạt động.", ephemeral=True
        )
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════
# ĐĂNG KÝ
# ══════════════════════════════════════════════════════════════════

def register_role(manager):
    manager.register(CipherBreaker)

