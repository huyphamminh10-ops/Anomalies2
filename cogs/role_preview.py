"""
role_preview.py — discord.py 2.x
Role info catalogue is built at startup by scanning the roles/ folder via AST.
No hardcoded descriptions. Tips are derived from each role's own description text.
All 4 buttons are fully functional.
"""

from __future__ import annotations

import ast
import glob
import os
import traceback
from collections import Counter
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Select, View

from role_distributor import (
    ANOMALIES_META,
    EVENT_META,
    SURVIVORS_META,
    UNKNOWN_META,
    RoleDistributor,
    validate_balance,
)


# ══════════════════════════════════════════════════════════════════
# ROLE CATALOGUE BUILDER
# Scans roles/ via AST at import time — no discord import needed.
# ══════════════════════════════════════════════════════════════════

def _derive_tips(name: str, faction: str, description: str, meta: dict) -> str:
    """
    Generate practical gameplay tips derived from a role's description text.
    Keyword-matches description content to produce contextual advice.
    """
    desc_lower = description.lower()
    tips: list[str] = []

    # Kill / attack roles
    if any(k in desc_lower for k in ("giết", "sát", "bắn", "tiêu diệt", "xử tử")):
        if faction == "Survivors":
            tips.append("Chỉ hành động khi chắc chắn — sai lầm có thể gây hại cho phe bạn.")
        else:
            tips.append("Ưu tiên tiêu diệt Thám Trưởng, Cai Ngục và Thám Tử trước tiên.")

    # Investigate / detect
    if any(k in desc_lower for k in ("điều tra", "kiểm tra", "linh cảm", "phát hiện", "nhận ra")):
        tips.append("Xác nhận thông tin từ nhiều nguồn trước khi cáo buộc công khai.")

    # Protect / fortify
    if any(k in desc_lower for k in ("bảo vệ", "gia cố", "miễn nhiễm", "không thể bị giết")):
        tips.append("Ưu tiên bảo vệ các vai trò quan trọng như Thám Trưởng hoặc Cai Ngục.")

    # Reveal / expose
    if any(k in desc_lower for k in ("lộ diện", "tiết lộ", "công bố")):
        tips.append("Thời điểm lộ diện quyết định thành bại — đừng hành động quá sớm.")

    # Jail / imprison
    if any(k in desc_lower for k in ("giam giữ", "giam cầm", "bắt giam", "cách ly")):
        tips.append("Nhốt người nghi vấn vào những đêm mấu chốt để vô hiệu hóa hành động của họ.")

    # Revive / resurrect
    if any(k in desc_lower for k in ("hồi sinh", "sống lại")):
        tips.append("Hồi sinh Thám Trưởng hoặc Cai Ngục ở giai đoạn cuối để lật ngược thế cờ.")

    # Dead communication / will
    if any(k in desc_lower for k in ("người đã chết", "linh hồn", "di chúc")):
        tips.append("Thông tin từ người chết rất quý giá — hãy chuyển tải khéo léo mà không lộ vai trò.")

    # Vote weight / ballot
    if any(k in desc_lower for k in ("phiếu bầu", "hệ số", "x3", "bỏ phiếu")):
        tips.append("Kiểm soát bỏ phiếu là vũ khí chiến lược — phối hợp để loại đúng người.")

    # Trap / ambush
    if any(k in desc_lower for k in ("bẫy", "phục kích")):
        tips.append("Đặt bẫy vào nhà những người có thể bị nhắm mục tiêu để lộ diện kẻ tấn công.")

    # Disguise / mimic / parasite
    if any(k in desc_lower for k in ("giả mạo", "cộng sinh", "ngụy trang", "ký sinh")):
        tips.append("Giữ vỏ bọc càng lâu càng tốt — một khi bị lộ bạn trở thành mục tiêu ngay.")

    # Mark / countdown / activate
    if any(k in desc_lower for k in ("đánh dấu", "đếm ngược", "kích hoạt")):
        tips.append("Kiên nhẫn tích lũy đủ điều kiện trước khi kích hoạt vào thời điểm quyết định.")

    # Revenge / death-trigger
    if any(k in desc_lower for k in ("báo thù", "kéo xuống", "trả thù")):
        tips.append("Sự hy sinh có chủ đích của bạn có thể thay đổi cục diện cả trận đấu.")

    # Control / puppet / manipulate
    if any(k in desc_lower for k in ("điều khiển", "kiểm soát", "buộc")):
        tips.append("Điều khiển những vai trò mạnh để biến vũ khí của đối phương chống lại chính họ.")

    # Observe / camera / spy
    if any(k in desc_lower for k in ("theo dõi", "camera", "nghe lén", "nhắm vào ai")):
        tips.append("Thông tin bạn thu thập có giá trị hơn một cú giết — dùng nó đúng lúc đúng chỗ.")

    # Steal / read / copy
    if any(k in desc_lower for k in ("đánh cắp", "đọc di chúc", "sao chép")):
        tips.append("Khai thác thông tin thu thập được ngay trước khi đối thủ kịp thích nghi.")

    # Time / rewind
    if any(k in desc_lower for k in ("tua", "quay lại", "thời gian")):
        tips.append("Dành khả năng đặc biệt cho khoảnh khắc thay đổi cục diện — đừng phung phí sớm.")

    # Bullet / charge economy
    if any(k in desc_lower for k in ("viên đạn", "lượt", "lần duy nhất")):
        tips.append("Quản lý tài nguyên có hạn thật cẩn thận — mỗi lần dùng đều phải có giá trị.")

    # ── Extended tips ───────────────────────────────────────────

    # Silence / block / prevent
    if any(k in desc_lower for k in ("chặn", "ngăn chặn", "vô hiệu hóa", "không thể hành động")):
        tips.append("Chặn đúng người đúng đêm có thể cứu cả trận — hãy đọc kỹ tình huống.")

    # Corrupt / destroy data / will
    if any(k in desc_lower for k in ("phá hủy", "xóa", "dữ liệu", "di chúc")):
        tips.append("Xóa di chúc của Thám Tử hoặc Thám Trưởng trước khi họ chết để bịt đầu mối.")

    # Announce / mayor / public reveal
    if any(k in desc_lower for k in ("công khai", "thị trưởng", "tuyên bố")):
        tips.append("Chỉ lộ danh tính khi thị trấn đang lung lay — bạn không thể rút lại sau đó.")

    # Solo win condition
    if any(k in desc_lower for k in ("thắng một mình", "solo", "chiến thắng riêng")):
        tips.append("Giả vờ theo phe nào đó cho đến gần cuối — rồi phản bội cả hai.")

    # Chaos / random / unpredictable
    if any(k in desc_lower for k in ("ngẫu nhiên", "hỗn loạn", "bất định")):
        tips.append("Sự hỗn loạn là lợi thế — hãy khiến cả hai phe không thể đọc được bạn.")

    # Infection / spread
    if any(k in desc_lower for k in ("lây nhiễm", "lây lan", "lan rộng")):
        tips.append("Nhắm vào những người có ảnh hưởng lớn để lan rộng hiệu ứng nhanh nhất.")

    # Track / follow
    if any(k in desc_lower for k in ("theo dõi", "đi theo", "bám theo")):
        tips.append("Theo dõi người bị nghi ngờ nhiều nhất — nhưng đừng bao giờ tiết lộ bạn đang làm điều đó.")

    # Night immunity / invincible
    if any(k in desc_lower for k in ("miễn nhiễm ban đêm", "không thể bị giết ban đêm", "sống sót")):
        tips.append("Miễn nhiễm không có nghĩa là an toàn — ban ngày bạn vẫn có thể bị trục xuất.")

    # Convert / recruit
    if any(k in desc_lower for k in ("chiêu mộ", "chuyển đổi", "gia nhập")):
        tips.append("Chiêu mộ các vai trò mạnh nhất trước — một Cai Ngục đứng về phía bạn là cơn ác mộng.")

    # Bomb / explode / trap death
    if any(k in desc_lower for k in ("nổ", "bom", "kéo theo")):
        tips.append("Để kẻ tấn công tự kích hoạt bẫy — đừng tiết lộ trước khi quá muộn.")

    # Dream / sleep / confuse
    if any(k in desc_lower for k in ("giấc mơ", "mê hoặc", "gây mê", "ngủ")):
        tips.append("Gây nhầm lẫn cho đối thủ hiệu quả hơn là giết trực tiếp — thông tin sai còn nguy hiểm hơn.")

    # Blackmail / threaten
    if any(k in desc_lower for k in ("tống tiền", "đe dọa", "im lặng")):
        tips.append("Ép im lặng đúng lúc — không cho đối thủ chia sẻ thông tin là cách vô hiệu hóa tốt nhất.")

    # Fake role / lie
    if any(k in desc_lower for k in ("giả mạo vai trò", "khai giả", "mạo danh")):
        tips.append("Mạo danh Thám Trưởng hoặc Thám Tử — khiến thị trấn tin bạn là đồng minh.")

    # Link / bond / share
    if any(k in desc_lower for k in ("liên kết", "kết nối", "chia sẻ số phận")):
        tips.append("Chọn đối tác liên kết thật cẩn thận — số phận bạn phụ thuộc vào người đó.")

    # Countdown / last night / timer
    if any(k in desc_lower for k in ("đêm cuối", "còn lại", "giới hạn")):
        tips.append("Đừng lãng phí những đêm cuối — mỗi hành động đều phải mang lại kết quả rõ ràng.")

    # Passive ability
    if any(k in desc_lower for k in ("thụ động", "tự động", "luôn luôn", "mỗi khi")):
        tips.append("Khả năng thụ động mạnh khi kết hợp đúng vai — hãy cân nhắc ai nên đứng cạnh bạn.")

    # Anonymity / hidden
    if any(k in desc_lower for k in ("ẩn danh", "không ai biết", "bí mật")):
        tips.append("Danh tính ẩn là tài sản lớn nhất — đừng hành động theo cách dễ bị nhận ra.")

    # Execute / final vote
    if any(k in desc_lower for k in ("xử tử", "tử hình", "phán quyết")):
        tips.append("Chỉ xử tử khi bằng chứng đủ mạnh — một sai lầm ở giai đoạn cuối là thất bại.")

    # Cooldown / skip night
    if any(k in desc_lower for k in ("hồi chiêu", "nghỉ", "cần chờ", "qua đêm")):
        tips.append("Lên kế hoạch từ trước — đêm cooldown là đêm bạn cần quan sát thật kỹ.")

    # Heal / restore
    if any(k in desc_lower for k in ("chữa lành", "hồi phục", "cứu chữa")):
        tips.append("Cứu người quan trọng nhất — đừng lãng phí heal vào những vai trò ít ảnh hưởng.")

    # Ghost / undead / spirit
    if any(k in desc_lower for k in ("bóng ma", "linh hồn chưa siêu thoát", "vong")):
        tips.append("Sức mạnh sau khi chết vẫn còn — hãy chắc chắn hy sinh vào đúng thời điểm.")

    # Multiple targets / aoe
    if any(k in desc_lower for k in ("nhiều mục tiêu", "tất cả", "hàng loạt", "diện rộng")):
        tips.append("Tấn công diện rộng mạnh nhất khi tập trung vào nhóm đông — chọn đêm đỉnh điểm.")

    # Confusion / swap
    if any(k in desc_lower for k in ("hoán đổi", "đánh tráo", "thay thế")):
        tips.append("Hoán đổi mục tiêu khi cả hai phe đang dồn sức vào nhau để tối đa hóa hỗn loạn.")

    # Watcher / alert
    if any(k in desc_lower for k in ("canh gác", "cảnh báo", "cảnh giác")):
        tips.append("Báo động sớm cứu được nhiều mạng hơn — chia sẻ kết quả quan sát ngay khi an toàn.")

    # Sacrifice / give up
    if any(k in desc_lower for k in ("hy sinh", "đánh đổi", "mất đi")):
        tips.append("Hy sinh có giá trị — nhưng chỉ khi nó đổi lấy thứ gì đó lớn hơn bản thân bạn.")

    # Paranoia / doubt
    if any(k in desc_lower for k in ("nghi ngờ", "hoang mang", "mất tin tưởng")):
        tips.append("Gieo nghi ngờ vào đúng người đúng lúc có thể phá vỡ toàn bộ chiến lược đối phương.")

    # Redirect / deflect
    if any(k in desc_lower for k in ("chuyển hướng", "chuyển mục tiêu", "đổi hướng")):
        tips.append("Chuyển hướng đòn tấn công vào kẻ thù của kẻ thù — khiến họ tự tiêu diệt nhau.")

    # Read wills / documents
    if any(k in desc_lower for k in ("đọc", "xem di chúc", "tài liệu")):
        tips.append("Di chúc giả có thể là bẫy — hãy đọc kỹ và đối chiếu với hành vi thực tế của họ.")

    # Escape / evade
    if any(k in desc_lower for k in ("trốn thoát", "thoát khỏi", "miễn trừ")):
        tips.append("Khả năng thoát thoát chỉ dùng được một lần — giữ lại cho đêm nguy hiểm nhất.")

    # Stealthy kill / no trace
    if any(k in desc_lower for k in ("không để lại dấu vết", "sạch sẽ", "ẩn náu")):
        tips.append("Giết không dấu vết đặc biệt mạnh khi Thám Tử đang còn sống — ưu tiên dùng lúc đó.")

    # Copycat / mirror
    if any(k in desc_lower for k in ("sao chép", "phản chiếu", "bắt chước")):
        tips.append("Sao chép vai trò mạnh nhất trong trận — nhưng đừng để lộ bạn đang làm điều đó.")

    # Mind control / force
    if any(k in desc_lower for k in ("thao túng", "bắt buộc", "không thể từ chối")):
        tips.append("Thao túng người có hệ số phiếu cao sẽ có tác động lớn hơn nhiều so với người thường.")

    # Chaos agent / neutral
    if any(k in desc_lower for k in ("trung lập", "không thuộc phe", "độc lập")):
        tips.append("Là người trung lập — bạn có thể đứng về bất kỳ ai miễn là nó có lợi cho mục tiêu của bạn.")

    # Snitch / inform
    if any(k in desc_lower for k in ("báo cáo", "cung cấp thông tin", "phản bội")):
        tips.append("Thông tin bạn chia sẻ có thể cứu đồng đội — nhưng cũng có thể lộ vị trí của bạn.")

    # Delayed action / future effect
    if any(k in desc_lower for k in ("ngày hôm sau", "lần sau", "hiệu lực sau")):
        tips.append("Hành động trễ nghĩa là phải lên kế hoạch sớm hơn — không được phép phản ứng muộn.")

    # Witness / observe kill
    if any(k in desc_lower for k in ("chứng kiến", "thấy kẻ tấn công", "nhận ra")):
        tips.append("Chứng kiến một vụ giết là bằng chứng mạnh nhất — nhưng kẻ giết cũng biết bạn thấy họ.")

    # Eliminate all factions
    if any(k in desc_lower for k in ("tiêu diệt tất cả", "không còn ai", "diệt gọn")):
        tips.append("Để các phe tự đánh nhau trước — rồi ra tay dọn dẹp phần còn lại.")

    # Hidden faction / secret team
    if any(k in desc_lower for k in ("phe ẩn", "bí mật", "không ai biết phe")):
        tips.append("Che giấu phe phái là lợi thế lớn nhất — đừng để hành động của bạn tự tố cáo.")

    # Last man standing
    if any(k in desc_lower for k in ("người cuối cùng", "sống sót cuối", "còn lại duy nhất")):
        tips.append("Tránh đối đầu trực tiếp — để người khác tiêu hao nhau rồi bạn mới xuất hiện.")

    # Number-based / threshold
    if any(k in desc_lower for k in ("bằng số", "vượt quá", "đủ số lượng")):
        tips.append("Đạt ngưỡng điều kiện sớm sẽ cho bạn lợi thế to lớn — đừng trì hoãn tích lũy.")

    # Whisper / private message
    if any(k in desc_lower for k in ("thì thầm", "tin nhắn riêng", "nhắn tin")):
        tips.append("Nhắn tin riêng dễ bị nghi ngờ — hãy làm điều đó tự nhiên và không quá thường xuyên.")

    # Expose Anomaly
    if any(k in desc_lower for k in ("vạch mặt", "tố cáo", "lộ mặt dị thể")):
        tips.append("Tố cáo sớm rất rủi ro — chờ thêm bằng chứng để tăng độ tin cậy trước thị trấn.")

    # Survive to endgame
    if any(k in desc_lower for k in ("đến cuối trận", "sống đến", "tồn tại")):
        tips.append("Sống sót qua giai đoạn giữa trận là thách thức lớn nhất — hãy giữ profile thấp.")

    # Punish attacker
    if any(k in desc_lower for k in ("trừng phạt kẻ tấn công", "phản đòn", "kẻ tấn công chết")):
        tips.append("Đừng tiết lộ bạn có khả năng phản đòn — kẻ tấn công sẽ né nếu biết trước.")

    # Share info teammates
    if any(k in desc_lower for k in ("chia sẻ với đồng đội", "thông báo cho phe", "đồng minh biết")):
        tips.append("Chia sẻ thông tin đúng người — không phải ai cũng đáng tin, kể cả trong cùng phe.")

    # ── Extended tips (100 new) ──────────────────────────────────

    # Poison / toxin / slow kill
    if any(k in desc_lower for k in ("đầu độc", "chất độc", "độc tố", "nhiễm độc")):
        tips.append("Độc tác dụng chậm — hãy đầu độc từ sớm để hiệu quả xuất hiện đúng lúc cần thiết.")

    # Shield / armor / physical defense
    if any(k in desc_lower for k in ("khiên", "giáp", "lá chắn", "hấp thụ đòn")):
        tips.append("Dùng khiên khi bạn biết mình là mục tiêu — đừng tiêu tốn nó vào những đêm yên tĩnh.")

    # Clone / duplicate self
    if any(k in desc_lower for k in ("nhân bản", "phân thân", "bản sao")):
        tips.append("Bản sao là mồi nhử hoàn hảo — để kẻ địch tốn hành động vào mục tiêu sai.")

    # Bounty / reward / mark for kill
    if any(k in desc_lower for k in ("tiền thưởng", "truy nã", "đặt giá")):
        tips.append("Đặt tiền thưởng vào đúng người sẽ khiến cả thị trấn làm công việc thay bạn.")

    # Oracle / prophecy / foresee
    if any(k in desc_lower for k in ("tiên tri", "dự đoán", "nhìn thấy tương lai", "báo trước")):
        tips.append("Tiên tri không có nghĩa là chắc chắn — hãy trình bày khéo léo để không bị xem là kẻ nói dối.")

    # Teleport / warp / instant move
    if any(k in desc_lower for k in ("dịch chuyển", "tức thì", "bước qua")):
        tips.append("Dịch chuyển giúp bạn không bị đoán trước — thay đổi mục tiêu mỗi đêm để gây bối rối.")

    # Curse / hex / doom
    if any(k in desc_lower for k in ("nguyền rủa", "yểm bùa", "lời nguyền", "đánh dấu chết")):
        tips.append("Lời nguyền mạnh nhất khi nhắm vào những vai trò không thể bị giết trực tiếp.")

    # Silence / mute / suppress speech
    if any(k in desc_lower for k in ("bịt miệng", "câm lặng", "không được phép nói", "mất tiếng")):
        tips.append("Bịt miệng Thám Trưởng trước khi họ kịp chia sẻ thông tin là ưu tiên hàng đầu.")

    # Paralyze / stun / freeze in place
    if any(k in desc_lower for k in ("tê liệt", "choáng", "đóng băng hành động", "không thể di chuyển")):
        tips.append("Tê liệt đúng người đúng đêm tương đương với một cú giết — nhưng không để lại bằng chứng.")

    # Fire / burn / arson / ignite
    if any(k in desc_lower for k in ("đốt cháy", "phóng hỏa", "lửa", "thiêu rụi")):
        tips.append("Phóng hỏa nhiều nhà trước rồi kích hoạt cùng lúc — đừng để đối thủ kịp phản ứng.")

    # Ice / cold / freeze status
    if any(k in desc_lower for k in ("băng giá", "lạnh buốt", "đóng băng", "hóa đá")):
        tips.append("Đóng băng mục tiêu trong đêm quan trọng sẽ vô hiệu hóa hoàn toàn kế hoạch của họ.")

    # Darkness / shadow manipulation
    if any(k in desc_lower for k in ("bóng tối", "màn đêm", "che khuất", "bóng đen")):
        tips.append("Hoạt động trong bóng tối khiến kẻ điều tra không tìm ra bạn — giữ bí mật tuyệt đối.")

    # Illuminate / reveal hidden
    if any(k in desc_lower for k in ("chiếu sáng", "soi rọi", "làm lộ", "xóa tan bóng tối")):
        tips.append("Soi rọi khu vực nghi ngờ nhất ngay khi bắt đầu đêm — thông tin sớm quyết định cả trận.")

    # Power boost / strengthen ally
    if any(k in desc_lower for k in ("tăng cường", "hỗ trợ", "nâng sức mạnh", "buff")):
        tips.append("Tăng cường sức mạnh cho đồng đội nguy hiểm nhất của bạn — nhân đôi áp lực lên đối thủ.")

    # Weaken / debuff enemy
    if any(k in desc_lower for k in ("làm yếu", "giảm sức mạnh", "suy yếu", "debuff")):
        tips.append("Làm yếu mục tiêu nguy hiểm nhất trước khi đồng đội ra tay sẽ đảm bảo thành công.")

    # Luck / fortune / probability manipulation
    if any(k in desc_lower for k in ("may mắn", "vận may", "xác suất", "số phận")):
        tips.append("Xác suất không đảm bảo gì — luôn có phương án dự phòng nếu vận may không đứng về phía bạn.")

    # Barrier / force field / blockade
    if any(k in desc_lower for k in ("hàng rào", "lực trường", "tường chắn", "phong tỏa")):
        tips.append("Dựng hàng rào quanh đồng minh quan trọng nhất — buộc kẻ địch phải thay đổi mục tiêu.")

    # Fake death / play dead
    if any(k in desc_lower for k in ("giả chết", "giả vờ chết", "làm ra vẻ đã chết")):
        tips.append("Giả chết thuyết phục nhất khi được thực hiện sớm — kẻ địch sẽ bỏ qua bạn.")

    # Double agent / spy both sides
    if any(k in desc_lower for k in ("hai mặt", "nằm vùng", "gián điệp hai phe", "phục vụ cả hai")):
        tips.append("Là kẻ hai mặt — nhưng phải nhất quán trong từng lần tương tác để không bị bại lộ.")

    # Purify / cleanse / remove effect
    if any(k in desc_lower for k in ("thanh tẩy", "gỡ trạng thái", "loại bỏ hiệu ứng", "giải độc")):
        tips.append("Giải độc và thanh tẩy trạng thái nguy hiểm ngay lập tức — để lâu sẽ gây hậu quả không thể cứu vãn.")

    # Lock / seal / bind target
    if any(k in desc_lower for k in ("phong ấn", "niêm phong", "trói buộc", "khóa lại")):
        tips.append("Phong ấn mục tiêu nguy hiểm nhất đêm đó — một mình bạn có thể vô hiệu hóa cả chiến lược đối phương.")

    # Unlock / free / release bind
    if any(k in desc_lower for k in ("giải phóng", "mở khóa", "tháo phong ấn", "thả tự do")):
        tips.append("Giải phóng đúng đồng minh vào đúng thời điểm — đôi khi phá thế bế tắc quan trọng hơn tấn công.")

    # Auto win condition / instant victory
    if any(k in desc_lower for k in ("thắng ngay lập tức", "chiến thắng tức thì", "kết thúc trận")):
        tips.append("Điều kiện thắng tức thì rất hiếm — nhưng khi gần đạt được, đừng để ai nhận ra bạn đang ở đó.")

    # Leader / commander / head of faction
    if any(k in desc_lower for k in ("chỉ huy", "thủ lĩnh", "đứng đầu phe", "lãnh đạo")):
        tips.append("Thủ lĩnh là mục tiêu ưu tiên của kẻ địch — hãy hành động thận trọng hơn bất kỳ ai.")

    # Berserker / rage / uncontrollable fury
    if any(k in desc_lower for k in ("bạo loạn", "điên cuồng", "mất kiểm soát", "cuồng nộ")):
        tips.append("Sức mạnh khi cuồng nộ là hai lưỡi dao — hãy kích hoạt đúng lúc hoặc nó sẽ hại chính bạn.")

    # Sniper / precision kill / long range
    if any(k in desc_lower for k in ("bắn tỉa", "tầm xa", "chính xác tuyệt đối", "không thể né")):
        tips.append("Bắn tỉa từ xa không để lại dấu vết rõ ràng — nhưng hai lần sai mục tiêu là thất bại toàn trận.")

    # Escort / distract / seduce target
    if any(k in desc_lower for k in ("dẫn dụ", "cám dỗ", "phân tâm", "quyến rũ")):
        tips.append("Phân tâm đúng người vào đêm quyết định — ngăn họ hành động hiệu quả hơn một cú giết.")

    # Lookout / patrol / watch area
    if any(k in desc_lower for k in ("tuần tra", "gác đêm", "quan sát khu vực", "chốt gác")):
        tips.append("Tuần tra vị trí có nhiều lưu lượng di chuyển nhất — thông tin về ai thăm ai rất có giá trị.")

    # Forger / fake evidence / fabricate
    if any(k in desc_lower for k in ("làm giả", "giả mạo bằng chứng", "tạo bằng chứng", "ngụy tạo")):
        tips.append("Bằng chứng giả mạo hiệu quả nhất khi nhắm vào người mà cả thị trấn đang nghi ngờ.")

    # Duel / 1v1 / challenge to fight
    if any(k in desc_lower for k in ("đấu tay đôi", "thách đấu", "1 đối 1", "đọ sức")):
        tips.append("Thách đấu kẻ bạn chắc chắn có thể thắng — đừng bao giờ mạo hiểm với ẩn số.")

    # Multiple lives / extra life / respawn
    if any(k in desc_lower for k in ("thêm mạng", "mạng dự phòng", "sống lại lần hai", "không chết lần đầu")):
        tips.append("Mạng dự phòng không có nghĩa là bất tử — hãy sử dụng cơ hội thứ hai khôn ngoan hơn lần đầu.")

    # Amnesia / forget role / memory loss
    if any(k in desc_lower for k in ("mất trí nhớ", "quên đi", "không nhớ", "xóa ký ức")):
        tips.append("Quên đi vai trò cũ là cơ hội — hãy quan sát kỹ bối cảnh để chọn vai trò mới phù hợp nhất.")

    # Drain power / steal ability
    if any(k in desc_lower for k in ("hút năng lượng", "đánh cắp kỹ năng", "lấy đi khả năng")):
        tips.append("Hút năng lượng mục tiêu mạnh nhất — kép mang lại cho bạn quyền năng và đồng thời làm yếu đối thủ.")

    # Transform / evolve / final form
    if any(k in desc_lower for k in ("biến đổi", "tiến hóa", "hình thức cuối", "lột xác")):
        tips.append("Biến đổi hoàn toàn thay đổi cách mọi người nhìn nhận bạn — hãy tận dụng sự bất ngờ đó.")

    # Day action / active during daytime
    if any(k in desc_lower for k in ("hành động ban ngày", "hoạt động ngày", "trong giai đoạn ngày")):
        tips.append("Hành động ban ngày dễ bị quan sát hơn — hãy che giấu ý định bằng lý do hợp lý.")

    # Phase advantage / gains power at certain phase
    if any(k in desc_lower for k in ("giai đoạn đầu", "giai đoạn cuối", "đêm đầu tiên", "đêm thứ")):
        tips.append("Nắm rõ giai đoạn bạn mạnh nhất — tập trung toàn lực vào thời điểm đó để tạo bước ngoặt.")

    # Summon / call helper / invoke ally
    if any(k in desc_lower for k in ("triệu hồi", "gọi đến", "kêu gọi", "mang tới")):
        tips.append("Triệu hồi đồng minh vào thời điểm thị trấn đang chia rẽ nhất — tác động sẽ được nhân lên gấp bội.")

    # Echo / repeat last action
    if any(k in desc_lower for k in ("lặp lại", "tiếp tục hành động", "sao lại hành động", "lặp lại đêm trước")):
        tips.append("Lặp lại hành động thành công nhất bạn quan sát — đừng phát minh lại bánh xe khi có sẵn công thức chiến thắng.")

    # Alliance / form pact / team up
    if any(k in desc_lower for k in ("liên minh", "kết minh", "hợp tác tạm thời", "giao kèo")):
        tips.append("Liên minh tạm thời có thể là bước đệm — nhưng hãy biết chính xác khi nào cần phá vỡ nó.")

    # Rival / nemesis / opposite counterpart
    if any(k in desc_lower for k in ("đối thủ không đội trời chung", "nemesis", "kẻ thù không thể hòa giải")):
        tips.append("Biết rõ đối thủ của mình là ai — loại bỏ họ trước khi họ tìm ra bạn là ai.")

    # Final judgment / deliver verdict
    if any(k in desc_lower for k in ("phán xét cuối cùng", "lời phán quyết", "tuyên án")):
        tips.append("Phán xét có trọng lượng nhất khi được đưa ra sau nhiều bằng chứng tích lũy — đừng phán xét vội vàng.")

    # Vote reform / change voting rules
    if any(k in desc_lower for k in ("thay đổi luật bầu", "cải cách bỏ phiếu", "quy tắc mới")):
        tips.append("Thay đổi luật bầu phiếu khi bạn đang ở thế bất lợi — đảo ngược cuộc chơi từ bên trong.")

    # Bribe / corruption / buy loyalty
    if any(k in desc_lower for k in ("hối lộ", "mua chuộc", "tham nhũng", "đổi chác")):
        tips.append("Mua chuộc người có ảnh hưởng lớn nhất — một đồng minh được mua bằng lợi ích thường đáng tin hơn ta nghĩ.")

    # Phantom / untargetable form
    if any(k in desc_lower for k in ("hình thức ảo", "không thể bị nhắm", "vô hình", "xuyên không")):
        tips.append("Khi ở trạng thái vô hình — vẫn hành động bình thường vì kẻ địch không thể phản ứng kịp.")

    # Blind / disorient / confuse vision
    if any(k in desc_lower for k in ("làm mù", "mù quáng", "mất định hướng", "không nhìn thấy")):
        tips.append("Làm mù kẻ điều tra trong đêm quan trọng nhất — thông tin sai còn tệ hơn không có thông tin.")

    # Hunt / chase / pursue target
    if any(k in desc_lower for k in ("săn đuổi", "truy đuổi", "đuổi theo")):
        tips.append("Săn đuổi liên tục một mục tiêu có thể làm lộ danh tính bạn — hãy thay đổi mục tiêu đôi khi.")

    # Backstab / betray ally
    if any(k in desc_lower for k in ("đâm sau lưng", "phản bội đồng minh", "bội phản")):
        tips.append("Phản bội đúng lúc có thể giúp bạn thắng — nhưng chỉ có một cơ hội duy nhất, đừng hành động quá sớm.")

    # Execute order / carry out assassination
    if any(k in desc_lower for k in ("thực thi lệnh", "thực hiện ám sát", "tuân lệnh giết")):
        tips.append("Thực thi lệnh hiệu quả nhất khi không ai nghi ngờ bạn — giữ bình tĩnh tuyệt đối trước công chúng.")

    # Cleanse curse / remove negative status
    if any(k in desc_lower for k in ("xóa lời nguyền", "loại trừ hiệu ứng âm", "thoát khỏi trạng thái xấu")):
        tips.append("Làm sạch trạng thái xấu càng sớm càng tốt — để lâu sẽ ảnh hưởng đến các đêm tiếp theo.")

    # Charge / rush / burst attack
    if any(k in desc_lower for k in ("돌진", "lao vào", "tấn công tốc biến", "xông thẳng")):
        tips.append("Tấn công tốc biến phá vỡ thế phòng thủ — nhưng chỉ mạnh khi tung ra vào đúng đêm quyết định.")

    # Sneak attack / ambush bonus damage
    if any(k in desc_lower for k in ("tập kích", "ra tay bất ngờ", "đánh lén", "ra đòn từ phía sau")):
        tips.append("Tập kích hiệu quả nhất vào người vừa hành động xong — họ không còn sức phòng thủ.")

    # Predict opponent action / counter plan
    if any(k in desc_lower for k in ("đọc trước hành động", "dự đoán đối thủ", "biết trước kế hoạch")):
        tips.append("Đọc được hành động đối thủ là lợi thế chiến lược — hãy hành động ngược lại để phá vỡ kế hoạch của họ.")

    # Signal / beacon / warn allies
    if any(k in desc_lower for k in ("tín hiệu", "phát tín hiệu", "cảnh báo đồng minh", "truyền tin")):
        tips.append("Tín hiệu cảnh báo sớm giúp đồng đội chuẩn bị — nhưng tín hiệu sai còn nguy hiểm hơn im lặng.")

    # Messenger / relay information / courier
    if any(k in desc_lower for k in ("đưa tin", "truyền đạt", "liên lạc viên", "mang thông điệp")):
        tips.append("Thông tin qua trung gian dễ bị bóp méo — hãy chắc chắn nội dung không bị thay đổi trên đường truyền.")

    # False trail / plant fake clue
    if any(k in desc_lower for k in ("dấu vết giả", "bằng chứng giả tạo", "đánh lạc hướng điều tra")):
        tips.append("Dấu vết giả hiệu quả nhất khi nhắm vào người vô tội — nhưng hãy chuẩn bị giải thích nếu bị phanh phui.")

    # Compass / locate / pinpoint player
    if any(k in desc_lower for k in ("xác định vị trí", "tìm kiếm", "định vị")):
        tips.append("Xác định vị trí mục tiêu trước khi hành động — không bao giờ tấn công mà không biết bạn đang nhắm vào ai.")

    # Coordinate strategy / team plan
    if any(k in desc_lower for k in ("phối hợp chiến lược", "lên kế hoạch cùng nhau", "hành động đồng bộ")):
        tips.append("Hành động đồng bộ với đồng đội tạo ra áp lực không thể cưỡng lại — lên kế hoạch từ sớm.")

    # Vote immunity / protect from vote out
    if any(k in desc_lower for k in ("miễn trừ bỏ phiếu", "không thể bị trục xuất", "bất khả xâm phạm ban ngày")):
        tips.append("Miễn trừ bỏ phiếu là lá chắn ban ngày — hãy sử dụng sự an toàn đó để phát ngôn táo bạo hơn.")

    # Anonymous vote / secret ballot
    if any(k in desc_lower for k in ("bỏ phiếu ẩn danh", "bỏ phiếu bí mật", "phiếu không tên")):
        tips.append("Phiếu ẩn danh loại bỏ áp lực xã hội — hãy bỏ phiếu theo lý trí chứ không phải theo đám đông.")

    # Track win condition / monitor victory
    if any(k in desc_lower for k in ("theo dõi điều kiện thắng", "tiến độ chiến thắng", "kiểm tra mục tiêu")):
        tips.append("Luôn theo dõi tiến độ điều kiện thắng — đừng để mải chiến thuật mà quên mất đích đến.")

    # Forced reveal / expose role to all
    if any(k in desc_lower for k in ("buộc lộ diện", "ép tiết lộ vai trò", "phơi bày công khai")):
        tips.append("Ép lộ diện đối thủ mạnh nhất vào giai đoạn giữa trận — thông tin đó sẽ quyết định cán cân quyền lực.")

    # Fake claim / false identity presentation
    if any(k in desc_lower for k in ("khai gian", "tự xưng sai", "nhận vai không phải của mình")):
        tips.append("Khai giả một vai trò quen thuộc với thị trấn — nhưng phải thuộc bài chi tiết để không bị vặn.")

    # Power surge / temporary massive boost
    if any(k in desc_lower for k in ("bùng phát sức mạnh", "tăng vọt", "sức mạnh tạm thời")):
        tips.append("Bùng phát sức mạnh mạnh nhất khi tung ra bất ngờ — đừng báo hiệu trước bằng hành vi khác thường.")

    # Last resort / desperation ability
    if any(k in desc_lower for k in ("chiêu cuối", "khi gần chết", "tuyệt chiêu", "hết đường lui")):
        tips.append("Chiêu cuối thường không thể bị cản — nhưng nó chỉ có ý nghĩa nếu bạn còn đủ đồng minh để thắng.")

    # Passive immunity / auto natural defense
    if any(k in desc_lower for k in ("kháng cự tự nhiên", "miễn nhiễm bẩm sinh", "tự động phòng thủ")):
        tips.append("Miễn nhiễm bẩm sinh không che giấu được — đối thủ sẽ biết và chuyển sang chiến thuật khác.")

    # Fake result / mislead investigation
    if any(k in desc_lower for k in ("kết quả giả", "thay đổi kết quả điều tra", "đánh lừa thám tử")):
        tips.append("Kết quả điều tra giả mạo là vũ khí tâm lý mạnh nhất — dùng nó để đẩy thám tử vào con đường sai.")

    # Duplicate / spawn another copy of effect
    if any(k in desc_lower for k in ("nhân đôi hiệu ứng", "sao chép kỹ năng", "phát tán sang người khác")):
        tips.append("Nhân đôi hiệu ứng mạnh nhất bạn quan sát được — nhưng chỉ khi mục tiêu thứ hai cũng có giá trị cao.")

    # Recruit secretly / hidden membership
    if any(k in desc_lower for k in ("kết nạp bí mật", "chiêu dụ ngầm", "tuyển mộ không ai hay")):
        tips.append("Kết nạp thành viên mới trong bóng tối — kẻ địch không thể đối phó với mối đe dọa mà họ không nhìn thấy.")

    # Silent kill / no death announcement
    if any(k in desc_lower for k in ("giết trong im lặng", "cái chết không thông báo", "xóa dấu vết cái chết")):
        tips.append("Giết không thông báo gieo hoang mang — nhưng đừng lạm dụng kẻo thị trấn nhận ra mô hình.")

    # Daytime kill / attack during day phase
    if any(k in desc_lower for k in ("giết ban ngày", "tấn công trong ngày", "hành động ngày")):
        tips.append("Giết ban ngày là cực kỳ rủi ro — hãy chắc chắn 100% trước khi thực hiện vì mọi người đều là nhân chứng.")

    # Counter ability / react to incoming action
    if any(k in desc_lower for k in ("phản ứng", "đáp trả", "hành động đối trọng", "phản chiêu")):
        tips.append("Khả năng phản ứng mạnh hơn khi đối thủ không biết bạn có nó — đừng dùng quá sớm để lộ bài.")

    # Endgame trigger / activate win condition
    if any(k in desc_lower for k in ("kích hoạt điều kiện thắng", "kết thúc trò chơi", "mở màn kết thúc")):
        tips.append("Kích hoạt điều kiện kết thúc khi bạn ở thế mạnh nhất — không phải khi bạn đã đủ điểm.")

    # Faction leader / head / supreme
    if any(k in desc_lower for k in ("đầu não phe", "cầm đầu", "người dẫn dắt phe")):
        tips.append("Mất đầu não phe là thất bại chắc chắn — hãy đảm bảo an toàn bản thân trên hết mọi thứ.")

    # Lone wolf / no team / absolute solo
    if any(k in desc_lower for k in ("sói đơn độc", "một mình chiến đấu", "không cần đồng đội")):
        tips.append("Cô đơn là sức mạnh của bạn — đừng bị cám dỗ liên minh vì nó sẽ làm lộ mục tiêu thật sự.")

    # Power share / give own ability
    if any(k in desc_lower for k in ("chia sẻ kỹ năng", "trao quyền năng", "chuyển giao khả năng")):
        tips.append("Chia sẻ kỹ năng với đồng minh đáng tin cậy nhất — nhưng hãy chắc chắn họ biết cách sử dụng nó đúng lúc.")

    # Duality / two modes / dual nature
    if any(k in desc_lower for k in ("hai mặt tính cách", "bản chất kép", "chuyển đổi hình thái")):
        tips.append("Chuyển đổi giữa hai hình thái vào đúng thời điểm — sự linh hoạt là lợi thế mà đối thủ không thể đọc được.")

    # Passive trigger / auto activate on condition
    if any(k in desc_lower for k in ("kích hoạt tự động khi", "tự động phản ứng", "tự kích hoạt")):
        tips.append("Kỹ năng tự động mạnh nhất khi đối thủ không nhận ra điều kiện kích hoạt của nó.")

    # Confront / face off openly
    if any(k in desc_lower for k in ("đối mặt công khai", "thách thức trực tiếp", "ra mặt đương đầu")):
        tips.append("Đối mặt công khai tạo uy tín — nhưng chỉ nên làm khi bạn chắc chắn đám đông đứng về phía mình.")

    # Shadow copy / mirror dark actions
    if any(k in desc_lower for k in ("phản chiếu hắc ám", "bản sao bóng tối", "nhân đôi ác ý")):
        tips.append("Nhân bản hành động tối tăm nhất của kẻ địch và trả lại họ gấp đôi — đây là hình phạt hoàn hảo.")

    # Reverse / invert effect
    if any(k in desc_lower for k in ("đảo ngược hiệu ứng", "lật ngược tác dụng", "đổi chiều")):
        tips.append("Đảo ngược hiệu ứng mạnh nhất đang chống lại phe bạn — biến bất lợi thành cơ hội.")

    # Area control / zone domination
    if any(k in desc_lower for k in ("kiểm soát khu vực", "chiếm lĩnh vùng", "thống trị địa bàn")):
        tips.append("Kiểm soát khu vực trung tâm trước — thông tin về ai đi qua sẽ cực kỳ giá trị.")

    # Chain / consecutive actions
    if any(k in desc_lower for k in ("chuỗi hành động", "liên hoàn", "kết hợp liên tiếp")):
        tips.append("Chuỗi hành động liên tiếp cực kỳ mạnh — nhưng một mắt xích bị phá sẽ phá vỡ toàn bộ kế hoạch.")

    # Swap ability / exchange power with target
    if any(k in desc_lower for k in ("trao đổi kỹ năng", "đổi khả năng", "hoán đổi quyền năng")):
        tips.append("Hoán đổi kỹ năng với đối thủ nguy hiểm nhất — vừa làm họ yếu đi vừa làm bạn mạnh lên.")

    # Mystery identity / role unknown even to self
    if any(k in desc_lower for k in ("không rõ vai trò", "danh tính bí ẩn", "chưa biết mình là ai")):
        tips.append("Không biết vai trò của chính mình nghĩa là phải quan sát cẩn thận hơn để tự khám phá sức mạnh thật sự.")

    # Risk-reward mechanic / high stakes gamble
    if any(k in desc_lower for k in ("đánh cược", "rủi ro cao", "phần thưởng lớn", "đặt cược")):
        tips.append("Đặt cược lớn chỉ có nghĩa khi tỷ lệ thành công cao — đừng bao giờ đánh cược khi bạn chưa chuẩn bị kỹ.")

    # Team coordination required / joint effort
    if any(k in desc_lower for k in ("cần phối hợp", "đòi hỏi đồng đội", "không thể một mình")):
        tips.append("Phụ thuộc vào đồng đội nghĩa là cần giao tiếp liên tục — im lặng quá lâu có thể khiến kế hoạch sụp đổ.")

    # Eavesdrop / intercept communication
    if any(k in desc_lower for k in ("nghe trộm", "chặn tin nhắn", "đánh cắp thông tin liên lạc")):
        tips.append("Nghe trộm cho bạn bức tranh toàn cảnh — nhưng đừng phản ứng ngay lập tức vì sẽ lộ ra bạn đã nghe.")

    # Guard post / stationed / fixed defense
    if any(k in desc_lower for k in ("chốt chặn", "cố thủ", "đứng vị trí", "bất động phòng thủ")):
        tips.append("Cố thủ một vị trí quan trọng cho phép bạn kiểm soát luồng thông tin đi qua đó.")

    # Hidden condition / secret trigger mechanism
    if any(k in desc_lower for k in ("điều kiện ẩn", "kích hoạt bí mật", "cơ chế không ai biết")):
        tips.append("Điều kiện kích hoạt ẩn là vũ khí tâm lý — kẻ địch không thể ngăn điều họ không biết tồn tại.")

    # Final gambit / all or nothing move
    if any(k in desc_lower for k in ("tất tay", "toàn lực cuối", "không còn gì để mất")):
        tips.append("Tất tay chỉ khi không còn lựa chọn nào khác — nhưng hãy thực hiện nó với sự quyết tâm tuyệt đối.")

    # Overload / overwhelm / flood with actions
    if any(k in desc_lower for k in ("áp đảo", "dồn dập", "tấn công liên tục")):
        tips.append("Áp đảo đối thủ bằng hành động dồn dập — nhưng hãy chắc chắn bạn có đủ nguồn lực duy trì đến cuối.")

    # Sanctuary / safe zone / protected area
    if any(k in desc_lower for k in ("thánh địa", "vùng an toàn", "khu bất khả xâm phạm")):
        tips.append("Vùng an toàn bảo vệ đồng minh — nhưng hãy để đối thủ lãng phí hành động tấn công vào đó trước.")

    # Overwrite / replace existing effect
    if any(k in desc_lower for k in ("ghi đè", "thay thế hiệu ứng cũ", "xóa và thay")):
        tips.append("Ghi đè hiệu ứng có lợi của đối thủ bằng hiệu ứng bất lợi — phá vỡ thế cân bằng ngay tức khắc.")

    # Weaken vote / reduce vote power
    if any(k in desc_lower for k in ("giảm trọng lượng phiếu", "phiếu không có giá trị", "vô hiệu phiếu")):
        tips.append("Vô hiệu hóa phiếu bầu của người có ảnh hưởng lớn — đặc biệt hiệu quả vào ngày bầu phiếu quyết định.")

    # Inherit / receive dead player's ability
    if any(k in desc_lower for k in ("thừa kế", "nhận lấy kỹ năng người chết", "kế thừa vai trò")):
        tips.append("Thừa kế kỹ năng mạnh nhất có thể — hãy lên kế hoạch từ trước ai là người bạn muốn kế thừa.")

    # Intimidate / threaten to change behavior
    if any(k in desc_lower for k in ("uy hiếp", "đe nẹt", "khiến sợ hãi", "răn đe")):
        tips.append("Uy hiếp đúng mục tiêu có thể thay đổi kế hoạch của họ mà không cần hành động thực sự.")

    # Undetectable / bypass investigation
    if any(k in desc_lower for k in ("không thể bị phát hiện", "vượt qua điều tra", "miễn nhiễm thám tử")):
        tips.append("Không thể bị phát hiện không có nghĩa là vô hình — hành vi của bạn vẫn có thể bị đọc vị.")

    # Guarantee kill / bypass all protection
    if any(k in desc_lower for k in ("xuyên giáp", "vượt qua bảo vệ", "giết chắc chắn")):
        tips.append("Đòn xuyên giáp quý giá nhất khi dùng vào mục tiêu được bảo vệ bởi nhiều người — đừng lãng phí.")

    # Stall / delay / waste opponent's time
    if any(k in desc_lower for k in ("câu giờ", "kéo dài thời gian", "làm chậm trễ")):
        tips.append("Câu giờ hiệu quả khi phe bạn cần thêm đêm để hoàn thành mục tiêu — nhưng đừng làm lộ ý định.")

    # Stealth mode / reduce own visibility
    if any(k in desc_lower for k in ("giảm sự hiện diện", "hạ thấp profile", "ít lộ mặt hơn")):
        tips.append("Giữ profile thấp trong giai đoạn đầu — những kẻ ồn ào nhất thường là người chết trước.")

    # Absorb / negate incoming damage or effect
    if any(k in desc_lower for k in ("hấp thụ", "vô hiệu hóa đòn đánh", "triệt tiêu tác động")):
        tips.append("Hấp thụ đòn tấn công và để lộ sức mạnh của bạn — nhưng chỉ làm điều này một lần để giữ yếu tố bất ngờ.")

    # Conditional ability / only works under specific circumstances
    if any(k in desc_lower for k in ("chỉ khi", "điều kiện tiên quyết", "cần thỏa mãn điều kiện")):
        tips.append("Hiểu rõ điều kiện kích hoạt kỹ năng của bạn — chuẩn bị tạo ra điều kiện đó nếu nó chưa xảy ra tự nhiên.")

    # Collective punishment / punish group
    if any(k in desc_lower for k in ("trừng phạt tập thể", "ảnh hưởng cả nhóm", "liên đới")):
        tips.append("Trừng phạt tập thể gây chia rẽ nội bộ phe đối thủ — đây là chiến thuật gây hoang mang tốt nhất.")

    # Reinforce / strengthen own position
    if any(k in desc_lower for k in ("củng cố vị thế", "gia tăng ảnh hưởng", "mở rộng quyền lực")):
        tips.append("Củng cố vị thế trước khi tấn công — một nền tảng vững chắc cho phép bạn hành động táo bạo hơn.")

    # Two targets same night / hit multiple
    if any(k in desc_lower for k in ("hai mục tiêu một đêm", "nhắm hai người", "tấn công song song")):
        tips.append("Tấn công hai mục tiêu cùng đêm chia sẻ rủi ro nhưng cũng chia sẻ hiệu quả — hãy chọn cặp mục tiêu bổ trợ nhau.")

    # Disrupt / break coordination
    if any(k in desc_lower for k in ("phá vỡ phối hợp", "chia cắt liên lạc", "gây rối hàng ngũ")):
        tips.append("Phá vỡ sự phối hợp của phe đối thủ hiệu quả hơn bất kỳ cú giết đơn lẻ nào — hãy nhắm vào cầu nối thông tin.")

    # Test target / probe without committing
    if any(k in desc_lower for k in ("thăm dò", "kiểm tra phản ứng", "đánh giá mục tiêu")):
        tips.append("Thăm dò trước khi toàn tâm tấn công — phản ứng của mục tiêu sẽ tiết lộ rất nhiều về vai trò thật sự của họ.")

    # Exploit confusion / use chaos to advance
    if any(k in desc_lower for k in ("lợi dụng hỗn loạn", "khai thác sự nhầm lẫn", "thừa nước đục thả câu")):
        tips.append("Hỗn loạn là cơ hội tốt nhất để hành động mà không bị để ý — hãy luôn chuẩn bị sẵn kế hoạch cho kịch bản này.")

    # ── Meta-based tips ─────────────────────────────────────────

    if meta.get("requires"):
        tips.append(f"Chỉ xuất hiện khi có **{meta['requires']}** trong trận — hãy bảo vệ nhau.")

    if meta.get("max_count", 1) > 1:
        tips.append(
            f"Có thể xuất hiện tối đa **{meta['max_count']}** lần — phối hợp để tăng hiệu quả tổng thể."
        )

    if meta.get("min_players", 5) >= 15:
        tips.append(
            f"Chỉ xuất hiện trong lobby lớn (≥{meta['min_players']} người) — "
            "tác động của bạn sẽ rất lớn."
        )

    # ── Faction fallback ────────────────────────────────────────

    if not tips:
        if faction == "Survivors":
            tips.append("Thu thập thông tin, phối hợp chặt chẽ với phe Survivors.")
        elif faction == "Anomalies":
            tips.append("Ẩn danh và tiêu diệt các vai trò nguy hiểm trước khi bị phát hiện.")
        else:
            tips.append("Hành động độc lập — cả hai phe đều là mối đe dọa cho bạn.")

    return "\n".join(f"• {t}" for t in tips[:4])


