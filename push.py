import subprocess
import os
import time

COUNTER_FILE = ".push_counter"
MAX_RETRIES  = 5
RETRY_DELAY  = 5  # giây giữa mỗi lần thử

# ── Đọc số commit hiện tại ────────────────────────────────────────────────────
if os.path.exists(COUNTER_FILE):
    with open(COUNTER_FILE, "r") as f:
        count = int(f.read().strip())
else:
    count = 20

# ── git add + commit ──────────────────────────────────────────────────────────
subprocess.run(["git", "add", "."], check=True)

result = subprocess.run(["git", "commit", "-m", str(count)])
if result.returncode != 0:
    print("⚠️  Không có gì thay đổi hoặc commit lỗi — bỏ qua push.")
    exit(0)

# ── git push với retry ────────────────────────────────────────────────────────
for attempt in range(1, MAX_RETRIES + 1):
    print(f"🚀 Push lần {attempt}/{MAX_RETRIES}  (commit #{count})...")
    result = subprocess.run(["git", "push", "origin", "master"])

    if result.returncode == 0:
        # Lưu số tiếp theo chỉ khi push thành công
        with open(COUNTER_FILE, "w") as f:
            f.write(str(count + 1))
        print(f"✅ Done — commit #{count}")
        break

    print(f"❌ Push thất bại (lần {attempt}). Thử lại sau {RETRY_DELAY}s...")
    time.sleep(RETRY_DELAY)

else:
    print(f"💀 Push thất bại sau {MAX_RETRIES} lần. Kiểm tra mạng rồi chạy lại.")
    exit(1)
