HƯỚNG DẪN SỬ DỤNG BOT ANOMALIES

Giới thiệu

Anomalies là một bot Discord tự động hóa trò chơi nhập vai suy luận xã hội kiểu Ma Sói. Bot quản lý toàn bộ tiến trình từ phòng chờ, phân vai trò, điều khiển đêm – ngày, bỏ phiếu, di chúc, cho đến kênh chat riêng của phe Dị Thể và người chết. Hệ thống hỗ trợ trên 65 vai trò, nhiều chế độ chơi, và có thể tùy chỉnh sâu qua lệnh /setting.

Bot chạy ổn định trên Discord, hỗ trợ môi trường Render, Hugging Face Spaces, và máy chủ riêng.

---

1. Cài đặt Bot lần đầu – Lệnh /setup

Ngay sau khi mời bot vào server, chủ server hoặc người có quyền cần chạy /setup. Quá trình gồm 4 bước tương tác.

Bước 1: Chọn kênh chat chữ (Text Channel)

· Chọn một kênh có sẵn, hoặc “Tạo kênh mới cho tôi” (bot tạo kênh 🌃-thị-trấn).

Bước 2: Chọn kênh thoại (Voice Channel)

· Chọn một kênh thoại có sẵn, “Tạo mới” (🗣️-nói-chuyện), hoặc “Không có kênh thoại”.

Bước 3: Chọn danh mục (Category)

· Có: bot sẽ gom kênh vào một Category (có sẵn hoặc tạo mới 🏙️ THỊ TRẤN).
· Không: các kênh nằm ngoài danh mục.

Bước 4: Xác nhận

Nhấn ✅ Xác nhận & Setup để bot tự động:

· Tạo kênh, role Alive-❤️‍🩹 (xanh) và Dead-☠️ (xám).
· Phân quyền: @everyone chỉ xem, các role khác được nói và gửi tin nhắn.
· Gửi bảng lobby đầu tiên vào kênh chat chữ.

🔁 Có thể chạy lại /setup bất kỳ lúc nào để thay đổi kênh hoặc tạo thêm.

---

2. Cấu hình trò chơi – Lệnh /setting

Lệnh /setting cho phép tùy chỉnh toàn bộ thông số trận đấu. Giao diện có 11 trang với nút ◀ / ▶.

Mục Loại Mô tả Giới hạn
Số người chơi tối đa Số Giới hạn người trong phòng chờ 5–65
Số người tối thiểu để bắt đầu Số Đủ người mới đếm ngược ≥5, < tổng
Thời gian đếm ngược Thời gian Countdown sau khi đủ người 1–3 phút (60–180s)
Thời gian thảo luận Thời gian Thời gian ban ngày 30–120s (mặc định 90)
Thời gian bỏ phiếu Thời gian Thời gian bình chọn trục xuất 15–45s (mặc định 30)
Delay DM Skip Thời gian Thời gian chờ trước khi gửi DM nhắc bỏ qua thảo luận Số giây tùy ý
Skip Thảo Luận Bật/Tắt Cho phép người chơi rút ngắn thảo luận bằng phiếu ✅ Bật
Mute Khi Chết Bật/Tắt Tự động tắt mic người chết ✅ Bật, nhưng bị khóa nếu bật “Không gỡ role”
Tên kênh Tùy chọn khác Đổi tên danh mục, kênh text, kênh voice ngay trong game –
Quyền sử dụng lệnh Tùy chọn khác Ai được dùng /setting, /clear, /setup (4 cấp) Chỉ chủ server sửa được
Không gỡ role Bật/Tắt Giữ nguyên toàn bộ role server, không gán role Alive/Dead ❌ Tắt

💡 Các mục “Thời gian” sẽ hiện modal nhập số, “Bật/Tắt” sẽ đảo trạng thái ngay lập tức.

---

3. Cách tham gia và bắt đầu trận

1. Vào kênh thoại của bot (kênh được chọn khi /setup).
2. Bot sẽ tự động nhận diện và thêm bạn vào phòng chờ.
3. Khi số người trong phòng chờ ≥ số tối thiểu, bot bắt đầu đếm ngược.
4. Hết đếm ngược, bot khởi động trận đấu, phân vai trò qua DM.

📌 Lưu ý: Hãy chắc chắn bạn đã bật nhận tin nhắn từ thành viên server (cài đặt quyền riêng tư) để nhận DM từ bot.

---

4. Gameplay chi tiết

4.1. Ban đêm (Night)

· Tất cả người sống bị mute trong kênh thoại (trừ chế độ Parliament).
· Bot gửi DM riêng cho từng người có giao diện chọn mục tiêu (nếu vai trò có hành động).
· Người chơi có thời gian Thời gian đêm (mặc định 45s) để chọn.
· Sau khi hết giờ, các hành động được giải quyết theo thứ tự ưu tiên.
· Kẻ bị tấn công có thể được bảo vệ hoặc miễn nhiễm (xem chi tiết vai trò).
· Bot gửi log đêm cho Anomaly Chat và Sleeper (nếu có).

4.2. Ban ngày (Day)

· Tất cả người sống được unmute.
· Bot thông báo ai đã chết trong đêm (với hiệu ứng AI tường thuật nếu có).
· Người chơi thảo luận công khai trong kênh voice và text.
· Nếu bật Skip Thảo Luận, người chơi có thể bỏ phiếu rút ngắn qua DM.

4.3. Bỏ phiếu trục xuất (Voting)

