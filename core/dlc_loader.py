# ══════════════════════════════════════════════════════════════════
# core/dlc_loader.py — Hệ thống DOELCES v2.0
# Quét, validate và load động các DLC từ thư mục /DLCs
#
# ───── CẤU TRÚC DLC v2.0 ─────────────────────────────────────────
#
#   DLCs/
#     TenMod/
#       mod.py            ← metadata (bắt buộc)
#       pack.png/jpg/webp ← icon (bắt buộc)
#       roles/
#         survivors/      ← phe mặc định
#         anomalies/      ← phe mặc định
#         unknown/        ← phe mặc định
#         <CustomTeam>/   ← phe tuỳ chỉnh (khai báo qua new_teams)
#       events/           ← folder event (khai báo qua new_events)
#       CUSTOM_META.py    ← distributor tuỳ chỉnh (ngang cấp roles/)
#
# ─── 14 FEATURES ────────────────────────────────────────────────
#   new_role       → Thêm vai trò mới
#   new_team       → Thêm phe mới
#   new_event      → Thêm event can thiệp game
#   new_item       → Thêm vật phẩm
#   new_ability    → Thêm kỹ năng
#   new_faction    → Thêm faction phụ
#   new_map        → Thêm bản đồ
#   new_mode       → Thêm chế độ chơi
#   custom_win     → Điều kiện thắng tuỳ chỉnh
#   custom_ui      → Giao diện tuỳ chỉnh
#   custom_sound   → Âm thanh tuỳ chỉnh
#   balance_patch  → Cân bằng game
#   seasonal       → Nội dung theo mùa
#   community      → Nội dung cộng đồng
# ══════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import os
import random
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DLC_ROOT       = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "DLCs"
VALID_ICONS    = {".jpg", ".jpeg", ".png", ".webp"}

VALID_FEATURES = {
    "new_role", "new_team", "new_event", "new_item",
    "new_ability", "new_faction", "new_map", "new_mode",
    "custom_win", "custom_ui", "custom_sound", "balance_patch",
    "seasonal", "community",
}

VALID_CURRENCIES     = {"gold", "gems", "nope"}
DEFAULT_ROLE_FOLDERS = {"survivors", "anomalies", "unknown"}

_event_registry: Dict[str, Dict[str, Any]] = {}


@dataclass
class DLCPrice:
    amount: int
    currency: str
    def is_free(self) -> bool: return self.currency == "nope"
    def display(self) -> str:
        if self.is_free(): return "🆓 Miễn phí"
        icon = "🪙" if self.currency == "gold" else "💎"
        return f"{icon} {self.amount:,} {self.currency.capitalize()}"


@dataclass
class DLCAddress:
    module_path: str
    function: str
    description: str = ""
    tag: str = ""  # "NewTeam" | "NewEvent" | ""


@dataclass
class NewTeamConfig:
    team_name: str
    folder_path: str
    distribution_meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NewEventConfig:
    event_name: str
    folder_path: str
    entry_module: str
    entry_function: str = "run_event"


@dataclass
class DLCMeta:
    name: str
    description: str
    price: DLCPrice
    features: List[str]
    roles: Dict[str, List[str]]
    new_team_roles: Dict[str, List[str]]
    addresses: List[DLCAddress]
    new_teams: List[NewTeamConfig]
    new_events: List[NewEventConfig]
    has_custom_meta: bool = False
    version: str = "1.0.0"
    author: str = "Unknown"
    requires: List[str] = field(default_factory=list)


@dataclass
class DLCPackage:
    folder_name: str
    folder_path: Path
    icon_path: Path
    meta: DLCMeta
    loaded: bool = False
    load_errors: List[str] = field(default_factory=list)
    registered_roles: List[str] = field(default_factory=list)
    custom_meta_module: Any = None


_loaded_dlcs: Dict[str, DLCPackage] = {}
_scan_errors: List[Tuple[str, str]] = []


# ── Validation ──────────────────────────────────────────────────────

def _find_icon(folder: Path) -> Optional[Path]:
    for ext in VALID_ICONS:
        c = folder / f"pack{ext}"
        if c.exists(): return c
    return None


