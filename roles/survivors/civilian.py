import disnake
from roles.base_role import BaseRole


class Civilian(BaseRole):
    name = "Dân Thường"
    team = "Survivors"
    max_count = 12
    dif = 2

    description = (
        "Bạn là một Dân Thường bình thường của thị trấn.\n\n"
        "• Không có khả năng đặc biệt vào ban đêm.\n"
        "• Nhiệm vụ của bạn là quan sát, suy luận và bỏ phiếu đúng người vào ban ngày.\n"
        "• Hãy dùng lý trí để bảo vệ Người Sống Sót và loại bỏ Dị Thể."
    )

    dm_message = (
        "🏘️ **DÂN THƯỜNG**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "Bạn không có khả năng đặc biệt, nhưng lá phiếu của bạn rất quan trọng.\n\n"
        "🎯 Mục tiêu: Giúp thị trấn xác định và loại bỏ tất cả Dị Thể.\n"
        "💡 Hãy lắng nghe, quan sát và đưa ra phán đoán chính xác mỗi ngày."
    )

    # ==============================
    # GỬI UI BAN ĐÊM — Chỉ thông báo, không có action
    # ==============================

    async def send_ui(self, game):
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="🌙 ĐÊM — NGỦ NGON",
                    description=(
                        "Bạn là Dân Thường — không có hành động đặc biệt đêm nay.\n\n"
                        "💤 Hãy nghỉ ngơi và chờ bình minh."
                    ),
                    color=0x95a5a6
                )
            )
        except Exception:
            pass