def _build_role_catalogue(roles_base_dir: Optional[str] = None) -> dict[str, dict]:
    """
    Scan roles/survivors, roles/anomalies, roles/unknown using Python AST.
    Returns {role_name: {faction, ability, tips}}.

    'ability' = the class-level `description` attribute from the role file.
    'tips'    = derived by _derive_tips() based on description content.

    No discord import required — pure AST traversal.
    """
    if roles_base_dir is None:
        # cogs/role_preview.py  →  go up one level to reach roles/
        here = os.path.dirname(os.path.abspath(__file__))
        roles_base_dir = os.path.join(here, "..", "roles")

    catalogue: dict[str, dict] = {}
    all_meta = {**SURVIVORS_META, **ANOMALIES_META, **UNKNOWN_META}

    folder_default_faction = {
        "survivors": "Survivors",
        "anomalies": "Anomalies",
        "unknown":   "Unknown Entities",
        "event":     "Event Roles",
    }

    for folder, default_faction in folder_default_faction.items():
        folder_path = os.path.join(roles_base_dir, folder)
        if not os.path.isdir(folder_path):
            print(f"[role_preview] ⚠ Folder not found: {folder_path}")
            continue

        for filepath in sorted(glob.glob(os.path.join(folder_path, "*.py"))):
            filename = os.path.basename(filepath)
            if filename.startswith("_"):
                continue

            try:
                src  = open(filepath, encoding="utf-8").read()
                tree = ast.parse(src)
            except Exception as exc:
                print(f"[role_preview] ⚠ AST error {filename}: {exc}")
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                attrs: dict[str, str] = {}
                for item in node.body:
                    if not isinstance(item, ast.Assign):
                        continue
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id in (
                            "name", "team", "faction", "description", "dm_message"
                        ):
                            try:
                                attrs[target.id] = ast.literal_eval(item.value)
                            except Exception:
                                pass

                role_name = attrs.get("name", "").strip()
                if not role_name or role_name == "Base":
                    continue

                # Canonical faction label
                raw_team = attrs.get("team") or attrs.get("faction") or default_faction
                if "survivor" in raw_team.lower():
                    faction = "Survivors"
                elif "anomal" in raw_team.lower():
                    faction = "Anomalies"
                else:
                    faction = "Unknown Entities"

                # Ability text: prefer description, fall back to dm_message summary
                description = attrs.get("description", "").strip()
                if not description:
                    dm = attrs.get("dm_message", "")
                    if dm:
                        lines = [
                            ln.strip() for ln in dm.split("\n")
                            if ln.strip()
                            and not ln.strip().startswith("**")
                            and not any(ln.strip().startswith(e) for e in ("🔥", "⏳", "🚫", "📝"))
                        ]
                        description = " ".join(lines[:2])

                meta   = all_meta.get(role_name, {})
                ability = description or "Thông tin đang được cập nhật."
                tips    = _derive_tips(role_name, faction, description, meta)

                # First-encountered class wins for each role name
                if role_name not in catalogue:
                    catalogue[role_name] = {
                        "faction": faction,
                        "ability": ability,
                        "tips":    tips,
                    }

    print(f"[role_preview] ✔ Hệ Thống Role : {len(catalogue)} vai trò được tải trong thư mục roles/ .")
    return catalogue


