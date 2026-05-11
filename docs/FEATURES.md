# 🎛️ Danh Sách 14 Features — DOELCES v2.0

File này mô tả đầy đủ 14 feature tag có thể khai báo trong `mod.py`.  
Mỗi DLC được dùng **tối đa 14 loại**, phải khai báo đúng tên.

---

## Cách khai báo

```python
DLC = {
    ...
    "features": ["new_role", "new_team", "new_event"],  # ← khai báo ở đây
    ...
}
```

---

## 1. `new_role` — Thêm vai trò mới

Thêm role mới vào các phe mặc định: `survivors`, `anomalies`, `unknown`.  
Đây là feature cơ bản nhất — hầu hết DLC đều dùng.

**Yêu cầu:**
- File role đặt trong `roles/<phe>/tên_file.py`
- File phải có class kế thừa `BaseRole` và hàm `register_role(role_manager)`
- Khai báo trong `"roles": {...}` trong `mod.py`

**Ví dụ:**
```python
"features": ["new_role"],
"roles": {"survivors": ["thám_tử_đặc_biệt"]}
```

---

## 2. `new_team` — Thêm phe mới

Tạo một phe hoàn toàn mới bên cạnh 3 phe mặc định.  
Phe mới có mục tiêu thắng riêng, phân phối riêng và meta riêng.

**Yêu cầu:**
- Khai báo block `"new_teams": [...]` trong `mod.py`
- Tạo folder `roles/<TênPhe>/` với các role bên trong
- Tạo `CUSTOM_META.py` để khai báo `TEAM_META_MAP` và `get_slot_counts()`
- Role trong phe mới phải có `team = "TênPhe"` khớp chính xác

**Ví dụ:**
```python
"features": ["new_role", "new_team"],
"new_teams": [
    {
        "team_name":   "Vampire",
        "folder_path": "roles/Vampire",
    }
],
"roles": {"Vampire": ["ma_ca_rong"]}
```

**CUSTOM_META.py phải có:**
```python
VAMPIRE_META = {"Ma Cà Rồng": {"weight": 8, "min_players": 6, "max_count": 3, "core": True}}
CUSTOM_TEAMS = ["Vampire"]
TEAM_META_MAP = {"Vampire": VAMPIRE_META}
def get_slot_counts(total_players): return {"Vampire": max(1, round(total_players * 0.15))}
```

---

## 3. `new_event` — Thêm event can thiệp game

Thêm sự kiện đặc biệt có thể can thiệp trực tiếp vào trận đấu đang chạy.

**Cơ chế:**
- Mỗi **2 ngày**, `EventScheduler` tự động roll **50% cơ hội**
- Nếu trúng: chọn ngẫu nhiên 1 event từ tất cả DLC đã load
- Bot gửi thông báo vào text channel, **chạy code event đến khi xong**
- Sau đó game tiếp tục bình thường

**Yêu cầu:**
- Khai báo block `"new_events": [...]` trong `mod.py`
- Viết file event với hàm `async def run_event(game):` hoặc `def run_event(game):`
- `game`: object `GameEngine` hiện tại (có thể `None` nếu không có game)

**Ví dụ file event:**
```python
async def run_event(game):
    if game is None: return
    # Can thiệp trực tiếp vào game
    for role in game.roles.values():
        if role.alive and role.team == "Anomalies":
            role.alive = False
            await role.on_death(game)
    await game.channel.send("☀️ Ánh sáng công lý đã diệt mọi Dị Thể!")
```

**Khởi động EventScheduler** (trong `bot_main.py` hoặc `app.py`):
```python
from core.dlc_loader import EventScheduler
scheduler = EventScheduler(bot=bot, channel_id=YOUR_CHANNEL_ID, game_ref=None)
scheduler.start()
# Khi game bắt đầu: scheduler.game_ref = game_instance
```

---

## 4. `new_item` — Thêm vật phẩm mới

Thêm item/vật phẩm mà người chơi có thể nhận và sử dụng trong game.

**Dự kiến:**
- File item đặt trong `items/tên_item.py`
- Class kế thừa `BaseItem` (nếu có) hoặc tự định nghĩa
- Khai báo trong `addresses` để đăng ký item vào item manager

**Ví dụ (khi item system được implement):**
```python
"features": ["new_item"],
"addresses": [{"module_path": "DLCs.MyMod.items.holy_water", "function": "register_item"}]
```

---

## 5. `new_ability` — Thêm kỹ năng mới

Thêm kỹ năng/ability đặc biệt cho role hoặc như một hệ thống riêng.

**Dự kiến:**
- Ability có thể được gắn vào role hiện có hoặc role mới
- File ability đặt trong `abilities/tên_ability.py`
- Khai báo qua `addresses` để hook vào game engine

**Ví dụ:**
```python
"features": ["new_role", "new_ability"],
```

---

## 6. `new_faction` — Thêm faction phụ

