import os as _os, sys as _sys
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
# Đi ngược lên root nếu file này nằm trong subfolder
for _candidate in [_BASE_DIR, _os.path.dirname(_BASE_DIR)]:
    _core = _os.path.join(_candidate, "core")
    if _os.path.isdir(_core) and _core not in _sys.path:
        _sys.path.insert(0, _core)
del _os, _sys, _BASE_DIR, _candidate, _core

import disnake
from disnake.ext import commands
from disnake.ui import View, Select, Modal, TextInput
import asyncio
import traceback
import sys
from config_manager import load_guild_config, save_guild_config


# ══════════════════════════════════════════════════════════════════
# PERMISSION SYSTEM — 4 CẤP ĐỘ (áp dụng cho /setting, /clear, /setup)
# ══════════════════════════════════════════════════════════════════

def _invalidate(guild_id: str):
    """Xóa config cache sau khi save."""
    try:
        bot_mod = sys.modules.get("bot") or sys.modules.get("__main__")
        if bot_mod and hasattr(bot_mod, "invalidate_config_cache"):
            bot_mod.invalidate_config_cache(str(guild_id))
    except Exception:
        pass


def check_command_permission(interaction: disnake.ApplicationCommandInteraction, config: dict) -> bool:
    """
    Kiểm tra quyền dùng /setting, /clear, /setup theo 4 cấp:
      1. owner       — Chỉ chủ server
      2. admin       — Chủ server + roles có quyền Quản lý máy chủ (manage_guild)
      3. role        — Cấp 2 + tối đa 12 role tùy chọn
      4. player      — Cấp 3 + tối đa 6 người tùy chọn
    Chủ server LUÔN có quyền bất kể mode nào.
    """
    mode  = config.get("setting_permission_mode", "owner")
    user  = interaction.user
    guild = interaction.guild

    if user.id == guild.owner_id:
        return True

    if mode == "owner":
        return False

    def _is_admin():
        for role in user.roles:
            if role.permissions.administrator or role.permissions.manage_guild:
                return True
        return False

    if mode == "admin":
        return _is_admin()

    if mode == "role":
        if _is_admin():
            return True
        allowed_roles = config.get("setting_allowed_roles", [])
        user_role_ids = {r.id for r in user.roles}
        return any(rid in user_role_ids for rid in allowed_roles)

    if mode == "player":
        if _is_admin():
            return True
        allowed_roles = config.get("setting_allowed_roles", [])
        user_role_ids = {r.id for r in user.roles}
        if any(rid in user_role_ids for rid in allowed_roles):
            return True
        allowed_users = config.get("setting_allowed_users", [])
        return user.id in allowed_users

    return False


_check = check_command_permission


# ══════════════════════════════════════════════════════════════════
# DANH SÁCH SETTINGS
# ══════════════════════════════════════════════════════════════════

