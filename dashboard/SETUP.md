# Anomalies Dashboard v3 — Hướng dẫn Deploy

## Cấu trúc file
```
dashboard/
├── index.html      ← Frontend SPA (HTML/CSS/JS)
├── server.py       ← FastAPI backend
├── requirements.txt
├── render.yaml     ← Config deploy Render
└── SETUP.md
```

## Bước 1 — Discord Developer Portal
1. Vào https://discord.com/developers/applications
2. Mở app bot của bạn → **OAuth2** → **Redirects**
3. Thêm: `https://TÊN-APP.onrender.com/auth/callback`
4. Lưu lại **Client ID** và **Client Secret**

## Bước 2 — Render.com
1. Tạo Web Service mới, kết nối repo GitHub
2. Build command: `pip install -r dashboard/requirements.txt`
3. Start command: `uvicorn dashboard.server:app --host 0.0.0.0 --port $PORT`

## Bước 3 — Biến môi trường trên Render
| Key | Giá trị |
|-----|---------|
| `DISCORD_CLIENT_ID` | Client ID từ Discord Dev Portal |
| `DISCORD_CLIENT_SECRET` | Client Secret |
| `DISCORD_REDIRECT_URI` | `https://TÊN-APP.onrender.com/auth/callback` |
| `MONGO_URI` | MongoDB Atlas URI (`mongodb+srv://...`) |
| `BOT_OWNER_ID` | Discord ID của chủ bot (mặc định đã set trong code) |
| `SESSION_SECRET` | Tự động generate bởi Render |
| `RENDER_EXTERNAL_URL` | `https://TÊN-APP.onrender.com` |

## Biến môi trường BOT_OWNER_ID
Mặc định trong code là `1306441206296875099`.  
Nếu muốn đổi mà không sửa code, set biến `BOT_OWNER_ID` trên Render.

## MongoDB Collections dùng
- `guild_configs` — Config từng server
- `feedbacks` — Feedback người chơi
- `changelogs` — Update log
- `bans` — Danh sách ban/lobby
- `roles_catalog` — (tuỳ chọn) Vai trò tùy chỉnh

## Phân quyền
- **Người chơi thường**: Xem vai trò, gửi feedback, đọc hướng dẫn, xem update log
- **Quản lý server**: Chỉnh sửa cài đặt phòng (cần MANAGE_GUILD hoặc ADMINISTRATOR trong Discord)
- **Chủ bot**: Mọi tính năng, bypass tất cả kiểm tra

## Kết nối với bot Discord
Bot và dashboard dùng chung MongoDB. Bot dùng `config_manager.py` để
read/write `guild_configs` — dashboard đọc và sửa cùng collection đó.
Đảm bảo cả hai đều dùng cùng `MONGO_URI` và `DB_NAME = "Anomalies_DB"`.
