"""
cogs/help.py — Lệnh /help cho Anomalies
Gồm 2 tab chính: Lệnh & Gameplay
"""
from __future__ import annotations
import disnake
from disnake.ext import commands


# ══════════════════════════════════════════════════════════════════
# DỮ LIỆU LỆNH
# ══════════════════════════════════════════════════════════════════

COMMANDS_DATA = [
    {
        "emoji": "⚙️",
        "name": "/setup",
        "desc": (
            "Cài đặt bot lần đầu cho server — chọn kênh chat chữ, kênh thoại "
            "và danh mục (Category) thông qua menu tương tác. Bot sẽ tự tạo kênh "
            "nếu bạn chọn *Tạo cho tôi*."
        ),
        "perm": "Chủ server / Admin",
    },
    {
        "emoji": "🔧",
        "name": "/setting",
        "desc": (
            "Điều chỉnh các thông số trận đấu: số người, thời gian thảo luận, "
            "thời gian bỏ phiếu, đếm ngược, bật/tắt mute, phân quyền lệnh..."
        ),
        "perm": "Theo cấu hình /setting → Quyền sử dụng lệnh",
    },
    {
        "emoji": "🗑️",
        "name": "/clear",
        "desc": (
            "Xóa toàn bộ tin nhắn trong kênh game (dọn sạch sau trận). "
            "Thường dùng sau khi trận kết thúc để chuẩn bị cho trận tiếp theo."
        ),
        "perm": "Theo cấu hình /setting → Quyền sử dụng lệnh",
    },
    {
        "emoji": "👁️",
        "name": "/role",
        "desc": (
            "Xem danh sách tất cả các vai trò trong game, đọc mô tả chi tiết, "
            "mẹo chơi, và chỉnh sửa tỉ lệ xuất hiện của từng role trong trận tiếp theo."
        ),
        "perm": "Tất cả mọi người",
    },
    {
        "emoji": "❓",
        "name": "/help",
        "desc": "Hiển thị trang trợ giúp này.",
        "perm": "Tất cả mọi người",
    },
]


# ══════════════════════════════════════════════════════════════════
# DỮ LIỆU GAMEPLAY — mỗi mục là 1 câu hỏi thường gặp
# ══════════════════════════════════════════════════════════════════

