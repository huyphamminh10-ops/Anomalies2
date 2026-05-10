# ==============================
# game_engine.py — Anomalies v3.1
# Production-ready | 65+ players | Extensible
# ==============================
#
# ✅ Hệ thống bao gồm:
#  1. Action Priority System
#  2. Voice Control (batch + parliament mode)
#  3. Dead & Spectator System
#  4. Fail-Safe & Anti-Crash
#  5. Internal Logger & Debug Mode
#  6. Dynamic Balance Helper
#  7. Performance Optimization (alive cache)
#  8. Voting System Upgrade (anon/public/weighted/revote/skip)
#  9. Anti-Chaos System (role tiers, Large Server Mode)
# 10. Extensible Role Framework (priority, cooldown, max_uses, is_unique)
# 11. Win Condition Refactor (team/solo/hidden)
# 12. GameConfig System Nâng Cao
# 13. Anti-Abuse Protection
# 14. Future-Proof System (season/event/ranked hooks)
# 15. Event Role Integration (Blind, Pro Tester, Cipher Breaker)
# ==============================

from __future__ import annotations
import os as _os, sys as _sys
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
for _candidate in [_BASE_DIR, _os.path.dirname(_BASE_DIR)]:
    _core = _os.path.join(_candidate, "core")
    if _os.path.isdir(_core) and _core not in _sys.path:
        _sys.path.insert(0, _core)
del _os, _sys, _BASE_DIR, _candidate, _core


import asyncio
import copy
import inspect
import math
import os
import random
import time
import traceback
import uuid
from config_manager import load_guild_config, save_guild_config, clear_active_players
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import disnake


# ══════════════════════════════════════════════════════════════════════
# §AI  AI NARRATOR — Tường thuật sự kiện chết/hành động bằng Gemini AI
# ══════════════════════════════════════════════════════════════════════

try:
    from google import genai as _genai
    from google.genai import types as _genai_types
    _NARRATOR_GENAI_OK = True
except Exception:
    _genai = None           # type: ignore
    _genai_types = None     # type: ignore
    _NARRATOR_GENAI_OK = False

def _narrator_api_key() -> str:
    for _k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        _v = (os.environ.get(_k) or "").strip()
        if _v:
            return _v
    return ""

_NARRATOR_MODEL = (os.environ.get("GEMINI_MODEL") or "gemini-2.0-flash").strip()

# Model riêng cho narrator kết thúc trận — dùng Gemini 2.5 Flash
_NARRATOR_ENDING_MODEL = "gemini-2.5-flash-preview-05-20"

_NARRATOR_SYSTEM = (
    "Ngươi là NGƯỜI KỂ CHUYỆN huyền bí của trận Ma Sói 'Anomalies'. "
    "Phong cách: tối tăm, thơ mộng, đầy ám ảnh — như một tiểu thuyết kinh dị hạng sang. "
    "Ngôn ngữ: Tiếng Việt. "
    "Độ dài: 1–2 câu ngắn, súc tích, giàu hình ảnh. "
    "TUYỆT ĐỐI không tiết lộ vai trò của bất kỳ ai. "
    "TUYỆT ĐỐI không giải thích, không thêm bình luận ngoài lề. "
    "Chỉ trả về đúng 1 câu tường thuật, không có dấu nháy bao ngoài."
)

_NARRATOR_PROMPTS = {
    "night_death": (
        "Buổi sáng vừa ló dạng tại thị trấn Anomalies. "
        "Hãy viết 1 câu tường thuật ám ảnh mô tả cảnh người ta phát hiện xác chết của {name} trong đêm. "
        "Không tiết lộ vai trò. Không ghi tên vào câu này — câu tường thuật đứng độc lập trước dòng thông báo tên."
    ),
    "exile_death": (
        "Dân làng vừa bỏ phiếu trục xuất {name}. "
        "Hãy viết 1 câu tường thuật ám ảnh kiểu xử tử nơi công cộng — súng nổ, đám đông, sự im lặng sau đó. "
        "Không tiết lộ vai trò. Câu tường thuật đứng độc lập trước dòng thông báo tên."
    ),
    "night_action": (
        "Đêm nay tại Anomalies, {actor} ({role_hint}) đã thực hiện một hành động bí ẩn nhắm vào {target}. "
        "Hãy viết 1 câu tường thuật mơ hồ, ám ảnh mô tả hành động đó mà KHÔNG tiết lộ vai trò cụ thể. "
        "Câu phải gợi lên không khí đêm tối và sự nguy hiểm rình rập."
    ),
}


_NARRATOR_ENDING_SYSTEM = (
    "Ngươi là NGƯỜI KỂ CHUYỆN huyền bí của trận Ma Sói 'Anomalies'. "
    "Phong cách: tối tăm, thơ mộng, sử thi — như đoạn kết của một tiểu thuyết kinh dị hạng sang. "
    "Ngôn ngữ: Tiếng Việt. "
    "Độ dài: 3–5 câu giàu hình ảnh, đầy cảm xúc, mang tính tổng kết và ám ảnh. "
    "TUYỆT ĐỐI không tiết lộ vai trò cụ thể của bất kỳ ai. "
    "TUYỆT ĐỐI không giải thích hay thêm bình luận ngoài lề. "
    "Chỉ trả về đúng đoạn tường thuật kết thúc, không có dấu nháy bao ngoài."
)

_NARRATOR_ENDING_PROMPTS = {
    # Phe Người Sống Sót thắng
    "survivor_win": (
        "Trận Anomalies vừa kết thúc với chiến thắng thuộc về Phe Người Sống Sót. "
        "Tổng số người chơi: {total}. Số người sống sót đến cuối: {survivors}. "
        "Có {eliminated} người đã bị loại trong suốt cuộc chiến. "
        "Hãy viết một đoạn tường thuật 3–5 câu mô tả khoảnh khắc bình minh trở lại sau đêm dài kinh hoàng — "
        "sự nhẹ nhõm, nỗi đau mất mát, và hy vọng le lói dù thị trấn vẫn còn đầy vết thương. "
        "Không nhắc đến tên người chơi hay vai trò cụ thể."
    ),
    # Phe Dị Thể thắng
    "anomaly_win": (
        "Trận Anomalies vừa kết thúc với chiến thắng thuộc về Phe Dị Thể. "
        "Tổng số người chơi: {total}. Các Dị Thể đã chiếm ưu thế hoàn toàn. "
        "Có {eliminated} người đã gục ngã trước bóng tối. "
        "Hãy viết một đoạn tường thuật 3–5 câu mô tả khoảnh khắc thị trấn hoàn toàn rơi vào tay bóng tối — "
        "sự im lặng chết chóc, những tiếng thì thầm kỳ dị, và thế giới đã không còn như trước. "
        "Không nhắc đến tên người chơi hay vai trò cụ thể."
    ),
    # Thực Thể Không Xác Định thắng (solo win)
    "unknown_win": (
        "Trận Anomalies vừa kết thúc với một kẻ bí ẩn giành chiến thắng: {winner_name}. "
        "Không thuộc về phe nào, không theo quy tắc của ai — kẻ đó chơi một ván cờ riêng và thắng. "
        "Tổng số người chơi: {total}. Có {eliminated} người đã bị loại trước khi trận kết thúc. "
        "Hãy viết một đoạn tường thuật 3–5 câu mô tả khoảnh khắc cả hai phe nhận ra "
        "mình đã bị thao túng từ đầu bởi một thế lực thứ ba vô hình — "
        "sự kinh ngạc, phản bội, và cái cúi đầu bất lực trước số phận. "
        "Không nhắc đến tên người chơi hay vai trò cụ thể."
    ),
}

# Ảnh embed theo từng loại kết thúc
_ENDING_IMAGES = {
    "survivor_win": "https://cdn.discordapp.com/attachments/1400774089664364636/1503143917728829551/Sunrise.jpg?ex=6a02475d&is=6a00f5dd&hm=baf5408ee7c6d69d482f474cef16c3e1f94af1adc61ed865fbd0e55ea64615c2&",
    "anomaly_win":  "https://cdn.discordapp.com/attachments/1400774089664364636/1503143934921019473/Love_never_dies_a_natural_death__She_dies_from_blindness_mistakes_and_betrayals..jpg?ex=6a024761&is=6a00f5e1&hm=281b146228e7263a6b602ead161ea44581bb7e92a4dba4a2ab224a6a3f163937&",
    "unknown_win":  "https://cdn.discordapp.com/attachments/1400774089664364636/1503143947420041376/Picsart_26-05-10_21-20-40-952.jpg?ex=6a024764&is=6a00f5e4&hm=9562f0700e1483af1770c8091ecb79448c74097e6d6d3b14bb5b70a2ced17cbb&",
}


async def _ai_narrate_ending(ending_type: str, **kwargs) -> str:
    """
    Gọi Gemini 2.5 Flash để sinh câu dẫn chuyện kết thúc trận.
    ending_type: 'survivor_win' | 'anomaly_win' | 'unknown_win'
    Trả về chuỗi rỗng nếu lỗi hoặc không có API key.
    """
    if not _NARRATOR_GENAI_OK:
        return ""
    api_key = _narrator_api_key()
    if not api_key:
        return ""

    prompt_template = _NARRATOR_ENDING_PROMPTS.get(ending_type, "")
    if not prompt_template:
        return ""

    try:
        prompt = prompt_template.format(**kwargs)
    except KeyError:
        return ""

    try:
        client = _genai.Client(api_key=api_key)
        cfg = _genai_types.GenerateContentConfig(
            system_instruction=_NARRATOR_ENDING_SYSTEM,
            temperature=1.2,
            top_p=0.97,
        )
        resp = await client.aio.models.generate_content(
            model=_NARRATOR_ENDING_MODEL,
            contents=prompt,
            config=cfg,
        )
        text = (getattr(resp, "text", "") or "").strip()
        return text
    except Exception as _e:
        print(f"[NarratorEnding] Lỗi Gemini: {_e}")
        return ""


async def _ai_narrate(event_type: str, **kwargs) -> str:
    """
    Gọi Gemini AI để sinh câu tường thuật. Trả về chuỗi rỗng nếu lỗi.
    event_type: 'night_death' | 'exile_death' | 'night_action'
    Dùng chung GEMINI_API_KEY với GeminiHost — không cần key riêng.
    """
    if not _NARRATOR_GENAI_OK:
        return ""
    api_key = _narrator_api_key()
    if not api_key:
        return ""

    prompt_template = _NARRATOR_PROMPTS.get(event_type, "")
    if not prompt_template:
        return ""

    try:
        prompt = prompt_template.format(**kwargs)
    except KeyError:
        return ""

    try:
        client = _genai.Client(api_key=api_key)
        cfg = _genai_types.GenerateContentConfig(
            system_instruction=_NARRATOR_SYSTEM,
            temperature=1.1,
            top_p=0.95,
        )
        resp = await client.aio.models.generate_content(
            model=_NARRATOR_MODEL,
            contents=prompt,
            config=cfg,
        )
        text = (getattr(resp, "text", "") or "").strip()
        return text
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════
# §0  HẰNG SỐ MẶC ĐỊNH
# ══════════════════════════════════════════════════════════════════════

ROLE_DISTRIBUTE_TIME = 15
NIGHT_TIME           = 45
DAY_TIME             = 90
VOTE_TIME            = 30
SKIP_THRESHOLD       = 0.6

TEAM_SURVIVOR = "Survivors"
TEAM_ANOMALY  = "Anomalies"
TEAM_UNKNOWN  = "Unknown"
TEAM_UNKNOWN2 = "Unknown Entities"

# Action priority constants — lower = runs first
PRIORITY_BLOCK      = 10   # Dark-Architect, Jailor block
PRIORITY_PROTECT    = 20   # Architect, Trapper protect
PRIORITY_INVESTIGATE= 30   # Investigator, Overseer, Spy
PRIORITY_CONTROL    = 40   # Puppeteer, Jailor control
PRIORITY_KILL       = 50   # Anomaly kill, Harbinger
PRIORITY_CLEANUP    = 60   # Janitor, Glitch-Worm cleanup
PRIORITY_PASSIVE    = 70   # Sleeper report, TimeWeaver snapshot


# ══════════════════════════════════════════════════════════════════════
# §1  GAME CONFIG
# ══════════════════════════════════════════════════════════════════════

class GameConfig:
    """
    Centralised configuration for one game session.
    Pass as `config=GameConfig(...)` to GameEngine.
    """

    def __init__(
        self,
        # Player limits
        max_players: int = 65,
        min_players: int = 5,

        # Voice
        allow_voice: bool = True,
        mute_dead: bool = True,
        no_remove_roles: bool = False,
        voice_mode: str = "free",          # "free" | "parliament"
        parliament_seconds: int = 60,       # seconds per speaker in parliament mode
        voice_batch_size: int = 5,
        voice_batch_delay: float = 0.4,    # seconds between batches

        # Voting
        anonymous_vote: bool = False,
        allow_skip: bool = True,
        weighted_vote: bool = True,
        revote_on_tie: bool = True,
        max_revotes: int = 1,

        # Fail-safe
        auto_random_if_no_action: bool = True,  # random target if role idle
        dm_fallback_to_public: bool = True,

        # Scale
        large_server_mode: bool = False,   # auto-enable if players >= 40
        large_server_threshold: int = 40,

        # Debug
        debug_mode: bool = False,
        save_crash_log: bool = True,
        log_dir: str = "logs",

        # Future-proof hooks
        season_mode: Optional[str] = None,   # e.g. "halloween"
        event_mode: Optional[str] = None,
        ranked_mode: bool = False,

        # Anti-chaos
        max_night_actors: int = 20,          # ignored if 0

        # Role IDs
        dead_role_id: Optional[int] = None,
        alive_role_id: Optional[int] = None,

        # Channel IDs (lưu để tham chiếu, không dùng trực tiếp trong engine)
        text_channel_id: Optional[int] = None,
        voice_channel_id: Optional[int] = None,
        category_id: Optional[int] = None,

        # Misc
        skip_discussion_delay: int = 30,
        role_distribute_time: int = ROLE_DISTRIBUTE_TIME,
        night_time: int = NIGHT_TIME,
        day_time: int = DAY_TIME,
        vote_time: int = VOTE_TIME,
        skip_threshold: float = SKIP_THRESHOLD,
    ):
        self.max_players               = max_players
        self.min_players               = min_players
        self.allow_voice               = allow_voice
        self.no_remove_roles           = no_remove_roles
        self.mute_dead                 = False if no_remove_roles else mute_dead
        self.voice_mode                = voice_mode
        self.parliament_seconds        = parliament_seconds
        self.voice_batch_size          = voice_batch_size
        self.voice_batch_delay         = voice_batch_delay
        self.anonymous_vote            = anonymous_vote
        self.allow_skip                = allow_skip
        self.weighted_vote             = weighted_vote
        self.revote_on_tie             = revote_on_tie
        self.max_revotes               = max_revotes
        self.auto_random_if_no_action  = auto_random_if_no_action
        self.dm_fallback_to_public     = dm_fallback_to_public
        self.large_server_mode         = large_server_mode
        self.large_server_threshold    = large_server_threshold
        self.debug_mode                = debug_mode
        self.save_crash_log            = save_crash_log
        self.log_dir                   = log_dir
        self.season_mode               = season_mode
        self.event_mode                = event_mode
        self.ranked_mode               = ranked_mode
        self.max_night_actors          = max_night_actors
        self.dead_role_id              = dead_role_id
        self.alive_role_id             = alive_role_id
        self.text_channel_id           = text_channel_id
        self.voice_channel_id          = voice_channel_id
        self.category_id               = category_id
        self.skip_discussion_delay     = skip_discussion_delay
        self.role_distribute_time      = role_distribute_time
        self.night_time                = night_time
        self.day_time                  = day_time
        self.vote_time                 = vote_time
        self.skip_threshold            = skip_threshold

    def auto_adjust(self, player_count: int):
        """Auto-enable large_server_mode and tune timings."""
        if player_count >= self.large_server_threshold:
            self.large_server_mode = True
        if self.large_server_mode:
            # Give more time in large games
            self.night_time = max(self.night_time, 60)
            self.day_time   = max(self.day_time, 120)
            self.vote_time  = max(self.vote_time, 45)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


# ══════════════════════════════════════════════════════════════════════
# §2  INTERNAL LOGGER
# ══════════════════════════════════════════════════════════════════════