def _get_settings_list(config: dict, bot) -> list[dict]:
    max_p   = config.get("max_players", 65)
    min_p   = config.get("min_players_to_start", 5)
    cdmin   = config.get("countdown_minutes", 3)
    day_t   = config.get("day_time", 90)
    vote_t  = config.get("vote_time", 30)
    skip_d  = config.get("skip_discussion_delay", 30)
    skip_on = config.get("skip_discussion", True)
    mute_on = config.get("mute_dead", True)
    no_remove_roles_on = config.get("no_remove_roles", False)

    vote_label = "Thanh Hóa" if vote_t == 36 else f"{vote_t}s"

    cat_name = vc_name = tc_name = "Chưa đặt"
    if bot:
        if cid := config.get("category_id"):
            ch = bot.get_channel(cid)
            if ch: cat_name = ch.name
        if cid := config.get("text_channel_id"):
            ch = bot.get_channel(cid)
            if ch: tc_name = ch.name
        if cid := config.get("voice_channel_id"):
            ch = bot.get_channel(cid)
            if ch: vc_name = ch.name

    mode = config.get("setting_permission_mode", "owner")
    mode_labels = {
        "owner":  "👑 Chỉ Chủ Server",
        "admin":  "🛡️ Quản trị viên",
        "role":   "🎭 Vai trò đặc biệt",
        "player": "⭐ Người chơi đặc quyền",
    }
    perm_val = mode_labels.get(mode, "👑 Chỉ Chủ Server")
    if mode in ("role", "player"):
        roles = config.get("setting_allowed_roles", [])
        users = config.get("setting_allowed_users", [])
        if roles:
            perm_val += f"\n　Roles: {len(roles)}/12 đã chọn"
        if mode == "player" and users:
            perm_val += f"\n　Người dùng: {len(users)}/6 đã chọn"

    return [
        {
            "key":   "max_players",
            "label": "Số người chơi tối đa",
            "emoji": "👥",
            "value": f"`{max_p}` người (5–65)",
            "desc":  "Giới hạn tối đa người có thể tham gia phòng chờ.",
            "type":  "number",
            "modal": "MaxPlayersModal",
        },
        {
            "key":   "min_players",
            "label": "Số người tối thiểu để bắt đầu",
            "emoji": "📊",
            "value": f"`{min_p}` người (5–{max_p - 1})",
            "desc":  "Cần đủ số người này mới bắt đầu đếm ngược.",
            "type":  "number",
            "modal": "MinPlayersModal",
        },
        {
            "key":   "countdown",
            "label": "Thời gian đếm ngược",
            "emoji": "⏱️",
            "value": f"`{cdmin}` phút (1–3)",
            "desc":  "Thời gian đếm ngược sau khi đủ người chơi.",
            "type":  "time",
            "modal": "CountdownModal",
        },
        {
            "key":   "day_time",
            "label": "Thời gian thảo luận",
            "emoji": "☀️",
            "value": f"`{day_t}s` (30–120s)",
            "desc":  "Thời gian mỗi ngày để thảo luận trước khi bỏ phiếu.",
            "type":  "time",
            "modal": "DayTimeModal",
        },
        {
            "key":   "vote_time",
            "label": "Thời gian bỏ phiếu",
            "emoji": "🗳️",
            "value": f"`{vote_label}` (15–45s)",
            "desc":  "Thời gian mỗi vòng bỏ phiếu trục xuất.",
            "type":  "time",
            "modal": "VoteTimeModal",
        },
        {
            "key":   "skip_delay",
            "label": "Delay DM Skip thảo luận",
            "emoji": "📨",
            "value": f"`{skip_d}s`",
            "desc":  "Sau bao nhiêu giây thì gửi DM nhắc nhở vote skip.",
            "type":  "time",
            "modal": "SkipDelayModal",
        },
        {
            "key":         "toggle_skip",
            "label":       "Skip Thảo Luận",
            "emoji":       "⏩",
            "value":       "✅ Bật" if skip_on else "❌ Tắt",
            "desc":        "Cho phép người chơi vote rút ngắn thời gian thảo luận.",
            "type":        "toggle",
            "toggle_key":  "skip_discussion",
            "toggle_def":  True,
        },
        {
            "key":         "toggle_mute",
            "label":       "Mute Khi Chết",
            "emoji":       "🔇",
            "value":       "❌ Tắt (bị khóa bởi Không gỡ role)" if no_remove_roles_on else ("✅ Bật" if mute_on else "❌ Tắt"),
            "desc":        "Tự động tắt mic người chơi khi họ chết trong trận. Không thể bật khi Không gỡ role đang bật.",
            "type":        "toggle",
            "toggle_key":  "mute_dead",
            "toggle_def":  True,
        },
        {
            "key":   "channels",
            "label": "Tên kênh",
            "emoji": "🏷️",
            "value": f"📂 `{cat_name}`\n💬 `{tc_name}`\n🔊 `{vc_name}`",
            "desc":  "Đổi tên danh mục, kênh văn bản hoặc kênh thoại của bot.",
            "type":  "other",
        },
        {
            "key":   "permission",
            "label": "Quyền sử dụng lệnh",
            "emoji": "🔐",
            "value": perm_val,
            "desc":  "Cấu hình ai được dùng /setting, /clear và /setup.",
            "type":  "other",
        },
        {
            "key":         "toggle_no_remove_roles",
            "label":       "Không gỡ role",
            "emoji":       "🛡️",
            "value":       "✅ Bật" if no_remove_roles_on else "❌ Tắt",
            "desc":        "Khi khởi tạo trận đấu, bot sẽ giữ nguyên toàn bộ role server sẵn có của người chơi như Member/Admin/Owner/role màu. Bot cũng không cấp hoặc gỡ Alive/Dead role. An toàn tuyệt đối cho server nhiều role; Mute Khi Chết sẽ bị tắt khi bật mục này.",
            "type":        "toggle",
            "toggle_key":  "no_remove_roles",
            "toggle_def":  False,
        },
    ]


def _build_setting_embed(setting: dict, idx: int, total: int) -> disnake.Embed:
    s_type = setting["type"]
    if s_type == "time":
        color = 0x3498db
    elif s_type == "toggle":
        color = 0x2ecc71
    elif s_type == "other":
        color = 0x9b59b6
    else:
        color = 0x595858

    embed = disnake.Embed(title="⚙️ CÀI ĐẶT ANOMALIES", color=color)
    embed.add_field(
        name=f"{setting['emoji']} {setting['label']}",
        value=(
            f"> **Hiện tại:** {setting['value']}\n"
            f"> \n"
            f"> 📋 {setting['desc']}"
        ),
        inline=False,
    )
    type_icon = {"time": "⏱️ Đồng hồ", "toggle": "🔄 Bật / Tắt", "other": "⚙️ Tùy chọn", "number": "🔢 Số Lượng"}
    embed.set_footer(
        text=f"Thông số {idx + 1}/{total}  •  Loại: {type_icon.get(s_type, '')}  •  /setting"
    )
    return embed


# ══════════════════════════════════════════════════════════════════
# MAIN SETTINGS VIEW
# ══════════════════════════════════════════════════════════════════