GAMEPLAY_FAQ = [
    {
        "emoji": "🎮",
        "q": "Cách tham gia & bắt đầu trận",
        "a": (
            "**1.** Vào kênh thoại của bot (kênh được chọn lúc /setup).\n"
            "**2.** Bot sẽ nhận diện bạn và thêm vào phòng chờ.\n"
            "**3.** Khi đủ số người tối thiểu, bot bắt đầu đếm ngược rồi tự động khởi động trận.\n"
            "**4.** Vai trò sẽ được gửi qua **DM** — hãy đảm bảo bật nhận tin nhắn từ server."
        ),
    },
    {
        "emoji": "🌙",
        "q": "Cách thực hiện hành động ban đêm",
        "a": (
            "Khi màn đêm bắt đầu, bot gửi **DM** cho bạn kèm giao diện nút bấm hoặc menu chọn.\n\n"
            "• **Chọn mục tiêu** → bấm nút hoặc chọn từ menu Select.\n"
            "• **Xác nhận** → bấm nút xác nhận (nếu có).\n"
            "• Hành động sẽ được thực thi vào **cuối đêm** (trừ một số role đặc biệt).\n"
            "• Nếu không thực hiện gì, lượt đó coi như bỏ qua.\n\n"
            "⚠️ Một số role có thể bị **chặn hành động** (bởi Kiến Trúc Sư Bóng Tối, Cai Ngục...) "
            "— bạn sẽ nhận thông báo trong DM."
        ),
    },
    {
        "emoji": "☀️",
        "q": "Cách thảo luận & bỏ phiếu ban ngày",
        "a": (
            "**Ban ngày**, tất cả người sống được unmute và nói chuyện tự do.\n\n"
            "• Thảo luận trong kênh chat chữ và kênh thoại.\n"
            "• Khi hết giờ thảo luận, **giai đoạn bỏ phiếu** bắt đầu — bot gửi giao diện bỏ phiếu.\n"
            "• Mỗi người chỉ được **1 phiếu** — bỏ phiếu cho người bạn nghi ngờ là Dị Thể.\n"
            "• Người nhận **nhiều phiếu nhất** sẽ bị trục xuất khỏi thị trấn.\n"
            "• Nếu hòa phiếu → **không ai bị trục xuất** trong ngày đó.\n\n"
            "⏩ **Skip thảo luận:** Nếu được bật, người chơi có thể vote rút ngắn thời gian "
            "thảo luận — bot gửi DM nhắc nhở sau một thời gian nhất định."
        ),
    },
    {
        "emoji": "📜",
        "q": "Cách nhập & xem di chúc",
        "a": (
            "**Ghi di chúc — hoàn toàn qua DM của bot:**\n"
            "Nhắn tin trực tiếp cho bot (DM): `Nhập di chúc`\n"
            "Bot sẽ phản hồi hướng dẫn — sau đó mỗi tin nhắn bạn gửi trong DM = **1 dòng** di chúc.\n\n"
            "• Tối đa **45 dòng**, mỗi dòng tối đa **60 ký tự** (không tính dấu cách).\n"
            "• Dòng hợp lệ → bot react ✅ + số thứ tự dòng.\n"
            "• Dòng quá dài → bot react 🚫 + số thứ tự, kèm thông báo lý do.\n"
            "• Di chúc lưu tự động sau mỗi dòng — không cần lệnh kết thúc.\n"
            "• Khi bạn **chết**, di chúc tự động khóa.\n\n"
            "**Xem di chúc:**\n"
            "Mỗi sáng, bot gửi bảng **📜 LÁ THƯ NGƯỜI CHẾT** kèm menu chọn tại kênh game.\n"
            "Chọn tên người chết → bot gửi **DM** file `.txt` chứa toàn bộ di chúc của họ."
        ),
    },
    {
        "emoji": "💬",
        "q": "Các kênh chat riêng tư có gì?",
        "a": (
            "**🔴 Kênh Dị Thể (Anomaly Chat):**\n"
            "Kênh riêng tư chỉ dành cho phe Dị Thể. Các thành viên Dị Thể có thể "
            "thảo luận chiến thuật mà không bị phe Survivor biết. "
            "Mỗi ngày bot gửi log tổng hợp sự kiện đêm qua vào kênh này.\n\n"
            "**⚫ Kênh Người Chết (Dead Chat):**\n"
            "Kênh dành riêng cho người đã chết. Người chết có thể nói chuyện với nhau "
            "nhưng **không thể** can thiệp vào trận đấu.\n"
            "Nhà Ngoại Cảm có thể hỏi han người trong Dead Chat vào ban đêm.\n\n"
            "**📩 DM (Tin nhắn riêng):**\n"
            "Bot gửi DM cho bạn khi: nhận vai trò, thực hiện hành động đêm, "
            "nhận kết quả điều tra, nhận thông báo bị tấn công, và xem di chúc."
        ),
    },
    {
        "emoji": "👁️",
        "q": "Cách xem phân vai role trong trận tiếp theo",
        "a": (
            "Dùng lệnh **/role** để:\n\n"
            "• **Xem tất cả role** có trong game cùng mô tả chi tiết và mẹo chơi.\n"
            "• **Điều chỉnh tỉ lệ** xuất hiện của từng role trong trận tiếp theo "
            "(ví dụ: tăng số lượng Dị Thể, bỏ một số role nhất định...).\n"
            "• Xem **bảng phân phối role** dự kiến dựa trên số người chơi.\n\n"
            "⚠️ Thay đổi tỉ lệ role chỉ áp dụng cho **1 trận tiếp theo** rồi reset."
        ),
    },
    {
        "emoji": "🏆",
        "q": "Điều kiện thắng của mỗi phe",
        "a": (
            "**🔵 Survivors (Người Sống Sót):**\n"
            "Loại bỏ tất cả Dị Thể và các thực thể đe dọa còn lại.\n\n"
            "**🔴 Anomalies (Dị Thể):**\n"
            "Chiếm đa số — số Dị Thể sống bằng hoặc hơn số Survivor còn lại.\n\n"
            "**⚫ Unknown Entities (Thực Thể Ẩn):**\n"
            "Mỗi role có điều kiện riêng:\n"
            "• **Kẻ Giết Người Hàng Loạt** — là người sống sót duy nhất.\n"
            "• **A.I Tha Hóa** — thu thập đủ dữ liệu từ cả hai phe.\n"
            "• **Đồng Hồ Tận Thế** — kéo dài trận đủ số ngày quy định.\n"
            "• **Kẻ Dệt Thời Gian**, **Kẻ Dệt Mộng**, **Con Tàu Ma**, **Kẻ Tâm Thần** — "
            "điều kiện thắng riêng biệt được ghi trong mô tả vai trò."
        ),
    },
    {
        "emoji": "🔍",
        "q": "Vai trò điều tra hoạt động thế nào?",
        "a": (
            "**🔵 Thám Tử:** Điều tra 1 người/đêm — nhận kết quả là danh sách "
            "các vai trò có thể là người đó (nhóm gợi ý, không phải tên chính xác).\n\n"
            "**🔵 Thám Trưởng:** Điều tra 1 người/đêm — biết **chính xác** vai trò "
            "của họ. Mạnh nhất về thông tin nhưng là mục tiêu ưu tiên của Dị Thể.\n\n"
            "**🔵 Điệp Viên:** Mỗi đêm nhận thông tin Dị Thể **nhắm vào ai** "
            "(nhưng không biết ai trong phe Dị Thể đã thực hiện).\n\n"
            "**🔵 Người Tiên Tri:** Cảm nhận linh hồn 1 người — "
            "biết họ thuộc phe *thiện* hay *ác*.\n\n"
            "**🔴 Tín Hiệu Giả:** Giả mạo kết quả điều tra — làm Thám Tử/Thám Trưởng "
            "nhận thông tin sai về mình."
        ),
    },
    {
        "emoji": "🛡️",
        "q": "Vai trò bảo vệ & chữa lành hoạt động thế nào?",
        "a": (
            "**🔵 Kiến Trúc Sư:** Gia cố nhà 1 người/đêm — người đó được bảo vệ "
            "khỏi tấn công thông thường trong đêm đó.\n\n"
            "**🔵 Nhà Dược Học Điên:** Có 4 loại thuốc:\n"
            "• **Thuốc Chữa** — bảo vệ mục tiêu khỏi bị giết.\n"
            "• **Thuốc Điên** — làm đảo lộn hành động của mục tiêu.\n"
            "• **Thuốc Bộc Lộ** — lộ vai trò mục tiêu trước mọi người.\n"
            "• **Thuốc Virus** — lây bệnh, giết mục tiêu sau 1 đêm.\n\n"
            "⚠️ **Dị Thể Hành Quyết** có thể **xuyên qua** lớp bảo vệ để tiêu diệt mục tiêu."
        ),
    },
    {
        "emoji": "⚰️",
        "q": "Điều gì xảy ra khi bạn chết?",
        "a": (
            "• Bạn nhận **role Dead** và bị mute trong kênh thoại.\n"
            "• Bạn được thêm vào **Dead Chat** — có thể nói chuyện với người chết khác.\n"
            "• Di chúc của bạn (nếu có) tự động **khóa lại**.\n"
            "• Người chơi sẽ thấy bạn trong bảng di chúc mỗi sáng.\n"
            "• Bạn vẫn có thể theo dõi diễn biến qua kênh chat chính (chỉ xem).\n"
            "• **Kẻ Báo Oán** có thể hồi sinh bạn — bạn sẽ nhận DM thông báo.\n\n"
            "⚠️ Người chết **không được** tiết lộ thông tin cho người sống qua kênh công khai."
        ),
    },
    {
        "emoji": "🎭",
        "q": "Spectator — theo dõi trận không tham gia",
        "a": (
            "Nếu bạn vào kênh thoại **sau khi trận đã bắt đầu**, "
            "bot sẽ tự động cho bạn vào chế độ **Spectator** (khán giả).\n\n"
            "• Nickname được đổi thành `👻 Spectator` trong trận.\n"
            "• Có thể xem kênh chat nhưng không thể gửi tin nhắn vào chat game.\n"
            "• Không thể tham gia bỏ phiếu hay thực hiện hành động.\n"
            "• Sau khi trận kết thúc, nickname được **tự động trả lại** tên gốc."
        ),
    },
    {
        "emoji": "🔇",
        "q": "Hệ thống mute hoạt động thế nào?",
        "a": (
            "**Ban đêm:** Tất cả người chơi bị mute trong kênh thoại. "
            "Mọi hành động đêm được thực hiện qua **DM**.\n\n"
            "**Ban ngày:** Tất cả người sống được unmute và thảo luận tự do.\n\n"
            "**Khi chết:** Người chết bị mute vĩnh viễn trong kênh thoại game "
            "(có thể cấu hình tắt tính năng này qua `/setting → Mute Khi Chết`).\n\n"
            "**Chế độ Parliament:** Nếu bật, chỉ người được chỉ định mới được nói "
            "— bot quản lý lượt phát biểu."
        ),
    },
    {
        "emoji": "⚡",
        "q": "Các role đặc biệt của phe Dị Thể",
        "a": (
            "**🔴 Lãnh Chúa (Overlord):** Thủ lĩnh Dị Thể — thấy toàn bộ phe mình "
            "và có thể ra lệnh giết.\n\n"
            "**🔴 Lao Công:** Xóa vai trò công khai của nạn nhân — làm Thám Trưởng "
            "nhận kết quả trống khi điều tra xác.\n\n"
            "**🔴 Máy Hủy Tài Liệu:** Đánh dấu 1 người — nếu họ chết đêm đó, "
            "toàn bộ di chúc bị xóa.\n\n"
            "**🔴 Nguồn Tĩnh Điện:** Làm méo mó DM của người chơi — "
            "kết quả điều tra, thông báo bị nhiễu.\n\n"
            "**🔴 Kẻ Điều Khiển:** Ép 1 Survivor bỏ phiếu theo ý mình ban ngày.\n\n"
            "**🔴 Ký Sinh Thần Kinh:** Tha hóa tâm trí — người bị ký sinh "
            "có thể hành động sai lệch so với ý muốn."
        ),
    },
    {
        "emoji": "🌀",
        "q": "Unknown Entities — các thực thể bí ẩn là gì?",
        "a": (
            "Các **Unknown Entities** không thuộc phe Survivors hay Anomalies — "
            "họ có mục tiêu và điều kiện thắng riêng.\n\n"
            "**Kẻ Giết Người Hàng Loạt** — tấn công mỗi đêm, muốn là người sống duy nhất.\n"
            "**A.I Tha Hóa** — thu thập dữ liệu từ cả hai phe.\n"
            "**Đồng Hồ Tận Thế** — kéo dài trận đủ số ngày.\n"
            "**Kẻ Dệt Mộng** — liên kết 2 người, họ biết vai trò của nhau.\n"
            "**Con Tàu Ma** — bắt cóc người chơi đưa vào vùng trung gian.\n"
            "**Kẻ Dệt Thời Gian** — quan sát và thao túng dòng thời gian.\n"
            "**Kẻ Tâm Thần** — xuất hiện như Dị Thể trong mắt mọi người.\n"
            "**Kẻ Giải Mã** — phá hủy hệ thống truyền tin của cả hai phe."
        ),
    },
]


