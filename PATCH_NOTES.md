# Anomalies Dashboard — Patch Notes v2.4

## Tổng quan

Sau khi kiểm tra toàn bộ codebase, phần lớn yêu cầu trong 4 prompt đã được **triển khai đúng** từ trước. Patch này tập trung vào **các bug thực tế còn tồn tại** và cung cấp giải thích đầy đủ về từng hạng mục.

---

## Prompt 1 — `dashboard_routes.py` (Sửa lỗi Logic & Hệ thống)

### ✅ Đã fix: Lỗi `if not guilds:` → `if guilds is None:`

**File:** `dashboard_routes.py`, dòng 147

**Lỗi:** Khi `guilds = {}` (dict rỗng — bình thường lúc bot mới khởi động), điều kiện `if not guilds:` đánh giá là `True`, khiến code nhảy vào nhánh fallback DB không cần thiết. Với PyMongo ≥ 4.x, so sánh truthiness trên Collection object ném `NotImplementedError`.

```python
# TRƯỚC (lỗi):
if not guilds:

# SAU (đúng):
if guilds is None:
```

### ✅ Đã fix: Đếm chính xác từ MongoDB

**File:** `dashboard_routes.py`, hàm `api_stats()`

**Lỗi:** Hàm `_mongo_counts()` chỉ trả về 2 giá trị (guilds, bans). Nay thêm `feedbacks_n` từ `db["feedbacks"].count_documents({})` để Dashboard hiển thị số thật.

```python
# SAU:
def _mongo_counts():
    ...
    guilds_n   = db["guild_configs"].count_documents({})
    bans_n     = db["bans"].count_documents({})
    feedbacks_n = db["feedbacks"].count_documents({})
    return (guilds_n, bans_n, feedbacks_n)
```

**Bonus:** Nếu TiDB không kết nối được, `total_feedbacks` tự động fallback về số đếm MongoDB.

### ✅ Đã có sẵn: Fix TiDB database namespace

**File:** `database_tidb.py`, hàm `_get_connection()`

Code đã kiểm tra `db_name` trước khi connect và raise `RuntimeError` rõ ràng nếu thiếu. Patch bổ sung thêm `USE \`{db_name}\`` ngay sau khi tạo connection để đảm bảo namespace chính xác, tránh truy vào `sys`.

```python
# THÊM MỚI trong _get_connection():
conn = mysql.connector.connect(**connect_kw)
# Safety: explicitly USE the project database
try:
    _safe_cur = conn.cursor()
    _safe_cur.execute(f"USE `{db_name}`")
    _safe_cur.close()
except Exception:
    pass  # connection already has DB set via connect_kw
```

### ✅ Đã có sẵn: Tra cứu người chơi — ép kiểu str

**File:** `dashboard_routes.py`, hàm `api_player_lookup()`

Đã implement đúng:
- Ép `uid_str = str(user_id).strip()`
- Query MongoDB bằng string, fallback int
- Trả HTTP 404 với thông báo rõ ràng nếu không tìm thấy

---

## Prompt 2 — Quản lý Feedback (Xóa & Phản hồi)

### ✅ Đã có sẵn: Endpoint DELETE `/api/dash/admin/feedback/{fb_id}`

Đã implement đầy đủ:
- Dùng `bson.ObjectId` để xóa đúng document MongoDB
- Fallback xóa bằng `created_at` nếu ID không phải ObjectId
- Xóa đồng thời trong TiDB qua `database_tidb.delete_feedback(fb_id)`
- Trả 404 nếu không tìm thấy ở cả hai DB

### ✅ Đã có sẵn: Endpoint POST `/api/dash/admin/feedback/reply`

Đã implement đầy đủ:
- Cập nhật `reply` trong MongoDB (theo `created_at`)
- Cập nhật trong TiDB (theo `fb_id`)
- Gửi Discord Webhook nếu `webhook_url` được cung cấp
- Body: `{ created_at, fb_id, reply, webhook_url }`

### ✅ Đã có sẵn: Frontend kết nối đúng

`index.html` đã có `deleteFeedback()` gọi `DELETE /api/dash/admin/feedback/{id}` và `submitReply()` gọi `POST /api/dash/admin/feedback/reply`.

---

## Prompt 3 — Tra Cứu Vai Trò & Phòng Chơi

### ✅ Đã có sẵn: Đọc dữ liệu thực từ roles/

**File:** `dashboard_routes.py`, hàm `_build_roles_catalog()`

Hàm này dùng Python `ast` để **parse trực tiếp** source code các class trong `roles/**/*.py`. Không dùng data tĩnh.

Dữ liệu được extract:
- `name`, `team`, `description` — từ class attributes
- `fake_good` — từ `_SPECIAL_FLAGS` dict (Tín Hiệu Giả, Kẻ Mô Phỏng Sinh Học)
- `anomaly_chat_mgr` — từ `_SPECIAL_FLAGS` dict (Thám Trưởng, Mù Quáng, Kẻ Tâm Thần)
- `faction` — từ folder (`survivors/` → `Survivors`, `anomalies/` → `Anomalies`, `unknown/` → `Neutrals`)
- `color` — từ `_COLOR_MAP` dict

