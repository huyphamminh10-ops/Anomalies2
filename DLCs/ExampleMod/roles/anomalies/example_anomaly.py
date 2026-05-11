# ══════════════════════════════════════════════════════════════════
# DLCs/ExampleMod/roles/anomalies/example_anomaly.py
# Ví dụ vai Anomaly cho DLC
# ══════════════════════════════════════════════════════════════════

import disnake
import sys, os

_base = os.path.join(os.path.dirname(__file__), "../../../../roles")
if os.path.join(os.path.dirname(__file__), "../../../..") not in sys.path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from roles.base_role import BaseRole


class ExampleAnomaly(BaseRole):
    name        = "Bóng Ma Số"
    team        = "Anomalies"
    max_count   = 1
    description = (
        "Một Anomaly bí ẩn từ DLC Example.\n\n"
        "• Mỗi đêm có thể ẩn mình, miễn dịch với mọi hành động.\n"
        "• Nhiệm vụ: tiêu diệt tất cả Survivors."
    )

    async def night_action(self, game):
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="👻 ĐÊM — BÓNG MA SỐ",
                    description=(
                        "Bạn đang ẩn mình trong bóng tối...\n\n"
                        "*(Thêm logic Anomaly action tại đây)*"
                    ),
                    color=0xe74c3c,
                )
            )
        except Exception:
            pass

    async def on_game_start(self, game):
        try:
            await self.safe_send(
                embed=disnake.Embed(
                    title="💀 BÓNG MA SỐ",
                    description=(
                        "Bạn thuộc phe **Anomalies**.\n\n"
                        f"{self.description}\n\n"
                        "🎯 Mục tiêu: Tiêu diệt tất cả Survivors!"
                    ),
                    color=0xe74c3c,
                )
            )
        except Exception:
            pass


def register_role(role_manager):
    """Hàm bắt buộc để đăng ký role vào RoleManager."""
    role_manager.register(ExampleAnomaly)
