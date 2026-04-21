
# ==============================
# config_manager.py — Anomalies v2.2
# REFACTOR: Chuyển toàn bộ từ local JSON sang MongoDB Atlas
# Collections: guild_configs, active_players, lobby_states
# ==============================

import os
import re
from pymongo import MongoClient
from pymongo.errors import PyMongoError

# ── Kết nối MongoDB ────────────────────────────────────────────────
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb+srv://HuyPh:axQGNHfYHMpL0WRq@anom.05vxqrw.mongodb.net/?appName=Anom"
)
DB_NAME = "Anomalies_DB"

_client = None


def _get_db():
    """Trả về database instance, tạo kết nối nếu chưa có (lazy singleton)."""
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    return _client[DB_NAME]


def _guild_configs():
    return _get_db()["guild_configs"]


def _active_players():
    return _get_db()["active_players"]


def _lobby_states():
    return _get_db()["lobby_states"]


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
    """Tải config của guild từ MongoDB. Luôn trả về dict hợp lệ."""
    try:
        doc = _guild_configs().find_one({"guild_id": str(guild_id)})
        if doc is None:
            return default_config()
        doc.pop("_id", None)
        doc.pop("guild_id", None)
        doc.pop("guild_name", None)
        # Merge với default để đảm bảo các key mới luôn có mặt
        cfg = default_config()
        cfg.update(doc)
        return cfg
    except PyMongoError:
        return default_config()


def save_guild_config(guild_id, data: dict, guild_name=None):
    """Lưu config của guild vào MongoDB (upsert)."""
    payload = dict(data)
    payload["guild_id"]   = str(guild_id)
    payload["guild_name"] = guild_name or ""
    try:
        _guild_configs().update_one(
            {"guild_id": str(guild_id)},
            {"$set": payload},
            upsert=True
        )
    except PyMongoError as e:
        print(f"[config_manager] Lỗi save_guild_config({guild_id}): {e}")


def load_all_configs() -> dict:
    """Trả về dict {guild_id: config} cho tất cả guild đã có config."""
    result = {}
    try:
        for doc in _guild_configs().find({}):
            gid = doc.get("guild_id")
            if not gid:
                continue
            doc.pop("_id", None)
            doc.pop("guild_id", None)
            doc.pop("guild_name", None)
            cfg = default_config()
            cfg.update(doc)
            result[str(gid)] = cfg
    except PyMongoError as e:
        print(f"[config_manager] Lỗi load_all_configs: {e}")
    return result


# ── Trạng thái ingame ──────────────────────────────────────────────

def set_guild_status(guild_id: str, status) -> None:
    """Đặt trạng thái ingame vào MongoDB (upsert)."""
    try:
        if status is None:
            _guild_configs().update_one(
                {"guild_id": str(guild_id)},
                {"$unset": {"status": ""}, "$set": {"guild_id": str(guild_id)}},
                upsert=True
            )
        else:
            _guild_configs().update_one(
                {"guild_id": str(guild_id)},
                {"$set": {"guild_id": str(guild_id), "status": status}},
                upsert=True
            )
    except PyMongoError as e:
        print(f"[config_manager] Lỗi set_guild_status({guild_id}): {e}")


def get_guild_status(guild_id: str):
    """Lấy trạng thái guild từ MongoDB."""
    try:
        doc = _guild_configs().find_one(
            {"guild_id": str(guild_id)},
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
    try:
        _active_players().update_one(
            {"guild_id": str(guild_id)},
            {"$set": {
                "guild_id":   str(guild_id),
                "player_ids": [str(pid) for pid in player_ids]
            }},
            upsert=True
        )
    except PyMongoError as e:
        print(f"[config_manager] Lỗi save_active_players({guild_id}): {e}")


def load_active_players(guild_id: str) -> list:
    """Tải danh sách player ID đang chơi từ MongoDB."""
    try:
        doc = _active_players().find_one({"guild_id": str(guild_id)})
        if doc:
            return [int(pid) for pid in doc.get("player_ids", [])]
    except PyMongoError as e:
        print(f"[config_manager] Lỗi load_active_players({guild_id}): {e}")
    return []


def clear_active_players(guild_id: str):
    """Xóa document active_players của guild sau khi hết trận."""
    try:
        _active_players().delete_one({"guild_id": str(guild_id)})
    except PyMongoError as e:
        print(f"[config_manager] Lỗi clear_active_players({guild_id}): {e}")


# ── Lobby State ────────────────────────────────────────────────────

def load_guild_lobby(guild_id) -> dict | None:
    """Tải lobby state từ MongoDB. Trả None nếu không có."""
    try:
        doc = _lobby_states().find_one({"guild_id": str(guild_id)})
        if doc:
            doc.pop("_id", None)
            doc.pop("guild_id", None)
            return doc
    except PyMongoError as e:
        print(f"[config_manager] Lỗi load_guild_lobby({guild_id}): {e}")
    return None


def save_guild_lobby(guild_id, data):
    """Lưu lobby state vào MongoDB (upsert). Hỗ trợ cả dict lẫn Discord Message object."""
    try:
        if hasattr(data, 'id'):
            # Discord Message object
            payload = {
                "guild_id":   str(guild_id),
                "message_id": data.id,
                "channel_id": data.channel.id
            }
        else:
            payload = {"guild_id": str(guild_id), **data}

        _lobby_states().update_one(
            {"guild_id": str(guild_id)},
            {"$set": payload},
            upsert=True
        )
    except PyMongoError as e:
        print(f"[config_manager] Lỗi save_guild_lobby({guild_id}): {e}")


# ── Khởi tạo index (gọi một lần khi bot start) ────────────────────

def ensure_indexes():
    """Tạo unique index trên guild_id cho cả 3 collections. Gọi khi on_ready."""
    try:
        db = _get_db()
        db["guild_configs"].create_index("guild_id", unique=True)
        db["active_players"].create_index("guild_id", unique=True)
        db["lobby_states"].create_index("guild_id", unique=True)
        print("[config_manager] MongoDB indexes OK.")
    except PyMongoError as e:
        print(f"[config_manager] Lỗi ensure_indexes: {e}")
