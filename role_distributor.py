import random
import math

# ══════════════════════════════════════════════════════════════════
# BẢNG META ROLE — Định nghĩa trọng số và ràng buộc từng role
# ══════════════════════════════════════════════════════════════════

SURVIVORS_META = {
    "Dân Thường":         {"weight": 10, "min_players": 5,  "max_count": 9, "core": True},
    "Thám Tử":     {"weight": 6,  "min_players": 6,  "max_count": 2,  "core": False},
    "Cai Ngục":           {"weight": 5,  "min_players": 10, "max_count": 1,  "core": False},
    "Thị Trưởng":            {"weight": 4,  "min_players": 10, "max_count": 1,  "core": False},
    "Phụ Tá Thị Trưởng":     {"weight": 3,  "min_players": 12, "max_count": 1,  "core": False, "requires": "Thị Trưởng"},
    "Nhà Ngoại Cảm":           {"weight": 4,  "min_players": 5,  "max_count": 1,  "core": False},
    "Người Thử Nghiệm":       {"weight": 3,  "min_players": 7,  "max_count": 2,  "core": False, "event": True},
    "Người Tiên Tri":          {"weight": 4,  "min_players": 6,  "max_count": 1,  "core": False},
    "Kẻ Báo Oán":   {"weight": 3,  "min_players": 12, "max_count": 1,  "core": False},
    "Thám Trưởng":          {"weight": 5,  "min_players": 5,  "max_count": 1,  "core": False},
    "Điệp Viên":              {"weight": 4,  "min_players": 7, "max_count": 1,  "core": False},
    "Kiến Trúc Sư":    {"weight": 3,  "min_players": 12, "max_count": 1,  "core": False},
    "Nhà Lưu Trữ":    {"weight": 3,  "min_players": 7, "max_count": 1,  "core": False},
    "Kẻ Báo Thù":      {"weight": 2,  "min_players": 15, "max_count": 1,  "core": False},
    "Người Giám Sát":     {"weight": 3,  "min_players": 12, "max_count": 1,  "core": False},
    "Kẻ Ngủ Mê":      {"weight": 2,  "min_players": 7, "max_count": 1,  "core": False},
    "Thợ Đặt Bẫy":          {"weight": 4,  "min_players": 6,  "max_count": 1,  "core": False},
    "Kẻ Trừng Phạt":        {"weight": 4,  "min_players": 5,  "max_count": 2,  "core": False},
    "Nhà Dược Học Điên":    {"weight": 3,  "min_players": 16, "max_count": 1,  "core": False},
}

ANOMALIES_META = {
    "Dị Thể":              {"weight": 10, "min_players": 5,  "max_count": 7,  "core": True},
    "Mù Quáng":                {"weight": 3,  "min_players": 10, "max_count": 1,  "core": False, "event": True},
    "Lãnh Chúa":             {"weight": 5,  "min_players": 10, "max_count": 1,  "core": False},
    "Lao Công":              {"weight": 4,  "min_players": 10, "max_count": 1,  "core": False},
    "Kẻ Rình Rập":   {"weight": 4,  "min_players": 6,  "max_count": 1,  "core": False},
    "Sứ Giả Tận Thế":        {"weight": 3,  "min_players": 15, "max_count": 1,  "core": False},
    "Kẻ Điều Khiển":        {"weight": 3,  "min_players": 12, "max_count": 1,  "core": False},
    "Kiến Trúc Sư Bóng Tối":   {"weight": 3,  "min_players": 12, "max_count": 1,  "core": False},
    "Kẻ Mô Phỏng Sinh Học":        {"weight": 3,  "min_players": 7, "max_count": 1,  "core": False},
    "Ký Sinh Thần Kinh":   {"weight": 3,  "min_players": 12, "max_count": 1,  "core": False},
    "Sâu Lỗi":      {"weight": 3,  "min_players": 7, "max_count": 1,  "core": False},
    "Dị Thể Hành Quyết": {"weight": 2, "min_players": 15, "max_count": 1, "core": False},
    "Tín Hiệu Giả":     {"weight": 2,  "min_players": 15, "max_count": 1,  "core": False},
    "Máy Hủy Tài Liệu":   {"weight": 2,  "min_players": 15, "max_count": 1,  "core": False},
    "Nguồn Tĩnh Điện":   {"weight": 1,  "min_players": 20, "max_count": 1,  "core": False},
    "Kẻ Đánh Cắp Lời Thì Thầm":    {"weight": 1,  "min_players": 20, "max_count": 1,  "core": False},
}


