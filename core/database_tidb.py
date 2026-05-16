# ==============================
# database_tidb.py — Anomalies v3.0
# Module kết nối TiDB (MySQL-compatible) để lưu Feedback & Update Log.
#
# THAY ĐỔI v3.0:
#   - generate_tidb_id() đổi tên thành generate_id() (nhưng alias vẫn còn)
#   - generate_tidb_id() được export rõ ràng để /api/feedback dùng
#   - Thêm delete_feedback() và delete_update_log() cho admin dashboard
#   - Thêm get_feedback_by_id() để owner xem chi tiết
#   - Cải thiện _connection_hint() với nhiều pattern lỗi hơn
#   - SSL CA certificate path từ certifi (tương thích mọi môi trường)
#   - Thêm pool-like pattern: tái sử dụng connection trong cùng request
#
# Chức năng:
#   - generate_tidb_id()    → chuỗi 15 ký tự (VD: 9c29t64xq9d6v40)
#   - generate_id()         → alias của generate_tidb_id()
#   - insert_feedback()     → lưu feedback vào TiDB
#   - insert_update_log()   → lưu update log (chỉ BOT_OWNER_ID)
#   - get_feedbacks()       → lấy danh sách feedback (phân trang)
#   - get_update_logs()     → lấy danh sách update log (phân trang)
#   - get_feedback_by_id()  → lấy feedback theo ID
#   - reply_feedback()      → owner trả lời feedback
#   - delete_feedback()     → xóa feedback theo ID
#   - delete_update_log()   → xóa update log theo ID
#   - count_feedbacks()     → đếm tổng feedback
#   - count_update_logs()   → đếm tổng update log
#   - ensure_tables()       → tạo bảng nếu chưa có (gọi lúc startup)
#
# Database:
#   TiDB Cloud (mysql-connector-python)
#   URL: mysql://user:pass@host:port/database
#   Biến môi trường: TIDB_URL
# ==============================

from __future__ import annotations

import os
import random
import string
import time
import traceback
from datetime import datetime, timezone

# ── mysql-connector-python ─────────────────────────────────────────
# pip install mysql-connector-python
try:
    import mysql.connector
    _HAS_CONNECTOR = True
except ImportError:
    _HAS_CONNECTOR = False
    print("[database_tidb] CẢNH BÁO: mysql-connector-python chưa được cài.")
    print("                Chạy: pip install mysql-connector-python")

# ── SSL CA certificate (certifi) ───────────────────────────────────
try:
    import certifi
    _SSL_CA = certifi.where()
except ImportError:
    _SSL_CA = None  # TiDB vẫn kết nối được nếu không có CA cụ thể

# ══════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════

# Format: mysql://user:password@host:port/database
# Không dùng URL mặc định trong code — đặt TIDB_URL trên Render / .env.
TIDB_URL = (os.environ.get("TIDB_URL") or "").strip()

BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "1306441206296875099"))

# ══════════════════════════════════════════════════════════════════
# PARSE TIDB_URL → dict tham số kết nối
# ══════════════════════════════════════════════════════════════════

def _parse_tidb_url(url: str) -> dict:
    """
    Phân tích URL dạng mysql://user:pass@host:port/dbname
    thành dict tham số cho mysql.connector.connect().

    Hỗ trợ các format:
      mysql://user:pass@host:port/db
      mysql+mysqlconnector://user:pass@host:port/db
    """
    url = (url or "").strip()
    if not url:
        return {}
    try:
        # Bỏ scheme
        rest = url
        for prefix in ("mysql+mysqlconnector://", "mysql://"):
            if rest.startswith(prefix):
                rest = rest[len(prefix):]
                break

        # Tách userinfo@hostpart
        at_idx   = rest.rfind("@")
        userinfo = rest[:at_idx]
        hostpart = rest[at_idx + 1:]

        # Tách user:password
        if ":" in userinfo:
            user, password = userinfo.split(":", 1)
        else:
            user, password = userinfo, ""

        # Tách host:port/database
        if "/" in hostpart:
            hostport, database = hostpart.rsplit("/", 1)
            # Bỏ query string nếu có (VD: ?ssl_mode=REQUIRED)
            database = database.split("?")[0]
        else:
            # Nếu URL không có database name, cảnh báo ngay — namespace "sys" là system schema của TiDB
            # và không chứa bảng user. Luôn chỉ định DB trong TIDB_URL.
            print("[database_tidb] CẢNH BÁO: TIDB_URL thiếu tên database. "
                  "Thêm /dbname vào cuối URL: mysql://user:pass@host:4000/your_db")
            hostport, database = hostpart, ""

        # Tách host:port
        if ":" in hostport:
            host, port_str = hostport.rsplit(":", 1)
            port = int(port_str)
        else:
            host, port = hostport, 4000  # TiDB mặc định port 4000

        return {
            "host":     host,
            "port":     port,
            "user":     user,
            "password": password,
            "database": database,
        }
    except Exception as e:
        print(f"[database_tidb] Lỗi parse TIDB_URL: {e}")
        return {}


