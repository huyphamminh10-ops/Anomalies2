# ==============================
# database_tidb.py — Anomalies v2.5
# Module kết nối TiDB (MySQL-compatible) để lưu Feedback & Update Log.
#
# Chức năng:
#   - generate_id()         → chuỗi ngẫu nhiên 15 ký tự (VD: 9c29t64xq9d6v40)
#   - insert_feedback()     → lưu feedback với ID 15 ký tự làm PK
#   - insert_update_log()   → lưu update log (chỉ BOT_OWNER_ID)
#   - get_feedbacks()       → lấy danh sách feedback
#   - get_update_logs()     → lấy danh sách update log
#   - reply_feedback()      → owner trả lời feedback
#   - ensure_tables()       → tạo bảng nếu chưa có (gọi lúc startup)
#
# Xử lý lỗi:
#   - Mọi truy vấn đều có try-except riêng
#   - Lỗi kết nối trả về dict {"ok": False, "error": "...", "hint": "..."}
#   - Không crash toàn bộ process khi TiDB không đến được
# ==============================

from __future__ import annotations

import os
import random
import string
from datetime import datetime, timezone
from typing import Optional

# mysql-connector-python (không phải mysqlclient)
# pip install mysql-connector-python
try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
    _HAS_CONNECTOR = True
except ImportError:
    _HAS_CONNECTOR = False
    print("[database_tidb] CẢNH BÁO: mysql-connector-python chưa được cài. "
          "Chạy: pip install mysql-connector-python")

# ── Kết nối TiDB ──────────────────────────────────────────────────
# Format: mysql://user:password@host:port/database
TIDB_URL = os.environ.get(
    "TIDB_URL",
    "mysql://pmiJpFtdc5E8WwZ.root:r0QZSVZVEINtmH39@gateway01.ap-southeast-1.prod.aws.tidbcloud.com:4000/sys"
)

BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "1306441206296875099"))

# ── Parse TIDB_URL → dict tham số ─────────────────────────────────

def _parse_tidb_url(url: str) -> dict:
    """
    Phân tích URL dạng mysql://user:pass@host:port/dbname
    thành dict tham số cho mysql.connector.connect().
    """
    try:
        # Bỏ scheme
        rest = url.replace("mysql://", "").replace("mysql+mysqlconnector://", "")
        # Tách userinfo và host
        at_idx = rest.rfind("@")
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
        else:
            hostport, database = hostpart, "sys"
        # Tách host:port
        if ":" in hostport:
            host, port_str = hostport.rsplit(":", 1)
            port = int(port_str)
        else:
            host, port = hostport, 4000
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


# ── Tạo kết nối mới (không pool — dùng create new mỗi lần) ────────

def _get_connection():
    """
    Tạo kết nối mới đến TiDB.
    TiDB Cloud yêu cầu SSL; thêm ssl_disabled=False (mặc định).
    Raise MySQLError nếu kết nối thất bại (caller tự bắt).
    """
    if not _HAS_CONNECTOR:
        raise RuntimeError("mysql-connector-python chưa được cài.")
    if not _TIDB_PARAMS:
        raise RuntimeError("TIDB_URL không hợp lệ hoặc chưa được đặt.")
    return mysql.connector.connect(
        **_TIDB_PARAMS,
        ssl_disabled=False,        # TiDB Cloud bắt buộc SSL
        connection_timeout=10,
        autocommit=True,
    )


# ── generate_id() — chuỗi ngẫu nhiên 15 ký tự ────────────────────

_ID_CHARS = string.ascii_lowercase + string.digits  # a-z 0-9

def generate_id(length: int = 15) -> str:
    """
    Sinh chuỗi ID ngẫu nhiên 15 ký tự gồm chữ thường + số.
    VD: 9c29t64xq9d6v40
    Dùng làm Primary Key trong TiDB.
    """
    return "".join(random.choices(_ID_CHARS, k=length))


