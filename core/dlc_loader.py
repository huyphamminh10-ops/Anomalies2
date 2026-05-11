# ══════════════════════════════════════════════════════════════════
# core/dlc_loader.py — Hệ thống DOELCES v1.0
# Quét, validate và load động các DLC từ thư mục /DLCs
#
# Cấu trúc DLC folder hợp lệ:
#   DLCs/
#     TenMod/
#       mod.py          ← metadata + DLCMeta class (bắt buộc)
#       pack.png/jpg/webp ← icon (bắt buộc)
#       roles/
#         survivors/    ← tùy chọn
#         anomalies/    ← tùy chọn
#         unknown/      ← tùy chọn
#
# Chức năng:
#   scan_dlcs()         → quét và trả về dict {name: DLCPackage}
#   load_dlc_roles()    → nạp role từ DLC vào RoleManager
#   get_loaded_dlcs()   → danh sách DLC đã load
#   get_dlc_by_name()   → lấy DLC theo tên
# ══════════════════════════════════════════════════════════════════

from __future__ import annotations

import importlib.util
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ── Constants ──────────────────────────────────────────────────────

DLC_ROOT       = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "DLCs"
VALID_ICONS    = {".jpg", ".jpeg", ".png", ".webp"}
VALID_FEATURES = {
    "new_role", "new_team", "new_event", "new_item",
    "new_ability", "new_faction", "new_map", "new_mode",
    "custom_win", "custom_ui", "custom_sound", "balance_patch",
    "seasonal", "community",
}
VALID_CURRENCIES = {"gold", "gems", "nope"}
ROLE_FOLDERS     = {"survivors", "anomalies", "unknown"}

# ── Data classes ────────────────────────────────────────────────────

@dataclass
class DLCPrice:
    amount: int                 # 0 nếu nope
    currency: str               # "gold" | "gems" | "nope"

    def is_free(self) -> bool:
        return self.currency == "nope"

    def display(self) -> str:
        if self.is_free():
            return "🆓 Miễn phí"
        icon = "🪙" if self.currency == "gold" else "💎"
        return f"{icon} {self.amount:,} {self.currency.capitalize()}"


@dataclass
class DLCAddress:
    """Trỏ tới function/path mà app.py cần import để kích hoạt tính năng."""
    module_path: str            # VD: "DLCs.TenMod.features.custom_event"
    function: str               # VD: "register_event"
    description: str = ""


@dataclass
class DLCMeta:
    """Schema metadata của một DLC pack."""
    name: str
    description: str
    price: DLCPrice
    features: List[str]
    roles: Dict[str, List[str]]     # {"survivors": [...], "anomalies": [...], "unknown": [...]}
    addresses: List[DLCAddress]
    version: str = "1.0.0"
    author: str = "Unknown"
    requires: List[str] = field(default_factory=list)  # DLC dependencies


@dataclass
class DLCPackage:
    """Một DLC đã được scan và validate xong."""
    folder_name: str            # tên thư mục trong /DLCs
    folder_path: Path           # đường dẫn tuyệt đối
    icon_path: Path             # đường dẫn file icon
    meta: DLCMeta
    loaded: bool = False        # đã load vào system chưa
    load_errors: List[str] = field(default_factory=list)
    registered_roles: List[str] = field(default_factory=list)


# ── Internal state ─────────────────────────────────────────────────

_loaded_dlcs: Dict[str, DLCPackage] = {}   # key = folder_name
_scan_errors: List[Tuple[str, str]] = []   # [(folder, error_msg)]


# ══════════════════════════════════════════════════════════════════
# VALIDATION HELPERS
# ══════════════════════════════════════════════════════════════════

def _find_icon(folder: Path) -> Optional[Path]:
    """Tìm file icon pack.* trong folder."""
    for ext in VALID_ICONS:
        candidate = folder / f"pack{ext}"
        if candidate.exists():
            return candidate
    return None


def _validate_price(raw: Any) -> Tuple[Optional[DLCPrice], Optional[str]]:
    """Validate và parse price object."""
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


