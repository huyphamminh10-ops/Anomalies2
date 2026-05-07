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

if grep -q "Host ${SSH_CONFIG_HOST}" "$SSH_CONFIG" 2>/dev/null; then
    ok "SSH config đã có entry cho hf.co"
else
    log "Thêm SSH config cho hf.co..."
    cat >> "$SSH_CONFIG" << EOF

Host hf.co
    HostName hf.co
    User git
    IdentityFile ${KEY_PATH}
    StrictHostKeyChecking no
EOF
    chmod 600 "$SSH_CONFIG"
    ok "Đã thêm SSH config"
fi

# Test SSH kết nối
log "Kiểm tra kết nối SSH đến hf.co..."
if ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no -o BatchMode=yes \
       -T git@hf.co 2>&1 | grep -q "Welcome\|authenticated\|Hi "; then
    ok "SSH kết nối thành công!"
else
    warn "Không thể verify SSH (có thể vẫn OK — HF không trả 'welcome message' như GitHub)"
fi

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

log "Đang push lên HF (nhánh main)..."
GIT_SSH_COMMAND="ssh -i ${KEY_PATH} -o StrictHostKeyChecking=no" \
    git push hf main --force

ok "Push thành công!"

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