class GameLogger:
    """
    Lightweight in-memory logger.  Writes crash log on demand.
    """

    def __init__(self, game_id: str, debug: bool = False, log_dir: str = "logs"):
        self.game_id  = game_id
        self.debug_mode = debug
        self.log_dir  = log_dir
        self._entries: List[Tuple[str, str, str]] = []

    def _record(self, level: str, msg: str):
        ts = datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]
        self._entries.append((ts, level, msg))
        if self.debug_mode or level in ("ERROR", "FATAL"):
            print(f"[{self.game_id}][{ts}][{level}] {msg}")

    def info(self, msg: str):  self._record("INFO",  msg)
    def warn(self, msg: str):  self._record("WARN",  msg)
    def error(self, msg: str): self._record("ERROR", msg)
    def debug(self, msg: str):
        if self.debug_mode:
            self._record("DEBUG", msg)

    def dump_to_file(self):
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            path = os.path.join(self.log_dir, f"{self.game_id}.txt")
            with open(path, "w", encoding="utf-8") as f:
                for ts, level, msg in self._entries:
                    f.write(f"[{ts}][{level}] {msg}\n")
            print(f"[Logger] Saved log → {path}")
        except Exception as e:
            print(f"[Logger] Failed to write log: {e}")

    def get_recent(self, n: int = 30) -> str:
        lines = [f"[{ts}][{level}] {msg}" for ts, level, msg in self._entries[-n:]]
        return "\n".join(lines)

# ══════════════════════════════════════════════════════════════════════
# §3  PLAYER WRAPPER & PROXIES  (backward-compat)
# ══════════════════════════════════════════════════════════════════════

class _PlayerWrapper:
    def __init__(self, member, role, game):
        self._member = member
        self._role   = role
        self._game   = game

    def __getattr__(self, item):
        return getattr(self._member, item)

    @property
    def display_name(self):
        return self._member.display_name

    def __str__(self):
        return self._member.display_name

    # FIX: __repr__ trả về tên thay vì object address — tránh hiện "<game._PlayerWrapper object at 0x...>"
    def __repr__(self):
        return self._member.display_name

    @property
    def alive(self):   return self._game.is_alive(self._member.id)
    @property
    def faction(self):
        if self._role:
            return getattr(self._role, "faction", None) or getattr(self._role, "team", "?")
        return "?"
    @property
    def name(self):  return self._member.display_name
    @property
    def id(self):    return self._member.id


class _ChoiceView(disnake.ui.View):
    def __init__(self, members, timeout=30):
        super().__init__(timeout=timeout)
        self.chosen     = members[0] if members else None
        self.members_map = {m.id: m for m in members}
        options = [disnake.SelectOption(label=m.display_name, value=str(m.id)) for m in members]
        self.add_item(self._ChoiceSelect(self, options))

    class _ChoiceSelect(disnake.ui.Select):
        def __init__(self, view_ref, options):
            super().__init__(placeholder="Chọn mục tiêu...", options=options[:25], min_values=1, max_values=1)
            self.view_ref = view_ref
        async def callback(self, interaction: disnake.ApplicationCommandInteraction):
            chosen_id = int(self.values[0])
            self.view_ref.chosen = self.view_ref.members_map.get(chosen_id)
            await interaction.response.send_message("✅ Đã chọn!", ephemeral=True)
            self.view_ref.stop()


class _PlayersProxy:
    def __init__(self, engine):
        self._engine = engine
    def __getitem__(self, pid):   return self._engine._players_dict[pid]
    def __setitem__(self, pid, v): self._engine._players_dict[pid] = v
    def get(self, pid, default=None): return self._engine._players_dict.get(pid, default)
    def items(self):   return self._engine._players_dict.items()
    def values(self):  return self._engine._players_dict.values()
    def keys(self):    return self._engine._players_dict.keys()
    def update(self, d): self._engine._players_dict.update(d)
    def pop(self, key, *args): return self._engine._players_dict.pop(key, *args)
    def __iter__(self):
        for pid, member in self._engine._players_dict.items():
            yield _PlayerWrapper(member, self._engine.roles.get(pid), self._engine)
    def __len__(self):   return len(self._engine._players_dict)
    def __contains__(self, item): return item in self._engine._players_dict


# ══════════════════════════════════════════════════════════════════════
# §4  ACTION PRIORITY SYSTEM
# ══════════════════════════════════════════════════════════════════════

class NightAction:
    """
    Represents a single night action registered by a role.

    Roles call  game.register_action(NightAction(...))  inside send_ui /
    send_night_ui.  The engine sorts by priority and resolves in order.
    """

    def __init__(
        self,
        actor_id: int,
        role_name: str,
        priority: int,
        handler,          # async callable(game) → None
        target_id: Optional[int] = None,
        bypass_block: bool = False,
        bypass_protection: bool = False,
        faction: str = "Unknown",
    ):
        self.actor_id          = actor_id
        self.role_name         = role_name
        self.priority          = priority
        self.handler           = handler
        self.target_id         = target_id
        self.bypass_block      = bypass_block
        self.bypass_protection = bypass_protection
        self.faction           = faction
        self.cancelled         = False   # set True if actor gets blocked


class ActionQueue:
    """Collects and resolves NightActions in priority order."""

    def __init__(self):
        self._queue: List[NightAction] = []

    def register(self, action: NightAction):
        self._queue.append(action)

    def clear(self):
        self._queue.clear()

    def get_sorted(self) -> List[NightAction]:
        return sorted(self._queue, key=lambda a: a.priority)

    async def resolve(self, game: "GameEngine"):
        for action in self.get_sorted():
            if action.cancelled:
                game.logger.debug(f"Action skipped (cancelled): {action.role_name}")
                continue
            # Block check
            if action.actor_id in game.blocked and not action.bypass_block:
                game.logger.info(f"{action.role_name} blocked, skipping action.")
                continue
            # Dead check (actor died earlier this night)
            if not game.is_alive(action.actor_id):
                continue
            try:
                await action.handler(game)
                game.logger.debug(f"Action resolved: {action.role_name} (priority={action.priority})")
            except Exception as e:
                game.logger.error(f"Action error [{action.role_name}]: {e}\n{traceback.format_exc()}")
                # Do NOT crash the game — safe continue


# ══════════════════════════════════════════════════════════════════════
# §5  DYNAMIC BALANCE HELPER
# ══════════════════════════════════════════════════════════════════════

class BalanceHelper:
    """Advanced balance validation and role suggestions."""

    ANOMALY_WARN_PCT  = 0.35
    UNKNOWN_WARN_COUNT = 4

    # Suggested role ratios per bracket
    SUGGESTIONS = [
        (5,  10, "2-3 Civilian, 1-2 Anomaly, 1 Unknown (Serial Killer)"),
        (10, 20, "5-6 Survivor roles, 3-4 Anomaly, 1-2 Unknown"),
        (20, 35, "12 Survivors, 6-7 Anomalies, 2-3 Unknown"),
        (35, 50, "22 Survivors, 10-11 Anomalies, 3-4 Unknown"),
        (50, 65, "30 Survivors, 15 Anomalies, 4-5 Unknown"),
        (65, 99, "39 Survivors, 18 Anomalies, 5-6 Unknown"),
    ]

    @classmethod
    def validate(cls, roles: dict, config: GameConfig) -> Tuple[bool, List[str]]:
        warnings = []
        total = len(roles)
        if total == 0:
            return False, ["No roles assigned"]

        counts: Dict[str, int] = defaultdict(int)
        for role in roles.values():
            team = getattr(role, "team", "Unknown")
            counts[team] += 1

        survivors = counts.get(TEAM_SURVIVOR, 0)
        anomalies = counts.get(TEAM_ANOMALY, 0)
        unknowns  = total - survivors - anomalies

        # Anomalies % check
        if total > 0 and anomalies / total > cls.ANOMALY_WARN_PCT:
            warnings.append(
                f"⚠️ Anomalies chiếm {anomalies/total:.0%} > {cls.ANOMALY_WARN_PCT:.0%} — quá nhiều!"
            )

        # Unknown count check
        if unknowns > cls.UNKNOWN_WARN_COUNT:
            warnings.append(
                f"⚠️ Unknown Entities = {unknowns} — quá nhiều, khó kiểm soát!"
            )

        # Survivors must outnumber Anomalies
        if survivors <= anomalies:
            warnings.append(
                f"⚠️ Survivors ({survivors}) ≤ Anomalies ({anomalies}) — game mất cân bằng!"
            )

        # Large server specific
        if config.large_server_mode and anomalies > 20:
            warnings.append("⚠️ Large Server Mode: Anomalies > 20 có thể áp đảo!")

        # Unique role duplicates check
        unique_names: Set[str] = set()
        for role in roles.values():
            is_unique = getattr(role, "is_unique", False)
            if is_unique:
                if role.name in unique_names:
                    warnings.append(f"🔴 Role unique '{role.name}' bị trùng lặp!")
                unique_names.add(role.name)

        ok = len([w for w in warnings if w.startswith("🔴")]) == 0
        return ok, warnings

    @classmethod
    def suggest(cls, player_count: int) -> str:
        for lo, hi, text in cls.SUGGESTIONS:
            if lo <= player_count < hi:
                return f"📊 **Gợi ý ({player_count} người):** {text}"
        return f"📊 **Gợi ý:** Dùng tỉ lệ 60% Survivors / 30% Anomalies / 10% Unknown"


# ══════════════════════════════════════════════════════════════════════
# §6  VOICE CONTROL SYSTEM
# ══════════════════════════════════════════════════════════════════════

class VoiceController:
    """
    Handles batch mute/unmute with configurable delay.
    Supports free mode and parliament mode.
    """

    def __init__(self, config: GameConfig, logger: GameLogger):
        self.config = config
        self.logger = logger
        self._parliament_task: Optional[asyncio.Task] = None

    async def set_mute(self, members: List[disnake.Member], muted: bool):
        """Batch mute/unmute with small delay per batch."""
        if not self.config.allow_voice:
            return

        if muted:
            # Khi mute: chỉ xử lý người đang trong voice
            targets = [m for m in members if m.voice is not None]
        else:
            # Khi unmute: thử tất cả (Discord voice cache có thể cũ)
            targets = list(members)

        in_voice = targets
        if not in_voice:
            return

        batch_size  = self.config.voice_batch_size
        batch_delay = self.config.voice_batch_delay

        for i in range(0, len(in_voice), batch_size):
            batch = in_voice[i:i + batch_size]
            tasks = []
            for member in batch:
                tasks.append(self._try_mute(member, muted))
            await asyncio.gather(*tasks, return_exceptions=True)
            if i + batch_size < len(in_voice):
                await asyncio.sleep(batch_delay)

        action = "muted" if muted else "unmuted"
        self.logger.debug(f"Voice: {action} {len(in_voice)} members in voice")

    async def _try_mute(self, member: disnake.Member, muted: bool, _retries: int = 3):
        for attempt in range(_retries):
            try:
                await member.edit(mute=muted)
                return
            except disnake.Forbidden:
                self.logger.warn(f"No permission to mute {member.display_name}")
                return
            except disnake.HTTPException as e:
                if e.status == 400:
                    return  # member not in voice — bỏ qua
                if e.status == 429:
                    retry_after = float(getattr(e, "retry_after", 1.0) or 1.0)
                    self.logger.warn(f"Rate limit muting {member.display_name}, retry in {retry_after:.1f}s")
                    await asyncio.sleep(retry_after)
                    continue
                self.logger.warn(f"HTTP {e.status} muting {member.display_name}: {e}")
                return

    async def start_parliament(self, members: List[disnake.Member], channel: disnake.TextChannel):
        """Parliament mode: each living member speaks for X seconds in order."""
        if self.config.voice_mode != "parliament":
            return
        if self._parliament_task and not self._parliament_task.done():
            self._parliament_task.cancel()
        self._parliament_task = asyncio.create_task(
            self._parliament_loop(members, channel)
        )

    async def _parliament_loop(self, members: List[disnake.Member], channel: disnake.TextChannel):
        secs = self.config.parliament_seconds
        try:
            for member in members:
                try:
                    rest = [m for m in members if m.id != member.id]
                    await self.set_mute([member], False)
                    await self.set_mute(rest, True)
                    await channel.send(
                        f"🎤 **{member.display_name}** đang phát biểu ({secs}s)...",
                        delete_after=secs
                    )
                    await asyncio.sleep(secs)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"Parliament error: {e}")
        finally:
            # LUÔN unmute tất cả khi parliament kết thúc (dù bình thường hay bị huỷ)
            try:
                await self.set_mute(members, False)
            except Exception:
                pass

    def stop_parliament(self):
        if self._parliament_task and not self._parliament_task.done():
            self._parliament_task.cancel()


# ══════════════════════════════════════════════════════════════════════
# §7  DEAD CHAT SYSTEM
# ══════════════════════════════════════════════════════════════════════

class AnomalyChatManager:
    """
    Quản lý kênh chat bí mật dành riêng cho phe Anomalies.
    - Chỉ thành viên Anomalies (và Psychopath) có quyền đọc/ghi.
    - Bot gửi daily log tình hình sau mỗi đêm.
    - Các role Survivor điều tra trúng Anomaly sẽ gửi cảnh báo ẩn danh vào đây.
    """

    def __init__(self, logger):
        self.logger  = logger
        self.channel: Optional[disnake.TextChannel] = None

    # ── Tạo kênh ──────────────────────────────────────────────────────────────
    async def create(self, guild: disnake.Guild, category=None, fallback_channel=None):
        """
        Luôn tạo PRIVATE THREAD trong `fallback_channel` (text_channel chính của game),
        bất kể có hay không có category.
        """
        self.is_thread = False
        if fallback_channel is not None:
            try:
                self.channel = await fallback_channel.create_thread(
                    name="🔴 Anomalies Chat",
                    type=disnake.ChannelType.private_thread,
                    invitable=False,
                    auto_archive_duration=1440,
                    reason="Anomalies Game — Anomaly Chat",
                )
                self.is_thread = True
                self.logger.info(f"Anomaly Chat created as private thread: #{self.channel.name}")
                return
            except Exception as e:
                self.logger.error(f"Failed to create Anomaly Chat thread: {e}")
        else:
            self.logger.error("Anomaly Chat: không có fallback_channel để tạo private thread.")

    # ── Cấp quyền cho 1 thành viên (đọc + ghi) ────────────────────────────────
    async def add_member(self, member, send: bool = True):
        """Cho phép một thành viên đọc/ghi kênh (hoặc add vào thread)."""
        if not self.channel:
            return
        try:
            if getattr(self, "is_thread", False):
                await self.channel.add_user(member)
            else:
                await self.channel.set_permissions(
                    member,
                    read_messages=True,
                    send_messages=send,
                )
        except Exception as e:
            self.logger.warn(f"Anomaly Chat: cannot add {member.display_name}: {e}")

    # ── Cấp quyền chỉ đọc (dành cho Psychopath) ───────────────────────────────
    async def add_spectator(self, member):
        """Cho phép một thành viên chỉ đọc (không ghi)."""
        await self.add_member(member, send=False)

    # ── Gửi tin nhắn vào kênh ─────────────────────────────────────────────────
    async def send(self, content: str = "", embed=None):
        if not self.channel:
            return
        try:
            await self.channel.send(content, embed=embed)
        except Exception as e:
            self.logger.warn(f"Anomaly Chat send error: {e}")

    # ── Gửi daily log sau mỗi đêm ────────────────────────────────────────────
    async def send_daily_log(self, game):
        """Gửi tóm tắt tình hình mỗi sáng để Anomalies nắm thông tin."""
        if not self.channel:
            return

        alive_survivors  = [
            p for p in game.get_alive_players()
            if getattr(game.roles.get(p.id), "team", "") == "Survivors"
        ]
        alive_anomalies  = [
            p for p in game.get_alive_players()
            if getattr(game.roles.get(p.id), "team", "") == "Anomalies"
        ]
        alive_unknown    = [
            p for p in game.get_alive_players()
            if getattr(game.roles.get(p.id), "team", "") not in ("Survivors", "Anomalies")
        ]

        total_alive = len(game.get_alive_players())

        embed = disnake.Embed(
            title=f"📊 BÁO CÁO ĐÊM {game.night_count} — ANOMALIES INTEL",
            description=(
                "Thông tin tình hình trận đấu sau đêm vừa qua.\n"
                "Hãy lên kế hoạch cẩn thận cho đêm tiếp theo. 🩸"
            ),
            color=0xe74c3c
        )
        embed.add_field(
            name="👥 Người Còn Sống",
            value=(
                f"🛡️ **Survivors:** `{len(alive_survivors)}`\n"
                f"🔴 **Anomalies:** `{len(alive_anomalies)}`\n"
                f"❓ **Unknown:** `{len(alive_unknown)}`\n"
                f"📊 **Tổng:** `{total_alive}`"
            ),
            inline=True
        )

        # Danh sách đồng đội Anomalies còn sống
        if alive_anomalies:
            team_lines = "\n".join(
                f"• **{p.display_name}** — {getattr(game.roles.get(p.id), 'name', '?')}"
                for p in alive_anomalies
            )
        else:
            team_lines = "*Không còn ai...*"
        embed.add_field(
            name="🔴 Đồng Đội Còn Sống",
            value=team_lines,
            inline=True
        )

        # Night events dành riêng cho Anomalies
        anomaly_events = [
            text for faction, text in game.night_events
            if faction == "Anomalies"
        ]
        if anomaly_events:
            embed.add_field(
                name="🌙 Sự Kiện Đêm Qua",
                value="\n".join(f"> {e}" for e in anomaly_events[:8]),
                inline=False
            )

        embed.set_footer(text="🤫 Chỉ phe Anomalies mới thấy kênh này | Giữ bí mật!")

        try:
            await self.channel.send(embed=embed)
        except Exception as e:
            self.logger.warn(f"Anomaly Chat daily log error: {e}")

    # ── Xóa kênh khi game kết thúc ────────────────────────────────────────────
    async def delete(self):
        if self.channel:
            try:
                await self.channel.delete(reason="Anomalies Game ended")
            except Exception:
                pass
            self.channel = None