def _validate_features(raw: Any) -> Tuple[List[str], Optional[str]]:
    """Validate features list."""
    if not isinstance(raw, list):
        return [], "features phải là list"
    if len(raw) > 14:
        return [], f"features tối đa 14 loại, hiện có {len(raw)}"
    invalid = [f for f in raw if f not in VALID_FEATURES]
    if invalid:
        return [], f"feature không hợp lệ: {invalid}. Hợp lệ: {sorted(VALID_FEATURES)}"
    return [str(f) for f in raw], None


def _validate_roles(raw: Any, folder: Path) -> Tuple[Dict[str, List[str]], List[str]]:
    """Validate roles config và kiểm tra file tồn tại."""
    warnings = []
    result: Dict[str, List[str]] = {k: [] for k in ROLE_FOLDERS}
    if not isinstance(raw, dict):
        warnings.append("roles phải là dict {survivors/anomalies/unknown: [...]}")
        return result, warnings
    roles_dir = folder / "roles"
    for faction, files in raw.items():
        if faction not in ROLE_FOLDERS:
            warnings.append(f"faction '{faction}' không hợp lệ, bỏ qua")
            continue
        if not isinstance(files, list):
            warnings.append(f"roles.{faction} phải là list")
            continue
        for fn in files:
            role_file = roles_dir / faction / f"{fn}.py"
            if not role_file.exists():
                warnings.append(f"File role không tồn tại: {role_file.relative_to(folder)}")
            else:
                result[faction].append(str(fn))
    return result, warnings


