# 🧩 DOELCES v1.0 — Hướng Dẫn Tạo Mod DLC

## Cấu Trúc Folder DLC

```
DLCs/
└── TenModCuaBan/                ← Tên folder = ID của mod (không dấu, không space)
    ├── mod.py                   ← 📌 BẮT BUỘC: Metadata
    ├── pack.png                 ← 📌 BẮT BUỘC: Icon (jpg/png/webp, đề xuất 256x256)
    └── roles/
        ├── survivors/
        │   └── vai_cua_ban.py
        ├── anomalies/
        │   └── di_the_moi.py
        └── unknown/
            └── vai_bi_an.py
```

---

## File `mod.py` — Metadata

```python
DLC = {
    # Tên hiển thị (chuỗi Unicode bình thường)
    "name": "Tên Mod Của Bạn",

    # Mô tả nội dung DLC
    "description": "Thêm 2 vai mới: Nhà Thám Hiểm và Bóng Ma Số.",

    # Phiên bản và tác giả
    "version": "1.0.0",
    "author":  "TênBạn",

    # Giá:
    #   Miễn phí → "nope"
    #   Trả Gold  → {"currency": "gold", "amount": 500}
    #   Trả Gems  → {"currency": "gems", "amount": 50}
    "price": {"currency": "gold", "amount": 500},

    # Tính năng (tối đa 14 loại):
    # new_role | new_team | new_event | new_item | new_ability
    # new_faction | new_map | new_mode | custom_win | custom_ui
    # custom_sound | balance_patch | seasonal | community
    "features": ["new_role"],

    # Roles — tên file không có .py, trong thư mục roles/
    "roles": {
        "survivors": ["ten_file_survivor"],
        "anomalies": ["ten_file_anomaly"],
        "unknown":   [],
    },

    # Addresses — hàm cần gọi để kích hoạt tính năng phụ
    "addresses": [
        # {
        #   "module_path": "DLCs.TenMod.features.my_feature",
        #   "function":    "register",
        #   "description": "Đăng ký event custom",
        # }
    ],

    # DLC cần load trước (tên folder)
    "requires": [],
}
```

---

## Tạo Role Mới

Mỗi file role phải kế thừa `BaseRole` và có hàm `register_role()`:

```python
# DLCs/TenMod/roles/survivors/vai_moi.py
import disnake
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
from roles.base_role import BaseRole


class VaiMoi(BaseRole):
    name      = "Tên Vai Trò"       # ← Tên hiển thị trong game
    team      = "Survivors"          # "Survivors" | "Anomalies" | "Unknown"
    max_count = 2                    # Số lượng tối đa trong 1 game
    description = "Mô tả vai trò..."

    async def night_action(self, game):
        """Hành động ban đêm."""
        await self.safe_send(embed=disnake.Embed(
            title="🌙 ĐÊM",
            description="Logic của bạn ở đây...",
            color=0x3498db,
        ))

    async def on_game_start(self, game):
        """Thông báo vai trò khi game bắt đầu."""
        await self.safe_send(embed=disnake.Embed(
            title=f"🎭 {self.name.upper()}",
            description=self.description,
            color=0x3498db,
        ))

    async def on_death(self, game):
        """Hook khi chết (tùy chọn)."""
        pass


def register_role(role_manager):
    """BẮT BUỘC: Đăng ký role."""
    role_manager.register(VaiMoi)
```

---

## Hệ Thống Kinh Tế

### Kiếm Gold & Gems
| Điều kiện | Phần thưởng |
|-----------|-------------|
| Sống sót đến cuối | 1–35 Gold (ngẫu nhiên) + số ngày sống |
| Chết giữa trận | 30 Gold cố định |
| Mỗi hành động | 50% cơ hội nhận 1–5 Gems (cộng dồn) |

### Gọi hàm reward sau trận (trong game.py)
```python
from core.dlc_economy import award_game_rewards

results = await award_game_rewards(
    players_data=[
        {
            "user_id":      "123456789",
            "survived":     True,
            "days_survived": 4,
            "actions_taken": 3,   # số action đã thực hiện
        },
        # ...
    ],
    game_id="game_xyz",
)
# results = {"user_id": {"gold": 39, "gems": 7, "reason": "Sống sót 4 ngày"}}
```

---

## Kích Hoạt Mod — Luồng Hoạt Động

```
Owner tạo serial  →  Bot lưu DB  →  Người chơi mua trên Dashboard
                                   HOẶC
                                   Người chơi dùng /mods → nhập serial qua DM
                                   ↓
                              Bot validate → đánh dấu "used" → unlock Mod
                                   ↓
                              Người chơi dùng /settings → bật Mod trong server
```

### Format Serial Key
```
TenMod:59c19yu0%951b@@5odv0#i%t
  └─────┘ └─────────────────────┘
 Tên folder     25 ký tự (a-z A-Z 0-9 @ & % ₫)
```

---

## Checklist Trước Khi Phát Hành

- [ ] `mod.py` có biến `DLC = {...}` hợp lệ
- [ ] Có file icon `pack.png` (hoặc .jpg / .webp)
- [ ] Mỗi file role có hàm `register_role(role_manager)`
- [ ] `name` trong role không trùng với role hiện có
- [ ] Test thử: `python -c "from core.dlc_loader import scan_dlcs; scan_dlcs()"`
- [ ] Mô tả rõ ràng trong `description` (người chơi sẽ đọc trước khi mua)

---

## Lỗi Thường Gặp

| Lỗi | Nguyên nhân | Cách sửa |
|-----|------------|---------|
| `Thiếu file bắt buộc: mod.py` | Không có file mod.py | Tạo file mod.py |
| `Thiếu file icon` | Không tìm thấy pack.* | Đặt ảnh pack.png vào folder |
| `DLC trong mod.py phải là dict` | Sai cú pháp | Kiểm tra lại `DLC = {...}` |
| `feature không hợp lệ` | Tên feature sai | Dùng đúng 14 tên đã liệt kê |
| `File role không tồn tại` | Tên file không khớp | Kiểm tra `"roles"` trong DLC dict |
| `mod.py thiếu hàm register_role()` | Role file thiếu hàm | Thêm `def register_role(rm): rm.register(TenClass)` |