# ══════════════════════════════════════════════════════════════════
# EMBED BUILDERS
# ══════════════════════════════════════════════════════════════════

COLOR_HELP     = 0x5865F2   # Discord blurple
COLOR_COMMANDS = 0x3498db   # xanh dương
COLOR_GAMEPLAY = 0x9b59b6   # tím


def build_main_embed() -> disnake.Embed:
    embed = disnake.Embed(
        title="📖 ANOMALIES — TRỢ GIÚP",
        description=(
            "Chào mừng bạn đến với **Anomalies** — trò chơi nhập vai suy luận xã hội!\n\n"
            "Chọn thao tác dưới đây để tìm hiểu thêm:"
        ),
        color=COLOR_HELP,
    )
    embed.add_field(
        name="📋 Lệnh",
        value="Danh sách tất cả lệnh bot và chức năng.",
        inline=True,
    )
    embed.add_field(
        name="🎮 Gameplay",
        value="Hướng dẫn chơi, cơ chế game và câu hỏi thường gặp.",
        inline=True,
    )
    embed.set_footer(text="Anomalies Bot  •  /help")
    return embed


def build_commands_embed() -> disnake.Embed:
    embed = disnake.Embed(
        title="📋 DANH SÁCH LỆNH",
        description="Tất cả lệnh slash có trong bot Anomalies:",
        color=COLOR_COMMANDS,
    )
    for cmd in COMMANDS_DATA:
        embed.add_field(
            name=f"{cmd['emoji']} {cmd['name']}",
            value=f"{cmd['desc']}\n> 🔑 **Quyền:** {cmd['perm']}",
            inline=False,
        )
    embed.set_footer(text="Anomalies Bot  •  /help → Lệnh")
    return embed