class SettingsView(View):
    def __init__(self, bot: commands.Bot, guild_id: str, lock: asyncio.Lock, idx: int = 0):
        super().__init__(timeout=300)
        self.bot      = bot
        self.guild_id = guild_id
        self.lock     = lock
        self.idx      = idx
        self.message: disnake.Message | None = None
        self._refresh()

    def _settings(self) -> list[dict]:
        config = load_guild_config(self.guild_id)
        return _get_settings_list(config, self.bot)

    def _refresh(self):
        self.clear_items()
        settings = self._settings()
        total    = len(settings)
        setting  = settings[self.idx]
        s_type   = setting["type"]

        if s_type == "time":
            btn_action = disnake.ui.Button(
                label="⏱️ Chọn Thời Gian",
                style=disnake.ButtonStyle.primary,
                row=0,
            )
            btn_action.callback = self._action_callback
        elif s_type == "toggle":
            btn_action = disnake.ui.Button(
                label="🔄 Bật / Tắt",
                style=disnake.ButtonStyle.success,
                row=0,
            )
            btn_action.callback = self._action_callback
        elif s_type == "other":
            btn_action = disnake.ui.Button(
                label="⚙️ Cài đặt",
                style=disnake.ButtonStyle.secondary,
                row=0,
            )
            btn_action.callback = self._action_callback
        elif s_type == "number":
            btn_action = disnake.ui.Button(
                label="▶️ Chọn Số",
                style=disnake.ButtonStyle.secondary,
                row=0,
            )
            btn_action.callback = self._action_callback

        self.add_item(btn_action)

        btn_prev = disnake.ui.Button(
            label="◀ Trang trước",
            style=disnake.ButtonStyle.secondary,
            disabled=(self.idx == 0),
            row=1,
        )
        btn_prev.callback = self._prev

        btn_next = disnake.ui.Button(
            label="Trang sau ▶",
            style=disnake.ButtonStyle.secondary,
            disabled=(self.idx >= total - 1),
            row=1,
        )
        btn_next.callback = self._next

        self.add_item(btn_prev)
        self.add_item(btn_next)

    def _build_embed(self) -> disnake.Embed:
        settings = self._settings()
        return _build_setting_embed(settings[self.idx], self.idx, len(settings))

    async def _prev(self, interaction: disnake.ApplicationCommandInteraction):
        self.idx -= 1
        self._refresh()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _next(self, interaction: disnake.ApplicationCommandInteraction):
        self.idx += 1
        self._refresh()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    async def _action_callback(self, interaction: disnake.ApplicationCommandInteraction):
        settings = self._settings()
        setting  = settings[self.idx]
        s_type   = setting["type"]
        key      = setting["key"]

        if s_type == "toggle":
            async with self.lock:
                config  = load_guild_config(self.guild_id)
                tk      = setting["toggle_key"]
                current = config.get(tk, setting["toggle_def"])
                new_value = not current
                if tk == "mute_dead" and new_value and config.get("no_remove_roles", False):
                    await interaction.response.send_message(
                        embed=disnake.Embed(
                            title="⚠️ Không thể bật",
                            description="**Mute Khi Chết** không thể bật khi **Không gỡ role** đang bật.\nHãy tắt **Không gỡ role** trước nếu muốn dùng lại Mute Khi Chết.",
                            color=disnake.Color.orange(),
                        ),
                        ephemeral=True,
                    )
                    return
                config[tk] = new_value
                if tk == "no_remove_roles" and new_value:
                    config["mute_dead"] = False
                save_guild_config(self.guild_id, config)
                _invalidate(self.guild_id)
            new_label = "✅ Bật" if not current else "❌ Tắt"
            extra_desc = ""
            if setting["toggle_key"] == "no_remove_roles" and not current:
                extra_desc = "\n🔇 **Mute Khi Chết** đã tự động tắt."
            self._refresh()
            await interaction.response.edit_message(embed=self._build_embed(), view=self)
            await interaction.followup.send(
                embed=disnake.Embed(
                    title="✅ Đã cập nhật",
                    description=f"**{setting['label']}:** {new_label}{extra_desc}",
                    color=disnake.Color.green(),
                ),
                ephemeral=True,
            )
            return

        if s_type == "time" or s_type == "number":
            modal_map = {
                "max_players": MaxPlayersModal,
                "min_players": MinPlayersModal,
                "countdown":   CountdownModal,
                "day_time":    DayTimeModal,
                "vote_time":   VoteTimeModal,
                "skip_delay":  SkipDelayModal,
            }
            cls = modal_map.get(key)
            if cls:
                modal = cls(self.bot, self.guild_id, self.lock, parent_view=self)
                await interaction.response.send_modal(modal)
            return

        if key == "channels":
            config = load_guild_config(self.guild_id)
            embed  = _build_channels_embed(self.bot, config)
            view   = ChannelsView(self.bot, self.guild_id, self.lock)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.message = await interaction.original_response()
            return

        if key == "permission":
            if interaction.user.id != interaction.guild.owner_id:
                await interaction.response.send_message(
                    "❌ Chỉ Chủ Server mới có thể thay đổi quyền sử dụng lệnh.",
                    ephemeral=True,
                )
                return
            config = load_guild_config(self.guild_id)
            embed  = _build_permission_embed(config)
            view   = PermissionView(self.bot, self.guild_id, self.lock)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.message = await interaction.original_response()
            return


# ══════════════════════════════════════════════════════════════════
# PERMISSION VIEW — 4 cấp
# ══════════════════════════════════════════════════════════════════

_MODE_LABELS = {
    "owner":  "👑 Chỉ Chủ Server",
    "admin":  "🛡️ Quản trị viên",
    "role":   "🎭 Vai trò đặc biệt",
    "player": "⭐ Người chơi đặc quyền",
}