# Built once at module import — available to all views
# Guild-level custom role list overrides for the next game.
# { guild_id: {"Survivors": [("RoleName", count), ...], "Anomalies": [...], "Unknown Entities": [...]} }
# Tự reset sau khi Distributor chạy xong (xem app.py - launch_game).
_pending_role_overrides: dict[str, dict[str, list[tuple[str, int]]]] = {}

_ROLE_CATALOGUE: dict[str, dict] = _build_role_catalogue()


# ══════════════════════════════════════════════════════════════════
# FACTION CONFIGURATION
# ══════════════════════════════════════════════════════════════════

def _get_event_role_names() -> list[str]:
    """Lấy danh sách tên event role từ folder roles/event/ qua AST."""
    here = os.path.dirname(os.path.abspath(__file__))
    event_dir = os.path.join(here, "..", "roles", "event")
    names = []
    if not os.path.isdir(event_dir):
        return names
    for filepath in sorted(glob.glob(os.path.join(event_dir, "*.py"))):
        filename = os.path.basename(filepath)
        if filename.startswith("_"):
            continue
        try:
            src  = open(filepath, encoding="utf-8").read()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for item in node.body:
                    if not isinstance(item, ast.Assign):
                        continue
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "name":
                            try:
                                val = ast.literal_eval(item.value)
                                if val and val != "Base":
                                    names.append(val)
                            except Exception:
                                pass
        except Exception:
            pass
    return names