class DeadChatManager:
    """
    Creates and manages a Dead Chat channel.
    Dead players get send-message access; alive players are read-only.
    """

    def __init__(self, logger: GameLogger):
        self.logger    = logger
        self.channel: Optional[disnake.TextChannel] = None
        self._dead_overwrites: Dict[int, disnake.PermissionOverwrite] = {}

    async def create(
        self,
        guild: disnake.Guild,
        category: Optional[disnake.CategoryChannel] = None,
        fallback_channel=None,
    ):
        """
        Luôn tạo PRIVATE THREAD trong `fallback_channel` (text_channel chính của game),
        bất kể có hay không có category.
        """
        self.is_thread = False
        if fallback_channel is not None:
            try:
                self.channel = await fallback_channel.create_thread(
                    name="💀 Dead Chat",
                    type=disnake.ChannelType.private_thread,
                    invitable=False,
                    auto_archive_duration=1440,
                    reason="Anomalies Game — Dead Chat",
                )
                self.is_thread = True
                self.logger.info(f"Dead Chat created as private thread: #{self.channel.name}")
                return
            except Exception as e:
                self.logger.error(f"Failed to create Dead Chat thread: {e}")
        else:
            self.logger.error("Dead Chat: không có fallback_channel để tạo private thread.")

    async def add_dead_player(self, member: disnake.Member):
        """Grant send permissions to a newly dead player."""
        if not self.channel:
            return
        try:
            if getattr(self, "is_thread", False):
                await self.channel.add_user(member)
            else:
                overwrite = disnake.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                )
                await self.channel.set_permissions(member, overwrite=overwrite)
            await self.channel.send(
                f"💀 **{member.display_name}** đã gia nhập Dead Chat.",
                delete_after=30,
            )
        except Exception as e:
            self.logger.warn(f"Could not add {member.display_name} to Dead Chat: {e}")

    async def add_spectator(self, member: disnake.Member):
        """Spectators can read but not write."""
        if not self.channel:
            return
        try:
            if getattr(self, "is_thread", False):
                await self.channel.add_user(member)
                return
            overwrite = disnake.PermissionOverwrite(
                read_messages=True,
                send_messages=False,
            )
            await self.channel.set_permissions(member, overwrite=overwrite)
        except Exception as e:
            self.logger.warn(f"Could not add spectator {member.display_name}: {e}")

    async def delete(self):
        if self.channel:
            try:
                await self.channel.delete(reason="Anomalies Game ended")
            except Exception:
                pass
            self.channel = None


# ══════════════════════════════════════════════════════════════════════
# §8  ANTI-ABUSE TRACKER
# ══════════════════════════════════════════════════════════════════════

class AbuseTracker:
    """Rate-limit interactions per user."""

    COOLDOWN = 2.0   # seconds between interactions

    def __init__(self):
        self._last_action: Dict[int, float] = {}

    def is_allowed(self, user_id: int) -> bool:
        now = time.monotonic()
        last = self._last_action.get(user_id, 0)
        if now - last < self.COOLDOWN:
            return False
        self._last_action[user_id] = now
        return True

    def reset(self, user_id: int):
        self._last_action.pop(user_id, None)

    def clear(self):
        self._last_action.clear()


# ══════════════════════════════════════════════════════════════════════
# §9  WIN CONDITION MANAGER
# ══════════════════════════════════════════════════════════════════════

class WinConditionManager:
    """
    Evaluates win conditions.
    Roles can define:
        win_type = "team"   → wins together with faction
        win_type = "solo"   → check_win_condition(game) → bool
        win_type = "hidden" → resolved at game end by engine
    """

    @staticmethod
    def check(game: "GameEngine") -> Optional[str]:
        if game.ended:
            return game.winner

        alive_ids = game.alive_players - game.temporarily_removed
        if not alive_ids:
            return "Draw"

        def team(pid):
            r = game.roles.get(pid)
            return (getattr(r, "team", None) or getattr(r, "faction", None)) if r else None

        survivors = sum(1 for p in alive_ids if team(p) == TEAM_SURVIVOR)
        anomalies = sum(1 for p in alive_ids if team(p) == TEAM_ANOMALY)
        unknowns  = sum(1 for p in alive_ids if team(p) in (TEAM_UNKNOWN, TEAM_UNKNOWN2))

        # Solo win check — roles with win_type="solo"
        for pid in list(alive_ids):
            role = game.roles.get(pid)
            if not role:
                continue
            wtype = getattr(role, "win_type", "team")
            if wtype != "solo":
                continue
            if not hasattr(role, "check_win_condition"):
                continue
            try:
                sig = inspect.signature(role.check_win_condition)
                params = list(sig.parameters.keys())
                if len(params) != 1:
                    continue
                result = role.check_win_condition(game)
                if inspect.isawaitable(result):
                    result.close()
                    continue
                if result:
                    return role.name
            except Exception:
                pass

        # Anomalies win
        if anomalies >= survivors and anomalies > 0 and unknowns == 0:
            return TEAM_ANOMALY

        # Survivors win
        if anomalies == 0 and unknowns == 0:
            return TEAM_SURVIVOR

        return None


# ══════════════════════════════════════════════════════════════════════
# §10  VOTING SYSTEM
# ══════════════════════════════════════════════════════════════════════

class VotingSession:
    """
    Handles one vote phase with support for:
    - Anonymous / Public display
    - Weighted votes
    - Skip Vote
    - Revote on tie
    """

    def __init__(self, game: "GameEngine", alive_members: List, revote: bool = False):
        self.game          = game
        self.alive_members = alive_members
        self.votes: Dict[int, int]  = {}   # voter_id → target_id
        self.skip_votes: Set[int]   = set()
        self.revote        = revote
        self._phase_active = True
        self._abuse        = game.abuse_tracker

    def record_vote(self, voter_id: int, target_id: int) -> bool:
        """Returns False if rate-limited or invalid."""
        if not self._abuse.is_allowed(voter_id):
            return False
        if not self.game.is_alive(voter_id):
            return False
        if voter_id == target_id:
            return False
        self.votes[voter_id] = target_id
        return True

    def record_skip(self, voter_id: int) -> bool:
        if not self._abuse.is_allowed(voter_id):
            return False
        if not self.game.is_alive(voter_id):
            return False
        self.skip_votes.add(voter_id)
        return True

    def tally(self) -> Dict[int, float]:
        """Returns {target_id: weighted_vote_count}."""
        counts: Dict[int, float] = defaultdict(float)
        cfg = self.game.config
        for voter_id, target_id in self.votes.items():
            # Apply Puppeteer override
            forced = self.game.puppeteer_controls.get(voter_id)
            if forced:
                target_id = forced
            role = self.game.roles.get(voter_id)
            weight = 1.0
            if cfg.weighted_vote and role and hasattr(role, "vote_weight"):
                try:
                    weight = float(role.vote_weight())
                except Exception:
                    weight = 1.0
            counts[target_id] += weight
        return dict(counts)

    def should_skip(self) -> bool:
        """Check if enough skip votes have been cast."""
        if not self.game.config.allow_skip:
            return False
        alive = len(self.game.get_alive_players())
        needed = math.ceil(alive * self.game.config.skip_threshold)
        return len(self.skip_votes) >= needed

    def get_result(self) -> Tuple[Optional[int], str]:
        """
        Returns (target_id, reason).
        target_id = None means no eviction (tie / skip / no votes).
        """
        if self.should_skip():
            return None, "skip"

        counts = self.tally()
        if not counts:
            return None, "no_votes"

        max_v   = max(counts.values())
        leaders = [k for k, v in counts.items() if v == max_v]

        if len(leaders) > 1:
            return None, "tie"

        return leaders[0], "normal"



# ══════════════════════════════════════════════════════════════════════
# §10.5  VOTE VIEW V2 — UI bỏ phiếu công khai cho phase_voting
# ══════════════════════════════════════════════════════════════════════

class VoteViewV2(disnake.ui.View):
    """
    View bỏ phiếu trục xuất cho toàn server.
    - Mỗi người alive chỉ vote được 1 lần (có thể đổi ý).
    - Hỗ trợ anonymous_vote: ẩn tên người vote.
    - Hỗ trợ allow_skip: nút bỏ qua.
    - Tích hợp VotingSession để record vote.
    """

    def __init__(self, game: "GameEngine", alive_members: list, vote_time: int, session: "VotingSession"):
        super().__init__(timeout=vote_time + 5)
        self.game    = game
        self.session = session

        # Select menu chọn người bị trục xuất
        options = [
            disnake.SelectOption(
                label=p.display_name[:100],
                value=str(p.id),
                emoji="🎯"
            )
            for p in alive_members
        ][:25]

        self.add_item(VoteViewV2.VoteSelect(game, session, options))

        # Nút bỏ qua (skip) nếu config cho phép
        if game.config.allow_skip:
            self.add_item(VoteViewV2.SkipButton(session))

    class VoteSelect(disnake.ui.Select):
        def __init__(self, game: "GameEngine", session: "VotingSession", options):
            self.game    = game
            self.session = session
            super().__init__(
                placeholder="🗳️ Chọn người muốn trục xuất...",
                options=options,
                min_values=1,
                max_values=1,
                row=0,
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):
            voter_id  = interaction.user.id
            target_id = int(self.values[0])

            if not self.game.is_alive(voter_id):
                await interaction.response.send_message(
                    "❌ Bạn đã chết và không thể bỏ phiếu.",
                    ephemeral=True
                )
                return

            recorded = self.session.record_vote(voter_id, target_id)
            if not recorded:
                await interaction.response.send_message(
                    "⚠️ Không thể ghi nhận phiếu (rate-limit hoặc không hợp lệ).",
                    ephemeral=True
                )
                return

            target = self.game._players_dict.get(target_id)
            target_name = getattr(target, "display_name", str(target_id))

            if self.game.config.anonymous_vote:
                await interaction.response.send_message(
                    f"🗳️ Phiếu của bạn đã được ghi nhận *(ẩn danh)*.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"🗳️ Bạn đã vote: **{target_name}**",
                    ephemeral=True
                )

    class SkipButton(disnake.ui.Button):
        def __init__(self, session: "VotingSession"):
            self.session = session
            super().__init__(
                label="⏭️ Bỏ qua",
                style=disnake.ButtonStyle.secondary,
                row=1,
            )

        async def callback(self, interaction: disnake.ApplicationCommandInteraction):
            voter_id = interaction.user.id

            if not self.session.game.is_alive(voter_id):
                await interaction.response.send_message(
                    "❌ Bạn đã chết và không thể bỏ phiếu.",
                    ephemeral=True
                )
                return

            recorded = self.session.record_skip(voter_id)
            if not recorded:
                await interaction.response.send_message(
                    "⚠️ Không thể ghi nhận phiếu skip.",
                    ephemeral=True
                )
                return

            alive     = len(self.session.game.get_alive_players())
            needed    = math.ceil(alive * self.session.game.config.skip_threshold)
            current   = len(self.session.skip_votes)
            await interaction.response.send_message(
                f"⏭️ Bỏ qua được ghi nhận. ({current}/{needed} cần thiết)",
                ephemeral=True
            )

# ══════════════════════════════════════════════════════════════════════
# §11  WILL SYSTEM  — Áp dụng cho TẤT CẢ người chơi
# ══════════════════════════════════════════════════════════════════════

MAX_WILL_LINES    = 45
MAX_WILL_CHARS    = 60   # kí tự/dòng (không tính dấu cách)
WILL_TRIGGER      = "Nhập di chúc"


# ── Chuyển số thành emoji chữ số Discord ─────────────────────────────────────
def _num_to_emoji(n: int) -> list:
    """Trả về list các emoji số, mỗi phần tử là 1 emoji để add_reaction riêng."""
    digits = {
        "0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣",
        "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣", "9": "9️⃣",
    }
    return [digits[d] for d in str(n)]


class WillState:
    def __init__(self):
        self.writing_will: bool       = False
        self.will_lines:  List[str]   = []    # các dòng đã confirm
        self.locked:      bool        = False  # không thay đổi được nữa


def get_will_state(game: "GameEngine", member_id: int) -> "WillState":
    if member_id not in game.will_states:
        game.will_states[member_id] = WillState()
    return game.will_states[member_id]


async def handle_will_message(game: "GameEngine", message: disnake.Message) -> bool:
    """STUB — di chúc nay được xử lý hoàn toàn qua DM (handle_will_dm).
    Hàm này giữ nguyên để app.py không bị lỗi import, nhưng luôn trả False.
    """
    return False