def _validate_price(raw):
    if isinstance(raw, str) and raw.lower() == "nope":
        return DLCPrice(0, "nope"), None
    if isinstance(raw, dict):
        currency = str(raw.get("currency", "")).lower()
        amount   = raw.get("amount", 0)
        if currency not in VALID_CURRENCIES:
            return None, f"currency phải là một trong: {VALID_CURRENCIES}"
        if currency != "nope" and (not isinstance(amount, int) or amount < 0):
            return None, "amount phải là số nguyên dương"
        return DLCPrice(int(amount), currency), None
    return None, "price phải là 'nope' hoặc dict {currency, amount}"


def _validate_features(raw):
    if not isinstance(raw, list): return [], "features phải là list"
    if len(raw) > 14: return [], f"features tối đa 14, hiện có {len(raw)}"
    invalid = [f for f in raw if f not in VALID_FEATURES]
    if invalid: return [], f"feature không hợp lệ: {invalid}. Hợp lệ: {sorted(VALID_FEATURES)}"
    return [str(f) for f in raw], None


def _validate_roles(raw, folder: Path, extra_teams: List[str]):
    warnings = []
    default_result = {k: [] for k in DEFAULT_ROLE_FOLDERS}
    nt_result: Dict[str, List[str]] = {}
    if not isinstance(raw, dict):
        warnings.append("roles phải là dict")
        return default_result, nt_result, warnings
    all_valid = DEFAULT_ROLE_FOLDERS | set(extra_teams)
    roles_dir = folder / "roles"
    for faction, files in raw.items():
        if faction not in all_valid:
            warnings.append(f"faction '{faction}' không hợp lệ, hợp lệ: {sorted(all_valid)}")
            continue
        if not isinstance(files, list):
            warnings.append(f"roles.{faction} phải là list"); continue
        for fn in files:
            role_file = roles_dir / faction / f"{fn}.py"
            if not role_file.exists():
                warnings.append(f"File role không tồn tại: roles/{faction}/{fn}.py")
            else:
                if faction in DEFAULT_ROLE_FOLDERS: default_result[faction].append(str(fn))
                else: nt_result.setdefault(faction, []).append(str(fn))
    return default_result, nt_result, warnings


def _validate_addresses(raw):
    if raw is None: return [], None
    if not isinstance(raw, list): return [], "addresses phải là list"
    result = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict): return [], f"addresses[{i}] phải là dict"
        mp = item.get("module_path", ""); fn = item.get("function", "")
        if not mp or not fn: return [], f"addresses[{i}] thiếu module_path hoặc function"
        result.append(DLCAddress(module_path=str(mp), function=str(fn),
                                 description=str(item.get("description", "")),
                                 tag=str(item.get("tag", ""))))
    return result, None


def _validate_new_teams(raw, folder: Path, features: List[str]):
    if "new_team" not in features: return [], []
    if raw is None: return [], ["Feature 'new_team' được khai báo nhưng thiếu block 'new_teams'"]
    if not isinstance(raw, list): return [], ["new_teams phải là list"]
    configs, warnings = [], []
    for i, item in enumerate(raw):
        if not isinstance(item, dict): warnings.append(f"new_teams[{i}] phải là dict"); continue
        name = str(item.get("team_name", "")).strip()
        path = str(item.get("folder_path", "")).strip()
        if not name: warnings.append(f"new_teams[{i}] thiếu team_name"); continue
        if not path: warnings.append(f"new_teams[{i}] thiếu folder_path"); continue
        if not (folder / path).exists(): warnings.append(f"NewTeam '{name}': folder không tồn tại: {path}")
        configs.append(NewTeamConfig(team_name=name, folder_path=path,
                                     distribution_meta=item.get("distribution_meta", {})))
    return configs, warnings