· Giao diện bỏ phiếu xuất hiện công khai trong kênh text.
· Mỗi người sống được chọn một mục tiêu (hoặc Bỏ qua).
· Phiếu có thể có trọng số tùy vai trò, và ẩn danh nếu cấu hình.
· Người nhiều phiếu nhất bị trục xuất và chết ngay lập tức (luôn bị mute).
· Nếu hòa phiếu, tùy cấu hình sẽ bỏ phiếu lại hoặc không ai bị trục xuất.

Vòng lặp Đêm → Ngày → Bỏ phiếu tiếp tục cho đến khi một phe đạt điều kiện thắng.

4.4. Điều kiện thắng

· Survivors: loại bỏ tất cả Anomalies và các thực thể thù địch.
· Anomalies: chiếm đa số (số Anomalies sống ≥ số Survivors).
· Unknown Entities: mỗi vai trò có điều kiện riêng (ví dụ: Serial Killer sống sót cuối cùng, Corrupted AI thu thập đủ dữ liệu, …).

---

5. Hệ thống Di Chúc (Will)

Di chúc là tính năng cho phép tất cả người chơi viết ghi chú để lại sau khi chết.

Cách viết di chúc

1. Mở DM với bot, gửi tin nhắn chính xác: Nhập di chúc
2. Bot sẽ hướng dẫn bạn. Sau đó, mỗi tin nhắn bạn gửi được tính là 1 dòng.
3. Giới hạn: tối đa 45 dòng, mỗi dòng tối đa 60 kí tự (không tính dấu cách).
4. Dòng hợp lệ: bot react ✅ + số thứ tự. Dòng quá dài: bot react 🚫 và báo lỗi.
5. Khi bạn chết, di chúc tự động khóa.

Xem di chúc người đã chết

· Mỗi sáng, bot gửi bảng 📋 LÁ THƯ NGƯỜI CHẾT kèm menu chọn.
· Chọn tên → bot gửi file .txt vào DM của bạn chứa toàn bộ di chúc của người đó.

---

6. Các kênh chat riêng

6.1. Anomaly Chat (🔴)

· Kênh bí mật chỉ dành cho các thành viên phe Anomalies.
· Bot tự động thêm người vào khi nhận vai trò.
· Gửi báo cáo hàng đêm (danh sách Survivors còn sống, đồng đội, sự kiện).
· Survivor điều tra trúng Anomaly sẽ gây cảnh báo trong kênh này.

6.2. Dead Chat (💀)

· Kênh dành cho người đã chết.
· Có thể trò chuyện với nhau nhưng không can thiệp vào game.
· Một số vai trò (Nhà Ngoại Cảm) có thể giao tiếp với Dead Chat.

---

7. Quản lý Vai Trò – Lệnh /role

Lệnh /role mở bảng điều khiển cho phép:

Chức năng Mô tả
Xem phân bổ hiện tại Xem danh sách vai trò sẽ được phân phát dựa trên số người trong kênh thoại.
Thống kê vai trò Tổng quan số lượng, tỉ lệ các phe.
Thông tin vai trò Tra cứu chi tiết từng vai trò: khả năng, mẹo chơi.
Event Role Xem event role đang hoạt động và lịch sử xoay vòng.
🔄 Roll lại Tạo lại bảng phân phối mới (ngẫu nhiên).
🛠 Chỉnh sửa vai trò Tùy chỉnh thủ công danh sách vai trò cho ván tiếp theo (chọn chính xác số lượng mỗi role).

🔐 Quyền chỉnh sửa vai trò dùng chung cấu hình Quyền sử dụng lệnh (Mục 8).

---

8. Phân quyền sử dụng lệnh

Hệ thống 4 cấp độ kiểm soát ai được dùng /setting, /clear, /setup, và Chỉnh sửa vai trò:

Cấp Tên Quyền
1 Chỉ Chủ Server Chỉ chủ server
2 Quản trị viên Chủ server + những role có quyền Quản lý máy chủ
3 Vai trò đặc biệt Cấp 2 + tối đa 12 role được chọn thủ công
4 Người chơi đặc quyền Cấp 3 + tối đa 6 người dùng cụ thể

Thay đổi cấp độ này chỉ dành cho chủ server, thực hiện trong /setting → Quyền sử dụng lệnh.

---

9. Lệnh /clear và các lệnh khác

Lệnh Mô tả Quyền
/setup Cài đặt / thay đổi kênh chơi Theo cấp quyền
/setting Điều chỉnh mọi thông số Theo cấp quyền
/clear Xóa tất cả tin nhắn trong kênh game (trừ bảng lobby) Theo cấp quyền
/role Xem / chỉnh sửa vai trò Tất cả (chỉnh sửa cần quyền)
/help Xem hướng dẫn dạng menu tương tác Tất cả

---

10. Event Role

· Hệ thống tự động xoay vòng event role mỗi giờ từ kho roles/event/.
· Xem role đang kích hoạt và đồng hồ đếm ngược qua /role → Event Role.
· Admin có thể thêm role mới bằng cách thả file .py vào thư mục roles/event/.

---

11. Các chế độ đặc biệt

11.1. Large Server Mode

Tự động kích hoạt khi số người chơi ≥ 40 (có thể tùy chỉnh ngưỡng). Khi bật:

· Thời gian đêm/ngày/vote được kéo dài.
· Giới hạn số lượng vai trò điều tra hoạt động mỗi đêm (tránh quá tải).

11.2. Parliament Mode

Thay vì tự do nói, mỗi người sống được phát biểu trong X giây (do bot kiểm soát mute/unmute). Bật trong /setting (voice mode).

---