async def handle_will_dm(active_games: dict, message: disnake.Message) -> bool:
    """Xử lý toàn bộ cơ chế di chúc trong DM của bot.
    Được gọi từ on_message khi message.guild is None.
    Trả về True nếu đã xử lý (để on_message không gọi handle_owner_dm).
    """
    if message.author.bot:
        return False
    # Chỉ xử lý DM (không có guild)
    if message.guild is not None:
        return False

    uid     = message.author.id
    content = message.content.strip()

    # Tìm game mà người này đang tham gia
    game = None
    for g in active_games.values():
        if uid in g.players:
            game = g
            break

    # ── Trigger: "Nhập di chúc" ──────────────────────────────────────────────
    if content == WILL_TRIGGER:
        if game is None:
            await message.channel.send("❌ Bạn không đang trong trận nào.")
            return True

        # 🔒 Người đã chết không được viết di chúc
        if uid in game.dead_players:
            await message.channel.send("💀 Bạn đã chết — không thể viết di chúc nữa.")
            return True

        ws = get_will_state(game, uid)

        if ws.locked:
            await message.channel.send("🔒 Di chúc của bạn đã bị khóa — không thể chỉnh sửa.")
            return True
        if ws.writing_will:
            await message.channel.send(
                f"📖 Bạn đang trong chế độ ghi di chúc rồi. "
                f"Đã viết **{len(ws.will_lines)}/{MAX_WILL_LINES}** dòng. "
                f"Tiếp tục gửi từng dòng."
            )
            return True

        ws.writing_will = True
        # ✅ FIX: tạo file sẽ có di chúc (rỗng ban đầu) để đánh dấu đã bắt đầu
        game.wills[uid] = ""
        embed = disnake.Embed(
            title="📜 HỆ THỐNG DI CHÚC",
            description=(
                f"Hãy viết di chúc của bạn, Tối đa **{MAX_WILL_LINES} dòng**. "
                f"Mỗi dòng tối đa **{MAX_WILL_CHARS} kí tự** (không tính dấu cách)\n\n"
                "⚠️ **Lưu ý:** Sau khi gửi mỗi dòng, bạn không thể chỉnh sửa dòng đó được nữa."
            ),
            color=0x9b59b6
        )
        embed.set_footer(text=f"Đã viết: 0/{MAX_WILL_LINES} dòng")
        await message.channel.send(embed=embed)
        return True

    # ── Người đang ghi dở → tiếp nhận dòng mới ──────────────────────────────
    if game is None:
        return False   # Không phải trigger, không trong game → bỏ qua

    ws = get_will_state(game, uid)
    if not ws.writing_will:
        return False   # Không trong chế độ ghi → không xử lý

    # 🔒 Nếu người đã chết trong khi đang ghi dở → khóa lại
    if uid in game.dead_players:
        ws.writing_will = False
        ws.locked = True
        if ws.will_lines:
            game.wills[uid] = "\n".join(ws.will_lines)
        await message.channel.send("💀 Bạn đã chết — di chúc đã bị khóa lại.")
        return True

    # Kiểm tra giới hạn số dòng
    if len(ws.will_lines) >= MAX_WILL_LINES:
        over_line = len(ws.will_lines) + 1
        await message.add_reaction("🚫")
        for emoji in _num_to_emoji(over_line):
            await message.add_reaction(emoji)
        await message.channel.send(
            f"Bạn không được viết quá **{MAX_WILL_LINES} dòng**. Di chúc đã được khóa."
        )
        ws.writing_will = False
        ws.locked = True
        game.wills[uid] = "\n".join(ws.will_lines)
        return True

    # Đếm kí tự không tính dấu cách
    char_count = len(content.replace(" ", ""))

    if char_count > MAX_WILL_CHARS:
        next_line = len(ws.will_lines) + 1
        await message.add_reaction("🚫")
        for emoji in _num_to_emoji(next_line):
            await message.add_reaction(emoji)
        await message.channel.send(
            f"Dòng đấy bạn ghi **{char_count}** kí tự, quá **{MAX_WILL_CHARS}** kí tự."
        )
        return True

    # Dòng hợp lệ → lưu vào
    ws.will_lines.append(content)
    current_line = len(ws.will_lines)
    game.wills[uid] = "\n".join(ws.will_lines)   # lưu realtime
    game.logger.debug(f"[Will] Saved line {current_line} for uid {uid}: {content[:50]}")

    # React ✅ + số thứ tự dòng
    await message.add_reaction("✅")
    for emoji in _num_to_emoji(current_line):
        await message.add_reaction(emoji)

    # Cập nhật footer embed nếu muốn (gửi thêm 1 dòng nhỏ)
    if current_line == MAX_WILL_LINES:
        await message.channel.send(
            f"✅ Đã đạt tối đa **{MAX_WILL_LINES} dòng**. Di chúc đã được khóa tự động."
        )
        ws.writing_will = False
        ws.locked = True

    return True


# ── Embed + Select sáng: xem di chúc người đã chết ───────────────────────────

class WillSelectView(disnake.ui.View):
    """View gửi vào text channel mỗi sáng để xem di chúc người chết."""

    def __init__(self, game: "GameEngine", dead_with_wills: list):
        super().__init__(timeout=120)
        self._game = game
        # dead_with_wills: list of (member_id, display_name)
        if dead_with_wills:
            self.add_item(WillSelectMenu(game, dead_with_wills))


