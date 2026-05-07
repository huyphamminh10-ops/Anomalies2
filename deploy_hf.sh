#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════╗
# ║        Anomalies2 — Auto Deploy to Hugging Face      ║
# ║  Chạy: bash deploy_hf.sh                             ║
# ╚══════════════════════════════════════════════════════╝

set -e  # Dừng ngay nếu có lỗi

# ── Màu sắc terminal ────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${CYAN}[•]${NC} $1"; }
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }
hr()   { echo -e "${BOLD}────────────────────────────────────────${NC}"; }

hr
echo -e "${BOLD}  🚀 Anomalies2 — Hugging Face Deploy Script${NC}"
hr

# ════════════════════════════════════════════════════════
# CẤU HÌNH — Sửa 2 dòng này thôi
# ════════════════════════════════════════════════════════
HF_USERNAME=""          # ← username Hugging Face của bạn
SSH_KEY_PATH=""         # ← đường dẫn private key (để trống = tự tạo mới)
# ════════════════════════════════════════════════════════

# ── Hỏi nếu chưa điền ──────────────────────────────────
if [[ -z "$HF_USERNAME" ]]; then
    echo -e -n "${YELLOW}  HF Username của bạn: ${NC}"
    read -r HF_USERNAME
fi

[[ -z "$HF_USERNAME" ]] && fail "HF_USERNAME không được để trống!"

SPACE_NAME="Anomalies2"
HF_REMOTE="git@hf.co:spaces/${HF_USERNAME}/${SPACE_NAME}"
SSH_CONFIG_HOST="hf.co"
KEY_NAME="hf_anomalies2"
KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/$KEY_NAME}"

echo ""
log "HF Space target: ${BOLD}${HF_USERNAME}/${SPACE_NAME}${NC}"
echo ""

# ════════════════════════════════════════════════════════
# BƯỚC 1: SSH Key
# ════════════════════════════════════════════════════════
hr; echo -e "${BOLD}  Bước 1/5: SSH Key${NC}"; hr

if [[ -f "$KEY_PATH" ]]; then
    ok "Đã có private key tại $KEY_PATH — bỏ qua tạo mới"
else
    log "Tạo SSH key mới (ed25519)..."
    mkdir -p "$HOME/.ssh"
    ssh-keygen -t ed25519 -C "${KEY_NAME}" -f "$KEY_PATH" -N "" -q
    ok "Đã tạo key pair tại $KEY_PATH"
fi

PUB_KEY=$(cat "${KEY_PATH}.pub")

echo ""
echo -e "${YELLOW}${BOLD}  ► Dán public key này vào HF Settings → SSH Keys:${NC}"
echo -e "${BOLD}  https://huggingface.co/settings/keys${NC}"
echo ""
echo -e "  ${GREEN}${PUB_KEY}${NC}"
echo ""
echo -e -n "  Nhấn ${BOLD}Enter${NC} sau khi đã thêm key vào HF... "
read -r

# ════════════════════════════════════════════════════════
# BƯỚC 2: SSH config
# ════════════════════════════════════════════════════════
hr; echo -e "${BOLD}  Bước 2/5: Cấu hình SSH${NC}"; hr

SSH_CONFIG="$HOME/.ssh/config"
touch "$SSH_CONFIG"

# Luôn ghi lại SSH config để đảm bảo đúng key (xoá entry cũ nếu có)
log "Cập nhật SSH config cho hf.co..."
if grep -q "Host ${SSH_CONFIG_HOST}" "$SSH_CONFIG" 2>/dev/null; then
    # Xoá block cũ bằng Python
    python3 - "$SSH_CONFIG" "$KEY_PATH" << 'PYEOF2'
import sys, re
cfg_path, key_path = sys.argv[1], sys.argv[2]
with open(cfg_path) as f:
    txt = f.read()
# Xoá block Host hf.co cũ
txt = re.sub(r'\nHost hf\.co.*?(?=\nHost |\Z)', '', txt, flags=re.DOTALL)
txt = txt.rstrip() + f"""

Host hf.co
    HostName hf.co
    User git
    IdentityFile {key_path}
    StrictHostKeyChecking no
"""
with open(cfg_path, 'w') as f:
    f.write(txt)
PYEOF2
    ok "Đã cập nhật SSH config (key mới)"
else
    cat >> "$SSH_CONFIG" << EOF

Host hf.co
    HostName hf.co
    User git
    IdentityFile ${KEY_PATH}
    StrictHostKeyChecking no
EOF
    ok "Đã thêm SSH config"
fi
chmod 600 "$SSH_CONFIG"

# Test SSH — retry đến khi OK
log "Kiểm tra kết nối SSH đến hf.co..."
_ssh_ok=0
for _attempt in 1 2 3; do
    _out=$(ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no \
               -o BatchMode=yes -o ConnectTimeout=10 \
               -T git@hf.co 2>&1 || true)
    if echo "$_out" | grep -qi "permission denied\|authentication failed\|publickey"; then
        echo ""
        warn "Lần $_attempt: SSH bị từ chối — key chưa được HF nhận."
        echo ""
        echo -e "  ${YELLOW}${BOLD}Kiểm tra lại:${NC}"
        echo -e "  1. Vào ${BOLD}https://huggingface.co/settings/keys${NC}"
        echo -e "  2. Xoá key cũ nếu có, thêm lại public key:"
        echo ""
        echo -e "  ${GREEN}${PUB_KEY}${NC}"
        echo ""
        if [[ $_attempt -lt 3 ]]; then
            echo -e -n "  Nhấn Enter để thử lại... "
            read -r
        fi
    else
        _ssh_ok=1
        break
    fi
