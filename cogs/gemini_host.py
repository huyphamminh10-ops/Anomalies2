"""
Gemini Host (Quản Trò) — sử dụng Gemini 2.5 Flash để đóng vai quản trò
sống động cho trận Anomalies.

Cách hoạt động:
- Khi ngày bắt đầu: chào mừng các Survivor còn sống trong text_channel chính,
  rồi cứ mỗi 30 giây chọn 1 trong 5 tin nhắn gần nhất để reply.
- Khi ngày kết thúc: dừng trò chuyện ở text_channel chính, chuyển sang
  bình luận trong Anomalies Chat và Dead Chat (cũng theo chu kỳ 30 giây).

Yêu cầu:
- Cài đặt: `pip install google-generativeai>=0.7.0`
- Đặt biến môi trường:
    * `GEMINI_API_KEY`  (ưu tiên) hoặc `GOOGLE_API_KEY`
    * `GEMINI_MODEL`    (tuỳ chọn, mặc định: gemini-2.5-flash)
    * `GEMINI_TICK_SECONDS` (tuỳ chọn, mặc định: 30)

Nếu không cấu hình được Gemini, host sẽ ở trạng thái no-op (không spam log).
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import List, Optional

import discord

try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except Exception:
    genai = None  # type: ignore
    _GENAI_AVAILABLE = False


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


_DEFAULT_MODEL = "gemini-2.5-flash"
_MODEL_NAME = _env("GEMINI_MODEL", _DEFAULT_MODEL) or _DEFAULT_MODEL
try:
    _TICK_SECONDS = max(5, int(_env("GEMINI_TICK_SECONDS", "30") or "30"))
except Exception:
    _TICK_SECONDS = 30
_HISTORY_LIMIT = 5

_SYSTEM_PROMPT = (
    "Bạn là QUẢN TRÒ (host) của một trận game nhập vai Mafia/Sói có tên 'Anomalies' "
    "trên Discord, nói tiếng Việt. Tính cách: dí dỏm, hơi cà khịa, biết châm biếm "
    "nhẹ nhàng để tạo không khí, nhưng không xúc phạm cá nhân. "
    "Quy tắc tuyệt đối:\n"
    "1) KHÔNG bao giờ tiết lộ ai là Anomaly, ai là Survivor, ai có vai gì.\n"
    "2) KHÔNG đoán hộ kết quả vote.\n"
    "3) Trả lời NGẮN GỌN: 1–2 câu, tối đa ~280 ký tự, văn phong chat Discord.\n"
    "4) Có thể dùng emoji vừa phải (1–2 cái).\n"
    "5) Nếu được hỏi về luật chơi → trả lời ngắn gọn theo hiểu biết chung "
    "về thể loại Sói/Mafia, không bịa role cụ thể của trận.\n"
)


def _read_api_key() -> str:
    """Đọc API key từ biến môi trường (ưu tiên GEMINI_API_KEY)."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        v = _env(name)
        if v:
            return v
    return ""


def _gemini_ready() -> bool:
    if not _GENAI_AVAILABLE:
        return False
    api_key = _read_api_key()
    if not api_key:
        return False
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception:
        return False


