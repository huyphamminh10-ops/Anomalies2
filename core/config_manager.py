
# ==============================
# config_manager.py — Anomalies v2.4 (Fixed for Render)
#
# FIX v2.4:
#   - Đọc URI theo thứ tự: MONGO_URI → MONGODB_URI → DATABASE_URL (chỉ nếu là mongodb:// / mongodb+srv://)
#   - Báo lỗi rõ ràng nếu thiếu URI MongoDB (Render thường đặt DATABASE_URL cho Postgres — không dùng nhầm)
#   - Retry kết nối: tối đa 5 lần, cách nhau 5 giây, kèm phân loại lỗi (timeout / xác thực / khác)
#
# FIX v2.3:
#   - Thêm tlsAllowInvalidCertificates=True để tránh lỗi SSL cert trên Render
#   - Thêm traceback.format_exc() để log lỗi chi tiết vào console
#   - Đảm bảo _client được reset về None khi kết nối thất bại (tránh zombie client)
#   - Tương thích hoàn toàn với code cũ (không đổi API)
# ==============================

import os
import re
import ssl
import time
import traceback
import certifi
from pymongo import MongoClient
from pymongo.errors import PyMongoError, ConnectionFailure, ServerSelectionTimeoutError, OperationFailure

# ── Kết nối MongoDB ────────────────────────────────────────────────
_CONNECT_RETRIES = 5
_CONNECT_RETRY_DELAY_SEC = 5
# ── Cache TTL: 30s — đủ fresh cho bot, tránh hammering MongoDB ────
_CACHE_TTL_SEC = 30.0


