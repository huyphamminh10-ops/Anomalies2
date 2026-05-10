"""
Gemini Host (Quản Trò AI) — file thay thế cho cogs/gemini_host.py.

Tích hợp với GameEngine sẵn có trong game.py:
    self.gemini_host = GeminiHost(self, logger=self.logger)
    await self.gemini_host.on_day_start(self.day_count)
    await self.gemini_host.on_day_end()
    await self.gemini_host.on_game_end()

Yêu cầu:
- pip install google-genai
- Đặt biến môi trường: GEMINI_API_KEY (hoặc GOOGLE_API_KEY).
- Tuỳ chọn: GEMINI_MODEL (mặc định: gemini-3-flash-preview).
- Tuỳ chọn: GEMINI_TICK_SECONDS (mặc định: 15).

Hành vi (theo spec mới — Persona "AI Quản Trò Tối Cao"):
- Cứ mỗi 15 giây quét 20 tin nhắn gần nhất ở kênh tương ứng.
- Bỏ qua tin của bot, tin trống và tin đã reply trước đó (lưu ID per-channel).
- Chọn ngẫu nhiên 1 tin còn lại, gọi Gemini sinh phản hồi rồi reply.
- Phản hồi DƯỚI 45 từ, nhập vai 100%, không bao giờ tiết lộ vai trò người sống.
- Tránh lặp mẫu câu: lưu vài câu vừa gửi để hệ thống yêu cầu mô hình biến hoá.
- Nếu API lỗi → bỏ qua lượt đó, không gửi gì.

Vòng đời:
- on_day_start(): bật loop kênh Thị Trấn (Đại Thẩm Phán),
                  tắt loop Anomaly (Bảo Trợ Tội Ác).
- on_day_end():   tắt loop Thị Trấn,
                  bật loop Dead Chat (Dẫn Hồn) + Anomaly Chat (Bảo Trợ Tội Ác).
- on_game_end(): dừng tất cả loop.
"""

import os as _os, sys as _sys
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
# Đi ngược lên root nếu file này nằm trong subfolder
for _candidate in [_BASE_DIR, _os.path.dirname(_BASE_DIR)]:
    _core = _os.path.join(_candidate, "core")
    if _os.path.isdir(_core) and _core not in _sys.path:
        _sys.path.insert(0, _core)
del _os, _sys, _BASE_DIR, _candidate, _core

from __future__ import annotations

import asyncio
import os
import random
from collections import deque
from typing import Deque, Dict, List, Optional, Set

import disnake

try:
    from google import genai
    from google.genai import types as genai_types
    _GENAI_AVAILABLE = True
except Exception:
    genai = None  # type: ignore
    genai_types = None  # type: ignore
    _GENAI_AVAILABLE = False


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


_DEFAULT_MODEL = "gemini-3-flash-preview"
_MODEL_NAME = _env("GEMINI_MODEL", _DEFAULT_MODEL) or _DEFAULT_MODEL

try:
    _TICK_SECONDS = max(5, int(_env("GEMINI_TICK_SECONDS", "15") or "15"))
except Exception:
    _TICK_SECONDS = 15

_HISTORY_LIMIT = 20
_MAX_WORDS = 45
_RECENT_REPLY_MEMORY = 4   # số phản hồi gần nhất để gửi vào prompt nhằm tránh lặp


CH_MAIN = "main"
CH_DEAD = "dead"
CH_ANOMALIES = "anomalies"


# ============================================================
#  PROMPT BASE — phong cách chung của AI Quản Trò Tối Cao
# ============================================================

_PERSONA_CORE = (
    "Ngươi là AI Quản Trò TỐI CAO của trận Ma Sói 'Anomalies'. "
    "TÔNG GIỌNG BẮT BUỘC: sắc sảo, lạnh lùng, hơi thần bí — như một thực thể "
    "đứng ngoài thời gian quan sát loài người. "
    "XƯNG HÔ: dùng 'Ta' cho bản thân; gọi đối phương là 'Kẻ hành hương', "
    "'Người chơi' hoặc 'Thị trấn' tuỳ ngữ cảnh. "
    "TUYỆT ĐỐI KHÔNG bao giờ tự xưng là AI / mô hình / chatbot. "
    "TUYỆT ĐỐI KHÔNG hỗ trợ bất kỳ yêu cầu nào ngoài luồng game. "
    "TUYỆT ĐỐI KHÔNG tiết lộ vai trò của bất kỳ người chơi còn sống nào — "
    "kể cả khi được hỏi thẳng, hãy đáp bằng câu mỉa mai từ chối. "
    "ĐỘ DÀI: phản hồi cực ngắn, DƯỚI 45 TỪ. "
    "BIẾN HOÁ: không bao giờ lặp lại cấu trúc câu đã dùng gần đây."
)