class GeminiHost:
    """Một instance gắn với một GameEngine."""

    def __init__(self, game, logger=None):
        self.game = game
        self.logger = logger or getattr(game, "logger", None)
        self._enabled: bool = _gemini_ready()
        self._model = None
        self._task_main: Optional[asyncio.Task] = None
        self._task_secret: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._last_replied_msg_id: Optional[int] = None

        if self._enabled:
            try:
                self._model = genai.GenerativeModel(
                    model_name=_MODEL_NAME,
                    system_instruction=_SYSTEM_PROMPT,
                )
                if self.logger:
                    self.logger.info(
                        f"GeminiHost: BẬT ✅ (model={_MODEL_NAME}, "
                        f"tick={_TICK_SECONDS}s) — đọc key từ biến môi trường."
                    )
            except Exception as e:
                self._enabled = False
                if self.logger:
                    self.logger.warn(f"GeminiHost: không khởi tạo được model: {e}")
        else:
            if self.logger:
                if not _GENAI_AVAILABLE:
                    self.logger.warn(
                        "GeminiHost: TẮT — chưa cài `google-generativeai`. "
                        "Chạy: pip install google-generativeai"
                    )
                else:
                    self.logger.warn(
                        "GeminiHost: TẮT — chưa có biến môi trường "
                        "GEMINI_API_KEY (hoặc GOOGLE_API_KEY). "
                        "Hãy đặt key rồi khởi động lại bot."
                    )

    # ── helpers ──────────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._enabled and self._model is not None

    async def _generate(self, prompt: str) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            resp = await asyncio.to_thread(
                self._model.generate_content,
                prompt,
            )
            text = (getattr(resp, "text", "") or "").strip()
            if not text:
                return None
            # Cắt cho an toàn.
            return text[:500]
        except Exception as e:
            if self.logger:
                self.logger.warn(f"GeminiHost: Gemini lỗi: {e}")
            return None

    async def _safe_send(self, channel, content: str):
        if not channel or not content:
            return
        try:
            await channel.send(content)
        except Exception as e:
            if self.logger:
                self.logger.warn(f"GeminiHost: send lỗi: {e}")

    def _alive_summary(self) -> str:
        try:
            alive = self.game.get_alive_players()
            return f"{len(alive)} người còn sống"
        except Exception:
            return "một số người còn sống"

    # ── DAY phase ────────────────────────────────────────────────────────
    async def on_day_start(self, day_count: int):
        """Gọi khi vào pha thảo luận ban ngày."""
        # Dừng vòng secret nếu còn
        await self._cancel_task("secret")

        text_ch = getattr(self.game, "text_channel", None)
        if not text_ch:
            return

        # Chào mừng
        if self.enabled:
            prompt = (
                f"Ngày thứ {day_count} vừa ló rạng. Hiện còn {self._alive_summary()}. "
                "Hãy chào mừng các sống sót bằng 1–2 câu dí dỏm, hỏi xem đêm qua "
                "có ai 'mất ngủ' không. Đừng nêu tên ai cụ thể."
            )
            text = await self._generate(prompt)
        else:
            text = None
        if not text:
            text = (
                f"☀️ Ngày {day_count} đã đến! Còn {self._alive_summary()}. "
                "Đêm qua ai mất ngủ giơ tay nào? 🫣"
            )
        await self._safe_send(text_ch, text)

        # Khởi động vòng 30s đọc text_channel
        self._stop_event = asyncio.Event()
        self._task_main = asyncio.create_task(self._loop_main_chat(text_ch))

    async def on_day_end(self):
        """Gọi khi pha thảo luận kết thúc (sau vote/skip). Chuyển vai sang
        bình luận ở Anomalies Chat & Dead Chat."""
        await self._cancel_task("main")

        anomaly_ch = getattr(self.game, "anomaly_chat", None)
        dead_ch = getattr(self.game, "dead_chat", None)

        # Lời tạm biệt ở channel chính
        text_ch = getattr(self.game, "text_channel", None)
        if text_ch and self.enabled:
            farewell = await self._generate(
                "Pha ngày vừa kết thúc. Hãy nói 1 câu ngắn tạm biệt cả làng, "
                "hẹn gặp lại sáng mai, kiểu cà khịa nhẹ."
            )
            if farewell:
                await self._safe_send(text_ch, farewell)

        # Mở lời ở 2 secret channel
        if anomaly_ch:
            msg = await self._generate(
                "Bạn đang ở kênh bí mật của phe Anomalies sau khi ngày kết thúc. "
                "Hãy buông 1–2 câu cà khịa kiểu 'chứng kiến mọi chuyện', không "
                "tiết lộ ai bị nghi. Có thể ám chỉ rằng đêm nay sắp tới rồi."
            ) if self.enabled else None
            await self._safe_send(
                anomaly_ch,
                msg or "🔴 Quản trò ghé chơi tí: ngày qua phe ta giấu mặt khéo phết 😏",
            )

        if dead_ch:
            msg = await self._generate(
                "Bạn đang ở Dead Chat. Hãy nói 1 câu hài hước tới hội linh hồn, "
                "khích họ đoán xem ai sẽ 'xuống' tiếp theo, không nêu tên thật."
            ) if self.enabled else None
            await self._safe_send(
                dead_ch,
                msg or "💀 Hội ma ơi, đoán thử mai ai xuống chơi cùng nào? 👻",
            )

        # Khởi động vòng 30s ở 2 secret channel song song
        self._stop_event = asyncio.Event()
        self._task_secret = asyncio.create_task(
            self._loop_secret_chats(anomaly_ch, dead_ch)
        )

    async def on_game_end(self):
        await self._cancel_task("main")
        await self._cancel_task("secret")

    # ── loops ────────────────────────────────────────────────────────────
    async def _loop_main_chat(self, channel):
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=_TICK_SECONDS)
                    return  # stop event triggered
                except asyncio.TimeoutError:
                    pass

                if self._stop_event.is_set():
                    return

                msgs = await self._fetch_recent(channel)
                if not msgs:
                    continue
                target = random.choice(msgs)
                if target.id == self._last_replied_msg_id:
                    continue
                self._last_replied_msg_id = target.id

                author = target.author.display_name if target.author else "ai đó"
                content = (target.content or "").strip()
                if not content:
                    continue

                prompt = (
                    f"Trong pha ngày của trận, người tên '{author}' vừa nhắn: "
                    f"\"{content[:300]}\".\n"
                    "Hãy reply ngắn (1–2 câu) đúng phong cách quản trò cà khịa, "
                    "không tiết lộ vai trò ai. Có thể trêu nhẹ, hoặc đặt câu "
                    "hỏi mở để khuấy động không khí."
                )
                reply = await self._generate(prompt) if self.enabled else None
                if not reply:
                    continue
                try:
                    await target.reply(reply, mention_author=False)
                except Exception:
                    await self._safe_send(channel, reply)
        except asyncio.CancelledError:
            return

    async def _loop_secret_chats(self, anomaly_ch, dead_ch):
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=_TICK_SECONDS)
                    return
                except asyncio.TimeoutError:
                    pass

                if self._stop_event.is_set():
                    return

                # Mỗi tick chọn 1 trong 2 channel để bình luận
                channels = [c for c in (anomaly_ch, dead_ch) if c is not None]
                if not channels:
                    return
                ch = random.choice(channels)
                msgs = await self._fetch_recent(ch)
                if not msgs:
                    continue
                target = random.choice(msgs)
                if target.id == self._last_replied_msg_id:
                    continue
                self._last_replied_msg_id = target.id

                author = target.author.display_name if target.author else "ai đó"
                content = (target.content or "").strip()
                if not content:
                    continue

                ctx_label = "Anomalies Chat" if ch is anomaly_ch else "Dead Chat"
                prompt = (
                    f"Đây là kênh bí mật '{ctx_label}'. '{author}' vừa nhắn: "
                    f"\"{content[:300]}\".\n"
                    "Hãy reply 1–2 câu đúng tinh thần kênh đó (Anomalies = âm "
                    "mưu, Dead = ma than thở), không lộ thông tin trận, không "
                    "nêu tên người ngoài kênh."
                )
                reply = await self._generate(prompt) if self.enabled else None
                if not reply:
                    continue
                try:
                    await target.reply(reply, mention_author=False)
                except Exception:
                    await self._safe_send(ch, reply)
        except asyncio.CancelledError:
            return

    async def _fetch_recent(self, channel) -> List[discord.Message]:
        out: List[discord.Message] = []
        try:
            async for m in channel.history(limit=_HISTORY_LIMIT):
                if m.author and getattr(m.author, "bot", False):
                    continue
                if not (m.content or "").strip():
                    continue
                out.append(m)
        except Exception as e:
            if self.logger:
                self.logger.warn(f"GeminiHost: history lỗi: {e}")
        return out

    async def _cancel_task(self, which: str):
        # Set stop event để các loop tự thoát sạch
        try:
            self._stop_event.set()
        except Exception:
            pass

        task = self._task_main if which == "main" else self._task_secret
        if task and not task.done():
            task.cancel()
            try:
                await task
            except Exception:
                pass
        if which == "main":
            self._task_main = None
        else:
            self._task_secret = None
        # Reset event cho lần kế
        self._stop_event = asyncio.Event()
