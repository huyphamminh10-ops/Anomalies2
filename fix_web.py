import os

def fix_dashboard():
    file_name = 'index.html'
    
    if not os.path.exists(file_name):
        print(f"❌ Không tìm thấy file {file_name} trong thư mục này!")
        return

    with open(file_name, 'r', encoding='utf-8') as f:
        content = f.read()

    # Đoạn script JS cần chèn vào
    fix_js = """
// --- AUTO FIX START ---
const API_URL = window.location.origin; 
const state = { user: null, view: 'dashboard', loading: false };

async def_boot() {
    console.log("System booting...");
    if (typeof showLoading === 'function') showLoading(true);
    try {
        // Nếu API chưa sẵn sàng, giả lập user để hiện Dashboard luôn
        // Sau này ông chạy backend xong thì xóa dòng dưới đi nhé
        state.user = { name: "NẶNG5GRAM", role: "Admin" }; 
        
        if (typeof render === 'function') render();
    } catch (e) {
        console.error("Boot error:", e);
    } finally {
        if (typeof showLoading === 'function') showLoading(false);
    }
}

// Tự kích hoạt khi load trang
window.addEventListener('DOMContentLoaded', def_boot);

// Bẫy lỗi alert để debug trên điện thoại
window.onerror = function(msg, url, line) {
    alert("Lỗi JS: " + msg + "\\nTại dòng: " + line);
};
// --- AUTO FIX END ---
"""

    # Tìm thẻ đóng </script> cuối cùng để chèn vào trước đó
    if '</script>' in content:
        # Chèn vào trước thẻ đóng script cuối cùng
        parts = content.rsplit('</script>', 1)
        new_content = parts[0] + fix_js + '\n</script>' + parts[1]
        
        with open(file_name, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"✅ Đã 'tiêm' thuốc hồi sinh vào {file_name} thành công!")
    else:
        print("❌ Không tìm thấy thẻ <script> để sửa!")

if __name__ == "__main__":
    fix_dashboard()