_TIDB_PARAMS = _parse_tidb_url(TIDB_URL)

if _TIDB_PARAMS:
    print(f"[database_tidb] TiDB host={_TIDB_PARAMS.get('host')} "
          f"port={_TIDB_PARAMS.get('port')} db={_TIDB_PARAMS.get('database')}")
elif not TIDB_URL:
    print("[database_tidb] TIDB_URL trống — tính năng feedback/changelog trên TiDB sẽ không dùng được.")
else:
    print("[database_tidb] CẢNH BÁO: Không parse được TIDB_URL!")

# ══════════════════════════════════════════════════════════════════
# CONNECTION
# ══════════════════════════════════════════════════════════════════

_TIDB_CONNECT_RETRIES = 5
_TIDB_RETRY_DELAY_SEC = 5


def _classify_mysql_connect_error(exc: BaseException) -> str:
    msg = str(exc).lower()
    if "access denied" in msg or "1045" in msg:
        return "xác thực MySQL/TiDB (sai user/password)"
    if "timed out" in msg or "timeout" in msg:
        return "timeout"
    if "can't connect" in msg or "connection refused" in msg or "2003" in msg:
        return "không tới được server (host/port/firewall/IP whitelist)"
    if "ssl" in msg or "certificate" in msg or "tls" in msg:
        return "SSL/TLS"
    if "unknown database" in msg:
        return "database không tồn tại"
    return type(exc).__name__


def _get_connection():
    """
    Tạo kết nối mới đến TiDB Cloud, có retry (5 lần, cách nhau 5s).

    TiDB Cloud bắt buộc SSL. Dùng certifi CA nếu có,
    không thì để mysql.connector tự xử lý.
    Raise Exception nếu kết nối thất bại sau hết số lần thử.
    """
    if not _HAS_CONNECTOR:
        raise RuntimeError("mysql-connector-python chưa được cài. "
                           "Chạy: pip install mysql-connector-python")
    if not _TIDB_PARAMS:
        raise RuntimeError(
            "TIDB_URL chưa được đặt hoặc không hợp lệ. "
            "Trên Render thêm biến TIDB_URL dạng mysql://user:pass@host:4000/dbname"
        )

    ssl_args = {}
    if _SSL_CA:
        ssl_args["ssl_ca"] = _SSL_CA

    # Kiểm tra database name không trống — tránh query vào namespace sys
    db_name = _TIDB_PARAMS.get("database", "")
    if not db_name:
        raise RuntimeError(
            "TIDB_URL thiếu tên database. "
            "Format đúng: mysql://user:pass@host:4000/your_database_name "
            "(không dùng 'sys' — đó là system schema của TiDB)"
        )

    connect_kw = {
        **_TIDB_PARAMS,
        "ssl_disabled": False,
        "connection_timeout": 10,
        "autocommit": True,
        **ssl_args,
    }

    last_exc: BaseException | None = None
    for attempt in range(1, _TIDB_CONNECT_RETRIES + 1):
        try:
            conn = mysql.connector.connect(**connect_kw)
            # Safety: explicitly USE the project database to avoid falling into sys schema
            try:
                _safe_cur = conn.cursor()
                _safe_cur.execute(f"USE `{db_name}`")
                _safe_cur.close()
            except Exception:
                pass  # connection already has DB set via connect_kw
            if attempt > 1:
                print(f"[database_tidb] ✓ Kết nối TiDB thành công sau {attempt} lần thử.")
            return conn
        except Exception as e:
            last_exc = e
            kind = _classify_mysql_connect_error(e)
            hint = _connection_hint(str(e))
            print(
                f"[database_tidb] ✗ Lần {attempt}/{_TIDB_CONNECT_RETRIES}: [{kind}] {e}\n"
                f"  Gợi ý: {hint}"
            )
            print(traceback.format_exc())
            if attempt < _TIDB_CONNECT_RETRIES:
                print(f"[database_tidb] Chờ {_TIDB_RETRY_DELAY_SEC}s rồi thử lại kết nối TiDB...")
                time.sleep(_TIDB_RETRY_DELAY_SEC)

    assert last_exc is not None
    raise last_exc