def _validate_new_events(raw, folder: Path, features: List[str]):
    if "new_event" not in features: return [], []
    if raw is None: return [], ["Feature 'new_event' được khai báo nhưng thiếu block 'new_events'"]
    if not isinstance(raw, list): return [], ["new_events phải là list"]
    configs, warnings = [], []
    for i, item in enumerate(raw):
        if not isinstance(item, dict): warnings.append(f"new_events[{i}] phải là dict"); continue
        name      = str(item.get("event_name", "")).strip()
        entry_mod = str(item.get("entry_module", "")).strip()
        entry_fn  = str(item.get("entry_function", "run_event")).strip()
        path      = str(item.get("folder_path", "")).strip()
        if not name: warnings.append(f"new_events[{i}] thiếu event_name"); continue
        if not entry_mod: warnings.append(f"new_events[{i}] thiếu entry_module"); continue
        configs.append(NewEventConfig(event_name=name, folder_path=path,
                                      entry_module=entry_mod, entry_function=entry_fn))
    return configs, warnings


# ── Mod.py Loader ────────────────────────────────────────────────────

def _load_mod_py(folder: Path):
    errors = []
    mod_file = folder / "mod.py"
    if not mod_file.exists():
        return None, ["Thiếu file bắt buộc: mod.py"]
    spec = importlib.util.spec_from_file_location(f"dlc_{folder.name}_mod", str(mod_file))
    try:
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    except Exception as e:
        return None, [f"Lỗi khi import mod.py: {e}\n{traceback.format_exc(limit=3)}"]
    if not hasattr(module, "DLC"):
        return None, ["mod.py phải định nghĩa biến DLC = {...}"]
    raw = module.DLC
    if not isinstance(raw, dict):
        return None, ["DLC trong mod.py phải là dict"]

    name = str(raw.get("name", "")).strip()
    if not name: errors.append("Thiếu field: name")
    description = str(raw.get("description", "")).strip()
    if not description: errors.append("Thiếu field: description")

    price_raw = raw.get("price")
    if price_raw is None: errors.append("Thiếu field: price"); price = DLCPrice(0, "nope")
    else:
        price, price_err = _validate_price(price_raw)
        if price_err: errors.append(f"price không hợp lệ: {price_err}"); price = DLCPrice(0, "nope")

    features, feat_err = _validate_features(raw.get("features", []))
    if feat_err: errors.append(f"features không hợp lệ: {feat_err}")

    new_teams, nt_warns = _validate_new_teams(raw.get("new_teams"), folder, features)
    for w in nt_warns: print(f"  [DLC:{folder.name}] ⚠ {w}")
    extra_team_names = [t.team_name for t in new_teams]

    new_events, ne_warns = _validate_new_events(raw.get("new_events"), folder, features)
    for w in ne_warns: print(f"  [DLC:{folder.name}] ⚠ {w}")

    default_roles, nt_roles, role_warns = _validate_roles(raw.get("roles", {}), folder, extra_team_names)
    for w in role_warns: print(f"  [DLC:{folder.name}] ⚠ {w}")

    addresses, addr_err = _validate_addresses(raw.get("addresses"))
    if addr_err: errors.append(f"addresses không hợp lệ: {addr_err}"); addresses = []

    has_custom_meta = (folder / "CUSTOM_META.py").exists()

    if errors: return None, errors

    meta = DLCMeta(
        name=name, description=description, price=price, features=features,
        roles=default_roles, new_team_roles=nt_roles, addresses=addresses,
        new_teams=new_teams, new_events=new_events, has_custom_meta=has_custom_meta,
        version=str(raw.get("version", "1.0.0")), author=str(raw.get("author", "Unknown")),
        requires=list(raw.get("requires", [])),
    )
    return meta, []


# ── CUSTOM_META Loader ──────────────────────────────────────────────