def build_gameplay_menu_embed() -> disnake.Embed:
    embed = disnake.Embed(
        title="🎮 GAMEPLAY — CÂU HỎI THƯỜNG GẶP",
        description="Bạn muốn tra cứu gì về gameplay?\nChọn từ menu bên dưới:",
        color=COLOR_GAMEPLAY,
    )
    for i, faq in enumerate(GAMEPLAY_FAQ, 1):
        embed.add_field(
            name=f"{faq['emoji']} {i}. {faq['q']}",
            value="",
            inline=False,
        )
    embed.set_footer(text="Anomalies Bot  •  /help → Gameplay")
    return embed


def build_faq_embed(index: int) -> disnake.Embed:
    faq   = GAMEPLAY_FAQ[index]
    embed = disnake.Embed(
        title=f"{faq['emoji']} {faq['q']}",
        description=faq["a"],
        color=COLOR_GAMEPLAY,
    )
    embed.set_footer(text=f"Câu hỏi {index + 1}/{len(GAMEPLAY_FAQ)}  •  Anomalies Bot  •  /help")
    return embed


# ══════════════════════════════════════════════════════════════════
# VIEWS
# ══════════════════════════════════════════════════════════════════

class HelpMainView(disnake.ui.View):
    """View chính: 2 nút — Lệnh và Gameplay."""

    def __init__(self, interaction: disnake.ApplicationCommandInteraction):
        super().__init__(timeout=180)
        self._origin = interaction

    @disnake.ui.button(label="📋 Lệnh", style=disnake.ButtonStyle.primary, row=0)
    async def btn_commands(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        embed = build_commands_embed()
        view  = CommandsBackView(self._origin)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @disnake.ui.button(label="🎮 Gameplay", style=disnake.ButtonStyle.secondary, row=0)
    async def btn_gameplay(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        embed = build_gameplay_menu_embed()
        view  = GameplayMenuView(self._origin)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self._origin.edit_original_response(view=self)
        except Exception:
            pass


class CommandsBackView(disnake.ui.View):
    """Đứng sau màn Lệnh — có nút Quay lại."""

    def __init__(self, origin: disnake.ApplicationCommandInteraction):
        super().__init__(timeout=180)
        self._origin = origin

    @disnake.ui.button(label="← Quay lại", style=disnake.ButtonStyle.secondary, row=0)
    async def btn_back(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        embed = build_main_embed()
        view  = HelpMainView(self._origin)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self._origin.edit_original_response(view=self)
        except Exception:
            pass


class GameplayMenuView(disnake.ui.View):
    """Menu chọn câu hỏi gameplay + nút Quay lại."""

    def __init__(self, origin: disnake.ApplicationCommandInteraction):
        super().__init__(timeout=180)
        self._origin = origin
        self.add_item(GameplaySelect(origin))

    @disnake.ui.button(label="← Quay lại", style=disnake.ButtonStyle.secondary, row=1)
    async def btn_back(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        embed = build_main_embed()
        view  = HelpMainView(self._origin)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self._origin.edit_original_response(view=self)
        except Exception:
            pass


class GameplaySelect(disnake.ui.Select):
    """Select menu chọn câu hỏi."""

    def __init__(self, origin: disnake.ApplicationCommandInteraction):
        self._origin = origin
        options = [
            disnake.SelectOption(
                label=f"{i+1}. {faq['q']}"[:100],
                value=str(i),
                emoji=faq["emoji"],
            )
            for i, faq in enumerate(GAMEPLAY_FAQ)
        ]
        super().__init__(
            placeholder="Chọn câu hỏi bạn muốn tìm hiểu...",
            options=options,
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: disnake.ApplicationCommandInteraction):
        idx   = int(self.values[0])
        embed = build_faq_embed(idx)
        view  = FAQDetailView(self._origin, idx)
        await interaction.response.edit_message(embed=embed, view=view)


class FAQDetailView(disnake.ui.View):
    """Chi tiết 1 câu hỏi — có nút ◀ ▶ và Quay lại menu."""

    def __init__(self, origin: disnake.ApplicationCommandInteraction, idx: int):
        super().__init__(timeout=180)
        self._origin = origin
        self._idx    = idx
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        total = len(GAMEPLAY_FAQ)

        btn_prev = disnake.ui.Button(
            label="◀ Trước",
            style=disnake.ButtonStyle.secondary,
            disabled=(self._idx == 0),
            row=0,
        )
        btn_prev.callback = self._prev

        btn_next = disnake.ui.Button(
            label="Tiếp ▶",
            style=disnake.ButtonStyle.secondary,
            disabled=(self._idx >= total - 1),
            row=0,
        )
        btn_next.callback = self._next

        btn_menu = disnake.ui.Button(
            label="📋 Danh sách câu hỏi",
            style=disnake.ButtonStyle.primary,
            row=1,
        )
        btn_menu.callback = self._back_menu

        self.add_item(btn_prev)
        self.add_item(btn_next)
        self.add_item(btn_menu)

    async def _prev(self, interaction: disnake.ApplicationCommandInteraction):
        self._idx -= 1
        self._rebuild()
        await interaction.response.edit_message(embed=build_faq_embed(self._idx), view=self)

    async def _next(self, interaction: disnake.ApplicationCommandInteraction):
        self._idx += 1
        self._rebuild()
        await interaction.response.edit_message(embed=build_faq_embed(self._idx), view=self)

    async def _back_menu(self, interaction: disnake.ApplicationCommandInteraction):
        embed = build_gameplay_menu_embed()
        view  = GameplayMenuView(self._origin)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self._origin.edit_original_response(view=self)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════

class HelpCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.slash_command(name="help", description="Xem hướng dẫn sử dụng bot Anomalies")
    async def help_command(self, interaction: disnake.ApplicationCommandInteraction):
        embed = build_main_embed()
        view  = HelpMainView(interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
