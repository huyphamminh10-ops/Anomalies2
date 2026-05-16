# ══════════════════════════════════════════════════════════════════
# core/dlc_economy.py — Hệ thống Kinh tế DOELCES v1.0
#
# Chức năng:
#   award_game_rewards()     → trao Gold + Gems sau trận
#   generate_serial_key()    → tạo mã kích hoạt DLC
#   redeem_serial()          → nhập mã kích hoạt
#   purchase_dlc()           → mua DLC (trừ tiền + tạo serial)
#   get_player_wallet()      → lấy số dư ví người chơi
#   get_player_dlcs()        → DLC đã sở hữu
#   ensure_economy_tables()  → tạo bảng DB nếu chưa có
#
# Cơ chế kiếm tiền:
#   - Sống sót đến cuối: 1-35 Gold (ngẫu nhiên) + số ngày sống sót
#   - Chết giữa chừng: cố định 30 Gold
#   - Mỗi hành động: 50% tỉ lệ nhận 1-5 Gems
#   - Phần thưởng stack (cộng dồn)
#
# Cơ chế kích hoạt Mod:
#   Format: <TÊN_MOD>:<KEY_25_KÝ_TỰ>
#   Key gồm: chữ, số, @, &, %, ₫
# ══════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
import random
import string
import time
import traceback
from typing import Dict, List, Optional, Tuple

# ── DB import ──────────────────────────────────────────────────────
try:
    import mysql.connector
    _HAS_CONNECTOR = True
except ImportError:
    _HAS_CONNECTOR = False

try:
    import certifi
    _SSL_CA = certifi.where()
except ImportError:
    _SSL_CA = None

TIDB_URL = (os.environ.get("TIDB_URL_DLC") or os.environ.get("TIDB_URL") or "").strip()

# Ký tự hợp lệ trong key
_KEY_CHARSET = string.ascii_letters + string.digits + "@&%₫"
_KEY_LENGTH  = 25

# ══════════════════════════════════════════════════════════════════
# DB CONNECTION (tái sử dụng logic từ database_tidb.py)
# ══════════════════════════════════════════════════════════════════

def _parse_tidb_url(url: str) -> dict:
    url = (url or "").strip()
    if not url:
        return {}
    try:
        rest = url
        for prefix in ("mysql+mysqlconnector://", "mysql://"):
            if rest.startswith(prefix):
                rest = rest[len(prefix):]
                break
        at_idx   = rest.rfind("@")
        userinfo = rest[:at_idx]
        hostpart = rest[at_idx + 1:]
        colon_ui = userinfo.index(":")
        user     = userinfo[:colon_ui]
        password = userinfo[colon_ui + 1:]
        if "/" in hostpart:
            host_port, dbname = hostpart.rsplit("/", 1)
        else:
            host_port = hostpart
            dbname    = "sys"
        if ":" in host_port:
            host, port = host_port.rsplit(":", 1)
            port = int(port)
        else:
            host = host_port
            port = 4000
        return {"host": host, "port": port, "user": user, "password": password, "database": dbname}
    except Exception:
        return {}


def _get_conn():
    if not _HAS_CONNECTOR:
        raise RuntimeError("mysql-connector-python chưa được cài")
    params = _parse_tidb_url(TIDB_URL)
    if not params:
        raise RuntimeError("TIDB_URL chưa được cấu hình")
    ssl_args = {}
    if _SSL_CA:
        ssl_args = {"ssl_ca": _SSL_CA, "ssl_verify_cert": True, "ssl_verify_identity": True}
    return mysql.connector.connect(**params, **ssl_args, autocommit=False, connection_timeout=10)


# ══════════════════════════════════════════════════════════════════
# TABLE SETUP
# ══════════════════════════════════════════════════════════════════

