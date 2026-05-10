"""
debug.py — Theo dõi code thực thi theo thời gian thực.

Gõ trực tiếp vào console khi bot đang chạy:
    DEBUG_MODE On    →  Bắt đầu in từng dòng code
    DEBUG_MODE Off   →  Dừng lại
"""

import sys
import time
import linecache
import threading
from datetime import datetime

# ─────────────────────────────────────────────
# ANSI COLORS
# ─────────────────────────────────────────────
C_TIME = "\033[90m"
C_FILE = "\033[36m"
C_LNUM = "\033[33m"
C_FUNC = "\033[35m"
C_CODE = "\033[97m"
C_CALL = "\033[92m"
C_RET  = "\033[91m"
C_EXC  = "\033[41;97m"
C_RST  = "\033[0m"

# ─────────────────────────────────────────────
# LUÔN BỎ QUA CÁC MODULE NÀY
# ─────────────────────────────────────────────
_EXCLUDE = (
    "debug.py",
    "<frozen",
    "importlib",
    "threading",
    "asyncio",
    "discord",
    "logging",
    "traceback",
    "linecache",
    "inspect",
    "abc.py",
    "enum.py",
    "typing",
    "pathlib",
    "posixpath",
    "codecs",
    "encodings",
    "site.py",
    "functools",
    "weakref",
    "collections",
    "contextlib",
    "warnings",
    "json",
)

# ─────────────────────────────────────────────
# TRẠNG THÁI NỘI BỘ
# ─────────────────────────────────────────────
_active     = False
_filters    = ["game", "bot", "roles"]
_max_depth  = 5
_start_time = None
_print_lock = threading.Lock()


def _should_trace(filename: str) -> bool:
    if any(ex in filename for ex in _EXCLUDE):
        return False
    if _filters:
        return any(f in filename for f in _filters)
    return True


def _get_depth(frame) -> int:
    depth = 0
    f = frame.f_back
    while f and depth < 30:
        if not any(ex in f.f_code.co_filename for ex in _EXCLUDE):
            depth += 1
        f = f.f_back
    return depth


def _trace(frame, event, arg):
    if not _active:
        return None

    filename = frame.f_code.co_filename
    if not _should_trace(filename):
        return _trace

    depth = _get_depth(frame)
    if depth > _max_depth:
        return _trace

    short_file = filename.rsplit("/", 1)[-1]
    funcname   = frame.f_code.co_name
    lineno     = frame.f_lineno
    now        = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    indent     = "  " * depth

    with _print_lock:
        if event == "call":
            print(
                f"{C_TIME}{now}{C_RST} "
                f"{C_CALL}{indent}▶ {C_RST}"
                f"{C_FILE}{short_file}{C_RST}"
                f"{C_LNUM}:{lineno}{C_RST} "
                f"{C_FUNC}{funcname}(){C_RST}"
            )

        elif event == "line":
            source = linecache.getline(filename, lineno).strip()
            if source:
                print(
                    f"{C_TIME}{now}{C_RST} "
                    f"{C_FILE}{short_file}{C_RST}"
                    f"{C_LNUM}:{lineno:<4}{C_RST} "
                    f"{C_CODE}{indent}{source}{C_RST}"
                )

        elif event == "return":
            ret_str = repr(arg)[:80] if arg is not None else ""
            print(
                f"{C_TIME}{now}{C_RST} "
                f"{C_RET}{indent}◀ {C_RST}"
                f"{C_FILE}{short_file}{C_RST}"
                f"{C_LNUM}:{lineno}{C_RST} "
                f"{C_FUNC}{funcname}{C_RST}"
                + (f" → {C_CODE}{ret_str}{C_RST}" if ret_str else "")
            )

        elif event == "exception":
            exc_type, exc_val, _ = arg
            print(
                f"{C_TIME}{now}{C_RST} "
                f"{C_EXC} EXCEPTION {C_RST} "
                f"{C_FILE}{short_file}{C_RST}"
                f"{C_LNUM}:{lineno}{C_RST} "
                f"{C_RET}{exc_type.__name__}: {exc_val}{C_RST}"
            )

    return _trace


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────
def start(filter=None, max_depth=5):
    global _active, _filters, _max_depth, _start_time
    _active     = True
    _start_time = time.time()
    _max_depth  = max_depth
    if filter is not None:
        _filters = [filter] if isinstance(filter, str) else list(filter)

    sys.settrace(_trace)
    threading.settrace(_trace)

    # Patch Thread.run để mọi thread mới (kể cả asyncio) tự nhận trace
    _orig_run = threading.Thread.run
    def _run_with_trace(self_t):
        sys.settrace(_trace)
        try:
            _orig_run(self_t)
        finally:
            sys.settrace(None)
    threading.Thread.run = _run_with_trace

    fs = ", ".join(_filters) if _filters else "tất cả"
    print(f"\n{C_CALL}{'━'*50}{C_RST}")
    print(f"{C_CALL}  🐛 DEBUG BẮT ĐẦU — Filter: {fs}{C_RST}")
    print(f"{C_CALL}{'━'*50}{C_RST}\n")


def stop():
    global _active
    _active = False
    sys.settrace(None)
    threading.settrace(None)
    elapsed = f"{time.time() - _start_time:.2f}s" if _start_time else "?"
    print(f"\n{C_RET}{'━'*50}{C_RST}")
    print(f"{C_RET}  🛑 DEBUG DỪNG — Đã chạy {elapsed}{C_RST}")
    print(f"{C_RET}{'━'*50}{C_RST}\n")


# ─────────────────────────────────────────────
# ĐỌC LỆNH TỪ CONSOLE — chạy trong background thread
# KHÔNG block asyncio event loop
# ─────────────────────────────────────────────
def _console_listener():
    """Vòng lặp đọc stdin trong thread riêng — không block bot."""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:          # EOF (stdin bị đóng)
                break
            cmd = line.strip()
            if cmd.upper() == "DEBUG_MODE ON":
                start()
            elif cmd.upper() == "DEBUG_MODE OFF":
                stop()
        except Exception:
            break


def init():
    """Khởi động listener console. Gọi 1 lần khi bot start."""
    t = threading.Thread(target=_console_listener, name="DebugConsole", daemon=True)
    t.start()
    print(f"\n{C_CALL}{'━'*55}{C_RST}")
    print(f"{C_CALL}  🐛 DEBUG TRACER — Sẵn sàng{C_RST}")
    print(f"  Gõ lệnh bất cứ lúc nào:")
    print(f"    {C_CODE}DEBUG_MODE On{C_RST}   →  Bắt đầu in code đang thực thi")
    print(f"    {C_CODE}DEBUG_MODE Off{C_RST}  →  Dừng")
    print(f"{C_CALL}{'━'*55}{C_RST}\n")
