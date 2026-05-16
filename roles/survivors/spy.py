import disnake
from roles.base_role import BaseRole


class Spy(BaseRole):
    name = "Điệp Viên"
    team = "Survivors"
    max_count = 1
    dif = 5
    rarity = "rare"

    description = (
        "Mỗi đêm bạn sẽ biết Dị Thể nhắm vào ai.\n"
        "Bạn không biết ai là kẻ giết."
    )

    dm_message = (
        "👁️ **ĐIỆP VIÊN**\n\n"
        "Bạn thuộc phe **Người Sống Sót**.\n\n"
        "📡 Mỗi đêm bạn tự động nhận thông tin về mục tiêu mà Dị Thể nhắm vào.\n"
        "🔕 Bạn không biết ai là kẻ giết — chỉ biết ai bị nhắm.\n\n"
        "💡 Hãy chia sẻ thông tin cẩn thận — lộ sớm có thể khiến bạn bị tiêu diệt.\n"
        "🎯 Mục tiêu: Dùng tin tức để hướng dẫn thị trấn bỏ phiếu đúng người."
    )


    # ==============================
    # GỬI UI BAN ĐÊM — Thông báo đang thu thập tín hiệu
    # ==============================

    async def send_ui(self, game):
        view = self.SpyStandbyView(self)
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="👁️ ĐÊM — ĐIỆP VIÊN",
                    description=(
                        "Hệ thống theo dõi đang hoạt động...\n\n"
                        "🔎 Bạn sẽ tự động nhận được thông tin về mục tiêu của Dị Thể\n"
                        "sau khi phe Dị Thể hoàn tất lựa chọn.\n\n"
                        "📡 Đang thu thập tín hiệu..."
                    ),
                    color=0x34495e
                ),
                view=view
            )
        except Exception:
            pass

    class SpyStandbyView(disnake.ui.View):
        def __init__(self, role):
            super().__init__(timeout=60)
            self.role = role

        @disnake.ui.button(label="📡 Trạng thái: Đang theo dõi", style=disnake.ButtonStyle.secondary, disabled=True)
        async def status(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
            pass

    # ==============================
    # NHẬN THÔNG TIN SAU KHI ANOMALIES CHỌN
    # ==============================

    async def receive_info(self, game, target):
        if not target:
            try:
                await self.safe_send(
                    embed=disnake.Embed(
                        title="👁️ THÔNG TIN TÌNH BÁO",
                        description="📡 Đêm nay Dị Thể không có hành động bất thường.",
                        color=0x34495e
                    )
                )
            except Exception:
                pass
            return

        try:
            embed = disnake.Embed(
                title="👁️ THÔNG TIN TÌNH BÁO",
                description=f"⚠️ Dị Thể đang nhắm vào: **{target.display_name}**",
                color=0xe74c3c
            )
            embed.set_footer(text="Bạn không biết kẻ nào trong số Dị Thể đang ra tay.")
            await self.safe_send(embed=embed)
        except Exception:
            pass