_FACTION_ROLES: dict[str, list[str]] = {
    "Survivors":        list(SURVIVORS_META.keys()),
    "Anomalies":        list(ANOMALIES_META.keys()),
    "Unknown Entities": list(UNKNOWN_META.keys()),
    "Event Roles":      _get_event_role_names(),
}

_FACTION_EMOJI: dict[str, str] = {
    "Survivors":        "👥",
    "Anomalies":        "🐺",
    "Unknown Entities": "❓",
    "Event Roles":      "🎪",
}

_FACTION_COLOR: dict[str, discord.Color] = {
    "Survivors":        discord.Color.blue(),
    "Anomalies":        discord.Color.red(),
    "Unknown Entities": discord.Color.purple(),
    "Event Roles":      discord.Color.gold(),
}

_FACTION_SELECT_VALUES: dict[str, str] = {
    "Survivors":        "survivors",
    "Anomalies":        "anomalies",
    "Unknown Entities": "unknown",
    "Event Roles":      "event",
}

_VALUE_TO_FACTION: dict[str, str] = {v: k for k, v in _FACTION_SELECT_VALUES.items()}


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _get_voice_members(interaction: discord.Interaction) -> list[discord.Member]:
    """Return non-bot members in the interaction user's current voice channel."""
    member = interaction.guild.get_member(interaction.user.id)
    if member and member.voice and member.voice.channel:
        return [m for m in member.voice.channel.members if not m.bot]
    return []


