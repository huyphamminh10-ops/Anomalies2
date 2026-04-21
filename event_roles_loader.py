# ══════════════════════════════════════════════════════════════════
# event_roles_loader.py — Anomalies v2.0
# ══════════════════════════════════════════════════════════════════

import os
import json
import random
import importlib.util
import time
import asyncio
import logging

log = logging.getLogger("EventRolesLoader")

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
EVENT_ROLES_DIR  = os.path.join(BASE_DIR, "roles", "event")
EVENT_STATE_FILE = os.path.join(BASE_DIR, "event_state.json")
ROTATE_INTERVAL  = 3600

_ROLE_DEFAULTS = {"weight": 3, "min_players": 5, "max_count": 1, "core": False, "event": True}


def _cls_to_entry(cls) -> dict:
    faction = getattr(cls, "team", None) or getattr(cls, "faction", "Survivors")
    return {
        "name":        cls.name,
        "faction":     faction,
        "weight":      getattr(cls, "weight",      _ROLE_DEFAULTS["weight"]),
        "min_players": getattr(cls, "min_players", _ROLE_DEFAULTS["min_players"]),
        "max_count":   getattr(cls, "max_count",   _ROLE_DEFAULTS["max_count"]),
        "core":        False,
        "event":       True,
    }


def _entry_name(entry) -> str:
    return entry["name"] if isinstance(entry, dict) else entry