def ensure_economy_tables() -> None:
    """Tạo các bảng kinh tế và DLC nếu chưa tồn tại."""
    ddl_statements = [
        # Ví người chơi
        """
        CREATE TABLE IF NOT EXISTS player_wallet (
            user_id      VARCHAR(32)  NOT NULL PRIMARY KEY,
            gold         BIGINT       NOT NULL DEFAULT 0,
            gems         BIGINT       NOT NULL DEFAULT 0,
            total_games  INT          NOT NULL DEFAULT 0,
            updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                         ON UPDATE CURRENT_TIMESTAMP
        )
        """,
        # Danh sách DLC serial keys
        """
        CREATE TABLE IF NOT EXISTS dlc_serials (
            serial_id    VARCHAR(64)  NOT NULL PRIMARY KEY,
            mod_name     VARCHAR(128) NOT NULL,
            serial_key   VARCHAR(32)  NOT NULL,
            status       ENUM('unused','used') NOT NULL DEFAULT 'unused',
            owner_id     VARCHAR(32)  DEFAULT NULL,
            created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            redeemed_at  DATETIME     DEFAULT NULL,
            INDEX idx_mod_status (mod_name, status),
            INDEX idx_owner (owner_id)
        )
        """,
        # DLC sở hữu của người chơi
        """
        CREATE TABLE IF NOT EXISTS player_dlcs (
            id           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
            user_id      VARCHAR(32)  NOT NULL,
            mod_name     VARCHAR(128) NOT NULL,
            serial_id    VARCHAR(64)  NOT NULL,
            acquired_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uniq_user_mod (user_id, mod_name),
            INDEX idx_user (user_id)
        )
        """,
        # Lịch sử phần thưởng
        """
        CREATE TABLE IF NOT EXISTS reward_history (
            id           BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
            user_id      VARCHAR(32)  NOT NULL,
            game_id      VARCHAR(64)  DEFAULT NULL,
            gold_earned  INT          NOT NULL DEFAULT 0,
            gems_earned  INT          NOT NULL DEFAULT 0,
            reason       VARCHAR(255) DEFAULT '',
            earned_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_user_time (user_id, earned_at)
        )
        """,
    ]
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        for stmt in ddl_statements:
            cur.execute(stmt.strip())
        conn.commit()
        cur.close()
        conn.close()
        print("[Economy] ✅ Bảng kinh tế đã sẵn sàng.")
    except Exception as e:
        print(f"[Economy] ❌ Lỗi tạo bảng: {e}")


# ══════════════════════════════════════════════════════════════════
# WALLET OPERATIONS
# ══════════════════════════════════════════════════════════════════

def get_player_wallet(user_id: str) -> Dict:
    """Lấy số dư ví người chơi. Trả về dict {gold, gems, total_games}."""
    try:
        conn = _get_conn()
        cur  = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT gold, gems, total_games FROM player_wallet WHERE user_id=%s",
            (str(user_id),)
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        return row if row else {"gold": 0, "gems": 0, "total_games": 0}
    except Exception as e:
        print(f"[Economy] Lỗi get_player_wallet: {e}")
        return {"gold": 0, "gems": 0, "total_games": 0}


def _add_to_wallet(user_id: str, gold: int, gems: int, conn) -> None:
    """Cộng gold + gems vào ví (upsert). Dùng trong transaction."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO player_wallet (user_id, gold, gems, total_games)
        VALUES (%s, %s, %s, 1)
        ON DUPLICATE KEY UPDATE
            gold        = gold + VALUES(gold),
            gems        = gems + VALUES(gems),
            total_games = total_games + 1
        """,
        (str(user_id), max(0, gold), max(0, gems))
    )
    cur.close()


def _log_reward(user_id: str, gold: int, gems: int, reason: str, game_id: str, conn) -> None:
    """Ghi lịch sử phần thưởng."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reward_history (user_id, game_id, gold_earned, gems_earned, reason) VALUES (%s,%s,%s,%s,%s)",
        (str(user_id), str(game_id or ""), gold, gems, reason[:255])
    )
    cur.close()


# ══════════════════════════════════════════════════════════════════
# REWARD SYSTEM
# ══════════════════════════════════════════════════════════════════

def calculate_game_reward(
    survived: bool,
    days_survived: int,
    actions_taken: int = 0,
) -> Tuple[int, int]:
    """
    Tính phần thưởng sau trận:
      - Sống sót: 1-35 Gold + days_survived
      - Chết:     30 Gold cố định
      - Mỗi action: 50% nhận 1-5 Gems
    Trả về (gold, gems).
    """
    if survived:
        base_gold = random.randint(1, 35)
        gold = base_gold + max(0, days_survived)
    else:
        gold = 30

    # Gems từ hành động (stack)
    gems = 0
    for _ in range(max(0, actions_taken)):
        if random.random() < 0.5:
            gems += random.randint(1, 5)

    return gold, gems


async def award_game_rewards(
    players_data: List[Dict],
    game_id: str = "",
) -> Dict[str, Dict]:
    """
    Trao phần thưởng cho danh sách người chơi sau trận.

    players_data: list of {
        "user_id":      str,
        "survived":     bool,
        "days_survived": int,
        "actions_taken": int,   ← tùy chọn
    }

    Trả về dict {user_id: {gold, gems, reason}} cho mỗi người.
    """
    results: Dict[str, Dict] = {}

    try:
        conn = _get_conn()
        for p in players_data:
            uid           = str(p.get("user_id", ""))
            survived      = bool(p.get("survived", False))
            days_survived = int(p.get("days_survived", 0))
            actions_taken = int(p.get("actions_taken", 0))

            gold, gems = calculate_game_reward(survived, days_survived, actions_taken)
            reason     = (
                f"Sống sót {days_survived} ngày" if survived
                else "Chết giữa trận"
            )

            _add_to_wallet(uid, gold, gems, conn)
            _log_reward(uid, gold, gems, reason, game_id, conn)

            results[uid] = {"gold": gold, "gems": gems, "reason": reason}

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Economy] ❌ Lỗi award_game_rewards: {e}")
        traceback.print_exc()

    return results


# ══════════════════════════════════════════════════════════════════
# SERIAL KEY SYSTEM
# ══════════════════════════════════════════════════════════════════

def _generate_key() -> str:
    """Tạo key 25 ký tự từ charset hợp lệ."""
    return "".join(random.choices(_KEY_CHARSET, k=_KEY_LENGTH))


def generate_serial_key(mod_name: str) -> Optional[str]:
    """
    Tạo một serial key mới cho mod và lưu vào DB.
    Trả về chuỗi "<MOD_NAME>:<KEY>" hoặc None nếu lỗi.
    """
    try:
        key       = _generate_key()
        serial_id = f"{mod_name}:{int(time.time()*1000)}:{random.randint(1000,9999)}"
        conn = _get_conn()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO dlc_serials (serial_id, mod_name, serial_key, status)
            VALUES (%s, %s, %s, 'unused')
            """,
            (serial_id, str(mod_name), key)
        )
        conn.commit()
        cur.close(); conn.close()
        return f"{mod_name}:{key}"
    except Exception as e:
        print(f"[Economy] ❌ Lỗi generate_serial_key: {e}")
        return None