def _resolve_mongo_uri() -> str:
    """
    Render / các PaaS đôi khi chỉ cung cấp DATABASE_URL (Postgres) hoặc tên khác.
    Chỉ chấp nhận DATABASE_URL nếu rõ ràng là MongoDB.
    """
    for key in ("MONGO_URI", "MONGODB_URI"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    du = (os.environ.get("DATABASE_URL") or "").strip()
    if du.startswith(("mongodb://", "mongodb+srv://")):
        return du
    return ""


MONGO_URI = _resolve_mongo_uri()

if not MONGO_URI:
    print(
        "[config_manager] LỖI CẤU HÌNH: Chưa có URI MongoDB.\n"
        "  → Trên Render, thêm Environment:\n"
        "     MONGO_URI=mongodb+srv://user:pass@cluster... (khuyến nghị)\n"
        "     hoặc MONGODB_URI=...\n"
        "     hoặc DATABASE_URL=... chỉ khi giá trị bắt đầu bằng mongodb:// hoặc mongodb+srv://\n"
        "  → Nếu bạn dùng PostgreSQL trên Render, biến DATABASE_URL đó KHÔNG dùng được cho app này;\n"
        "     cần MongoDB Atlas (hoặc URI Mongo tương đương)."
    )
else:
    # Log URI ẩn password để debug (chỉ hiện scheme + host)
    try:
        from urllib.parse import urlparse
        _parsed = urlparse(MONGO_URI)
        _src = "MONGO_URI/MONGODB_URI/DATABASE_URL(mongo)"
        print(f"[config_manager] MongoDB URI ({_src}): {_parsed.scheme}://{_parsed.hostname}/...")
    except Exception:
        print("[config_manager] MongoDB URI đã được đặt (không parse được URI).")


def _classify_mongo_connect_error(exc: BaseException) -> str:
    """Nhãn ngắn cho log — phân biệt timeout, xác thực, mạng."""
    msg = str(exc).lower()
    if isinstance(exc, ServerSelectionTimeoutError) or "serverselectiontimeout" in msg:
        return "timeout/lựa chọn server (Atlas IP whitelist, DNS, hoặc cluster đang sleep)"
    if isinstance(exc, ConnectionFailure):
        if "timed out" in msg or "timeout" in msg:
            return "timeout kết nối TCP/TLS"
        if "authentication failed" in msg or "bad auth" in msg:
            return "xác thực MongoDB (sai user/password hoặc user chưa có quyền)"
        return "lỗi kết nối mạng/TLS"
    if isinstance(exc, OperationFailure) and "authentication" in msg:
        return "xác thực MongoDB"
    if "ssl" in msg or "tls" in msg or "certificate" in msg:
        return "SSL/TLS hoặc chứng chỉ"
    return f"{type(exc).__name__}"

DB_NAME = "Anomalies_DB"

_client = None
_client_last_ping: float = 0.0
_CLIENT_PING_INTERVAL = 60.0  # ping MongoDB tối đa 1 lần/phút để tránh overhead

# ── Cache RAM với timestamp để invalidate ──────────────────────────
# Cấu trúc: { guild_id: {"data": dict, "last_updated": float} }
_config_cache: dict = {}


def _get_db():
    """Trả về database instance, tạo kết nối nếu chưa có (lazy singleton).
    Optimized: ping MongoDB tối đa mỗi 60s thay vì mỗi lần gọi.
    """
    global _client, _client_last_ping
    now = time.time()

    if _client is not None:
        # Chỉ ping nếu đã qua interval — tránh overhead mỗi DB call
        if now - _client_last_ping > _CLIENT_PING_INTERVAL:
            try:
                _client.admin.command("ping")
                _client_last_ping = now
            except Exception:
                print("[config_manager] Client hiện tại đã mất kết nối — tạo lại.")
                try:
                    _client.close()
                except Exception:
                    pass
                _client = None

    if _client is None:
        if not MONGO_URI:
            print("[config_manager] Không có URI MongoDB — bỏ qua kết nối (xem log LỖI CẤU HÌNH ở trên).")
            return None
        last_err: BaseException | None = None
        for attempt in range(1, _CONNECT_RETRIES + 1):
            try:
                print(f"[config_manager] Đang kết nối MongoDB (lần {attempt}/{_CONNECT_RETRIES})...")
                _client = MongoClient(
                    MONGO_URI,
                    serverSelectionTimeoutMS=8000,   # 8s để Atlas cold-start kịp phản hồi
                    connectTimeoutMS=15000,
                    socketTimeoutMS=30000,
                    # ── FIX SSL cho Render ──────────────────────────────
                    tls=True,
                    tlsAllowInvalidCertificates=True,
                    # ────────────────────────────────────────────────────
                    retryWrites=True,
                    w="majority",
                )
                _client.admin.command("ping")
                _client_last_ping = time.time()
                if attempt > 1:
                    print(f"[config_manager] ✓ MongoDB kết nối thành công sau {attempt} lần thử.")
                else:
                    print("[config_manager] ✓ MongoDB kết nối thành công.")
                last_err = None
                break
            except (ConnectionFailure, ServerSelectionTimeoutError) as e:
                last_err = e
                kind = _classify_mongo_connect_error(e)
                print(f"[config_manager] ✗ Lần {attempt}/{_CONNECT_RETRIES}: [{kind}] {e}")
                print(traceback.format_exc())
                _client = None
                if attempt < _CONNECT_RETRIES:
                    print(f"[config_manager] Chờ {_CONNECT_RETRY_DELAY_SEC}s rồi thử lại...")
                    time.sleep(_CONNECT_RETRY_DELAY_SEC)
            except Exception as e:
                last_err = e
                kind = _classify_mongo_connect_error(e)
                print(f"[config_manager] ✗ Lần {attempt}/{_CONNECT_RETRIES}: [{kind}] {e}")
                print(traceback.format_exc())
                _client = None
                if attempt < _CONNECT_RETRIES:
                    print(f"[config_manager] Chờ {_CONNECT_RETRY_DELAY_SEC}s rồi thử lại...")
                    time.sleep(_CONNECT_RETRY_DELAY_SEC)

        if last_err is not None and _client is None:
            print(
                "[config_manager] ✗ Hết số lần thử MongoDB.\n"
                "  Kiểm tra: MONGO_URI / Atlas Network Access (0.0.0.0/0 hoặc IP outbound Render),\n"
                "  user/password trong URI, và database user có quyền trên Anomalies_DB."
            )
            return None

    try:
        return _client[DB_NAME]
    except Exception as e:
        print(f"[config_manager] Lỗi lấy database '{DB_NAME}': {e}")
        print(traceback.format_exc())
        return None


def _guild_configs():
    db = _get_db()
    return db["guild_configs"] if db is not None else None


def _active_players():
    db = _get_db()
    return db["active_players"] if db is not None else None


def _lobby_states():
    db = _get_db()
    return db["lobby_states"] if db is not None else None


# ── Utility ────────────────────────────────────────────────────────

def sanitize_name(name: str) -> str:
    """Giữ lại để tương thích với code cũ."""
    name = name.strip()
    name = re.sub(r'[^\w\s\-]', '', name, flags=re.UNICODE)
    name = re.sub(r'\s+', '_', name).strip('_')
    return name[:40] if name else "server"


def default_config() -> dict:
    return {
        "text_channel_id":          None,
        "voice_channel_id":         None,
        "dead_role_id":             None,
        "alive_role_id":            None,
        "max_players":              65,
        "min_players":              5,
        "countdown_time":           200,
        "allow_chat":               False,
        "mute_dead":                True,
        "no_remove_roles":          False,
        "music":                    True,
        "skip_discussion":          False,
        "day_time":                 90,
        "vote_time":                30,
        "skip_discussion_delay":    30,
        "status":                   None,
        # Super Gamemodes (mặc định tắt)
        "super_gamemodes_enabled":  False,
    }


# ── Guild Config ───────────────────────────────────────────────────

def load_guild_config(guild_id, guild_name=None) -> dict:
    """Tải config của guild từ MongoDB.
    Optimized: TTL cache 30s — tránh DB roundtrip mỗi lần đọc config trong game loop.
    Vẫn force-reload nếu DB có last_updated mới hơn (Dashboard sửa config).
    """
    gid = str(guild_id)
    now = time.time()

    # Fast path: cache còn trong TTL → trả ngay không cần DB
    cached = _config_cache.get(gid)
    if cached and (now - cached.get("fetched_at", 0)) < _CACHE_TTL_SEC:
        return dict(cached["data"])

    col = _guild_configs()
    if col is None:
        return default_config()
    try:
        doc = col.find_one({"guild_id": gid})
        if doc is None:
            return default_config()

        db_last_updated = doc.get("last_updated", 0)

        # Nếu cache có cùng last_updated → không cần rebuild dict
        if cached and cached.get("last_updated", -1) == db_last_updated:
            cached["fetched_at"] = now  # refresh TTL
            return dict(cached["data"])

        doc.pop("_id", None)
        doc.pop("guild_id", None)
        doc.pop("guild_name", None)
        doc.pop("last_updated", None)
        cfg = default_config()
        cfg.update(doc)

        _config_cache[gid] = {
            "data": dict(cfg),
            "last_updated": db_last_updated,
            "fetched_at": now,
        }
        return cfg
    except PyMongoError as e:
        print(f"[config_manager] Lỗi load_guild_config({guild_id}): {e}")
        print(traceback.format_exc())
        return default_config()


def save_guild_config(guild_id, data: dict, guild_name=None):
    """Lưu config của guild vào MongoDB (upsert).
    Optimized: cập nhật cache RAM ngay sau khi save — tránh DB read ngay sau write.
    """
    gid = str(guild_id)
    col = _guild_configs()
    if col is None:
        return
    payload = dict(data)
    payload["guild_id"]     = gid
    payload["guild_name"]   = guild_name or ""
    ts = time.time()
    payload["last_updated"] = ts
    try:
        col.update_one(
            {"guild_id": gid},
            {"$set": payload},
            upsert=True
        )
        # Invalidate cache sau khi write
        _config_cache.pop(gid, None)
    except PyMongoError as e:
        print(f"[config_manager] Lỗi save_guild_config({guild_id}): {e}")
        print(traceback.format_exc())


def load_all_configs() -> dict:
    """Trả về dict {guild_id: config} cho tất cả guild đã có config."""
    result = {}
    col = _guild_configs()
    if col is None:
        print("[config_manager] load_all_configs: DB chưa kết nối, trả về dict rỗng.")
        return result
    try:
        for doc in col.find({}):
            gid = doc.get("guild_id")
            if not gid:
                continue
            gid = str(gid)
            doc.pop("_id", None)
            doc.pop("guild_id", None)
            doc.pop("guild_name", None)
            doc.pop("last_updated", None)
            cfg = default_config()
            cfg.update(doc)
            result[gid] = cfg
    except PyMongoError as e:
        print(f"[config_manager] Lỗi load_all_configs: {e}")
        print(traceback.format_exc())
    return result


# ── Trạng thái ingame ──────────────────────────────────────────────

def set_guild_status(guild_id: str, status) -> None:
    """Đặt trạng thái ingame vào MongoDB (upsert)."""
    gid = str(guild_id)
    col = _guild_configs()
    if col is None:
        return
    try:
        if status is None:
            col.update_one(
                {"guild_id": gid},
                {"$unset": {"status": ""}, "$set": {"guild_id": gid, "last_updated": time.time()}},
                upsert=True
            )
        else:
            col.update_one(
                {"guild_id": gid},
                {"$set": {"guild_id": gid, "status": status, "last_updated": time.time()}},
                upsert=True
            )
        _config_cache.pop(gid, None)
    except PyMongoError as e:
        print(f"[config_manager] Lỗi set_guild_status({guild_id}): {e}")
        print(traceback.format_exc())


def get_guild_status(guild_id: str):
    """Lấy trạng thái guild từ MongoDB."""
    gid = str(guild_id)
    col = _guild_configs()
    if col is None:
        return None
    try:
        doc = col.find_one(
            {"guild_id": gid},
            {"status": 1, "_id": 0}
        )
        if doc:
            return doc.get("status")
    except PyMongoError as e:
        print(f"[config_manager] Lỗi get_guild_status({guild_id}): {e}")
        print(traceback.format_exc())
    return None


# ── Active Players ─────────────────────────────────────────────────

def save_active_players(guild_id: str, player_ids: list):
    """Lưu danh sách player ID đang chơi vào MongoDB (upsert)."""
    gid = str(guild_id)
    col = _active_players()
    if col is None:
        return
    try:
        col.update_one(
            {"guild_id": gid},
            {"$set": {
                "guild_id":   gid,
                "player_ids": [str(pid) for pid in player_ids]
            }},
            upsert=True
        )
    except PyMongoError as e:
        print(f"[config_manager] Lỗi save_active_players({guild_id}): {e}")
        print(traceback.format_exc())


def load_active_players(guild_id: str) -> list:
    """Tải danh sách player ID đang chơi từ MongoDB."""
    gid = str(guild_id)
    col = _active_players()
    if col is None:
        return []
    try:
        doc = col.find_one({"guild_id": gid})
        if doc:
            return [int(pid) for pid in doc.get("player_ids", [])]
    except PyMongoError as e:
        print(f"[config_manager] Lỗi load_active_players({guild_id}): {e}")
        print(traceback.format_exc())
    return []


def clear_active_players(guild_id: str):
    """Xóa document active_players của guild sau khi hết trận."""
    gid = str(guild_id)
    col = _active_players()
    if col is None:
        return
    try:
        col.delete_one({"guild_id": gid})
    except PyMongoError as e:
        print(f"[config_manager] Lỗi clear_active_players({guild_id}): {e}")
        print(traceback.format_exc())


# ── Lobby State ────────────────────────────────────────────────────

def load_guild_lobby(guild_id) -> dict | None:
    """Tải lobby state từ MongoDB. Trả None nếu không có."""
    gid = str(guild_id)
    col = _lobby_states()
    if col is None:
        return None
    try:
        doc = col.find_one({"guild_id": gid})
        if doc:
            doc.pop("_id", None)
            doc.pop("guild_id", None)
            return doc
    except PyMongoError as e:
        print(f"[config_manager] Lỗi load_guild_lobby({guild_id}): {e}")
        print(traceback.format_exc())
    return None


def save_guild_lobby(guild_id, data):
    """Lưu lobby state vào MongoDB (upsert). Hỗ trợ cả dict lẫn Discord Message object."""
    gid = str(guild_id)
    col = _lobby_states()
    if col is None:
        return
    try:
        if hasattr(data, 'id'):
            payload = {
                "guild_id":   gid,
                "message_id": data.id,
                "channel_id": data.channel.id
            }
        else:
            payload = {"guild_id": gid, **data}

        col.update_one(
            {"guild_id": gid},
            {"$set": payload},
            upsert=True
        )
    except PyMongoError as e:
        print(f"[config_manager] Lỗi save_guild_lobby({guild_id}): {e}")
        print(traceback.format_exc())


# ── Khởi tạo index (gọi một lần khi bot start) ────────────────────

def ensure_indexes():
    """Tạo unique index trên guild_id cho cả 3 collections. Gọi khi on_ready.

    FIX v2.3: Thêm log chi tiết + traceback để biết chính xác bước nào thất bại.
    """
    print("[config_manager] Đang khởi tạo MongoDB indexes...")
    db = _get_db()
    if db is None:
        print("[config_manager] ✗ Không tạo được index — DB chưa kết nối.")
        print("  → Kiểm tra MONGO_URI và IP Whitelist trên MongoDB Atlas.")
        return
    try:
        db["guild_configs"].create_index("guild_id", unique=True)
        db["active_players"].create_index("guild_id", unique=True)
        db["lobby_states"].create_index("guild_id", unique=True)
        print("[config_manager] ✓ MongoDB indexes OK.")
    except PyMongoError as e:
        print(f"[config_manager] ✗ Lỗi ensure_indexes: {e}")
        print(traceback.format_exc())
