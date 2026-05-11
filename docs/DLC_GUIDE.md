# 🧩 DOELCES v2.0 — Hướng Dẫn Tạo Mod DLC

## Mục Lục
1. [Cấu trúc folder](#1-cấu-trúc-folder)
2. [File mod.py](#2-file-modpy)
3. [Tạo role mới (new_role)](#3-tạo-role-mới)
4. [Thêm phe mới (new_team)](#4-thêm-phe-mới-newteam)
5. [CUSTOM_META.py — Phân phối tuỳ chỉnh](#5-custom_metapy)
6. [Thêm event (new_event)](#6-thêm-event-newevent)
7. [Hệ thống kinh tế](#7-hệ-thống-kinh-tế)
8. [Luồng kích hoạt mod](#8-luồng-kích-hoạt-mod)
9. [Checklist trước khi phát hành](#9-checklist)
10. [Lỗi thường gặp](#10-lỗi-thường-gặp)

---

## 1. Cấu Trúc Folder

```
DLCs/
└── TenModCuaBan/                ← Tên folder = ID mod (không dấu, không space)
    ├── mod.py                   ← 📌 BẮT BUỘC: Metadata
    ├── pack.png                 ← 📌 BẮT BUỘC: Icon (jpg/png/webp, 256x256)
    ├── CUSTOM_META.py           ← Tuỳ chọn: Phân phối phe mới
    │
    ├── roles/
    │   ├── survivors/           ← Role phe Người Sống Sót (mặc định)
    │   ├── anomalies/           ← Role phe Dị Thể (mặc định)
    │   ├── unknown/             ← Role phe Không Xác Định (mặc định)
    │   └── Vampire/             ← Role phe mới (khai báo qua new_teams)
    │       └── ma_ca_rong.py
    │
    └── events/                  ← Event files (khai báo qua new_events)
        └── anh_sang_cong_ly.py
```

---

## 2. File `mod.py`

```python
DLC = {
    "name":        "Tên Mod Của Bạn",
    "description": "Mô tả nội dung DLC.",
    "version":     "1.0.0",
    "author":      "TênBạn",

    # Giá: "nope" (miễn phí) | {"currency": "gold", "amount": 500} | {"currency": "gems", "amount": 50}
    "price": "nope",

    # Tối đa 14 feature tag (xem docs/FEATURES.md để biết đầy đủ)
    "features": ["new_role"],

    # Roles trong 3 phe mặc định + phe mới
    "roles": {
        "survivors": ["tên_file_không_py"],
        "anomalies": [],
        "unknown":   [],
    },

    # Chỉ cần khi features có "new_team"
    "new_teams": [],

    # Chỉ cần khi features có "new_event"
    "new_events": [],

    # Hàm cần gọi khi kích hoạt DLC (balance patch, feature đặc biệt...)
    "addresses": [],

    # Tên folder DLC cần load trước
    "requires": [],
}
```

---

## 3. Tạo Role Mới

Mỗi file role phải kế thừa `BaseRole` và có hàm `register_role()`:

```python
# roles/survivors/tên_file.py
import disnake
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
from roles.base_role import BaseRole


class TênClass(BaseRole):
    name        = "Tên Hiển Thị"   # Tên role trong game
    team        = "Survivors"       # "Survivors" | "Anomalies" | "Unknown" | "TênPheM ới"
    faction     = "Survivors"       # Giống team
    max_count   = 2
    description = "Mô tả vai trò..."

    async def on_game_start(self, game):
        await self.safe_send(embed=disnake.Embed(
            title=f"🎭 {self.name.upper()}",
            description=self.description,
            color=0x3498db,
        ))

    async def night_action(self, game):
        """Hành động ban đêm — gửi UI hoặc xử lý logic ở đây."""
        pass

    async def on_death(self, game):
        """Hook khi chết — tuỳ chọn."""
        pass


def register_role(role_manager):
    role_manager.register(TênClass)
```

**Màu embed theo phe:**
| Phe | Màu |
|-----|-----|
| Survivors | `0x2ecc71` (xanh lá) |
| Anomalies | `0xe74c3c` (đỏ) |
| Unknown | `0x9b59b6` (tím) |
| Phe mới | Tự chọn |

---

## 4. Thêm Phe Mới (NewTeam)

### Bước 1 — Khai báo trong `mod.py`

```python
"features": ["new_role", "new_team"],

"new_teams": [
    {
        "team_name":   "Vampire",          # Tên phe — dùng trong role.team
        "folder_path": "roles/Vampire",    # Đường dẫn từ folder mod
    }
],

"roles": {
    "survivors": [],
    "anomalies": [],
    "unknown":   [],
    "Vampire":   ["ma_ca_rong"],           # File trong roles/Vampire/
},
```

### Bước 2 — Tạo CUSTOM_META.py

```python
# CUSTOM_META.py (đặt cùng cấp với roles/)

VAMPIRE_META = {
    "Ma Cà Rồng": {"weight": 8, "min_players": 6,  "max_count": 3, "core": True},
    "Bá Tước":    {"weight": 4, "min_players": 12, "max_count": 1, "core": False},
}

CUSTOM_TEAMS = ["Vampire"]
TEAM_META_MAP = {"Vampire": VAMPIRE_META}

def get_slot_counts(total_players: int) -> dict:
    """Trả về số slot mỗi phe mới theo số người chơi."""
    return {"Vampire": max(1, round(total_players * 0.15))}
```

### Bước 3 — Tạo role

```python
# roles/Vampire/ma_ca_rong.py
class MaCaRong(BaseRole):
    name    = "Ma Cà Rồng"
    team    = "Vampire"         # ← Phải khớp với team_name
    faction = "Vampire"
    ...
```

### Bước 4 — Dùng ExtendedRoleDistributor trong game.py

```python
from core.role_distributor import distribute_roles_extended
from core.dlc_loader import collect_all_custom_metas

custom_metas = collect_all_custom_metas()
roles = distribute_roles_extended(members, role_classes, custom_metas)
```

---

## 5. CUSTOM_META.py

`CUSTOM_META.py` nằm **ngang cấp với thư mục `roles/`** (trong folder mod).  
Nó cho phép bạn kiểm soát hoàn toàn cách phân phối phe mới.

**Các thành phần:**

```python
# ── META cho phe mới (bắt buộc nếu có new_team) ──
TEAM_META_MAP = {
    "TênPhe": {
        "Tên Role": {
            "weight":      8,      # Trọng số chọn ngẫu nhiên (cao = phổ biến hơn)
            "min_players": 6,      # Số người chơi tối thiểu để role này xuất hiện
            "max_count":   3,      # Số lượng tối đa trong 1 game
            "core":        True,   # True = role mặc định khi không đủ power role
        },
    },
}

CUSTOM_TEAMS = ["TênPhe"]  # Danh sách phe được quản lý bởi file này

# ── Override số slot ─────────────────────────────────────────────
def get_slot_counts(total_players: int) -> dict:
    return {"TênPhe": max(1, round(total_players * 0.15))}

# ── Override điều kiện thắng (cần custom_win trong features) ────
def check_win_condition(alive_roles: list) -> tuple:
    team_alive = [r for r in alive_roles if r.team == "TênPhe"]
    others     = [r for r in alive_roles if r.team != "TênPhe"]
    if team_alive and not others:
        return True, "TênPhe"
    return False, None
```

---

## 6. Thêm Event (NewEvent)

### Khai báo trong `mod.py`

```python
"features": ["new_event"],

"new_events": [
    {
        "event_name":     "Tên Sự Kiện",
        "folder_path":    "events",
        "entry_module":   "DLCs.TênMod.events.tên_file",   # Đường dẫn Python (dấu chấm)
        "entry_function": "run_event",                      # Tên hàm (mặc định: run_event)
    },
],
```

### Viết file event

```python
# events/tên_sự_kiện.py
import disnake

async def run_event(game):
    """
    Hàm chính của event.
    - game: GameEngine instance (hoặc None nếu không có game đang chạy)
    - Sau khi hàm này return, EventScheduler sẽ thông báo và game tiếp tục.
    """
    if game is None:
        return  # Không có game đang chạy

    # === CODE EVENT CỦA BẠN ===
    # Ví dụ: giết tất cả Anomalies
    for role in game.roles.values():
        if role.alive and role.team == "Anomalies":
            role.alive = False
            await role.on_death(game)

    # Gửi thông báo vào channel
    await game.channel.send(embed=disnake.Embed(
        title="☀️ Ánh Sáng Công Lý",
        description="Tất cả Dị Thể đã bị tiêu diệt!",
        color=0xFFD700,
    ))
```

### Khởi động EventScheduler

Trong `bot_main.py` hoặc `app.py`, sau khi bot ready:

```python
from core.dlc_loader import EventScheduler

# Tạo và start scheduler
scheduler = EventScheduler(
    bot=bot,
    channel_id=1234567890,   # ID của text channel để gửi thông báo
    game_ref=None,           # Truyền game object khi game bắt đầu
)
scheduler.start()

# Khi game bắt đầu:
scheduler.game_ref = game_instance

# Khi game kết thúc:
scheduler.game_ref = None
```

**Cơ chế tự động:**
- Mỗi **48 giờ** scheduler thức dậy
- Roll **50% cơ hội** — nếu trúng mới kích hoạt
- Chọn **ngẫu nhiên** 1 event từ bất kỳ DLC nào đã đăng ký
- Gửi thông báo → chạy event → báo hoàn thành → game tiếp tục

---

## 7. Hệ Thống Kinh Tế

| Điều kiện | Phần thưởng |
|-----------|-------------|
| Sống sót đến cuối | 1–35 Gold + số ngày sống |
| Chết giữa trận | 30 Gold cố định |
| Mỗi action thực hiện | 50% cơ hội 1–5 Gems |

```python
from core.dlc_economy import award_game_rewards

results = await award_game_rewards(
    players_data=[
        {"user_id": "123", "survived": True, "days_survived": 4, "actions_taken": 3},
    ],
    game_id="game_xyz",
)
```

---

## 8. Luồng Kích Hoạt Mod

```
Owner tạo serial key
    ↓
Bot lưu vào DB
    ↓
Người chơi dùng /mods → nhập serial qua DM
    ↓
Bot validate → đánh dấu "used" → unlock Mod
    ↓
Admin bật Mod trong server: /settings → chọn Mod
    ↓
Bot load DLC: scan → validate → load roles → register events → activate addresses
    ↓
Game bắt đầu với roles + teams + events từ DLC
```

**Format Serial Key:**
```
TênMod:59c19yu0%951b@@5odv0#i%t
  └────┘ └────────────────────────┘
Tên folder     25 ký tự (a-z A-Z 0-9 @ & % ₫)
```

---

## 9. Checklist

Trước khi phát hành DLC:

- [ ] `mod.py` có biến `DLC = {...}` hợp lệ
- [ ] Có file icon `pack.png` (hoặc `.jpg` / `.webp`)
- [ ] Mỗi file role có `register_role(role_manager)` và kế thừa `BaseRole`
- [ ] `name` trong role **không trùng** với role hiện có trong game gốc
- [ ] Nếu có `new_team`: `CUSTOM_META.py` tồn tại và có `TEAM_META_MAP`
- [ ] Nếu có `new_event`: file event có hàm `run_event(game)` đúng cú pháp
- [ ] Test quick: `python -c "from core.dlc_loader import scan_dlcs; scan_dlcs()"`
- [ ] Mô tả `description` rõ ràng (người chơi đọc trước khi mua)

---

## 10. Lỗi Thường Gặp

| Lỗi | Nguyên nhân | Cách sửa |
|-----|------------|----------|
| `Thiếu file bắt buộc: mod.py` | Không có `mod.py` | Tạo file `mod.py` |
| `Thiếu file icon` | Không tìm thấy `pack.*` | Đặt `pack.png` vào folder |
| `feature không hợp lệ` | Tên feature sai | Dùng đúng 14 tên trong `FEATURES.md` |
| `faction 'X' không hợp lệ` | Phe chưa được khai báo trong `new_teams` | Thêm vào `new_teams` trước |
| `NewTeam 'X': folder không tồn tại` | Thiếu thư mục | Tạo `roles/<TênPhe>/` |
| `Feature 'new_team' nhưng thiếu new_teams` | Khai báo feature nhưng quên block | Thêm `"new_teams": [...]` vào DLC dict |
| `Không tìm thấy hàm run_event` | Sai tên hàm | Đảm bảo file event có `def run_event(game):` |
| `thiếu hàm register_role()` | Quên thêm | Thêm `def register_role(rm): rm.register(TênClass)` |
| `CUSTOM_META.py thiếu TEAM_META_MAP` | File thiếu biến | Định nghĩa `TEAM_META_MAP = {"TênPhe": ...}` |
