
# ==============================
# config_manager.py — Anomalies v2.2
# REFACTOR: Chuyển toàn bộ từ local JSON sang MongoDB Atlas
# Collections: guild_configs, active_players, lobby_states
# FIX: ID Stringify, MongoDB timeout, Cache Invalidation (last_updated)
# ==============================

import os
import re
import time
from pymongo import MongoClient
from pymongo.errors import PyMongoError

# ── Kết nối MongoDB ────────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "")
if not MONGO_URI:
    print("[config_manager] CẢNH BÁO: Biến môi trường MONGO_URI chưa được đặt!")
DB_NAME = "Anomalies_DB"

_client = None

# ── Cache RAM với timestamp để invalidate ──────────────────────────
# Cấu trúc: { guild_id: {"data": dict, "last_updated": float} }
_config_cache: dict = {}


def _get_db():
    """Trả về database instance, tạo kết nối nếu chưa có (lazy singleton).
    FIX: Thêm serverSelectionTimeoutMS=5000 + connectTimeoutMS=10000 + ping kiểm tra.
    Trả về None nếu kết nối thất bại thay vì crash toàn bộ tiến trình.
    """
    global _client
    if _client is None:
        if not MONGO_URI:
            print("[config_manager] Không có MONGO_URI — bỏ qua kết nối.")
            return None
        try:
            _client = MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000,
            )
            # Kiểm tra kết nối thực sự bằng ping
            _client.admin.command("ping")
            print("[config_manager] MongoDB kết nối thành công.")
        except Exception as e:
            print(f"[config_manager] Không kết nối được MongoDB: {e}")
            _client = None
            return None
    try:
        return _client[DB_NAME]
    except Exception as e:
        print(f"[config_manager] Lỗi lấy database: {e}")
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
    """Giữ lại để tương thích với code cũ, không còn dùng cho đường dẫn."""
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
        # Chỉ lấy last_updated trước để kiểm tra cache
        doc = col.find_one({"guild_id": gid})
        if doc is None:
            return default_config()

        db_last_updated = doc.get("last_updated", 0)
        cached = _config_cache.get(gid)

        # Nếu cache còn hợp lệ (DB chưa thay đổi) → dùng cache RAM
        if cached and cached.get("last_updated", -1) == db_last_updated:
            return dict(cached["data"])

        # Cache hết hiệu lực hoặc chưa có → tải lại từ DB
        doc.pop("_id", None)
        doc.pop("guild_id", None)
        doc.pop("guild_name", None)
        doc.pop("last_updated", None)   # Không trả trường nội bộ ra ngoài
        cfg = default_config()
        cfg.update(doc)

        _config_cache[gid] = {
            "data": dict(cfg),
            "last_updated": db_last_updated,
        }
        return cfg
    except PyMongoError as e:
        print(f"[config_manager] Lỗi load_guild_config({guild_id}): {e}")
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
    payload["last_updated"] = time.time()   # Timestamp → trigger cache invalidation
    try:
        col.update_one(
            {"guild_id": gid},
            {"$set": payload},
            upsert=True
        )
        # Xóa cache RAM của guild này để lần load sau lấy từ DB
        _config_cache.pop(gid, None)
    except PyMongoError as e:
        print(f"[config_manager] Lỗi save_guild_config({guild_id}): {e}")


def load_all_configs() -> dict:
    """Trả về dict {guild_id: config} cho tất cả guild đã có config."""
    result = {}
    col = _guild_configs()
    if col is None:
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
    return None


def save_guild_lobby(guild_id, data):
    """Lưu lobby state vào MongoDB (upsert). Hỗ trợ cả dict lẫn Discord Message object."""
    gid = str(guild_id)
    col = _lobby_states()
    if col is None:
        return
    try:
        if hasattr(data, 'id'):
            # Discord Message object
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


# ── Khởi tạo index (gọi một lần khi bot start) ────────────────────

def ensure_indexes():
    """Tạo unique index trên guild_id cho cả 3 collections. Gọi khi on_ready."""
    db = _get_db()
    if db is None:
        print("[config_manager] Không tạo được index — DB chưa kết nối.")
        return
    try:
        db["guild_configs"].create_index("guild_id", unique=True)
        db["active_players"].create_index("guild_id", unique=True)
        db["lobby_states"].create_index("guild_id", unique=True)
        print("[config_manager] MongoDB indexes OK.")
    except PyMongoError as e:
        print(f"[config_manager] Lỗi ensure_indexes: {e}")
