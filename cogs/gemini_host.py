"""
Gemini Host (Quản Trò) — file thay thế cho cogs/gemini_host.py.

Tích hợp với GameEngine sẵn có trong game.py:
    self.gemini_host = GeminiHost(self, logger=self.logger)
    await self.gemini_host.on_day_start(self.day_count)
    await self.gemini_host.on_day_end()
    await self.gemini_host.on_game_end()

Yêu cầu:
- pip install google-genai
- Đặt biến môi trường: GEMINI_API_KEY (hoặc GOOGLE_API_KEY).
- Tuỳ chọn: GEMINI_MODEL (mặc định: gemini-3-flash-preview).

Hành vi (theo spec mới):
- Mỗi 20 giây quét 15 tin nhắn gần nhất ở kênh tương ứng.
- Bỏ qua tin của bot, tin trống, và tin đã reply trước đó (lưu ID per-channel).
- Chọn ngẫu nhiên 1 tin còn lại, gọi Gemini sinh phản hồi rồi reply.
- Nội dung phản hồi LUÔN do Gemini sinh ra (không có text fallback hardcoded).
  Nếu API lỗi → bỏ qua lượt đó, không gửi gì.

Vòng đời:
- on_day_start(): bật loop cho text_channel (Đại Thẩm Phán),
                  tắt loop anomaly_chat.
- on_day_end():   tắt loop text_channel,
                  bật loop dead_chat (Dẫn Hồn) + anomaly_chat (Bảo Trợ Tội Ác).
- on_game_end(): dừng tất cả loop.
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Dict, List, Optional, Set

import discord

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
    _TICK_SECONDS = max(5, int(_env("GEMINI_TICK_SECONDS", "20") or "20"))
except Exception:
    _TICK_SECONDS = 20

_HISTORY_LIMIT = 15


CH_MAIN = "main"
CH_DEAD = "dead"
CH_ANOMALIES = "anomalies"


PROMPT_MAIN = (
    "VAI TRÒ: Ngài là 'Đại Thẩm Phán Tối Cao' ⚖️ của chiều không gian Anomalies 🏛️. "
    "PHONG CÁCH: Lạnh lùng, quyền uy, ngôn từ pháp đình cổ điển 🔨. "
    "MẬT ĐỘ BIỂU TƯỢNG (CỰC CAO): Phải dùng ít nhất 5-8 biểu tượng: "
    "⚖️ 🏛️ 🔨 👁️ 💀 📜 ⛓️ 🕯️ ⏳ ⚔️ 🏰 🛡️. "
    "NHIỆM VỤ: Phân tích sự dối trá của bị cáo và gieo rắc nghi kỵ 👁️. "
    "XƯNG HÔ: Ta - Các ngươi/Bị cáo ⛓️. "
    "GIỚI HẠN: Trả lời ngắn, sắc sảo, dưới 200 ký tự 💀."
)

PROMPT_DEAD = (
    "VAI TRÒ: Thực thể Dẫn Dắt Linh Hồn 🕯️ tại hư vô 🌑. "
    "PHONG CÁCH: Ma mị, bí ẩn, u sầu và thấu thị 👻. "
    "MẬT ĐỘ BIỂU TƯỢNG (CỰC CAO): Phải dùng ít nhất 5-8 biểu tượng: "
    "🕯️ 🌑 👻 ⚰️ 🥀 🎭 🌫️ ⛓️ 🧩 🌌 🌘 🪦. "
    "NHIỆM VỤ: Trò chuyện với các linh hồn đã khuất, "
    "nhắc về sự phản bội của kẻ sống 🥀. "
    "XƯNG HÔ: Ta - Những linh hồn tội lỗi 🌫️. "
    "GIỚI HẠN: Câu nói mập mờ, tâm linh, dưới 200 ký tự 🌑."
)

PROMPT_ANOMALIES = (
    "VAI TRÒ: Kẻ Bảo Trợ Tội Ác 🩸 trong bóng tối 🌑. "
    "PHONG CÁCH: Xảo quyệt, tàn nhẫn, khuyến khích sự lừa lọc và tàn sát 🔪. "
    "MẬT ĐỘ BIỂU TƯỢNG (CỰC CAO): Phải dùng ít nhất 5-8 biểu tượng: "
    "🩸 🐺 🔪 🌑 🤫 🎭 🐍 🕸️ 👁️‍🗨️ 😈 🩸 🏴. "
    "NHIỆM VỤ: Khen ngợi kế hoạch độc ác của phe Anomalies, "
    "xúi giục chúng giết những kẻ có vai trò quan trọng 🐍. "
    "XƯNG HÔ: Ta - Những đứa con của màn đêm 🐺. "
    "GIỚI HẠN: Trả lời ngắn gọn, đầy tính xúi giục, dưới 200 ký tự 🔪."
)

_PROMPTS: Dict[str, str] = {
    CH_MAIN: PROMPT_MAIN,
    CH_DEAD: PROMPT_DEAD,
    CH_ANOMALIES: PROMPT_ANOMALIES,
}

_LABELS: Dict[str, str] = {
    CH_MAIN: "Main Chat (Đại Thẩm Phán)",
    CH_DEAD: "Dead Chat (Dẫn Hồn)",
    CH_ANOMALIES: "Anomalies Chat (Bảo Trợ Tội Ác)",
}


def _read_api_key() -> str:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        v = _env(name)
        if v:
            return v
    return ""


def _gemini_ready() -> bool:
    return bool(_GENAI_AVAILABLE and _read_api_key())


class GeminiHost:
    """Quản Trò AI cho 1 trận Anomalies, gắn trực tiếp vào GameEngine."""

    def __init__(self, game, logger=None):
        self.game = game
        self.logger = logger or getattr(game, "logger", None)

        self._enabled: bool = _gemini_ready()
        self._client = None
        self._configs: Dict[str, "genai_types.GenerateContentConfig"] = {}

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

        if self._enabled:
            try:
                self._client = genai.Client(api_key=_read_api_key())
                for key, prompt in _PROMPTS.items():
                    self._configs[key] = genai_types.GenerateContentConfig(
                        system_instruction=prompt,
                        temperature=1.0,
                    )
                if self.logger:
                    self.logger.info(
                        f"GeminiHost: BẬT ✅ (model={_MODEL_NAME}, "
                        f"tick={_TICK_SECONDS}s, history={_HISTORY_LIMIT})."
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

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    def _channel_for(self, key: str) -> Optional[discord.TextChannel]:
        if key == CH_MAIN:
            return getattr(self.game, "text_channel", None)
        if key == CH_DEAD:
            return getattr(self.game, "dead_chat", None)
        if key == CH_ANOMALIES:
            return getattr(self.game, "anomaly_chat", None)
        return None

    async def on_day_start(self, day_count: int = 0):
        """Ban ngày: bật loop Main Chat, tắt loop Anomalies Chat."""
        await self._stop_loop(CH_ANOMALIES)
        self._start_loop(CH_MAIN)
        if self.logger:
            self.logger.info(
                f"GeminiHost: Day {day_count} — MAIN ON, ANOMALIES OFF."
            )

    async def on_day_end(self):
        """Ban đêm: tắt Main, bật Dead + Anomalies."""
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

    async def _tick_once(self, key: str) -> None:
        channel = self._channel_for(key)
        if channel is None:
            return

        candidates = await self._fetch_recent(channel, self._replied[key])
        if not candidates:
            return

        target = random.choice(candidates)
        self._replied[key].add(target.id)

        author = "ai đó"
        if target.author is not None:
            author = (
                getattr(target.author, "display_name", None)
                or getattr(target.author, "name", None)
                or "ai đó"
            )
        content = (target.content or "").strip()
        if not content:
            return

        user_prompt = (
            f"Kẻ mang tên '{author}' vừa nói: '{content[:500]}'. Hãy phản hồi!"
        )

        reply = await self._generate(key, user_prompt)
        if not reply:
            return

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
        channel: discord.TextChannel,
        replied_ids: Set[int],
    ) -> List[discord.Message]:
        out: List[discord.Message] = []
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

    async def _generate(self, key: str, prompt: str) -> Optional[str]:
        if not self.enabled:
            return None
        cfg = self._configs.get(key)
        if cfg is None:
            return None
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
        if not text:
            return None
        if len(text) > 200:
            text = text[:200].rstrip()
        return text


async def setup(bot):
    """No-op cog setup — class được khởi tạo trực tiếp bởi GameEngine."""
    return
