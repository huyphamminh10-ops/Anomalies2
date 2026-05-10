import os as _os, sys as _sys
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
# Đi ngược lên root nếu file này nằm trong subfolder
for _candidate in [_BASE_DIR, _os.path.dirname(_BASE_DIR)]:
    _core = _os.path.join(_candidate, "core")
    if _os.path.isdir(_core) and _core not in _sys.path:
        _sys.path.insert(0, _core)
del _os, _sys, _BASE_DIR, _candidate, _core

import disnake
import traceback
import os
import re
import asyncio
from disnake.ext import commands
from config_manager import load_guild_config, save_guild_config
from updater import greet_owner_on_setup
from cogs.settings import check_command_permission as _check_perm


# ───────────────────────────────────────────
# CONSTANTS
# ───────────────────────────────────────────
SELECT_PAGE_SIZE = 23          # Tối đa 25 options — dành 2 slot cho "Tạo cho tôi" + "→ Trang sau"
COLOR_SETUP      = 0x5865F2    # Màu embed setup (Discord Blurple)
COLOR_DONE       = 0x2ecc71    # Màu xanh hoàn tất


# ───────────────────────────────────────────
# HELPERS
# ───────────────────────────────────────────
def slugify(name: str) -> str:
    name = name.strip().replace(" ", "_")
    return re.sub(r"[^\w\-]", "", name)


def get_guild_dir(guild_id: str, guild_name: str) -> str:
    path = os.path.join("guild_data", f"{slugify(guild_name)}-{guild_id}")
    os.makedirs(path, exist_ok=True)
    return path


def build_status_embed(state: dict) -> disnake.Embed:
    """Tạo embed hiển thị trạng thái setup hiện tại."""
    lines = []

    # 1. Kênh chữ
    if state.get("text_channel_id") == "create":
        txt = "✅ Tạo kênh mới tự động"
    elif state.get("text_channel_id"):
        txt = f"✅ <#{state['text_channel_id']}>"
    else:
        txt = "⏳ Chưa chọn"
    lines.append(f"**1. Kênh chat chữ**\n{txt}")

    # 2. Kênh thoại
    if state.get("voice_channel_id") == "create":
        vc = "✅ Tạo kênh mới tự động"
    elif state.get("voice_channel_id") == "none":
        vc = "✅ Không có kênh thoại"
    elif state.get("voice_channel_id"):
        vc = f"✅ <#{state['voice_channel_id']}>"
    else:
        vc = "⏳ Chưa chọn"
    lines.append(f"**2. Kênh thoại**\n{vc}")

    # 3. Danh mục
    if state.get("use_category") is None:
        cat = "⏳ Chưa chọn"
    elif state.get("use_category") is False:
        cat = "✅ Không dùng danh mục"
    elif state.get("category_id") == "create":
        cat = "✅ Tạo danh mục mới tự động"
    elif state.get("category_id"):
        cat = f"✅ Danh mục ID: {state['category_id']}"
    else:
        cat = "⏳ Đang chọn danh mục..."
    lines.append(f"**3. Danh mục (Category)**\n{cat}")

    embed = disnake.Embed(
        title="⚙️ SETUP — ANOMALIES",
        description="\n\n".join(lines),
        color=COLOR_SETUP
    )
    embed.set_footer(text="Chọn lần lượt từng mục bên dưới để hoàn tất cài đặt.")
    return embed


# ───────────────────────────────────────────────────────────────────────────────
# VIEW CHÍNH
# ───────────────────────────────────────────────────────────────────────────────

