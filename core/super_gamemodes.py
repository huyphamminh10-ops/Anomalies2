# ==============================
# super_gamemodes.py — Anomalies Super Gamemodes System
# Rotate every 72 hours. Replaces normal gameplay + Lobby Embed.
# ==============================
#
# Các chế độ:
#  1. HE RETURNED!!!   — Serial Killer 1v All (giết 1 người/đêm, Survivors phải tiêu diệt)
#  2. KING!!!          — Cả 3 phe hợp tác để GIẾT KING; KING chết = tất cả thắng
#  3. I TRIED!         — Game tốc độ x3
#  4. FRANCE MODE 🇫🇷  — Đổi ngôn ngữ sang Tiếng Pháp
# ==============================

from __future__ import annotations

import time
from typing import Optional

# ── Hằng số ────────────────────────────────────────────────────────
ROTATION_INTERVAL_HOURS = 72          # 72 giờ / chế độ
ROTATION_INTERVAL_SECS  = ROTATION_INTERVAL_HOURS * 3600

# Epoch mốc: 2025-01-01 00:00:00 UTC (dùng để tính chu kỳ đồng nhất giữa mọi server)
_EPOCH = 1735689600


# ══════════════════════════════════════════════════════════════════════
# §1  GAMEMODE REGISTRY
# ══════════════════════════════════════════════════════════════════════

class SuperGamemode:
    """Một chế độ chơi đặc biệt."""

    def __init__(
        self,
        id: str,
        name: str,                  # tên Unicode hiển thị (font đặc biệt)
        description: str,           # mô tả ngắn cách hoạt động
        apply_fn,                   # callable(raw_config: dict) -> dict  — trả về config đã sửa
    ):
        self.id          = id
        self.name        = name
        self.description = description
        self.apply_fn    = apply_fn   # sửa raw_config rồi trả về bản mới


def _apply_he_returned(raw: dict) -> dict:
    """Force 1 Serial Killer, loại bỏ Anomalies thường; Survivors phải tiêu diệt SK."""
    cfg = dict(raw)
    cfg["super_gamemode_active"]         = True
    cfg["super_gamemode_id"]             = "he_returned"
    # Buộc role override: chỉ 1 Serial Killer + Survivors đầy
    cfg["super_gamemode_force_roles"]    = {
        "Survivors": "all",          # phân phối Survivors bình thường
        "Anomalies": [],             # không có Anomaly thường
        "Unknown":   ["KẺ GIẾT NGƯỜI HÀNG LOẠT"],  # đúng 1 Serial Killer
    }
    cfg["super_gamemode_win_override"]   = "he_returned"   # logic thắng tùy chỉnh
    return cfg


def _apply_king(raw: dict) -> dict:
    """Chọn 1 người bí mật làm KING. Cả 3 phe hợp tác để GIẾT KING — KING chết = tất cả thắng."""
    cfg = dict(raw)
    cfg["super_gamemode_active"]       = True
    cfg["super_gamemode_id"]           = "king"
    cfg["super_gamemode_win_override"] = "king"   # engine check KING còn sống
    return cfg