def apply_blind_to_options(game, options: list, role_faction: str) -> list:
    """
    Helper dùng trong send_ui của các role Survivors / Unknown.
    Nếu blind_active = True, thay toàn bộ SelectOption bằng '👁 : ĐÃ BỊ MÙ'.

    Cách dùng trong send_ui:
        from role_distributor import apply_blind_to_options
        options = [SelectOption(...) for p in targets]
        options = apply_blind_to_options(game, options, self.team)

    Anomalies không bị ảnh hưởng.
    """
    if role_faction == "Anomalies":
        return options
    if not game.night_effects.get("blind_active", False):
        return options

    # Import ở đây để tránh circular import
    try:
        from roles.event.blind import make_blind_options
        return make_blind_options(len(options))
    except Exception:
        return options

UNKNOWN_META = {
    "KẺ GIẾT NGƯỜI HÀNG LOẠT":      {"weight": 6,  "min_players": 7,  "max_count": 1,  "core": True},
    "A.I THA HÓA":   {"weight": 4,  "min_players": 15, "max_count": 1,  "core": False},
    "ĐỒNG HỒ TẬN THẾ": {"weight": 3,  "min_players": 15, "max_count": 1,  "core": False},
    "Kẻ Dệt Mộng":    {"weight": 3,  "min_players": 15, "max_count": 1,  "core": False},
    "Con Tàu Ma":     {"weight": 2,  "min_players": 20, "max_count": 1,  "core": False},
    # "Sâu Lỗi" ĐÃ BỊ XÓA — class có team="Anomalies", chỉ nằm trong ANOMALIES_META
    "Kẻ Dệt Thời Gian":    {"weight": 3,  "min_players": 15, "max_count": 1,  "core": False},
    "Kẻ Tâm Thần":     {"weight": 2,  "min_players": 20, "max_count": 1,  "core": False},
}

# ── Event Role META — đọc động từ event_state.json ───────────────
def get_event_meta() -> dict:
    """
    Đọc pool từ event_state.json và trả về dict cùng cấu trúc
    với SURVIVORS_META / ANOMALIES_META / UNKNOWN_META.
    Trả về {} nếu file chưa tồn tại hoặc lỗi.
    """
    import os, json as _json
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "event_state.json")
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = _json.load(f)
        result = {}
        for entry in data.get("pool", []):
            name = entry.get("name")
            if name:
                result[name] = {
                    "weight":      entry.get("weight",      3),
                    "min_players": entry.get("min_players", 5),
                    "max_count":   entry.get("max_count",   1),
                    "core":        False,
                    "event":       True,
                    "faction":     entry.get("faction",     "Survivors"),
                }
        return result
    except Exception:
        return {}

# Alias để role_preview.py import như cũ
EVENT_META = get_event_meta()

# ══════════════════════════════════════════════════════════════════
# CORE ENGINE
# ══════════════════════════════════════════════════════════════════