def validate_serial_format(serial_str: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Kiểm tra format serial "<MOD_NAME>:<KEY>".
    Trả về (mod_name, key) hoặc (None, None) nếu sai.
    """
    parts = serial_str.strip().split(":", 1)
    if len(parts) != 2:
        return None, None
    mod_name, key = parts
    if not mod_name or len(key) != _KEY_LENGTH:
        return None, None
    # Kiểm tra ký tự hợp lệ trong key
    valid_chars = set(_KEY_CHARSET)
    if not all(c in valid_chars for c in key):
        return None, None
    return mod_name, key


def redeem_serial(user_id: str, serial_str: str) -> Dict:
    """
    Người chơi nhập mã serial để kích hoạt mod.
    Trả về {ok: bool, message: str, mod_name: str | None}
    """
    mod_name, key = validate_serial_format(serial_str)
    if not mod_name:
        return {
            "ok": False,
            "message": "❌ Định dạng mã không hợp lệ. Ví dụ: `TenMod:25KyTuKey`",
            "mod_name": None,
        }

    try:
        conn = _get_conn()
        cur  = conn.cursor(dictionary=True)

        # Kiểm tra serial có tồn tại và chưa dùng
        cur.execute(
            """
            SELECT serial_id, status, owner_id
            FROM dlc_serials
            WHERE mod_name=%s AND serial_key=%s
            LIMIT 1
            """,
            (mod_name, key)
        )
        row = cur.fetchone()

        if not row:
            cur.close(); conn.close()
            return {
                "ok": False,
                "message": f'❌ Mã Serial của Mod **"{mod_name}"** không tồn tại.',
                "mod_name": mod_name,
            }

        if row["status"] == "used":
            cur.close(); conn.close()
            return {
                "ok": False,
                "message": f'❌ Mã Serial này đã được sử dụng rồi.',
                "mod_name": mod_name,
            }

        # Kiểm tra người chơi đã có mod chưa
        cur.execute(
            "SELECT id FROM player_dlcs WHERE user_id=%s AND mod_name=%s",
            (str(user_id), mod_name)
        )
        if cur.fetchone():
            cur.close(); conn.close()
            return {
                "ok": False,
                "message": f'⚠️ Bạn đã sở hữu Mod **"{mod_name}"** rồi.',
                "mod_name": mod_name,
            }

        # Đánh dấu used + ghi player_dlcs
        serial_id = row["serial_id"]
        cur.execute(
            """
            UPDATE dlc_serials
            SET status='used', owner_id=%s, redeemed_at=NOW()
            WHERE serial_id=%s
            """,
            (str(user_id), serial_id)
        )
        cur.execute(
            """
            INSERT INTO player_dlcs (user_id, mod_name, serial_id)
            VALUES (%s, %s, %s)
            """,
            (str(user_id), mod_name, serial_id)
        )
        conn.commit()
        cur.close(); conn.close()

        return {
            "ok": True,
            "message": (
                f'✅ Serial của Mod **"{mod_name}"** đã đúng!\n'
                f'Bây giờ bạn có thể thêm Mod vào trong phần cài đặt `/settings`'
            ),
            "mod_name": mod_name,
        }

    except Exception as e:
        print(f"[Economy] ❌ Lỗi redeem_serial: {e}")
        return {
            "ok": False,
            "message": "❌ Lỗi hệ thống khi xử lý mã. Vui lòng thử lại.",
            "mod_name": None,
        }


def purchase_dlc(user_id: str, mod_name: str, price_amount: int, price_currency: str) -> Dict:
    """
    Mua DLC: trừ tiền + tạo serial key mới.
    Trả về {ok, message, serial}
    """
    if price_currency not in ("gold", "gems", "nope"):
        return {"ok": False, "message": "Loại tiền không hợp lệ.", "serial": None}

    try:
        conn = _get_conn()
        cur  = conn.cursor(dictionary=True)

        # Kiểm tra đã có chưa
        cur.execute(
            "SELECT id FROM player_dlcs WHERE user_id=%s AND mod_name=%s",
            (str(user_id), mod_name)
        )
        if cur.fetchone():
            cur.close(); conn.close()
            return {"ok": False, "message": f'Bạn đã sở hữu Mod "{mod_name}" rồi.', "serial": None}

        # Kiểm tra số dư (nếu không miễn phí)
        if price_currency != "nope" and price_amount > 0:
            cur.execute(
                f"SELECT {price_currency} FROM player_wallet WHERE user_id=%s",
                (str(user_id),)
            )
            wallet_row = cur.fetchone()
            balance    = (wallet_row or {}).get(price_currency, 0)
            if balance < price_amount:
                icon = "🪙" if price_currency == "gold" else "💎"
                cur.close(); conn.close()
                return {
                    "ok": False,
                    "message": f"Không đủ {icon} {price_currency.capitalize()}. Bạn có {balance:,}, cần {price_amount:,}.",
                    "serial": None,
                }

            # Trừ tiền
            cur.execute(
                f"UPDATE player_wallet SET {price_currency}={price_currency}-%s WHERE user_id=%s",
                (price_amount, str(user_id))
            )

        conn.commit()

        # Tạo serial key
        key       = _generate_key()
        serial_id = f"{mod_name}:{int(time.time()*1000)}:{random.randint(1000,9999)}"
        serial_str = f"{mod_name}:{key}"

        cur.execute(
            """
            INSERT INTO dlc_serials (serial_id, mod_name, serial_key, status, owner_id, redeemed_at)
            VALUES (%s, %s, %s, 'used', %s, NOW())
            """,
            (serial_id, mod_name, key, str(user_id))
        )
        cur.execute(
            "INSERT INTO player_dlcs (user_id, mod_name, serial_id) VALUES (%s,%s,%s)",
            (str(user_id), mod_name, serial_id)
        )
        conn.commit()
        cur.close(); conn.close()

        return {
            "ok": True,
            "message": f'✅ Mua Mod **"{mod_name}"** thành công!',
            "serial": serial_str,
        }

    except Exception as e:
        print(f"[Economy] ❌ Lỗi purchase_dlc: {e}")
        return {"ok": False, "message": "Lỗi hệ thống khi mua.", "serial": None}


def get_player_dlcs(user_id: str) -> List[str]:
    """Trả về danh sách tên mod người chơi đã sở hữu."""
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        cur.execute(
            "SELECT mod_name FROM player_dlcs WHERE user_id=%s ORDER BY acquired_at",
            (str(user_id),)
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        print(f"[Economy] Lỗi get_player_dlcs: {e}")
        return []


# ══════════════════════════════════════════════════════════════════
# ADMIN: List all serials for a mod
# ══════════════════════════════════════════════════════════════════

def list_serials_for_mod(mod_name: str, status: str = "all") -> List[Dict]:
    """Owner xem danh sách serial của một mod."""
    try:
        conn = _get_conn()
        cur  = conn.cursor(dictionary=True)
        if status == "all":
            cur.execute(
                "SELECT serial_id, serial_key, status, owner_id, created_at, redeemed_at FROM dlc_serials WHERE mod_name=%s ORDER BY created_at DESC",
                (mod_name,)
            )
        else:
            cur.execute(
                "SELECT serial_id, serial_key, status, owner_id, created_at, redeemed_at FROM dlc_serials WHERE mod_name=%s AND status=%s ORDER BY created_at DESC",
                (mod_name, status)
            )
        rows = cur.fetchall()
        cur.close(); conn.close()
        return rows
    except Exception as e:
        print(f"[Economy] Lỗi list_serials_for_mod: {e}")
        return []