Tạo một faction (nhóm nhỏ) **trong nội bộ một phe** — không phải phe mới độc lập.  
Ví dụ: "Giáo Hội" là faction trong Survivors, có mục tiêu phụ riêng.

**Khác với `new_team`:**
- `new_team`: phe mới hoàn toàn, thắng/thua độc lập
- `new_faction`: nhóm nhỏ trong phe hiện có, thắng cùng phe nhưng có điều kiện phụ

---

## 7. `new_map` — Thêm bản đồ mới

Thêm map/địa điểm mới cho các game mode có hỗ trợ map.  
Tag này để đánh dấu — implementation phụ thuộc vào game mode.

---

## 8. `new_mode` — Thêm chế độ chơi mới

Thêm một game mode hoàn toàn khác (VD: Battle Royale, Coop, Ranked...).

**Yêu cầu:**
- File mode đặt trong `modes/tên_mode.py`
- Khai báo qua `addresses` để đăng ký vào mode selector

---

## 9. `custom_win` — Điều kiện thắng tuỳ chỉnh

Thêm hoặc override điều kiện thắng của game.

**Yêu cầu:**
- Trong `CUSTOM_META.py`, định nghĩa hàm `check_win_condition(alive_roles)`:

```python
def check_win_condition(alive_roles: list) -> tuple:
    """Trả về (đã_thắng: bool, tên_phe_thắng: str | None)"""
    vampires = [r for r in alive_roles if r.team == "Vampire"]
    others   = [r for r in alive_roles if r.team != "Vampire"]
    if vampires and not others:
        return True, "Vampire"
    return False, None
```

Game engine sẽ gọi hàm này sau mỗi vòng nếu `custom_win` được khai báo.

---

## 10. `custom_ui` — Giao diện tuỳ chỉnh

Thay đổi giao diện embed, button, hoặc select menu trong game.

**Ví dụ:**
- Embed màu đặc trưng cho phe mới
- Button hành động có icon riêng
- Thông báo ban đêm/ban ngày được reskin

Khai báo qua `addresses` để override hàm UI:
```python
"addresses": [{"module_path": "DLCs.MyMod.ui.vampire_ui", "function": "patch_ui"}]
```

---

## 11. `custom_sound` — Âm thanh tuỳ chỉnh

Thêm âm thanh/nhạc nền/effect đặc biệt (TTS, file audio trong voice channel).

**Ví dụ:**
- Âm thanh khi phe Vampire ra mắt
- Nhạc nền đặc biệt khi event kích hoạt

---

## 12. `balance_patch` — Điều chỉnh cân bằng

Thay đổi weight, min_players, max_count của role hiện có mà **không thêm role mới**.

**Ví dụ:**
```python
# Trong CUSTOM_META.py hoặc address function:
from core.role_distributor import SURVIVORS_META
SURVIVORS_META["Thám Tử"]["weight"] = 8   # Tăng từ 6 lên 8
SURVIVORS_META["Cai Ngục"]["min_players"] = 8  # Hạ từ 10 xuống 8
```

Khai báo qua `addresses` để áp patch khi DLC load:
```python
"addresses": [{"module_path": "DLCs.MyMod.patches.balance", "function": "apply"}]
```

---

## 13. `seasonal` — Nội dung theo mùa

Đánh dấu DLC chỉ hoạt động trong một khoảng thời gian nhất định (lễ hội, mùa...).

**Ví dụ:** Halloween Pack, Christmas Pack, Tết Pack.

Game engine / dashboard có thể dùng tag này để ẩn/hiện DLC theo thời gian.

---

## 14. `community` — Nội dung cộng đồng

Đánh dấu DLC được tạo bởi cộng đồng (community-made), không phải official.  
Dùng để phân loại trong cửa hàng và dashboard.

---

## Bảng Tóm Tắt

| Feature | Cần thêm gì | Có trong v2.0 |
|---------|-------------|:---:|
| `new_role` | File role + `register_role()` | ✅ |
| `new_team` | `new_teams` block + `CUSTOM_META.py` | ✅ |
| `new_event` | `new_events` block + file event | ✅ |
| `new_item` | File item + address | 🔜 |
| `new_ability` | File ability + address | 🔜 |
| `new_faction` | Sub-faction trong role | 🔜 |
| `new_map` | File map + address | 🔜 |
| `new_mode` | File mode + address | 🔜 |
| `custom_win` | `check_win_condition()` trong CUSTOM_META | ✅ |
| `custom_ui` | Address + UI patch function | 🔜 |
| `custom_sound` | Address + sound function | 🔜 |
| `balance_patch` | Address + patch function | ✅ |
| `seasonal` | Tag only (logic ở game engine) | ✅ tag |
| `community` | Tag only | ✅ tag |

> ✅ Có hỗ trợ đầy đủ | 🔜 Tag đã sẵn sàng, implementation mở rộng sau