class WillSelectMenu(disnake.ui.Select):
    def __init__(self, game: "GameEngine", dead_with_wills: list):
        self._game = game
        # Lưu mapping id→name để callback không phải parse lại từ options
        self._id_to_name: dict = {mid: name for mid, name in dead_with_wills}
        options = [
            disnake.SelectOption(
                label=name[:100],
                value=str(mid),
                emoji="📜"
            )
            for mid, name in dead_with_wills
        ]
        super().__init__(
            placeholder="Chọn người để xem di chúc...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: disnake.ApplicationCommandInteraction):
        mid  = int(self.values[0])
        # Lấy tên từ dict đã lưu — không bao giờ trả về object repr hay Discord ID
        name = self._id_to_name.get(mid)
        if not name:
            raw = self._game._players_dict.get(mid)
            name = getattr(raw, "display_name", None) or str(mid)

        # Tạo nội dung file .txt
        will_text_raw = self._game.wills.get(mid, "")
        lines         = will_text_raw.split("\n") if will_text_raw else []

        if not lines:
            return await interaction.response.send_message(
                f"📜 **{name}** không để lại di chúc.",
                ephemeral=True
            )

        file_content = (
            f"Đây là di chúc của {name}\n"
            f"\n"
            + "\n".join(f"{i+1}. {l}" for i, l in enumerate(lines))
            + f"\n\nMong rằng nó sẽ giúp bạn."
        )

        # Gửi DM kèm file .txt (không mã hóa đầu cuối — dùng disnake.File với StringIO)
        import io
        file_bytes = file_content.encode("utf-8")
        fp = io.BytesIO(file_bytes)
        fp.seek(0)
        filename = f"di_chuc_{name.replace(' ', '_')}.txt"
        dfile    = disnake.File(fp, filename=filename)

        try:
            await interaction.user.send(
                content=f"📜 Di chúc của **{name}**:",
                file=dfile
            )
            await interaction.response.send_message(
                f"✅ Đã gửi di chúc của **{name}** vào DM của bạn!",
                ephemeral=True
            )
        except disnake.Forbidden:
            await interaction.response.send_message(
                "❌ Không thể gửi DM cho bạn. Hãy bật cho phép nhận tin nhắn từ thành viên server.",
                ephemeral=True
            )


async def send_morning_will_board(game: "GameEngine"):
    """Gửi bảng danh sách người chết mỗi sáng — luôn hiện, kể cả khi không ai có di chúc."""
    dead_ids = list(game.dead_players)  # lấy từ dead_players chính xác

    if not dead_ids:
        return

    dead_with_wills = []
    dead_lines = []

    for pid in dead_ids:
        # Lấy member từ _players_dict (có thể là discord.Member hoặc _PlayerWrapper)
        member = game._players_dict.get(pid)
        if not member:
            continue
        # An toàn: luôn lấy display_name qua getattr để tránh f-string dùng __repr__
        name = getattr(member, "display_name", None) or str(pid)
        role_obj = game.roles.get(pid)
        role_name = getattr(role_obj, "name", "Ẩn")
        will_text = game.wills.get(pid, "")
        if not will_text or not will_text.strip():
            # Fallback: will_lines chưa được flush kịp vào wills dict
            _ws_fb = game.will_states.get(pid)
            if _ws_fb and _ws_fb.will_lines:
                will_text = "\n".join(_ws_fb.will_lines)
                game.wills[pid] = will_text   # sync để lần sau khỏi fallback
        has_will = bool(will_text and will_text.strip())

        will_icon = "📜" if has_will else "🚫"
        will_label = "Có Di Chúc" if has_will else "Không Có Di Chúc"
        dead_lines.append(f"`{name}` — {will_label} — {will_icon}")

        if has_will:
            dead_with_wills.append((pid, name))

    description = (
        "Danh sách những người đã chết:\n\n"
        + "\n".join(dead_lines)
    )
    if dead_with_wills:
        description += "\n\n*📜 = có di chúc — chọn bên dưới để xem qua DM*"
    else:
        description += "\n\n*Không ai để lại di chúc.*"

    embed = disnake.Embed(
        title="📋 LÁ THƯ NGƯỜI CHẾT",
        description=description,
        color=0x9b59b6
    )
    embed.set_footer(text=f"{len(dead_ids)} người đã chết | {len(dead_with_wills)} di chúc")

    if dead_with_wills:
        view = WillSelectView(game, dead_with_wills)
        await game.text_channel.send(embed=embed, view=view)
    else:
        await game.text_channel.send(embed=embed)


async def publish_will(game: "GameEngine", member_id: int):
    """Hiển thị di chúc ngay khi người chơi chết (dùng lại ở một số role đặc biệt)."""
    ws     = game.will_states.get(member_id)
    member = game._players_dict.get(member_id)
    name   = member.display_name if member else str(member_id)

    if not ws or not ws.will_lines:
        return   # Không có di chúc → im lặng

    lines   = ws.will_lines
    content = "\n".join(f"{i+1}. {l}" for i, l in enumerate(lines))
    if len(content) > 4000:
        content = content[:4000] + "\n*...(cắt bớt)*"

    await game.text_channel.send(embed=disnake.Embed(
        title=f"📜 DI CHÚC CỦA {name}",
        description=content,
        color=0x9b59b6
    ))


# ══════════════════════════════════════════════════════════════════════
# §12  GAME ENGINE  (core)
# ══════════════════════════════════════════════════════════════════════

class GameEngine:
    """
    Anomalies GameEngine v2.0 — Stable / Production

    Key design decisions:
    • action_queue handles ALL night actions via NightAction objects
    • alive_cache invalidated only on death/revive (O(1) is_alive)
    • config is a GameConfig dataclass (not raw dict)
    • logger writes to memory; dumps to file on crash
    • voice, dead_chat, abuse_tracker, balance helper are sub-systems
    """

    def __init__(
        self,
        guild: disnake.Guild,
        members: List[disnake.Member],
        text_channel: disnake.TextChannel,
        config: Optional[GameConfig] = None,
        voice_channel: Optional[disnake.VoiceChannel] = None,
    ):
        # ── IDs & Identity ────────────────────────────────────────
        self.game_id  = f"ANOMALIES-{uuid.uuid4().hex[:8].upper()}"
        self.guild    = guild
        self.text_channel = text_channel
        self.voice_channel = voice_channel
        self.config   = config or GameConfig()
        self.config.auto_adjust(len(members))

        # ── Sub-systems ───────────────────────────────────────────
        self.logger        = GameLogger(self.game_id, self.config.debug_mode, self.config.log_dir)
        self.voice_ctrl    = VoiceController(self.config, self.logger)
        self.dead_chat_mgr    = DeadChatManager(self.logger)
        # Quản trò Gemini (Flash 2.5) — hoạt động per-game
        try:
            from cogs.gemini_host import GeminiHost
            self.gemini_host = GeminiHost(self, logger=self.logger)
        except Exception as _e:
            self.logger.warn(f"GeminiHost: import lỗi → tắt host: {_e}")
            self.gemini_host = None
        self.anomaly_chat_mgr = AnomalyChatManager(self.logger)
        self.abuse_tracker = AbuseTracker()

        # ── Players ───────────────────────────────────────────────
        self._players_dict        = {m.id: m for m in members}
        self.players              = _PlayersProxy(self)
        self.alive_players: Set[int]   = set(m.id for m in members)
        self.dead_players: Set[int]    = set()
        self.spectators: Set[int]      = set()
        self._force_muted: Set[int]    = set()  # pid bị exile/chết cần mute khi vào lại voice
        self.initial_player_count = len(members)
        self._alive_cache_dirty   = True      # invalidate on death/revive
        self._alive_cache: List   = []

        # ── Roles ─────────────────────────────────────────────────
        self.roles: Dict[int, Any] = {}

        # ── Game state ────────────────────────────────────────────
        self.day_count   = 0
        self.night_count = 0
        self.ended       = False
        self.winner: Optional[str] = None
        self.phase: str  = "waiting"  # waiting/night/day/vote/ended

        # ── Night systems ─────────────────────────────────────────
        self.action_queue            = ActionQueue()
        self.kill_queue: List[Tuple] = []
        self.pending_death_announcements: List[str] = []
        self.nick_registry: Dict[int, str | None] = {}  # lưu nick gốc trước khi đổi
        self.protected: Set[int]     = set()
        self.blocked: Set[int]       = set()
        self.cleaned_roles: Set[int] = set()
        self.night_actors: Set[int]  = set()
        self.night_events: List[Tuple[str, str]] = []
        self._roles_preloaded: bool  = False  # True nếu role map đã inject từ preview
        self.music_player             = None   # MusicPlayer — inject từ bot.py
        self.night_effects: Dict[str, Any]        = {
            "blind_active":           False,  # Blind: mù hóa danh sách mục tiêu
            "cipher_alive":           False,  # Cipher Breaker: passive nhiễu đang bật
            "cipher_destroy_active":  False,  # Cipher Breaker: phá hủy hoàn toàn đêm nay
        }

        # ── Misc state ────────────────────────────────────────────
        self.wills: Dict[int, str]            = {}
        self.will_states: Dict[int, WillState] = {}
        self.selected_targets: Dict[int, Any] = {}
        self.puppeteer_controls: Dict[int, int] = {}
        self.last_night_killers: List[int]    = []
        self.temp_channels: List               = []
        self.fast_forward_next_day = False
        self.overlord_alive        = True
        self.temporarily_removed: Set[int]    = set()
        self.snapshots: Dict                  = {}
        self.harbinger_mass_kill   = False
        self.anomaly_chat          = None
        self.log_channel           = text_channel
        self.dead_chat: Optional[disnake.TextChannel] = None

        # ── Voice state ───────────────────────────────────────────
        self._muting_enabled: bool = True  # tắt khi end_game để tránh race condition

        # ── Future-proof mode hooks ───────────────────────────────
        self._mode_hooks: Dict[str, List] = defaultdict(list)

        self.logger.info(f"GameEngine {self.game_id} initialized | {len(members)} players")
        # ── FIX: lưu guild_id và set status ingame vào config file ──
        self.guild_id = str(guild.id)
        try:
            _cfg = load_guild_config(self.guild_id)
            _cfg["status"] = "ingame"
            save_guild_config(self.guild_id, _cfg)
        except Exception as _e:
            self.logger.warn(f"[GameEngine] set status=ingame lỗi: {_e}")
        if self.config.large_server_mode:
            self.logger.info("Large Server Mode ACTIVE")

    # ══════════════════════════════════════════════════
    # §12.1  ALIVE CACHE
    # ══════════════════════════════════════════════════

    def _invalidate_alive_cache(self):
        self._alive_cache_dirty = True

    def get_alive_players(self) -> List:
        if self._alive_cache_dirty:
            self._alive_cache = [
                self._players_dict[pid]
                for pid in self.alive_players
                if pid not in self.temporarily_removed
            ]
            self._alive_cache_dirty = False
        return self._alive_cache

    def get_dead_players(self) -> List:
        return [self._players_dict[pid] for pid in self.dead_players if pid in self._players_dict]

    def is_alive(self, pid: int) -> bool:
        return pid in self.alive_players and pid not in self.temporarily_removed

    # ══════════════════════════════════════════════════
    # §12.2  UTIL / COMPAT
    # ══════════════════════════════════════════════════

    def get_role(self, member_or_id) -> Optional[Any]:
        pid = member_or_id if isinstance(member_or_id, int) else member_or_id.id
        return self.roles.get(pid)

    def get_role_by_name(self, name: str) -> Optional[Any]:
        for role in self.roles.values():
            if role.name == name:
                return role
        return None

    find_role = get_role_by_name   # backward compat

    # ══════════════════════════════════════════════════
    # §12.2b  DISCORD ROLE & VOICE HELPERS
    # ══════════════════════════════════════════════════

    def _get_dead_role(self) -> "disnake.Role | None":
        if not self.config.dead_role_id:
            return None
        return self.guild.get_role(self.config.dead_role_id)

    def _get_alive_role(self) -> "disnake.Role | None":
        if not self.config.alive_role_id:
            return None
        return self.guild.get_role(self.config.alive_role_id)

    async def _assign_alive_role(self, member: disnake.Member):
        """Gán Alive role khi game bắt đầu."""
        if self.config.no_remove_roles:
            return
        role = self._get_alive_role()
        if not role:
            return
        try:
            if role not in member.roles:
                await member.add_roles(role, reason="Anomalies — game bắt đầu")
        except Exception as e:
            self.logger.warn(f"Cannot add Alive role to {member.display_name}: {e}")

    async def _apply_dead_role(self, member: disnake.Member, force_mute: bool = False):
        """
        Khi chết: gỡ Alive role, gán Dead role, mute nếu cần.
        force_mute=True: bỏ qua config.mute_dead (dùng cho vote-out — luôn mute).
        """
        alive_role = self._get_alive_role()
        dead_role  = self._get_dead_role()
        if not self.config.no_remove_roles:
            try:
                to_remove = [r for r in [alive_role] if r and r in member.roles]
                if to_remove:
                    await member.remove_roles(*to_remove, reason="Anomalies — người chơi chết")
            except Exception as e:
                self.logger.warn(f"Cannot remove Alive role from {member.display_name}: {e}")
            try:
                if dead_role and dead_role not in member.roles:
                    await member.add_roles(dead_role, reason="Anomalies — người chơi chết")
            except Exception as e:
                self.logger.warn(f"Cannot add Dead role to {member.display_name}: {e}")
        # Mute:
        #  - force_mute=True  → luôn mute (vote-out), BỎ QUA no_remove_roles
        #  - force_mute=False → mute nếu config.mute_dead=True (chết ban đêm)
        #  - no_remove_roles  → chỉ ngăn gán/gỡ Discord role, KHÔNG ngăn force_mute
        should_mute = (force_mute or (self.config.mute_dead and not self.config.no_remove_roles)) and self._muting_enabled
        if should_mute and self.config.allow_voice:
            if member.voice:
                await self.voice_ctrl._try_mute(member, True)
            # Nếu không trong voice → đánh dấu để mute khi vào lại
            self._force_muted.add(member.id)

    async def _cleanup_discord_roles(self, member: disnake.Member):
        """Hết trận: tháo Dead/Alive role, unmute."""
        if self.config.no_remove_roles:
            return
        dead_role  = self._get_dead_role()
        alive_role = self._get_alive_role()
        to_remove = [r for r in [dead_role, alive_role] if r and r in member.roles]
        if to_remove:
            try:
                await member.remove_roles(*to_remove, reason="Anomalies — hết trận")
            except Exception as e:
                self.logger.warn(f"Cannot cleanup roles for {member.display_name}: {e}")

    def get_member(self, pid: int) -> Optional[disnake.Member]:
        return self._players_dict.get(pid)

    def get_player_wrapper(self, pid: int) -> Optional[_PlayerWrapper]:
        member = self._players_dict.get(pid)
        if not member:
            return None
        return _PlayerWrapper(member, self.roles.get(pid), self)

    def set_selected_target(self, actor, target):
        self.selected_targets[actor.id] = target

    def get_selected_target(self, actor):
        return self.selected_targets.get(actor.id)

    def block_player(self, member):
        self.blocked.add(member.id)

    def protect_player(self, member):
        self.protected.add(member.id)

    def generate_night_report(self) -> List[str]:
        return [text for _, text in self.night_events]

    # ══════════════════════════════════════════════════
    # §NICK REGISTRY — lưu & trả lại nick khi đổi tên
    # ══════════════════════════════════════════════════

    def save_nick(self, member: disnake.Member) -> None:
        """Lưu nick gốc của member nếu chưa lưu. Gọi TRƯỚC khi edit(nick=...)."""
        if member.id not in self.nick_registry:
            self.nick_registry[member.id] = member.nick  # None nếu chưa có nick

    async def restore_nick(self, member: disnake.Member) -> None:
        """Trả lại nick gốc đã lưu cho member."""
        original = self.nick_registry.pop(member.id, "NOT_SAVED")
        if original == "NOT_SAVED":
            return  # không có trong registry → bỏ qua
        try:
            await member.edit(nick=original)
        except Exception:
            pass

    async def restore_all_nicks(self) -> None:
        """Trả lại tất cả nick đã lưu trong registry. Gọi lúc end_game."""
        for pid, original in list(self.nick_registry.items()):
            member = self.guild.get_member(pid)
            if member:
                try:
                    await member.edit(nick=original)
                except Exception:
                    pass
        self.nick_registry.clear()

    def add_night_event(self, faction: str, text: str):
        # ── Cipher Breaker active: phá hủy hoàn toàn night event ──
        try:
            from roles.event.cipher_breaker import CipherBreaker
            text = CipherBreaker.apply_destroy(text, self)
        except Exception:
            pass
        self.night_events.append((faction, text))

    def get_protectors(self, pid: int) -> List[int]:
        return [pid] if pid in self.protected else []

    def roles_state_copy(self) -> dict: return {}
    def restore_roles(self, snapshot): pass

    # Mode hooks
    def register_mode_hook(self, event: str, fn):
        self._mode_hooks[event].append(fn)

    async def _fire_hooks(self, event: str):
        for fn in self._mode_hooks.get(event, []):
            try:
                result = fn(self)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                self.logger.error(f"Hook error [{event}]: {e}")

    # ══════════════════════════════════════════════════
    # §12.3  SEND / LOG
    # ══════════════════════════════════════════════════

    async def send(self, content=None, embed=None):
        try:
            await self.text_channel.send(content=content, embed=embed)
        except Exception as e:
            self.logger.error(f"send() error: {e}")

    broadcast = send

    async def log(self, text: str, color: int = 0x95a5a6):
        embed = disnake.Embed(description=text, color=color)
        await self.send(embed=embed)

    add_log = log   # backward compat

    async def send_dm(self, member: disnake.Member, text: str, embed=None):
        """Send DM with fallback to public channel if DMs disabled."""
        try:
            if embed:
                await member.send(embed=embed)
            else:
                await member.send(text)
        except (disnake.Forbidden, disnake.HTTPException) as e:
            self.logger.warn(f"DM failed for {member.display_name}: {e}")
            if self.config.dm_fallback_to_public:
                try:
                    msg = f"*(DM lỗi → public)* {member.mention}: {text}"
                    await self.text_channel.send(msg[:1900], delete_after=15)
                except Exception:
                    pass

    async def reveal_message_to_town(self, text: str):
        await self.send(content=text)

    async def ask_player_choice(self, player, candidates, prompt: str):
        if not candidates:
            return None
        members = []
        for c in candidates:
            if isinstance(c, _PlayerWrapper):
                members.append(c._member)
            elif hasattr(c, "_member"):
                members.append(c._member)
            else:
                members.append(c)
        view = _ChoiceView(members, timeout=30)
        try:
            await player.send(prompt, view=view)
        except Exception:
            return members[0] if members else None
        await view.wait()
        return view.chosen

    # ══════════════════════════════════════════════════
    # §12.4  ROLE DISTRIBUTION
    # ══════════════════════════════════════════════════

    def distribute_roles(self, survivor_classes, anomaly_classes, unknown_classes):
        from role_distributor import distribute_roles

        all_classes = survivor_classes + anomaly_classes + unknown_classes
        members     = list(self._players_dict.values())

        # FIX BUG: Ưu tiên dùng map đã pre-compute từ /preview để bảng Embed
        # khớp 100 % với phân vai thực tế. Nếu map đã lưu trùng đúng tập
        # member hiện tại → dùng lại; nếu khác (có người rời/vào) → roll mới.
        role_map = None
        try:
            from app import _pending_role_maps  # type: ignore[import]
            guild_id = ""
            try:
                gid = getattr(self, "guild_id", None)
                if gid:
                    guild_id = str(gid)
                elif getattr(self, "text_channel", None) and getattr(self.text_channel, "guild", None):
                    guild_id = str(self.text_channel.guild.id)
            except Exception:
                guild_id = ""
            pending = _pending_role_maps.pop(guild_id, None) if guild_id else None
            if pending and set(pending.keys()) == {m.id for m in members}:
                role_map = pending
                self.logger.info(
                    f"[distribute_roles] Dùng lại preview map (guild={guild_id}, "
                    f"{len(role_map)} người)."
                )
            elif pending:
                self.logger.warn(
                    f"[distribute_roles] Preview map không khớp lobby hiện tại "
                    f"(preview={len(pending)} vs lobby={len(members)}) → roll mới."
                )
        except Exception as _e:
            self.logger.debug(f"[distribute_roles] Không đọc được _pending_role_maps: {_e}")

        if role_map is None:
            # Seed ngẫu nhiên mỗi ván — trộn time + member IDs để không bao giờ lặp lại
            _seed = int(time.time() * 1000) ^ sum(m.id for m in members)
            random.seed(_seed)
            random.shuffle(members)
            role_map = distribute_roles(members, all_classes)
            # Reset seed về random thật
            random.seed()

        self.roles.update(role_map)

        # Gán _game vào mỗi role để các role có thể dùng game.save_nick() v.v.
        for _role_obj in self.roles.values():
            _role_obj._game = self

        ok, warnings = BalanceHelper.validate(self.roles, self.config)
        for w in warnings:
            self.logger.warn(w)
        if warnings:
            asyncio.create_task(self._send_balance_warnings(warnings))

        suggestion = BalanceHelper.suggest(len(members))
        self.logger.info(suggestion)

    async def _send_balance_warnings(self, warnings: List[str]):
        if not warnings:
            return
        lines = "\n".join(warnings)
        embed = disnake.Embed(
            title="⚖️ CẢNH BÁO CÂN BẰNG",
            description=lines,
            color=0xe67e22
        )
        await self.send(embed=embed)

    # ══════════════════════════════════════════════════
    # §12.5  START
    # ══════════════════════════════════════════════════

    async def start(self, survivor_classes, anomaly_classes, unknown_classes):
        try:
            self.logger.info("Game starting...")
            await self._fire_hooks("on_game_start")

            self.distribute_roles(survivor_classes, anomaly_classes, unknown_classes)

            # Create dead chat
            # Lấy category từ config (nếu setup đã đặt)
            _cat = None
            try:
                _cat_id = getattr(self.config, "category_id", None)
                if _cat_id:
                    _cat = self.guild.get_channel(int(_cat_id))
                    if _cat is not None and not isinstance(_cat, disnake.CategoryChannel):
                        _cat = None
            except Exception:
                _cat = None

            await self.dead_chat_mgr.create(
                self.guild, category=_cat, fallback_channel=self.text_channel,
            )
            self.dead_chat = self.dead_chat_mgr.channel

            # Create anomaly chat
            await self.anomaly_chat_mgr.create(
                self.guild, category=_cat, fallback_channel=self.text_channel,
            )
            self.anomaly_chat = self.anomaly_chat_mgr.channel
            # Cấp quyền cho tất cả Anomalies + Psychopath ngay khi tạo
            for _pid, _role in self.roles.items():
                _member = self._players_dict.get(_pid)
                if not _member:
                    continue
                if getattr(_role, 'team', '') == 'Anomalies':
                    await self.anomaly_chat_mgr.add_member(_member)
                elif getattr(_role, 'can_read_anomaly_chat', lambda: False)():
                    await self.anomaly_chat_mgr.add_spectator(_member)
            # Gửi lời chào mừng
            if self.anomaly_chat:
                await self.anomaly_chat_mgr.send(
                    embed=disnake.Embed(
                        title='🔴 ANOMALIES — KÊNH BÍ MẬT',
                        description=(
                            'Chào mừng các Dị Thể!\n\n'
                            'Đây là kênh liên lạc nội bộ của phe — **chỉ bạn mới thấy được kênh này**.\n'
                            '📌 Bot sẽ gửi báo cáo tình hình mỗi sáng sau mỗi đêm.\n'
                            '⚠️ Nếu Survivor dùng kỹ năng phát hiện trúng bạn, cảnh báo sẽ xuất hiện tại đây.\n\n'
                            '🩸 Hãy cùng nhau lên kế hoạch và giành chiến thắng!'
                        ),
                        color=0xe74c3c
                    )
                )

            # Gán Alive role (không gỡ roles server)
            if self.config.alive_role_id:
                for member in self._players_dict.values():
                    await self._assign_alive_role(member)
                    await asyncio.sleep(0.05)

            await self.log("🎮 **TRẬN ĐẤU BẮT ĐẦU!** Đang phát vai trò...", color=0x9b59b6)
            await self.phase_distribute_roles()

            # on_game_start hooks for roles
            for pid, role in self.roles.items():
                if hasattr(role, "on_game_start"):
                    await self._safe_call(role.on_game_start, self, label=f"{role.name}.on_game_start")
                # Cipher Breaker: bật passive ngay khi game bắt đầu
                if getattr(role, "name", "") == "Cipher Breaker":
                    self.night_effects["cipher_alive"] = True

            # Ghost Ship
            gs_role = self.get_role_by_name("Con Tàu Ma")
            if gs_role:
                try:
                    gs_role.calculate_required(self)
                except Exception:
                    pass

            # Main loop
            while not self.ended:
                tw_role = self.get_role_by_name("Kẻ Dệt Thời Gian")
                if tw_role:
                    try:
                        tw_role.save_snapshot(self)
                    except Exception:
                        pass

                await self.phase_night()
                if self.ended:
                    break
                await self.phase_day()
                if self.ended:
                    break
                await self.phase_voting()
                self._check_win()

            await self.end_game(self.winner or "Unknown")

        except Exception as e:
            tb = traceback.format_exc()
            self.logger.error(f"FATAL: {e}\n{tb}")
            if self.config.save_crash_log:
                self.logger.dump_to_file()
            # Thông báo lỗi ra kênh
            try:
                err_msg = await self.text_channel.send(
                    embed=disnake.Embed(
                        title="❌ TRẬN BỊ HUỶ — LỖI HỆ THỐNG",
                        description=f"```{tb[-500:]}```",
                        color=0xe74c3c
                    )
                )
                await self._purge_text_channel(keep_id=err_msg.id, reason="Lỗi Hệ Thống")
            except Exception:
                pass
            # Dọn dẹp Discord: xóa kênh, gỡ roles, unmute — chỉ khi chưa ended
            if not self.ended:
                self.ended = True
                try:
                    await self.dead_chat_mgr.delete()
                except Exception:
                    pass
                try:
                    await self.anomaly_chat_mgr.delete()
                except Exception:
                    pass
                try:
                    await self._cleanup_temp_channels()
                except Exception:
                    pass
                # Unmute + gỡ Alive/Dead role cho tất cả người chơi
                self._muting_enabled = False
                for _member in self._players_dict.values():
                    try:
                        await self._cleanup_discord_roles(_member)
                    except Exception:
                        pass
                    try:
                        if _member.voice:
                            await self.voice_ctrl._try_mute(_member, False)
                    except Exception:
                        pass

    # ══════════════════════════════════════════════════
    # §12.6  PHASE: DISTRIBUTE ROLES
    # ══════════════════════════════════════════════════

    async def phase_distribute_roles(self):
        tasks = [
            self._send_role_dm(self._players_dict[pid], role)
            for pid, role in self.roles.items()
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(self.config.role_distribute_time)

    async def _send_role_dm(self, member: disnake.Member, role):
        try:
            team = getattr(role, "team", None) or getattr(role, "faction", "?")
            dm_msg = getattr(role, "dm_message", None)

            # Chọn màu embed theo phe
            team_colors = {
                "Anomalies": 0xe74c3c,   # Đỏ — Dị Thể
                "Survivors":  0x2ecc71,  # Xanh lá — Người Sống Sót
                "Unknown":    0xf1c40f,  # Vàng — Ẩn Danh
            }
            embed_color = team_colors.get(team, 0x9b59b6)

            # Tạo embed với dm_message (description chỉ dùng cho role_preview)
            embed = disnake.Embed(
                description=dm_msg if dm_msg else "",
                color=embed_color
            )

            await member.send(embed=embed)

            # ── Gửi thêm danh sách vai trò toàn trận ─────────────────────
            await member.send(embed=self._build_role_list_embed())

        except Exception as e:
            self.logger.warn(f"Cannot send role DM to {member}: {e}")
            if self.config.dm_fallback_to_public:
                try:
                    await self.text_channel.send(
                        f"*(DM lỗi)* {member.mention} nhận vai — vui lòng kiểm tra DM.",
                        delete_after=10
                    )
                except Exception:
                    pass

    def _build_role_list_embed(self) -> disnake.Embed:
        """Tạo embed danh sách vai trò xuất hiện trong trận này (không tiết lộ ai là ai)."""
        # Đếm số lượng từng role
        role_counts: dict[str, int] = {}
        team_of:     dict[str, str] = {}
        for role_obj in self.roles.values():
            rname = role_obj.name
            role_counts[rname] = role_counts.get(rname, 0) + 1
            team_of[rname]     = getattr(role_obj, "team", "?")

        # Phân nhóm theo phe
        survivors = {}
        anomalies = {}
        unknowns  = {}
        for rname, cnt in role_counts.items():
            t = team_of[rname]
            if t == "Survivors":
                survivors[rname] = cnt
            elif t == "Anomalies":
                anomalies[rname] = cnt
            else:
                unknowns[rname]  = cnt

        def fmt(d: dict) -> str:
            if not d:
                return "*Không có*"
            return "\n".join(
                f"• **{name}**" + (f" ×{cnt}" if cnt > 1 else "")
                for name, cnt in sorted(d.items())
            )

        total = len(self.roles)
        embed = disnake.Embed(
            title="📋 DANH SÁCH VAI TRÒ TRẬN NÀY",
            description=f"Tổng cộng **{total} người chơi** với các vai trò sau:",
            color=0x2c3e50
        )
        embed.add_field(name="🔵 Người Sống Sót",    value=fmt(survivors), inline=False)
        embed.add_field(name="🔴 Dị Thể",            value=fmt(anomalies), inline=False)
        if unknowns:
            embed.add_field(name="⚫ Thực Thể Ẩn",   value=fmt(unknowns),  inline=False)
        embed.set_footer(text="Danh sách này không tiết lộ ai đang giữ vai trò nào.")
        return embed

    # ══════════════════════════════════════════════════
    # §12.7  PHASE: NIGHT
    # ══════════════════════════════════════════════════

    async def phase_night(self):
        self.phase         = "night"
        self.night_count  += 1
        # ── Nhạc đêm ─────────────────────────────────────────────
        if self.music_player:
            await self.music_player.play_night()
        self.selected_targets.clear()
        self.kill_queue.clear()
        self.protected.clear()
        self.blocked.clear()
        self.night_actors.clear()
        self.last_night_killers.clear()
        self.harbinger_mass_kill   = False
        self.fast_forward_next_day = False
        self.night_events  = []
        self.pending_death_announcements.clear()   # reset mỗi đêm
        # Chỉ reset per-night effects — GIỮ cipher_alive (persistent)
        self.night_effects["blind_active"]          = False
        self.night_effects["cipher_destroy_active"] = False
        if "cipher_alive" not in self.night_effects:
            self.night_effects["cipher_alive"] = False
        self.action_queue.clear()

        try:
            from roles.event.pro_tester import ProTester
            ProTester._claimed_targets = set()
        except Exception:
            pass

        self.logger.info(f"=== NIGHT {self.night_count} ===")
        await self._fire_hooks("on_night_start")

        await self.log(
            f"🌙 **ĐÊM {self.night_count}** — Mọi người hãy im lặng và thực hiện hành động.",
            color=0x2c3e50
        )

        # Ping các thành viên Anomalies vào anomaly_chat để họ biết kênh
        if self.anomaly_chat:
            anomaly_mentions = " ".join(
                self._players_dict[pid].mention
                for pid, role in self.roles.items()
                if getattr(role, "team", "") == "Anomalies" and self.is_alive(pid)
                and pid in self._players_dict
            )
            if anomaly_mentions:
                try:
                    await self.anomaly_chat.send(
                        f"🔔 {anomaly_mentions}\n"
                        f"🌙 **Đêm {self.night_count} bắt đầu** — Lên kế hoạch ngay!"
                    )
                except Exception as _e:
                    self.logger.warn(f"[phase_night] Ping Anomalies lỗi: {_e}")

        # Mute tất cả người còn sống vào đầu đêm (chế độ free)
        if self.config.allow_voice and self._muting_enabled and self.config.voice_mode != "parliament":
            alive_members = self.get_alive_players()
            if alive_members:
                await self.voice_ctrl.set_mute(alive_members, True)

        # Send night UIs
        tasks = []
        active_count = 0
        max_actors = self.config.max_night_actors if self.config.max_night_actors > 0 else 9999

        for pid, role in self.roles.items():
            if not self.is_alive(pid):
                continue
            # Large Server Mode: limit investigative roles
            if self.config.large_server_mode:
                tier = getattr(role, "tier", "Core")
                if tier == "Chaos" and active_count >= max_actors:
                    continue
            if hasattr(role, "send_ui") or hasattr(role, "send_night_ui"):
                if active_count < max_actors:
                    active_count += 1
                    tasks.append(self._safe_send_night_ui_dispatch(role))

        await asyncio.gather(*tasks, return_exceptions=True)

        # Đồng hồ đếm ngược đêm
        night_time = self.config.night_time
        timer_embed = disnake.Embed(
            title=f"🌙 ĐÊM {self.night_count} — HÀNH ĐỘNG",
            description=f"⏱️ Còn lại: **{night_time}s**",
            color=0x2c3e50
        )
        timer_msg = None
        try:
            timer_msg = await self.text_channel.send(embed=timer_embed)
        except Exception:
            pass
        for elapsed in range(night_time):
            await asyncio.sleep(1)
            remaining = night_time - elapsed - 1
            if timer_msg:
                try:
                    timer_embed.description = f"⏱️ Còn lại: **{remaining}s**"
                    await timer_msg.edit(embed=timer_embed)
                except Exception:
                    pass
        if timer_msg:
            try:
                timer_embed.description = "⏱️ Hết thời gian!"
                await timer_msg.edit(embed=timer_embed)
            except Exception:
                pass

        # Auto-fill missing actions
        if self.config.auto_random_if_no_action:
            await self._auto_fill_actions()

        # Pre-process Dark-Architect blocks TRƯỚC khi resolve actions
        dark_arch = self.get_role_by_name("Kiến Trúc Sư Bóng Tối")
        if dark_arch and self.is_alive(dark_arch.player.id):
            blocked_targets = getattr(dark_arch, "blocked_targets", set())
            if blocked_targets:
                for _pid in blocked_targets:
                    self.blocked.add(_pid)
                self.add_night_event("Anomalies", f"Bóng tối bao phủ **{len(blocked_targets)}** ngôi nhà.")
                dark_arch.blocked_targets = set()

        # Resolve actions in priority order
        await self.action_queue.resolve(self)

        # Legacy resolve (roles not yet migrated to ActionQueue)
        await self._resolve_legacy_night_actions()

        # Fallback: nếu Anomalies đã vote nhưng không ai đạt đa số → lấy top vote
        await self._resolve_anomaly_vote_fallback()

        await self._process_kills()
        await self._cleanup_temp_channels()

        # TimeWeaver morning passive
        tw_role = self.get_role_by_name("Kẻ Dệt Thời Gian")
        if tw_role and self.is_alive(tw_role.player.id):
            await self._safe_call(tw_role.morning_passive, self, label="TimeWeaver.morning_passive")

        await self._send_sleeper_night_report()
        await self.anomaly_chat_mgr.send_daily_log(self)
        await self._fire_hooks("on_night_end")
        self.logger.info(f"Night {self.night_count} complete")

    async def _safe_send_night_ui_dispatch(self, role):
        self.night_actors.add(role.player.id)
        if hasattr(role, "send_ui"):
            await self._safe_call(role.send_ui, self, label=f"{role.name}.send_ui")
        elif hasattr(role, "send_night_ui"):
            await self._safe_call(role.send_night_ui, self, label=f"{role.name}.send_night_ui")

    async def _safe_call(self, fn, *args, label: str = ""):
        """Safe wrapper that catches all exceptions without crashing."""
        try:
            result = fn(*args)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            self.logger.error(f"[{label or fn.__name__}] {e}\n{traceback.format_exc()}")

    async def _auto_fill_actions(self):
        """For roles that haven't chosen — auto-skip or random-target per config."""
        alive_non_self = self.get_alive_players()
        for pid, role in self.roles.items():
            if not self.is_alive(pid):
                continue
            if pid in self.selected_targets:
                continue
            # Only auto-fill roles that have night actions and haven't acted
            if not (hasattr(role, "send_ui") or hasattr(role, "send_night_ui")):
                continue
            # Check cooldown / max_uses
            if getattr(role, "max_uses", None) is not None and getattr(role, "uses_remaining", 1) <= 0:
                continue
            if getattr(role, "cooldown", 0) > 0:
                continue
            # Auto-random
            candidates = [p for p in alive_non_self if p.id != pid]
            if candidates:
                self.selected_targets[pid] = random.choice(candidates)
                self.logger.debug(f"Auto-filled target for {role.name} (pid={pid})")

    # ══════════════════════════════════════════════════
    # §12.8  LEGACY NIGHT ACTION RESOLVER
    # (Roles not yet migrated to ActionQueue)
    # ══════════════════════════════════════════════════

    async def _resolve_legacy_night_actions(self):
        """Original hardcoded resolves, preserved for compatibility."""

        def name(pid):
            m = self._players_dict.get(pid)
            return m.display_name if m else "???"

        # ── JAILOR ────────────────────────────────────────────────
        jailor = self.get_role_by_name("Cai Ngục")
        if jailor and self.is_alive(jailor.player.id):
            await self._safe_call(jailor.night_action, self, label="Jailor.night_action")
            if getattr(jailor, "current_prisoner", None):
                self.add_night_event("Survivors", f"**{jailor.current_prisoner.display_name}** đã bị Quản Ngục giam giữ đêm nay.")

        # ── THE ARCHITECT ─────────────────────────────────────────
        architect = self.get_role_by_name("Kiến Trúc Sư")
        if architect and self.is_alive(architect.player.id) and self.protected:
            self.add_night_event("Survivors", f"Một Kiến Trúc Sư đã gia cố **{len(self.protected)}** ngôi nhà.")

        # ── MEDIUM ────────────────────────────────────────────────
        medium = self.get_role_by_name("Nhà Ngoại Cảm")
        if medium and self.is_alive(medium.player.id):
            await self._safe_call(medium.night_action, self, label="Medium.night_action")
            self.add_night_event("Survivors", "Một Đồng Cốt đã mở phiên giao tiếp với linh hồn.")

        # ── SPY ───────────────────────────────────────────────────
        spy = self.get_role_by_name("Điệp Viên")
        if spy and self.is_alive(spy.player.id):
            anomaly_target = None
            for pid, role in self.roles.items():
                if getattr(role, "team", "") == TEAM_ANOMALY and getattr(role, "last_target_id", None):
                    anomaly_target = self._players_dict.get(role.last_target_id)
                    break
            await self._safe_call(spy.receive_info, self, anomaly_target, label="Spy.receive_info")
            if anomaly_target:
                self.add_night_event("Survivors", "Một Điệp Viên đã thu thập tín hiệu.")
                # Cảnh báo Anomalies: có Spy đang theo dõi mục tiêu của họ
                await self.anomaly_chat_mgr.send(
                    embed=disnake.Embed(
                        title="👁️ CẢNH BÁO ĐIỆP VIÊN",
                        description=(
                            "**ĐIỆP VIÊN** đang theo dõi hành động của phe Dị Thể!\n\n"
                            "📡 Có người trong thị trấn biết phe **Anomalies đang nhắm vào ai** đêm nay.\n"
                            "⚠️ Hãy cân nhắc đổi mục tiêu hoặc hành động bất ngờ hơn!"
                        ),
                        color=0x34495e
                    )
                )

        # ── THE OVERSEER ──────────────────────────────────────────
        overseer = self.get_role_by_name("Người Giám Sát")
        if overseer and self.is_alive(overseer.player.id) and getattr(overseer, "used_tonight", False):
            self.add_night_event("Survivors", "Camera an ninh đã ghi lại hoạt động đêm nay.")

        # ── THE GLITCH-STALKER (Kẻ Rình Rập) ──────────────────────
        stalker = self.get_role_by_name("Kẻ Rình Rập")
        if stalker and getattr(stalker, "target_id", None):
            target_role = self.roles.get(stalker.target_id)
            if target_role:
                stalker.discovered_roles = getattr(stalker, "discovered_roles", {})
                stalker.discovered_roles[stalker.target_id] = target_role.name
                await self.send_dm(stalker.player, "", embed=disnake.Embed(
                    title="👁️ KẾT QUẢ THEO DÕI",
                    description=f"Vai trò của mục tiêu: **{target_role.name}**",
                    color=0xe74c3c
                ))
                self.add_night_event("Anomalies", f"Một Dị Thể đã phát hiện thông tin về **{name(stalker.target_id)}**.")
            stalker.target_id = None

        # Dark-Architect block đã được xử lý trước action_queue.resolve() — bỏ qua ở đây

        # ── THE HARBINGER ─────────────────────────────────────────
        harbinger = self.get_role_by_name("Sứ Giả Tận Thế")
        if harbinger and getattr(harbinger, "mass_kill_ready", False):
            alive_marked = [pid for pid in getattr(harbinger, "marked", []) if self.is_alive(pid)]
            for pid in alive_marked[:3]:
                self.queue_kill(pid, reason="Bị Harbinger tiêu diệt hàng loạt", bypass=True)
            self.add_night_event("Anomalies", f"Harbinger kích hoạt Tiêu Diệt Hàng Loạt: {', '.join(name(p) for p in alive_marked[:3])}.")
            harbinger.mass_kill_ready = False
            harbinger.cooldown = True

        # ── THE PUPPETEER ─────────────────────────────────────────
        puppeteer = self.get_role_by_name("Kẻ Điều Khiển")
        if puppeteer and getattr(puppeteer, "control_data", None):
            victim_id, forced_id = puppeteer.control_data
            self.puppeteer_controls[victim_id] = forced_id
            self.add_night_event("Anomalies", f"Sợi dây vô hình đã gắn vào **{name(victim_id)}** — ép bỏ phiếu sáng mai.")
            puppeteer.control_data = None

        # ── THE GLITCH-WORM ──────────────────────────────────────
        gw = self.get_role_by_name("Sâu Lỗi")
        if gw and getattr(gw, "marked_target", None):
            self.wills[gw.marked_target] = "✖ Dữ liệu đã bị Glitch-Worm phá hủy."
            self.add_night_event("Anomalies", f"Sâu Mã Độc xâm nhập, phá hủy dữ liệu **{name(gw.marked_target)}**.")
            gw.marked_target = None

        # ── THE NEURO-PARASITE ───────────────────────────────────
        np_role = self.get_role_by_name("Ký Sinh Thần Kinh")
        if np_role and getattr(np_role, "host_id", None) and not self.is_alive(np_role.host_id):
            self.queue_kill(np_role.player.id, reason="Ký sinh chủ đã chết")
            self.add_night_event("Anomalies", "Ký sinh chủ của Neuro-Parasite chết — ký sinh tan rã.")

        # ── THE BIO-MIMIC ─────────────────────────────────────────
        bm = self.get_role_by_name("Kẻ Mô Phỏng Sinh Học")
        if bm and getattr(bm, "host_id", None):
            if not self.is_alive(bm.host_id) and not getattr(bm, "link_used", False):
                bm.link_used      = True
                bm.night_immunity = True
                self.add_night_event("Anomalies", "Bio-Mimic hấp thụ năng lượng từ liên kết đứt — nhận miễn nhiễm.")

        # ── THE GHOST SHIP ────────────────────────────────────────
        gs = self.get_role_by_name("Con Tàu Ma")
        if gs and getattr(gs, "last_target", None) and self.night_count >= 3:
            self.add_night_event("Unknown", f"**{name(gs.last_target)}** biến mất không dấu vết.")

        # ── THE DOOMSDAY CLOCK ────────────────────────────────────
        if self.fast_forward_next_day:
            self.add_night_event("Unknown", "Thời gian bị bóp méo — thảo luận ngày mai bị rút ngắn.")

        # ── THE DREAMWEAVER ───────────────────────────────────────
        dw = self.get_role_by_name("Kẻ Dệt Mộng")
        if dw and getattr(dw, "dream_pairs", None):
            self.add_night_event("Unknown", "Hai linh hồn bị buộc trong cùng giấc mơ.")

    # ══════════════════════════════════════════════════
    # §12.9  KILL SYSTEM
    # ══════════════════════════════════════════════════

    def queue_kill(self, target_id: int, reason: str = "Không rõ", bypass: bool = False):
        self.kill_queue.append((target_id, reason, bypass))

    async def _resolve_anomaly_vote_fallback(self):
        """
        Cuối đêm: nếu Anomalies đã vote nhưng chưa có kill được queue cho phe Anomalies,
        lấy mục tiêu nhiều phiếu nhất (dù không đạt đa số) để đảm bảo kill luôn xảy ra.
        """
        overlord = self.get_role_by_name("Lãnh Chúa")
        if overlord and self.is_alive(overlord.player.id):
            # Overlord còn sống — kill đã được queue trong callback rồi
            return

        # Thu thập vote từ tất cả Anomaly còn sống
        vote_count: Dict[int, int] = {}
        for pid, role in self.roles.items():
            if getattr(role, "team", "") != TEAM_ANOMALY:
                continue
            if not self.is_alive(pid):
                continue
            v = getattr(role, "vote_target", None)
            if v and self.is_alive(v):
                vote_count[v] = vote_count.get(v, 0) + 1

        if not vote_count:
            return

        # Kiểm tra xem đã có kill được queue cho Anomaly chưa
        anomaly_kill_queued = any(
            any(k in reason for k in ("Anomal", "Overlord", "Dị Thể", "Anomalies tiêu diệt"))
            for _, reason, _ in self.kill_queue
        )
        if anomaly_kill_queued:
            return

        # Lấy mục tiêu nhiều phiếu nhất
        best_target = max(vote_count, key=lambda t: vote_count[t])
        self.queue_kill(best_target, reason="Bị Anomalies tiêu diệt trong đêm")
        self.logger.info(f"[Fallback] Anomaly kill queued → target {best_target} ({vote_count[best_target]} phiếu)")

    async def kill_player(
        self,
        member,
        reason: str = "Không rõ",
        bypass: bool = False,
        bypass_protection: bool = False,
        force_mute: bool = False,
    ):
        bypass = bypass or bypass_protection
        if hasattr(member, "player"):
            member = member.player
        if not member:
            return
        pid = member.id
        if not self.is_alive(pid):
            return

        role = self.roles.get(pid)

        # ── Pharmacist: Immortal (Trường Sinh) ──────────────────────────────
        pharma = self.get_role_by_name("Nhà Dược Học Điên")
        if pharma and pid in getattr(pharma, "immortal_targets", {}):
            self.add_night_event("Survivors", f"**{member.display_name}** được bảo vệ bởi Thuốc Trường Sinh.")
            await self.send_dm(member, "⚗️ Thuốc Trường Sinh đã bảo vệ bạn đêm nay!")
            return

        # ── Pharmacist: Glow (Phát Sáng) — lộ kẻ tấn công ───────────────────
        if not bypass and pharma and pid in getattr(pharma, "glow_targets", set()):
            pharma.glow_targets.discard(pid)
            # Tìm kẻ tấn công (Anomaly có last_target_id = pid)
            for _pid, _role in self.roles.items():
                if getattr(_role, "team", "") == "Anomalies" and getattr(_role, "last_target_id", None) == pid:
                    attacker = self._players_dict.get(_pid)
                    if attacker:
                        await self.log(
                            f"✨ **{attacker.display_name}** bị **PHÁT SÁNG** — lộ diện do tấn công mục tiêu có Thuốc Phát Sáng!",
                            color=0xf1c40f
                        )
                    break

        # ── Pharmacist: Virus — ai giết mục tiêu này chết theo ───────────────
        if not bypass and pharma and pid in getattr(pharma, "virus_targets", set()):
            # Mục tiêu đã chết (virus), tìm kẻ gây ra cái chết và giết họ
            for _pid, _role in self.roles.items():
                if getattr(_role, "team", "") == "Anomalies" and getattr(_role, "last_target_id", None) == pid:
                    attacker = self._players_dict.get(_pid)
                    if attacker and self.is_alive(_pid):
                        await self.kill_player(attacker, reason="Chết do tiếp xúc Thuốc Virus", bypass=True)
                        await self.log(
                            f"☠️ **{attacker.display_name}** chết vì cố giết người đã nhiễm Thuốc Virus!",
                            color=0x8e44ad
                        )
                    break

        # Bio Mimic immunity
        if role and getattr(role, "night_immunity", False) and not bypass:
            role.night_immunity = False
            self.add_night_event("Anomalies", f"**{member.display_name}** hấp thụ đòn nhờ liên kết cộng sinh.")
            await self.send_dm(member, "🛡️ Bạn miễn nhiễm đòn tấn công đêm nay!")
            return

        # Corrupted AI Shield check (3 điểm = chặn 1 đòn)
        if role and hasattr(role, "shields") and role.shields >= 3 and not bypass:
            role.shields -= 3
            self.add_night_event("Unknown", f"**{member.display_name}** được khiên A.I hấp thụ đòn tấn công.")
            await self.send_dm(member, "🛡️ Khiên A.I kích hoạt — bạn sống sót! (-3 điểm khiên)")
            return

        # Protection check
        if pid in self.protected and not bypass:
            self.add_night_event("Survivors", f"**{member.display_name}** được bảo vệ và sống sót.")
            await self.send_dm(member, "🛡️ Bạn được bảo vệ khỏi tấn công đêm nay!")
            return

        # Trapper
        trapper = self.get_role_by_name("Thợ Đặt Bẫy")
        if trapper and trapper.player.id == pid and not bypass:
            attackers = [self._players_dict.get(k) for k, r in self.roles.items() if getattr(r, "team", "") == TEAM_ANOMALY]
            survived = not await self._safe_call_bool(
                trapper.on_attacked, self, [a for a in attackers if a],
                label="Trapper.on_attacked"
            )
            if survived:
                return

        # Execute kill
        self.alive_players.discard(pid)
        self.dead_players.add(pid)
        self._invalidate_alive_cache()
        self.last_night_killers.append(pid)

        # 🔒 Tự động khóa di chúc nếu người chơi đang ghi dở
        _ws_kill = self.will_states.get(pid)
        if _ws_kill and _ws_kill.writing_will:
            _ws_kill.writing_will = False
            _ws_kill.locked = True
            if _ws_kill.will_lines:
                self.wills[pid] = "\n".join(_ws_kill.will_lines)
            await self.send_dm(member, "💀 Bạn đã chết — di chúc đã được khóa lại tự động.")

        # Gán Dead role + mute nếu cần
        if self._muting_enabled:
            await self._apply_dead_role(member, force_mute=force_mute)

        # on_death hook
        if role and hasattr(role, "on_death"):
            fn     = role.on_death
            params = list(inspect.signature(fn).parameters.keys())
            try:
                if len(params) >= 2:
                    if any(k in reason for k in ("trục xuất", "vote", "bỏ phiếu")):
                        death_reason = "vote"
                    elif any(k in reason for k in ("Anomal", "Overlord", "Harbinger", "Stalker", "Puppeteer", "Corrupted AI", "Neuro", "Ký sinh")):
                        death_reason = "anomalies"
                    elif any(k in reason for k in ("Serial Killer", "Dreamweaver", "Ghost Ship", "Time-Weaver", "Doomsday", "Unknown")):
                        death_reason = "unknown"
                    elif any(k in reason for k in ("Pro Tester", "Giao Thức Kiểm Soát", "Hi sinh")):
                        death_reason = "event_sacrifice"   # Pro Tester tự hi sinh
                    elif any(k in reason for k in ("Blind", "gây mù", "blind")):
                        death_reason = "event"
                    elif any(k in reason for k in ("Cipher", "Mã Hóa")):
                        death_reason = "unknown"
                    else:
                        death_reason = reason
                    result = fn(self, death_reason)
                else:
                    result = fn(self)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                self.logger.error(f"on_death error [{role.name}]: {traceback.format_exc()}")

        # Khoá + flush di chúc khi chết
        _ws = self.will_states.get(pid)
        if _ws:
            _ws.writing_will = False
            _ws.locked = True
            # Luôn flush từ will_lines nếu có — đây là nguồn chính xác nhất
            if _ws.will_lines:
                self.wills[pid] = "\n".join(_ws.will_lines)
                self.logger.debug(
                    f"[Will] Flushed on death: {member.display_name} "
                    f"(pid={pid}), {len(_ws.will_lines)} lines"
                )
            # Nếu will_lines rỗng nhưng wills[pid] đã có dữ liệu realtime → giữ nguyên

        # Dead Chat
        await self.dead_chat_mgr.add_dead_player(member)

        # Anomaly Chat — khi Anomaly chết vẫn giữ quyền đọc nhưng không ghi
        if role and getattr(role, 'team', '') == 'Anomalies':
            await self.anomaly_chat_mgr.add_spectator(member)
            await self.anomaly_chat_mgr.send(
                f'💀 **{member.display_name}** đã ngã xuống... Phe Dị Thể mất đi một thành viên.'
            )

        # Announce — nếu đang ban đêm, defer đến sáng; còn lại thông báo ngay
        if self.phase == "night":
            self.pending_death_announcements.append(member.display_name)
        else:
            await self.log(f"💀 **{member.display_name}** ĐÃ CHẾT.", color=0xe74c3c)

        # Night event log
        if any(k in reason for k in ("Anomal", "Overlord", "Harbinger", "Stalker", "Corrupted AI", "Puppeteer")):
            self.add_night_event("Anomalies", f"Phe Anomalies tiêu diệt **{member.display_name}**.")
        elif any(k in reason for k in ("Serial Killer", "Dreamweaver", "Ghost Ship", "Time-Weaver", "Doomsday", "Unknown")):
            self.add_night_event("Unknown", f"Thực thể ẩn danh tiêu diệt **{member.display_name}**.")
        elif any(k in reason for k in ("Quản Ngục", "xử tử", "Vigilante", "trục xuất", "Trapper", "Avenger", "Retributionist")):
            self.add_night_event("Survivors", f"**{member.display_name}** bị loại bởi Survivors.")
        elif any(k in reason for k in ("Ký sinh", "Neuro")):
            self.add_night_event("Anomalies", f"**{member.display_name}** tan rã do ký sinh đứt liên kết.")
        elif any(k in reason for k in ("Hi sinh sau khi kích hoạt", "Giao Thức Kiểm Soát")):
            self.add_night_event("Survivors", f"⚡ **{member.display_name}** hi sinh sau khi kích hoạt Giao Thức Kiểm Soát.")
        elif "bởi giao thức Pro Tester" in reason:
            self.add_night_event("Survivors", f"💀 **{member.display_name}** bị Overlord ép tiêu diệt bởi Pro Tester.")
        else:
            self.add_night_event("Anomalies", f"**{member.display_name}** bị tiêu diệt trong đêm.")

        # Mayor Aide notification
        aide = self.get_role_by_name("Phụ Tá Thị Trưởng")
        if aide and self.is_alive(aide.player.id):
            await self._safe_call(aide.on_other_death, self, member, label="MayorAide.on_other_death")

        # Janitor
        janitor = self.get_role_by_name("Lao Công")
        if janitor and janitor.player.id != pid:
            clean_effect = self.night_effects.get("clean_target")
            clean_select = self.selected_targets.get(janitor.player.id)
            if (clean_effect and clean_effect == pid) or (clean_select and clean_select.id == pid):
                self.cleaned_roles.add(pid)

        self._check_win()

    async def _safe_call_bool(self, fn, *args, label="") -> bool:
        try:
            result = fn(*args)
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception as e:
            self.logger.error(f"[{label}] {e}")
            return False

    async def revive_player(self, member: disnake.Member):
        pid = member.id
        if pid not in self.dead_players:
            return
        self.dead_players.discard(pid)
        self.alive_players.add(pid)
        self._invalidate_alive_cache()
        # Gỡ Dead role, gán lại Alive role, unmute
        dead_role  = self._get_dead_role()
        alive_role = self._get_alive_role()
        try:
            if not self.config.no_remove_roles:
                to_remove = [r for r in [dead_role] if r and r in member.roles]
                if to_remove:
                    await member.remove_roles(*to_remove, reason="Anomalies — hồi sinh")
                if alive_role and alive_role not in member.roles:
                    await member.add_roles(alive_role, reason="Anomalies — hồi sinh")
        except Exception as e:
            self.logger.warn(f"Revive role cleanup failed for {member.display_name}: {e}")
        if self.config.allow_voice and self._muting_enabled and member.voice:
            await self.voice_ctrl._try_mute(member, False)
        await self.log(f"✨ **{member.display_name}** đã được hồi sinh!", color=0x2ecc71)
        # Nếu là Anomaly được hồi sinh → cấp lại quyền ghi vào anomaly_chat
        revived_role = self.roles.get(pid)
        if revived_role and getattr(revived_role, "team", "") == "Anomalies":
            await self.anomaly_chat_mgr.add_member(member)
            await self.anomaly_chat_mgr.send(
                f"✨ **{member.display_name}** đã được hồi sinh và quay lại hàng ngũ Dị Thể!"
            )

    async def _process_kills(self):
        for pid, reason, bypass in self.kill_queue:
            member = self._players_dict.get(pid)
            if member:
                await self.kill_player(member, reason=reason, bypass=bypass)
        self.kill_queue.clear()

    # ══════════════════════════════════════════════════
    # §12.10  WIN CONDITION
    # ══════════════════════════════════════════════════

    def _check_win(self):
        if self.ended:
            return
        result = WinConditionManager.check(self)
        if result:
            self.ended  = True
            self.winner = result
            self.logger.info(f"Win condition met: {result}")

    check_win = _check_win   # backward compat

    async def _purge_text_channel(self, keep_id: int = None, reason: str = "Tự Động Dọn Dẹp"):
        """Xóa tất cả tin nhắn trong text_channel, giữ lại keep_id (và lobby embed). Thông báo sau 15s."""
        if not self.text_channel:
            return
        try:
            lobby_id = getattr(self, "lobby_message_id", None)

            def check(msg):
                if lobby_id and msg.id == lobby_id:
                    return False
                return keep_id is None or msg.id != keep_id

            deleted = []
            try:
                deleted = await self.text_channel.purge(limit=300, check=check, bulk=True)
            except disnake.Forbidden:
                async for msg in self.text_channel.history(limit=300):
                    if keep_id and msg.id == keep_id:
                        continue
                    if lobby_id and msg.id == lobby_id:
                        continue
                    try:
                        await msg.delete()
                        deleted.append(msg)
                        await asyncio.sleep(0.4)
                    except Exception:
                        pass

            count      = len(deleted)
            guild_name = self.guild.name if self.guild else "Server"
            if count > 0:
                await self.text_channel.send(
                    f"🧹 **[ {guild_name} ]** : Đã Xóa **{count}** Tin Nhắn ( {reason} )",
                    delete_after=15
                )
        except Exception as e:
            self.logger.warn(f"[purge_text_channel] {e}")

    async def end_game(self, winner: str):
        self.ended  = True
        self.winner = winner
        self.phase  = "ended"

        await self._fire_hooks("on_game_end")
        # Quản trò Gemini: dừng tất cả vòng chat
        if getattr(self, "gemini_host", None):
            try:
                await self.gemini_host.on_game_end()
            except Exception as _e:
                self.logger.warn(f"GeminiHost on_game_end lỗi: {_e}")

        colors = {TEAM_SURVIVOR: 0x2ecc71, TEAM_ANOMALY: 0xe74c3c, "Draw": 0x95a5a6}
        color  = colors.get(winner, 0x9b59b6)

        # ── Xác định loại kết thúc + ảnh ──────────────────────────────
        total_players   = len(self._players_dict)
        alive_count     = len(self.alive_players)
        eliminated      = total_players - alive_count

        if winner == TEAM_SURVIVOR:
            _ending_type = "survivor_win"
        elif winner == TEAM_ANOMALY:
            _ending_type = "anomaly_win"
        else:
            # Solo win (unknown entity) hoặc draw
            _ending_type = "unknown_win"

        _ending_image = _ENDING_IMAGES.get(_ending_type, "")

        # ── Gọi Gemini 2.5 Flash sinh câu dẫn chuyện kết thúc ─────────
        _narrator_text = ""
        try:
            _narrator_kwargs = dict(
                total=total_players,
                survivors=alive_count,
                eliminated=eliminated,
                winner_name=winner,
            )
            _narrator_text = await _ai_narrate_ending(_ending_type, **_narrator_kwargs)
        except Exception as _ne:
            self.logger.warn(f"[NarratorEnding] Lỗi gọi AI: {_ne}")

        # ── Build embed kết thúc ───────────────────────────────────────
        _description = _narrator_text if _narrator_text else f"**Người chiến thắng: {winner}**"
        if _narrator_text:
            _description += f"\n\n**🏆 Người chiến thắng: {winner}**"

        embed = disnake.Embed(
            title="🏁 TRẬN ĐẤU KẾT THÚC",
            description=_description,
            color=color
        )

        if _ending_image:
            embed.set_image(url=_ending_image)

        lines = []
        for pid, member in self._players_dict.items():
            role      = self.roles.get(pid)
            role_name = role.name if role else "???"
            status    = "✅" if self.is_alive(pid) else "💀"
            # Compact format: Tên · Vai Trò · emoji — mỗi người 1 hàng, ngắn gọn
            lines.append(f"`{member.display_name}` · {role_name} · {status}")

        embed.add_field(name="📋 Danh sách vai trò", value="\n".join(lines) or "—", inline=False)
        result_msg = await self.text_channel.send(embed=embed)

        # Xóa tất cả tin nhắn game, giữ bảng kết quả
        await self._purge_text_channel(keep_id=result_msg.id, reason="Kết Thúc Trận")

        await self._cleanup_temp_channels()
        await self.dead_chat_mgr.delete()
        await self.anomaly_chat_mgr.delete()

        # Tắt muting TRƯỚC — ngăn race condition với kill_player còn đang chạy
        self._muting_enabled = False
        await asyncio.sleep(0.3)

        # Trả lại nick gốc cho tất cả người đã đổi tên trong game
        await self.restore_all_nicks()

        # Unmute tất cả người chơi + gỡ Dead/Alive role
        all_members = list(self._players_dict.values())
        for member in all_members:
            await self._cleanup_discord_roles(member)
            await asyncio.sleep(0.1)

        # Unmute voice — gọi 2 lần để chắc chắn
        if self.config.allow_voice and self.voice_channel:
            await self.voice_ctrl.set_mute(all_members, False)
            await asyncio.sleep(2)
            await self.voice_ctrl.set_mute(all_members, False)
            self.logger.info(f"Unmuted {len(all_members)} players at game end")

        if self.config.debug_mode:
            self.logger.dump_to_file()

        self.logger.info(f"Game {self.game_id} ended. Winner: {winner}")
        # ── FIX: xóa persistent ingame status khi trận kết thúc ──
        try:
            _cfg = load_guild_config(self.guild_id)
            _cfg.pop("status", None)
            save_guild_config(self.guild_id, _cfg)
            clear_active_players(self.guild_id)
        except Exception as _e:
            self.logger.warn(f"[GameEngine] clear status lỗi: {_e}")

    # ══════════════════════════════════════════════════
    # §12.11  PHASE: DAY
    # ══════════════════════════════════════════════════

    async def emergency_force_end(self, reason: str = "Cập nhật hệ thống"):
        """
        FIX: Hủy trận khẩn cấp trước khi bot restart (gọi từ updater.py).
        1. Gửi thông báo hủy trận tới text channel
        2. Thu hồi Dead/Alive role toàn bộ người chơi
        3. Unmute voice + xóa temp channels + xóa dead chat
        4. Xóa persistent ingame status khỏi config file
        """
        if self.ended:
            return
        self.ended           = True
        self._muting_enabled = False
        self.phase           = "ended"

        # 1. Thông báo
        try:
            embed = disnake.Embed(
                title="⚠️ TRẬN ĐẤU BỊ HỦY",
                description=(
                    f"**Lý do:** {reason}\n\n"
                    "Bot sắp restart để cập nhật.\n"
                    "Toàn bộ vai trò sẽ được thu hồi ngay.\n"
                    "Mọi người vào lại trận mới sau khi bot bật."
                ),
                color=0xe74c3c
            )
            await self.text_channel.send(embed=embed)
        except Exception as _e:
            self.logger.warn(f"[emergency_force_end] Gửi thông báo lỗi: {_e}")

        # 2. Trả lại nick + thu hồi role + unmute
        try:
            await self.restore_all_nicks()
        except Exception:
            pass

        all_members = list(self._players_dict.values())
        for member in all_members:
            try:
                await self._cleanup_discord_roles(member)
            except Exception:
                pass
            await asyncio.sleep(0.05)

        if self.config.allow_voice and self.voice_channel:
            try:
                await self.voice_ctrl.set_mute(all_members, False)
            except Exception:
                pass

        # 3. Xóa temp channels + dead chat
        try:
            await self._cleanup_temp_channels()
        except Exception:
            pass
        try:
            await self.dead_chat_mgr.delete()
            await self.anomaly_chat_mgr.delete()
        except Exception:
            pass

        # 4. Clear persistent status
        try:
            _cfg = load_guild_config(self.guild_id)
            _cfg.pop("status", None)
            save_guild_config(self.guild_id, _cfg)
            clear_active_players(self.guild_id)
        except Exception:
            pass

        self.logger.info(f"[emergency_force_end] Hủy trận {self.game_id}: {reason}")

    async def phase_day(self):
        # ── Nhạc ngày ────────────────────────────────────────────
        if self.music_player:
            await self.music_player.play_day()
        self.phase      = "day"
        self.day_count += 1

        day_time = 20 if self.fast_forward_next_day else self.config.day_time

        await self._fire_hooks("on_day_start")
        # Quản trò Gemini chào mừng + bắt đầu vòng 30s ở text channel
        if self.gemini_host:
            try:
                await self.gemini_host.on_day_start(self.day_count)
            except Exception as _e:
                self.logger.warn(f"GeminiHost on_day_start lỗi: {_e}")
        await self.log(
            f"☀️ **NGÀY {self.day_count}** — Thảo luận bắt đầu! ({day_time}s)"
            + (" ⏩ *(Rút ngắn!)*" if self.fast_forward_next_day else ""),
            color=0xf39c12
        )

        # ── Thông báo xác chết từ đêm qua (defer đến sáng) ─────────────────
        if self.pending_death_announcements:
            for name in self.pending_death_announcements:
                narration = await _ai_narrate("night_death", name=name)
                if narration:
                    await self.log(
                        f"> {narration}\n💀 **{name}** đã chết trong đêm qua.",
                        color=0xe74c3c
                    )
                else:
                    await self.log(f"💀 **{name}** đã chết trong đêm qua.", color=0xe74c3c)
            self.pending_death_announcements.clear()

        # ── Bảng di chúc sáng — cho người sống xem di chúc người đã chết ────
        try:
            await send_morning_will_board(self)
        except Exception:
            pass

        # ── AI Narrator: tường thuật hành động đêm qua (mơ hồ, không tiết lộ vai trò) ────
        try:
            action_lines = []
            for actor_id, target in self.selected_targets.items():
                if actor_id not in self._players_dict:
                    continue
                actor_member = self._players_dict[actor_id]
                target_name  = getattr(target, "display_name", str(target))
                actor_role   = self.roles.get(actor_id)
                # role_hint mơ hồ — chỉ nói team, không nói tên role
                team = getattr(actor_role, "team", None) if actor_role else None
                if team == TEAM_ANOMALY:
                    role_hint = "một thực thể bóng tối"
                elif team == TEAM_SURVIVOR:
                    role_hint = "một người trong thị trấn"
                else:
                    role_hint = "một bóng ma vô danh"
                narration = await _ai_narrate(
                    "night_action",
                    actor=actor_member.display_name,
                    role_hint=role_hint,
                    target=target_name,
                )
                if narration:
                    action_lines.append(f"> {narration}")
            if action_lines:
                await self.log(
                    "🌘 **Những gì xảy ra trong bóng tối...**\n" + "\n".join(action_lines),
                    color=0x2c3e50
                )
        except Exception:
            pass

        alive_members = self.get_alive_players()

        # Unmute tất cả người còn sống vào ban ngày
        if self.config.allow_voice and self._muting_enabled and self.config.voice_mode != "parliament":
            if alive_members:
                await self.voice_ctrl.set_mute(alive_members, False)

        if self.config.voice_mode == "parliament":
            await self.voice_ctrl.start_parliament(alive_members, self.text_channel)

        if self.config.allow_skip:
            skip_tracker = SkipTracker(self, day_time)
            await self.text_channel.send(
                embed=disnake.Embed(
                    title="⏩ Bỏ Phiếu Rút Ngắn",
                    description=f"≥{int(self.config.skip_threshold*100)}% đồng ý → kết thúc sớm.",
                    color=0x3498db
                ),
                view=skip_tracker
            )
        else:
            skip_tracker = None

        # Đồng hồ đếm ngược ngày
        day_timer_embed = disnake.Embed(
            title=f"☀️ NGÀY {self.day_count} — THẢO LUẬN",
            description=f"⏱️ Còn lại: **{day_time}s**",
            color=0xf39c12
        )
        day_timer_msg = None
        try:
            day_timer_msg = await self.text_channel.send(embed=day_timer_embed)
        except Exception:
            pass
        for elapsed in range(day_time):
            await asyncio.sleep(1)
            # Kiểm tra skip vote — nếu đủ phiếu thì kết thúc sớm
            if skip_tracker is not None and skip_tracker.skip_event.is_set():
                break
            remaining = day_time - elapsed - 1
            if day_timer_msg:
                try:
                    day_timer_embed.description = f"⏱️ Còn lại: **{remaining}s**"
                    await day_timer_msg.edit(embed=day_timer_embed)
                except Exception:
                    pass
        if day_timer_msg:
            try:
                day_timer_embed.description = "⏱️ Hết thời gian thảo luận!"
                await day_timer_msg.edit(embed=day_timer_embed)
            except Exception:
                pass

        self.voice_ctrl.stop_parliament()

        # ── Event role: day end hooks ─────────────────────────────
        # Blind: tắt hiệu ứng mù sau khi ngày kết thúc
        if self.night_effects.get("blind_active"):
            self.night_effects["blind_active"] = False
            self.logger.info("[Event] blind_active reset sau khi ngày kết thúc.")

        await self._fire_hooks("on_day_end")
        # Quản trò Gemini: dừng chat ngày, chuyển sang Anomalies/Dead Chat
        if self.gemini_host:
            try:
                await self.gemini_host.on_day_end()
            except Exception as _e:
                self.logger.warn(f"GeminiHost on_day_end lỗi: {_e}")

    # ══════════════════════════════════════════════════
    # §12.12  PHASE: VOTING
    # ══════════════════════════════════════════════════

    async def phase_voting(self):
        self.phase = "vote"
        alive      = self.get_alive_players()
        if not alive:
            return

        # ── Nhạc bỏ phiếu ────────────────────────────────────────
        if self.music_player:
            await self.music_player.play_vote()

        await self._fire_hooks("on_vote_start")

        for revote_round in range(self.config.max_revotes + 1):
            is_revote = revote_round > 0
            label     = f"🗳️ **{'REVOTE ' if is_revote else ''}BỎ PHIẾU TRỤC XUẤT**"
            await self.log(f"{label} — Chọn người bạn muốn loại!", color=0xe67e22)

            session = VotingSession(self, alive, revote=is_revote)
            vote_time = self.config.vote_time
            view    = VoteViewV2(self, alive, vote_time, session)
            vote_timer_embed = disnake.Embed(
                title="🗳️ BỎ PHIẾU" + (" — REVOTE" if is_revote else ""),
                description="Nhấn nút để chọn người bị trục xuất."
                + (" *(Ẩn danh)*" if self.config.anonymous_vote else "")
                + f"\n\n⏱️ Còn lại: **{vote_time}s**",
                color=0xe67e22
            )
            vote_timer_msg = None
            try:
                vote_timer_msg = await self.text_channel.send(
                    embed=vote_timer_embed, view=view
                )
            except Exception:
                pass
            for elapsed in range(vote_time):
                await asyncio.sleep(1)
                remaining = vote_time - elapsed - 1
                if vote_timer_msg:
                    try:
                        new_desc = ("Nhấn nút để chọn người bị trục xuất."
                            + (" *(Ẩn danh)*" if self.config.anonymous_vote else "")
                            + f"\n\n⏱️ Còn lại: **{remaining}s**")
                        vote_timer_embed.description = new_desc
                        await vote_timer_msg.edit(embed=vote_timer_embed)
                    except Exception:
                        pass
            if vote_timer_msg:
                try:
                    vote_timer_embed.description = "⏱️ Hết thời gian bỏ phiếu!"
                    await vote_timer_msg.edit(embed=vote_timer_embed, view=None)
                except Exception:
                    pass

            target_id, reason = session.get_result()
            self.puppeteer_controls.clear()  # xóa SAU get_result() để Puppeteer hoạt động

            if reason == "skip":
                await self.log("⏭️ Bỏ phiếu bị bỏ qua.", color=0x95a5a6)
                return
            if reason == "no_votes":
                await self.log("⚖️ Không có phiếu nào. Không ai bị trục xuất.", color=0x95a5a6)
                return
            if reason == "tie":
                if self.config.revote_on_tie and revote_round < self.config.max_revotes:
                    await self.log("⚖️ Hòa phiếu! Tiến hành REVOTE...", color=0xe67e22)
                    continue
                await self.log("⚖️ Hòa phiếu! Không ai bị trục xuất.", color=0x95a5a6)
                return

            target = self._players_dict.get(target_id)
            if target:
                role      = self.roles.get(target_id)
                role_name = role.name if role and target_id not in self.cleaned_roles else "???"
                # Notify Psychopath exile hook BEFORE kill (so win check can read state)
                if role and hasattr(role, "on_exile_vote"):
                    try:
                        role.on_exile_vote(self, session.votes)
                    except Exception:
                        pass
                exile_narration = await _ai_narrate("exile_death", name=target.display_name)
                await self.log(
                    (f"> {exile_narration}\n" if exile_narration else "")
                    + f"🚫 **{target.display_name}** đã bị trục xuất!",
                    color=0xe74c3c
                )
                await self.kill_player(
                    target,
                    reason     = "Bị trục xuất bởi dân làng",
                    bypass     = True,
                    force_mute = True,   # Vote-out: LUÔN mute, bỏ qua config.mute_dead
                )
            break

        await self._fire_hooks("on_vote_end")

    # ══════════════════════════════════════════════════
    # §12.13  NIGHT REPORT (The Sleeper)
    # ══════════════════════════════════════════════════

    async def _send_sleeper_night_report(self):
        sleeper = self.get_role_by_name("Kẻ Ngủ Mê")
        if not sleeper or not self.is_alive(sleeper.player.id):
            return

        groups = {"Anomalies": [], "Survivors": [], "Unknown": []}
        for faction, text in self.night_events:
            groups.setdefault(faction, []).append(text)

        embed = disnake.Embed(
            title=f"🌙 CHỈ THỊ HỆ THỐNG — NGÀY {self.day_count + 1}",
            description=f"*Báo cáo Đêm {self.night_count}*",
            color=0x2c3e50
        )
        if not self.night_events:
            embed.add_field(name="📭 Kết quả", value="> Đêm qua không có hoạt động.", inline=False)
        else:
            for faction, label in [("Anomalies", "⚠️ Phe Anomalies"), ("Survivors", "🛡️ Phe Survivors"), ("Unknown", "❓ Thực thể Không Rõ")]:
                if groups.get(faction):
                    embed.add_field(name=label, value="\n".join(f"> {e}" for e in groups[faction]), inline=False)

        embed.set_footer(text="📝 Gõ 'Nhập di chúc' để bắt đầu viết di chúc.")
        await self.send_dm(sleeper.player, "", embed=embed)

    # ══════════════════════════════════════════════════
    # §12.15  CLEANUP
    # ══════════════════════════════════════════════════

    async def _cleanup_temp_channels(self):
        for ch in self.temp_channels:
            try:
                await ch.delete()
            except Exception:
                pass
        self.temp_channels.clear()

    # ══════════════════════════════════════════════════
    # §12.16  ACTION QUEUE REGISTRATION HELPERS
    # ══════════════════════════════════════════════════

    def register_action(self, action: NightAction):
        """Called by roles to register a night action."""
        self.action_queue.register(action)
        self.logger.debug(f"Action registered: {action.role_name} (priority={action.priority})")


# ══════════════════════════════════════════════════════════════════════
# §13  UI COMPONENTS
# ══════════════════════════════════════════════════════════════════════

class SkipTracker(disnake.ui.View):
    def __init__(self, game: GameEngine, day_time: int):
        super().__init__(timeout=day_time)
        self.game     = game
        self.skippers: Set[int] = set()
        self.skip_event: asyncio.Event = asyncio.Event()

    @disnake.ui.button(label="⏩ Bỏ qua thảo luận", style=disnake.ButtonStyle.secondary)
    async def skip(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        uid = interaction.user.id
        if not self.game.abuse_tracker.is_allowed(uid):
            await interaction.response.send_message(
                "⚠️ Bạn đang thực hiện hành động quá nhanh. Vui lòng chờ một chút.",
                ephemeral=True
            )
            return

        self.skippers.add(uid)
        total_alive = len([p for p in self.game.players if self.game.is_alive(p)])
        needed = max(1, (total_alive // 2) + 1)

        await interaction.response.send_message(
            f"⏩ **{interaction.user.display_name}** muốn bỏ qua. "
            f"({len(self.skippers)}/{needed} cần thiết)",
            ephemeral=False
        )

        if len(self.skippers) >= needed:
            self.skip_event.set()