def _run_preview_distribution(
    player_count: int,
    role_classes: list,
    members: list | None = None,
) -> tuple[list[str], dict]:
    """
    Chạy distribute thật với real members (hoặc fake nếu không có).
    Trả về (role_names, role_map) để lưu vào _pending_role_maps.
    role_map: {member_id: role_obj} — giống hệt game thật sẽ dùng.
    """
    class _FakeMember:
        def __init__(self, mid: int):
            self.id   = mid
            self.name = f"Player{mid}"
            self.display_name = self.name

    real_members = members if members else [_FakeMember(i) for i in range(player_count)]

    distributor = RoleDistributor(role_classes)
    role_map    = distributor.distribute(real_members)

    role_names = [role.name for role in role_map.values()]
    return role_names, role_map


def _build_preview_embed(role_names: list[str], player_count: int) -> discord.Embed:
    """Build 'roles that WILL be distributed' embed — grouped by team with counts."""
    name_to_team: dict[str, str] = {}
    for n in SURVIVORS_META:
        name_to_team[n] = "Survivors"
    for n in ANOMALIES_META:
        name_to_team[n] = "Anomalies"
    for n in UNKNOWN_META:
        name_to_team[n] = "Unknown Entities"

    by_team: dict[str, Counter] = {
        "Survivors":        Counter(),
        "Anomalies":        Counter(),
        "Unknown Entities": Counter(),
    }
    for rn in role_names:
        by_team[name_to_team.get(rn, "Unknown Entities")][rn] += 1

    total = len(role_names)
    embed = discord.Embed(title="🎭 VAI TRÒ SẼ ĐƯỢC PHÂN BỐ", color=discord.Color.blurple())

    for team_key, field_label in (
        ("Survivors",        "👥 Những Người Sống Sót"),
        ("Anomalies",        "🐺 Dị Thể"),
        ("Unknown Entities", "❓ Thực Thể Không Xác Định"),
    ):
        cnt = by_team[team_key]
        if not cnt:
            continue
        parts      = [f"{rn} x{c}" if c > 1 else rn for rn, c in sorted(cnt.items())]
        team_total = sum(cnt.values())
        pct        = int(team_total / total * 100) if total else 0
        embed.add_field(
            name  = f"{field_label} — {team_total} ({pct}%)",
            value = "\n".join(f"• {p}" for p in parts),
            inline = False,
        )

    embed.set_footer(text=f"Số người chơi được phát hiện: {player_count}")
    return embed


def _build_role_info_embed(faction: str, page: int, roles: list[str]) -> discord.Embed:
    """Build the role info embed for Button 3 — one role per page."""
    if not roles:
        return discord.Embed(title="📖 Không có vai trò nào", color=discord.Color.greyple())

    role_name = roles[page]
    cat       = _ROLE_CATALOGUE.get(role_name, {})
    ability   = cat.get("ability") or "Thông tin đang được cập nhật."
    tips      = cat.get("tips")    or "Thông tin đang được cập nhật."

    meta_table = {
        "Survivors":        SURVIVORS_META,
        "Anomalies":        ANOMALIES_META,
        "Unknown Entities": UNKNOWN_META,
    }.get(faction, UNKNOWN_META)

    # Event role: đọc thẳng từ EVENT_META trong role_distributor
    if faction == "Event Roles":
        meta = EVENT_META.get(role_name, {"min_players": 5, "max_count": 1, "core": False, "event": True})
    else:
        meta = meta_table.get(role_name, {})
    color = _FACTION_COLOR.get(faction, discord.Color.blurple())
    emoji = _FACTION_EMOJI.get(faction, "❓")

    embed = discord.Embed(title=f"{emoji} {role_name}", color=color)
    embed.add_field(name="🏳️ Phe",     value=faction,                                          inline=True)
    embed.add_field(name="🎖️ Loại",    value="⭐ Cốt lõi" if meta.get("core") else "💎 Đặc biệt", inline=True)
    embed.add_field(name="👤 Tối thiểu", value=f"{meta.get('min_players', '?')} người",          inline=True)
    embed.add_field(name="⚡ Khả năng", value=ability, inline=False)
    embed.add_field(name="💡 Mẹo",      value=tips,    inline=False)

    if meta.get("requires"):
        embed.add_field(
            name  = "🔗 Yêu cầu",
            value = f"Phải có **{meta['requires']}** trong trận",
            inline = False,
        )

    embed.set_footer(text=f"Trang {page + 1} / {len(roles)}")
    return embed


def _build_event_embed() -> discord.Embed:
    """Hiển thị event role đang active, countdown, và toàn bộ pool."""
    try:
        from event_roles_loader import get_loader as _get_loader  # type: ignore[import]
        loader  = _get_loader()
        current = loader.get_current_role_name()
        pool    = loader.get_pool()
        queue   = loader.get_queue()
        secs    = loader.seconds_until_next_rotate()
    except Exception:
        current = None
        pool    = []
        queue   = []
        secs    = 0

    embed = discord.Embed(
        title       = "🎪 EVENT ROLE HIỆN TẠI",
        color       = discord.Color.gold(),
    )

    if not pool:
        embed.description = (
            "⚠️ Chưa có event role nào.\n"
            "Admin hãy thêm file `.py` vào thư mục `roles/event/` và restart bot."
        )
        return embed

    # ── Role đang active ──────────────────────────────────────────
    if current:
        cat     = _ROLE_CATALOGUE.get(current, {})
        faction = cat.get("faction", "Unknown")
        ability = cat.get("ability", "Thông tin đang được cập nhật.")
        color   = _FACTION_COLOR.get(faction, discord.Color.gold())
        embed.color = color
        embed.add_field(
            name  = f"✨ {current}",
            value = (
                f"🏳️ Phe: **{faction}**\n"
                f"⚡ {ability[:200]}{'...' if len(ability) > 200 else ''}"
            ),
            inline = False,
        )
    else:
        embed.add_field(name="✨ Đang active", value="Không có", inline=False)

    # ── Countdown ─────────────────────────────────────────────────
    hours, rem = divmod(secs, 3600)
    mins, s    = divmod(rem, 60)
    countdown_str = f"{hours}h {mins}m {s}s" if hours else f"{mins}m {s}s"
    embed.add_field(
        name  = "⏰ Đổi role sau",
        value = countdown_str,
        inline = True,
    )
    embed.add_field(
        name  = "📦 Pool",
        value = f"**{len(pool)}** role",
        inline = True,
    )
    embed.add_field(
        name  = "🔄 Hàng chờ",
        value = f"**{len(queue)}** role còn lại trong vòng này",
        inline = True,
    )

    # ── Danh sách toàn bộ pool ────────────────────────────────────
    # pool và queue là list[dict] — lấy "name" để hiển thị
    queue_names = {e["name"] if isinstance(e, dict) else e for e in queue}
    pool_lines  = []
    for entry in pool:
        rname = entry["name"] if isinstance(entry, dict) else entry
        if rname == current:
            pool_lines.append(f"▶️ **{rname}** *(đang active)*")
        elif rname not in queue_names:
            pool_lines.append(f"✅ ~~{rname}~~ *(đã xuất hiện vòng này)*")
        else:
            pool_lines.append(f"⏳ {rname}")

    embed.add_field(
        name  = "📋 Danh sách event role",
        value = "\n".join(pool_lines) or "Trống",
        inline = False,
    )

    embed.set_footer(text="Event role tự động rotate mỗi 1 giờ.")
    return embed


