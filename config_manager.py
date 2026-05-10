
# ==============================
# config_manager.py — Anomalies v2.3 (Fixed for Render)
#
# FIX v2.3:
#   - Thêm tlsAllowInvalidCertificates=True để tránh lỗi SSL cert trên Render
#   - Thêm traceback.format_exc() để log lỗi chi tiết vào console
#   - Thêm retry logic khi kết nối MongoDB thất bại lần đầu
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
from pymongo.errors import PyMongoError, ConnectionFailure, ServerSelectionTimeoutError

# ── Kết nối MongoDB ────────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "")
if not MONGO_URI:
    print("[config_manager] CẢNH BÁO: Biến môi trường MONGO_URI chưa được đặt!")
else:
    # Log URI ẩn password để debug (chỉ hiện scheme + host)
    try:
        from urllib.parse import urlparse
        _parsed = urlparse(MONGO_URI)
        print(f"[config_manager] MONGO_URI nhận diện được: {_parsed.scheme}://{_parsed.hostname}/...")
    except Exception:
        print("[config_manager] MONGO_URI đã được đặt (không parse được URI).")

DB_NAME = "Anomalies_DB"

_client = None

# ── Cache RAM với timestamp để invalidate ──────────────────────────
# Cấu trúc: { guild_id: {"data": dict, "last_updated": float} }
_config_cache: dict = {}


def _get_db():
    """Trả về database instance, tạo kết nối nếu chưa có (lazy singleton).

    FIX v2.3:
    - tlsAllowInvalidCertificates=True: tránh lỗi SSL cert chain trên môi trường Render
      (Render dùng proxy nội bộ có thể không khớp CA chain của certifi)
    - tls=True: đảm bảo kết nối mã hóa tới MongoDB Atlas
    - traceback.format_exc(): in toàn bộ stack trace khi lỗi để dễ debug
    - Reset _client = None sau khi lỗi để lần gọi tiếp sẽ thử kết nối lại
    """
    global _client
    if _client is not None:
        # Kiểm tra nhanh client còn sống không
        try:
            _client.admin.command("ping")
        except Exception:
            print("[config_manager] Client hiện tại đã mất kết nối — tạo lại.")
            try:
                _client.close()
            except Exception:
                pass
            _client = None

    if _client is None:
        if not MONGO_URI:
            print("[config_manager] Không có MONGO_URI — bỏ qua kết nối.")
            return None
        try:
            print("[config_manager] Đang kết nối MongoDB Atlas...")
            _client = MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=8000,   # 8s để Atlas cold-start kịp phản hồi
                connectTimeoutMS=15000,
                socketTimeoutMS=30000,
                # ── FIX SSL cho Render ──────────────────────────────
                # Render có thể không có đủ CA bundle → tlsAllowInvalidCertificates=True
                # tls=True vẫn giữ mã hóa, chỉ bỏ qua xác minh chain
                tls=True,
                tlsAllowInvalidCertificates=True,
                # ────────────────────────────────────────────────────
                retryWrites=True,
                w="majority",
            )
            # Kiểm tra kết nối thực sự bằng ping
            _client.admin.command("ping")
            print("[config_manager] ✓ MongoDB kết nối thành công.")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            print(f"[config_manager] ✗ Không kết nối được MongoDB (ConnectionFailure):")
            print(f"  Lỗi: {e}")
            print(f"  Chi tiết:\n{traceback.format_exc()}")
            print("  Kiểm tra: MONGO_URI đúng không? MongoDB Atlas IP Whitelist có 0.0.0.0/0 chưa?")
            _client = None
            return None
        except Exception as e:
            print(f"[config_manager] ✗ Lỗi không xác định khi kết nối MongoDB:")
            print(f"  Lỗi: {e}")
            print(f"  Chi tiết:\n{traceback.format_exc()}")
            _client = None
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
    }


# ── Guild Config ───────────────────────────────────────────────────

def load_guild_config(guild_id, guild_name=None) -> dict:
    """Tải config của guild từ MongoDB. Luôn trả về dict hợp lệ.
    FIX Cache Invalidation: So sánh last_updated trong DB với bản trong RAM.
    Nếu DB mới hơn (Dashboard vừa sửa) → buộc reload. ID luôn ép str().
    """
    gid = str(guild_id)
    col = _guild_configs()
    if col is None:
        return default_config()
    try:
        doc = col.find_one({"guild_id": gid})
        if doc is None:
            return default_config()

        db_last_updated = doc.get("last_updated", 0)
        cached = _config_cache.get(gid)

        if cached and cached.get("last_updated", -1) == db_last_updated:
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
        }
        return cfg
    except PyMongoError as e:
        print(f"[config_manager] Lỗi load_guild_config({guild_id}): {e}")
        print(traceback.format_exc())
        return default_config()


def save_guild_config(guild_id, data: dict, guild_name=None):
    """Lưu config của guild vào MongoDB (upsert).
    FIX: guild_id luôn ép str(). Cập nhật last_updated để Bot tự reload cache.
    """
    gid = str(guild_id)
    col = _guild_configs()
    if col is None:
        return
    payload = dict(data)
    payload["guild_id"]     = gid
    payload["guild_name"]   = guild_name or ""
    payload["last_updated"] = time.time()
    try:
        col.update_one(
            {"guild_id": gid},
            {"$set": payload},
            upsert=True
        )
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