# ── ensure_tables() — tạo bảng nếu chưa tồn tại ──────────────────

def ensure_tables() -> dict:
    """
    Tạo bảng feedbacks và update_logs trong TiDB nếu chưa có.
    Gọi một lần khi bot khởi động (trong on_ready hoặc startup).
    Trả về {"ok": True} hoặc {"ok": False, "error": "...", "hint": "..."}.
    """
    if not _HAS_CONNECTOR:
        return {"ok": False, "error": "mysql-connector-python chưa cài", "hint": "pip install mysql-connector-python"}

    ddl_feedbacks = """
    CREATE TABLE IF NOT EXISTS feedbacks (
        id          CHAR(15)     NOT NULL PRIMARY KEY,
        user_id     VARCHAR(30)  NOT NULL,
        username    VARCHAR(100) NOT NULL,
        avatar      TEXT,
        content     TEXT,
        images      TEXT,
        reply       TEXT,
        created_at  DATETIME     NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    ddl_update_logs = """
    CREATE TABLE IF NOT EXISTS update_logs (
        id          CHAR(15)     NOT NULL PRIMARY KEY,
        title       VARCHAR(200) NOT NULL,
        content     TEXT         NOT NULL,
        version     VARCHAR(20),
        posted_by   VARCHAR(30)  NOT NULL,
        created_at  DATETIME     NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    try:
        conn = _get_connection()
        cur  = conn.cursor()
        cur.execute(ddl_feedbacks)
        cur.execute(ddl_update_logs)
        cur.close()
        conn.close()
        print("[database_tidb] TiDB tables OK (feedbacks, update_logs).")
        return {"ok": True}
    except Exception as e:
        msg = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi ensure_tables: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ── insert_feedback() ──────────────────────────────────────────────

def insert_feedback(
    user_id:  str,
    username: str,
    avatar:   str,
    content:  str,
    images:   list[str],
) -> dict:
    """
    Lưu feedback vào TiDB.
    PK là ID 15 ký tự do generate_id() tạo.
    Trả về {"ok": True, "id": "..."} hoặc {"ok": False, "error": "...", "hint": "..."}.
    """
    if not _HAS_CONNECTOR:
        return {"ok": False, "error": "mysql-connector-python chưa cài", "hint": "pip install mysql-connector-python"}

    fb_id      = generate_id()
    images_str = ",".join(images) if images else ""
    now        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    sql = """
    INSERT INTO feedbacks (id, user_id, username, avatar, content, images, reply, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, NULL, %s)
    """
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        cur.execute(sql, (fb_id, str(user_id), username, avatar, content, images_str, now))
        cur.close()
        conn.close()
        return {"ok": True, "id": fb_id}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi insert_feedback: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ── insert_update_log() ────────────────────────────────────────────

def insert_update_log(
    user_id: str,
    title:   str,
    content: str,
    version: str = "",
) -> dict:
    """
    Lưu update log vào TiDB. Chỉ BOT_OWNER_ID mới được gọi.
    Caller phải kiểm tra quyền trước khi gọi hàm này.
    Trả về {"ok": True, "id": "..."} hoặc {"ok": False, "error": "...", "hint": "..."}.
    """
    if not _HAS_CONNECTOR:
        return {"ok": False, "error": "mysql-connector-python chưa cài", "hint": "pip install mysql-connector-python"}

    log_id = generate_id()
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    sql = """
    INSERT INTO update_logs (id, title, content, version, posted_by, created_at)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        cur.execute(sql, (log_id, title, content, version, str(user_id), now))
        cur.close()
        conn.close()
        return {"ok": True, "id": log_id}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi insert_update_log: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ── get_feedbacks() ────────────────────────────────────────────────

def get_feedbacks(limit: int = 50, offset: int = 0) -> dict:
    """
    Lấy danh sách feedback từ TiDB, mới nhất trước.
    Trả về {"ok": True, "items": [...]} hoặc {"ok": False, "error": "...", "hint": "..."}.
    """
    if not _HAS_CONNECTOR:
        return {"ok": False, "error": "mysql-connector-python chưa cài", "hint": "pip install mysql-connector-python"}

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
        return {"ok": True, "items": rows}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi get_feedbacks: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ── get_update_logs() ─────────────────────────────────────────────

def get_update_logs(limit: int = 50, offset: int = 0) -> dict:
    """
    Lấy danh sách update log từ TiDB, mới nhất trước.
    Trả về {"ok": True, "items": [...]} hoặc {"ok": False, "error": "...", "hint": "..."}.
    """
    if not _HAS_CONNECTOR:
        return {"ok": False, "error": "mysql-connector-python chưa cài", "hint": "pip install mysql-connector-python"}

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
        return {"ok": True, "items": rows}
    except Exception as e:
        msg  = str(e)
        hint = _connection_hint(msg)
        print(f"[database_tidb] Lỗi get_update_logs: {msg}")
        return {"ok": False, "error": msg, "hint": hint}


# ── reply_feedback() ──────────────────────────────────────────────

def reply_feedback(feedback_id: str, reply_text: str) -> dict:
    """
    Owner trả lời một feedback theo ID.
    Trả về {"ok": True} hoặc {"ok": False, "error": "...", "hint": "..."}.
    """
    if not _HAS_CONNECTOR:
        return {"ok": False, "error": "mysql-connector-python chưa cài", "hint": "pip install mysql-connector-python"}

    sql = "UPDATE feedbacks SET reply = %s WHERE id = %s"
    try:
        conn = _get_connection()
        cur  = conn.cursor()
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


# ── count_feedbacks() / count_update_logs() ───────────────────────

def count_feedbacks() -> int:
    """Đếm tổng số feedback. Trả 0 nếu lỗi."""
    if not _HAS_CONNECTOR:
        return 0
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM feedbacks")
        (n,) = cur.fetchone()
        cur.close()
        conn.close()
        return int(n)
    except Exception as e:
        print(f"[database_tidb] Lỗi count_feedbacks: {e}")
        return 0


def count_update_logs() -> int:
    """Đếm tổng số update log. Trả 0 nếu lỗi."""
    if not _HAS_CONNECTOR:
        return 0
    try:
        conn = _get_connection()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM update_logs")
        (n,) = cur.fetchone()
        cur.close()
        conn.close()
        return int(n)
    except Exception as e:
        print(f"[database_tidb] Lỗi count_update_logs: {e}")
        return 0


# ── Helper: gợi ý sửa lỗi kết nối ────────────────────────────────

def _connection_hint(error_msg: str) -> str:
    """
    Phân tích message lỗi và trả về gợi ý sửa.
    Giúp người dùng biết nguyên nhân thay vì thấy lỗi trắng.
    """
    msg = error_msg.lower()
    if "access denied" in msg:
        return "Sai username/password TiDB. Kiểm tra lại TIDB_URL."
    if "can't connect" in msg or "connection refused" in msg or "timed out" in msg:
        return (
            "Không kết nối được TiDB Cloud. "
            "Kiểm tra: (1) IP Whitelist trên TiDB Cloud Console, "
            "(2) Render outbound IP đã được thêm chưa, "
            "(3) TiDB_URL đúng host/port chưa."
        )
    if "unknown database" in msg:
        return "Database không tồn tại. Kiểm tra tên DB trong TIDB_URL."
    if "ssl" in msg:
        return "Lỗi SSL. TiDB Cloud yêu cầu SSL — đảm bảo ssl_disabled=False."
    if "table" in msg and "doesn't exist" in msg:
        return "Bảng chưa được tạo. Gọi ensure_tables() khi khởi động."
    return "Kiểm tra TIDB_URL, kết nối mạng và IP Whitelist trên TiDB Cloud."