def _build_stats_embed() -> discord.Embed:
    """Build the role statistics embed for Button 2."""
    embed = discord.Embed(
        title       = "📊 THỐNG KÊ VAI TRÒ",
        description = "Tổng quan tất cả vai trò trong hệ thống.",
        color       = discord.Color.blurple(),
    )
    for meta, label, emoji in (
        (SURVIVORS_META, "Những Người Sống Sót", "👥"),
        (ANOMALIES_META, "Dị Thể",               "🐺"),
        (UNKNOWN_META,   "Thực Thể Không XĐ",    "❓"),
    ):
        total     = len(meta)
        core      = sum(1 for m in meta.values() if m.get("core"))
        min_p_avg = int(sum(m.get("min_players", 5) for m in meta.values()) / total) if total else 0
        embed.add_field(
            name  = f"{emoji} {label} ({total} vai trò)",
            value = (
                f"⭐ Cốt lõi: **{core}**\n"
                f"💎 Đặc biệt: **{total - core}**\n"
                f"👤 Min players TB: **{min_p_avg}**"
            ),
            inline = True,
        )
    embed.add_field(
        name  = "🎯 Tỷ lệ phân bổ mục tiêu",
        value = "👥 Survivors: **60%**\n🐺 Anomalies: **30%**\n❓ Unknown: **10%**",
        inline = False,
    )
    embed.set_footer(text=f"Dữ liệu vai trò: {len(_ROLE_CATALOGUE)} vai trò đã được tải từ hệ thống.")
    return embed


# ══════════════════════════════════════════════════════════════════
# VIEWS
# ══════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════
# ROLE EDITOR HELPERS
# ══════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════
# ROLE EDITOR
# ══════════════════════════════════════════════════════════════════

_EDITOR_FACTIONS = ["Survivors", "Anomalies", "Unknown Entities"]
_EDITOR_FACTION_EMOJI = {
    "Survivors":        "👥",
    "Anomalies":        "🐺",
    "Unknown Entities": "❓",
}

_ALL_META: dict[str, dict] = {
    **{k: {**v, "_faction": "Survivors"}        for k, v in SURVIVORS_META.items()},
    **{k: {**v, "_faction": "Anomalies"}        for k, v in ANOMALIES_META.items()},
    **{k: {**v, "_faction": "Unknown Entities"} for k, v in UNKNOWN_META.items()},
}


def _build_editor_overview_embed(guild_id: str, max_lobby: int) -> discord.Embed:
    override = _pending_role_overrides.get(guild_id, {})
    embed = discord.Embed(
        title="🛠 CHỈNH SỬA VAI TRÒ — Ván tiếp theo",
        color=discord.Color.orange(),
    )
    embed.set_footer(
        text=f"Lobby tối đa: {max_lobby} người  •  Danh sách tự reset sau khi ván kết thúc."
    )
    has_any = any(override.get(f) for f in _EDITOR_FACTIONS)
    if not has_any:
        embed.description = (
            "Chưa có danh sách tuỳ chỉnh.\n"
            "Chọn phe → chọn vai trò → chọn số lượng.\n\n"
            "⚠️ Khi bật tuỳ chỉnh, **Distributor** sẽ bị bỏ qua."
        )
        return embed

    lines: list[str] = []
    total = 0
    for faction in _EDITOR_FACTIONS:
        entries = override.get(faction, [])
        if not entries:
            continue
        lines.append(f"**{_EDITOR_FACTION_EMOJI[faction]} {faction}**")
        for name, count in entries:
            lines.append(f"  • {name}  ×{count}")
            total += count
    lines.append(f"\n📊 Tổng: **{total}** vai trò")
    embed.description = "\n".join(lines)
    return embed


def _editor_role_options(faction: str, max_lobby: int, guild_id: str) -> list[discord.SelectOption]:
    """Danh sách role đủ điều kiện cho phe, đánh dấu role đã thêm."""
    if faction == "Survivors":
        meta = SURVIVORS_META
    elif faction == "Anomalies":
        meta = ANOMALIES_META
    else:
        meta = UNKNOWN_META

    override  = _pending_role_overrides.get(guild_id, {})
    added_set = {name for name, _ in override.get(faction, [])}

    options: list[discord.SelectOption] = []
    for name, m in meta.items():
        if m.get("min_players", 5) > max_lobby:
            continue
        desc  = f"Tối thiểu {m.get('min_players',5)} người • Tối đa ×{m.get('max_count',1)}"
        emoji = "✅" if name in added_set else None
        options.append(discord.SelectOption(
            label=name, value=name, description=desc, emoji=emoji,
        ))
        if len(options) >= 25:
            break

    if not options:
        options = [discord.SelectOption(label="(không có vai trò phù hợp)", value="__none__")]
    return options


def _editor_qty_options(role_name: str) -> list[discord.SelectOption]:
    m         = _ALL_META.get(role_name, {})
    max_count = max(1, min(m.get("max_count", 1), 9))
    return [
        discord.SelectOption(label=f"×{i}", value=str(i),
                             description=f"Thêm {i} {role_name}")
        for i in range(1, max_count + 1)
    ]


class RoleEditorView(View):
    """
    View CỐ ĐỊNH — không dùng clear_items/rebuild.
    Tất cả Select/Button được tạo 1 lần trong __init__ với custom_id cố định.
    Cập nhật options bằng cách replace item trong self.children rồi edit_message.

    Cấu trúc:
      row 0 — _faction_sel  : chọn phe
      row 1 — _role_sel     : chọn role (options thay đổi theo phe)
      row 2 — _qty_sel      : chọn số lượng (options thay đổi theo role)
      row 3 — btn_remove, btn_clear
    """

    def __init__(self, bot: commands.Bot, guild_id: str, max_lobby: int = 20) -> None:
        super().__init__(timeout=600)
        self.bot          = bot
        self.guild_id     = guild_id
        self.max_lobby    = max_lobby
        self._faction     = "Survivors"
        self._pending_role: str | None = None

        # ── row 0: faction select ────────────────────────────────
        self._faction_sel = Select(
            custom_id   = "editor_faction",
            placeholder = "📂 Bước 1 — Chọn phe",
            options     = self._faction_options(),
            row         = 0,
        )
        self._faction_sel.callback = self._on_faction  # type: ignore[method-assign]

        # ── row 1: role select ───────────────────────────────────
        self._role_sel = Select(
            custom_id   = "editor_role",
            placeholder = "🎭 Bước 2 — Chọn vai trò",
            options     = _editor_role_options(self._faction, self.max_lobby, self.guild_id),
            row         = 1,
        )
        self._role_sel.callback = self._on_role  # type: ignore[method-assign]

        # ── row 2: qty select ────────────────────────────────────
        self._qty_sel = Select(
            custom_id   = "editor_qty",
            placeholder = "🔢 Bước 3 — Chọn số lượng",
            options     = [discord.SelectOption(label="(chọn vai trò trước)", value="__wait__")],
            disabled    = True,
            row         = 2,
        )
        self._qty_sel.callback = self._on_qty  # type: ignore[method-assign]

        # ── row 3: buttons ───────────────────────────────────────
        self._btn_remove = Button(
            custom_id = "editor_remove",
            label     = "⬅ Xoá cuối",
            style     = discord.ButtonStyle.secondary,
            row       = 3,
        )
        self._btn_remove.callback = self._on_remove  # type: ignore[method-assign]

        self._btn_clear = Button(
            custom_id = "editor_clear",
            label     = "🗑 Xoá tất cả",
            style     = discord.ButtonStyle.danger,
            row       = 3,
        )
        self._btn_clear.callback = self._on_clear  # type: ignore[method-assign]

        for item in (self._faction_sel, self._role_sel, self._qty_sel,
                     self._btn_remove, self._btn_clear):
            self.add_item(item)

    # ── helpers ──────────────────────────────────────────────────

    def _faction_options(self) -> list[discord.SelectOption]:
        return [
            discord.SelectOption(
                emoji   = _EDITOR_FACTION_EMOJI[f],
                label   = f"Chọn vai trò cho phe: {f}",
                value   = f,
                default = (f == self._faction),
            )
            for f in _EDITOR_FACTIONS
        ]

    def _refresh_selects(self) -> None:
        """Cập nhật options của các select IN-PLACE (không xoá item)."""
        # faction options — cập nhật default
        self._faction_sel.options = self._faction_options()

        # role options — theo phe mới
        self._role_sel.options     = _editor_role_options(self._faction, self.max_lobby, self.guild_id)
        self._role_sel.placeholder = f"🎭 Bước 2 — Chọn vai trò  [{_EDITOR_FACTION_EMOJI[self._faction]} {self._faction}]"
        self._role_sel.disabled    = False

        # qty options — chỉ enable khi đã chọn role
        if self._pending_role:
            self._qty_sel.options     = _editor_qty_options(self._pending_role)
            self._qty_sel.placeholder = f"🔢 Bước 3 — Số lượng cho: {self._pending_role}"
            self._qty_sel.disabled    = False
        else:
            self._qty_sel.options     = [discord.SelectOption(label="(chọn vai trò trước)", value="__wait__")]
            self._qty_sel.placeholder = "🔢 Bước 3 — Chọn số lượng"
            self._qty_sel.disabled    = True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    # ── callbacks ────────────────────────────────────────────────

    async def _on_faction(self, interaction: discord.Interaction) -> None:
        self._faction      = self._faction_sel.values[0]
        self._pending_role = None
        self._refresh_selects()
        await interaction.response.edit_message(
            embed=_build_editor_overview_embed(self.guild_id, self.max_lobby),
            view=self,
        )

    async def _on_role(self, interaction: discord.Interaction) -> None:
        chosen = self._role_sel.values[0]
        if chosen == "__none__":
            await interaction.response.defer()
            return
        self._pending_role = chosen
        self._refresh_selects()
        await interaction.response.edit_message(
            embed=_build_editor_overview_embed(self.guild_id, self.max_lobby),
            view=self,
        )

    async def _on_qty(self, interaction: discord.Interaction) -> None:
        chosen = self._qty_sel.values[0]
        if chosen == "__wait__":
            await interaction.response.defer()
            return

        qty     = int(chosen)
        role    = self._pending_role
        faction = self._faction

        override = _pending_role_overrides.setdefault(self.guild_id, {})
        entries  = override.setdefault(faction, [])
        for idx, (n, _) in enumerate(entries):
            if n == role:
                entries[idx] = (role, qty)
                break
        else:
            entries.append((role, qty))

        self._pending_role = None
        self._refresh_selects()
        await interaction.response.edit_message(
            embed=_build_editor_overview_embed(self.guild_id, self.max_lobby),
            view=self,
        )

    async def _on_remove(self, interaction: discord.Interaction) -> None:
        override = _pending_role_overrides.get(self.guild_id, {})
        entries  = override.get(self._faction, [])
        if entries:
            entries.pop()
        self._pending_role = None
        self._refresh_selects()
        await interaction.response.edit_message(
            embed=_build_editor_overview_embed(self.guild_id, self.max_lobby),
            view=self,
        )

    async def _on_clear(self, interaction: discord.Interaction) -> None:
        _pending_role_overrides.pop(self.guild_id, None)
        self._pending_role = None
        self._refresh_selects()
        await interaction.response.edit_message(
            embed=_build_editor_overview_embed(self.guild_id, self.max_lobby),
            view=self,
        )


# ══════════════════════════════════════════════════════════════════
# MAIN VIEW
# ══════════════════════════════════════════════════════════════════