def _apply_i_tried(raw: dict) -> dict:
    """Tăng tốc game 3x (night/day/vote time chia 3)."""
    cfg = dict(raw)
    cfg["super_gamemode_active"] = True
    cfg["super_gamemode_id"]     = "i_tried"
    cfg["night_time"]  = max(10, (raw.get("night_time",  45) // 3))
    cfg["day_time"]    = max(10, (raw.get("day_time",    90) // 3))
    cfg["vote_time"]   = max(5,  (raw.get("vote_time",   30) // 3))
    cfg["role_distribute_time"] = max(3, (raw.get("role_distribute_time", 15) // 3))
    return cfg


def _apply_france_mode(raw: dict) -> dict:
    """Đổi toàn bộ ngôn ngữ game sang Tiếng Pháp."""
    cfg = dict(raw)
    cfg["super_gamemode_active"]   = True
    cfg["super_gamemode_id"]       = "france_mode"
    cfg["game_language"]           = "fr"   # GameEngine sẽ dùng key này
    return cfg


# Danh sách theo thứ tự xoay vòng
ALL_GAMEMODES: list[SuperGamemode] = [
    SuperGamemode(
        id          = "he_returned",
        name        = "⚡️𝙎𝙐𝙋𝙀𝙍 𝙂𝘼𝙈𝙀𝙈𝙊𝘿𝙀𝙎 \n🅷🅴 🆁🅴🆃🆄🆁🅽🅴🅳!!!",
        description = (
            "Tất cả Survivors đối đầu với **1 KẺ GIẾT NGƯỜI HÀNG LOẠT** bí ẩn.\n"
            "Hắn giết 1 người mỗi đêm — không gì có thể ngăn hắn lại.\n"
            "🎯 **Nhiệm vụ:** Tìm ra và tiêu diệt Kẻ Giết Người trước khi quá muộn."
        ),
        apply_fn    = _apply_he_returned,
    ),
    SuperGamemode(
        id          = "king",
        name        = "⚡️𝙎𝙐𝙋𝙀𝙍 𝙂𝘼𝙈𝙀𝙈𝙊𝘿𝙀𝙎 \n🅺🅸🅽🅶!!!",
        description = (
            "Một người bí mật được chọn làm **KING**.\n"
            "Cả 3 phe — Survivors, Anomalies, Unknown — đều hợp tác để **GIẾT** KING.\n"
            "💀 KING chết → ba phe đều chiến thắng.\n"
            "👑 KING sống sót qua **5 đêm** → KING thắng một mình!"
        ),
        apply_fn    = _apply_king,
    ),
    SuperGamemode(
        id          = "i_tried",
        name        = "⚡️𝙎𝙐𝙋𝙀𝙍 𝙂𝘼𝙈𝙀𝙈𝙊𝘿𝙀𝙎 \n🅸 🆃🆁🅸🅴🅳!",
        description = (
            "Game bình thường nhưng chạy ở **tốc độ x3**.\n"
            "⚡ Thời gian đêm, ngày, bỏ phiếu đều rút ngắn xuống còn 1/3.\n"
            "Phản ứng nhanh — hoặc chết."
        ),
        apply_fn    = _apply_i_tried,
    ),
    SuperGamemode(
        id          = "france_mode",
        name        = "⚡️𝙎𝙐𝙋𝙀𝙍 𝙂𝘼𝙈𝙀𝙈𝙊𝘿𝙀𝙎 \n🇫🇷 🅵🆁🅰🅽🅲🅴 🅼🅾🅳🅴",
        description = (
            "Toàn bộ ngôn ngữ trong game chuyển sang **Tiếng Pháp** 🇫🇷.\n"
            "Tin nhắn bot, thông báo đêm/ngày, DM vai trò — tất cả bằng Français.\n"
            "Bonne chance, joueurs!"
        ),
        apply_fn    = _apply_france_mode,
    ),
]

# Map ID → object để tra nhanh
_GAMEMODE_MAP: dict[str, SuperGamemode] = {gm.id: gm for gm in ALL_GAMEMODES}


# ══════════════════════════════════════════════════════════════════════
# §2  ROTATION LOGIC
# ══════════════════════════════════════════════════════════════════════

def get_current_gamemode_index(now: Optional[float] = None) -> int:
    """Trả về index gamemode hiện tại dựa trên thời gian UTC (xoay vòng 72h)."""
    t = (now or time.time()) - _EPOCH
    slot = int(t // ROTATION_INTERVAL_SECS)
    return slot % len(ALL_GAMEMODES)


def get_current_gamemode(now: Optional[float] = None) -> SuperGamemode:
    return ALL_GAMEMODES[get_current_gamemode_index(now)]


def get_time_remaining_in_slot(now: Optional[float] = None) -> int:
    """Số giây còn lại trong slot hiện tại."""
    t   = (now or time.time()) - _EPOCH
    elapsed_in_slot = t % ROTATION_INTERVAL_SECS
    return int(ROTATION_INTERVAL_SECS - elapsed_in_slot)


def format_time_remaining(secs: int) -> str:
    """Ví dụ: 2d 13h 43p"""
    d = secs // 86400
    secs %= 86400
    h = secs // 3600
    secs %= 3600
    m = secs // 60
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    parts.append(f"{m}p")
    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════
# §3  CONFIG PATCHER
# ══════════════════════════════════════════════════════════════════════

def patch_config_for_gamemode(raw_config: dict) -> dict:
    """
    Nếu super_gamemodes bật → áp dụng chế độ hiện tại lên raw_config.
    Gọi trước build_game_config() trong launch_game().
    """
    if not raw_config.get("super_gamemodes_enabled", False):
        return raw_config
    gm  = get_current_gamemode()
    cfg = gm.apply_fn(raw_config)
    print(f"[SuperGamemodes] Áp dụng chế độ: {gm.id}")
    return cfg


# ══════════════════════════════════════════════════════════════════════
# §4  LOBBY EMBED BUILDER
# ══════════════════════════════════════════════════════════════════════

def build_super_gamemode_embed(guild_id: str = None, player_count: int = 0) -> dict:
    """
    Trả về kwargs cho disnake.Embed thay thế lobby embed khi Super Gamemodes bật.
    Caller tự tạo embed rồi set fields từ dict này.
    """
    import disnake
    gm        = get_current_gamemode()
    remaining = get_time_remaining_in_slot()
    time_str  = format_time_remaining(remaining)

    embed = disnake.Embed(
        title       = gm.name,
        description = (
            f"{gm.description}\n\n"
            f"⏳ **<{time_str}>** cho đến chế độ tiếp theo\n\n"
            f"Đang chờ **{player_count}** người..."
        ),
        color       = 0xf1c40f,
    )
    embed.set_footer(text="⚡ SUPER GAMEMODES  •  Xoay vòng mỗi 72 giờ")
    return embed


# ══════════════════════════════════════════════════════════════════════
# §5  WIN OVERRIDE HOOKS  (được game.py gọi)
# ══════════════════════════════════════════════════════════════════════

def check_win_override(game, win_override: str) -> Optional[str]:
    """
    Trả về tên phe thắng (str) hoặc None nếu chưa kết thúc.
    Chỉ được gọi khi super_gamemode_win_override được đặt trong config.

    game: GameEngine instance
    """
    if win_override == "he_returned":
        return _check_win_he_returned(game)
    if win_override == "king":
        return _check_win_king(game)
    return None


def _check_win_he_returned(game) -> Optional[str]:
    """
    Serial Killer (duy nhất trong Unknown) giết 1 người/đêm.
    - SK chết → Survivors thắng.
    - Survivors hết → SK thắng.
    """
    from roles.unknown.serial_killer import SerialKiller

    alive      = game.get_alive_players()
    alive_ids  = {p.id for p in alive}
    sk_alive   = any(
        isinstance(game.roles.get(pid), SerialKiller)
        for pid in alive_ids
    )

    if not sk_alive:
        return "Survivors"

    non_sk_alive = [
        p for p in alive
        if not isinstance(game.roles.get(p.id), SerialKiller)
    ]
    if not non_sk_alive:
        return "Serial Killer"

    return None


_KING_SURVIVE_NIGHTS = 5   # KING thắng nếu sống đủ số đêm này

def _check_win_king(game) -> Optional[str]:
    """
    - KING chết (bất kỳ lúc nào)  → cả 3 phe thắng.
    - KING sống qua đủ 5 đêm      → KING thắng (solo).
    """
    king_id = getattr(game, "super_king_id", None)
    if king_id is None:
        return None

    alive_ids = {p.id for p in game.get_alive_players()}

    # KING đã chết → tất cả thắng
    if king_id not in alive_ids:
        return "Tất Cả — KING đã bị tiêu diệt!"

    # KING sống đủ 5 đêm → KING thắng
    nights_passed = getattr(game, "night_count", 0)
    if nights_passed >= _KING_SURVIVE_NIGHTS:
        return "👑 KING — Sống Sót 5 Đêm!"

    return None


# ══════════════════════════════════════════════════════════════════════
# §6  KING MODE SETUP
# ══════════════════════════════════════════════════════════════════════

async def king_night_reminder(game):
    """
    Gửi DM nhắc nhở cho KING vào đầu mỗi đêm: còn bao nhiêu đêm cần sống sót.
    Gọi từ phase_night() trong game.py khi super_gamemode_id == "king".
    """
    import disnake
    king_id = getattr(game, "super_king_id", None)
    if king_id is None:
        return

    alive_ids = {p.id for p in game.get_alive_players()}
    if king_id not in alive_ids:
        return   # KING đã chết, không cần nhắc

    nights_passed   = getattr(game, "night_count", 0)
    nights_remaining = max(0, _KING_SURVIVE_NIGHTS - nights_passed)

    king_member = game._players_dict.get(king_id)
    if not king_member:
        return

    try:
        if nights_remaining <= 0:
            return  # _check_win_king sẽ xử lý
        embed = disnake.Embed(
            title       = f"👑 ĐÊM {nights_passed} — CÒN {nights_remaining} ĐÊM!",
            description = (
                f"Bạn đã sống sót qua **{nights_passed}/{_KING_SURVIVE_NIGHTS} đêm**.\n"
                f"Hãy tiếp tục — chỉ còn **{nights_remaining} đêm** nữa để chiến thắng!"
            ),
            color = 0xe74c3c,
        )
        await king_member.send(embed=embed)
    except Exception:
        pass
    """
    Được gọi sau phase_distribute_roles() khi chế độ KING bật.
    Chọn ngẫu nhiên 1 người làm KING và DM thông báo cho họ.
    """
    import random, disnake

    alive  = game.get_alive_players()
    if not alive:
        return

    king   = random.choice(alive)
    game.super_king_id = king.id
    game.logger.info(f"[KingMode] KING được chọn: {king.display_name} ({king.id})")

    # DM thông báo bí mật cho KING
    try:
        embed = disnake.Embed(
            title       = "👑 BẠN LÀ KING!",
            description = (
                "Bạn được bí mật chọn làm **KING** trong trận đấu này.\n\n"
                "Cả ba phe đều biết có một KING tồn tại — và họ sẽ hợp tác\n"
                "để **tìm ra và tiêu diệt** bạn.\n\n"
                "⚔️ **Hãy sống sót đủ 5 đêm → bạn thắng!**\n"
                "💀 Nếu bạn chết trước đó → tất cả mọi người thắng."
            ),
            color = 0xe74c3c,
        )
        await king.send(embed=embed)
    except Exception:
        pass

    # Thông báo công khai
    await game.text_channel.send(
        embed=disnake.Embed(
            title       = "👑 KING MODE — BẮT ĐẦU!",
            description = (
                "Một **KING** bí ẩn đã được chọn trong số các người chơi.\n\n"
                "⚔️ Cả ba phe hợp tác — tìm ra và **giết** KING.\n"
                "🏆 KING chết → **tất cả cùng chiến thắng**.\n"
                "👑 KING sống sót qua **5 đêm** → **KING thắng một mình**."
            ),
            color = 0xe74c3c,
        )
    )


# ══════════════════════════════════════════════════════════════════════
# §7  FRENCH TRANSLATIONS  (game_language = "fr")
# ══════════════════════════════════════════════════════════════════════

FR_STRINGS: dict[str, str] = {
    # Phases
    "night_start":       "🌙 **La nuit tombe sur Anomalies...**",
    "day_start":         "☀️ **Le soleil se lève. Un nouveau jour commence.**",
    "vote_start":        "🗳️ **Il est temps de voter l'expulsion !**",
    "game_start":        "🎮 **La partie commence ! Distribution des rôles...**",
    "game_end_survivor": "🎉 **Les Survivants ont gagné !** La menace est éliminée.",
    "game_end_anomaly":  "💀 **Les Anomalies ont gagné !** L'obscurité règne.",
    "game_end_unknown":  "🎭 **L'Entité Inconnue a gagné !** Personne ne l'a vu venir.",
    "exile_vote":        "☠️ **{name}** a été expulsé par le village.",
    "no_death":          "😮 **Personne n'est mort cette nuit.** Le village est soulagé... pour l'instant.",
    "death_night":       "💀 **{name}** a été trouvé mort ce matin.",
    "waiting":           "En attente de **{min_p}** joueurs...",
    "player_joined":     "✅ **{name}** a rejoint le lobby !",
    "player_left":       "👋 **{name}** a quitté le lobby.",
    "already_joined":    "✅ Vous êtes déjà dans le lobby !",
    "game_running":      "❌ Une partie est en cours. Veuillez attendre.",
    "lobby_full":        "❌ Le lobby est plein !",
    "skip_discussion":   "⏩ Vote pour raccourcir la discussion",
    "lobby_embed_title": "🔴 》ANOMALIES《",
    "in_game_title":     "🔥 PARTIE EN COURS",
    "in_game_desc":      "Veuillez attendre la fin de la partie.",
}


def get_string(key: str, lang: str = "vi", **kwargs) -> str:
    """Lấy chuỗi theo ngôn ngữ. Mặc định tiếng Việt (trả về key gốc)."""
    if lang == "fr" and key in FR_STRINGS:
        s = FR_STRINGS[key]
        try:
            return s.format(**kwargs)
        except KeyError:
            return s
    return key   # caller tự xử lý chuỗi tiếng Việt gốc