class SetupView(disnake.ui.View):
    def __init__(self, guild: disnake.Guild, interaction: disnake.ApplicationCommandInteraction, config: dict):
        super().__init__(timeout=300)
        self.guild       = guild
        self.interaction = interaction
        self.config      = config
        self.state: dict = {}

        self.text_channels  = [c for c in guild.channels if isinstance(c, disnake.TextChannel)]
        self.voice_channels = [c for c in guild.channels if isinstance(c, disnake.VoiceChannel)]
        self.categories     = list(guild.categories)

        self.text_page  = 0
        self.voice_page = 0
        self.cat_page   = 0

        self._rebuild()

    def _rebuild(self):
        self.clear_items()

        # Row 0: Select kênh chữ (luôn hiện)
        self.add_item(TextChannelSelect(self, self.text_channels, self.text_page))

        # Row 1: Select kênh thoại (sau khi chọn kênh chữ)
        if "text_channel_id" in self.state:
            self.add_item(VoiceChannelSelect(self, self.voice_channels, self.voice_page))

        # Row 2: Có dùng category không (sau khi chọn kênh thoại)
        if "voice_channel_id" in self.state:
            self.add_item(UseCategorySelect(self))

        # Row 3: Chọn category (nếu chọn có)
        if self.state.get("use_category") is True and "category_id" not in self.state:
            self.add_item(CategorySelect(self, self.categories, self.cat_page))

        # Row 4: Nút xác nhận (khi đủ điều kiện)
        if self._is_complete():
            self.add_item(ConfirmButton(self))

    def _is_complete(self) -> bool:
        if "text_channel_id" not in self.state:
            return False
        if "voice_channel_id" not in self.state:
            return False
        if self.state.get("use_category") is None:
            return False
        if self.state.get("use_category") is True and "category_id" not in self.state:
            return False
        return True

    async def refresh(self, interaction: disnake.ApplicationCommandInteraction):
        self._rebuild()
        try:
            await interaction.response.edit_message(
                embed=build_status_embed(self.state),
                view=self
            )
        except disnake.InteractionResponded:
            await interaction.message.edit(
                embed=build_status_embed(self.state),
                view=self
            )

    async def on_timeout(self):
        try:
            for item in self.children:
                item.disabled = True
            await self.interaction.edit_original_response(
                embed=disnake.Embed(
                    title="⏰ Hết thời gian",
                    description="Setup đã hết thời gian (5 phút). Dùng `/setup` để thử lại.",
                    color=0xe74c3c
                ),
                view=self
            )
        except Exception:
            pass


# ───────────────────────────────────────────────────────────────────────────────
# SELECT: KÊNH CHỮ
# ───────────────────────────────────────────────────────────────────────────────