_MODE_DESCS = {
    "owner":  "Chỉ chủ server được dùng `/setting`, `/clear`, `/setup`.",
    "admin":  "Chủ server + thành viên có role mang quyền **Quản lý máy chủ**.",
    "role":   "Cấp Admin + tối đa **12 role** tùy chọn.",
    "player": "Cấp Vai trò + tối đa **6 người dùng** tùy chọn.",
}


def _build_permission_embed(config: dict) -> disnake.Embed:
    mode    = config.get("setting_permission_mode", "owner")
    current = _MODE_LABELS.get(mode, "👑 Chỉ Chủ Server")
    desc_parts = [f"**Hiện tại:** {current}", f"> {_MODE_DESCS.get(mode, '')}"]

    if mode in ("role", "player"):
        roles = config.get("setting_allowed_roles", [])
        desc_parts.append(f"\n**Roles đã chọn ({len(roles)}/12):**")
        if roles:
            desc_parts.append("  " + ", ".join(f"<@&{r}>" for r in roles))
        else:
            desc_parts.append("  *(Chưa có role nào)*")

    if mode == "player":
        users = config.get("setting_allowed_users", [])
        desc_parts.append(f"\n**Người dùng đã chọn ({len(users)}/6):**")
        if users:
            desc_parts.append("  " + ", ".join(f"<@{u}>" for u in users))
        else:
            desc_parts.append("  *(Chưa có ai)*")

    embed = disnake.Embed(
        title="🔐 QUYỀN SỬ DỤNG LỆNH",
        description="\n".join(desc_parts),
        color=disnake.Color.gold(),
    )
    embed.set_footer(text="Áp dụng cho /setting • /clear • /setup  |  Chỉ Chủ Server mới thay đổi được.")
    return embed