# ══════════════════════════════════════════════════════════════════
# GENERATE ID — Chuỗi 15 ký tự (chữ thường + số)
# ══════════════════════════════════════════════════════════════════

_ID_CHARS = string.ascii_lowercase + string.digits  # a-z 0-9

def generate_tidb_id(length: int = 15) -> str:
    """
    Sinh chuỗi ID ngẫu nhiên 15 ký tự gồm chữ thường + số.
    Ví dụ: 9c29t64xq9d6v40

    Dùng làm Primary Key trong TiDB cho feedback và update log.
    Không dùng UUID để giữ ID ngắn gọn và dễ đọc.
    """
    return "".join(random.choices(_ID_CHARS, k=length))


# Alias để tương thích với code cũ
def generate_id(length: int = 15) -> str:
    """Alias của generate_tidb_id(). Dùng generate_tidb_id() để rõ nghĩa hơn."""
    return generate_tidb_id(length)


# ══════════════════════════════════════════════════════════════════
# ENSURE TABLES — Tạo bảng khi startup
# ══════════════════════════════════════════════════════════════════

def ensure_tables() -> dict:
    """
    Tạo bảng feedbacks và update_logs trong TiDB nếu chưa có.
    Gọi một lần trong on_ready hoặc startup event.

    Trả về:
      {"ok": True}
      {"ok": False, "error": "...", "hint": "..."}
    """
    if not _HAS_CONNECTOR:
        return {
            "ok": False,
            "error": "mysql-connector-python chưa cài",
            "hint": "pip install mysql-connector-python",
        }

    if not _TIDB_PARAMS:
        return {
            "ok": False,
            "error": "TIDB_URL chưa được đặt hoặc không parse được",
            "hint": "Trên Render: Environment → TIDB_URL = mysql://user:pass@host:4000/db",
        }

    ddl_feedbacks = """
    CREATE TABLE IF NOT EXISTS feedbacks (
        id          CHAR(15)     NOT NULL,
        user_id     VARCHAR(30)  NOT NULL,
        username    VARCHAR(100) NOT NULL,
        avatar      TEXT,
        content     TEXT,
        images      TEXT,
        reply       TEXT,
        created_at  DATETIME     NOT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    ddl_update_logs = """
    CREATE TABLE IF NOT EXISTS update_logs (
        id          CHAR(15)     NOT NULL,
        title       VARCHAR(200) NOT NULL,
        content     TEXT         NOT NULL,
        version     VARCHAR(20),
        posted_by   VARCHAR(30)  NOT NULL,
        created_at  DATETIME     NOT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    try:
        conn = _get_connection()
        cur  = conn.cursor()
        _db_name = _TIDB_PARAMS.get("database", "")
        if _db_name:
            cur.execute(f"USE `{_db_name}`")
        cur.execute(ddl_feedbacks)
        cur.execute(ddl_update_logs)
        cur.close()
        conn.close()
        print("[database_tidb] ✓ TiDB tables OK (feedbacks, update_logs).")
        return {"ok": True}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] ✗ ensure_tables lỗi: {msg}")
        if hint:
            print(f"[database_tidb]   Gợi ý: {hint}")
        return {"ok": False, "error": msg, "hint": hint}


# ══════════════════════════════════════════════════════════════════
# INSERT FEEDBACK
# ══════════════════════════════════════════════════════════════════

def insert_feedback(
    user_id:  str,
    username: str,
    avatar:   str,
    content:  str,
    images:   list[str],
) -> dict:
    """
    Lưu feedback vào TiDB.
    PK là ID 15 ký tự được tạo bởi generate_tidb_id().

    POST /api/feedback gọi hàm này và trả về ID cho client xác nhận.

    Trả về:
      {"ok": True, "id": "abc123def456xyz"}
      {"ok": False, "error": "...", "hint": "..."}
    """
    if not _HAS_CONNECTOR:
        return {
            "ok": False,
            "error": "mysql-connector-python chưa cài",
            "hint": "pip install mysql-connector-python",
        }

    fb_id      = generate_tidb_id()
    images_str = ",".join(str(i) for i in images) if images else ""
    now        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    sql = """
    INSERT INTO feedbacks (id, user_id, username, avatar, content, images, reply, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, NULL, %s)
    """
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        _db_name = _TIDB_PARAMS.get("database", "")
        if _db_name:
            cur.execute(f"USE `{_db_name}`")
        cur.execute(sql, (fb_id, str(user_id), username, avatar, content, images_str, now))
        cur.close()
        conn.close()
        print(f"[database_tidb] Feedback lưu thành công. ID={fb_id}")
        return {"ok": True, "id": fb_id}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi insert_feedback: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ══════════════════════════════════════════════════════════════════