class TextChannelSelect(disnake.ui.Select):
    def __init__(self, view: SetupView, channels: list, page: int):
        self._sv   = view
        self._page = page
        total      = max(1, -(-len(channels) // SELECT_PAGE_SIZE))

        super().__init__(
            placeholder=f"1. Kênh chat chữ sẽ ở đâu? (trang {page + 1}/{total})",
            options=self._opts(channels, page, total),
            min_values=1, max_values=1, row=0
        )

    def _opts(self, channels, page, total):
        start   = page * SELECT_PAGE_SIZE
        chunk   = channels[start: start + SELECT_PAGE_SIZE]
        opts    = [
            disnake.SelectOption(label=f"# {c.name}"[:100], value=str(c.id), emoji="💬")
            for c in chunk
        ]
        opts.append(disnake.SelectOption(label="✨ Tạo kênh mới cho tôi", value="create", emoji="🔧"))
        if total > 1:
            nxt = (page + 1) % total
            opts.append(disnake.SelectOption(label=f"→ Trang {nxt + 1}/{total}", value=f"__page_{nxt}__", emoji="📄"))
        return opts

    async def callback(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != self._sv.interaction.user.id:
            return await interaction.response.send_message("Không phải lượt của bạn.", ephemeral=True)
        val = self.values[0]
        if val.startswith("__page_"):
            self._sv.text_page = int(val.split("_")[-1])
        else:
            self._sv.state["text_channel_id"] = val
        await self._sv.refresh(interaction)


# ───────────────────────────────────────────────────────────────────────────────
# SELECT: KÊNH THOẠI
# ───────────────────────────────────────────────────────────────────────────────

class VoiceChannelSelect(disnake.ui.Select):
    def __init__(self, view: SetupView, channels: list, page: int):
        self._sv   = view
        self._page = page
        total      = max(1, -(-len(channels) // SELECT_PAGE_SIZE))

        super().__init__(
            placeholder=f"2. Kênh thoại sẽ ở đâu? (trang {page + 1}/{total})",
            options=self._opts(channels, page, total),
            min_values=1, max_values=1, row=1
        )

    def _opts(self, channels, page, total):
        start = page * SELECT_PAGE_SIZE
        chunk = channels[start: start + SELECT_PAGE_SIZE]
        opts  = [
            disnake.SelectOption(label=f"🔊 {c.name}"[:100], value=str(c.id), emoji="🔊")
            for c in chunk
        ]
        opts.append(disnake.SelectOption(label="✨ Tạo kênh mới cho tôi", value="create", emoji="🔧"))
        opts.append(disnake.SelectOption(label="🚫 Không có kênh thoại",  value="none",   emoji="🚫"))
        if total > 1:
            nxt = (page + 1) % total
            opts.append(disnake.SelectOption(label=f"→ Trang {nxt + 1}/{total}", value=f"__page_{nxt}__", emoji="📄"))
        return opts

    async def callback(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != self._sv.interaction.user.id:
            return await interaction.response.send_message("Không phải lượt của bạn.", ephemeral=True)
        val = self.values[0]
        if val.startswith("__page_"):
            self._sv.voice_page = int(val.split("_")[-1])
        else:
            self._sv.state["voice_channel_id"] = val
        await self._sv.refresh(interaction)


# ───────────────────────────────────────────────────────────────────────────────
# SELECT: CÓ DÙNG CATEGORY KHÔNG
# ───────────────────────────────────────────────────────────────────────────────

class UseCategorySelect(disnake.ui.Select):
    def __init__(self, view: SetupView):
        self._sv = view
        super().__init__(
            placeholder="3. Có đặt game trong danh mục (Category) không?",
            options=[
                disnake.SelectOption(label="✅ Có, tôi muốn chọn danh mục", value="yes", emoji="📂"),
                disnake.SelectOption(label="❌ Không, bỏ qua danh mục",      value="no",  emoji="🚫"),
            ],
            min_values=1, max_values=1, row=2
        )

    async def callback(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != self._sv.interaction.user.id:
            return await interaction.response.send_message("Không phải lượt của bạn.", ephemeral=True)
        if self.values[0] == "yes":
            self._sv.state["use_category"] = True
            self._sv.state.pop("category_id", None)
        else:
            self._sv.state["use_category"] = False
            self._sv.state.pop("category_id", None)
        await self._sv.refresh(interaction)


# ───────────────────────────────────────────────────────────────────────────────
# SELECT: CHỌN CATEGORY
# ───────────────────────────────────────────────────────────────────────────────

class CategorySelect(disnake.ui.Select):
    def __init__(self, view: SetupView, categories: list, page: int):
        self._sv   = view
        self._page = page
        total      = max(1, -(-len(categories) // SELECT_PAGE_SIZE))

        super().__init__(
            placeholder=f"Bạn muốn đặt game vào danh mục nào? (trang {page + 1}/{total})",
            options=self._opts(categories, page, total),
            min_values=1, max_values=1, row=3
        )

    def _opts(self, categories, page, total):
        start = page * SELECT_PAGE_SIZE
        chunk = categories[start: start + SELECT_PAGE_SIZE]
        opts  = [
            disnake.SelectOption(label=f"📂 {c.name}"[:100], value=str(c.id))
            for c in chunk
        ]
        opts.append(disnake.SelectOption(label="✨ Tạo danh mục mới cho tôi", value="create", emoji="🔧"))
        if total > 1:
            nxt = (page + 1) % total
            opts.append(disnake.SelectOption(label=f"→ Trang {nxt + 1}/{total}", value=f"__page_{nxt}__", emoji="📄"))
        return opts

    async def callback(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != self._sv.interaction.user.id:
            return await interaction.response.send_message("Không phải lượt của bạn.", ephemeral=True)
        val = self.values[0]
        if val.startswith("__page_"):
            self._sv.cat_page = int(val.split("_")[-1])
        else:
            self._sv.state["category_id"] = val
        await self._sv.refresh(interaction)


# ───────────────────────────────────────────────────────────────────────────────
# NÚT XÁC NHẬN
# ───────────────────────────────────────────────────────────────────────────────

class ConfirmButton(disnake.ui.Button):
    def __init__(self, sv: SetupView):
        super().__init__(label="✅ Xác nhận & Setup", style=disnake.ButtonStyle.success, emoji="🚀", row=4)
        self._sv = sv

    async def callback(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != self._sv.interaction.user.id:
            return await interaction.response.send_message("Không phải lượt của bạn.", ephemeral=True)

        for item in self._sv.children:
            item.disabled = True

        await interaction.response.edit_message(
            embed=disnake.Embed(
                title="⚙️ Đang cài đặt...",
                description="Vui lòng chờ trong giây lát...",
                color=0xf39c12
            ),
            view=self._sv
        )

        await do_setup(interaction, self._sv.guild, self._sv.state, self._sv.config)


# ───────────────────────────────────────────────────────────────────────────────
# HÀM SETUP THỰC THI
# ───────────────────────────────────────────────────────────────────────────────

async def do_setup(interaction: disnake.ApplicationCommandInteraction, guild: disnake.Guild, state: dict, config: dict):
    guild_id = str(guild.id)

    try:
        # ── 1. Category ──────────────────────────────────────────────
        category  = None
        cat_label = "🚫 Không dùng danh mục"
        if state.get("use_category"):
            cat_val = state.get("category_id", "create")
            if cat_val == "create":
                category  = await guild.create_category("🏙️ THỊ TRẤN")
                cat_label = f"✨ Tạo mới: `{category.name}`"
            else:
                category  = guild.get_channel(int(cat_val))
                cat_label = f"📂 `{category.name}`" if category else "❓ Không tìm thấy"

        # ── 2. Text channel ──────────────────────────────────────────
        txt_val = state.get("text_channel_id", "create")
        if txt_val == "create":
            text_channel = await guild.create_text_channel("🌃-thị-trấn", category=category)
            txt_label    = f"✨ Tạo mới: `{text_channel.name}`"
        else:
            text_channel = guild.get_channel(int(txt_val))
            txt_label    = f"💬 `{text_channel.name}`" if text_channel else "❓ Không tìm thấy"

        # ── 3. Voice channel ─────────────────────────────────────────
        vc_val = state.get("voice_channel_id", "create")
        if vc_val == "none":
            voice_channel = None
            vc_label      = "🚫 Không có kênh thoại"
        elif vc_val == "create":
            voice_channel = await guild.create_voice_channel("🗣️-nói-chuyện", category=category)
            vc_label      = f"✨ Tạo mới: `{voice_channel.name}`"
        else:
            voice_channel = guild.get_channel(int(vc_val))
            vc_label      = f"🔊 `{voice_channel.name}`" if voice_channel else "❓ Không tìm thấy"

        # ── 4. Roles ─────────────────────────────────────────────────
        alive_role = await guild.create_role(
            name="Alive-❤️‍🩹", color=disnake.Color.green(),
            permissions=disnake.Permissions(
                view_channel=True, send_messages=True, send_messages_in_threads=True,
                read_message_history=True, add_reactions=True, use_external_emojis=True,
                use_application_commands=True, connect=True, speak=True,
                use_voice_activation=True, change_nickname=True,
            ),
            reason="Anomalies — Alive role"
        )
        dead_role = await guild.create_role(
            name="Dead-☠️", color=disnake.Color.dark_grey(),
            reason="Anomalies — Dead role"
        )

        # ── 5. Permissions ───────────────────────────────────────────
        server_roles = [
            r for r in guild.roles
            if not r.is_default() and r not in (alive_role, dead_role) and not r.managed
        ]
        if text_channel:
            await text_channel.set_permissions(guild.default_role,
                read_messages=True, send_messages=False, add_reactions=False)
            for r in server_roles:
                try:
                    await text_channel.set_permissions(r,
                        read_messages=True, send_messages=True, add_reactions=True)
                except Exception:
                    pass

        if voice_channel:
            await voice_channel.set_permissions(guild.default_role,
                connect=True, speak=False, send_messages=False,
                stream=False, use_voice_activation=True)
            for r in server_roles:
                try:
                    await voice_channel.set_permissions(r,
                        connect=True, speak=True, send_messages=False,
                        use_voice_activation=True)
                except Exception:
                    pass

        # ── 6. Lưu config ────────────────────────────────────────────
        config["category_id"]      = category.id      if category      else None
        config["text_channel_id"]  = text_channel.id  if text_channel  else None
        config["voice_channel_id"] = voice_channel.id if voice_channel else None
        config["alive_role_id"]    = alive_role.id
        config["dead_role_id"]     = dead_role.id
        config.setdefault("max_players",           65)
        config.setdefault("min_players_to_start",  5)
        config.setdefault("countdown_minutes",     3)
        save_guild_config(guild_id, config)

        # ── 7. Folder + init_guild ───────────────────────────────────
        get_guild_dir(guild_id, guild.name)

        # FIX: gọi init_guild() để gửi embed Lobby ngay sau khi setup xong.
        # Cách cũ (sys.modules["__main__"]) bị HỎNG khi bot chạy qua Streamlit
        # vì __main__ lúc đó là module của Streamlit, không phải app.py
        # → init_guild bị bỏ qua trong im lặng → không có embed lobby.
        # Fix: ưu tiên `from app import init_guild`, fallback __main__ cho an toàn.
        _init_guild = None
        try:
            from app import init_guild as _init_guild  # type: ignore
        except Exception as _imp_err:
            print(f"[SETUP] Không import được app.init_guild: {_imp_err}")
            try:
                import sys
                _bot_module = sys.modules.get("__main__")
                _init_guild = getattr(_bot_module, "init_guild", None)
            except Exception:
                _init_guild = None

        if _init_guild and text_channel:
            try:
                await _init_guild(guild_id, text_channel)
                print(f"[SETUP] ✅ Đã gọi init_guild({guild_id}) — embed lobby sẽ được gửi.")
            except Exception as _ig_err:
                print(f"[SETUP] ❌ init_guild lỗi: {_ig_err}")
                traceback.print_exc()
        else:
            print(
                f"[SETUP] ⚠️ Không tìm thấy init_guild — "
                f"text_channel={bool(text_channel)}, init_guild={bool(_init_guild)}"
            )

        # ── 8. Embed kết quả ─────────────────────────────────────────
        embed = disnake.Embed(title="✅ SETUP HOÀN TẤT!", color=COLOR_DONE)
        embed.add_field(name="📂 Danh mục",   value=cat_label, inline=False)
        embed.add_field(name="💬 Kênh chữ",   value=txt_label, inline=False)
        embed.add_field(name="🔊 Kênh thoại", value=vc_label,  inline=False)
        embed.add_field(name="❤️‍🩹 Alive Role", value=f"`{alive_role.name}`", inline=True)
        embed.add_field(name="☠️ Dead Role",  value=f"`{dead_role.name}`",  inline=True)
        if server_roles:
            embed.set_footer(text=f"Đã cấp quyền cho {len(server_roles)} server role.")

        await interaction.edit_original_response(embed=embed, view=None)

    except Exception:
        tb = traceback.format_exc()[-1800:]
        print(f"[SETUP] ❌ LỖI:\n{tb}")
        try:
            await interaction.edit_original_response(
                embed=disnake.Embed(
                    title="❌ Setup thất bại",
                    description=f"```{tb}```",
                    color=0xe74c3c
                ),
                view=None
            )
        except Exception:
            pass


# ───────────────────────────────────────────────────────────────────────────────
# COG
# ───────────────────────────────────────────────────────────────────────────────

class Setup(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def lay_category(self, guild_id: str):
        config = load_guild_config(guild_id)
        cat_id = config.get("category_id")
        if not cat_id:
            return None
        ch = self.bot.get_channel(cat_id)
        return ch if isinstance(ch, disnake.CategoryChannel) else None

    def lay_ten_category(self, guild_id: str) -> str:
        cat = self.lay_category(guild_id)
        return cat.name if cat else "Chưa đặt"

    @commands.slash_command(name="setup", description="Cài đặt hệ thống Anomalies cho server")
    
    async def setup_command(self, interaction: disnake.ApplicationCommandInteraction):
        guild    = interaction.guild
        guild_id = str(guild.id)
        config   = load_guild_config(guild_id)

        if not _check_perm(interaction, config):
            return await interaction.response.send_message(
                "❌ Bạn không có quyền dùng lệnh này.", ephemeral=True
            )

        already = ""
        if config.get("text_channel_id"):
            already = "\n\n⚠️ **Server đã được setup trước đó.** Tiếp tục sẽ tạo thêm kênh/role mới."

        view  = SetupView(guild, interaction, config)
        embed = build_status_embed(view.state)
        if already:
            embed.description = (embed.description or "") + already

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        await greet_owner_on_setup(self.bot)


def setup(bot: commands.Bot):
    bot.add_cog(Setup(bot))