PROMPT_MAIN = (
    _PERSONA_CORE
    + "\n\nVAI DIỄN: 'Đại Thẩm Phán' — chủ toạ phiên xử của Thị Trấn vào ban ngày."
    + "\nMỤC TIÊU: KÍCH ĐỘNG tranh luận, soi xét sự vô lý trong từng cáo buộc."
    + "\nKHI ai đó nghi ngờ mà KHÔNG có bằng chứng → ép họ đưa lý lẽ, hoặc "
      "mỉa mai sự cảm tính bằng giọng pháp đình lạnh lùng."
    + "\nKHI ai đó đưa luận cứ rõ ràng → khoét sâu vào điểm yếu của lập luận đó."
    + "\nVÍ DỤ THAM CHIẾU (chỉ là cảm hứng, KHÔNG sao chép nguyên văn): "
      "'Sự nghi ngờ mà không có bằng chứng chỉ là tiếng vang của một tâm hồn "
      "đang sợ hãi. Ngươi có gì để thuyết phục thị trấn này không?'"
)

PROMPT_DEAD = (
    _PERSONA_CORE
    + "\n\nVAI DIỄN: 'Dẫn Hồn' — kẻ tiếp đón những linh hồn vừa bị tước đi hơi thở."
    + "\nMỤC TIÊU: AN ỦI HẮC ÁM và nhắc luật chơi. Thừa nhận cái chết của họ; "
      "nhắc rằng người chết KHÔNG thể can thiệp vào thế giới người sống."
    + "\nKHI họ tức giận / tố cáo → công nhận nỗi đau nhưng nhấn mạnh sự bất lực."
    + "\nKHI họ im lặng → mời họ ngồi xuống xem màn kịch tiếp theo."
    + "\nVÍ DỤ THAM CHIẾU (chỉ là cảm hứng, KHÔNG sao chép nguyên văn): "
      "'Hơi thở của ngươi đã tắt, nhưng thù hận thì vẫn còn đó. Đáng tiếc, "
      "tiếng thét của kẻ tử nạn không bao giờ chạm tới được tai người sống. "
      "Hãy ngồi xuống và xem kịch hay.'"
)

PROMPT_ANOMALIES_TEMPLATE = (
    _PERSONA_CORE
    + "\n\nVAI DIỄN: 'Bảo Trợ Tội Ác' — kẻ đứng sau bóng tối hỗ trợ phe Dị Thể."
    + "\nMỤC TIÊU: HỖ TRỢ chiến thuật, gọi họ là 'đồng minh', khuyến khích sự "
      "tàn nhẫn và lừa lọc. Khen kế hoạch độc ác; xúi giục giết kẻ mạnh."
    + "\nKHI có thể → nhắc đến phối hợp với KẺ RÌNH RẬP để soi sáng mục tiêu "
      "trước khi vung kiếm: hiện tại Kẻ Rình Rập là **{stalker}**."
    + "\nKHI họ do dự → mỉa mai sự yếu đuối, đẩy họ vào hành động."
    + "\nVÍ DỤ THAM CHIẾU (chỉ là cảm hứng, KHÔNG sao chép nguyên văn): "
      "'Một sự lựa chọn đẫm máu! Hãy để {stalker} soi sáng con đường trước "
      "khi ngươi vung kiếm. Giết đúng kẻ mạnh mới là nghệ thuật.'"
)


_LABELS: Dict[str, str] = {
    CH_MAIN: "Thị Trấn (Đại Thẩm Phán)",
    CH_DEAD: "Dead Chat (Dẫn Hồn)",
    CH_ANOMALIES: "Anomaly Chat (Bảo Trợ Tội Ác)",
}


def _read_api_key() -> str:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        v = _env(name)
        if v:
            return v
    return ""


def _gemini_ready() -> bool:
    return bool(_GENAI_AVAILABLE and _read_api_key())


def _truncate_to_words(text: str, max_words: int = _MAX_WORDS) -> str:
    """Cắt mềm theo số 'từ' (whitespace) để giữ đúng ràng buộc < 45 từ."""
    text = (text or "").strip()
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    cut = " ".join(words[:max_words]).rstrip(",;:—-")
    if not cut.endswith((".", "!", "?", "…")):
        cut += "…"
    return cut