class RoleMainView(View):
    """
    Main panel — 1 Select cố định, không rebuild.
    """

    def __init__(
        self,
        bot: commands.Bot,
        guild_id: str,
        cached_role_names: list[str] | None = None,
        max_lobby: int = 20,
    ) -> None:
        super().__init__(timeout=300)
        self.bot                = bot
        self.guild_id           = guild_id
        self.max_lobby          = max_lobby
        self._cached_role_names : list[str] | None = cached_role_names
        self._cached_role_map   : dict | None       = None

        override   = _pending_role_overrides.get(guild_id, {})
        edit_desc  = (
            "✏️ Đang có tuỳ chỉnh — nhấn để chỉnh sửa tiếp"
            if any(override.get(f) for f in _EDITOR_FACTIONS)
            else "Tuỳ chỉnh pool vai trò cho ván tiếp theo"
        )

        self._main_sel = Select(
            custom_id   = "main_action",
            placeholder = "🎭 Chọn thao tác...",
            options     = [
                discord.SelectOption(emoji="👥", label="Vai trò hiện tại",      value="current",
                                     description="Xem phân bổ vai trò từ kênh thoại"),
                discord.SelectOption(emoji="📊", label="Thống kê vai trò",      value="stats",
                                     description="Xem thống kê & tỉ lệ xuất hiện"),
                discord.SelectOption(emoji="📖", label="Thông tin vai trò",     value="info",
                                     description="Tra cứu chi tiết từng vai trò"),
                discord.SelectOption(emoji="🎪", label="Event Role",            value="event",
                                     description="Xem danh sách vai trò sự kiện"),
                discord.SelectOption(emoji="🔄", label="Quay lại vai trò mới",  value="reroll",
                                     description="Roll lại danh sách vai trò mới"),
                discord.SelectOption(emoji="🛠", label="Chỉnh sửa vai trò",     value="edit",
                                     description=edit_desc),
            ],
            row=0,
        )
        self._main_sel.callback = self._on_select  # type: ignore[method-assign]
        self.add_item(self._main_sel)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    async def _on_select(self, interaction: discord.Interaction) -> None:
        choice = self._main_sel.values[0]

        if choice == "current":
            await self._action_current(interaction)
        elif choice == "stats":
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(embed=_build_stats_embed(), ephemeral=True)
        elif choice == "info":
            faction = "Survivors"
            roles   = list(_FACTION_ROLES[faction])
            await interaction.response.send_message(
                embed=_build_role_info_embed(faction, 0, roles),
                view=RoleInfoView(faction, 0, roles),
                ephemeral=True,
            )
        elif choice == "event":
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(embed=_build_event_embed(), ephemeral=True)
        elif choice == "reroll":
            await self._action_reroll(interaction)
        elif choice == "edit":
            await self._action_edit(interaction)

    async def _action_current(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        members = _get_voice_members(interaction)
        if not members:
            await interaction.followup.send(
                "❌ Bạn phải ở trong một kênh thoại.", ephemeral=True)
            return
        player_count = len(members)
        if player_count < 5:
            await interaction.followup.send(
                f"❌ Cần ít nhất **5 người chơi**. Hiện có {player_count}.", ephemeral=True)
            return
        if self._cached_role_names:
            await interaction.followup.send(
                embed=_build_preview_embed(self._cached_role_names, player_count), ephemeral=True)
            return
        try:
            from bot import load_role_classes, _pending_role_maps  # type: ignore[import]
            s, a, u              = load_role_classes()
            role_names, role_map = _run_preview_distribution(player_count, s + a + u, members)
            _pending_role_maps[str(interaction.guild_id)] = role_map
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ Không thể tính toán vai trò.", ephemeral=True)
            return
        self._cached_role_names = role_names
        self._cached_role_map   = role_map
        await interaction.followup.send(
            embed=_build_preview_embed(role_names, player_count), ephemeral=True)

    async def _action_reroll(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        members      = _get_voice_members(interaction)
        player_count = len(members)
        embed = discord.Embed(
            title="🎭 QUẢN LÝ VAI TRÒ",
            description="Chọn thao tác bạn muốn thực hiện.",
            color=discord.Color.blurple(),
        )
        if player_count >= 5:
            try:
                from bot import load_role_classes, _pending_role_maps  # type: ignore[import]
                s, a, u              = load_role_classes()
                role_names, role_map = _run_preview_distribution(player_count, s + a + u, members)
                self._cached_role_names = role_names
                self._cached_role_map   = role_map
                _pending_role_maps[str(interaction.guild_id)] = role_map
                embed       = _build_preview_embed(role_names, player_count)
                embed.title = "🔄 VAI TRÒ SẼ ĐƯỢC PHÂN BỐ (Mới)"
            except Exception:
                traceback.print_exc()
        elif player_count > 0:
            embed.description = f"⚠️ Cần ít nhất **5 người**. Hiện có **{player_count}**."
        else:
            embed.description = "⚠️ Tham gia kênh thoại để xem phân bổ vai trò."
        new_view = RoleMainView(self.bot, self.guild_id, self._cached_role_names, self.max_lobby)
        new_view._cached_role_map = self._cached_role_map
        await interaction.followup.send(embed=embed, view=new_view, ephemeral=True)

    async def _action_edit(self, interaction: discord.Interaction) -> None:
        members   = _get_voice_members(interaction)
        max_lobby = max(len(members), 5) if members else self.max_lobby
        await interaction.response.send_message(
            embed=_build_editor_overview_embed(self.guild_id, max_lobby),
            view=RoleEditorView(self.bot, self.guild_id, max_lobby),
            ephemeral=True,
        )



# ══════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════


class RoleCog(commands.Cog):
    """Quản lý vai trò cho trò chơi Anomalies."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name        = "role",
        description = "Quản lý và xem phân bổ vai trò cho trò chơi",
    )
    @app_commands.guild_only()
    async def role_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title       = "🎭 VAI TRÒ CỦA GAME",
            description = "Chọn thao tác bạn muốn thực hiện.",
            color       = discord.Color.blurple(),
        )
        await interaction.response.send_message(
            embed=embed, view=RoleMainView(self.bot, str(interaction.guild_id))
        )


# ══════════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════════


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleCog(bot))
class RoleInfoView(View):
    """
    Faction Select + ◀ ▶ page buttons.
    Faction select change resets page to 0.
    Each page shows exactly one role from _ROLE_CATALOGUE.
    """

    def __init__(self, faction: str, page: int, roles: list[str]):
        super().__init__(timeout=300)
        self.faction = faction
        self.page    = page
        self.roles   = list(roles)
        self._rebuild_select()

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    def _rebuild_select(self) -> None:
        for item in list(self.children):
            if isinstance(item, Select):
                self.remove_item(item)
        options = [
            discord.SelectOption(
                label   = name,
                value   = value,
                emoji   = _FACTION_EMOJI[name],
                default = (name == self.faction),
            )
            for name, value in _FACTION_SELECT_VALUES.items()
        ]
        sel          = Select(placeholder="Chọn phe...", options=options[:25], row=0)
        sel.callback = self._faction_callback  # type: ignore[method-assign]
        self.add_item(sel)

    async def _faction_callback(self, interaction: discord.Interaction) -> None:
        self.faction = _VALUE_TO_FACTION[interaction.data["values"][0]]  # type: ignore[index]
        self.roles   = list(_FACTION_ROLES[self.faction])
        self.page    = 0
        self._rebuild_select()
        await interaction.response.edit_message(
            embed=_build_role_info_embed(self.faction, self.page, self.roles), view=self
        )

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev(self, interaction: discord.Interaction, button: Button) -> None:
        if not self.roles:
            await interaction.response.defer()
            return
        self.page = (self.page - 1) % len(self.roles)
        await interaction.response.edit_message(
            embed=_build_role_info_embed(self.faction, self.page, self.roles), view=self
        )

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction: discord.Interaction, button: Button) -> None:
        if not self.roles:
            await interaction.response.defer()
            return
        self.page = (self.page + 1) % len(self.roles)
        await interaction.response.edit_message(
            embed=_build_role_info_embed(self.faction, self.page, self.roles), view=self
        )


# ══════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════


class RoleCog(commands.Cog):
    """Quản lý vai trò cho trò chơi Anomalies."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name        = "role",
        description = "Quản lý và xem phân bổ vai trò cho trò chơi",
    )
    @app_commands.guild_only()
    async def role_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title       = "🎭 VAI TRÒ CỦA GAME",
            description = "Chọn thao tác bạn muốn thực hiện.",
            color       = discord.Color.blurple(),
        )
        await interaction.response.send_message(
            embed=embed, view=RoleMainView(self.bot, str(interaction.guild_id))
        )


# ══════════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════════


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleCog(bot))

# ══════════════════════════════════════════════════════════════════
# ROLE EDITOR — fixed custom_id, no rebuild(), state via edit_message
# ══════════════════════════════════════════════════════════════════

_EDITOR_FACTIONS = ["Survivors", "Anomalies", "Unknown Entities"]
_EDITOR_FACTION_EMOJI = {
    "Survivors":        "👥",
    "Anomalies":        "🐺",
    "Unknown Entities": "❓",
}

_ALL_META: dict[str, dict] = {
    **{k: {**v, "_faction": "Survivors"}        for k, v in SURVIVORS_META.items()},
    **{k: {**v, "_faction": "Anomalies"}        for k, v in ANOMALIES_META.items()},
    **{k: {**v, "_faction": "Unknown Entities"} for k, v in UNKNOWN_META.items()},
}


def _build_editor_overview_embed(guild_id: str, max_lobby: int) -> discord.Embed:
    override = _pending_role_overrides.get(guild_id, {})
    embed = discord.Embed(
        title="🛠 CHỈNH SỬA VAI TRÒ — Ván tiếp theo",
        color=discord.Color.orange(),
    )
    embed.set_footer(
        text=f"Lobby tối đa: {max_lobby} người  •  Danh sách tự reset sau ván."
    )
    has_any = any(override.get(f) for f in _EDITOR_FACTIONS)
    if not has_any:
        embed.description = (
            "Chưa có danh sách tuỳ chỉnh.\n"
            "➊ Chọn phe  ➋ Chọn vai trò  ➌ Chọn số lượng\n\n"
            "⚠️ Khi bật tuỳ chỉnh, **Distributor** sẽ bị bỏ qua."
        )
        return embed

    lines: list[str] = []
    total = 0
    for faction in _EDITOR_FACTIONS:
        entries = override.get(faction, [])
        if not entries:
            continue
        lines.append(f"**{_EDITOR_FACTION_EMOJI[faction]} {faction}**")
        for name, count in entries:
            lines.append(f"  • {name}  ×{count}")
            total += count
    lines.append(f"\n📊 Tổng: **{total}** vai trò")
    embed.description = "\n".join(lines)
    return embed


def _editor_role_options(faction: str, max_lobby: int, guild_id: str, pending: str) -> list[discord.SelectOption]:
    """Tạo options cho role select — luôn trả về ít nhất 1 option."""
    if faction == "Survivors":
        meta = SURVIVORS_META
    elif faction == "Anomalies":
        meta = ANOMALIES_META
    else:
        meta = UNKNOWN_META

    override  = _pending_role_overrides.get(guild_id, {})
    added_set = {name for name, _ in override.get(faction, [])}

    eligible = [
        name for name, m in meta.items()
        if m.get("min_players", 5) <= max_lobby
    ]

    if not eligible:
        return [discord.SelectOption(label="(Không có vai trò phù hợp)", value="__none__")]

    options = []
    for name in eligible[:25]:
        m = _ALL_META.get(name, {})
        options.append(discord.SelectOption(
            label       = name,
            value       = name,
            description = f"Tối thiểu {m.get('min_players',5)} người • Tối đa ×{m.get('max_count',1)}",
            emoji       = "✅" if name in added_set else None,
            default     = (name == pending),
        ))
    return options


def _editor_qty_options(role_name: str) -> list[discord.SelectOption]:
    m         = _ALL_META.get(role_name, {})
    max_count = max(1, min(m.get("max_count", 1), 9))
    return [
        discord.SelectOption(label=f"×{i}", value=str(i), description=f"Thêm {i} {role_name}")
        for i in range(1, max_count + 1)
    ]


