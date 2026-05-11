# ══════════════════════════════════════════════════════════════════
# mod.py — File metadata của DLC Pack
# DOELCES v1.0 — Anomalies Bot
#
# BẮT BUỘC: File này phải có biến DLC = {...}
# BẮT BUỘC: Folder phải có file pack.jpg / pack.png / pack.webp
#
# Hướng dẫn:
#   1. Sao chép folder này, đổi tên theo tên Mod của bạn
#   2. Chỉnh sửa thông tin bên dưới
#   3. Thêm role vào các folder tương ứng: roles/survivors/, roles/anomalies/, roles/unknown/
#   4. Đặt ảnh icon vào pack.png (đề xuất 256x256)
#
# FEATURES hợp lệ (tối đa 14):
#   new_role, new_team, new_event, new_item, new_ability, new_faction,
#   new_map, new_mode, custom_win, custom_ui, custom_sound, balance_patch,
#   seasonal, community
#
# PRICE:
#   Miễn phí:  "nope"
#   Trả phí:   {"currency": "gold", "amount": 500}
#               {"currency": "gems", "amount": 50}
# ══════════════════════════════════════════════════════════════════

DLC = {
    # ── Thông tin cơ bản ──────────────────────────────────────────
    "name": "Example Mod Pack",
    "description": "Một ví dụ DLC pack với các vai trò mới. Mô tả nội dung của bạn ở đây!",
    "version": "1.0.0",
    "author": "YourName",

    # ── Giá ────────────────────────────────────────────────────────
    # "nope"                           → miễn phí
    # {"currency": "gold", "amount": 500}  → 500 Gold
    # {"currency": "gems", "amount": 50}   → 50 Gems
    "price": {"currency": "gold", "amount": 500},

    # ── Tính năng (tối đa 14 loại) ────────────────────────────────
    "features": ["new_role", "new_team"],

    # ── Roles ─────────────────────────────────────────────────────
    # Danh sách tên file (không bao gồm .py) trong mỗi folder:
    #   roles/survivors/   → vai người sống sót
    #   roles/anomalies/   → vai dị thể
    #   roles/unknown/     → vai không rõ phe
    "roles": {
        "survivors": ["example_survivor"],  # → roles/survivors/example_survivor.py
        "anomalies": ["example_anomaly"],   # → roles/anomalies/example_anomaly.py
        "unknown":   [],
    },

    # ── Addresses ─────────────────────────────────────────────────
    # Danh sách hàm cần được gọi khi kích hoạt DLC.
    # module_path: đường dẫn module Python (dấu chấm)
    # function:    tên hàm trong module đó
    # Để trống nếu không cần:
    "addresses": [
        # {
        #     "module_path": "DLCs.ExampleMod.features.my_feature",
        #     "function":    "register",
        #     "description": "Đăng ký event custom",
        # }
    ],

    # ── Dependencies ──────────────────────────────────────────────
    # Tên các DLC khác cần được load trước (folder name):
    "requires": [],
}