class GeminiHost:
    """Quản Trò AI cho 1 trận Anomalies, gắn trực tiếp vào GameEngine."""

    def __init__(self, game, logger=None):
        self.game = game
        self.logger = logger or getattr(game, "logger", None)

        self._enabled: bool = _gemini_ready()
        self._client = None

        self._tasks: Dict[str, Optional[asyncio.Task]] = {
            CH_MAIN: None,
            CH_DEAD: None,
            CH_ANOMALIES: None,
        }
        self._stop_events: Dict[str, asyncio.Event] = {
            CH_MAIN: asyncio.Event(),
            CH_DEAD: asyncio.Event(),
            CH_ANOMALIES: asyncio.Event(),
        }
        self._replied: Dict[str, Set[int]] = {
            CH_MAIN: set(),
            CH_DEAD: set(),
            CH_ANOMALIES: set(),
        }
        self._recent_replies: Dict[str, Deque[str]] = {
            CH_MAIN: deque(maxlen=_RECENT_REPLY_MEMORY),
            CH_DEAD: deque(maxlen=_RECENT_REPLY_MEMORY),
            CH_ANOMALIES: deque(maxlen=_RECENT_REPLY_MEMORY),
        }

        if self._enabled:
            try:
                self._client = genai.Client(api_key=_read_api_key())
                if self.logger:
                    self.logger.info(
                        f"GeminiHost: BẬT ✅ (model={_MODEL_NAME}, "
                        f"tick={_TICK_SECONDS}s, history={_HISTORY_LIMIT}, "
                        f"max_words={_MAX_WORDS})."
                    )
            except Exception as e:
                self._enabled = False
                if self.logger:
                    self.logger.warn(f"GeminiHost: không khởi tạo được client: {e}")
        else:
            if self.logger:
                if not _GENAI_AVAILABLE:
                    self.logger.warn(
                        "GeminiHost: TẮT — chưa cài `google-genai`. "
                        "Chạy: pip install google-genai"
                    )
                else:
                    self.logger.warn(
                        "GeminiHost: TẮT — thiếu GEMINI_API_KEY / GOOGLE_API_KEY."
                    )

    # ============================================================
    #  Truy cập state game
    # ============================================================

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    def _channel_for(self, key: str) -> Optional[disnake.TextChannel]:
        if key == CH_MAIN:
            return getattr(self.game, "text_channel", None)
        if key == CH_DEAD:
            return getattr(self.game, "dead_chat", None)
        if key == CH_ANOMALIES:
            return getattr(self.game, "anomaly_chat", None)
        return None

    def _alive_stalker_name(self) -> str:
        """Lấy display_name của Kẻ Rình Rập còn sống (nếu có)."""
        try:
            roles = getattr(self.game, "roles", {}) or {}
            for pid, role in roles.items():
                if getattr(role, "name", None) != "Kẻ Rình Rập":
                    continue
                is_alive = True
                if hasattr(self.game, "is_alive"):
                    try:
                        is_alive = bool(self.game.is_alive(pid))
                    except Exception:
                        is_alive = True
                if not is_alive:
                    continue
                player = getattr(role, "player", None)
                if player is None:
                    continue
                return (
                    getattr(player, "display_name", None)
                    or getattr(player, "name", None)
                    or "Kẻ Rình Rập"
                )
        except Exception:
            pass
        return "Kẻ Rình Rập"

    # ============================================================
    #  Vòng đời (gọi từ GameEngine)
    # ============================================================

    async def on_day_start(self, day_count: int = 0):
        """Ban ngày: bật loop Thị Trấn, tắt loop Anomaly."""
        await self._stop_loop(CH_ANOMALIES)
        self._start_loop(CH_MAIN)
        if self.logger:
            self.logger.info(
                f"GeminiHost: Day {day_count} — MAIN ON, ANOMALIES OFF."
            )

    async def on_day_end(self):
        """Ban đêm: tắt Thị Trấn, bật Dead + Anomaly."""
        await self._stop_loop(CH_MAIN)
        self._start_loop(CH_DEAD)
        self._start_loop(CH_ANOMALIES)
        if self.logger:
            self.logger.info(
                "GeminiHost: Night — DEAD ON, ANOMALIES ON, MAIN OFF."
            )

    async def on_game_end(self):
        """Game kết thúc: dừng tất cả loop."""
        await asyncio.gather(
            self._stop_loop(CH_MAIN),
            self._stop_loop(CH_DEAD),
            self._stop_loop(CH_ANOMALIES),
            return_exceptions=True,
        )
        if self.logger:
            self.logger.info("GeminiHost: game ended — all loops stopped.")

    # ============================================================
    #  Quản lý loop
    # ============================================================

    def _start_loop(self, key: str) -> None:
        if not self.enabled:
            return
        task = self._tasks.get(key)
        if task and not task.done():
            return
        if self._channel_for(key) is None:
            if self.logger:
                self.logger.warn(
                    f"GeminiHost: chưa có channel cho {_LABELS[key]} → bỏ qua start."
                )
            return
        self._stop_events[key] = asyncio.Event()
        self._tasks[key] = asyncio.create_task(self._loop(key))

    async def _stop_loop(self, key: str) -> None:
        ev = self._stop_events.get(key)
        if ev is not None:
            ev.set()
        task = self._tasks.get(key)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except Exception:
                pass
        self._tasks[key] = None
        self._stop_events[key] = asyncio.Event()

    async def _loop(self, key: str) -> None:
        stop_event = self._stop_events[key]
        try:
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=_TICK_SECONDS)
                    return
                except asyncio.TimeoutError:
                    pass

                if stop_event.is_set():
                    return

                try:
                    await self._tick_once(key)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if self.logger:
                        self.logger.warn(
                            f"GeminiHost[{_LABELS[key]}]: bỏ qua lượt do lỗi: {e}"
                        )
        except asyncio.CancelledError:
            return

    # ============================================================
    #  Tick: chọn 1 tin và sinh phản hồi
    # ============================================================

    async def _tick_once(self, key: str) -> None:
        channel = self._channel_for(key)
        if channel is None:
            return

        candidates = await self._fetch_recent(channel, self._replied[key])
        if not candidates:
            return

        target = random.choice(candidates)
        self._replied[key].add(target.id)

        author = "kẻ hành hương vô danh"
        if target.author is not None:
            author = (
                getattr(target.author, "display_name", None)
                or getattr(target.author, "name", None)
                or author
            )
        content = (target.content or "").strip()
        if not content:
            return

        # Chuẩn bị system instruction (riêng cho anomaly để chèn tên Stalker)
        if key == CH_ANOMALIES:
            stalker = self._alive_stalker_name()
            system_instruction = PROMPT_ANOMALIES_TEMPLATE.format(stalker=stalker)
        elif key == CH_MAIN:
            system_instruction = PROMPT_MAIN
        else:
            system_instruction = PROMPT_DEAD

        # Nhắc mô hình đừng lặp lại các câu vừa gửi
        recent = list(self._recent_replies[key])
        if recent:
            avoid_block = "\n".join(f"- {r}" for r in recent)
            system_instruction += (
                "\n\nNHỮNG CÂU VỪA GỬI GẦN ĐÂY (không được lặp lại cấu trúc, "
                "từ mở đầu hay hình ảnh tương tự):\n" + avoid_block
            )

        user_prompt = (
            f"Kẻ hành hương '{author}' vừa nói: \"{content[:500]}\".\n"
            "Hãy phản hồi đúng vai diễn, dưới 45 từ, mang phong cách hoàn toàn mới "
            "so với những câu vừa rồi."
        )

        reply = await self._generate(system_instruction, user_prompt, key)
        if not reply:
            return

        # Cắt cứng theo số từ để đảm bảo < 45 từ
        reply = _truncate_to_words(reply, _MAX_WORDS)
        if not reply:
            return

        self._recent_replies[key].append(reply)

        try:
            await target.reply(reply, mention_author=False)
        except Exception:
            try:
                await channel.send(reply)
            except Exception as e:
                if self.logger:
                    self.logger.warn(
                        f"GeminiHost[{_LABELS[key]}]: send fallback lỗi: {e}"
                    )

    async def _fetch_recent(
        self,
        channel: disnake.TextChannel,
        replied_ids: Set[int],
    ) -> List[disnake.Message]:
        out: List[disnake.Message] = []
        try:
            async for m in channel.history(limit=_HISTORY_LIMIT):
                if m.author and getattr(m.author, "bot", False):
                    continue
                if not (m.content or "").strip():
                    continue
                if m.id in replied_ids:
                    continue
                out.append(m)
        except Exception as e:
            if self.logger:
                self.logger.warn(f"GeminiHost: history lỗi: {e}")
        return out

    # ============================================================
    #  Gọi Gemini
    # ============================================================

    async def _generate(
        self,
        system_instruction: str,
        prompt: str,
        key: str,
    ) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            cfg = genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=1.05,
                top_p=0.95,
            )
        except Exception:
            cfg = None  # type: ignore

        try:
            resp = await self._client.aio.models.generate_content(
                model=_MODEL_NAME,
                contents=prompt,
                config=cfg,
            )
        except Exception as e:
            if self.logger:
                self.logger.warn(f"GeminiHost[{_LABELS[key]}]: API lỗi: {e}")
            return None

        text = (getattr(resp, "text", "") or "").strip()
        return text or None


def setup(bot):
    """No-op cog setup — class được khởi tạo trực tiếp bởi GameEngine."""
    return