class RoleEditorView(View):
    """
    Tuỳ chỉnh pool role — dùng custom_id CỐ ĐỊNH, không rebuild().

    Row 0: Select phe         (custom_id="editor_faction")
    Row 1: Select role        (custom_id="editor_role")
    Row 2: Select số lượng   (custom_id="editor_qty")  — disabled khi chưa chọn role
    Row 3: Nút Xoá cuối / Xoá tất cả

    Mỗi interaction chỉ gọi interaction.response.edit_message() để cập nhật
    options + disabled state — custom_id KHÔNG bao giờ thay đổi.
    """

    def __init__(self, bot: commands.Bot, guild_id: str, max_lobby: int = 20) -> None:
        super().__init__(timeout=600)
        self.bot          = bot
        self.guild_id     = guild_id
        self.max_lobby    = max_lobby
        self._faction     = "Survivors"
        self._pending_role: str | None = None

        # ── Row 0: Faction select ────────────────────────────────
        self._sel_faction = Select(
            custom_id   = "editor_faction",
            placeholder = "📂 Chọn phe...",
            options     = [
                discord.SelectOption(
                    emoji   = _EDITOR_FACTION_EMOJI[f],
                    label   = f,
                    value   = f,
                    default = (f == self._faction),
                )
                for f in _EDITOR_FACTIONS
            ],
            row = 0,
        )
        self._sel_faction.callback = self._on_faction  # type: ignore[method-assign]

        # ── Row 1: Role select ───────────────────────────────────
        self._sel_role = Select(
            custom_id   = "editor_role",
            placeholder = f"🎭 Chọn vai trò — {self._faction}",
            options     = _editor_role_options(self._faction, self.max_lobby, self.guild_id, ""),
            row         = 1,
        )
        self._sel_role.callback = self._on_role  # type: ignore[method-assign]

        # ── Row 2: Qty select ─────────────────────────────────────
        self._sel_qty = Select(
            custom_id   = "editor_qty",
            placeholder = "🔢 Chọn số lượng (chọn vai trò trước)",
            options     = [discord.SelectOption(label="—", value="__disabled__")],
            disabled    = True,
            row         = 2,
        )
        self._sel_qty.callback = self._on_qty  # type: ignore[method-assign]

        # ── Row 3: Buttons ────────────────────────────────────────
        self._btn_remove = Button(
            custom_id = "editor_remove",
            label     = "⬅ Xoá cuối",
            style     = discord.ButtonStyle.secondary,
            row       = 3,
        )
        self._btn_remove.callback = self._on_remove  # type: ignore[method-assign]

        self._btn_clear = Button(
            custom_id = "editor_clear",
            label     = "🗑 Xoá tất cả",
            style     = discord.ButtonStyle.danger,
            row       = 3,
        )
        self._btn_clear.callback = self._on_clear  # type: ignore[method-assign]

        self.add_item(self._sel_faction)
        self.add_item(self._sel_role)
        self.add_item(self._sel_qty)
        self.add_item(self._btn_remove)
        self.add_item(self._btn_clear)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    # ── Helpers ───────────────────────────────────────────────────

    def _sync_faction_select(self) -> None:
        self._sel_faction.options = [
            discord.SelectOption(
                emoji   = _EDITOR_FACTION_EMOJI[f],
                label   = f,
                value   = f,
                default = (f == self._faction),
            )
            for f in _EDITOR_FACTIONS
        ]
        self._sel_faction.placeholder = "📂 Chọn phe..."

    def _sync_role_select(self) -> None:
        self._sel_role.options     = _editor_role_options(
            self._faction, self.max_lobby, self.guild_id,
            self._pending_role or "",
        )
        self._sel_role.placeholder = f"🎭 Chọn vai trò — {_EDITOR_FACTION_EMOJI[self._faction]} {self._faction}"
        self._sel_role.disabled    = False

    def _sync_qty_select(self) -> None:
        if self._pending_role:
            self._sel_qty.options     = _editor_qty_options(self._pending_role)
            self._sel_qty.placeholder = f"🔢 Số lượng — {self._pending_role}"
            self._sel_qty.disabled    = False
        else:
            self._sel_qty.options     = [discord.SelectOption(label="—", value="__disabled__")]
            self._sel_qty.placeholder = "🔢 Chọn số lượng (chọn vai trò trước)"
            self._sel_qty.disabled    = True

    # ── Callbacks ─────────────────────────────────────────────────

    async def _on_faction(self, interaction: discord.Interaction) -> None:
        self._faction      = self._sel_faction.values[0]
        self._pending_role = None
        self._sync_faction_select()
        self._sync_role_select()
        self._sync_qty_select()
        await interaction.response.edit_message(
            embed = _build_editor_overview_embed(self.guild_id, self.max_lobby),
            view  = self,
        )

    async def _on_role(self, interaction: discord.Interaction) -> None:
        chosen = self._sel_role.values[0]
        if chosen == "__none__":
            await interaction.response.defer()
            return
        self._pending_role = chosen
        self._sync_role_select()
        self._sync_qty_select()
        await interaction.response.edit_message(
            embed = _build_editor_overview_embed(self.guild_id, self.max_lobby),
            view  = self,
        )

    async def _on_qty(self, interaction: discord.Interaction) -> None:
        chosen = self._sel_qty.values[0]
        if chosen == "__disabled__":
            await interaction.response.defer()
            return

        qty     = int(chosen)
        role    = self._pending_role
        faction = self._faction

        override = _pending_role_overrides.setdefault(self.guild_id, {})
        entries  = override.setdefault(faction, [])
        for idx, (n, _) in enumerate(entries):
            if n == role:
                entries[idx] = (role, qty)
                break
        else:
            entries.append((role, qty))

        self._pending_role = None
        self._sync_faction_select()
        self._sync_role_select()
        self._sync_qty_select()
        await interaction.response.edit_message(
            embed = _build_editor_overview_embed(self.guild_id, self.max_lobby),
            view  = self,
        )

    async def _on_remove(self, interaction: discord.Interaction) -> None:
        override = _pending_role_overrides.get(self.guild_id, {})
        entries  = override.get(self._faction, [])
        if entries:
            entries.pop()
        self._pending_role = None
        self._sync_faction_select()
        self._sync_role_select()
        self._sync_qty_select()
        await interaction.response.edit_message(
            embed = _build_editor_overview_embed(self.guild_id, self.max_lobby),
            view  = self,
        )

    async def _on_clear(self, interaction: discord.Interaction) -> None:
        _pending_role_overrides.pop(self.guild_id, None)
        self._pending_role = None
        self._sync_faction_select()
        self._sync_role_select()
        self._sync_qty_select()
        await interaction.response.edit_message(
            embed = _build_editor_overview_embed(self.guild_id, self.max_lobby),
            view  = self,
        )


# ══════════════════════════════════════════════════════════════════
# MAIN VIEW — fixed custom_id select
# ══════════════════════════════════════════════════════════════════


class RoleMainView(View):
    """
    Main panel — Select Menu với custom_id cố định.
    """

    def __init__(
        self,
        bot: commands.Bot,
        guild_id: str,
        cached_role_names: list[str] | None = None,
        max_lobby: int = 20,
    ) -> None:
        super().__init__(timeout=300)
        self.bot                = bot
        self.guild_id           = guild_id
        self.max_lobby          = max_lobby
        self._cached_role_names : list[str] | None = cached_role_names
        self._cached_role_map   : dict | None       = None

        override  = _pending_role_overrides.get(guild_id, {})
        edit_desc = (
            "✏️ Đang có tuỳ chỉnh — nhấn để chỉnh sửa"
            if any(override.get(f) for f in _EDITOR_FACTIONS)
            else "Tuỳ chỉnh pool vai trò cho ván tiếp theo"
        )

        sel = Select(
            custom_id   = "main_action",
            placeholder = "🎭 Chọn thao tác...",
            options     = [
                discord.SelectOption(emoji="👥", label="Vai trò hiện tại",
                                     value="current", description="Xem phân bổ từ kênh thoại"),
                discord.SelectOption(emoji="📊", label="Thống kê vai trò",
                                     value="stats",   description="Xem thống kê & tỉ lệ xuất hiện"),
                discord.SelectOption(emoji="📖", label="Thông tin vai trò",
                                     value="info",    description="Tra cứu chi tiết từng vai trò"),
                discord.SelectOption(emoji="🎪", label="Event Role",
                                     value="event",   description="Xem danh sách vai trò sự kiện"),
                discord.SelectOption(emoji="🔄", label="Quay lại vai trò mới",
                                     value="reroll",  description="Roll lại danh sách mới"),
                discord.SelectOption(emoji="🛠", label="Chỉnh sửa vai trò",
                                     value="edit",    description=edit_desc),
            ],
            row = 0,
        )
        sel.callback = self._on_select  # type: ignore[method-assign]
        self.add_item(sel)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    async def _on_select(self, interaction: discord.Interaction) -> None:
        choice = interaction.data["values"][0]  # type: ignore[index]
        if choice == "current":
            await self._action_current(interaction)
        elif choice == "stats":
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(embed=_build_stats_embed(), ephemeral=True)
        elif choice == "info":
            faction = "Survivors"
            roles   = list(_FACTION_ROLES[faction])
            await interaction.response.send_message(
                embed=_build_role_info_embed(faction, 0, roles),
                view=RoleInfoView(faction, 0, roles),
                ephemeral=True,
            )
        elif choice == "event":
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(embed=_build_event_embed(), ephemeral=True)
        elif choice == "reroll":
            await self._action_reroll(interaction)
        elif choice == "edit":
            await self._action_edit(interaction)

    async def _action_current(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        members = _get_voice_members(interaction)
        if not members:
            await interaction.followup.send(
                "❌ Bạn phải ở trong kênh thoại để xem phân bổ vai trò.", ephemeral=True
            )
            return
        player_count = len(members)
        if player_count < 5:
            await interaction.followup.send(
                f"❌ Cần ít nhất **5 người chơi**. Hiện có {player_count} người.", ephemeral=True
            )
            return
        if self._cached_role_names:
            await interaction.followup.send(
                embed=_build_preview_embed(self._cached_role_names, player_count), ephemeral=True
            )
            return
        try:
            from bot import load_role_classes, _pending_role_maps  # type: ignore[import]
            s, a, u              = load_role_classes()
            role_names, role_map = _run_preview_distribution(player_count, s + a + u, members)
            _pending_role_maps[str(interaction.guild_id)] = role_map
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ Không thể tính toán vai trò.", ephemeral=True)
            return
        self._cached_role_names = role_names
        self._cached_role_map   = role_map
        await interaction.followup.send(
            embed=_build_preview_embed(role_names, player_count), ephemeral=True
        )

    async def _action_reroll(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        members      = _get_voice_members(interaction)
        player_count = len(members)
        embed = discord.Embed(
            title="🎭 QUẢN LÝ VAI TRÒ",
            description="Chọn thao tác bạn muốn thực hiện.",
            color=discord.Color.blurple(),
        )
        if player_count >= 5:
            try:
                from bot import load_role_classes, _pending_role_maps  # type: ignore[import]
                s, a, u              = load_role_classes()
                role_names, role_map = _run_preview_distribution(player_count, s + a + u, members)
                self._cached_role_names = role_names
                self._cached_role_map   = role_map
                _pending_role_maps[str(interaction.guild_id)] = role_map
                embed       = _build_preview_embed(role_names, player_count)
                embed.title = "🔄 VAI TRÒ SẼ ĐƯỢC PHÂN BỐ (Mới)"
            except Exception:
                traceback.print_exc()
        elif player_count > 0:
            embed.description = f"⚠️ Cần ít nhất **5 người chơi**. Hiện có **{player_count}** người."
        else:
            embed.description = "⚠️ Tham gia kênh thoại để xem phân bổ vai trò."
        new_view = RoleMainView(self.bot, self.guild_id, self._cached_role_names, self.max_lobby)
        new_view._cached_role_map = self._cached_role_map
        await interaction.followup.send(embed=embed, view=new_view, ephemeral=True)

    async def _action_edit(self, interaction: discord.Interaction) -> None:
        members   = _get_voice_members(interaction)
        max_lobby = max(len(members), 5) if members else self.max_lobby
        await interaction.response.send_message(
            embed = _build_editor_overview_embed(self.guild_id, max_lobby),
            view  = RoleEditorView(self.bot, self.guild_id, max_lobby),
            ephemeral = True,
        )

class RoleInfoView(View):
    """
    Faction Select + ◀ ▶ page buttons.
    Faction select change resets page to 0.
    Each page shows exactly one role from _ROLE_CATALOGUE.
    """

    def __init__(self, faction: str, page: int, roles: list[str]):
        super().__init__(timeout=300)
        self.faction = faction
        self.page    = page
        self.roles   = list(roles)
        self._rebuild_select()

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    def _rebuild_select(self) -> None:
        for item in list(self.children):
            if isinstance(item, Select):
                self.remove_item(item)
        options = [
            discord.SelectOption(
                label   = name,
                value   = value,
                emoji   = _FACTION_EMOJI[name],
                default = (name == self.faction),
            )
            for name, value in _FACTION_SELECT_VALUES.items()
        ]
        sel          = Select(placeholder="Chọn phe...", options=options[:25], row=0)
        sel.callback = self._faction_callback  # type: ignore[method-assign]
        self.add_item(sel)

    async def _faction_callback(self, interaction: discord.Interaction) -> None:
        self.faction = _VALUE_TO_FACTION[interaction.data["values"][0]]  # type: ignore[index]
        self.roles   = list(_FACTION_ROLES[self.faction])
        self.page    = 0
        self._rebuild_select()
        await interaction.response.edit_message(
            embed=_build_role_info_embed(self.faction, self.page, self.roles), view=self
        )

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev(self, interaction: discord.Interaction, button: Button) -> None:
        if not self.roles:
            await interaction.response.defer()
            return
        self.page = (self.page - 1) % len(self.roles)
        await interaction.response.edit_message(
            embed=_build_role_info_embed(self.faction, self.page, self.roles), view=self
        )

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction: discord.Interaction, button: Button) -> None:
        if not self.roles:
            await interaction.response.defer()
            return
        self.page = (self.page + 1) % len(self.roles)
        await interaction.response.edit_message(
            embed=_build_role_info_embed(self.faction, self.page, self.roles), view=self
        )


# ══════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════


class RoleCog(commands.Cog):
    """Quản lý vai trò cho trò chơi Anomalies."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name        = "role",
        description = "Quản lý và xem phân bổ vai trò cho trò chơi",
    )
    @app_commands.guild_only()
    async def role_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title       = "🎭 VAI TRÒ CỦA GAME",
            description = "Chọn thao tác bạn muốn thực hiện.",
            color       = discord.Color.blurple(),
        )
        await interaction.response.send_message(
            embed=embed, view=RoleMainView(self.bot, str(interaction.guild_id))
        )


# ══════════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════════


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleCog(bot))