class PermissionView(View):
    def __init__(self, bot: commands.Bot, guild_id: str, lock: asyncio.Lock):
        super().__init__(timeout=300)
        self.bot      = bot
        self.guild_id = guild_id
        self.lock     = lock
        self.message: disnake.Message | None = None
        self._build()

    def _build(self):
        self.clear_items()
        config = load_guild_config(self.guild_id)
        mode   = config.get("setting_permission_mode", "owner")

        select = Select(
            placeholder="Chọn cấp quyền...",
            min_values=1, max_values=1,
            options=[
                disnake.SelectOption(
                    label="1. Chủ server",
                    value="owner",
                    description="Chỉ chủ server",
                    emoji="👑",
                    default=(mode == "owner"),
                ),
                disnake.SelectOption(
                    label="2. Quản trị viên",
                    value="admin",
                    description="Chủ server + roles Quản lý máy chủ",
                    emoji="🛡️",
                    default=(mode == "admin"),
                ),
                disnake.SelectOption(
                    label="3. Vai trò đặc biệt",
                    value="role",
                    description="Cấp Admin + 12 roles tùy chọn",
                    emoji="🎭",
                    default=(mode == "role"),
                ),
                disnake.SelectOption(
                    label="4. Người chơi đặc quyền",
                    value="player",
                    description="Cấp Vai trò + 6 người dùng tùy chọn",
                    emoji="⭐",
                    default=(mode == "player"),
                ),
            ],
            row=0,
        )
        select.callback = self._mode_select
        self.add_item(select)

        if mode in ("role", "player"):
            btn_roles = disnake.ui.Button(
                label="🎭 Quản lý Roles (12)",
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
            btn_roles.callback = self._manage_roles
            self.add_item(btn_roles)

        if mode == "player":
            btn_users = disnake.ui.Button(
                label="👤 Quản lý Người dùng (6)",
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
            btn_users.callback = self._manage_users
            self.add_item(btn_users)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    async def _mode_select(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ Chỉ Chủ Server.", ephemeral=True)
            return
        chosen = interaction.data["values"][0]
        async with self.lock:
            config = load_guild_config(self.guild_id)
            config["setting_permission_mode"] = chosen
            if chosen in ("owner", "admin"):
                config.pop("setting_allowed_roles", None)
                config.pop("setting_allowed_users", None)
            save_guild_config(self.guild_id, config)
            _invalidate(self.guild_id)
        self._build()
        config = load_guild_config(self.guild_id)
        await interaction.response.edit_message(embed=_build_permission_embed(config), view=self)

    async def _manage_roles(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ Chỉ Chủ Server.", ephemeral=True)
            return
        config = load_guild_config(self.guild_id)
        roles  = [
            r for r in interaction.guild.roles
            if not r.is_default() and not r.managed
        ][:25]
        if not roles:
            await interaction.response.send_message("❌ Server không có role nào.", ephemeral=True)
            return
        current_ids = config.get("setting_allowed_roles", [])
        view = _RoleManageView(self.bot, self.guild_id, self.lock, roles, current_ids, parent=self)
        embed = disnake.Embed(
            title="🎭 QUẢN LÝ ROLES (tối đa 12)",
            description="Chọn các role được phép dùng lệnh.\n*Roles đang chọn sẽ được đánh dấu.*",
            color=disnake.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    async def _manage_users(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ Chỉ Chủ Server.", ephemeral=True)
            return
        config      = load_guild_config(self.guild_id)
        current_ids = config.get("setting_allowed_users", [])
        view  = _UserManageView(self.bot, self.guild_id, self.lock, current_ids, parent=self)
        embed = disnake.Embed(
            title="👤 QUẢN LÝ NGƯỜI DÙNG ĐẶC QUYỀN (tối đa 6)",
            description=(
                "Dùng nút bên dưới để thêm/xóa người dùng.\n"
                + ("**Đã chọn:** " + ", ".join(f"<@{u}>" for u in current_ids) if current_ids else "*Chưa có ai*")
            ),
            color=disnake.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


class _RoleManageView(View):
    def __init__(self, bot, guild_id, lock, roles, current_ids, parent: PermissionView):
        super().__init__(timeout=300)
        self.bot        = bot
        self.guild_id   = guild_id
        self.lock       = lock
        self.parent     = parent
        self.message: disnake.Message | None = None

        options = [
            disnake.SelectOption(
                label=r.name[:100],
                value=str(r.id),
                default=(r.id in current_ids),
            )
            for r in roles
        ]
        sel = Select(
            placeholder="Chọn roles (tối đa 12)...",
            min_values=0,
            max_values=min(12, len(options)),
            options=options[:25],
        )
        sel.callback = self._callback
        self.add_item(sel)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    async def _callback(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ Chỉ Chủ Server.", ephemeral=True)
            return
        selected = [int(v) for v in interaction.data["values"]][:12]
        async with self.lock:
            config = load_guild_config(self.guild_id)
            config["setting_allowed_roles"] = selected
            save_guild_config(self.guild_id, config)
            _invalidate(self.guild_id)
        self.parent._build()
        config = load_guild_config(self.guild_id)
        await interaction.response.edit_message(
            embed=disnake.Embed(
                title="✅ Đã cập nhật roles",
                description=f"Đã lưu **{len(selected)}** role.",
                color=disnake.Color.green(),
            ),
            view=None,
        )
        if self.parent.message:
            try:
                await self.parent.message.edit(embed=_build_permission_embed(config), view=self.parent)
            except Exception:
                pass


class _UserManageView(View):
    def __init__(self, bot, guild_id, lock, current_ids, parent: PermissionView):
        super().__init__(timeout=300)
        self.bot      = bot
        self.guild_id = guild_id
        self.lock     = lock
        self.parent   = parent
        self.current  = list(current_ids)
        self.message: disnake.Message | None = None

        btn_add = disnake.ui.Button(label="➕ Thêm người dùng", style=disnake.ButtonStyle.success, row=0)
        btn_add.callback = self._add
        btn_clr = disnake.ui.Button(label="🗑️ Xóa tất cả", style=disnake.ButtonStyle.danger, row=0)
        btn_clr.callback = self._clear
        self.add_item(btn_add)
        self.add_item(btn_clr)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    async def _add(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ Chỉ Chủ Server.", ephemeral=True)
            return
        if len(self.current) >= 6:
            await interaction.response.send_message("❌ Đã đủ 6 người.", ephemeral=True)
            return
        await interaction.response.send_modal(
            _AddUserModal(self.bot, self.guild_id, self.lock, self.current, parent_view=self)
        )

    async def _clear(self, interaction: disnake.ApplicationCommandInteraction):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("❌ Chỉ Chủ Server.", ephemeral=True)
            return
        async with self.lock:
            config = load_guild_config(self.guild_id)
            config["setting_allowed_users"] = []
            save_guild_config(self.guild_id, config)
            _invalidate(self.guild_id)
        self.current = []
        self.parent._build()
        config = load_guild_config(self.guild_id)
        await interaction.response.edit_message(
            embed=disnake.Embed(
                title="✅ Đã xóa tất cả",
                description="Danh sách người dùng đặc quyền đã được xóa.",
                color=disnake.Color.green(),
            ),
            view=None,
        )
        if self.parent.message:
            try:
                await self.parent.message.edit(embed=_build_permission_embed(config), view=self.parent)
            except Exception:
                pass


class _AddUserModal(Modal):
    def __init__(self, bot, guild_id, lock, current_ids, parent_view: _UserManageView):
        super().__init__(
            title="Thêm người dùng đặc quyền",
            components=[TextInput(
                label="User ID",
                placeholder="Nhập User ID (số) hoặc @mention",
                min_length=1, max_length=25, required=True,
                custom_id="user_id_input",
            )],
        )
        self.bot         = bot
        self.guild_id    = guild_id
        self.lock        = lock
        self.current_ids = current_ids
        self.parent_view = parent_view

    async def callback(self, interaction: disnake.ModalInteraction):
        raw = interaction.text_values["user_id_input"].strip().replace("<@", "").replace(">", "").replace("!", "")
        try:
            uid = int(raw)
        except ValueError:
            await interaction.response.send_message("❌ ID không hợp lệ.", ephemeral=True)
            return
        if uid in self.current_ids:
            await interaction.response.send_message("❌ Người này đã có trong danh sách.", ephemeral=True)
            return
        self.current_ids.append(uid)
        async with self.lock:
            config = load_guild_config(self.guild_id)
            config["setting_allowed_users"] = self.current_ids[:6]
            save_guild_config(self.guild_id, config)
            _invalidate(self.guild_id)
        self.parent_view.parent._build()
        config = load_guild_config(self.guild_id)
        await interaction.response.send_message(
            embed=disnake.Embed(
                title="✅ Đã thêm",
                description=f"<@{uid}> đã được thêm vào danh sách đặc quyền.",
                color=disnake.Color.green(),
            ),
            ephemeral=True,
        )
        if self.parent_view.parent.message:
            try:
                await self.parent_view.parent.message.edit(
                    embed=_build_permission_embed(config),
                    view=self.parent_view.parent,
                )
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════
# CHANNELS VIEW
# ══════════════════════════════════════════════════════════════════

def _build_channels_embed(bot, config: dict) -> disnake.Embed:
    cat_name = tc_name = vc_name = "Chưa đặt"
    if bot:
        if cid := config.get("category_id"):
            ch = bot.get_channel(cid)
            if ch: cat_name = ch.name
        if cid := config.get("text_channel_id"):
            ch = bot.get_channel(cid)
            if ch: tc_name = ch.name
        if cid := config.get("voice_channel_id"):
            ch = bot.get_channel(cid)
            if ch: vc_name = ch.name
    embed = disnake.Embed(
        title="🏷️ QUẢN LÝ KÊNH",
        description="Chọn kênh muốn đổi tên từ menu bên dưới.",
        color=disnake.Color.blurple(),
    )
    embed.add_field(name="📂 Danh mục",     value=f"`{cat_name}`", inline=False)
    embed.add_field(name="💬 Kênh văn bản", value=f"`{tc_name}`",  inline=False)
    embed.add_field(name="🔊 Kênh thoại",   value=f"`{vc_name}`",  inline=False)
    return embed


class ChannelsView(View):
    def __init__(self, bot, guild_id, lock):
        super().__init__(timeout=300)
        self.bot      = bot
        self.guild_id = guild_id
        self.lock     = lock
        self.message: disnake.Message | None = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    @disnake.ui.string_select(
        placeholder="Chọn kênh để đổi tên...",
        min_values=1, max_values=1,
        options=[
            disnake.SelectOption(label="Đổi tên danh mục",     value="category", emoji="📂"),
            disnake.SelectOption(label="Đổi tên kênh văn bản", value="text",     emoji="💬"),
            disnake.SelectOption(label="Đổi tên kênh thoại",   value="voice",    emoji="🔊"),
        ],
    )
    async def channel_select(self, select: disnake.ui.Select, interaction: disnake.MessageInteraction):
        await interaction.response.send_modal(
            RenameChannelModal(self.bot, self.guild_id, self.lock, select.values[0])
        )


# ══════════════════════════════════════════════════════════════════
# MODALS
# ══════════════════════════════════════════════════════════════════

class _BaseModal(Modal):
    """Base modal — auto-refreshes parent SettingsView sau khi submit."""

    def __init__(self, bot, guild_id, lock, parent_view: SettingsView | None = None, title: str = "", components=None):
        super().__init__(title=title, components=components or [])
        self.bot         = bot
        self.guild_id    = guild_id
        self.lock        = lock
        self.parent_view = parent_view

    async def _refresh_parent(self, interaction):
        if self.parent_view and self.parent_view.message:
            try:
                self.parent_view._refresh()
                await self.parent_view.message.edit(
                    embed=self.parent_view._build_embed(),
                    view=self.parent_view,
                )
            except Exception:
                pass


class MaxPlayersModal(_BaseModal):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("title", "Đặt số người chơi tối đa")
        kwargs.setdefault("components", [TextInput(label="Số người tối đa", placeholder="5–65", min_length=1, max_length=2, required=True, custom_id="val")])
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: disnake.ModalInteraction):
        try:
            async with self.lock:
                v = int(interaction.text_values["val"].strip())
                if not (5 <= v <= 65):
                    return await interaction.response.send_message(
                        embed=disnake.Embed(title="❌ Không hợp lệ", description="Phải từ 5 đến 65.", color=disnake.Color.red()),
                        ephemeral=True,
                    )
                config = load_guild_config(self.guild_id)
                if v < config.get("min_players_to_start", 5):
                    return await interaction.response.send_message(
                        embed=disnake.Embed(title="❌ Không hợp lệ", description="Tối đa phải lớn hơn tối thiểu.", color=disnake.Color.red()),
                        ephemeral=True,
                    )
                config["max_players"] = v
                save_guild_config(self.guild_id, config)
                _invalidate(self.guild_id)
            await interaction.response.send_message(
                embed=disnake.Embed(title="✅ Đã cập nhật", description=f"Số người tối đa: **{v}**", color=disnake.Color.green()),
                ephemeral=True,
            )
            await self._refresh_parent(interaction)
        except ValueError:
            await interaction.response.send_message(
                embed=disnake.Embed(title="❌", description="Nhập số hợp lệ.", color=disnake.Color.red()),
                ephemeral=True,
            )


class MinPlayersModal(_BaseModal):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("title", "Đặt số người tối thiểu để bắt đầu")
        kwargs.setdefault("components", [TextInput(label="Số người tối thiểu", placeholder="5–64", min_length=1, max_length=2, required=True, custom_id="val")])
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: disnake.ModalInteraction):
        try:
            async with self.lock:
                v = int(interaction.text_values["val"].strip())
                config = load_guild_config(self.guild_id)
                max_p  = config.get("max_players", 65)
                if v < 5 or v >= max_p:
                    return await interaction.response.send_message(
                        embed=disnake.Embed(title="❌ Không hợp lệ", description=f"Phải từ 5 đến {max_p - 1}.", color=disnake.Color.red()),
                        ephemeral=True,
                    )
                config["min_players_to_start"] = v
                save_guild_config(self.guild_id, config)
                _invalidate(self.guild_id)
            await interaction.response.send_message(
                embed=disnake.Embed(title="✅ Đã cập nhật", description=f"Số người tối thiểu: **{v}**", color=disnake.Color.green()),
                ephemeral=True,
            )
            await self._refresh_parent(interaction)
        except ValueError:
            await interaction.response.send_message(
                embed=disnake.Embed(title="❌", description="Nhập số hợp lệ.", color=disnake.Color.red()),
                ephemeral=True,
            )


class CountdownModal(_BaseModal):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("title", "Đặt thời gian đếm ngược")
        kwargs.setdefault("components", [TextInput(label="Thời gian đếm ngược (phút)", placeholder="1–3", min_length=1, max_length=1, required=True, custom_id="val")])
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: disnake.ModalInteraction):
        try:
            async with self.lock:
                v = int(interaction.text_values["val"].strip())
                if not (1 <= v <= 3):
                    return await interaction.response.send_message(
                        embed=disnake.Embed(title="❌ Không hợp lệ", description="Phải từ 1 đến 3 phút.", color=disnake.Color.red()),
                        ephemeral=True,
                    )
                secs = v * 60
                config = load_guild_config(self.guild_id)
                config["countdown_minutes"] = v
                config["countdown_seconds"] = secs
                save_guild_config(self.guild_id, config)
                _invalidate(self.guild_id)
                try:
                    bot_mod = sys.modules.get("bot") or sys.modules.get("__main__")
                    gs = bot_mod.get_guild_state(self.guild_id)
                    if gs["state"] in (bot_mod.GameState.COUNTDOWN, bot_mod.GameState.FULL_FAST):
                        gs["countdown_time"] = secs
                        await bot_mod.update_lobby(gs)
                except Exception:
                    pass
            await interaction.response.send_message(
                embed=disnake.Embed(title="✅ Đã cập nhật", description=f"Đếm ngược: **{v} phút** ({secs}s)", color=disnake.Color.green()),
                ephemeral=True,
            )
            await self._refresh_parent(interaction)
        except ValueError:
            await interaction.response.send_message(
                embed=disnake.Embed(title="❌", description="Nhập số hợp lệ.", color=disnake.Color.red()),
                ephemeral=True,
            )


class DayTimeModal(_BaseModal):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("title", "Đặt thời gian thảo luận")
        kwargs.setdefault("components", [TextInput(label="Thời gian thảo luận (giây)", placeholder="30–120", min_length=2, max_length=3, required=True, custom_id="val")])
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: disnake.ModalInteraction):
        try:
            async with self.lock:
                v = int(interaction.text_values["val"].strip())
                if not (30 <= v <= 120):
                    return await interaction.response.send_message(
                        embed=disnake.Embed(title="❌ Không hợp lệ", description="Phải từ 30 đến 120 giây.", color=disnake.Color.red()),
                        ephemeral=True,
                    )
                config = load_guild_config(self.guild_id)
                config["day_time"] = v
                save_guild_config(self.guild_id, config)
                _invalidate(self.guild_id)
            await interaction.response.send_message(
                embed=disnake.Embed(title="✅ Đã cập nhật", description=f"Thời gian thảo luận: **{v}s**", color=disnake.Color.green()),
                ephemeral=True,
            )
            await self._refresh_parent(interaction)
        except ValueError:
            await interaction.response.send_message(
                embed=disnake.Embed(title="❌", description="Nhập số hợp lệ.", color=disnake.Color.red()),
                ephemeral=True,
            )


class VoteTimeModal(_BaseModal):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("title", "Đặt thời gian bỏ phiếu")
        kwargs.setdefault("components", [TextInput(label="Thời gian bỏ phiếu (giây)", placeholder="15–45", min_length=2, max_length=2, required=True, custom_id="val")])
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: disnake.ModalInteraction):
        try:
            async with self.lock:
                v = int(interaction.text_values["val"].strip())
                if not (15 <= v <= 45):
                    return await interaction.response.send_message(
                        embed=disnake.Embed(title="❌ Không hợp lệ", description="Phải từ 15 đến 45 giây.", color=disnake.Color.red()),
                        ephemeral=True,
                    )
                config = load_guild_config(self.guild_id)
                config["vote_time"] = v
                save_guild_config(self.guild_id, config)
                _invalidate(self.guild_id)
            label = "36 Thanh Hóa giây" if v == 36 else f"{v}s"
            await interaction.response.send_message(
                embed=disnake.Embed(title="✅ Đã cập nhật", description=f"Thời gian bỏ phiếu: **{label}**", color=disnake.Color.green()),
                ephemeral=True,
            )
            await self._refresh_parent(interaction)
        except ValueError:
            await interaction.response.send_message(
                embed=disnake.Embed(title="❌", description="Nhập số hợp lệ.", color=disnake.Color.red()),
                ephemeral=True,
            )


class SkipDelayModal(_BaseModal):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("title", "Đặt delay DM Skip")
        kwargs.setdefault("components", [TextInput(label="Delay (giây)", placeholder="Số giây trước khi nhắc skip", min_length=1, max_length=3, required=True, custom_id="val")])
        super().__init__(*args, **kwargs)

    async def callback(self, interaction: disnake.ModalInteraction):
        try:
            async with self.lock:
                v = max(0, int(interaction.text_values["val"].strip()))
                config = load_guild_config(self.guild_id)
                config["skip_discussion_delay"] = v
                save_guild_config(self.guild_id, config)
                _invalidate(self.guild_id)
            await interaction.response.send_message(
                embed=disnake.Embed(title="✅ Đã cập nhật", description=f"Delay DM Skip: **{v}s**", color=disnake.Color.green()),
                ephemeral=True,
            )
            await self._refresh_parent(interaction)
        except ValueError:
            await interaction.response.send_message(
                embed=disnake.Embed(title="❌", description="Nhập số hợp lệ.", color=disnake.Color.red()),
                ephemeral=True,
            )


class RenameChannelModal(Modal):
    def __init__(self, bot, guild_id, lock, channel_type: str):
        titles = {
            "category": "Đổi tên danh mục",
            "text":     "Đổi tên kênh văn bản",
            "voice":    "Đổi tên kênh thoại",
        }
        super().__init__(
            title=titles.get(channel_type, "Đổi tên kênh"),
            components=[TextInput(
                label="Tên kênh mới",
                placeholder="Nhập tên mới",
                min_length=1, max_length=100,
                required=True,
                custom_id="new_name",
            )],
        )
        self.bot          = bot
        self.guild_id     = guild_id
        self.lock         = lock
        self.channel_type = channel_type

    async def callback(self, interaction: disnake.ModalInteraction):
        new_name = interaction.text_values["new_name"].strip()

        # Bước 1: Validate nhanh trong lock (không có I/O Discord nào ở đây)
        channel  = None
        old_name = None
        error    = None

        async with self.lock:
            config  = load_guild_config(self.guild_id)
            key_map = {
                "category": "category_id",
                "text":     "text_channel_id",
                "voice":    "voice_channel_id",
            }
            cid = config.get(key_map[self.channel_type])
            if not cid:
                error = "Kênh chưa được cấu hình trong /setup."
            else:
                channel = self.bot.get_channel(cid)
                if not channel:
                    error = "Không tìm thấy kênh (bot có thể chưa cache xong)."
                else:
                    old_name = channel.name
        # Lock đã giải phóng

        # Bước 2: Nếu lỗi validate → trả lời ngay (vẫn trong 3 giây)
        if error:
            await interaction.response.send_message(
                embed=disnake.Embed(
                    title="❌ Không thể đổi tên",
                    description=error,
                    color=disnake.Color.red(),
                ),
                ephemeral=True,
            )
            return

        # Bước 3: defer() — gia hạn 15 phút, tránh timeout 3 giây
        # Phải gọi TRƯỚC channel.edit() vì edit là HTTP call có thể chậm
        await interaction.response.defer(ephemeral=True)

        # Bước 4: Thực sự đổi tên (ngoài lock)
        try:
            await channel.edit(name=new_name)
        except disnake.Forbidden:
            await interaction.followup.send(
                embed=disnake.Embed(
                    title="❌ Không có quyền",
                    description="Bot cần quyền **Quản lý kênh** để đổi tên.",
                    color=disnake.Color.red(),
                ),
                ephemeral=True,
            )
            return
        except disnake.HTTPException as e:
            await interaction.followup.send(
                embed=disnake.Embed(
                    title="❌ Discord trả lỗi",
                    description=f"HTTP {e.status}: {e.text}",
                    color=disnake.Color.red(),
                ),
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.followup.send(
                embed=disnake.Embed(
                    title="❌ Lỗi không xác định",
                    description=str(e),
                    color=disnake.Color.red(),
                ),
                ephemeral=True,
            )
            return

        # Bước 5: Thông báo thành công
        await interaction.followup.send(
            embed=disnake.Embed(
                title="✅ Đã đổi tên thành công",
                description=f"`{old_name}` → `{new_name}`",
                color=disnake.Color.green(),
            ),
            ephemeral=True,
        )


# ══════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════

class SettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot        = bot
        self.edit_locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, guild_id: str) -> asyncio.Lock:
        if guild_id not in self.edit_locks:
            self.edit_locks[guild_id] = asyncio.Lock()
        return self.edit_locks[guild_id]

    @commands.slash_command(name="setting", description="Cấu hình cài đặt trò chơi Anomalies")
    
    async def setting_command(self, interaction: disnake.ApplicationCommandInteraction):
        guild_id = str(interaction.guild.id)
        config   = load_guild_config(guild_id)

        if not _check(interaction, config):
            await interaction.response.send_message(
                "❌ Bạn không có quyền sử dụng lệnh này.", ephemeral=True
            )
            return

        settings = _get_settings_list(config, self.bot)
        embed    = _build_setting_embed(settings[0], 0, len(settings))
        view     = SettingsView(self.bot, guild_id, self._get_lock(guild_id))

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


def setup(bot: commands.Bot):
    bot.add_cog(SettingsCog(bot))