class EventRolesLoader:
    def __init__(self, role_manager=None):
        self.role_manager = role_manager
        self._state: dict = {}
        self._class_cache: dict[str, type] = {}
        self._rotate_task: asyncio.Task | None = None

    def setup(self):
        os.makedirs(EVENT_ROLES_DIR, exist_ok=True)
        self._load_state()
        discovered = self._scan_event_roles()
        self._merge_pool(discovered)
        self._save_state()
        if self.role_manager:
            for cls in self._class_cache.values():
                self.role_manager.register(cls)
            log.info(f"[EventLoader] Đăng ký {len(self._class_cache)} event role.")
        log.info(f"[EventLoader] Pool: {[_entry_name(e) for e in self._state.get('pool', [])]}")
        log.info(f"[EventLoader] Current: {self._state.get('current')}")

    def start_rotate_loop(self, bot):
        if self._rotate_task and not self._rotate_task.done():
            return
        self._rotate_task = bot.loop.create_task(self._rotate_loop())
        log.info("[EventLoader] Rotate loop đã khởi động.")

    def stop_rotate_loop(self):
        if self._rotate_task:
            self._rotate_task.cancel()
            self._rotate_task = None

    def get_current_role_name(self) -> str | None:
        return self._state.get("current")

    def get_current_role_class(self) -> type | None:
        name = self.get_current_role_name()
        return self._class_cache.get(name) if name else None

    def get_pool(self) -> list[dict]:
        return list(self._state.get("pool", []))

    def get_queue(self) -> list[dict]:
        return list(self._state.get("queue", []))

    def get_current_entry(self) -> dict | None:
        name = self.get_current_role_name()
        if not name:
            return None
        return next((e for e in self._state.get("pool", []) if _entry_name(e) == name), None)

    def seconds_until_next_rotate(self) -> int:
        return max(0, int(ROTATE_INTERVAL - (time.time() - self._state.get("last_rotate", 0))))

    def force_rotate(self):
        self._rotate()
        self._save_state()

    def inject_into_pool(self, pool: list[str], total_players: int) -> list[str]:
        current_cls = self.get_current_role_class()
        if current_cls is None:
            return pool
        entry = self.get_current_entry()
        min_p = entry["min_players"] if entry else getattr(current_cls, "min_players", 5)
        if total_players < min_p:
            return pool
        faction      = entry["faction"] if entry else (getattr(current_cls, "team", None) or "Survivors")
        fallback_map = {"Survivors": "Civilian", "Anomalies": "Anomaly", "Unknown": "Serial Killer"}
        fallback     = fallback_map.get(faction, "Civilian")
        new_pool     = list(pool)
        for i in reversed(range(len(new_pool))):
            if new_pool[i] == fallback:
                new_pool[i] = current_cls.name
                return new_pool
        new_pool.append(current_cls.name)
        return new_pool

    # ── SCAN ─────────────────────────────────────────────────────

    def _scan_event_roles(self) -> list[dict]:
        discovered = []
        if not os.path.isdir(EVENT_ROLES_DIR):
            return discovered
        for filename in sorted(os.listdir(EVENT_ROLES_DIR)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            filepath    = os.path.join(EVENT_ROLES_DIR, filename)
            module_name = f"roles.event.{filename[:-3]}"
            try:
                spec   = importlib.util.spec_from_file_location(module_name, filepath)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and hasattr(attr, "name") and hasattr(attr, "team")
                            and attr.name not in ("Base", "BaseRole") and attr.__module__ == module_name):
                        self._class_cache[attr.name] = attr
                        discovered.append(_cls_to_entry(attr))
                        log.info(f"[EventLoader] Found: '{attr.name}'")
            except Exception as e:
                log.error(f"[EventLoader] Lỗi '{filename}': {e}")
        return discovered

    # ── STATE ────────────────────────────────────────────────────

    def _load_state(self):
        if os.path.exists(EVENT_STATE_FILE):
            try:
                with open(EVENT_STATE_FILE, "r", encoding="utf-8") as f:
                    self._state = json.load(f)
                self._state["pool"]  = self._migrate(self._state.get("pool",  []))
                self._state["queue"] = self._migrate(self._state.get("queue", []))
                log.info("[EventLoader] Loaded event_state.json")
            except Exception as e:
                log.warning(f"[EventLoader] Lỗi đọc JSON: {e} — tạo mới.")
                self._state = {}
        else:
            self._state = {}

    def _migrate(self, lst: list) -> list[dict]:
        result = []
        for item in lst:
            if isinstance(item, str):
                cls = self._class_cache.get(item)
                result.append(_cls_to_entry(cls) if cls else {"name": item, **_ROLE_DEFAULTS})
            else:
                result.append(item)
        return result

    def _save_state(self):
        try:
            def _lines(lst):
                return ",\n    ".join(json.dumps(e, ensure_ascii=False) for e in lst)

            content = (
                "{\n"
                f'  "pool": [\n    {_lines(self._state.get("pool", []))}\n  ],\n'
                f'  "queue": [\n    {_lines(self._state.get("queue", []))}\n  ],\n'
                f'  "current": {json.dumps(self._state.get("current"), ensure_ascii=False)},\n'
                f'  "last_rotate": {self._state.get("last_rotate", 0)}\n'
                "}"
            )
            with open(EVENT_STATE_FILE, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            log.error(f"[EventLoader] Lỗi lưu JSON: {e}")

    def _merge_pool(self, discovered: list[dict]):
        current_names  = {_entry_name(e) for e in self._state.get("pool", [])}
        current_queue  = list(self._state.get("queue", []))
        discovered_names = {e["name"] for e in discovered}

        # Role mới → thêm vào queue
        new_entries = [e for e in discovered if e["name"] not in current_names]
        if new_entries:
            current_queue.extend(new_entries)

        # Role bị xóa file → loại khỏi queue
        removed = current_names - discovered_names
        if removed:
            current_queue = [e for e in current_queue if _entry_name(e) not in removed]
            if self._state.get("current") in removed:
                self._state["current"] = None

        # Cập nhật pool từ class mới nhất
        # Giữ weight đã chỉnh tay trong JSON nếu có
        updated_pool = []
        for e in discovered:
            old = next((x for x in self._state.get("pool", []) if _entry_name(x) == e["name"]), None)
            if old and "weight" in old:
                e["weight"] = old["weight"]
            updated_pool.append(e)

        if not self._state.get("current") and updated_pool:
            if not current_queue:
                current_queue = updated_pool[:]
                random.shuffle(current_queue)
            self._state["current"]     = _entry_name(current_queue.pop(0))
            self._state["last_rotate"] = time.time()

        self._state["pool"]  = updated_pool
        self._state["queue"] = current_queue

    def _rotate(self):
        pool = self._state.get("pool", [])
        if not pool:
            return
        queue = self._state.get("queue", [])
        if not queue:
            queue = pool[:]
            random.shuffle(queue)
            current = self._state.get("current")
            if len(queue) > 1 and _entry_name(queue[0]) == current:
                queue.append(queue.pop(0))
        next_entry = queue.pop(0)
        self._state["current"]     = _entry_name(next_entry)
        self._state["queue"]       = queue
        self._state["last_rotate"] = time.time()
        log.info(f"[EventLoader] Rotate → {self._state['current']}")

    async def _rotate_loop(self):
        try:
            wait = self.seconds_until_next_rotate()
            if wait > 0:
                await asyncio.sleep(wait)
            while True:
                self._rotate()
                self._save_state()
                await asyncio.sleep(ROTATE_INTERVAL)
        except asyncio.CancelledError:
            log.info("[EventLoader] Rotate loop dừng.")


# ── SINGLETON ────────────────────────────────────────────────────

_loader_instance: EventRolesLoader | None = None

def get_loader() -> EventRolesLoader:
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = EventRolesLoader()
    return _loader_instance
