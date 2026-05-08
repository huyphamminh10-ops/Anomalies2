# 🚀 Hướng Dẫn Deploy Dashboard — Anomalies

## Cấu Trúc File

```
Anomalies2/
├── dashboard/
│   ├── server.py          ← FastAPI backend (Discord OAuth2)
│   ├── index.html         ← Frontend SPA (toàn bộ UI)
│   ├── requirements.txt   ← Dependencies
│   └── render.yaml        ← Cấu hình Render
└── ... (các file bot cũ)
```

---

## Bước 1 — Tạo Discord OAuth2 App

1. Vào **https://discord.com/developers/applications**
2. Chọn app bot của bạn (hoặc tạo mới)
3. Vào tab **OAuth2 → General**
4. Sao chép **Client ID** và **Client Secret**
5. Thêm **Redirect URI**:
   ```
   https://TÊN-APP-TRÊN-RENDER.onrender.com/auth/callback
   ```
6. Lưu lại

---

## Bước 2 — Deploy lên Render

1. Vào **https://render.com** → New → Web Service
2. Connect GitHub repo chứa code Anomalies2
3. Điền thông tin:
   - **Name**: `anomalies-dashboard` (hoặc tên bạn muốn)
   - **Root Directory**: để trống (dùng root repo)
   - **Build Command**: `pip install -r dashboard/requirements.txt`
   - **Start Command**: `uvicorn dashboard.server:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free

---

## Bước 3 — Đặt Environment Variables trên Render

Vào **Environment** tab, thêm các biến sau:

| Key | Giá trị |
|-----|---------|
| `DISCORD_CLIENT_ID` | Client ID từ bước 1 |
| `DISCORD_CLIENT_SECRET` | Client Secret từ bước 1 |
| `DISCORD_REDIRECT_URI` | `https://TÊN-APP.onrender.com/auth/callback` |
| `SESSION_SECRET` | Chuỗi ngẫu nhiên dài (Render có thể tự generate) |
| `MONGO_URI` | URI MongoDB Atlas của bạn (giống bot) |

---

## Bước 4 — Kiểm Tra

Sau khi deploy xong:
- Truy cập `https://TÊN-APP.onrender.com`
- Đăng nhập bằng Discord
- Nếu Discord ID của bạn là `1306441206296875099` → sẽ tự động nhận quyền **OWNER**

---

## Tính Năng Theo Phân Quyền

### 👤 Người Chơi Thường
| Tính Năng | Mô Tả |
|-----------|-------|
| 🎭 Tra Cứu Vai Trò | Xem toàn bộ 38 vai trò với filter, search |
| 📝 Báo Lỗi | Gửi text + URL ảnh đính kèm |
| 📖 Hướng Dẫn Chơi | Chiến thuật, luật chơi chi tiết |
| ⚙️ Cài Đặt Phòng | Sửa config server (nếu là chủ/có quyền quản lý) |
| 📋 Update Log | Xem lịch sử cập nhật |

### ⚡ Chủ Bot (ID `1306441206296875099`)
| Tính Năng | Mô Tả |
|-----------|-------|
| 💬 Xem Feedback | Đọc toàn bộ feedback, phản hồi bằng nút "Phản Hồi" |
| 📢 Đăng Update | Tạo changelog mới hiển thị cho tất cả người dùng |
| 🔨 Quản Lý Ban | Ban/Lobby/Gỡ ban người chơi theo User ID |
| 🎮 Quản Lý Phòng | Xem trạng thái tất cả server, tự cập nhật 20 giây |

---

## MongoDB Collections Dùng Thêm

Dashboard tự tạo thêm 2 collections mới:

```
feedbacks     ← Lưu feedback từ người chơi
changelogs    ← Lưu các bản cập nhật
```

Các collections cũ của bot (`guild_configs`, `active_players`, `lobby_states`) được dùng chung.

---

## Giao Diện

- **Dark Mode** (mặc định): Nền đen sci-fi, accent xanh cyan
- **Light Mode**: Nền trắng xám, accent xanh dương
- Toggle nhanh bằng nút ☀️/🌙 ở góc trên phải
- Responsive mobile, sidebar có thể thu gọn

---

## Lưu Ý Bảo Mật

- `SESSION_SECRET` phải là chuỗi ngẫu nhiên mạnh — **không được để lộ**
- `DISCORD_CLIENT_SECRET` tuyệt đối bảo mật
- Dashboard chỉ cho phép sửa các field config được whitelist
- Quyền OWNER được kiểm tra server-side bằng Discord ID