def _validate_addresses(raw: Any) -> Tuple[List[DLCAddress], Optional[str]]:
    """Validate addresses list."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return [], "addresses phải là list"
    result = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return [], f"addresses[{i}] phải là dict"
        mp = item.get("module_path", "")
        fn = item.get("function", "")
        if not mp or not fn:
            return [], f"addresses[{i}] thiếu module_path hoặc function"
        result.append(DLCAddress(
            module_path=str(mp),
            function=str(fn),
            description=str(item.get("description", "")),
        ))
    return result, None


# ══════════════════════════════════════════════════════════════════
# MOD.PY LOADER
# ══════════════════════════════════════════════════════════════════

def _load_mod_py(folder: Path) -> Tuple[Optional[DLCMeta], List[str]]:
    """
    Import mod.py từ folder và đọc DLCMeta.
    Trả về (meta, errors). Nếu errors rỗng thì OK.
    """
    errors: List[str] = []
    mod_file = folder / "mod.py"

    if not mod_file.exists():
        errors.append(f"Thiếu file bắt buộc: mod.py")
        return None, errors

    # Load module động
    spec = importlib.util.spec_from_file_location(
        f"dlc_{folder.name}_mod", str(mod_file)
    )
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        errors.append(f"Lỗi khi import mod.py: {e}\n{traceback.format_exc(limit=3)}")
        return None, errors

    # Kiểm tra class DLCMeta trong module
    if not hasattr(module, "DLC"):
        errors.append("mod.py phải định nghĩa biến DLC = {...} hoặc class DLC")
        return None, errors

    raw = module.DLC
    if not isinstance(raw, dict):
        errors.append("DLC trong mod.py phải là dict")
        return None, errors

    # Validate từng field
    name = str(raw.get("name", "")).strip()
    if not name:
        errors.append("Thiếu field: name")

    description = str(raw.get("description", "")).strip()
    if not description:
        errors.append("Thiếu field: description")

    price_raw = raw.get("price")
    if price_raw is None:
        errors.append("Thiếu field: price")
        price = DLCPrice(0, "nope")
    else:
        price, price_err = _validate_price(price_raw)
        if price_err:
            errors.append(f"price không hợp lệ: {price_err}")
            price = DLCPrice(0, "nope")

    features, feat_err = _validate_features(raw.get("features", []))
    if feat_err:
        errors.append(f"features không hợp lệ: {feat_err}")

    roles, role_warns = _validate_roles(raw.get("roles", {}), folder)
    for w in role_warns:
        print(f"  [DLC:{folder.name}] ⚠ {w}")

    addresses, addr_err = _validate_addresses(raw.get("addresses"))
    if addr_err:
        errors.append(f"addresses không hợp lệ: {addr_err}")
        addresses = []

    if errors:
        return None, errors

    meta = DLCMeta(
        name=name,
        description=description,
        price=price,
        features=features,
        roles=roles,
        addresses=addresses,
        version=str(raw.get("version", "1.0.0")),
        author=str(raw.get("author", "Unknown")),
        requires=list(raw.get("requires", [])),
    )
    return meta, []


# ══════════════════════════════════════════════════════════════════
# SCAN
# ══════════════════════════════════════════════════════════════════

def scan_dlcs(verbose: bool = True) -> Dict[str, DLCPackage]:
    """
    Quét thư mục /DLCs, validate từng folder và trả về dict packages.
    Tự động in lỗi ra console nếu verbose=True.
    """
    global _scan_errors
    _scan_errors = []
    packages: Dict[str, DLCPackage] = {}

    if not DLC_ROOT.exists():
        if verbose:
            print(f"[DLC] Thư mục DLCs không tồn tại: {DLC_ROOT}")
            print(f"[DLC] Tạo thư mục mặc định...")
        DLC_ROOT.mkdir(parents=True, exist_ok=True)
        return packages

    if verbose:
        print(f"\n{'═'*55}")
        print(f"  DOELCES v1.0 — Quét DLC từ: {DLC_ROOT}")
        print(f"{'═'*55}")

    subfolders = [f for f in DLC_ROOT.iterdir() if f.is_dir() and not f.name.startswith(".")]
    if not subfolders:
        if verbose:
            print("  [DLC] Không có DLC nào được tìm thấy.")
        return packages

    for folder in sorted(subfolders):
        folder_name = folder.name
        if verbose:
            print(f"\n  📦 Đang kiểm tra: {folder_name}")

        # 1. Tìm icon
        icon = _find_icon(folder)
        if icon is None:
            err = f"Thiếu file icon (pack.jpg / pack.png / pack.webp)"
            _scan_errors.append((folder_name, err))
            if verbose:
                print(f"    ❌ {err}")
            continue

        # 2. Load mod.py
        meta, errors = _load_mod_py(folder)
        if errors:
            for e in errors:
                _scan_errors.append((folder_name, e))
                if verbose:
                    print(f"    ❌ {e}")
            continue

        # 3. Tạo package
        pkg = DLCPackage(
            folder_name=folder_name,
            folder_path=folder,
            icon_path=icon,
            meta=meta,
        )
        packages[folder_name] = pkg
        if verbose:
            print(f"    ✅ OK — {meta.name} v{meta.version} by {meta.author}")
            print(f"       Giá: {meta.price.display()} | Features: {', '.join(meta.features) or 'none'}")

    if verbose:
        ok  = len(packages)
        err = len(_scan_errors)
        print(f"\n{'═'*55}")
        print(f"  Kết quả: {ok} DLC hợp lệ | {err} lỗi")
        print(f"{'═'*55}\n")

    return packages


# ══════════════════════════════════════════════════════════════════
# ROLE LOADING
# ══════════════════════════════════════════════════════════════════

def load_dlc_roles(packages: Dict[str, DLCPackage], role_manager) -> None:
    """
    Nạp role từ tất cả DLC packages vào RoleManager.
    Chỉ load role từ các folder: survivors, anomalies, unknown.
    """
    for folder_name, pkg in packages.items():
        errors: List[str] = []
        roles_dir = pkg.folder_path / "roles"

        for faction in ROLE_FOLDERS:
            faction_dir = roles_dir / faction
            if not faction_dir.exists():
                continue

            for role_name in pkg.meta.roles.get(faction, []):
                role_file = faction_dir / f"{role_name}.py"
                if not role_file.exists():
                    errors.append(f"Role file không tồn tại: {role_file}")
                    continue

                module_name = f"dlc_{folder_name}_{faction}_{role_name}"
                try:
                    spec   = importlib.util.spec_from_file_location(module_name, str(role_file))
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

                    if hasattr(module, "register_role"):
                        module.register_role(role_manager)
                        pkg.registered_roles.append(role_name)
                        print(f"  [DLC:{folder_name}] ✅ Nạp role: {role_name} ({faction})")
                    else:
                        errors.append(f"{role_name}.py thiếu hàm register_role()")
                except Exception as e:
                    errors.append(f"Lỗi load role {role_name}: {e}")
                    print(f"  [DLC:{folder_name}] ❌ {errors[-1]}")

        if errors:
            pkg.load_errors.extend(errors)
        else:
            pkg.loaded = True

        _loaded_dlcs[folder_name] = pkg


# ══════════════════════════════════════════════════════════════════
# ADDRESS ACTIVATION
# ══════════════════════════════════════════════════════════════════

def activate_dlc_addresses(packages: Dict[str, DLCPackage]) -> None:
    """
    Import và gọi các hàm được chỉ định trong addresses.
    Dùng để kích hoạt event, UI, hoặc tính năng custom.
    """
    for folder_name, pkg in packages.items():
        for addr in pkg.meta.addresses:
            try:
                # Đảm bảo thư mục DLC trong sys.path
                dlc_parent = str(pkg.folder_path.parent)
                if dlc_parent not in sys.path:
                    sys.path.insert(0, dlc_parent)

                module = importlib.import_module(addr.module_path)
                fn = getattr(module, addr.function, None)
                if fn is None:
                    print(f"  [DLC:{folder_name}] ⚠ Không tìm thấy hàm: {addr.function} trong {addr.module_path}")
                    continue
                fn()
                print(f"  [DLC:{folder_name}] ✅ Kích hoạt: {addr.module_path}.{addr.function}")
            except Exception as e:
                print(f"  [DLC:{folder_name}] ❌ Lỗi activate address: {e}")


# ══════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════

def initialize_dlcs(role_manager=None) -> Dict[str, DLCPackage]:
    """
    Hàm chính — gọi lúc startup của bot:
      1. Quét thư mục DLCs
      2. Load role vào RoleManager (nếu truyền vào)
      3. Kích hoạt addresses
    Trả về dict {folder_name: DLCPackage}.
    """
    packages = scan_dlcs(verbose=True)
    if role_manager is not None:
        load_dlc_roles(packages, role_manager)
    activate_dlc_addresses(packages)
    return packages


def get_loaded_dlcs() -> Dict[str, DLCPackage]:
    return dict(_loaded_dlcs)


def get_dlc_by_folder(folder_name: str) -> Optional[DLCPackage]:
    return _loaded_dlcs.get(folder_name)


def get_dlc_by_display_name(display_name: str) -> Optional[DLCPackage]:
    for pkg in _loaded_dlcs.values():
        if pkg.meta.name.lower() == display_name.lower():
            return pkg
    return None


def get_scan_errors() -> List[Tuple[str, str]]:
    return list(_scan_errors)


def get_all_dlcs_summary() -> List[dict]:
    """Trả về danh sách DLC dạng dict để dùng trong API / Dashboard."""
    result = []
    # Scan lại để lấy cả DLC chưa load
    packages = scan_dlcs(verbose=False)
    for folder_name, pkg in packages.items():
        loaded_pkg = _loaded_dlcs.get(folder_name)
        result.append({
            "folder_name":   folder_name,
            "name":          pkg.meta.name,
            "description":   pkg.meta.description,
            "version":       pkg.meta.version,
            "author":        pkg.meta.author,
            "price":         {
                "amount":   pkg.meta.price.amount,
                "currency": pkg.meta.price.currency,
                "display":  pkg.meta.price.display(),
                "is_free":  pkg.meta.price.is_free(),
            },
            "features":      pkg.meta.features,
            "roles":         pkg.meta.roles,
            "icon_ext":      pkg.icon_path.suffix,
            "loaded":        loaded_pkg.loaded if loaded_pkg else False,
        })
    return result