def _load_custom_meta(pkg: DLCPackage):
    custom_file = pkg.folder_path / "CUSTOM_META.py"
    if not custom_file.exists(): return None
    module_name = f"dlc_{pkg.folder_name}_custom_meta"
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(custom_file))
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module; spec.loader.exec_module(module)
        print(f"  [DLC:{pkg.folder_name}] ✅ CUSTOM_META loaded")
        return module
    except Exception as e:
        print(f"  [DLC:{pkg.folder_name}] ❌ Lỗi load CUSTOM_META.py: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
# SCAN
# ══════════════════════════════════════════════════════════════════

def scan_dlcs(verbose: bool = True) -> Dict[str, DLCPackage]:
    global _scan_errors
    _scan_errors = []; packages: Dict[str, DLCPackage] = {}
    if not DLC_ROOT.exists():
        if verbose: print(f"[DLC] Tạo thư mục DLCs...")
        DLC_ROOT.mkdir(parents=True, exist_ok=True); return packages
    if verbose:
        print(f"\n{'═'*58}")
        print(f"  DOELCES v2.0 — Quét DLC từ: {DLC_ROOT}")
        print(f"{'═'*58}")
    subfolders = [f for f in DLC_ROOT.iterdir() if f.is_dir() and not f.name.startswith(".")]
    if not subfolders:
        if verbose: print("  [DLC] Không có DLC nào.")
        return packages
    for folder in sorted(subfolders):
        fn = folder.name
        if verbose: print(f"\n  📦 Đang kiểm tra: {fn}")
        icon = _find_icon(folder)
        if icon is None:
            err = "Thiếu file icon (pack.jpg / pack.png / pack.webp)"
            _scan_errors.append((fn, err))
            if verbose: print(f"    ❌ {err}"); continue
        meta, errors = _load_mod_py(folder)
        if errors:
            for e in errors: _scan_errors.append((fn, e))
            if verbose: [print(f"    ❌ {e}") for e in errors]; continue
        pkg = DLCPackage(folder_name=fn, folder_path=folder, icon_path=icon, meta=meta)
        packages[fn] = pkg
        if verbose:
            teams_info  = f" | Phe mới: {', '.join(t.team_name for t in meta.new_teams)}" if meta.new_teams else ""
            events_info = f" | Events: {', '.join(e.event_name for e in meta.new_events)}" if meta.new_events else ""
            custom_info = " | 📐 CUSTOM_META" if meta.has_custom_meta else ""
            print(f"    ✅ OK — {meta.name} v{meta.version} by {meta.author}")
            print(f"       Giá: {meta.price.display()} | Features: {', '.join(meta.features) or 'none'}{teams_info}{events_info}{custom_info}")
    if verbose:
        print(f"\n{'═'*58}")
        print(f"  Kết quả: {len(packages)} DLC hợp lệ | {len(_scan_errors)} lỗi")
        print(f"{'═'*58}\n")
    return packages


# ══════════════════════════════════════════════════════════════════
# ROLE LOADING
# ══════════════════════════════════════════════════════════════════

def load_dlc_roles(packages: Dict[str, DLCPackage], role_manager) -> None:
    for folder_name, pkg in packages.items():
        errors = []; roles_dir = pkg.folder_path / "roles"
        all_factions: Dict[str, List[str]] = {}
        for faction in DEFAULT_ROLE_FOLDERS:
            rl = pkg.meta.roles.get(faction, [])
            if rl: all_factions[faction] = rl
        for team_cfg in pkg.meta.new_teams:
            rl = pkg.meta.new_team_roles.get(team_cfg.team_name, [])
            if rl: all_factions[team_cfg.team_name] = rl
        for faction, role_list in all_factions.items():
            faction_dir = roles_dir / faction
            if not faction_dir.exists(): continue
            for role_name in role_list:
                role_file = faction_dir / f"{role_name}.py"
                if not role_file.exists():
                    errors.append(f"Role file không tồn tại: {role_file}"); continue
                module_name = f"dlc_{folder_name}_{faction}_{role_name}"
                try:
                    spec = importlib.util.spec_from_file_location(module_name, str(role_file))
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module; spec.loader.exec_module(module)
                    if hasattr(module, "register_role"):
                        module.register_role(role_manager)
                        pkg.registered_roles.append(role_name)
                        print(f"  [DLC:{folder_name}] ✅ Nạp role: {role_name} ({faction})")
                    else:
                        errors.append(f"{role_name}.py thiếu hàm register_role()")
                except Exception as e:
                    errors.append(f"Lỗi load role {role_name}: {e}")
                    print(f"  [DLC:{folder_name}] ❌ {errors[-1]}")
        if pkg.meta.has_custom_meta:
            pkg.custom_meta_module = _load_custom_meta(pkg)
        pkg.load_errors.extend(errors)
        if not errors: pkg.loaded = True
        _loaded_dlcs[folder_name] = pkg


# ══════════════════════════════════════════════════════════════════
# EVENT REGISTRY
# ══════════════════════════════════════════════════════════════════

def register_dlc_events(packages: Dict[str, DLCPackage]) -> None:
    global _event_registry; _event_registry = {}
    for folder_name, pkg in packages.items():
        if "new_event" not in pkg.meta.features or not pkg.meta.new_events: continue
        dlc_parent = str(pkg.folder_path.parent)
        if dlc_parent not in sys.path: sys.path.insert(0, dlc_parent)
        for event_cfg in pkg.meta.new_events:
            try:
                module = importlib.import_module(event_cfg.entry_module)
                _event_registry.setdefault(folder_name, {})[event_cfg.event_name] = {
                    "module": module, "entry_function": event_cfg.entry_function,
                    "config": event_cfg, "mod_name": pkg.meta.name,
                }
                print(f"  [DLC:{folder_name}] ✅ Event đăng ký: {event_cfg.event_name}")
            except Exception as e:
                print(f"  [DLC:{folder_name}] ❌ Lỗi load event '{event_cfg.event_name}': {e}")


def get_event_registry() -> Dict[str, Dict[str, Any]]:
    return dict(_event_registry)


def pick_random_event() -> Optional[Tuple[str, str, Any]]:
    all_events = [(m, e, d) for m, evs in _event_registry.items() for e, d in evs.items()]
    return random.choice(all_events) if all_events else None


# ══════════════════════════════════════════════════════════════════
# EVENT SCHEDULER — Kích hoạt event mỗi 2 ngày, 50% cơ hội
# ══════════════════════════════════════════════════════════════════

class EventScheduler:
    """
    Chạy nền, mỗi 2 ngày (48h) roll 50%:
    - Trúng → chọn ngẫu nhiên 1 event từ bất kỳ DLC nào
    - Gửi thông báo vào channel → chạy code event → báo hoàn thành
    - Game tiếp tục sau khi event xong
    """
    INTERVAL_SECONDS = 172_800  # 2 ngày

    def __init__(self, bot, channel_id: int, game_ref: Any = None):
        self.bot = bot; self.channel_id = channel_id; self.game_ref = game_ref
        self._task: Optional[asyncio.Task] = None

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            print("[EventScheduler] ✅ Bắt đầu lên lịch event mỗi 2 ngày")

    def stop(self):
        if self._task and not self._task.done():
            self._task.cancel(); print("[EventScheduler] ⏹ Đã dừng scheduler")

    async def _loop(self):
        while True:
            await asyncio.sleep(self.INTERVAL_SECONDS)
            await self._try_fire_event()

    async def _try_fire_event(self):
        if random.random() > 0.5:
            print("[EventScheduler] 🎲 Không kích hoạt event lần này (50% miss)"); return
        picked = pick_random_event()
        if picked is None: print("[EventScheduler] ⚠ Không có event nào"); return
        mod_key, ev_name, ev_data = picked
        await self._fire_event(mod_key, ev_name, ev_data)

    async def _fire_event(self, mod_key: str, ev_name: str, ev_data: dict):
        import disnake
        channel = self.bot.get_channel(self.channel_id)
        mod_display = ev_data.get("mod_name", mod_key)
        if channel:
            embed = disnake.Embed(
                title=f"⚡ KÍCH HOẠT SỰ KIỆN: {ev_name}",
                description=f'Sự kiện từ Mod **"{mod_display}"** vừa được kích hoạt!',
                color=0xFF4500,
            )
            embed.set_footer(text="Sự kiện sẽ ảnh hưởng đến game ngay bây giờ...")
            await channel.send(embed=embed)

        module  = ev_data["module"]
        fn_name = ev_data["entry_function"]
        fn      = getattr(module, fn_name, None)
        if fn is None:
            print(f"[EventScheduler] ❌ Không tìm thấy hàm '{fn_name}' trong '{ev_name}'"); return
        try:
            sig = inspect.signature(fn)
            result = fn(self.game_ref) if sig.parameters else fn()
            if asyncio.iscoroutine(result): await result
            print(f"[EventScheduler] ✅ Event '{ev_name}' ({mod_display}) hoàn thành")
            if channel: await channel.send(f"✅ Sự kiện **{ev_name}** đã hoàn thành. Game tiếp tục...")
        except Exception as e:
            print(f"[EventScheduler] ❌ Lỗi event '{ev_name}': {e}\n{traceback.format_exc(limit=3)}")
            if channel: await channel.send(f"❌ Lỗi khi thực thi event **{ev_name}**: {e}")


# ── Addresses ────────────────────────────────────────────────────────

def activate_dlc_addresses(packages: Dict[str, DLCPackage]) -> None:
    for folder_name, pkg in packages.items():
        for addr in pkg.meta.addresses:
            if addr.tag in ("NewTeam", "NewEvent"): continue
            try:
                dlc_parent = str(pkg.folder_path.parent)
                if dlc_parent not in sys.path: sys.path.insert(0, dlc_parent)
                module = importlib.import_module(addr.module_path)
                fn = getattr(module, addr.function, None)
                if fn is None: print(f"  [DLC:{folder_name}] ⚠ Không tìm thấy: {addr.function}"); continue
                fn()
                print(f"  [DLC:{folder_name}] ✅ Kích hoạt: {addr.module_path}.{addr.function}")
            except Exception as e:
                print(f"  [DLC:{folder_name}] ❌ Lỗi activate: {e}")


# ── Custom Meta Helpers ─────────────────────────────────────────────

def get_custom_meta_for_distributor(folder_name: str):
    pkg = _loaded_dlcs.get(folder_name)
    return pkg.custom_meta_module if pkg else None


def collect_all_custom_metas() -> Dict[str, Any]:
    return {fn: pkg.custom_meta_module for fn, pkg in _loaded_dlcs.items() if pkg.custom_meta_module}


# ══════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════

def initialize_dlcs(role_manager=None) -> Dict[str, DLCPackage]:
    packages = scan_dlcs(verbose=True)
    if role_manager is not None: load_dlc_roles(packages, role_manager)
    register_dlc_events(packages)
    activate_dlc_addresses(packages)
    return packages

def get_loaded_dlcs() -> Dict[str, DLCPackage]: return dict(_loaded_dlcs)
def get_dlc_by_folder(folder_name: str): return _loaded_dlcs.get(folder_name)
def get_dlc_by_display_name(display_name: str):
    for pkg in _loaded_dlcs.values():
        if pkg.meta.name.lower() == display_name.lower(): return pkg
    return None
def get_scan_errors(): return list(_scan_errors)

def get_all_dlcs_summary() -> List[dict]:
    result = []
    for folder_name, pkg in scan_dlcs(verbose=False).items():
        lp = _loaded_dlcs.get(folder_name)
        result.append({
            "folder_name": folder_name, "name": pkg.meta.name,
            "description": pkg.meta.description, "version": pkg.meta.version,
            "author": pkg.meta.author,
            "price": {"amount": pkg.meta.price.amount, "currency": pkg.meta.price.currency,
                      "display": pkg.meta.price.display(), "is_free": pkg.meta.price.is_free()},
            "features": pkg.meta.features, "roles": pkg.meta.roles,
            "new_teams": [{"team_name": t.team_name, "folder": t.folder_path} for t in pkg.meta.new_teams],
            "new_events": [{"event_name": e.event_name, "module": e.entry_module} for e in pkg.meta.new_events],
            "has_custom_meta": pkg.meta.has_custom_meta,
            "icon_ext": pkg.icon_path.suffix, "loaded": lp.loaded if lp else False,
        })
    return result
