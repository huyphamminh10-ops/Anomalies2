# ══════════════════════════════════════════════════════════════════
# DLCs/ExampleMod/roles/survivors/example_survivor.py
# Ví dụ vai Survivor cho DLC
# ══════════════════════════════════════════════════════════════════

import disnake
import sys, os

# Ensure base_role is importable
_base = os.path.join(os.path.dirname(__file__), "../../../../roles")
if _base not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from roles.base_role import BaseRole


class ExampleSurvivor(BaseRole):
    name        = "Nhà Thám Hiểm"
    team        = "Survivors"
    max_count   = 2
    description = (
        "Một vai Survivor mới từ DLC Example.\n\n"
        "• Mỗi đêm có thể dò xét một người chơi.\n"
        "• Nếu người đó là Anomaly, bạn sẽ được thông báo.\n"
        "• Nhiệm vụ: bảo vệ Survivors và loại bỏ Anomalies."
    )

    async def night_action(self, game):
        """Gửi UI chọn mục tiêu dò xét ban đêm."""
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="🔦 ĐÊM — NHÀ THÁM HIỂM",
                    description=(
                        "Bạn đang dò xét khu vực...\n\n"
                        "*(Thêm logic action vào đây — xem các role hiện có để tham khảo)*"
                    ),
                    color=0x3498db,
                )
            )
        except Exception:
            pass

    async def on_game_start(self, game):
        """Thông báo vai trò khi game bắt đầu."""
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="🗺️ NHÀ THÁM HIỂM",
                    description=(
                        "Bạn thuộc phe **Survivors**.\n\n"
                        f"{self.description}\n\n"
                        "🎯 Mục tiêu: Giúp Survivors chiến thắng!"
                    ),
                    color=0x3498db,
                )
            )
        except Exception:
            pass


def register_role(role_manager):
    """Hàm bắt buộc để đăng ký role vào RoleManager."""
    role_manager.register(ExampleSurvivor)