done
[[ $_ssh_ok -eq 1 ]] || fail "SSH vẫn lỗi sau 3 lần — kiểm tra lại key tại https://huggingface.co/settings/keys"
ok "SSH kết nối thành công!"

# ════════════════════════════════════════════════════════
# BƯỚC 3: Secrets reminder
# ════════════════════════════════════════════════════════
hr; echo -e "${BOLD}  Bước 3/5: Secrets${NC}"; hr

echo -e "  Đảm bảo bạn đã set các biến sau trong HF Space:"
echo -e "  ${BOLD}https://huggingface.co/spaces/${HF_USERNAME}/${SPACE_NAME}/settings${NC}"
echo ""
echo -e "  ${YELLOW}  DISCORD_TOKEN${NC}  ← Token bot Discord"
echo -e "  ${YELLOW}  MONGO_URI     ${NC}  ← mongodb+srv://..."
echo ""
echo -e -n "  Nhấn ${BOLD}Enter${NC} sau khi đã set secrets... "
read -r

# ════════════════════════════════════════════════════════
# BƯỚC 4: Git remote + push
# ════════════════════════════════════════════════════════
hr; echo -e "${BOLD}  Bước 4/5: Push code lên HF${NC}"; hr

# Đảm bảo đang ở đúng thư mục (cùng chỗ với script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Kiểm tra có phải git repo không
[[ -d ".git" ]] || fail "Không tìm thấy .git — hãy chạy script này từ thư mục Anomalies2/"

# Thêm remote HF nếu chưa có
if git remote get-url hf &>/dev/null; then
    log "Remote 'hf' đã tồn tại — cập nhật URL..."
    git remote set-url hf "$HF_REMOTE"
else
    log "Thêm remote 'hf'..."
    git remote add hf "$HF_REMOTE"
fi
ok "Remote: $HF_REMOTE"

# Commit nếu có thay đổi chưa commit
if ! git diff --quiet || ! git diff --cached --quiet; then
    warn "Có thay đổi chưa commit — tự động commit..."
    git add -A
    git commit -m "chore: auto-deploy to Hugging Face"
    ok "Đã commit"
else
    ok "Không có thay đổi mới — dùng commit hiện tại"
fi

# Hỏi HF Token để tạo Space nếu chưa có (chỉ cần 1 lần)
log "Kiểm tra Space tồn tại chưa..."
SPACE_CHECK=$(curl -sf "https://huggingface.co/api/spaces/${HF_USERNAME}/${SPACE_NAME}" 2>/dev/null || true)
if echo "$SPACE_CHECK" | grep -q '"id"'; then
    ok "Space đã tồn tại"
else
    warn "Space chưa tồn tại — cần tạo mới"
    echo -e "  Vào: ${BOLD}https://huggingface.co/new-space${NC}"
    echo -e "  - Space name: ${BOLD}${SPACE_NAME}${NC}"
    echo -e "  - SDK: ${BOLD}Gradio${NC}"
    echo -e "  - Python: ${BOLD}3.10${NC}"
    echo -e "  - Visibility: ${BOLD}Public${NC}"
    echo ""
    echo -e "  ${YELLOW}Hoặc nhập HF Token để tạo tự động:${NC}"
    echo -e -n "  HF Token (Enter để bỏ qua và tạo tay): "
    read -r HF_TOKEN
    if [[ -n "$HF_TOKEN" ]]; then
        log "Đang tạo Space..."
        CREATE_RESP=$(curl -sf -X POST "https://huggingface.co/api/repos/create" \
            -H "Authorization: Bearer ${HF_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "{"type":"space","name":"${SPACE_NAME}","sdk":"gradio","private":false}" 2>&1 || true)
        if echo "$CREATE_RESP" | grep -q '"url"\|"id"'; then
            ok "Đã tạo Space thành công!"
            sleep 3
        else
            warn "Không tạo được tự động. Hãy tạo tay tại https://huggingface.co/new-space"
            echo -e -n "  Nhấn Enter sau khi đã tạo Space... "
            read -r
        fi
    else
        echo -e -n "  Nhấn Enter sau khi đã tạo Space... "
        read -r
    fi
fi

log "Đang push lên HF (nhánh main)..."
export GIT_SSH_COMMAND="ssh -i ${KEY_PATH} -o StrictHostKeyChecking=no -o BatchMode=yes -o IdentitiesOnly=yes"
if GIT_SSH_COMMAND="$GIT_SSH_COMMAND" git push hf main --force 2>&1; then
    ok "Push thành công!"
else
    fail "Push thất bại. Kiểm tra: (1) Space đã được tạo? (2) SSH key đúng? (3) Username đúng?"
fi

# ════════════════════════════════════════════════════════
# BƯỚC 5: Done
# ════════════════════════════════════════════════════════
hr; echo -e "${BOLD}  Bước 5/5: Hoàn tất 🎉${NC}"; hr

SPACE_URL="https://huggingface.co/spaces/${HF_USERNAME}/${SPACE_NAME}"
PING_URL="https://${HF_USERNAME}-${SPACE_NAME,,}.hf.space/ping"

echo ""
echo -e "  ${GREEN}${BOLD}Deploy thành công!${NC}"
echo ""
echo -e "  🌐 Space URL : ${CYAN}${SPACE_URL}${NC}"
echo -e "  🏓 Ping URL  : ${CYAN}${PING_URL}${NC}"
echo ""
echo -e "  ${YELLOW}Tip:${NC} Cài UptimeRobot ping Ping URL mỗi 5 phút"
echo -e "  để Space không bị ngủ:"
echo -e "  ${CYAN}https://uptimerobot.com${NC}"
echo ""
hr