class RoleDistributor:
    def __init__(self, role_classes: list):
        self._class_map: dict[str, type] = {
            cls.name: cls for cls in role_classes
        }

    def distribute(self, members: list) -> dict:
        total = len(members)
        if total < 5:
            raise ValueError(f"Cần ít nhất 5 người chơi, hiện có {total}.")

        # ── Tính số slot mỗi phe theo luật mới ───────────────────
        # Unknown Entities chỉ xuất hiện khi lobby >= 7 người
        if total == 5:
            n_survivors, n_anomalies, n_unknowns = 4, 1, 0
        elif total == 6:
            n_survivors, n_anomalies, n_unknowns = 4, 2, 0
        elif total == 7:
            n_survivors, n_anomalies, n_unknowns = 4, 2, 1
        elif total == 8:
            n_survivors, n_anomalies, n_unknowns = 4, 2, 2
        elif total == 9:
            n_survivors, n_anomalies, n_unknowns = 5, 3, 1
        elif 10 <= total <= 12:
            n_survivors = round(total * 0.50)
            n_anomalies = round(total * 0.25)
            n_unknowns = total - n_survivors - n_anomalies
        else: # total >= 13
            n_survivors = round(total * 0.55)
            n_anomalies = round(total * 0.30)
            n_unknowns = total - n_survivors - n_anomalies

        # Đảm bảo Anomalies >= 1
        if n_anomalies < 1:
            n_anomalies = 1
            n_survivors -= 1

        print(
            f"[Distributor] {total} người chơi → "
            f"Survivors={n_survivors} | Anomalies={n_anomalies} | Unknown={n_unknowns}"
        )

        # ── Build pool từng phe ───────────────────────────────────
        s_pool = self._build_pool("Survivors", SURVIVORS_META, n_survivors, total)
        a_pool = self._build_pool("Anomalies", ANOMALIES_META, n_anomalies, total)
        u_pool = self._build_pool("Unknown",   UNKNOWN_META,   n_unknowns,  total)

        # ── Kiểm tra requires (Mayor's Aide cần Mayor) ───────────
        s_pool = self._apply_requires(s_pool)

        full_pool = s_pool + a_pool + u_pool
        full_pool = self._fix_size(full_pool, total, n_survivors, n_anomalies, n_unknowns)

        # ── Inject event role (nếu có) ────────────────────────────
        try:
            from event_roles_loader import get_loader as _get_event_loader
            event_loader = _get_event_loader()
            full_pool = event_loader.inject_into_pool(full_pool, total)
            # Đăng ký event role class vào class_map nếu chưa có
            ecls = event_loader.get_current_role_class()
            if ecls and ecls.name not in self._class_map:
                self._class_map[ecls.name] = ecls
        except Exception as _e:
            print(f"[Distributor] ⚠ Event inject lỗi: {_e}")

        random.shuffle(full_pool)

        # ── Gán role cho member ───────────────────────────────────
        result = {}
        for member, role_name in zip(members, full_pool):
            cls = self._class_map.get(role_name)
            if cls is None:
                cls = self._class_map.get("Dân Thường") or self._class_map.get("Dị Thể")
            if cls:
                result[member.id] = cls(member)
            else:
                print(f"[Distributor] ⚠ Không tìm thấy class cho role '{role_name}'!")

        self._log_summary(result)
        return result

    def _build_pool(self, team: str, meta: dict, count: int, total_players: int) -> list[str]:
        if count <= 0:
            return []

        eligible = {
            name: m for name, m in meta.items()
            if total_players >= m["min_players"]
            and name in self._class_map
        }

        # ── Override max_count cho role event theo lobby size ────────
        # Đọc từ event_state.json thông qua get_event_meta()
        event_meta = get_event_meta()
        for role_name, emeta in event_meta.items():
            if role_name in eligible:
                eligible[role_name] = {**eligible[role_name], "max_count": emeta["max_count"]}
        
        if not eligible:
            fallback = "Dân Thường" if team == "Survivors" else ("Dị Thể" if team == "Anomalies" else "KẺ GIẾT NGƯỜI HÀNG LOẠT")
            return [fallback] * count

        pool = []
        used = {}
        
        power_roles = {n: m for n, m in eligible.items() if not m.get("core")}
        core_roles = [n for n, m in eligible.items() if m.get("core")]
        
        # ── XÁC ĐỊNH SỐ LƯỢNG POWER ROLE ──
        base_max_power = max(1, total_players // 5)
        target_power = 0
        
        if team == "Survivors":
            max_civ = math.floor(count * 0.5) if total_players < 10 else math.floor(count * 0.4)
            min_power = count - max_civ
            if total_players >= 6:
                min_power = max(1, min_power)
            target_power = min_power
            
        elif team == "Anomalies":
            limit = int(count * 0.5)
            target_power = min(base_max_power, limit)
            if count >= 2:
                target_power = max(1, target_power)
                
        else: # Unknown
            limit = math.ceil(count * 0.3)
            target_power = min(base_max_power, limit)
            if total_players >= 10:
                target_power = max(1, target_power)
                
        target_power = min(target_power, count)

        # ── ĐỔ POWER ROLE VÀO POOL ──
        power_candidates = list(power_roles.keys())

        # Nếu không có power role nào eligible → không cố fill, để core lấp đầy
        if not power_candidates:
            target_power = 0
        
        while len(pool) < target_power and power_candidates:
            weights = [power_roles[n]["weight"] for n in power_candidates]
            chosen = random.choices(power_candidates, weights=weights, k=1)[0]
            
            max_c = power_roles[chosen]["max_count"]
            cur_count = used.get(chosen, 0)
            
            if cur_count < max_c:
                pool.append(chosen)
                used[chosen] = cur_count + 1
                if used[chosen] >= max_c:
                    power_candidates.remove(chosen)
            else:
                power_candidates.remove(chosen)
                
        # ── ĐỔ CORE ROLE VÀO POOL (LẤP ĐẦY SLOT) ──
        slots_left = count - len(pool)
        
        if team == "Survivors" and slots_left > 0:
            max_civ = math.floor(count * 0.5) if total_players < 10 else math.floor(count * 0.4)
            civ_to_add = min(slots_left, max_civ)
            for _ in range(civ_to_add):
                pool.append("Dân Thường")
                used["Dân Thường"] = used.get("Dân Thường", 0) + 1
                slots_left -= 1
                
            # Nếu vẫn còn thiếu slot (do max_civ chặn), buộc thêm power role
            # Rebuild power_candidates từ đầu để không bị giới hạn bởi max_count cũ
            remaining_power = [
                n for n, m in power_roles.items()
                if used.get(n, 0) < m["max_count"]
            ]
            while slots_left > 0 and remaining_power:
                weights = [power_roles[n]["weight"] for n in remaining_power]
                chosen = random.choices(remaining_power, weights=weights, k=1)[0]
                max_c = power_roles[chosen]["max_count"]
                if used.get(chosen, 0) < max_c:
                    pool.append(chosen)
                    used[chosen] = used.get(chosen, 0) + 1
                    slots_left -= 1
                    if used[chosen] >= max_c:
                        remaining_power.remove(chosen)
                else:
                    remaining_power.remove(chosen)

            while slots_left > 0:
                pool.append("Dân Thường")
                slots_left -= 1
                
        elif team == "Unknown" and slots_left > 0:
            available_cores = list(core_roles)
            while slots_left > 0 and available_cores:
                chosen = random.choice(available_cores)
                max_c = eligible[chosen]["max_count"]
                if used.get(chosen, 0) < max_c:
                    pool.append(chosen)
                    used[chosen] = used.get(chosen, 0) + 1
                    slots_left -= 1
                    if used[chosen] >= max_c:
                        available_cores.remove(chosen)
                else:
                    available_cores.remove(chosen)
                    
            while slots_left > 0 and power_candidates:
                chosen = random.choice(power_candidates)
                pool.append(chosen)
                power_candidates.remove(chosen)
                slots_left -= 1
                
            while slots_left > 0:
                pool.append("KẺ GIẾT NGƯỜI HÀNG LOẠT")
                slots_left -= 1
                
        elif team == "Anomalies" and slots_left > 0:
            available_cores = list(core_roles)
            while slots_left > 0 and available_cores:
                chosen = random.choice(available_cores)
                max_c = eligible[chosen]["max_count"]
                if used.get(chosen, 0) < max_c:
                    pool.append(chosen)
                    used[chosen] = used.get(chosen, 0) + 1
                    slots_left -= 1
                    if used[chosen] >= max_c:
                        available_cores.remove(chosen)
                else:
                    available_cores.remove(chosen)
                    
            while slots_left > 0 and power_candidates:
                chosen = random.choice(power_candidates)
                pool.append(chosen)
                power_candidates.remove(chosen)
                slots_left -= 1
                
            while slots_left > 0:
                pool.append("Dị Thể")
                slots_left -= 1
                
        return pool

    def _apply_requires(self, pool: list[str]) -> list[str]:
        for name, meta in SURVIVORS_META.items():
            req = meta.get("requires")
            if req and name in pool and req not in pool:
                pool.remove(name)
                pool.append("Dân Thường")
                print(f"[Distributor] '{name}' bị loại vì thiếu '{req}', thay bằng Civilian.")
        return pool

    def _fix_size(self, pool: list[str], total: int, n_s: int, n_a: int, n_u: int) -> list[str]:
        diff = total - len(pool)
        if diff > 0:
            pool += ["Dân Thường"] * diff
            print(f"[Distributor] Thiếu {diff} slot, thêm Civilian.")
        elif diff < 0:
            # BUG FIX: Không cắt đuôi vì sẽ xóa mất Unknown roles.
            # Ưu tiên cắt Civilian thừa trước, sau đó mới cắt Anomaly core.
            to_cut = -diff
            for core_name in ("Dân Thường", "Dị Thể", "KẺ GIẾT NGƯỜI HÀNG LOẠT"):
                while to_cut > 0 and core_name in pool:
                    idx = len(pool) - 1 - pool[::-1].index(core_name)
                    pool.pop(idx)
                    to_cut -= 1
            # Nếu vẫn còn thừa, mới cắt từ đuôi (last resort)
            if to_cut > 0:
                pool = pool[:total]
            print(f"[Distributor] Thừa {-diff} slot, đã cắt bớt an toàn.")
        return pool

    def _log_summary(self, result: dict):
        from collections import Counter
        counts = Counter(type(r).__name__ for r in result.values())
        by_team = {}
        for role in result.values():
            t = getattr(role, "team", "?")
            by_team.setdefault(t, []).append(role.name)

        print("[Distributor] ══ Kết quả phân chia ══")
        for team, roles in by_team.items():
            summary = ", ".join(sorted(set(roles)))
            print(f"  {team}: {len(roles)} người → {summary}")


# ══════════════════════════════════════════════════════════════════
# COMPATIBILITY WRAPPER
# ══════════════════════════════════════════════════════════════════

def distribute_roles(members: list, role_classes: list) -> dict:
    distributor = RoleDistributor(role_classes)
    return distributor.distribute(members)

# ══════════════════════════════════════════════════════════════════
# BALANCE VALIDATOR
# ══════════════════════════════════════════════════════════════════

def validate_balance(roles: dict) -> tuple[bool, str]:
    from collections import Counter
    team_count: Counter = Counter()
    for role in roles.values():
        team_count[getattr(role, "team", "Unknown")] += 1

    total     = len(roles)
    survivors = team_count.get("Survivors", 0)
    anomalies = team_count.get("Anomalies", 0)
    unknowns  = sum(
        v for k, v in team_count.items()
        if k not in ("Survivors", "Anomalies")
    )

    issues = []

    if survivors <= anomalies:
        issues.append(f"Survivors ({survivors}) ≤ Anomalies ({anomalies})")

    if total > 0 and anomalies / total > 0.40:
        issues.append(f"Anomalies chiếm {anomalies/total:.0%} > 40%")

    # Unknown Entities chỉ bắt buộc khi >= 7 người
    if total >= 7 and unknowns == 0:
        issues.append("Không có Unknown Entity nào (cần >= 7 người)")

    if issues:
        return False, " | ".join(issues)
    return True, "✅ Cân bằng ổn định"