# INSERT UPDATE LOG
# ══════════════════════════════════════════════════════════════════

def insert_update_log(
    user_id: str,
    title:   str,
    content: str,
    version: str = "",
) -> dict:
    """
    Lưu update log vào TiDB.
    Caller phải kiểm tra user_id == BOT_OWNER_ID trước khi gọi.

    Trả về:
      {"ok": True, "id": "abc123def456xyz"}
      {"ok": False, "error": "...", "hint": "..."}
    """
    if not _HAS_CONNECTOR:
        return {
            "ok": False,
            "error": "mysql-connector-python chưa cài",
            "hint": "pip install mysql-connector-python",
        }

    log_id = generate_tidb_id()
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    sql = """
    INSERT INTO update_logs (id, title, content, version, posted_by, created_at)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        _db_name = _TIDB_PARAMS.get("database", "")
        if _db_name:
            cur.execute(f"USE `{_db_name}`")
        cur.execute(sql, (log_id, title, content, version, str(user_id), now))
        cur.close()
        conn.close()
        print(f"[database_tidb] Update log lưu thành công. ID={log_id}")
        return {"ok": True, "id": log_id}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi insert_update_log: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ══════════════════════════════════════════════════════════════════
# GET FEEDBACKS
# ══════════════════════════════════════════════════════════════════

def get_feedbacks(limit: int = 50, offset: int = 0) -> dict:
    """
    Lấy danh sách feedback từ TiDB, mới nhất trước.

    Trả về:
      {"ok": True, "items": [...], "total": N}
      {"ok": False, "error": "...", "hint": "..."}
    """
    if not _HAS_CONNECTOR:
        return {
            "ok": False,
            "error": "mysql-connector-python chưa cài",
            "hint": "pip install mysql-connector-python",
        }

    sql = """
    SELECT id, user_id, username, avatar, content, images, reply, created_at
    FROM feedbacks
    ORDER BY created_at DESC
    LIMIT %s OFFSET %s
    """
    try:
        conn = _get_connection()
        cur  = conn.cursor(dictionary=True)
        cur.execute(sql, (limit, offset))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Chuyển images string → list
        for row in rows:
            img = row.get("images") or ""
            row["images"] = [i for i in img.split(",") if i]
            if isinstance(row.get("created_at"), datetime):
                row["created_at"] = row["created_at"].isoformat()

        return {"ok": True, "items": rows, "total": len(rows)}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi get_feedbacks: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ══════════════════════════════════════════════════════════════════
# GET UPDATE LOGS
# ══════════════════════════════════════════════════════════════════

def get_update_logs(limit: int = 50, offset: int = 0) -> dict:
    """
    Lấy danh sách update log từ TiDB, mới nhất trước.

    Trả về:
      {"ok": True, "items": [...], "total": N}
      {"ok": False, "error": "...", "hint": "..."}
    """
    if not _HAS_CONNECTOR:
        return {
            "ok": False,
            "error": "mysql-connector-python chưa cài",
            "hint": "pip install mysql-connector-python",
        }

    sql = """
    SELECT id, title, content, version, posted_by, created_at
    FROM update_logs
    ORDER BY created_at DESC
    LIMIT %s OFFSET %s
    """
    try:
        conn = _get_connection()
        cur  = conn.cursor(dictionary=True)
        cur.execute(sql, (limit, offset))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        for row in rows:
            if isinstance(row.get("created_at"), datetime):
                row["created_at"] = row["created_at"].isoformat()

        return {"ok": True, "items": rows, "total": len(rows)}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi get_update_logs: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ══════════════════════════════════════════════════════════════════
# GET FEEDBACK BY ID
# ══════════════════════════════════════════════════════════════════

def get_feedback_by_id(feedback_id: str) -> dict:
    """
    Lấy một feedback theo ID 15 ký tự.

    Trả về:
      {"ok": True, "item": {...}}
      {"ok": False, "error": "Không tìm thấy"}
    """
    if not _HAS_CONNECTOR:
        return {"ok": False, "error": "mysql-connector-python chưa cài"}

    sql = """
    SELECT id, user_id, username, avatar, content, images, reply, created_at
    FROM feedbacks
    WHERE id = %s
    """
    try:
        conn = _get_connection()
        cur  = conn.cursor(dictionary=True)
        cur.execute(sql, (feedback_id,))
        row  = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return {"ok": False, "error": f"Không tìm thấy feedback id={feedback_id}"}

        img = row.get("images") or ""
        row["images"] = [i for i in img.split(",") if i]
        if isinstance(row.get("created_at"), datetime):
            row["created_at"] = row["created_at"].isoformat()

        return {"ok": True, "item": row}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi get_feedback_by_id: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ══════════════════════════════════════════════════════════════════
# REPLY FEEDBACK
# ══════════════════════════════════════════════════════════════════

def reply_feedback(feedback_id: str, reply_text: str) -> dict:
    """
    Owner trả lời một feedback theo ID 15 ký tự.
    Cột reply được cập nhật trong TiDB.

    Trả về:
      {"ok": True}
      {"ok": False, "error": "..."}
    """
    if not _HAS_CONNECTOR:
        return {"ok": False, "error": "mysql-connector-python chưa cài"}

    sql = "UPDATE feedbacks SET reply = %s WHERE id = %s"
    try:
        conn     = _get_connection()
        cur      = conn.cursor()
        cur.execute(sql, (reply_text, feedback_id))
        affected = cur.rowcount
        cur.close()
        conn.close()

        if affected == 0:
            return {"ok": False, "error": f"Không tìm thấy feedback id={feedback_id}"}
        return {"ok": True}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi reply_feedback: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ══════════════════════════════════════════════════════════════════
# DELETE FEEDBACK / UPDATE LOG
# ══════════════════════════════════════════════════════════════════

def delete_feedback(feedback_id: str) -> dict:
    """
    Xóa một feedback theo ID. Chỉ BOT_OWNER_ID mới được gọi (caller kiểm tra).

    Trả về:
      {"ok": True}
      {"ok": False, "error": "..."}
    """
    if not _HAS_CONNECTOR:
        return {"ok": False, "error": "mysql-connector-python chưa cài"}

    try:
        conn     = _get_connection()
        cur      = conn.cursor()
        cur.execute("DELETE FROM feedbacks WHERE id = %s", (feedback_id,))
        affected = cur.rowcount
        cur.close()
        conn.close()

        if affected == 0:
            return {"ok": False, "error": f"Không tìm thấy feedback id={feedback_id}"}
        return {"ok": True}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi delete_feedback: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


def delete_update_log(log_id: str) -> dict:
    """
    Xóa một update log theo ID. Chỉ BOT_OWNER_ID mới được gọi (caller kiểm tra).

    Trả về:
      {"ok": True}
      {"ok": False, "error": "..."}
    """
    if not _HAS_CONNECTOR:
        return {"ok": False, "error": "mysql-connector-python chưa cài"}

    try:
        conn     = _get_connection()
        cur      = conn.cursor()
        cur.execute("DELETE FROM update_logs WHERE id = %s", (log_id,))
        affected = cur.rowcount
        cur.close()
        conn.close()

        if affected == 0:
            return {"ok": False, "error": f"Không tìm thấy update log id={log_id}"}
        return {"ok": True}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi delete_update_log: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ══════════════════════════════════════════════════════════════════
# COUNT
# ══════════════════════════════════════════════════════════════════

def count_feedbacks() -> int:
    """
    Đếm tổng số feedback. Trả 0 nếu lỗi.
    Xử lý riêng lỗi 'Table doesn't exist' để tránh crash khi bảng chưa được tạo.
    """
    if not _HAS_CONNECTOR:
        return 0
    if not _TIDB_PARAMS or not _TIDB_PARAMS.get("database"):
        return 0
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        _db_name = _TIDB_PARAMS.get("database", "")
        if _db_name:
            cur.execute(f"USE `{_db_name}`")
        cur.execute("SELECT COUNT(*) FROM feedbacks")
        (n,) = cur.fetchone()
        cur.close()
        conn.close()
        return int(n)
    except Exception as e:
        msg = str(e).lower()
        if "doesn't exist" in msg or "not found" in msg or "1146" in msg:
            # Bảng chưa tồn tại — gọi ensure_tables() khi startup
            print("[database_tidb] Bảng 'feedbacks' chưa tồn tại. Gọi ensure_tables() khi khởi động.")
        else:
            print(f"[database_tidb] Lỗi count_feedbacks: {e}")
        return 0


def count_update_logs() -> int:
    """
    Đếm tổng số update log. Trả 0 nếu lỗi.
    Xử lý riêng lỗi 'Table doesn't exist' để tránh crash khi bảng chưa được tạo.
    """
    if not _HAS_CONNECTOR:
        return 0
    if not _TIDB_PARAMS or not _TIDB_PARAMS.get("database"):
        return 0
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        _db_name = _TIDB_PARAMS.get("database", "")
        if _db_name:
            cur.execute(f"USE `{_db_name}`")
        cur.execute("SELECT COUNT(*) FROM update_logs")
        (n,) = cur.fetchone()
        cur.close()
        conn.close()
        return int(n)
    except Exception as e:
        msg = str(e).lower()
        if "doesn't exist" in msg or "not found" in msg or "1146" in msg:
            print("[database_tidb] Bảng 'update_logs' chưa tồn tại. Gọi ensure_tables() khi khởi động.")
        else:
            print(f"[database_tidb] Lỗi count_update_logs: {e}")
        return 0


# ══════════════════════════════════════════════════════════════════
# CONNECTION HINT — Gợi ý sửa lỗi kết nối
# ══════════════════════════════════════════════════════════════════

def _connection_hint(error_msg: str) -> str:
    """
    Phân tích message lỗi và trả về gợi ý sửa bằng tiếng Việt.
    Giúp debug nhanh thay vì thấy traceback trắng.
    """
    msg = error_msg.lower()

    if "access denied" in msg:
        return ("Sai username/password TiDB. "
                "Kiểm tra TIDB_URL: mysql://user:pass@host:port/db")

    if "can't connect" in msg or "connection refused" in msg:
        return ("Không kết nối được TiDB Cloud. "
                "Kiểm tra: (1) host/port trong TIDB_URL đúng chưa, "
                "(2) IP Whitelist trên TiDB Cloud Console đã thêm IP Render chưa.")

    if "timed out" in msg or "timeout" in msg:
        return ("Kết nối TiDB bị timeout. "
                "Kiểm tra: (1) IP Whitelist trên TiDB Cloud, "
                "(2) Render outbound IP đã được thêm chưa.")

    if "unknown database" in msg or "unknown db" in msg:
        return ("Database không tồn tại. "
                "Kiểm tra tên DB trong TIDB_URL (phần sau dấu / cuối cùng).")

    if "ssl" in msg or "certificate" in msg:
        return ("Lỗi SSL/TLS. TiDB Cloud bắt buộc SSL. "
                "Đảm bảo ssl_disabled=False và certifi đã được cài.")

    if "table" in msg and ("doesn't exist" in msg or "not found" in msg or "1146" in msg):
        db = _TIDB_PARAMS.get("database", "?") if _TIDB_PARAMS else "?"
        return (
            f"Bảng chưa tồn tại trong DB '{db}'. "
            "Gọi ensure_tables() khi bot khởi động. "
            "Nếu DB là 'sys', đó là system schema — "
            "chỉ định đúng database trong TIDB_URL: mysql://user:pass@host:4000/your_db"
        )

    if "max_connections" in msg or "too many connections" in msg:
        return ("TiDB đã đạt giới hạn kết nối. "
                "Đóng kết nối sau mỗi query (conn.close()) để tránh rò rỉ.")

    if "lost connection" in msg or "server has gone away" in msg:
        return "Kết nối TiDB bị ngắt. App sẽ tự tạo kết nối mới ở lần query tiếp theo."

    if "2003" in msg:
        return ("MySQL Error 2003: Không kết nối được đến server. "
                "Kiểm tra host, port và IP Whitelist trên TiDB Cloud.")

    if "1045" in msg:
        return "MySQL Error 1045: Access denied. Kiểm tra lại username và password."

    return ("Kiểm tra TIDB_URL, kết nối mạng và IP Whitelist trên TiDB Cloud Console. "
            "URL format: mysql://user:pass@gateway01.ap-southeast-1.prod.aws.tidbcloud.com:4000/sys")