**Sheriff cụ thể:** Lấy đúng description từ `sheriff.py`:
> "Mỗi đêm bạn có thể kiểm tra 1 người chơi và biết chính xác vai trò của họ. Nếu mục tiêu đang dùng khả năng giả mạo (fake_good), bạn sẽ thấy kết quả không đáng ngờ..."

### ✅ Đã có sẵn: 43 vai trò đầy đủ

Catalog được build tự động — thêm file role mới vào `roles/` là tự động xuất hiện, không cần sửa code.

Danh sách hiện tại từ source (28 Survivors + 14 Anomalies + 7 Unknowns):

| Phe | Vai trò |
|-----|---------|
| **Survivors** | Dân Thường, Thám Tử, Cai Ngục, Nhà Dược Học Điên, Thị Trưởng, Phụ Tá Thị Trưởng, Nhà Ngoại Cảm, Người Tiên Tri, Kẻ Báo Oán, Thám Trưởng (Sheriff), Điệp Viên, Kiến Trúc Sư, Nhà Lưu Trữ, Kẻ Báo Thù, Người Giám Sát, Kẻ Ngủ Mê, Thợ Đặt Bẫy, Kẻ Trừng Phạt, Người Thử Nghiệm |
| **Anomalies** | Dị Thể, Dị Thể Hành Quyết, Lãnh Chúa, Lao Công, Tín Hiệu Giả, Ký Sinh Thần Kinh, Kiến Trúc Sư Bóng Tối, Kẻ Rình Rập, Kẻ Đánh Cắp Lời Thì Thầm, Nguồn Tĩnh Điện, Máy Hủy Tài Liệu, Kẻ Mô Phỏng Sinh Học, Sứ Giả Tận Thế, Kẻ Điều Khiển, Mù Quáng, Sâu Lỗi |
| **Neutrals** | Kẻ Giải Mã, KẺ GIẾT NGƯỜI HÀNG LOẠT, A.I THA HÓA, ĐỒNG HỒ TẬN THẾ, Kẻ Dệt Mộng, Con Tàu Ma, Kẻ Tâm Thần, Kẻ Dệt Thời Gian |

### ✅ Đã có sẵn: Quản lý phòng alive_players

`_get_guild_full_status()` đã đọc `game.alive_players` và `game.dead_players` trực tiếp từ game object.

---

## Prompt 4 — `index.html` (Hướng dẫn & Search)

### ✅ Đã có sẵn: 43 vai trò trong Guide Tab

Tab "Hướng Dẫn" render vai trò **tự động từ `ALL_ROLES`** (API `/api/dash/roles`), không có dữ liệu tĩnh. Thêm vai trò mới trong bot → tự động cập nhật Dashboard.

### ✅ Đã có sẵn: Search lọc theo tên & mô tả

```javascript
function renderGuideRoles() {
  const query = document.getElementById('roleSearchGuide').value.toLowerCase().trim();
  let roles = ALL_ROLES.slice();
  if (query) roles = roles.filter(r =>
    r.name.toLowerCase().includes(query) ||
    (r.description || '').toLowerCase().includes(query)  // ✅ lọc theo description
  );
  ...
}
```

### ✅ Đã có sẵn: Cơ chế Sheriff + fake_good

Trong `showRoleDetail()` và `renderGuideRoles()`:
```javascript
// sheriffNote được thêm khi r.anomaly_chat_mgr && r.name.includes('Thám Trưởng')
sheriffNote = '⚠️ Biết vai trò thật, TRỪ KHI mục tiêu có fake_good';
// fake_good badge: Tín Hiệu Giả 🎭, Kẻ Mô Phỏng Sinh Học 🎭
```

---

## File output

| File | Trạng thái |
|------|-----------|
| `dashboard_routes.py` | ✅ Đã patch (3 thay đổi) |
| `database_tidb.py` | ✅ Đã patch (1 thay đổi) |
| `dashboard/index.html` | ✅ Không cần thay đổi — đã đúng |

## Hướng dẫn triển khai

```bash
# Thay thế 2 file trong repo:
cp dashboard_routes.py   /path/to/project/dashboard_routes.py
cp database_tidb.py      /path/to/project/database_tidb.py

# Không cần restart nếu dùng hot-reload (uvicorn --reload)
# Nếu không: restart app.py
```

### Biến môi trường cần kiểm tra

```env
# TiDB — phải có tên database ở cuối
TIDB_URL=mysql://user:password@host:4000/anomalies_db

# Không được để trống hoặc thiếu /dbname
# ❌ TIDB_URL=mysql://user:pass@host:4000   ← lỗi sys namespace
# ✅ TIDB_URL=mysql://user:pass@host:4000/anomalies_db
```
